import hashlib
import json
import os
import re
import stat
import tempfile
from pathlib import Path

from .errors import TeleuserError


def _is_windows() -> bool:
    return os.name == "nt"


def state_dir() -> Path:
    if _is_windows():
        base = os.environ.get("LOCALAPPDATA")
        return (Path(base) if base else Path.home() / "AppData" / "Local") / "Teleuser"
    return Path.home() / ".local" / "share" / "teleuser"


def _is_link_or_reparse(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    attributes = getattr(info, "st_file_attributes", 0)
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return stat.S_ISLNK(info.st_mode) or bool(attributes & reparse)


def private_dir(path: Path) -> Path:
    path = path.absolute()
    if any(_is_link_or_reparse(parent) for parent in (path, *path.parents)):
        raise TeleuserError("UNSAFE_STORAGE", "Каталог данных не может быть символьной ссылкой.")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.stat()
    unsafe_posix = not _is_windows() and (info.st_uid != os.getuid() or info.st_mode & 0o077)
    if not stat.S_ISDIR(info.st_mode):
        raise TeleuserError("UNSAFE_STORAGE", "Путь данных должен быть каталогом.")
    if unsafe_posix:
        raise TeleuserError(
            "UNSAFE_STORAGE", "Каталог данных должен принадлежать вам и иметь права 0700."
        )
    return path


def _validate_credentials(value):
    if (
        not isinstance(value, dict)
        or set(value) != {"api_id", "api_hash", "session"}
        or type(value["api_id"]) is not int
        or not 0 < value["api_id"] < 2**31
        or not isinstance(value["api_hash"], str)
        or not re.fullmatch(r"[0-9a-fA-F]{32}", value["api_hash"])
        or not isinstance(value["session"], str)
        or not 1 <= len(value["session"]) <= 8192
    ):
        raise TeleuserError("INVALID_CREDENTIALS", "Локальная настройка сессии повреждена.")
    return value


def _load_windows_credentials():
    from .windows_credentials import load_credentials

    return load_credentials()


def _save_windows_credentials(credentials):
    from .windows_credentials import save_credentials

    save_credentials(credentials)


def load_credentials(*, root: Path | None = None):
    if root is None and _is_windows():
        return _validate_credentials(_load_windows_credentials())
    root = root or state_dir()
    if not root.exists():
        raise TeleuserError(
            "AUTH_REQUIRED", "Сначала выполните в своём терминале: teleuser auth login."
        )
    root = private_dir(root)
    try:
        path = root / "reader.json"
        if _is_link_or_reparse(path):
            raise TeleuserError("UNSAFE_STORAGE", "Нельзя безопасно открыть файл сессии.")
        flags = os.O_RDONLY | (0 if _is_windows() else os.O_NOFOLLOW)
        fd = os.open(path, flags)
    except FileNotFoundError as exc:
        raise TeleuserError("AUTH_REQUIRED", "Сначала выполните: teleuser auth login.") from exc
    except OSError as exc:
        raise TeleuserError("UNSAFE_STORAGE", "Нельзя безопасно открыть файл сессии.") from exc
    with os.fdopen(fd, "r") as handle:
        info = os.fstat(handle.fileno())
        unsafe_posix = not _is_windows() and (info.st_uid != os.getuid() or info.st_mode & 0o077)
        if not stat.S_ISREG(info.st_mode) or unsafe_posix or info.st_size > 16384:
            raise TeleuserError(
                "UNSAFE_STORAGE", "Файл сессии должен быть обычным файлом с правами 0600."
            )
        try:
            return _validate_credentials(json.load(handle))
        except (ValueError, UnicodeError) as exc:
            raise TeleuserError(
                "INVALID_CREDENTIALS", "Не удалось прочитать настройку сессии."
            ) from exc


def save_credentials(credentials, *, root: Path | None = None):
    credentials = _validate_credentials(credentials)
    if root is None and _is_windows():
        _save_windows_credentials(credentials)
        return
    root = private_dir(root or state_dir())
    path = root / "reader.json"
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if not _is_windows():
            flags |= os.O_NOFOLLOW
        fd = os.open(path, flags, 0o600)
    except FileExistsError as exc:
        raise TeleuserError(
            "ALREADY_AUTHORIZED", "Сессия уже настроена; существующий файл не перезаписан."
        ) from exc
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(credentials, handle)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


async def save_download(chunks, *, root: Path, max_bytes: int):
    root = private_dir(root)
    fd, name = tempfile.mkstemp(prefix="attachment-", suffix=".bin", dir=root)
    path = Path(name)
    digest = hashlib.sha256()
    size = 0
    try:
        with os.fdopen(fd, "wb") as handle:
            async for chunk in chunks:
                size += len(chunk)
                if size > max_bytes:
                    raise TeleuserError("MEDIA_TOO_LARGE", "Вложение превысило выбранный предел.")
                handle.write(chunk)
                digest.update(chunk)
        return {"path": str(path), "bytes": size, "sha256": digest.hexdigest()}
    except BaseException:
        path.unlink(missing_ok=True)
        raise
