---
name: session-rehome
description: >-
  Moves Claude Desktop and terminal (CLI) Code sessions on THIS machine without losing them: after a sign-in
  change ("I logged out and my sessions are gone"), between accounts ("move these sessions to my work account"),
  between Desktop windows / user-data-dirs ("move this session to my other Desktop window"), between terminal
  accounts (one CLAUDE_CONFIG_DIR home per account: "move this CLI session to my work home"), and between the
  terminal CLI and Desktop ("show my CLI sessions in Desktop", "continue this Desktop session in the terminal").
  Also answers "which window or CLI home is signed in as whom" and "which sessions belong to which account". Any
  number of accounts, any --user-data-dir, any CLI home. Dry runs, format validation, an archive before every
  change, exact undo, verification from Desktop's own log. Never signs in or out, never reads credentials, never
  edits a conversation. To move a session to ANOTHER machine or OS, use session-transporter.
license: MIT
compatibility: >-
  Python 3.9+, standard library only. Claude Desktop on Linux (verified), macOS (partly verified), Windows
  (experimental). See tested.json.
metadata:
  homepage: https://github.com/kulogix/session-rehome
---

# session-rehome

**Which skill?** This one works on **one machine**. The companion skill **session-transporter** moves a
session to **another machine or operating system**.

| The user wants to… | Use |
|---|---|
| get sessions back after signing in to a different account, or move them to another account | **this skill** |
| move a session to another Desktop window (another `--user-data-dir`) on this machine | **this skill** (`move --to-profile`) |
| move a session to another terminal account (another `CLAUDE_CONFIG_DIR` home) | **this skill** (`move cli … --to-profile cli:NAME`) |
| show a terminal (CLI) session in Desktop, or continue a Desktop session in the terminal | **this skill** (`register`, `resume-cli`) |
| move a session to another computer, another OS, or restore it from an archive | **session-transporter** |

**How to run the tool.** Every command is

    python3 "${CLAUDE_SKILL_DIR}/scripts/ccd-rehome" <command> ...

On Windows, use `py -3` (or `python`) instead of `python3`. In the tables below, **`R` stands for that whole
prefix**: type it in full each time, because shell variables do not survive between your commands. If you see the
text `${CLAUDE_SKILL_DIR}` literally, it means the folder that contains this SKILL.md. The tool needs Python 3.9+
and nothing else.

## Start here

| The user says / you need | Run |
|---|---|
| "my sessions are gone after I switched accounts" | `R status`, then the `fix:` command it prints, then `R launch P` and `R verify P` |
| "which window is signed in as whom" | `R profiles` |
| "my windows / CLI homes are in my own folder" | `R profiles --add-root DIR` (a folder of them) or `R profiles --add PATH` (one) |
| "what sessions does this window have, under which accounts" | `R sessions P` |
| "move these sessions to account X" | `R sessions P` (get ids), then `R move P --to X --only ID --dry-run`, then the same without `--dry-run` |
| "fix all my windows" | `R rehome --all --dry-run`, then `R rehome --all` |
| "undo that" | `R rollback P ARCHIVE` (the archive name the move printed; `R status P` lists them) |
| "move this session to my other Desktop window" (another user-data-dir, same machine) | `R move P --only ID --to-profile P2 --dry-run`, then without `--dry-run` (both windows quit) |
| "which terminal accounts do I have, and where are their sessions" | `R profiles`, then `R sessions cli` (or `R sessions cli:work`) |
| "move this terminal session to my work account/home" | read `references/cli-homes.md`, then `R move cli --only ID --to-profile cli:work --dry-run`, then without `--dry-run` |
| "show my terminal (CLI) sessions in Desktop" | `R cli-sessions`, then `R register P --cli-session-id ID` (never Desktop's "Recover CLI sessions") |
| "continue this Desktop session in the terminal" | `R resume-cli P --only ID` (prints the checked command); `R unregister P --only ID` to drop the Desktop record too |
| put a session record into a profile on ANOTHER machine | use session-transporter's bundle: it runs `R export-record` here and `R adopt` there for you |
| first use on a machine | `R doctor`, then `python3 -I "${CLAUDE_SKILL_DIR}/scripts/selftest.py"` |
| it worked on a new Desktop version or OS | `R report <what you ran>`, then offer the user to submit it (see "Maintaining this skill") |

`P` is a profile: `default` (the plain Desktop window), a folder name (`acct-e`: in a profile root, else a known
profile; it must fit one), any path to a user-data-dir, or a **CLI home**: `cli` (`~/.claude`), `cli:NAME`
(`~/.claude-NAME`, else a known home so named), or any path to a Claude Code config dir. Any folder works for both;
`~/.claude-instances` is only an example (mechanics.md §9). `ID` is a session id prefix from `R sessions P`. `X` is
an email, an account uuid, or a unique uuid prefix.

## Rules for the agent

1. **Read state before acting.** Run `status` or `sessions` with `--json`, and parse the JSON rather than the
   text. Never infer accounts from folder names: they are opaque UUIDs, and stray `<account>/<org>` folders are
   normal.
2. **`--dry-run` first** and show the user the plan, unless they asked for exactly that move. A dry run writes
   nothing at all (tested: the home folder is byte-identical afterwards) and works while the window is open; the
   real run needs it quit.
3. **Read the validation block.** Before any move the tool checks every file it will touch:
   - `ERROR`: a format changed or broke. The move is always refused.
   - `DRIFT`: a new record field or a new per-account file. A real run is refused.
   - `NOTE`: this Desktop version or OS isn't in `tested.json`.
   On DRIFT, show the user what's new. Use `--accept-drift` only with their OK, and only when the dry run shows the
   new item is harmless, for example a new field that is clearly session state. Then fix the tool (rule 9) so the
   next run is clean.
4. **Never quit a window yourself without the user's OK.** It may hold their live work. `R quit P` refuses
   outright if this command runs *inside* P, because that would end your own session.
5. **Exit codes:** `0` means done, nothing to do, or verify OK. `1` means refused, failed, or MISMATCH, and stderr
   says why. `2` means a bad command line. A refusal is a stop, not a puzzle to work around.
6. **Blockers are instructions for the human** (see Troubleshooting). Relay them; don't fake a sign-in, edit
   `config.json`, or create folders by hand. Signing in and out is always the user's job.
7. **After every real move,** `launch` and wait about 20 s, then `verify`. Report:
   - titles moved, from which email to which;
   - the archive name and undo command;
   - the `verify` result;
   - "reconnect claude.ai connectors under the new account";
   - any `transcript MISSING` sessions (they list but won't open; the tool didn't cause it).
8. **If another tool on the machine also moves Desktop session records** (for example a switcher between Anthropic
   and a local inference gateway), use this one for account changes and that one for gateway changes.
9. **If the tool misbehaves or `doctor` reports DRIFT, fix the skill itself.** See "Maintaining this skill"
   below. Never work around it by hand.
10. **When it worked on an untested combination** (NOTE above), run `R report <what ran>` and offer the user to
    submit it. The entry contains nothing identifying.
11. **CLI homes** (terminal accounts): see "CLI homes" below, and read `references/cli-homes.md` before a real CLI
    move. What `status` and `rehome` advise is always a `--copy`. Never read `.credentials.json` or
    `sessions/*.key`; a signed-out target is the user's sign-in job.

## What Desktop does (why sessions "vanish")

Each Code session record lives at `<profile>/claude-code-sessions/<accountUuid>/<orgUuid>/local_<id>.json`.
Desktop lists only the folder of the account and org that is signed in. After a sign-in change the old records
are still there, just not listed, and the conversations are untouched in `~/.claude/projects/`. Moving the small
record file into the signed-in account's folder brings the session back. Desktop never compares a record with
the signed-in account, so the folder alone decides where it shows. Since Desktop 5 a record can still hold the old
account's email and its cloud, Remote Control and connector ids; a move drops them (mechanics.md §5a).

## Commands

```
R profiles | status [P ...] | sessions P | accounts       [--json]   read-only reports
R profiles --add PATH | --add-root DIR | --forget PATH              register your own folders (or drop them)
R rehome P ... | --all              [--include-cowork] [--dry-run]   everything stranded -> signed-in account
R move P [--to ACCT] [--to-org ORG] [--from ACCT ...] [--only ID ...] [--include-cowork] [--dry-run]
R move P --only ID ... --to-profile P2 [--to ACCT] [--dry-run]      to another Desktop window on this machine
R move cli[:NAME] [--only ID ...] [--project DIR] --to-profile cli[:NAME] [--copy] [--no-memory] [--keep-dates] [--dry-run]
                                                                     terminal sessions between CLI homes
R rollback P ARCHIVE [--dry-run]                                     exact undo
R export-record P --only ID [--out FILE]                              one record as a portable ccd-record/1
R adopt P --record FILE [--to ACCT] [--to-org ORG] [--cwd DIR] [--cli-session-id ID] [--title T] [--dry-run]
R cli-sessions | register P --cli-session-id ID [--cwd DIR] [--to ACCT] | resume-cli P --only ID | unregister P --only ID
R quit P | launch P | verify P | doctor | report [CHECK ...] | --version
# moves also take --accept-drift (see rule 3)
```

- **`ACCT`:** an email, a full uuid, or a unique uuid prefix. Any account any profile or the CLI has ever been
  signed in to is known.
- **`--to`:** defaults to the signed-in account. It may name an account that isn't signed in (pre-staging);
  Desktop shows those sessions once the window signs in to it.
- **`--only`:** takes id prefixes from `sessions`.
- **`--from`:** limits the move to records filed under those accounts.
- **Discovery** (`profiles`, `status`, `--all`; `profiles` shows where it found each, JSON `found_by`):
  - the default profile; every subfolder of a **profile root** (`~/.claude-instances` while it exists, each
    `--add-root DIR`, `$CCD_REHOME_INSTANCES`);
  - the `--user-data-dir` of running Desktops, `.desktop` launchers and `claude-desktop`/`Claude` lines in shell
    startup files; on macOS, the profiles Desktop's shared log names;
  - every path added (`R profiles --add PATH`) or given before; `$CCD_REHOME_PROFILES` (`:`-joined; `;` on Windows);
  - **CLI homes**: `~/.claude`, `~/.claude-*` / `~/.claude_*` (never `~/.claude-instances`), those in a profile
    root, every `CLAUDE_CONFIG_DIR=` in the bash, zsh and fish startup files, this process's `CLAUDE_CONFIG_DIR`,
    and `$CCD_REHOME_CLI_HOMES`.

## What moves, and how

| Item | Handling |
|---|---|
| Record `local_<id>.json` | moved. If the target already has that id, the newer `lastActivityAt` wins and both copies are kept |
| Queued background work `armedWorkAtQuit` | kept in the record (it resumes at next launch) and reported |
| Effort, UltraCode, permissions, title, cwd, prompt suggestion, artifacts | kept |
| `remoteMcpServersConfig`, `withheldConnectorHosts`, `remoteControlAutoEligible`, `steeredByRemoteClient`, `bridgeSessionIds`; Desktop 5: the old account's `emailAddress`, cloud, Remote Control, connector, artifact and Space ids, `sshReattach`, the quit-resume marks | dropped (state of the old account: `references/desktop5-fields.md`). A session started from Remote Control keeps its "never bypass permissions" clamp and its Remote Control restrictions (`remoteClientLimits`, `remoteControlDescendant`) |
| `error*`, `cliBinaryPin`; Desktop 5: error-card detail, `peerInbound` | dropped (Desktop recreates them) |
| Local-gateway-only model | replaced with `$CCD_REHOME_FALLBACK_MODEL` |
| `backlog/tasks.json` task suggestions | merged by id. With `--only`, just those whose `originSessionId` moved |
| `scheduled-tasks.json` | merged by id (full moves) |
| `deleted_*` tombstones | copied, so deleted sessions stay deleted |
| Desktop 5: `owed-bridge-delete_*` (Remote Control deletes the old account owes), `archived-sessions.idx` (a cache) | left in place. A move refuses (DRIFT) while a Remote Control delete is still in progress for a session |
| Desktop 5: an imported session not resumed yet (its conversation is in `imported-staging/` in the account folder) | moves within its window (Desktop keeps reading it from there); `--to-profile`, `export-record` and `unregister` refuse it until it is resumed once. A fresh `local_<id>.json.tmp` of a session being moved is refused (DRIFT); other sessions' markers and files do not block a move |
| Cowork `local-agent-mode-sessions/<acct>/<org>/local_*` | moved with `--include-cowork`; `rpm/` (plugin cache) left |
| Conversations `~/.claude/projects/**.jsonl` | never touched |
| `scratch-workspaces/<acct>/…` | left in place: the cwd locates the transcript. WARNING: when the old account signs in there again, Desktop may delete a scratch workspace none of its sessions uses after 7 idle days; copy out what you need |
| Cookies, tokens, `spaces-present/*/link-key`, `config.json` | never touched |

**Target org**, in order of preference:
1. `--to-org`;
2. Desktop's log for that account in this profile;
3. the account's only org folder in this profile;
4. the account's only known org anywhere. This is safe because an account's org is the same in every profile; the
   tool prints "inferred".
If several orgs are possible, it refuses.

## CLI homes (terminal accounts)

**Read `references/cli-homes.md` before a real `move cli`, before rolling one back, and when a CLI-home message
appears**: it has every rule, refusal, warning and message in full. This section is the summary.

The terminal CLI keeps one **config dir** per account, chosen with `CLAUDE_CONFIG_DIR` (default `~/.claude`), each
with its own settings, `projects/` (the conversations) and login. **The CLI does not file sessions by account** (its
picker lists the folder's sessions whatever account is signed in), so nothing inside a home is stranded. To use
sessions with another account, move or copy them to the home where that account is signed in; two homes of the same
account need neither.

**How far it is tested** (tell the user before the first real move): the self-test on synthetic homes, and one run
of the real Claude Code CLI 2.1.319 on 2026-11-08 that resumed a moved transcript in the target home and not in the
source. A move has not yet run on a real signed-in CLI home, and `move cli` prints no `NOTE` about that. So run
`R move cli --only ID --to-profile cli:NAME --dry-run` first and show the plan; after the real move, have the user
resume one session with the printed line before relying on it; when it worked, run `R report selftest move-cli` and
offer to submit it.

- **Names:** `cli` = `~/.claude`, `cli:NAME` = `~/.claude-NAME` (else the one known home called `NAME`), or the path
  of a config dir (it has `projects/`, `.claude.json`, `.credentials.json` or `settings.json`, and no `config.json`).
  While a profile root holds a Desktop profile `cli`, `cli` is ambiguous: use the path. The home folder, folders
  above `~/.claude`, `~/.claude-instances`, folders holding a Desktop profile and the state folder are never CLI
  homes.
- **Signed in?** Only whether `.credentials.json` exists and is non-empty (`unknown` on macOS, where the login is in
  the Keychain); the tool never opens it.
- **Reports:** `R status cli:NAME --json` gives the account, sessions, archives and `move`, the `--copy` into the home
  of another account (null, with the reason in `move_why`, when there is none); `R sessions cli:NAME` flags `OPEN`,
  `desktop: PROFILE` and `older than N days`. `R rehome cli` only explains; `R rehome --all` skips CLI homes.
- **A move** takes each session's transcript byte for byte, its sidecar folder, `tasks/<id>/`, `todos/<id>*.json`
  and `file-history/<id>/`, and **copies** the project memory (a differing file is kept and reported; `--no-memory`
  skips it); never `history.jsonl`, `sessions/`, settings or credentials. `--copy` keeps the source. It is **all or
  nothing**: the archive name is printed first, and a failed step (permission, full disk, Ctrl-C, SIGTERM, SIGHUP)
  is undone and checked ("It was undone: nothing was changed"); when the undo cannot finish, the archive is kept and
  `R rollback P ARCHIVE` finishes the job. Relay that; never move files by hand. Relay the line a move prints to
  continue each session: `cd DIR && CLAUDE_CONFIG_DIR=<target> claude --resume ID` (on Windows, cmd and PowerShell
  lines).
- **Refuses** (nothing written; a dry run prints the `REFUSE` lines and exits 1): a target that is no CLI home, or
  the source; an `OPEN` session; a move **out of `~/.claude`** of a conversation any Desktop record names
  (unregister it first, or `--copy`; for a record's earlier conversation only `--copy`); a different transcript with
  that id in the target, or the id in two project folders of the source; a symlink (on Windows any junction), a
  path escaping a home, or a FIFO, socket or device file, in an item, the project memory or a target path; an item
  the target already has; `--keep-dates` on a plain move of a transcript the target would delete. An identical
  transcript in the target is skipped as already there.
- **Warns:** the transcript is older than the shortest `cleanupPeriodDays` (`desktopSessionCleanupPeriodDays` for
  one last continued in Desktop) any of the target's settings files sets. It is re-dated with its sidecar files,
  which only postpones the deletion (a `--copy` re-dates the copy, never the source); after a plain move the source
  no longer has it: for an old conversation from a backup home, use `--copy`. One last continued in Desktop is
  re-dated only when `claude --version` is below 2.1.248 or unknown. Also warned: homes in different organizations
  (signed thinking may be rejected; unverified); a signed-out target.
- **Undo:** `R rollback cli:NAME ARCHIVE`, from either home. It refuses while the session is open in the target,
  never for a Desktop record: relay its `warning:` and the `--copy` it prints. A `--copy` rollback keeps all of a
  session's copies when one changed or an original is gone. A rollback that stopped finishes when run again.
- **Desktop windows:** Desktop reads `CLAUDE_CONFIG_DIR` if it was started with it, else `~/.claude`, and nothing on
  disk says which, so every rule takes each Desktop profile to read `~/.claude` (if the user says a window was
  started with `CLAUDE_CONFIG_DIR`, ask before moving its conversations). For a record whose conversation is only in
  another home, `R sessions PROFILE` shows `in cli:NAME, CLI id …` and prints the copy into `~/.claude`, by CLI id:
  `R move cli:NAME --only CLI_ID --to-profile cli --copy` (`R status PROFILE --json` counts them in `elsewhere`).
  Advise that copy, never a plain move: the other home is often a backup with the only copy of an old conversation.
  A move into `~/.claude` is always allowed; `R register` files only a conversation there, and prints that copy for
  one in another home.

## CLI ↔ Desktop

A Desktop Code session **is** a Claude Code CLI conversation (`~/.claude/projects/<mangled cwd>/<id>.jsonl`)
plus a small Desktop record that points at it. Each transcript record carries an `entrypoint` stamp
(`claude-desktop` for Desktop turns, `cli` / `sdk-cli` for terminal turns), but nothing else differs. So
converting never edits a transcript:
- **CLI → Desktop: `register`.** It finds the conversation by id prefix (`cli-sessions` lists the ones no
  profile knows) and takes the folder the CLI filed it under. It **refuses** if that folder no longer exists,
  or if a `--cwd` would not resume it (its mangled key must equal the conversation's directory). It builds a
  record with title and times taken from the transcript, and files it through `adopt` (validated,
  idempotent, archived, undoable). Desktop then lists it; opening it resumes it with Desktop's CLI.
- **Never use Desktop's own "Recover CLI sessions" import** on a real conversation. It rewrites the
  transcript in place and strips its thinking content (session-transporter, prohibition 1). `register` is
  the safe replacement.
- **Desktop → CLI: `resume-cli`** prints `cd <folder> && claude --resume <id>` (with `CLAUDE_CONFIG_DIR=<home>`
  when the conversation is in a CLI home other than `~/.claude`; on Windows a cmd line and a PowerShell line) after
  checking the conversation is not open in any process (two writers fork the history). The session stays listed
  in Desktop. **`unregister`** removes the Desktop record (archived, undone by `rollback`) when it should be
  CLI-only.

**What carries over, and what does not**

| | Desktop → terminal (`resume-cli`, `unregister`) | terminal → Desktop (`register`) |
|---|---|---|
| The conversation (every turn, thinking, tool results, sidecars, todos) | kept: same file, never edited | kept: same file, never edited |
| Desktop's per-session settings (title, model, effort, permission mode, UltraCode, grants) | stay in the Desktop record; `unregister` archives them | restored from that archive when one exists; otherwise Desktop defaults |
| Which **account** runs the next turn | the terminal CLI's login (**warned** if it differs from Desktop's) | the Desktop window's account |
| Thinking-block signatures across accounts | same person, different account: worked before; **across orgs: unverified** | same |
| Model ID | an **older terminal CLI may not know it** (measured: 2.1.263 rejected `claude-opus-5-5`; **warned**) | Desktop's bundled CLI is usually the newest |
| Tools | Desktop-only tools (its MCP servers, computer use, browser pane, scheduled tasks) are missing in the terminal; old calls stay in the history | its own MCP setup, if any, is whatever Desktop loads from the same settings files |
| Queued background work at quit (`armedWorkAtQuit`) | stays with Desktop | n/a |
| Never at the same time | an open conversation in both forks the history; `resume-cli` refuses while it is open | `register` refuses while it is open |

- **Measured, a full round trip** (terminal → `register` → a Desktop turn → terminal `--resume`; Linux, Desktop
  2.31226.1, CLI 2.1.319): no byte of an earlier stage changed, no fork, thinking accepted on both sides
  (references/mechanics.md §4a).
- **Do not start the terminal leg from inside a Desktop session.** A `claude` launched from a shell inside
  Desktop inherits its environment: it was stamped `claude-desktop` and ran as that session's child.
  `resume-cli` warns and prints an `env -i` form.

## The transplant interface: `export-record` / `adopt`

session-transporter moves *conversations* between machines; this tool owns *Desktop records*. They meet here:
- **`export-record`** writes one record as `ccd-record/1`: `{format, tool, desktop, exported_utc, record,
  notes}`. Account-bound and transient fields are stripped, and it carries no account or org ids.
- **`adopt`** files such a record into any profile: by default under the signed-in account, or under `--to`
  (and `--to-org`). It runs the same validation as a move (ERROR always refuses; DRIFT refuses unless
  `--accept-drift`) and is **idempotent**: a conversation already registered there is left alone. It
  **refuses** when that conversation is already filed under another account in the profile; use `move` for
  that.
- **`--cwd`** rewrites `cwd` / `originCwd` and drops the fields bound to the old machine (`HOST_BOUND`: git
  anchors, plan path, shell folders, Chrome and computer-use state). Session settings are kept.
- **Every adopt is archived** (kind `adopt`) and undone exactly by `rollback`.

## Troubleshooting (messages and what to do)

**Messages about a CLI home** (a CLI move, its rollback, `register` across homes, retention): each has a row in
`references/cli-homes.md`. Desktop windows:

| Message | Meaning | Action |
|---|---|---|
| `is running … Quit it` | the window is open | the user quits it (File > Quit), or `R quit P` with their OK |
| `Desktop ignored the quit signal` | that build does not honour SIGTERM (seen: 1.9255.2 Linux arm64) | the user quits from the menu; if the window is frozen, force-close it (records on disk are safe), then relaunch |
| `refusing: this command is running INSIDE P` | you would kill your own session | ask the user to quit P |
| `not signed in (signed-out/expired)` | no live login in that window | the user signs in, then re-run (or name a target with `--to`) |
| `no org known for … in this profile`, `ambiguous: N orgs known for this account` | the account has several orgs and none is evident | the user opens the Code tab once while signed in and quits; or pass `--to-org` |
| `account '…' matches 0 known accounts` | email or uuid never seen on this host | check the spelling with `R accounts`; sign in to it once somewhere |
| `not a Desktop profile (no config.json)` | wrong folder, or never launched; also a path meant as a CLI home whose folder has none of `projects/`, `.claude.json`, `.credentials.json`, `settings.json` | launch it once, or fix the path (a CLI home exists once `claude` ran in it) |
| `… does not exist` | the name or path names no folder (no profile root or known profile has that name) | check `R profiles`; fix it, or register the folder (`R profiles --add PATH`) |
| `` `…` is ambiguous: N Desktop profiles have that folder name: … `` | two folders fit the name | use the path meant (the message lists them) |
| `cannot add …` / `is not registered with --add or --add-root` | `profiles --add`/`--add-root`/`--forget` refused, with the reason | relay it; nothing was changed |
| `cannot read … nothing was changed` | a corrupt record or side file | inspect that file; nothing was written |
| `these conversations are open in another process` | the session is resumed in a terminal or another window | close it there first |
| `MISMATCH  Desktop loaded …` (`verify`) | Desktop loaded fewer than exist | quit, relaunch, verify again; if it persists, check `sessions P` for unreadable records |
| `Desktop has not logged loading … yet` (`verify`) | launched but the log line hasn't appeared yet | wait, open the Code tab, re-run |
| `WARNING: N of these sessions' conversations … older than D days` (`status`; `doctor` WARN) | Claude Code would delete them at its next start: a terminal `claude` before 2.1.248 deletes every conversation older than `cleanupPeriodDays`, Desktop's included | tell the user; the fix is theirs: raise the setting named (e.g. `"cleanupPeriodDays": 3650` in that `settings.json`) or update Claude Code. Nothing is changed by the tool |
| `a Remote Control delete of … is in progress (state intent)` (DRIFT) | Desktop has not finished deleting a session on claude.ai | launch the window signed in to that account and let it finish, then move |
| `an imported session not resumed yet` (`--to-profile`, `export-record`, `unregister`) | its conversation is still staged inside the account folder, in no CLI home | the user resumes it once in Desktop (a move to the signed-in account of the same window works first), then re-run |
| `refusing: N imported session(s) were resumed in Desktop since …` (`rollback`) | restoring would bring back an older copy of their conversation | move the sessions back with `move` instead |
| `an unfinished write of a session record` (DRIFT) | a `local_*.json.tmp` Desktop would turn back into a record | launch and quit that window once; if it stays, check whether the `.json` is current before removing the `.tmp` (the user's call) |

## Platform support

`doctor` prints how far this OS is verified, read from `tested.json`.

| | Linux | macOS | Windows |
|---|---|---|---|
| Status | **verified** for Desktop moves (x86_64 and aarch64) | partly verified: self-test and read-only commands on a real Mac (Desktop 4.23118.0); no live move yet | experimental: CI self-test only |
| `move cli` (CLI homes) | self-test; not yet on a real signed-in home (see "CLI homes") | CI self-test only | CI self-test only (its POSIX-only checks are skipped) |
| Default profile | `~/.config/Claude` | `~/Library/Application Support/Claude` | `%APPDATA%\Claude` |
| Logs | `<profile>/logs` | `~/Library/Logs/Claude` (confirmed), shared by all instances; the tool uses only path-bearing lines there | `<profile>\logs` |
| Running check | `/proc` + `SingletonLock` | one `ps` + `SingletonLock` | one PowerShell CIM query + `lockfile` |
| Open-conversation check | `/proc/*/fd` | `lsof` | not available (warns) |
| `quit` | SIGTERM (Desktop quits cleanly) | SIGTERM (unverified) | **refused**: Python can only hard-kill there |
| `launch` | `claude-desktop` | `open -n -a Claude --args …` | `%LOCALAPPDATA%\AnthropicClaude\claude.exe` (a guess) |

All three can be overridden with `CCD_REHOME_DESKTOP`. On a new OS: run `doctor`, then the self-test, and make the
first move with `--dry-run`, then `verify`.

## Nuances that bite

- **Transitional log lines.** At a sign-in change Desktop logs the old account with the new org for about a second;
  taken at face value they send records to a folder Desktop never reads. The tool filters them (mechanics.md §3).
- **A profile stores only the email it is signed in to now.** The registry (`accounts.json` in the state folder)
  remembers every account/email pairing ever seen.
- **"Log out" in the app ends that login on the server.** Coming back needs a human sign-in.
- **Per-identity, not migrated:** claude.ai connectors (reconnect them), sidebar custom groups (re-create them),
  and Remote Control links.
- **Cowork:** on Desktop 4.x a Cowork store also holds your *spaces* and *agents*. Until their link to sessions
  is understood, a Cowork move (`--include-cowork`) refuses whenever they hold content (mechanics.md §5a). Code
  moves are unaffected.
- **`desktop` version** means the version that *last ran* the profile (from its log), not the installed package.
  After an upgrade, launch once before moving, so the files are in the new version's format.
- **`<name>-3p` profiles** are Desktop's own, for a third-party inference gateway (no Anthropic account): rejected.
- **The state folder** (`R profiles` prints it): `~/.local/state/session-rehome` (Linux; `$XDG_STATE_HOME`),
  `~/Library/Application Support/session-rehome`, `%LOCALAPPDATA%\session-rehome`; an existing
  `~/.claude-instances/_rehome` keeps being used. Archives accumulate in its `archive/` and `cli-archive/` (a few KB
  each; old ones are safe to delete).

## Maintaining this skill (agents: this is part of the job)

There is **one** copy of this skill: the project at https://github.com/kulogix/session-rehome. A local
install is normally a link to a clone of it (`install.py`), so the folder you are reading may be inside that clone.
Desktop, macOS and Windows will change under it. Whoever finds it wrong (usually an agent) fixes it **there**.

**Never:**
- copy the script somewhere else to patch it, or write a "v2" or a one-off variant;
- hand-move files around the tool because "it doesn't handle this case";
- hard-code a user's accounts, paths or hosts. Those belong in the user's own notes, or in `CCD_REHOME_*`
  variables.

A fork fixes one machine once and leaves every other copy broken. A workaround hides the bug from the next agent.

**When to act:**
- `doctor` prints DRIFT: a new record field, a new per-account file, or a missing log line;
- a refusal or result contradicts what you observe;
- `verify` says MISMATCH twice;
- it fails on a new OS or Desktop version.

**How:**
1. **Find the checkout.** `git -C "${CLAUDE_SKILL_DIR}" rev-parse --show-toplevel` names it. If the skill is not
   inside a git checkout (a copy or plugin install), tell the user, and suggest cloning the project and
   installing from it with `python3 install.py`, so the fix is not stranded in a copy.
2. **Reproduce and measure.** Find the real evidence: a record's fields, the log lines, the folder layout. Read the
   matching row of the contract in `references/mechanics.md` §0, and decide what changed. Not knowing what a new
   field is counts as a finding to investigate, not a reason to guess.
3. **Write the test first.** Add a synthetic fixture to `scripts/selftest.py` that reproduces the new behaviour, and
   watch it fail. Never put real user data in fixtures.
4. **Fix `scripts/ccd-rehome`.** Keep it to one file, stdlib only, Python 3.9+, with no new dependencies. Classify
   new record fields in `KNOWN_KEYS`, `ACCOUNT_BOUND` or `TRANSIENT`, and new per-account entries in
   `KNOWN_ENTRIES` plus the logic in `move()`.
5. **Prove the test bites.** Run `python3 -I scripts/selftest.py` until it passes. Then break your fix on purpose
   and confirm the test fails. Then run the whole project's tests: `python3 tests/run_all.py` in the checkout.
6. **Update the docs in the same change:** `references/mechanics.md` (the evidence and the contract row); this
   file, if behaviour or rules changed; the project's `docs/` pages, if a human-facing step changed; and the
   project's `CHANGELOG.md`, with the date and Desktop version.
7. **Commit** with a message naming the Desktop version and OS. Then **offer** the user to share it upstream as a
   pull request (the project's CONTRIBUTING.md:
   https://github.com/kulogix/session-rehome/blob/main/CONTRIBUTING.md). Push or open the PR only with their
   go-ahead, and never include their emails, ids or paths. Add a `tested.json` entry (`R report …`) once the fix
   has run for real.
8. **Prefer refusing over guessing.** If the right fix is unclear, make the tool refuse that case with a clear
   message and record the open question in `mechanics.md`. A loud refusal is a correct intermediate state; a quiet
   wrong move is not.

## Files and settings

- `scripts/ccd-rehome`: the tool (one file, Python 3.9+, stdlib only).
- `scripts/selftest.py`: the self-test on synthetic profiles, including simulated macOS and Windows layouts
  (about a minute; mutation-tested). Run it after any edit; `SELFTEST_VERBOSE=1` shows the tool's output on
  failures.
- `tested.json`: the tool, Desktop and OS combinations that passed. `doctor` reads it; `report` makes a new entry.
- `references/mechanics.md`: storage layout, log lines, and the evidence for every rule.
- `references/cli-homes.md`: CLI homes in full: every rule, refusal, warning and message of a CLI move.
- `references/cli-homes-review-log.md`: how 0.11.0's CLI homes were reviewed, round by round (historical).
- `references/desktop5-fields.md`: the 138 record fields Desktop 5 added, each with its class and the reason.
- Human guides (install, several windows, switching accounts, troubleshooting): the project's `docs/` folder,
  https://github.com/kulogix/session-rehome/tree/main/docs.
- **Environment:**
  - `CCD_REHOME_PROFILES`, `CCD_REHOME_INSTANCES` (folders of profiles), `CCD_REHOME_CLI_HOMES`: extra paths.
  - `CCD_REHOME_DESKTOP`: the app binary for `launch`.
  - `CCD_REHOME_STATE`: the state and archive dir (overrides the state folder).
  - `CCD_REHOME_FALLBACK_MODEL` / `CCD_REHOME_LOCAL_MODEL_RE`: the model rewrite.
  - `CCD_REHOME_HOME`, `CCD_REHOME_SANDBOX`, `CCD_REHOME_PLATFORM`: tests only.
  - `CCD_REHOME_FAULT`, `CCD_REHOME_OPEN_FILES` (references/cli-homes.md): self-test only, honoured only with
    `CCD_REHOME_SANDBOX=1`.
