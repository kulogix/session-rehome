# Security

## Reporting a vulnerability

Please report security problems privately, through GitHub's **"Report a vulnerability"** button on this
repository's Security tab (private vulnerability reporting), not in a public issue. Include the version
(`ccd-rehome --version`, `st-bundle --version`), your OS, and the steps to reproduce. Replace real e-mail addresses,
account ids and paths with placeholders.

You can expect an acknowledgement within a week. Fixes are released as a new version, with a CHANGELOG entry that
credits the reporter unless they prefer otherwise.

## What the tools touch

The tools run locally, with your own user's rights, and send no telemetry. They contact no online service. The
only network use is ssh (and rsync over it) to a machine you name, in the transporter's gated procedure. The
verifier's load probe starts your own Claude Code with its API address pointed at a closed local port, so no turn
is spent; any background traffic of Claude Code itself follows your Claude Code settings.

| | `ccd-rehome` | `st-bundle` and the `st-*` scripts |
|---|---|---|
| **Reads** | Desktop profiles: session records, their side files, the account id in `config.json` (never the stored login itself), Desktop's own logs, its local storage (scanned only for account-id and e-mail pairs), the login cookie's **name and expiry** (never its value); the account entry (id, e-mail, org) of the CLI's `~/.claude.json` | the chosen session: its transcript, sidecar files, tasks, project memory, project files |
| **Writes** | session records and their side files inside a profile; an archive before every change; its state folder (`~/.local/state/session-rehome`, `~/Library/Application Support/session-rehome` or `%LOCALAPPDATA%\session-rehome`; an existing `~/.claude-instances/_rehome` from an earlier version) | on the origin: only the bundle file and the proof file you name (`-o`). On the destination: the transcript copy, its sidecars, the project files, an appended relocation note, `CLAUDE.md`, and the Desktop record (through `ccd-rehome adopt`) |
| **Never** | signs in or out; reads passwords, tokens or cookie values; edits a transcript | edits a transcript's existing bytes; packs credentials, `~/.claude.json`, shell history, settings, or other sessions; changes the origin's Claude data or project (the ssh path runs only an allowlist of read-only commands there) |

**What a bundle contains.** A bundle (`.csb.zip`) carries a whole conversation, including every file and command
output it saw. Treat it as you would the project itself. Project files that look like secrets (`.env`, private
keys) are left out unless you ask for them, and secret-looking strings inside the conversation are counted and
reported, because history cannot be edited: rotate those credentials if the bundle is going anywhere you do not
control. Moving a session into **another person's** account exposes all of it to them; the transporter asks first
(question D6 in its SKILL.md).

**Supply chain.** The scripts use only the Python standard library. The plugin and `install.py` install exactly the
files in this repository. Review the `skills/` folder before you install from a fork or a mirror.

## Supported versions

Only the newest release receives fixes.
