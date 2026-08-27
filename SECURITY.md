# Security policy

## Reporting a vulnerability

Do not post Telegram API credentials, login codes, phone numbers, session strings, the
contents of `reader.json`, or the Teleuser Windows credential in a public issue.

Use GitHub private vulnerability reporting when it is enabled for the repository. If it is not
available, open a public issue containing no exploit details or secrets and ask the maintainer
for a private contact channel.

If a Teleuser session may have been exposed, revoke it immediately in the official Telegram
client under **Settings → Devices**. Then delete `~/.local/share/teleuser/reader.json` on
macOS/Linux, or remove the `Teleuser` generic credential for account `reader` in Windows
Credential Manager. Removing local storage without revoking the Telegram session is not
sufficient.

## Supported versions

Security fixes are applied to the latest release and the default branch. Teleuser depends on
pinned Telethon internals for its read-only RPC boundary, so dependency upgrades require a new
transport review rather than an automatic version bump.
