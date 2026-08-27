import asyncio
import getpass
import re
import sys
import warnings

from telethon import errors
from telethon.sessions import StringSession

from .errors import TeleuserError
from .storage import load_credentials, save_credentials
from .transport import PassiveClient, client_options, disconnect_client


def _hidden_prompt(label):
    # getpass can fall back to echoing input when no terminal is available.
    # Treat that warning as a failure rather than exposing a login secret.
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        try:
            return getpass.getpass(label, stream=sys.stderr)
        except getpass.GetPassWarning as exc:
            raise TeleuserError(
                "INTERACTIVE_REQUIRED", "Нужен терминал с безопасным скрытым вводом."
            ) from exc


def _client(api_id, api_hash):
    return PassiveClient(StringSession(), api_id, api_hash, **client_options())


async def _network(operation):
    async with asyncio.timeout(30):
        return await operation


def status(*, root=None):
    try:
        load_credentials(root=root)
    except TeleuserError as exc:
        if exc.code == "AUTH_REQUIRED":
            return {"configured": False}
        raise
    return {"configured": True}


def _parameters(prompt):
    api_id = prompt("API ID (ввод скрыт): ").strip()
    api_hash = prompt("API hash (ввод скрыт): ").strip()
    phone = prompt("Номер отдельного reader с + и кодом страны (ввод скрыт): ").strip()
    if (
        not api_id.isascii()
        or not api_id.isdecimal()
        or not 0 < int(api_id) < 2**31
        or not re.fullmatch(r"[0-9a-fA-F]{32}", api_hash)
        or not re.fullmatch(r"\+[0-9]{7,15}", phone)
    ):
        raise TeleuserError("INVALID_ARGUMENT", "Проверьте формат API ID, API hash и номера.")
    return int(api_id), api_hash, phone


async def login(*, root=None, prompt=None, factory=None):
    if not sys.stdin.isatty() or not sys.stderr.isatty():
        raise TeleuserError(
            "INTERACTIVE_REQUIRED", "Запустите teleuser auth login сами в своём терминале."
        )
    if status(root=root)["configured"]:
        raise TeleuserError(
            "ALREADY_AUTHORIZED", "Сессия уже настроена; повторный вход не выполнен."
        )
    prompt = prompt or _hidden_prompt
    api_id, api_hash, phone = _parameters(prompt)
    client = (factory or _client)(api_id, api_hash)
    try:
        await _network(client.connect())
        sent = await _network(client.send_code_request(phone))
        code = prompt("Код Telegram (ввод скрыт): ").strip()
        try:
            await _network(
                client.sign_in(phone=phone, code=code, phone_code_hash=sent.phone_code_hash)
            )
        except errors.SessionPasswordNeededError:
            password = prompt("Пароль Telegram 2FA (ввод скрыт): ")
            await _network(client.sign_in(password=password))
        me = await _network(client.get_me())
        if not me or me.bot:
            raise TeleuserError("USER_ACCOUNT_REQUIRED", "Нужна сессия пользовательского аккаунта.")
        save_credentials(
            {"api_id": api_id, "api_hash": api_hash, "session": client.session.save()},
            root=root,
        )
        return {"authorized": True, "user_id": me.id, "username": me.username}
    finally:
        await disconnect_client(client)
