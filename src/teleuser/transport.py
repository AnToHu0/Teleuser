import asyncio

from telethon import TelegramClient, errors, functions, utils
from telethon.sessions import StringSession

from . import __version__
from .errors import TeleuserError
from .service import ReadService

# These are explicit protocol reads, plus authorization transfer needed to read
# files from another Telegram DC. No general RPC escape hatch is exposed by CLI.
READ_REQUESTS = frozenset(
    {
        functions.contacts.ResolveUsernameRequest,
        functions.channels.GetChannelsRequest,
        functions.channels.GetMessagesRequest,
        functions.messages.GetHistoryRequest,
        functions.messages.SearchRequest,
        functions.messages.GetRepliesRequest,
        functions.messages.GetDiscussionMessageRequest,
        functions.messages.GetMessagesRequest,
        functions.users.GetUsersRequest,
        functions.updates.GetStateRequest,
        functions.help.GetConfigRequest,
        functions.help.GetCdnConfigRequest,
        functions.upload.GetFileRequest,
        functions.upload.GetCdnFileRequest,
        functions.upload.GetFileHashesRequest,
        functions.upload.GetCdnFileHashesRequest,
        functions.upload.ReuploadCdnFileRequest,
        functions.auth.ExportAuthorizationRequest,
        functions.auth.ImportAuthorizationRequest,
    }
)
WRAPPERS = frozenset(
    {
        functions.InvokeWithoutUpdatesRequest,
        functions.InvokeWithLayerRequest,
        functions.InitConnectionRequest,
    }
)


def _check_request(request):
    if type(request) in WRAPPERS:
        _check_request(request.query)
    elif type(request) not in READ_REQUESTS:
        raise TeleuserError("READ_ONLY", "Этот Telegram RPC не разрешён в режиме чтения.")


class PassiveClient(TelegramClient):
    """No account-wide inbox sync, including the implicit Telethon login sync."""

    async def _on_login(self, user):
        # Telethon 1.44's implementation also calls updates.getDifference, even
        # with receive_updates=False. We only need the identity for this command.
        self._mb_entity_cache.set_self_user(user.id, user.bot, user.access_hash)
        self._authorized = True
        return user

    async def _update_loop(self):
        # No event handlers or inbox: this CLI executes one explicit request.
        return


class ReadOnlyClient(PassiveClient):
    async def _call(self, sender, request, ordered=False, flood_sleep_threshold=None):
        # Downloads use _call directly. Checking __call__ alone misses that path.
        # Validate a whole batch before allowing even its first read to be sent.
        if utils.is_list_like(request):
            request = list(request)
            for item in request:
                _check_request(item)
        else:
            _check_request(request)
        return await super()._call(
            sender, request, ordered=ordered, flood_sleep_threshold=flood_sleep_threshold
        )


def client_options():
    return {
        "device_model": "Teleuser reader",
        "app_version": __version__,
        "receive_updates": False,
        "catch_up": False,
        "flood_sleep_threshold": 0,
        "request_retries": 1,
        "connection_retries": 1,
        "retry_delay": 1,
        "timeout": 15,
        "auto_reconnect": False,
        "raise_last_call_error": True,
    }


async def disconnect_client(client):
    """Best-effort cleanup that never hides an operation result or error."""
    try:
        async with asyncio.timeout(10):
            await client.disconnect()
    except Exception:
        # The CLI process is about to exit. Cancellation is a BaseException and
        # still propagates; ordinary cleanup failures must not rewrite the result.
        pass


class TelegramService:
    def __init__(self, credentials):
        self.credentials = credentials

    async def execute(self, request):
        try:
            session = StringSession(self.credentials["session"])
        except (ValueError, TypeError) as exc:
            raise TeleuserError("INVALID_CREDENTIALS", "Локальная сессия повреждена.") from exc
        client = ReadOnlyClient(
            session, self.credentials["api_id"], self.credentials["api_hash"], **client_options()
        )
        try:
            async with asyncio.timeout(120):
                await client.connect()
                if not await client.is_user_authorized():
                    raise TeleuserError("AUTH_REQUIRED", "Сессия не авторизована или отозвана.")
                return await ReadService(client).execute(request)
        finally:
            await disconnect_client(client)


def public_error(exc):
    """Never echo exception text: RPCs, paths and auth errors may contain secrets."""
    if isinstance(exc, TeleuserError):
        return exc
    if isinstance(
        exc,
        (
            errors.FloodWaitError,
            errors.FloodPremiumWaitError,
            errors.FloodTestPhoneWaitError,
            errors.SlowModeWaitError,
        ),
    ):
        return TeleuserError(
            "FLOOD_WAIT",
            "Telegram просит подождать; автоматического повтора нет.",
            retry_after_seconds=exc.seconds,
        )
    if isinstance(exc, (errors.UnauthorizedError, errors.AuthKeyError, errors.AuthKeyNotFound)):
        return TeleuserError("AUTH_REQUIRED", "Telegram-сессия недействительна или отозвана.")
    if isinstance(
        exc,
        (
            errors.PhoneCodeInvalidError,
            errors.PhoneCodeExpiredError,
            errors.PasswordHashInvalidError,
            errors.PhoneNumberInvalidError,
            errors.ApiIdInvalidError,
        ),
    ):
        return TeleuserError("LOGIN_FAILED", "Проверьте API-ключи, номер, код или пароль входа.")
    if isinstance(
        exc,
        (
            errors.ChannelPrivateError,
            errors.ChatAdminRequiredError,
            errors.UserBannedInChannelError,
        ),
    ):
        return TeleuserError("ACCESS_DENIED", "Аккаунт не имеет доступа к выбранному источнику.")
    if isinstance(exc, (errors.UsernameInvalidError, errors.UsernameNotOccupiedError)):
        return TeleuserError("SOURCE_NOT_FOUND", "Публичный источник не найден.")
    if isinstance(exc, errors.MsgIdInvalidError):
        return TeleuserError("MESSAGE_NOT_FOUND", "Сообщение или ветка отсутствует или недоступна.")
    if isinstance(exc, (TimeoutError, errors.TimedOutError)):
        return TeleuserError("TIMEOUT", "Истекло время запроса; операция остановлена.")
    if isinstance(exc, (ConnectionError, OSError)):
        return TeleuserError("IO_ERROR", "Ошибка подключения или локального хранилища.")
    if isinstance(exc, errors.RPCError):
        return TeleuserError("TELEGRAM_ERROR", "Telegram отклонил запрос.")
    return TeleuserError("INTERNAL_ERROR", "Внутренняя ошибка; секреты и детали запроса скрыты.")
