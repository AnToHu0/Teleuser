# Teleuser

Give your AI agent read-only access to public Telegram channels, posts, comments, and
search.

Instead of copying Telegram content into a chat, send your agent a `t.me` link or ask
it to research a public channel. The included Teleuser skill chooses the appropriate
CLI commands, retrieves a bounded set of messages through a separate Telegram reader
account, and treats everything it receives as untrusted source material.

```text
You → AI agent → Teleuser skill → teleuser CLI → Telegram MTProto
```

Teleuser uses a regular Telegram user session because bots cannot freely inspect
arbitrary public channel history. The agent does not receive a general-purpose
Telegram client: the CLI exposes a small allowlisted set of read operations and has no
commands for sending messages, reacting, joining groups, or changing account state.

Python 3.12+, Telethon, and a compact, portable Agent Skill. No MCP server, public
endpoint, or background channel collection. Teleuser targets macOS, Linux, and
Windows. The Windows implementation should work, but it has not yet been verified on
a native Windows machine.

## Quick start

Give your local coding agent this repository or its URL and ask:

> Install Teleuser from this repository for the agent harness you are currently
> running in. Follow AGENTS.md, install or update both the CLI and the portable
> Teleuser skill for my user account without touching unrelated skills, verify the
> installation, then tell me when I need to run `teleuser auth login` myself. Never
> ask me to paste Telegram credentials or login codes into chat.

The root [AGENTS.md](AGENTS.md) contains the installation and safety instructions an
agent needs. The source skill lives at [skills/teleuser](skills/teleuser/SKILL.md) and
uses the [open Agent Skills format](https://agentskills.io/specification). The installer
agent selects the correct user-level skill directory for its own harness. Documented
targets include [Codex](https://developers.openai.com/codex/skills),
[Claude Code](https://code.claude.com/docs/en/slash-commands), and
[OpenCode](https://opencode.ai/docs/skills); another local harness can use the same
skill if it supports Agent Skills and shell commands.

The agent may install and verify the software, but **you must perform Telegram sign-in
yourself in a terminal**. Never send API credentials, login codes, passwords, phone
numbers, or session files to an agent.

## Complete Telegram sign-in

Create a separate regular Telegram account for reading public sources and sign in to
it with an official Telegram client. Use a user account, not a bot token.

Obtain your own `api_id` and `api_hash` under **API development tools** at
[my.telegram.org](https://my.telegram.org). These identify your application; see
[Telegram's official instructions](https://core.telegram.org/api/obtaining_api_id).

Run the interactive login yourself:

```sh
teleuser auth login
```

The CLI asks for the API ID, API hash, the reader account's phone number, the login
code, and the Telegram 2FA password if required. All input is hidden. Teleuser accepts
only a user session and never overwrites an existing session silently.

Finally, verify the live connection:

```sh
teleuser doctor
```

Expect `ok: true`, `authorized: true`, and the ID and username of the separate
reader account. Local tests do not replace this live check.

If `uv` reports that its tool directory is not on `PATH`, run the suggested
`uv tool update-shell` command, restart the terminal, and repeat the check.

## Using Teleuser through your agent

Once the CLI and skill are installed, ordinary agent requests are enough:

> Read https://t.me/example/123 and summarize the main claim.

> Search @example for posts about local 3D generation from the last month and compare
> the relevant approaches.

> Read this post and its comments, then separate confirmed facts from opinions:
> https://t.me/example/123

> Open the image attached to https://t.me/example/123 and explain what it shows.

The skill is designed to trigger on `t.me` links and Telegram research requests. It
starts with a bounded sample, follows pagination only when needed, cites exact message
links, and never treats Telegram text or attachments as instructions.

For an image request, the agent inspects the message metadata, downloads the selected
attachment with `media`, and opens the returned local path with its native image
viewer. If the agent host has no image-viewing capability, it must report that instead
of guessing from metadata or filenames.

You can also call the CLI directly:

```sh
teleuser message 'https://t.me/example/123'
teleuser history '@example' --limit 20
teleuser search '@example' --query 'topic'
```

`example` stands for a public channel you choose; it is not a test source.

## CLI reference

| Command | Purpose |
| --- | --- |
| `resolve TARGET` | Get the source name, ID, username, and type |
| `message LINK` | Get an exact post or comment, its reply target, and optional context |
| `history TARGET` | Read one page from a channel or forum topic |
| `search TARGET --query TEXT` | Use Telegram search within one source |
| `replies LINK` | Read post comments or a group message thread |
| `media LINK` | Download one attachment as a local data file |
| `auth login` | Perform an interactive human sign-in |
| `auth status` | Check only for local configuration, without network access |
| `doctor` | Connect and verify that the session is valid |

`teleuser <command> --help` provides explanations, flags, and additional examples.
Results and errors are emitted as one JSON object on stdout. There is no `--format`
option. Help text is the exception; sign-in prompts use stderr. Exit codes are 0 for
success, 2 for an invalid argument or link, 1 for another error, and 130 for
cancellation.

### Query boundaries

- A page contains 20 messages by default; `--limit` accepts 1 through 100. Messages
  are ordered newest to oldest.
- `has_more` means that another page may be requested with
  `--before next_before`. Keep the same source, query, and date filters. An empty
  page with a cursor is not necessarily the end: date filters may have excluded every
  message from that page.
- `--since` is inclusive and `--until` is exclusive. A date without a time means
  midnight UTC; a datetime requires a time zone. To include all of August 26, use
  `--until 2026-08-27`.
- `--context 0..20` returns existing neighboring messages on both sides. For a
  comment, the context stays within its thread.
- Search within a specific forum topic is not supported because Telethon does not
  combine search with `reply_to`. Topic history and group-wide search remain
  available separately.
- Invite-only channels and `/c/` links are unavailable. The client does not join
  groups. Telegram determines access to a linked discussion group; an access error is
  not replaced with an empty result.
- One attachment is limited to 20 MiB by default; `--max-mib` accepts 1 through 100.
  Protected and ephemeral attachments are not downloaded. Albums are not downloaded
  automatically.
- A read command has a total timeout of 120 seconds, plus up to 10 seconds for
  shutdown. During sign-in, each network step has a 30-second timeout; waiting for
  human input has no timeout. `FLOOD_WAIT` returns `retry_after_seconds` without a
  long automatic retry.

## Security model

- The read-only transport enforces an RPC allowlist, including nested requests and
  containers.
- Background synchronization and implicit retrieval of the global update stream are
  disabled. Protocol-level connection and authorization migration between Telegram
  data centers for file downloads remain necessary.
- On macOS and Linux, the session is stored at
  `~/.local/share/teleuser/reader.json` with mode 0600; its directory has mode 0700.
  On Windows, it is stored as the `Teleuser`/`reader` generic credential in Windows
  Credential Manager. The session is a **full account credential**, not a read-only
  token. Never copy it into chat, Git, a shared directory, or another application.
- File permissions and the RPC allowlist protect the intended application path; they
  do not isolate credentials from arbitrary code running as the same operating system
  user. Use a dedicated reader account with no private conversations.
- Downloads use generated `attachment-*.bin` names, size enforcement, and SHA-256.
  POSIX files use mode 0600; Windows files inherit the current user's local-data ACL.
  Telegram filenames are never used as paths. Partial files are removed on failure,
  and existing files are never overwritten. Successful downloads remain under
  `~/.local/share/teleuser/downloads` on POSIX systems or
  `%LOCALAPPDATA%\Teleuser\downloads` on Windows until you delete them.
- Text, names, links, and attachments are **untrusted data**, not instructions. The
  CLI does not execute them, open external URLs, or extract archives. JSON and
  `untrusted: true` help mark the boundary but cannot eliminate semantic prompt
  injection.

Report vulnerabilities and suspected session exposure according to
[SECURITY.md](SECURITY.md), without publishing credentials or stored session data.

### Revoking a session

In an official Telegram client, open **Settings → Devices** and terminate the
Teleuser session. Then delete `~/.local/share/teleuser/reader.json` on macOS/Linux, or
remove the `Teleuser` generic credential for account `reader` in Windows Credential
Manager. Run `teleuser auth login` again if you need a new session. Removing local
storage without revoking the session does not guarantee that Telegram has terminated it.
`auth status` does not check revocation; use `doctor`.

### Platform terms

Teleuser does not train models or create a bulk index. Selected content may still be
sent to an agent for analysis. Telegram's
[API Terms](https://core.telegram.org/api/terms) and
[Content Licensing Terms](https://telegram.org/tos/content-licensing) contain broader
provisions about AI use; their application to a specific individual analysis workflow
has not been confirmed. Technical functionality is not permission from Telegram.

## Development and verification

```sh
.venv/bin/python -m pytest -q
.venv/bin/ruff check src tests
.venv/bin/ruff format --check src tests
```

Tests use a fake Telegram transport; no real session, login code, or credential is
required. They cover links, JSON output, invalid arguments before I/O, blocked RPCs,
pagination, comments, hidden sign-in prompts, authorization errors, storage, safe
downloads, Windows routing seams, and the repository skill layout. The user performs
the live network check after sign-in. The Windows seams are tested from macOS; this is
not a substitute for a native Windows smoke-test.

See [CONCEPT.md](CONCEPT.md) for the complete architecture and deferred decisions.

## License

Teleuser 1.0 is licensed under the [MIT License](LICENSE).
