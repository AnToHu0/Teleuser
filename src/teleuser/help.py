"""On-demand explanations; the skill need not carry this reference."""

OVERVIEW = """
Local read-only Telegram client. Results and errors are JSON.
Uses the configured reader account for public sources.
The user signs in separately: teleuser auth login.
Does not join groups, send messages, or open external links.

Examples:
  teleuser message 'https://t.me/example/123'
  teleuser history '@example' --limit 20
  teleuser search '@example' --query 'topic'

Details and additional scenarios: teleuser <command> --help.
"""

PAGING = """
Results are ordered newest to oldest. limit controls the page size (20 by default,
100 maximum). When has_more=true, continue with --before set to next_before.
This also applies to an empty page: date filters may have excluded all of its messages.
before excludes the specified ID. Keep the same source, dates, and search query.
since is inclusive; until is exclusive. YYYY-MM-DD means midnight UTC.
To include all of August 26, use --until 2026-08-27.
The response covers only the inspected page and does not claim completeness for the channel.
"""

DETAILS = {
    "resolve": """
Get the name, ID, username, and type of a public channel or group.
A private user in place of a channel is rejected. Invitations are not accepted.
Examples:
  teleuser resolve '@example'
  teleuser resolve 'https://t.me/example'
""",
    "message": """
Get an exact message. A link with ?comment= opens that comment in the linked
discussion group, not a message with the same ID in the original channel.
--context N adds up to N existing messages before and after it (20 maximum).
For a comment, context stays within its thread. The reply target is returned separately;
an inaccessible reply or one outside the selected source is marked explicitly.
Examples:
  teleuser message 'https://t.me/example/123' --context 3
  teleuser message 'https://t.me/example/123?comment=456'
  teleuser message 'https://t.me/example/100/123'
""",
    "history": PAGING
    + """
TARGET is an @username, channel link, or forum-topic link.
A link to an individual post does not select the entire channel; use @username.
Examples:
  teleuser history '@example' --since 2026-08-01 --until 2026-08-27 --limit 50
  teleuser history '@example' --before 123 --limit 20
  teleuser history 'https://t.me/example/100'
""",
    "search": PAGING
    + """
Use Telegram search within one selected channel or group, not across all Telegram.
Telegram determines match behavior. Forum topics support separate retrieval;
combining search with a topic is explicitly unsupported in this version.
Examples:
  teleuser search '@example' --query 'rental' --since 2026-08-01
  teleuser search '@example' --query 'rental' --before 123 --limit 30
""",
    "replies": PAGING
    + """
For a channel post: comments from its linked discussion group. For a group message:
its reply thread. For a comment link: discussion of the original post.
An inaccessible discussion is returned as an error, not as an absence of comments.
Examples:
  teleuser replies 'https://t.me/example/123' --limit 30
  teleuser replies 'https://t.me/example/123' --before 456 --limit 30
""",
    "media": """
Download one message attachment into a dedicated local directory as an inert .bin file.
The default maximum is 20 MiB; --max-mib 1..100 changes the limit. Output includes the
path, MIME type when known, size, and SHA-256. The original filename does not control
the path. Successful downloads remain in Teleuser's per-user data directory until the
user deletes them. Does not execute files, extract archives, or extract text automatically.
Protected and ephemeral content is not downloaded. A complete album is not downloaded:
provide a link to a specific message; grouped_id helps identify neighboring items.
Examples:
  teleuser media 'https://t.me/example/123'
  teleuser media 'https://t.me/example/123' --max-mib 50
""",
    "doctor": """
Check reader connectivity and authorization. Outputs only the account ID and username,
without the phone number or secrets. Does not start sign-in automatically.
Examples:
  teleuser doctor
""",
    "auth": """
Configure a user session. This is not a bot sign-in.
A human performs login in a terminal; status checks only local configuration.
Examples:
  teleuser auth login
  teleuser auth status
""",
    "login": """
Run this yourself in a terminal. You need your own api_id and api_hash from my.telegram.org,
the separate account's phone number, a login code, and its Telegram 2FA password if enabled.
Secrets are requested without echo and are not accepted through command-line arguments.
The reader session uses a mode-0600 file on POSIX or Windows Credential Manager.
An existing session is not overwritten. Revoke it under Telegram → Devices.
Examples:
  teleuser auth login
""",
    "status": """
Check for local configuration without network access or outputting sessions or credentials.
configured=true does not prove that the Telegram session remains valid; use doctor for that.
Examples:
  teleuser auth status
""",
}
