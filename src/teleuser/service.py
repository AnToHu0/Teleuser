from dataclasses import dataclass

from telethon import functions, types, utils

from .errors import TeleuserError
from .request import ReadRequest, validate_request
from .storage import private_dir, save_download, state_dir


def _iso(value):
    return value.isoformat() if value else None


def _url(entity, message_id):
    username = getattr(entity, "username", None)
    base = f"https://t.me/{username}" if username else f"https://t.me/c/{entity.id}"
    return f"{base}/{message_id}"


def _thread(message):
    reply = message.reply_to
    return (
        (getattr(reply, "reply_to_top_id", None) or getattr(reply, "reply_to_msg_id", None))
        if reply
        else None
    )


def _source(entity):
    return {
        "id": entity.id,
        "username": getattr(entity, "username", None),
        "title": entity.title,
        "kind": "channel" if getattr(entity, "broadcast", False) else "group",
    }


def _serialize(message, entity, url=None):
    file = message.file
    reply = message.reply_to
    return {
        "id": message.id,
        "url": url or _url(entity, message.id),
        "date": _iso(message.date),
        "edited_at": _iso(message.edit_date),
        "text": message.message or "",
        "author_signature": message.post_author,
        "sender_id": utils.get_peer_id(message.from_id) if message.from_id else None,
        "reply_to_id": getattr(reply, "reply_to_msg_id", None),
        "thread_id": _thread(message),
        "grouped_id": message.grouped_id,
        "media": None
        if not file
        else {
            "name": file.name,
            "mime_type": file.mime_type,
            "bytes": file.size,
        },
        "service_message": message.action is not None,
        "protected": bool(message.noforwards or getattr(entity, "noforwards", False)),
    }


@dataclass(frozen=True)
class Location:
    entity: object
    message_id: int
    thread_id: int | None = None
    post_url: str | None = None
    no_replies: bool = False

    def url(self, message):
        if self.post_url and message.id != self.thread_id:
            return f"{self.post_url}?comment={message.id}"
        return _url(self.entity, message.id)


class ReadService:
    def __init__(self, client):
        self.client = client

    async def execute(self, request: ReadRequest):
        validate_request(request)
        if request.command == "doctor":
            me = await self.client.get_me()
            if not me:
                raise TeleuserError("AUTH_REQUIRED", "Telegram-сессия не авторизована.")
            return {"authorized": True, "user_id": me.id, "username": me.username}
        target = request.target
        if target.private:
            raise TeleuserError("PRIVATE_SOURCE", "reader не открывает приватные ссылки.")
        try:
            entity = await self.client.get_entity(target.peer)
        except ValueError as exc:
            raise TeleuserError("SOURCE_NOT_FOUND", "Источник не найден или недоступен.") from exc
        if not isinstance(entity, types.Channel):
            raise TeleuserError(
                "UNSUPPORTED_PEER", "Поддерживаются публичные каналы и супергруппы."
            )
        if request.command == "resolve":
            return {"source": _source(entity), "url": target.url}
        if request.command in {"history", "search"}:
            thread = self._history_thread(entity, request)
            return await self._page(entity, request, thread=thread)
        location = await self._locate(entity, target, discussion=request.command == "replies")
        if request.command == "replies":
            if location.no_replies:
                return {
                    "source": _source(location.entity),
                    "thread_id": None,
                    "messages": [],
                    "has_more": False,
                    "next_before": None,
                    "since": _iso(request.since),
                    "until": _iso(request.until),
                }
            return await self._page(
                location.entity,
                request,
                thread=location.thread_id or location.message_id,
                location=location,
            )
        message = await self._message(location)
        if request.command == "media":
            return await self._media(location, message, request)
        return await self._message_context(location, message, request.context)

    def _history_thread(self, entity, request):
        target = request.target
        if target.comment_id:
            raise TeleuserError("INVALID_TARGET", "Для комментариев используйте replies.")
        thread = target.thread_id or target.message_id
        if thread and not entity.forum:
            raise TeleuserError("INVALID_TARGET", "Для истории канала используйте @username.")
        if thread and request.command == "search":
            raise TeleuserError("UNSUPPORTED_FILTER", "Поиск внутри темы пока не поддерживается.")
        return thread

    async def _discussion(self, entity, post_id):
        response = await self.client(
            functions.messages.GetDiscussionMessageRequest(peer=entity, msg_id=post_id)
        )
        for message in response.messages:
            origin = message.fwd_from
            if (
                origin
                and origin.channel_post == post_id
                and isinstance(origin.from_id, types.PeerChannel)
                and origin.from_id.channel_id == entity.id
                and isinstance(message.peer_id, types.PeerChannel)
                and message.peer_id.channel_id != entity.id
            ):
                linked = next(
                    (
                        chat
                        for chat in response.chats
                        if isinstance(chat, types.Channel) and chat.id == message.peer_id.channel_id
                    ),
                    None,
                )
                if linked:
                    return Location(linked, message.id, message.id, _url(entity, post_id))
        raise TeleuserError(
            "DISCUSSION_UNAVAILABLE", "Не удалось получить связанную ветку обсуждения."
        )

    async def _locate(self, entity, target, *, discussion):
        if target.comment_id or (discussion and entity.broadcast):
            post = await self.client.get_messages(entity, ids=target.message_id)
            if not post:
                raise TeleuserError(
                    "MESSAGE_NOT_FOUND", "Исходный пост отсутствует или недоступен."
                )
            # A known absence is distinct from an inaccessible linked discussion.
            if not target.comment_id and post.replies is None:
                return Location(entity, target.message_id, no_replies=True)
            location = await self._discussion(entity, target.message_id)
            if target.comment_id and not discussion:
                return Location(
                    location.entity, target.comment_id, location.thread_id, location.post_url
                )
            return location
        return Location(entity, target.message_id, target.thread_id)

    async def _message(self, location):
        message = await self.client.get_messages(location.entity, ids=location.message_id)
        if not message or isinstance(message, types.MessageEmpty):
            raise TeleuserError("MESSAGE_NOT_FOUND", "Сообщение отсутствует или недоступно.")
        if (
            location.thread_id
            and message.id != location.thread_id
            and _thread(message) != location.thread_id
        ):
            raise TeleuserError("COMMENT_MISMATCH", "Сообщение не принадлежит выбранной ветке.")
        return message

    async def _page(self, entity, request, *, thread=None, location=None):
        params = {"limit": request.limit + 1, "offset_id": request.before or 0}
        if request.until:
            params["offset_date"] = request.until
        if request.query is not None:
            params["search"] = request.query
        if thread:
            params["reply_to"] = thread
        messages = []
        scanned = 0
        last_id = None
        reached_since = False
        async for message in self.client.iter_messages(entity, **params):
            scanned += 1
            last_id = message.id
            if request.since and message.date < request.since:
                reached_since = True
                break
            if request.until and message.date >= request.until:
                continue
            messages.append(message)
        selected = messages[: request.limit]
        if len(messages) > request.limit:
            next_before = selected[-1].id
        elif scanned == request.limit + 1 and not reached_since:
            # Telegram may prioritize offset_id over offset_date. A full raw
            # page filtered to zero matches still needs a continuation cursor.
            next_before = last_id
        else:
            next_before = None
        return {
            "source": _source(entity),
            "thread_id": thread,
            "messages": [
                _serialize(m, entity, location.url(m) if location else None) for m in selected
            ],
            "has_more": next_before is not None,
            "next_before": next_before,
            "since": _iso(request.since),
            "until": _iso(request.until),
        }

    async def _neighbors(self, location, message, count, *, after=False):
        params = {"limit": count, "offset_id": message.id, "reverse": after}
        if location.thread_id:
            params["reply_to"] = location.thread_id
        neighbors = [m async for m in self.client.iter_messages(location.entity, **params)]
        return [
            _serialize(m, location.entity, location.url(m))
            for m in sorted(neighbors, key=lambda m: m.id)
        ]

    async def _reply(self, location, message):
        reply = message.reply_to
        reply_id = getattr(reply, "reply_to_msg_id", None)
        if not reply_id:
            return None
        peer = getattr(reply, "reply_to_peer_id", None)
        if peer and utils.get_peer_id(peer) != utils.get_peer_id(location.entity):
            return {"id": reply_id, "status": "outside_scope"}
        parent = await self.client.get_messages(location.entity, ids=reply_id)
        if not parent or isinstance(parent, types.MessageEmpty):
            return {"id": reply_id, "status": "unavailable"}
        return {
            "status": "available",
            "message": _serialize(parent, location.entity, location.url(parent)),
        }

    async def _message_context(self, location, message, count):
        return {
            "source": _source(location.entity),
            "message": _serialize(message, location.entity, location.url(message)),
            "reply": await self._reply(location, message),
            "context_before": await self._neighbors(location, message, count) if count else [],
            "context_after": await self._neighbors(location, message, count, after=True)
            if count
            else [],
        }

    async def _media(self, location, message, request):
        if (
            message.noforwards
            or getattr(location.entity, "noforwards", False)
            or message.ttl_period
            or getattr(message.media, "ttl_seconds", None)
        ):
            raise TeleuserError(
                "PROTECTED_CONTENT", "Защищённые и исчезающие вложения не скачиваются."
            )
        file = message.file
        if not file or not (message.photo or message.document):
            raise TeleuserError("NO_MEDIA", "В сообщении нет поддерживаемого фото или документа.")
        if file.size is not None and file.size > request.max_bytes:
            raise TeleuserError(
                "MEDIA_TOO_LARGE", "Вложение превышает выбранный предел.", bytes=file.size
            )
        private_dir(state_dir())
        root = private_dir(state_dir() / "downloads")
        result = await save_download(
            self.client.iter_download(message.media), root=root, max_bytes=request.max_bytes
        )
        return {**result, "mime_type": file.mime_type, "url": location.url(message)}
