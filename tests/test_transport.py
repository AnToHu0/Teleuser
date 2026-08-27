import asyncio

import pytest
from telethon import TelegramClient, errors, functions, types
from telethon.sessions import StringSession

from teleuser.errors import TeleuserError
from teleuser.request import ReadRequest
from teleuser.transport import ReadOnlyClient, TelegramService, public_error


@pytest.mark.parametrize(
    "rpc_request",
    [
        functions.messages.SendMessageRequest(peer=types.InputPeerSelf(), message="no"),
        functions.channels.JoinChannelRequest(channel=types.InputChannel(100, 123)),
        functions.messages.ImportChatInviteRequest(hash="invite"),
        functions.messages.DeleteMessagesRequest(id=[42]),
        functions.messages.SendReactionRequest(peer=types.InputPeerSelf(), msg_id=42),
        functions.messages.ReadHistoryRequest(peer=types.InputPeerSelf(), max_id=42),
        functions.InvokeWithoutUpdatesRequest(
            query=functions.messages.SendMessageRequest(
                peer=types.InputPeerSelf(), message="nested no"
            )
        ),
    ],
)
async def test_write_requests_are_blocked_at_transport_before_send(rpc_request, monkeypatch):
    async def forbidden(*args, **kwargs):
        pytest.fail("Write request reached Telegram transport")

    monkeypatch.setattr(TelegramClient, "_call", forbidden)
    client = ReadOnlyClient(StringSession(), 123, "a" * 32)
    with pytest.raises(TeleuserError) as error:
        await client._call(None, rpc_request)
    assert error.value.code == "READ_ONLY"


async def test_read_request_is_forwarded_and_mixed_batch_is_rejected_atomically(monkeypatch):
    forwarded = []

    async def recording(self, sender, request, **kwargs):
        forwarded.append(request)
        return "result"

    monkeypatch.setattr(TelegramClient, "_call", recording)
    client = ReadOnlyClient(StringSession(), 123, "a" * 32)
    read = functions.channels.GetMessagesRequest(channel=types.InputChannel(100, 123), id=[42])
    assert await client._call(None, read) == "result"
    assert forwarded == [read]
    with pytest.raises(TeleuserError):
        await client._call(None, [read, functions.messages.DeleteMessagesRequest(id=[42])])
    assert forwarded == [read]


async def test_real_connection_startup_does_not_fetch_account_wide_updates():
    sent = []

    class Sender:
        auth_key = None

        async def connect(self, connection):
            return True

        async def send(self, rpc, **kwargs):
            sent.append(rpc)
            inner = rpc
            while hasattr(inner, "query"):
                inner = inner.query
            if isinstance(inner, functions.help.GetConfigRequest):
                return None
            if isinstance(inner, functions.users.GetUsersRequest):
                return [types.User(id=55, is_self=True, bot=False, access_hash=99)]
            pytest.fail(f"Unexpected startup request: {type(inner).__name__}")

        def is_connected(self):
            return False

    client = ReadOnlyClient(StringSession(), 123, "a" * 32)
    client._sender = Sender()
    await client.connect()
    assert len(sent) == 2
    assert await client.is_user_authorized() is True
    await client._updates_handle
    await client._keepalive_handle


@pytest.mark.parametrize("authorized,fail", [(True, False), (False, False), (True, True)])
async def test_read_lifecycle_disconnects_and_never_implicitly_logs_in(
    monkeypatch, authorized, fail
):
    calls = []

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        async def connect(self):
            calls.append("connect")

        async def is_user_authorized(self):
            calls.append("authorized")
            return authorized

        async def get_me(self):
            calls.append("get_me")
            if fail:
                raise errors.FloodWaitError(request=None, capture=37)
            return types.User(id=55, username="reader")

        async def disconnect(self):
            calls.append("disconnect")

        async def start(self, *args, **kwargs):
            pytest.fail("Read command attempted interactive authentication")

    monkeypatch.setattr("teleuser.transport.ReadOnlyClient", Client)
    service = TelegramService({"session": "", "api_id": 123, "api_hash": "a" * 32})
    if authorized and not fail:
        result = await service.execute(ReadRequest(command="doctor"))
        assert result["authorized"] is True
        assert result["user_id"] == 55
    else:
        with pytest.raises((TeleuserError, errors.FloodWaitError)) as error:
            await service.execute(ReadRequest(command="doctor"))
        payload = public_error(error.value).as_dict()
        assert payload["code"] == ("FLOOD_WAIT" if authorized else "AUTH_REQUIRED")
        if authorized:
            assert payload["retry_after_seconds"] == 37
    assert calls == (
        ["connect", "authorized", "get_me", "disconnect"]
        if authorized
        else ["connect", "authorized", "disconnect"]
    )


@pytest.mark.parametrize("disconnect_error", [TimeoutError, OSError])
async def test_disconnect_failure_does_not_mask_authorization_failure(
    monkeypatch, disconnect_error
):
    class Client:
        def __init__(self, *args, **kwargs):
            pass

        async def connect(self):
            pass

        async def is_user_authorized(self):
            return False

        async def disconnect(self):
            raise disconnect_error

    monkeypatch.setattr("teleuser.transport.ReadOnlyClient", Client)
    service = TelegramService({"session": "", "api_id": 123, "api_hash": "a" * 32})

    with pytest.raises(TeleuserError) as error:
        await service.execute(ReadRequest(command="doctor"))

    assert error.value.code == "AUTH_REQUIRED"


@pytest.mark.parametrize("disconnect_error", [TimeoutError, OSError])
async def test_disconnect_failure_does_not_mask_successful_read(monkeypatch, disconnect_error):
    class Client:
        def __init__(self, *args, **kwargs):
            pass

        async def connect(self):
            pass

        async def is_user_authorized(self):
            return True

        async def get_me(self):
            return types.User(id=55, username="reader")

        async def disconnect(self):
            raise disconnect_error

    monkeypatch.setattr("teleuser.transport.ReadOnlyClient", Client)
    service = TelegramService({"session": "", "api_id": 123, "api_hash": "a" * 32})

    result = await service.execute(ReadRequest(command="doctor"))

    assert result == {"authorized": True, "user_id": 55, "username": "reader"}


async def test_read_disconnect_cancellation_propagates(monkeypatch):
    class Client:
        def __init__(self, *args, **kwargs):
            pass

        async def connect(self):
            pass

        async def is_user_authorized(self):
            return True

        async def get_me(self):
            return types.User(id=55, username="reader")

        async def disconnect(self):
            raise asyncio.CancelledError

    monkeypatch.setattr("teleuser.transport.ReadOnlyClient", Client)
    service = TelegramService({"session": "", "api_id": 123, "api_hash": "a" * 32})

    with pytest.raises(asyncio.CancelledError):
        await service.execute(ReadRequest(command="doctor"))
