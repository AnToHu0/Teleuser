import pytest

from teleuser.errors import TeleuserError
from teleuser.links import parse_target


@pytest.mark.parametrize(
    ("value", "peer", "message", "thread", "comment"),
    [
        ("@example", "example", None, None, None),
        ("example", "example", None, None, None),
        ("https://t.me/example/42", "example", 42, None, None),
        ("https://t.me/s/example/42", "example", 42, None, None),
        ("https://t.me/example/10/42", "example", 42, 10, None),
        ("https://t.me/example/42?comment=99", "example", 42, None, 99),
        ("https://t.me/c/123456/10/42", 123456, 42, 10, None),
        ("t.me/example/42?thread=10&single", "example", 42, 10, None),
    ],
)
def test_parses_supported_telegram_targets(value, peer, message, thread, comment):
    target = parse_target(value)
    assert (target.peer, target.message_id, target.thread_id, target.comment_id) == (
        peer,
        message,
        thread,
        comment,
    )


@pytest.mark.parametrize(
    "value",
    [
        "https://t.me.evil.test/example/1",
        "https://t.me@evil.test/example/1",
        "https://evil@t.me/example/1",
        "http://t.me/example/1",
        "file:///etc/passwd",
        "https://t.me/+invite",
        "https://t.me/joinchat/secret",
        "https://t.me/share/url",
        "https://t.me/example/0",
        "https://t.me/example/-1",
        "https://t.me/example/nope",
        "https://t.me/example/1?comment=2&comment=3",
        "https://t.me/example/10/42?thread=11",
        "https://t.me/example/10/42?comment=99",
        "https://t.me/example/42?thread=10&comment=99",
        "https://t.me/example/1?start=execute",
        "@example\n--format json",
        "https://t.me/example/1/2/3",
        "https://t.me/c/0/1",
        "https://t.me:443/example/1",
        "https://t.me/example/%31",
        "https://t.me/example/1#instructions",
        "https://t.me/example/0/42",
        "https://t.me/example/-2/42",
        "https://t.me/example/1?thread=0",
        "https://t.me/example/1?thread=-2",
        "https://t.me/example/1?comment=0",
        "https://t.me/example/1?comment=-2",
        "https://t.me/example/1?thread=2&thread=3",
        "https://t.me/exam\nple/42",
        "https://t.me/exam\rple/42",
        "https://t.me/exam\tple/42",
    ],
)
def test_rejects_ambiguous_or_action_targets(value):
    with pytest.raises(TeleuserError) as error:
        parse_target(value)
    assert error.value.code == "INVALID_TARGET"
