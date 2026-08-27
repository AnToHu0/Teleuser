import argparse
import asyncio
import json
import logging
import sys
import unicodedata

from . import __version__
from .errors import TeleuserError
from .help import DETAILS, OVERVIEW
from .links import parse_target
from .request import ReadRequest, parse_date, validate_request


class Parser(argparse.ArgumentParser):
    def error(self, message):
        # argparse may otherwise echo a mistakenly supplied secret back to stdout/stderr.
        raise TeleuserError(
            "INVALID_ARGUMENT", f"Некорректные аргументы. Справка: {self.prog} --help."
        )


def build_parser():
    parser = Parser(
        prog="teleuser",
        description=OVERVIEW,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        allow_abbrev=False,
    )
    parser.add_argument("--version", action="store_true", help="version as JSON")
    commands = parser.add_subparsers(dest="command")
    for name in ("resolve", "message", "history", "search", "replies", "media", "doctor", "auth"):
        sub = commands.add_parser(
            name,
            description=DETAILS[name],
            formatter_class=argparse.RawDescriptionHelpFormatter,
            allow_abbrev=False,
        )
        if name not in {"doctor", "auth"}:
            sub.add_argument("target", help="@username or a t.me link")
        if name in {"history", "search", "replies"}:
            sub.add_argument("--limit", type=int, default=20, help="1–100; default 20")
            sub.add_argument("--before", type=int, help="exclusive message ID cursor")
            sub.add_argument("--since", type=parse_date, help="inclusive lower date bound")
            sub.add_argument("--until", type=parse_date, help="exclusive upper date bound")
        if name == "search":
            sub.add_argument("--query", required=True, help="Telegram search query")
        if name == "message":
            sub.add_argument(
                "--context", type=int, default=0, help="0–20 neighboring messages on each side"
            )
        if name == "media":
            sub.add_argument("--max-mib", type=int, default=20, help="1–100 MiB; default 20")
        if name == "auth":
            auth_commands = sub.add_subparsers(dest="auth_command", required=True)
            for operation in ("login", "status"):
                auth_commands.add_parser(
                    operation,
                    description=DETAILS[operation],
                    formatter_class=argparse.RawDescriptionHelpFormatter,
                    allow_abbrev=False,
                )
    return parser


def _request(args):
    target = parse_target(args.target) if hasattr(args, "target") else None
    request = ReadRequest(
        command=args.command,
        target=target,
        limit=getattr(args, "limit", 20),
        before=getattr(args, "before", None),
        since=getattr(args, "since", None),
        until=getattr(args, "until", None),
        query=getattr(args, "query", None),
        context=getattr(args, "context", 0),
        max_bytes=getattr(args, "max_mib", 20) * 1024 * 1024,
    )
    validate_request(request)
    if target and target.private:
        raise TeleuserError("PRIVATE_SOURCE", "Reader открывает только публичные источники.")
    return request


def _default_credentials():
    from .storage import load_credentials

    return load_credentials()


def _default_service(credentials):
    from .transport import TelegramService

    return TelegramService(credentials)


def _emit(payload):
    # Keep non-ASCII Unicode compact, but escape terminal/bidi controls and
    # lone surrogates. json.loads restores the original content without rewriting it.
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    print(
        "".join(
            json.dumps(char)[1:-1] if unicodedata.category(char) in {"Cc", "Cf", "Cs"} else char
            for char in encoded
        )
    )


def _error(exc):
    if isinstance(exc, TeleuserError):
        return exc
    from .transport import public_error

    return public_error(exc)


def run(argv=None, *, credential_loader=None, service_factory=None):
    logging.getLogger("telethon").setLevel(logging.CRITICAL)
    try:
        args = build_parser().parse_args(argv)
        if args.version:
            _emit({"ok": True, "version": __version__})
            return 0
        if not args.command:
            raise TeleuserError("INVALID_ARGUMENT", "Нужна команда; справка: teleuser --help.")
        if args.command == "auth":
            from .auth import login, status

            result = asyncio.run(login()) if args.auth_command == "login" else status()
        else:
            request = _request(args)
            credentials = (credential_loader or _default_credentials)()
            service = (service_factory or _default_service)(credentials)
            result = asyncio.run(service.execute(request))
        _emit(
            {
                "ok": True,
                "untrusted": args.command not in {"auth", "doctor"},
                "data": result,
            }
        )
        return 0
    except SystemExit as exc:
        return int(exc.code or 0)
    except (KeyboardInterrupt, EOFError):
        _emit({"ok": False, "error": {"code": "CANCELLED", "message": "Операция отменена."}})
        return 130
    except Exception as exc:
        error = _error(exc)
        _emit({"ok": False, "error": error.as_dict()})
        return 2 if error.code in {"INVALID_ARGUMENT", "INVALID_TARGET"} else 1


def main():
    raise SystemExit(run(sys.argv[1:]))
