from dataclasses import dataclass
from datetime import UTC, datetime

from .errors import TeleuserError
from .links import Target


@dataclass(frozen=True)
class ReadRequest:
    command: str
    target: Target | None = None
    limit: int = 20
    before: int | None = None
    since: datetime | None = None
    until: datetime | None = None
    query: str | None = None
    context: int = 0
    max_bytes: int = 20 * 1024 * 1024


def parse_date(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
        if len(value) == 10:
            return parsed.replace(tzinfo=UTC)
        if parsed.tzinfo is None:
            raise ValueError("timezone required")
        return parsed.astimezone(UTC)
    except ValueError as exc:
        raise TeleuserError(
            "INVALID_ARGUMENT",
            "Дата: YYYY-MM-DD (полночь UTC) или ISO8601 с часовым поясом.",
        ) from exc


def validate_request(request: ReadRequest) -> None:
    if request.command in {"message", "replies", "media"} and (
        request.target is None or request.target.message_id is None
    ):
        raise TeleuserError("INVALID_TARGET", "Для этой команды нужна ссылка на сообщение.")
    if not 1 <= request.limit <= 100 or not 0 <= request.context <= 20:
        raise TeleuserError("INVALID_ARGUMENT", "limit: 1–100; context: 0–20.")
    if request.before is not None and not 1 <= request.before <= 2**31 - 1:
        raise TeleuserError("INVALID_ARGUMENT", "before должен быть положительным ID сообщения.")
    if request.since and request.until and request.since >= request.until:
        raise TeleuserError("INVALID_ARGUMENT", "since должен быть раньше until.")
    if request.command == "search" and (
        not request.query or not request.query.strip() or len(request.query) > 1024
    ):
        raise TeleuserError("INVALID_ARGUMENT", "Нужен непустой поисковый запрос до 1024 символов.")
    if not 1 <= request.max_bytes <= 100 * 1024 * 1024:
        raise TeleuserError("INVALID_ARGUMENT", "Максимальный размер вложения: от 1 до 100 MiB.")
