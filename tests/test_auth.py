import asyncio
import inspect
import sys
from types import SimpleNamespace

import pytest
from telethon import TelegramClient, errors

from teleuser import storage
from teleuser.auth import login, status
from teleuser.errors import TeleuserError
from teleuser.storage import load_credentials


class LoginClient:
    def __init__(self, *, two_factor=False, failure=None, bot=False):
        self.calls = []
        self.two_factor = two_factor
        self.failure = failure
        self.bot = bot
        self.session = SimpleNamespace(save=lambda: "test-session-not-a-real-secret")

    async def connect(self):
        self.calls.append("connect")

    async def disconnect(self):
        self.calls.append("disconnect")

    async def send_code_request(self, phone):
        self.calls.append(("code", phone))
        if isinstance(self.failure, errors.FloodWaitError):
            raise self.failure
        return SimpleNamespace(phone_code_hash="sent-code-hash")

    async def sign_in(self, **kwargs):
        self.calls.append(("sign_in", kwargs))
        if self.failure:
            raise self.failure
        if self.two_factor and "password" not in kwargs:
            raise errors.SessionPasswordNeededError(request=None)
        return SimpleNamespace(id=12345, username="test_reader", bot=self.bot)

    async def get_me(self):
        return SimpleNamespace(id=12345, username="test_reader", bot=self.bot)


def test_auth_api_has_no_profile_selector():
    assert "profile" not in inspect.signature(login).parameters
    assert "profile" not in inspect.signature(status).parameters


def interactive(monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("sys.stderr.isatty", lambda: True)


@pytest.mark.parametrize("two_factor", [False, True])
async def test_login_persists_only_authorized_session_with_code_and_optional_2fa(
    tmp_path, monkeypatch, capsys, two_factor
):
    interactive(monkeypatch)
    client = LoginClient(two_factor=two_factor)
    answers = iter(["123", "a" * 32, "+15550001111", "12345", "test-2fa"])
    constructed = []

    def factory(api_id, api_hash):
        constructed.append((api_id, api_hash))
        return client

    result = await login(root=tmp_path / "state", prompt=lambda _: next(answers), factory=factory)
    assert constructed == [(123, "a" * 32)]
    assert result == {"authorized": True, "user_id": 12345, "username": "test_reader"}
    assert client.calls[0] == "connect"
    assert client.calls[-1] == "disconnect"
    assert ("code", "+15550001111") in client.calls
    assert (
        "sign_in",
        {"phone": "+15550001111", "code": "12345", "phone_code_hash": "sent-code-hash"},
    ) in client.calls
    assert (("sign_in", {"password": "test-2fa"}) in client.calls) is two_factor
    stored = load_credentials(root=tmp_path / "state")
    assert stored == {
        "api_id": 123,
        "api_hash": "a" * 32,
        "session": "test-session-not-a-real-secret",
    }
    assert capsys.readouterr() == ("", "")


async def test_default_windows_login_uses_credential_manager_without_reader_file(
    tmp_path, monkeypatch
):
    interactive(monkeypatch)
    client = LoginClient()
    answers = iter(["123", "a" * 32, "+15550001111", "12345"])
    saved = []

    monkeypatch.setattr(storage, "_is_windows", lambda: True)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))

    def load_windows():
        if not saved:
            raise TeleuserError("AUTH_REQUIRED", "not configured")
        return saved[0]

    monkeypatch.setattr(storage, "_load_windows_credentials", load_windows)
    monkeypatch.setattr(storage, "_save_windows_credentials", lambda value: saved.append(value))

    result = await login(prompt=lambda _: next(answers), factory=lambda *_: client)

    assert result["authorized"] is True
    assert saved == [
        {
            "api_id": 123,
            "api_hash": "a" * 32,
            "session": "test-session-not-a-real-secret",
        }
    ]
    assert not (storage.state_dir() / "reader.json").exists()


@pytest.mark.parametrize("stdin_tty,stderr_tty", [(False, True), (True, False), (False, False)])
async def test_login_without_human_terminal_never_prompts_or_connects(
    tmp_path, monkeypatch, stdin_tty, stderr_tty
):
    monkeypatch.setattr("sys.stdin.isatty", lambda: stdin_tty)
    monkeypatch.setattr("sys.stderr.isatty", lambda: stderr_tty)

    def forbidden(*args):
        pytest.fail("Noninteractive login reached credentials or network")

    with pytest.raises(TeleuserError) as error:
        await login(root=tmp_path / "state", prompt=forbidden, factory=forbidden)
    assert error.value.code == "INTERACTIVE_REQUIRED"
    assert not (tmp_path / "state").exists()


@pytest.mark.parametrize("two_factor", [False, True])
async def test_default_login_uses_hidden_prompts_on_stderr_only(
    tmp_path, monkeypatch, capsys, caplog, two_factor
):
    interactive(monkeypatch)
    client = LoginClient(two_factor=two_factor)
    answers = iter(["123", "a" * 32, "+15550001111", "12345", "test-2fa"])
    prompts = []

    def hidden_prompt(label, *, stream):
        assert stream is sys.stderr
        prompts.append(label)
        return next(answers)

    def forbidden(*args):
        pytest.fail("Secrets must not be entered with echoing input()")

    monkeypatch.setattr("getpass.getpass", hidden_prompt)
    monkeypatch.setattr("builtins.input", forbidden)
    result = await login(root=tmp_path / "state", factory=lambda *_: client)
    assert result["authorized"] is True
    assert len(prompts) == (5 if two_factor else 4)
    captured = capsys.readouterr()
    assert captured.out == ""
    for secret in ("a" * 32, "+15550001111", "12345", "test-2fa", "test-session"):
        assert secret not in captured.out + captured.err + caplog.text


@pytest.mark.parametrize(
    "failure",
    [errors.FloodWaitError(request=None, capture=37), errors.PhoneCodeInvalidError(request=None)],
)
async def test_failed_login_disconnects_without_persisting(tmp_path, monkeypatch, failure):
    interactive(monkeypatch)
    client = LoginClient(failure=failure)
    answers = iter(["123", "a" * 32, "+15550001111", "12345"])
    with pytest.raises(type(failure)):
        await login(
            root=tmp_path / "state", prompt=lambda _: next(answers), factory=lambda *_: client
        )
    assert client.calls[-1] == "disconnect"
    assert not (tmp_path / "state" / "reader.json").exists()


async def test_login_rejects_bot_session_before_saving(tmp_path, monkeypatch):
    interactive(monkeypatch)
    client = LoginClient(bot=True)
    answers = iter(["123", "a" * 32, "+15550001111", "12345"])
    with pytest.raises(TeleuserError) as error:
        await login(
            root=tmp_path / "state", prompt=lambda _: next(answers), factory=lambda *_: client
        )
    assert error.value.code == "USER_ACCOUNT_REQUIRED"
    assert client.calls[-1] == "disconnect"
    assert not (tmp_path / "state" / "reader.json").exists()


@pytest.mark.parametrize("disconnect_error", [TimeoutError, OSError])
async def test_successful_login_is_not_masked_by_disconnect_failure(
    tmp_path, monkeypatch, disconnect_error
):
    interactive(monkeypatch)
    client = LoginClient()

    async def timeout():
        client.calls.append("disconnect")
        raise disconnect_error

    client.disconnect = timeout
    answers = iter(["123", "a" * 32, "+15550001111", "12345"])

    result = await login(
        root=tmp_path / "state", prompt=lambda _: next(answers), factory=lambda *_: client
    )

    assert result == {"authorized": True, "user_id": 12345, "username": "test_reader"}
    assert client.calls[-1] == "disconnect"
    assert load_credentials(root=tmp_path / "state")["session"] == (
        "test-session-not-a-real-secret"
    )


@pytest.mark.parametrize("disconnect_error", [TimeoutError, OSError])
async def test_disconnect_failure_does_not_mask_login_failure(
    tmp_path, monkeypatch, disconnect_error
):
    interactive(monkeypatch)
    failure = errors.PhoneCodeInvalidError(request=None)
    client = LoginClient(failure=failure)

    async def timeout():
        raise disconnect_error

    client.disconnect = timeout
    answers = iter(["123", "a" * 32, "+15550001111", "12345"])

    with pytest.raises(errors.PhoneCodeInvalidError):
        await login(
            root=tmp_path / "state", prompt=lambda _: next(answers), factory=lambda *_: client
        )

    assert not (tmp_path / "state" / "reader.json").exists()


async def test_login_disconnect_cancellation_propagates(tmp_path, monkeypatch):
    interactive(monkeypatch)
    client = LoginClient()

    async def cancelled():
        raise asyncio.CancelledError

    client.disconnect = cancelled
    answers = iter(["123", "a" * 32, "+15550001111", "12345"])

    with pytest.raises(asyncio.CancelledError):
        await login(
            root=tmp_path / "state", prompt=lambda _: next(answers), factory=lambda *_: client
        )


async def test_existing_login_is_not_replaced_or_reauthorized(tmp_path, monkeypatch):
    interactive(monkeypatch)
    from teleuser.storage import save_credentials

    root = tmp_path / "state"
    previous = {"api_id": 123, "api_hash": "a" * 32, "session": "previous-session"}
    save_credentials(previous, root=root)

    def forbidden(*args):
        pytest.fail("Existing login caused an unnecessary login attempt")

    with pytest.raises(TeleuserError) as error:
        await login(root=root, prompt=forbidden, factory=forbidden)
    assert error.value.code == "ALREADY_AUTHORIZED"
    assert load_credentials(root=root) == previous


def test_status_is_offline_and_does_not_return_secrets(tmp_path, monkeypatch, capsys, caplog):
    from teleuser.storage import save_credentials

    async def forbidden(*args, **kwargs):
        pytest.fail("Offline status accessed Telegram")

    monkeypatch.setattr(TelegramClient, "connect", forbidden)
    monkeypatch.setattr(TelegramClient, "send_code_request", forbidden)
    root = tmp_path / "state"
    assert status(root=root) == {"configured": False}
    save_credentials({"api_id": 123, "api_hash": "a" * 32, "session": "test-session"}, root=root)
    assert status(root=root) == {"configured": True}
    captured = capsys.readouterr()
    assert "a" * 32 not in captured.out + captured.err + caplog.text
    assert "test-session" not in captured.out + captured.err + caplog.text
