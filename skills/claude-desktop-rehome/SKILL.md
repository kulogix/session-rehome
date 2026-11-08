---
name: claude-desktop-rehome
description: >-
  List Claude Desktop Code sessions by account and move them between accounts, for ANY Desktop profile (the plain
  `claude-desktop` window or any `--user-data-dir`, e.g. ~/.claude-instances/acct-e or a path anywhere) and ANY
  number of accounts. Use when "I logged out of X and into Y and my sessions are gone", "switch this window from my
  personal to my work account", "Desktop doesn't show my old sessions", "move these sessions to account Z", "which sessions
  belong to which account", "which window is logged in as which email", "is this instance signed out". Also converts terminal (CLI) Claude Code
  sessions into Desktop sessions and back ("show my CLI sessions in Desktop", "continue this Desktop session in
  the terminal") without Desktop's transcript-rewriting import. Discovers
  profiles, account id -> email, signed-in state and login expiry; moves any or all sessions (Code, optionally
  Cowork) with their task suggestions, scheduled tasks and queued background work; archives first, undoes exactly,
  verifies from Desktop's own log. Linux verified; macOS and Windows experimental. NOT for moving sessions to
  another machine (a transcript-transplant job), and it never signs in or out for the user.
---

# claude-desktop-rehome

The script is `~/.claude/skills/claude-desktop-rehome/scripts/ccd-rehome`, Python 3.9+, stdlib only. Below, `R`
stands for that path.

## Start here

| The user says / you need | Run |
|---|---|
| "my sessions are gone after I switched accounts" | `R status`, then the `fix:` command it prints, then `R launch P` and `R verify P` |
| "which window is signed in as whom" | `R profiles` |
| "what sessions does this window have, under which accounts" | `R sessions P` |
| "move these sessions to account X" | `R sessions P` (get ids), then `R move P --to X --only ID ... --dry-run`, then without `--dry-run` |
| "fix all my windows" | `R rehome --all` |
| "undo that" | `R rollback P ARCHIVE` (the name the move printed) |
| put a session record into a profile on ANOTHER machine (with session-transporter) | `R export-record P --only ID --out r.json` here; `R adopt P2 --record r.json --cwd NEW_DIR` there (the transporter's bundle does both for you) |
| "move this session to my other Desktop window" (another user-data-dir, same machine) | `R move P --only ID --to-profile P2 [--to EMAIL] --dry-run`, then without `--dry-run` (both quit) |
| "show my terminal (CLI) sessions in Desktop" | `R cli-sessions`, then `R register P --cli-session-id ID` (never Desktop's "Recover CLI sessions") |
| "continue this Desktop session in the terminal" | `R resume-cli P --only ID` (prints the checked command); `R unregister P --only ID` to drop the Desktop record too |
| first use on a machine | `R doctor`, then `python3 -I <skill>/scripts/selftest.py` |
| it worked on a new Desktop version / OS | `R report <what you ran>`, then offer the user to submit it (CONTRIBUTING.md) |

`P` is a profile: `default` (the plain window), a folder name under `~/.claude-instances` (`acct-e`), or any path
to a user-data-dir.

## Rules for the agent

1. **Read state before acting.** Run `status` or `sessions` with `--json`, and parse the JSON rather than the
   text. Never infer accounts from folder names: they are opaque UUIDs, and stray `<account>/<org>` folders are
   normal.
2. **`--dry-run` first** and show the user the plan, unless they asked for exactly that move. A dry run writes
   nothing at all (tested: the whole home folder is byte-identical afterwards) and works while the window is
   open; the real run needs it quit.
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
   `config.json`, or create folders by hand.
7. **After every real move,** `launch` and wait about 20 s, then `verify`. Report:
   - titles moved, from which email to which;
   - the archive name and undo command;
   - the `verify` result;
   - "reconnect claude.ai connectors under the new account";
   - any `transcript MISSING` sessions (they list but won't open; the tool didn't cause it).
8. **If another tool on the machine also moves Desktop session records** (for example a switcher between Anthropic
   and a local inference gateway), use this one for account changes and that one for gateway changes.
9. **If the tool misbehaves or `doctor` reports DRIFT, fix the skill itself.** See "Maintaining this skill"
   below.
10. **When it worked on an untested combination** (NOTE above), run `R report <what ran>` and offer the user to
    submit it. The entry contains nothing identifying.

## What Desktop does (why sessions "vanish")

Each Code session record lives at `<profile>/claude-code-sessions/<accountUuid>/<orgUuid>/local_<id>.json`.
Desktop lists only the folder of the account and org that is signed in. After a sign-in change the old records
are still there, just not listed, and the conversations are untouched in `~/.claude/projects/`. Moving the small
record file into the signed-in account's folder brings the session back. Records contain no account ids, so the
folder alone decides ownership.

## Commands

```
R profiles | status [P ...] | sessions P | accounts       [--json]   read-only reports
R rehome P ... | --all              [--include-cowork] [--dry-run]   everything stranded -> signed-in account
R move P [--to ACCT] [--to-org ORG] [--from ACCT ...] [--only ID ...] [--include-cowork] [--dry-run]
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
- **Discovery** (`profiles`, `status`, `--all`) finds:
  - the default profile and `~/.claude-instances/*`;
  - the `--user-data-dir` of running Desktops and of `.desktop` launchers;
  - every path the tool was ever given;
  - `$CCD_REHOME_PROFILES` (paths joined by `:`, or `;` on Windows).

## What moves, and how

| Item | Handling |
|---|---|
| Record `local_<id>.json` | moved. If the target already has that id, the newer `lastActivityAt` wins and both copies are kept |
| Queued background work `armedWorkAtQuit` | kept in the record (it resumes at next launch) and reported |
| Effort, UltraCode, permissions, title, cwd, prompt suggestion, artifacts | kept |
| `remoteMcpServersConfig`, `withheldConnectorHosts`, `remoteControlAutoEligible`, `steeredByRemoteClient`, `bridgeSessionIds` | dropped (connector and Remote Control state of the old account) |
| `error*`, `cliBinaryPin` | dropped (Desktop recreates them) |
| Local-gateway-only model | replaced with `$CCD_REHOME_FALLBACK_MODEL` |
| `backlog/tasks.json` task suggestions | merged by id. With `--only`, just those whose `originSessionId` moved |
| `scheduled-tasks.json` | merged by id (full moves) |
| `deleted_*` tombstones | copied, so deleted sessions stay deleted |
| Cowork `local-agent-mode-sessions/<acct>/<org>/local_*` | moved with `--include-cowork`; `rpm/` (plugin cache) left |
| Conversations `~/.claude/projects/**.jsonl` | never touched |
| `scratch-workspaces/<acct>/…` | left in place: the cwd locates the transcript. Reported |
| Cookies, tokens, `spaces-present/*/link-key`, `config.json` | never touched |

**Target org**, in order of preference:
1. `--to-org`;
2. Desktop's log for that account in this profile;
3. the account's only org folder in this profile;
4. the account's only known org anywhere. This is safe because an account's org is the same in every profile; the
   tool prints "inferred".
If several orgs are possible, it refuses.

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
- **Desktop → CLI: `resume-cli`** prints `cd <folder> && claude --resume <id>` after checking the
  conversation is not open in any process (two writers fork the history). The session stays listed in
  Desktop. **`unregister`** removes the Desktop record (archived, undone by `rollback`) when it should be
  CLI-only.
**What carries over, and what does not**

| | Desktop → terminal (`resume-cli`, `unregister`) | terminal → Desktop (`register`) |
|---|---|---|
| The conversation (every turn, thinking, tool results, sidecars, todos) | kept: same file, never edited | kept: same file, never edited |
| Desktop's per-session settings (title, model, effort, permission mode, UltraCode, grants) | stay in the Desktop record; `unregister` archives them | restored from that archive when one exists; otherwise Desktop defaults |
| Which **account** runs the next turn | the terminal CLI's login (**warned** if it differs from Desktop's) | the Desktop window's account |
| Thinking-block signatures across accounts | same person, different account: worked before; **across orgs: unverified** | same |
| Model ID | an **older terminal CLI may not know it** (measured: 2.1.263 rejected `claude-opus-5-5`; **warned**) | Desktop's bundled CLI is usually the newest |
| Tools | Desktop-only tools (Desktop's MCP servers, computer use, browser pane, scheduled tasks) are unavailable in the terminal; old calls to them stay in the history | the terminal's own MCP setup, if any, is whatever Desktop loads from the same settings files |
| Queued background work at quit (`armedWorkAtQuit`) | stays with Desktop | n/a |
| Never at the same time | an open conversation in both forks the history; `resume-cli` refuses while it is open | `register` refuses while it is open |

- **Measured, a full round trip** (Linux, Desktop 2.31226.1, CLI 2.1.319, same account):
  1. a terminal turn planted ORCHID-42;
  2. `register`;
  3. a turn in Desktop recalled it and planted TULIP-7;
  4. a terminal `--resume` recalled both in order.
  The file reads `sdk-cli → claude-desktop → sdk-cli`, every earlier stage's bytes are unchanged, no message
  has two children (no fork), and the thinking signatures were accepted on both sides.
- **Do not start the terminal leg from inside a Desktop session.** A `claude` launched from a shell inside
  Desktop inherits its environment: it was stamped `claude-desktop` and ran as that session's child.
  `resume-cli` warns and prints an `env -i` form. The
  Desktop-made Fibonacci transcript was loaded by plain CLIs on macOS (2.1.119) and Linux arm64 (2.1.121).
- **The `mangle()` copy** in the script mirrors session-transporter's canonical `mangle.py`; the self-test
  cross-checks them whenever both are installed.

## The transplant interface: `export-record` / `adopt`

session-transporter moves *conversations* between machines; this tool owns *Desktop records*. They meet here:
- **`export-record`** writes one record as `ccd-record/1`: `{format, tool, desktop, exported_utc, record,
  notes}`. Account-bound and transient fields are stripped, and it carries no account or org ids.
- **`adopt`** files such a record into any profile: by default under the signed-in account, or under `--to`
  (and `--to-org`). It runs the same validation as a move (ERROR always refuses; DRIFT refuses unless
  `--accept-drift`) and is **idempotent**: a conversation already registered there is left alone. It
  **refuses** when that conversation is already filed under another account in the profile; use `move` for
  that.
- **`--cwd`** rewrites `cwd` / `originCwd`, and drops the fields bound to the old machine (`HOST_BOUND`):
  git anchors, `planPath`, `shellFolders`, Chrome tab group, computer-use display, screenshot and app grants.
  Session settings are kept.
- **Every adopt is archived** (kind `adopt`) and undone exactly by `rollback`.

## Troubleshooting (messages and what to do)

| Message | Meaning | Action |
|---|---|---|
| `is running … Quit it` | the window is open | the user quits it (File > Quit), or `R quit P` with their OK |
| `Desktop ignored the quit signal` | that build does not honour SIGTERM (seen: 1.9255.2 Linux arm64) | the user quits from the menu; if the window is frozen, force-close it (records on disk are safe), then relaunch |
| `refusing: this command is running INSIDE P` | you would kill your own session | ask the user to quit P |
| `not signed in (signed-out/expired)` | no live login in that window | the user signs in, then re-run (or name a target with `--to`) |
| `no org known … (ambiguous …)` | the account has several orgs and none is evident | the user opens the Code tab once while signed in and quits; or pass `--to-org` |
| `account '…' matches 0 known accounts` | email or uuid never seen on this host | check the spelling with `R accounts`; sign in to it once somewhere |
| `not a Desktop profile (no config.json)` | wrong folder, or never launched | launch it once, or fix the path |
| `cannot read … nothing was changed` | a corrupt record or side file | inspect that file; nothing was written |
| `these conversations are open in another process` | the session is resumed in a terminal or another window | close it there first |
| `verify: MISMATCH` | Desktop loaded fewer than exist | quit, relaunch, verify again; if it persists, check `sessions P` for unreadable records |
| `verify: has not logged loading … yet` | launched but the log line hasn't appeared yet | wait, open the Code tab, re-run |

## Platform support

| | Linux | macOS | Windows |
|---|---|---|---|
| Status | **verified** (x86_64 and aarch64; see `tested.json`) | partly verified: self-test and read-only commands on a real Mac (Desktop 4.23118.0); no live move yet | experimental: CI self-test only |
| Default profile | `~/.config/Claude` | `~/Library/Application Support/Claude` | `%APPDATA%\Claude` |
| Logs | `<profile>/logs` | `~/Library/Logs/Claude` (confirmed), shared by all instances; the tool uses only path-bearing lines there | `<profile>\logs` |
| Running check | `/proc` + `SingletonLock` | one `ps` + `SingletonLock` | one PowerShell CIM query + `lockfile` |
| Open-conversation check | `/proc/*/fd` | `lsof` | not available (warns) |
| `quit` | SIGTERM (Desktop quits cleanly) | SIGTERM (unverified) | **refused**: Python can only hard-kill there |
| `launch` | `claude-desktop` | `open -n -a Claude --args …` | `%LOCALAPPDATA%\AnthropicClaude\claude.exe` (a guess) |

All three can be overridden with `CCD_REHOME_DESKTOP`. On a new OS: run `doctor`, then the self-test, and make the
first move with `--dry-run`, then `verify`.

## Nuances that bite

- **Transitional log lines.** At a sign-in change Desktop logs the old account paired with the new org for about a
  second. Taken at face value, they send records to a folder Desktop never reads, typically when switching *back*
  to an account used before. The tool filters them everywhere.
- **A profile stores only the email it is signed in to now.** The registry
  (`~/.claude-instances/_rehome/accounts.json`) remembers every account/email pairing ever seen.
- **"Log out" in the app ends that login on the server.** Coming back needs a human sign-in.
- **Per-identity, not migrated:** claude.ai connectors (reconnect them), sidebar custom groups (re-create them),
  and Remote Control links.
- **Cowork:** on Desktop 4.x a Cowork store also holds your *spaces* and *agents*. Until their link to sessions
  is understood, a Cowork move (`--include-cowork`) refuses whenever they hold content (mechanics.md §5a). Code
  moves are unaffected.
- **`desktop` version** means the version that *last ran* the profile (from its log), not the installed package.
  After an upgrade, launch once before moving, so the files are in the new version's format.
- **`<name>-3p` profiles** are Desktop's own separate profile for a third-party inference gateway. They have no
  Anthropic account and are rejected.
- **Archives accumulate** in `~/.claude-instances/_rehome/archive/` (a few KB each). Old ones are safe to delete.

## Maintaining this skill (agents: this is part of the job)

This folder is the **one** copy of the skill: a git checkout of its canonical repo. Desktop, macOS and Windows will
change under it. Whoever uses it and finds it wrong (usually an agent) brings it up to date **here**.

**Never:**
- copy the script somewhere else to patch it;
- write a "v2" or a one-off variant script;
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
1. **Reproduce and measure.** Find the real evidence: a record's fields, the log lines, the folder layout. Read the
   matching row of the contract in `references/mechanics.md` §0, and decide what changed. Not knowing what a new
   field is counts as a finding to investigate, not a reason to guess.
2. **Write the test first.** Add a synthetic fixture to `scripts/selftest.py` that reproduces the new behaviour, and
   watch it fail. Never put real user data in fixtures.
3. **Fix `scripts/ccd-rehome`.** Keep it to one file, stdlib only, Python 3.8+, with no new dependencies. Classify
   new record fields in `KNOWN_KEYS`, `ACCOUNT_BOUND` or `TRANSIENT`, and new per-account entries in
   `KNOWN_ENTRIES` plus the logic in `move()`.
4. **Prove the test bites.** Run `python3 -I scripts/selftest.py` until it passes. Then break your fix on purpose
   and confirm the test fails.
5. **Update the docs in the same change:**
   - `references/mechanics.md`: the evidence, plus the contract row;
   - this file, if behaviour or rules changed;
   - `README.md`, if a human-facing step changed;
   - `CHANGELOG.md`, with the date and Desktop version.
6. **Commit in this folder** with a message naming the Desktop version and OS. Then **offer** the user to share
   it upstream (https://github.com/kulogix/claude-desktop-rehome) as a pull request, following CONTRIBUTING.md.
   Push or open the PR only with their go-ahead, and never include their emails, ids or paths. If the folder isn't
   a git checkout, tell the user, and suggest replacing it with a clone so the fix isn't stranded.
   - Also add a `tested.json` entry (`R report …`) once the fix has run for real.
7. **Prefer refusing over guessing.** If the right fix is unclear, make the tool refuse that case with a clear
   message and record the open question in `mechanics.md`. A loud refusal is a correct intermediate state; a quiet
   wrong move is not.

## Files and settings

- `scripts/ccd-rehome`: the tool.
- `tested.json`: tool, Desktop and OS combinations that passed (`doctor` checks this machine against it; `report`
  makes a new entry).
- `CONTRIBUTING.md`: issues, pull requests, CI. `.github/`: issue and PR templates; CI runs the self-test on
  Linux, macOS and Windows.
- `scripts/selftest.py`: 112 checks on synthetic profiles, including simulated macOS and Windows layouts, about 40
  s. Mutation-tested. Run it after any edit; `SELFTEST_VERBOSE=1` shows the tool's output on failures.
- `README.md`: human runbook, with install steps for a new machine.
- `references/mechanics.md`: storage layout, log lines, evidence for every rule.
- **Environment:**
  - `CCD_REHOME_PROFILES`: extra profile paths.
  - `CCD_REHOME_DESKTOP`: the app binary for `launch`.
  - `CCD_REHOME_STATE`: the state and archive dir.
  - `CCD_REHOME_FALLBACK_MODEL` / `CCD_REHOME_LOCAL_MODEL_RE`: the model rewrite.
  - `CCD_REHOME_HOME`, `CCD_REHOME_SANDBOX`, `CCD_REHOME_PLATFORM`: tests only.
- **Related:** moving sessions to *another machine* is a different job (transcripts and paths change); if a
  cross-machine transplant skill such as `session-transporter` is installed, use that.
