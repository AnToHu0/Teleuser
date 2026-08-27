import json

import pytest

from teleuser import windows_credentials
from teleuser.errors import TeleuserError
from teleuser.windows_credentials import load_credentials, save_credentials

CREDS = {"api_id": 123, "api_hash": "a" * 32, "session": "test-session"}


class Backend:
    def __init__(self, value=None, get_failure=None, set_failure=None):
        self.value = value
        self.get_failure = get_failure
        self.set_failure = set_failure
        self.writes = []

    def get_password(self, service, account):
        if self.get_failure:
            raise self.get_failure("secret backend detail")
        assert (service, account) == ("Teleuser", "reader")
        return self.value

    def set_password(self, service, account, value):
        if self.set_failure:
            raise self.set_failure("secret backend detail")
        assert (service, account) == ("Teleuser", "reader")
        self.writes.append(value)
        self.value = value


def test_windows_credentials_round_trip_without_overwrite():
    backend = Backend()

    save_credentials(CREDS, backend=backend)

    assert len(backend.writes) == 1
    serialized = backend.writes[0]
    assert json.loads(serialized) == CREDS
    fresh_backend = Backend(value=serialized)
    assert load_credentials(backend=fresh_backend) == CREDS
    with pytest.raises(TeleuserError) as error:
        save_credentials({**CREDS, "session": "replacement"}, backend=fresh_backend)
    assert error.value.code == "ALREADY_AUTHORIZED"
    assert fresh_backend.writes == []
    assert load_credentials(backend=fresh_backend) == CREDS


def test_windows_credentials_default_path_uses_keyring_backend(monkeypatch):
    backend = Backend()
    monkeypatch.setattr(windows_credentials, "_default_backend", lambda: backend)

    save_credentials(CREDS)

    assert len(backend.writes) == 1
    serialized = backend.writes[0]
    assert json.loads(serialized) == CREDS
    assert load_credentials() == CREDS


INVALID_VALUES = [
    {},
    {"api_id": True, "api_hash": "a" * 32, "session": "test-session"},
    {"api_id": 123, "api_hash": "short", "session": "test-session"},
    {"api_id": 123, "api_hash": "a" * 32, "session": ""},
    {**CREDS, "extra": "field"},
]


@pytest.mark.parametrize(
    "value",
    [None, "not-json", "[]", *(json.dumps(value) for value in INVALID_VALUES)],
)
def test_windows_credentials_fail_closed_for_missing_or_malformed_load(value):
    with pytest.raises(TeleuserError) as error:
        load_credentials(backend=Backend(value))
    assert error.value.code == ("AUTH_REQUIRED" if value is None else "INVALID_CREDENTIALS")
    payload = json.dumps(error.value.as_dict())
    for secret in (CREDS["api_hash"], CREDS["session"], "secret"):
        assert secret not in payload


@pytest.mark.parametrize("value", INVALID_VALUES)
def test_windows_credentials_reject_invalid_save_without_backend_write(value):
    backend = Backend()

    with pytest.raises(TeleuserError) as error:
        save_credentials(value, backend=backend)

    assert error.value.code == "INVALID_CREDENTIALS"
    assert backend.writes == []
    payload = json.dumps(error.value.as_dict())
    for secret in (CREDS["api_hash"], CREDS["session"], "secret"):
        assert secret not in payload


@pytest.mark.parametrize(
    "backend,operation",
    [
        (Backend(get_failure=RuntimeError), "load"),
        (Backend(get_failure=RuntimeError), "save"),
        (Backend(set_failure=RuntimeError), "save"),
    ],
)
def test_windows_backend_errors_are_redacted(backend, operation):
    action = (
        (lambda: load_credentials(backend=backend))
        if operation == "load"
        else (lambda: save_credentials(CREDS, backend=backend))
    )

    with pytest.raises(TeleuserError) as error:
        action()

    assert error.value.code == "UNSAFE_STORAGE"
    payload = json.dumps(error.value.as_dict())
    for secret in ("secret backend detail", CREDS["api_hash"], CREDS["session"]):
        assert secret not in payload


def test_windows_existing_credential_error_does_not_disclose_replacement():
    backend = Backend(value=json.dumps(CREDS))
    replacement = {**CREDS, "session": "replacement-secret"}

    with pytest.raises(TeleuserError) as error:
        save_credentials(replacement, backend=backend)

    payload = json.dumps(error.value.as_dict())
    assert error.value.code == "ALREADY_AUTHORIZED"
    for secret in (CREDS["api_hash"], CREDS["session"], "replacement-secret"):
        assert secret not in payload
    assert backend.writes == []
