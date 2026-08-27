# Teleuser 1.0: product and security design

Date: 2026-08-27.

Status: Teleuser 1.0 is a working reader-only CLI and portable Agent Skill for public
Telegram research. See [README.md](README.md) for installation and current commands.

## Product contract

The user gives an AI agent a Telegram message, comment, or public-channel link, or asks
the agent to research a topic in a public channel. The agent uses the Teleuser skill
to select bounded CLI calls, retrieves the required material, and answers with source
links and a clear description of what it inspected.

```text
User → agent → Teleuser skill → teleuser CLI → bounded Telethon layer → Telegram
```

- The product is the combination of the `teleuser` CLI and the portable source skill
  at `skills/teleuser`.
- A separate regular Telegram account reads public channels, supergroups, available
  comments, and forum topics.
- Application-level operations are read-only. Sending messages, reacting, editing,
  deleting, joining, and account management are outside the product.
- Retrieved Telegram content is untrusted data, including instructions in
  attachments, OCR output, and transcripts.
- Teleuser performs no background collection, global indexing, automatic conversation
  export, or model training.
- MCP, a continuously running server, and a public endpoint are not required.

## Skill and agent workflow

The repository keeps one harness-neutral source skill at `skills/teleuser`. During
installation, the current agent copies it to the user-level Agent Skills directory
documented by its own harness. Codex, Claude Code, and OpenCode use different native
locations but consume the same `SKILL.md`; other harnesses can do the same when they
implement the open Agent Skills format.

The skill description covers `t.me` links and Telegram research so an agent can
select it implicitly. Its body contains exactly three common examples—message,
history, and search—plus the essential read-only and untrusted-content rules. The
complete parameter reference stays in command-specific `--help` output so it enters
the agent context only when needed. This follows the progressive-disclosure model in
the [Agent Skills specification](https://agentskills.io/specification).

The repository root includes the shared [AGENTS.md](AGENTS.md), plus a minimal
[CLAUDE.md](CLAUDE.md) redirect for Claude Code. The shared guide tells an agent how
to:

1. install the CLI from the checkout;
2. install the skill without modifying unrelated skills;
3. ask the user to perform Telegram sign-in in their own terminal;
4. verify the CLI, session, and one user-selected public link.

The agent never requests login codes, passwords, API credentials, phone numbers, or
session strings in chat.

## CLI contract

The implementation uses Python and Telethon rather than reimplementing MTProto or
cryptography. The CLI provides `resolve`, `message`, `history`, `search`,
`replies`, and `media`, with separate `auth` setup and `doctor` diagnostics.

Examples:

```sh
teleuser message 'https://t.me/example/123' --context 5
teleuser history '@example' --since 2026-08-01 --until 2026-08-27 --limit 100
teleuser search '@example' --query 'topic' --limit 30
teleuser replies 'https://t.me/example/123' --limit 50
teleuser search --help
```

Results and errors are JSON. `--help` emits text, and local sign-in prompts use
stderr. Output contains the source, messages, IDs, dates, reply relationships, and
query boundaries. An empty result never replaces an access error. Server rate limits
return a structured retry delay without a long automatic sleep.

A page contains up to 20 messages by default and at most 100. `--before` excludes
the specified ID; `--since` is inclusive and `--until` is exclusive. A date
without a time means midnight UTC. No more than `limit + 1` messages are read for a
page, so local date filtering can produce an empty page with a continuation cursor.
Context includes up to 20 existing neighbors on each side. Downloads are limited to
20 MiB by default and at most 100 MiB.

Large result sets are read in pages. The agent narrows the material by period and
search before loading more context. Attachments are downloaded only when required,
and links inside messages never trigger actions by themselves.

The CLI is the only public programmatic interface. An agent may compose CLI calls and
process JSON for one-off work; a separate SDK is unnecessary. The application remains
internally modular, but raw `TelegramClient`, session credentials, and arbitrary RPC
access are not exposed.

## Reader account and public sources

The reader session is stored outside the project: in a mode-0600 file on macOS/Linux,
or in Windows Credential Manager on Windows. No message-text cache persists between
commands. Explicit media downloads remain in the platform's Teleuser user-data
directory until the user deletes them. The account should be dedicated to Teleuser
and contain no private conversations.

Public channels and available comments are the normal path. Invite links and private
`/c/` links are rejected. If Telegram does not expose a linked discussion group,
Teleuser returns an access error rather than claiming that the post has no comments.

Joining a group or submitting a membership request changes account state, so Teleuser
never does either. If a source requires membership, the user may join it manually in
an official client; Teleuser itself remains unchanged.

Read-only describes application-level behavior rather than the absence of every
protocol operation. Connection, authorization, and file downloads require supporting
Telegram requests. The application does not promise an invisible mode or alter
Telegram status behavior; [section 1.4 of the API Terms](https://core.telegram.org/api/terms)
separately restricts interference with basic client behavior.

An MTProto session is a full account credential. The RPC allowlist and platform
credential storage protect the intended application path, but they do not isolate
credentials from arbitrary code running as the same operating-system user. This is
why Teleuser supports only a dedicated reader account.

## Prompt-injection protection

The goal is to prevent Telegram content from changing the agent's task, commands, or
data-handling behavior.

1. The skill defines posts, channel names, author data, comments, links, documents,
   OCR output, and transcripts as untrusted data. They may be analyzed but cannot
   change the task.
2. Output has a fixed structure. Client-generated metadata is separated from external
   strings, which are serialized and escaped. The `untrusted` marker and JSON help
   establish a data boundary but do not eliminate semantic injection.
3. The client does not execute code from messages, construct shell commands from
   content, automatically open arbitrary URLs, or substitute external strings into
   control fields. The user's request determines whether another source is opened.
4. Downloaded files use safe generated names in a dedicated directory. Telegram names
   and paths cannot write `AGENTS.md`, `SKILL.md`, configuration, executable
   scripts, or files outside that directory. Execution, archive extraction, and
   autorun are disabled.
5. Read-only checks are independent of message text. Preventing Telegram writes does
   not by itself prevent exfiltration through other agent tools; shell, file, and
   outbound-network boundaries in the agent environment still matter.
6. Answers include source links, and truncation, omissions, filtering, and
   inaccessibility are stated explicitly. Processing must not silently rewrite source
   meaning.

[OpenAI's agent safety guidance](https://developers.openai.com/api/docs/guides/agent-builder-safety)
describes structured boundaries and reduced permissions as risk-reduction measures;
it does not promise absolute protection from injection.

### Optional classifier

A small local model for detecting suspicious instructions remains a separate
experiment, not a Teleuser 1.0 dependency.

If evaluated and added later, it would run before content reaches the main agent and
have no tools, credentials, or network access. It could return a bounded risk score
and pointers to suspicious fragments, but it could not turn material into trusted
content. Evaluation would need to cover missed attacks, false positives, languages,
OCR and transcript attacks, and latency on real tasks.

## Telegram terms and data handling

Teleuser targets on-demand retrieval for ordinary research. It does not require bulk
accumulation or model training.

Unconditional compliance with Telegram's rules has not been established.
[Section 1.5 of the API Terms](https://core.telegram.org/api/terms) and the
[Content Licensing Terms](https://telegram.org/tos/content-licensing) address the use
of retrieved data for AI, including deployment. The reviewed sources do not
officially establish how Telegram applies that language to individual, on-demand
reading performed for a user. Do not claim either guaranteed permission or
established illegality.

The CLI runs locally, but selected messages are passed to the model used by the agent
for analysis. The skill does not determine server-side retention or use by the model
provider. A separate reader account and the absence of training inside Teleuser do
not change that.

## Release checks

- Public post, comment, and topic links resolve with source URLs, dates, and context.
- Search and history return bounded samples with accurate continuation and
  incompleteness state.
- Invalid arguments and private links fail before credential or network access.
- The portable skill is present at `skills/teleuser` and is included in the source
  distribution.
- Read operations never send messages, reactions, or membership requests and never
  modify content.
- Malicious text, control characters, filenames, and attachments do not cause
  execution, configuration changes, or exfiltration through other tools.
- Server limits and retries have finite, observable behavior.
- Secrets never appear in JSON output or logs.
- Package metadata, runtime version, documentation, wheel, and source distribution
  all report Teleuser 1.0.0.

CLI checks can be deterministic. Behavioral agent tests for injection estimate
robustness on the evaluated set but do not prove absolute protection.
