import inspect
import json
import stat
from pathlib import Path

import pytest

from teleuser import storage
from teleuser.errors import TeleuserError
from teleuser.storage import load_credentials, save_credentials, save_download

CREDS = {"api_id": 123, "api_hash": "a" * 32, "session": "test-session"}


def test_credentials_api_has_no_profile_selector():
    assert "profile" not in inspect.signature(load_credentials).parameters
    assert "profile" not in inspect.signature(save_credentials).parameters


def test_windows_default_credentials_use_os_store_and_local_app_data(tmp_path, monkeypatch):
    saved = []
    monkeypatch.setattr(storage, "_is_windows", lambda: True)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    monkeypatch.setattr(storage, "_save_windows_credentials", lambda value: saved.append(value))
    monkeypatch.setattr(storage, "_load_windows_credentials", lambda: CREDS)

    save_credentials(CREDS)

    assert saved == [CREDS]
    assert load_credentials() == CREDS
    assert storage.state_dir() == tmp_path / "LocalAppData" / "Teleuser"
    assert not (storage.state_dir() / "reader.json").exists()


def test_posix_default_credentials_keep_private_file_backend(tmp_path, monkeypatch):
    home = tmp_path / "home"
    root = home / ".local" / "share" / "teleuser"
    monkeypatch.setattr(storage, "_is_windows", lambda: False)
    monkeypatch.setattr(storage.Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(
        storage,
        "_save_windows_credentials",
        lambda *_: pytest.fail("POSIX default reached Windows Credential Manager"),
    )
    monkeypatch.setattr(
        storage,
        "_load_windows_credentials",
        lambda: pytest.fail("POSIX default reached Windows Credential Manager"),
    )

    save_credentials(CREDS)

    assert load_credentials() == CREDS
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    assert stat.S_IMODE((root / "reader.json").stat().st_mode) == 0o600


def test_explicit_root_keeps_file_backend_when_windows_store_is_default(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "_is_windows", lambda: True)
    monkeypatch.delattr(storage.os, "getuid")
    monkeypatch.delattr(storage.os, "O_NOFOLLOW")
    monkeypatch.setattr(
        storage,
        "_save_windows_credentials",
        lambda *_: pytest.fail("Explicit root reached Windows Credential Manager"),
    )
    monkeypatch.setattr(
        storage,
        "_load_windows_credentials",
        lambda: pytest.fail("Explicit root reached Windows Credential Manager"),
    )

    root = tmp_path / "state"
    save_credentials(CREDS, root=root)

    assert load_credentials(root=root) == CREDS
    assert (root / "reader.json").is_file()


async def test_windows_download_does_not_require_posix_primitives(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "_is_windows", lambda: True)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    monkeypatch.delattr(storage.os, "getuid")
    monkeypatch.delattr(storage.os, "O_NOFOLLOW")

    root = storage.state_dir() / "downloads"
    result = await save_download(chunks(b"abc", b"def"), root=root, max_bytes=10)
    path = Path(result["path"])

    assert path.parent == root
    assert path.name.startswith("attachment-")
    assert path.suffix == ".bin"
    assert path.read_bytes() == b"abcdef"
    assert result["bytes"] == 6
    assert len(result["sha256"]) == 64

    existing = root / "existing.bin"
    existing.write_bytes(b"preserve")
    with pytest.raises(TeleuserError) as error:
        await save_download(chunks(b"12345", b"67890"), root=root, max_bytes=7)
    assert error.value.code == "MEDIA_TOO_LARGE"
    assert existing.read_bytes() == b"preserve"
    assert sorted(item.name for item in root.iterdir()) == sorted([path.name, existing.name])


def test_credentials_are_private_and_never_overwritten_silently(tmp_path):
    root = tmp_path / "state"
    save_credentials(CREDS, root=root)
    assert load_credentials(root=root) == CREDS
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    assert stat.S_IMODE((root / "reader.json").stat().st_mode) == 0o600
    with pytest.raises(TeleuserError) as error:
        save_credentials({**CREDS, "session": "other"}, root=root)
    assert error.value.code == "ALREADY_AUTHORIZED"
    assert load_credentials(root=root) == CREDS


def test_credentials_reject_symlink_and_world_readable_file(tmp_path):
    root = tmp_path / "state"
    root.mkdir(mode=0o700)
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps(CREDS))
    outside.chmod(0o600)
    path = root / "reader.json"
    path.symlink_to(outside)
    with pytest.raises(TeleuserError) as error:
        load_credentials(root=root)
    assert error.value.code == "UNSAFE_STORAGE"
    path.unlink()
    path.write_text(json.dumps(CREDS))
    path.chmod(0o644)
    with pytest.raises(TeleuserError) as error:
        load_credentials(root=root)
    assert error.value.code == "UNSAFE_STORAGE"


async def chunks(*values):
    for value in values:
        yield value


async def test_download_uses_inert_generated_name_and_exact_bytes(tmp_path):
    result = await save_download(chunks(b"abc", b"def"), root=tmp_path / "files", max_bytes=10)
    path = Path(result["path"])
    assert path.suffix == ".bin"
    assert path.read_bytes() == b"abcdef"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert result["bytes"] == 6
    assert len(result["sha256"]) == 64
    second = await save_download(chunks(b"second"), root=tmp_path / "files", max_bytes=10)
    second_path = Path(second["path"])
    assert path != second_path
    assert path.parent == second_path.parent == tmp_path / "files"
    assert path.read_bytes() == b"abcdef"
    assert second_path.read_bytes() == b"second"


async def test_download_over_limit_removes_only_partial_file(tmp_path):
    root = tmp_path / "files"
    root.mkdir(mode=0o700)
    existing = root / "existing.bin"
    existing.write_bytes(b"preserve")
    with pytest.raises(TeleuserError) as error:
        await save_download(chunks(b"12345", b"67890"), root=root, max_bytes=7)
    assert error.value.code == "MEDIA_TOO_LARGE"
    assert list(root.iterdir()) == [existing]
    assert existing.read_bytes() == b"preserve"


async def test_download_does_not_follow_directory_symlink(tmp_path):
    destination = tmp_path / "outside"
    destination.mkdir(mode=0o700)
    root = tmp_path / "files"
    root.symlink_to(destination, target_is_directory=True)
    with pytest.raises(TeleuserError) as error:
        await save_download(chunks(b"data"), root=root, max_bytes=10)
    assert error.value.code == "UNSAFE_STORAGE"
    assert list(destination.iterdir()) == []
