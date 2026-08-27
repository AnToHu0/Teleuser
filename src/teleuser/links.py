"""Parse Telegram references without opening URLs or accepting action links."""

import re
import unicodedata
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlsplit

from .errors import TeleuserError

USERNAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,31}\Z")
RESERVED = {
    "s",
    "c",
    "joinchat",
    "share",
    "addlist",
    "login",
    "proxy",
    "socks",
    "iv",
    "bg",
    "setlanguage",
    "addstickers",
    "addemoji",
    "confirmphone",
    "contact",
    "boost",
    "giftcode",
    "invoice",
    "m",
    "nft",
    "a",
}


def invalid():
    return TeleuserError(
        "INVALID_TARGET",
        "Нужен @username или однозначная ссылка https://t.me/... на канал, сообщение "
        "или комментарий. Приглашения и ссылки-действия не поддерживаются.",
    )


def positive_id(value: str) -> int:
    if not re.fullmatch(r"[1-9][0-9]{0,9}", value) or int(value) > 2**31 - 1:
        raise invalid()
    return int(value)


@dataclass(frozen=True)
class Target:
    peer: str | int
    message_id: int | None = None
    thread_id: int | None = None
    comment_id: int | None = None

    @property
    def private(self) -> bool:
        return isinstance(self.peer, int)

    @property
    def url(self) -> str:
        base = f"https://t.me/c/{self.peer}" if self.private else f"https://t.me/{self.peer}"
        if self.thread_id and self.message_id:
            base += f"/{self.thread_id}"
        if self.message_id:
            base += f"/{self.message_id}"
        if self.comment_id:
            base += f"?comment={self.comment_id}"
        return base


def _query(value):
    pairs = parse_qsl(value, keep_blank_values=True, max_num_fields=8)
    query = dict(pairs)
    if len(query) != len(pairs) or query.keys() - {"thread", "comment", "single", "t"}:
        raise invalid()
    if "single" in query and query["single"]:
        raise invalid()
    if "t" in query and not re.fullmatch(r"[0-9hms:]{1,32}", query["t"]):
        raise invalid()
    return query


def parse_target(value: str) -> Target:
    if (
        not value
        or len(value) > 2048
        or any(c.isspace() or unicodedata.category(c).startswith("C") for c in value)
    ):
        raise invalid()
    bare = value.removeprefix("@")
    if USERNAME.fullmatch(bare) and bare.lower() not in RESERVED:
        return Target(peer=bare.lower())
    if value.startswith(("t.me/", "telegram.me/")):
        value = "https://" + value
    try:
        url = urlsplit(value)
        if (
            url.scheme != "https"
            or url.netloc.lower() not in {"t.me", "telegram.me"}
            or url.fragment
            or "%" in url.path
            or "//" in url.path
        ):
            raise invalid()
        parts = url.path.strip("/").split("/")
        if parts[0] == "s":
            parts = parts[1:]
        if not parts:
            raise invalid()
        if parts[0] == "c":
            if len(parts) not in (3, 4) or not re.fullmatch(r"[1-9][0-9]{0,15}", parts[1]):
                raise invalid()
            peer = int(parts[1])
            rest = parts[2:]
        else:
            peer = parts[0].lower()
            if not USERNAME.fullmatch(peer) or peer in RESERVED or len(parts) > 3:
                raise invalid()
            rest = parts[1:]
        ids = [positive_id(part) for part in rest]
        query = _query(url.query)
        thread = positive_id(query["thread"]) if "thread" in query else None
        comment = positive_id(query["comment"]) if "comment" in query else None
        if len(ids) == 2:
            if thread is not None and thread != ids[0]:
                raise invalid()
            thread = ids[0]
        if thread is not None and comment is not None:
            raise invalid()
        if not ids and query:
            raise invalid()
        return Target(peer, ids[-1] if ids else None, thread, comment)
    except (ValueError, IndexError) as exc:
        raise invalid() from exc
