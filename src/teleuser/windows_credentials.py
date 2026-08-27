"""Windows Credential Manager adapter, imported only for the default Windows store."""

import json

from .errors import TeleuserError
from .storage import _validate_credentials

SERVICE = "Teleuser"
ACCOUNT = "reader"


def _default_backend():
    try:
        import keyring
        from keyring.backends.Windows import WinVaultKeyring

        backend = keyring.get_keyring()
    except Exception as exc:
        raise TeleuserError("UNSAFE_STORAGE", "Windows Credential Manager недоступен.") from exc
    if not isinstance(backend, WinVaultKeyring):
        raise TeleuserError("UNSAFE_STORAGE", "Нужен системный Windows Credential Manager.")
    return backend


def _read(backend):
    try:
        return backend.get_password(SERVICE, ACCOUNT)
    except Exception as exc:
        raise TeleuserError(
            "UNSAFE_STORAGE", "Не удалось безопасно прочитать Windows credential."
        ) from exc


def load_credentials(*, backend=None):
    value = _read(backend or _default_backend())
    if value is None:
        raise TeleuserError(
            "AUTH_REQUIRED", "Сначала выполните в своём терминале: teleuser auth login."
        )
    try:
        return _validate_credentials(json.loads(value))
    except (ValueError, UnicodeError, TypeError) as exc:
        raise TeleuserError(
            "INVALID_CREDENTIALS", "Не удалось прочитать настройку сессии."
        ) from exc


def save_credentials(credentials, *, backend=None):
    credentials = _validate_credentials(credentials)
    backend = backend or _default_backend()
    if _read(backend) is not None:
        raise TeleuserError(
            "ALREADY_AUTHORIZED", "Сессия уже настроена; существующая запись не перезаписана."
        )
    value = json.dumps(credentials, ensure_ascii=True, separators=(",", ":"))
    try:
        backend.set_password(SERVICE, ACCOUNT, value)
    except Exception as exc:
        raise TeleuserError(
            "UNSAFE_STORAGE", "Не удалось безопасно сохранить Windows credential."
        ) from exc
