# mechanics.md: how Claude Desktop ties Code sessions to accounts

This is the evidence behind every rule in SKILL.md (and in `cli-homes.md`, its CLI-home rules in full). It was first
measured on 2026-11-07 on Linux, with Claude Desktop 2.31226.1 (Electron 44), five profiles and two accounts.
Accounts are shown as `<A>` (old) and `<B>` (new), orgs as `<OA>` and `<OB>`. **When Desktop changes, this file is
updated together with the code** (see SKILL.md "Maintaining this skill").

## 0. The contract (what the tool relies on, and how to re-check it)

| # | Fact the tool depends on | Used in | Re-check | `doctor` watches it? |
|---|---|---|---|---|
| C1 | Records live at `<profile>/claude-code-sessions/<acct>/<org>/local_<id>.json` and contain no account id | everything | `ls` a profile; `grep` a record for the account uuid | partly (unknown entries) |
| C2 | Desktop lists only `<signed-in acct>/<its org>` | `move` target | sign in, open the Code tab, look for `Loaded N persisted sessions from …` | yes (log line present) |
| C3 | Log line `[LocalSessionManager] Initialization succeeded — accountId=…, orgId=…` | target org | `grep "Initialization succeeded" logs/main.log` | indirectly |
| C4 | Log line `Loaded N persisted sessions from <path>` | target org, `verify` | `grep "persisted sessions" logs/main.log` | yes |
| C5 | Transitional pair at sign-in (old account + new org, then new + new, within seconds) | org filter | sign out and in, read the log | no: selftest "switching BACK" |
| C6 | Login events: `Login-state transition (loggedOut: X → Y, …)` (newer builds) or `claude.ai account active and logged in` / `[account] User is logged out` (all builds; the only ones on 1.9255.2). The NEWEST one decides | signed-in verdict | sign out and in, read the log | no: selftest "older Desktop builds" |
| C7 | The claude.ai `sessionKey*` cookie in `Cookies` / `Network/Cookies` marks a live login | verdict, expiry | `sqlite3` on a copy: name and expiry columns only | no |
| C8b | `config.json` `lastKnownAccountUuid` names the signed-in account. **Older builds (1.9255.2) never write it**; the account is then taken from the newest real init line (C3/C4) | account | read config.json | no: selftest |
| C8 | IndexedDB holds `<uuid> … email_address … <email>` for the signed-in account | emails | `accounts` shows the email | no |
| C9 | The record key list and its keep / drop classes (§5) | `move` rewrite | `doctor` | **yes** (unknown fields) |
| C10 | Per-account side files: `deleted_*`, `backlog/tasks.json` (items with `id`, `originSessionId`), `scheduled-tasks.json` (`scheduledTasks` with `id`) | `move` | `doctor` | **yes** (unknown entries) |
| C11 | `SingletonLock` → `<host>-<pid>` (Linux, macOS); `lockfile` held open (Windows) | running check | look while Desktop runs | no |
| C12 | SIGTERM makes Desktop quit cleanly (`willQuit … quitting` in the log). **Not on 1.9255.2 Linux arm64: it ignores SIGTERM**; `quit` detects that after 30 s and says so | `quit` | `quit`, then read the log | no |
| C14 | Linux launcher name: `claude-desktop`, or `claude-desktop-unofficial` (community Debian package from 4.x; the old name became an empty transitional package and `/usr/lib/claude-desktop/` was removed **under a running instance**, which then could not quit) | `launch`, `doctor` | `command -v` both | yes (Desktop app line) |
| C13 | Every launch logs `Starting app {` followed by `appVersion: 'X.Y.Z'` | Desktop version (`doctor`, `report`, `tested.json`) | `grep -A2 'Starting app {' main.log` | yes ("Desktop ?") |

If a re-check fails, the tool is out of date. Fix it as described in SKILL.md and change this table.

**Validation before every move** (`validate()` in the script) checks each folder the move touches:

| Item | ERROR (always refuse) | DRIFT (refuse a real run unless `--accept-drift`) |
|---|---|---|
| `local_<id>.json` | not JSON or not an object; `sessionId` ≠ file name; a core field has the wrong type (`cliSessionId`, `title`, `model`, `cwd`: string; `lastActivityAt`, `createdAt`: number; `sessionSettings`, `armedWorkAtQuit`: object; `priorCliSessionIds`: list) | a key outside `KNOWN_KEYS` |
| `backlog/tasks.json` | not `{"items": [{"id": …}, …]}` | anything else inside `backlog/` |
| `scheduled-tasks.json` | not `{"scheduledTasks": [...]}` | |
| `deleted_*` | a folder | content not a ms timestamp |
| any other entry | | not matched by `KNOWN_ENTRIES` (it would be left behind) |

`doctor` runs the same checks across all profiles without moving anything, and compares (tool, Desktop version,
OS family) against `tested.json`. The Desktop version comes from the profiles' own `config.json`
(`updaterLastSeenVersion`).

## 1. Storage layout

```
<profile>/config.json                        lastKnownAccountUuid, oauth:tokenCache(V2) (encrypted)
<profile>/Cookies  (or Network/Cookies)      claude.ai sessionKey*: the login credential
<profile>/IndexedDB/https_claude.ai_0.*      cached account object: <uuid> ... "email_address" ... <email>
<profile>/logs/main.log, main1..N.log        rotated; the evidence for orgs and login state (macOS: see §8)
<profile>/claude-code-sessions/<acct>/<org>/
    local_<sessionId>.json                   one per Code session (small; no account ids inside)
    deleted_<id>                             tombstones (content: a ms timestamp)
    backlog/tasks.json                       {"version", "items":[{id, originSessionId, ...}]}  task suggestions
    scheduled-tasks.json                     {"scheduledTasks":[...], ...}
<profile>/local-agent-mode-sessions/<acct>/<org>/   Cowork, same layout; rpm/ = per-org plugin cache
<profile>-3p/                                Desktop's separate profile for a third-party inference gateway
<CLI home>/projects/<mangled-cwd>/<cliSessionId>.jsonl   the conversation; never touched by a Desktop move
```

The CLI home is the one the window reads: `CLAUDE_CONFIG_DIR ?? ~/.claude` (§4b), so `~/.claude` for a window
started without `CLAUDE_CONFIG_DIR`. Profiles that read the same home share its conversations; each
`CLAUDE_CONFIG_DIR` home has its own `projects/`.

## 2. What Desktop reads

On start, and on every login-state change:

```
[LocalSessionManager] Initialization succeeded — accountId=<B>, orgId=<OB>, existingSessions=N
Loaded N persisted sessions from <profile>/claude-code-sessions/<B>/<OB>
```

It reads only `<B>/<OB>`. Records anywhere else are invisible: no error and no recovery prompt. `verify` compares
`Loaded N` with the records that existed at that time. Records created afterwards don't count, and Desktop
rewrites records while it runs, so modification times prove nothing. First measurement: 5 of 5 profiles matched
exactly after their moves.

## 3. The transitional pair

At a sign-in change Desktop logs, within about 2 s:

```
10:57:46  Initialization succeeded — accountId=<A> (OLD), orgId=<OB> (NEW org), existingSessions=4
10:57:46  Loaded 0 persisted sessions from …/claude-code-sessions/<A>/<OB>
10:57:48  Initialization succeeded — accountId=<B> (NEW), orgId=<OB>, existingSessions=0
10:57:48  Loaded 0 persisted sessions from …/claude-code-sessions/<B>/<OB>
```

The first pair is a transitional state, not a real pairing. Rule: skip an (account, org) observation when the
next distinct one, within 10 s, has a different account and the same org. Without it, switching **back** to an
account the profile used before picks the other account's org as the target. Covered by selftest "switching
BACK"; disabling the rule fails 4 checks.

## 4. Login state

- **The credential:** the claude.ai `sessionKey` cookie. OAuth tokens are minted from it and cached. When the
  cookie names another account, Desktop logs `oauth: sessionKey names a different account than the flow; not
  minting`. The cookie, not `config.json`, carries the login.
- **"Log out" in the app:** `Navigated to /logout, synthesizing logged-out`, then
  `Login-state transition (loggedOut: false → true, uuid: <A> → <none>), clearing oauth cache`. This ends the
  login on the server. Coming back means signing in again.
- **Sign-in:** `Login-state transition (loggedOut: true → false, uuid: <none> → <B>)`.
- **Cookie lifetime:** about 28 days, extended on use.
- **Tool verdict:**
  - no `sessionKey` cookie, or the last transition is logged-out → `signed-out`;
  - cookie past expiry → `expired`;
  - otherwise `signed-in` as `lastKnownAccountUuid`.
  The tool reads only the cookie's name and expiry, from a temporary copy, never its value. A cookie that can't be
  read (locked on Windows) gives `unknown`.

## 5. Record keys and what a move does with them

Initial inventory: 22 records plus their archived copies, 59 distinct keys. The list is `KNOWN_KEYS` in the
script, and `doctor` flags any key outside it.
- **Session state, kept:**
  - `armedWorkAtQuit` (`{at, exitKind, cronCount, durableCronCount, backgroundTaskCount}`): background work
    queued at quit, resumed at next launch;
  - `promptSuggestion`, `lastTurnCutShort`, `devIntents`, `envScopeId`, `scratchOfferFolder`,
    `transcriptUnavailable`;
  - `publishedArtifacts` (`[{url, title, sourcePath}]`): the artifacts stay owned by their account;
  - effort, model, `sessionSettings` (UltraCode), permissions, title, cwd, and the rest.
- **Account-bound, dropped:**
  - `remoteMcpServersConfig` and `withheldConnectorHosts` (claude.ai connectors);
  - `remoteControlAutoEligible`, `steeredByRemoteClient`, and `bridgeSessionIds` (`["session_…"]`) for Remote
    Control.
  Carrying them would point a session at another account's connectors and bridges.
- **Transient, dropped:** `error`, `errorAt`, `errorRows`, `priorErrorMark`, `cliBinaryPin`. Desktop recreates
  them if still true.
- **Desktop 4.x (first seen 4.23118.0, macOS 26.6), 18 new fields, all classified session state, kept:**
  - computer-use grants for the session: `cuAllowedApps` (`[{bundleId, displayName, grantedAt}]`),
    `cuGrantFlags` (`{clipboardRead, clipboardWrite, systemKeyCombos}`), `cuLastScreenshotDims`,
    `cuSelectedDisplayId`;
  - Claude in Chrome: `chromeAllowedDomains` (`["host:port"]`), `chromeTabGroupId` (int);
  - turn bookkeeping: `turnBoxDeclared`, `turnBoxMounted` (bool), `turnWrapUp` (`{description, …}`),
    `lastTurnEdgeAt`, `contextExceededCount`, `queryCrashes` (`[{assistantUuid, resultUuid, …}]`),
    `interruptedAwaitingPerson`;
  - history and links: `previousTitles`, `planPath` (a file in `~/.claude/plans/`), `shellFolders`,
    `lastAssistantCliSessionId`, `spawnedFrom` (`{sessionId, taskId, title}`: the parent session).
  None refers to claude.ai connectors or Remote Control, which is the test for ACCOUNT_BOUND. They were classified
  from value shapes on one machine; if a later version shows one of them to be account-bound, move it.
- **Host-bound fields (dropped by `adopt --cwd`, kept by same-host moves):** `gitAnchors`,
  `gitAnchorsFolderRealpath`, `gitAnchorsLookupOnly`, `planPath`, `shellFolders`, `chromeTabGroupId`,
  `cuSelectedDisplayId`, `cuLastScreenshotDims`, `cuAllowedApps`. They name the origin machine's filesystem,
  displays, apps or browser tabs, so on another host they would point at things that don't exist. They are
  dropped rather than rewritten; Desktop records them afresh as the session is used. Classified from value
  shapes; adopted records were then loaded by Desktop's CLI on macOS and Linux ARM (session-transporter
  bundle test, 2026-11-07).
- **Sidebar custom groups** are per identity: `LocalSessions.setCustomGroups: … dropped (identity mismatch)`. They
  are not migrated.

## 4a. CLI vs Desktop conversations

- **Same files.** A conversation is `~/.claude/projects/<mangle(realpath(cwd))>/<cliSessionId>.jsonl`,
  whoever started it. A Desktop session adds `claude-code-sessions/<acct>/<org>/local_<id>.json`
  (`cliSessionId`, `cwd`, …). Desktop runs its bundled CLI with `--resume <cliSessionId>` from `cwd`.
- **The stamp:** each transcript record has `entrypoint`: `claude-desktop` (Desktop turns), `cli`
  (interactive terminal), `sdk-cli` (headless). Measured on 25 Desktop and 7 CLI-only transcripts here.
- **Desktop's own recovery** scans for "recoverable CLI transcripts" (no record), skipping desktop-stamped
  ones after a cutoff date (`CCD-SessionRecovery … desktop-stamped transcripts re-admitted only if
  started before …`). Its import strips thinking blocks in place, so it is never used. `register`
  writes the record instead and leaves the transcript byte-identical. Measured: register → launch →
  `Loaded 4 persisted sessions` (was 3), transcript sha256 unchanged.
- **A full round trip** (measured on Linux, Desktop 2.31226.1, CLI 2.1.319, one account): a terminal turn planted
  ORCHID-42; `register`; a turn in Desktop recalled it and planted TULIP-7; a terminal `--resume` recalled both in
  order. The file reads `sdk-cli → claude-desktop → sdk-cli`, every earlier stage's bytes are unchanged, no message
  has two children (no fork), and the thinking signatures were accepted on both sides. The Desktop-made test
  transcript was loaded by plain CLIs on macOS (2.1.119) and Linux arm64 (2.1.121).
- **The `mangle()` copy** in the script mirrors session-transporter's canonical `mangle.py`; the self-test
  cross-checks them whenever both are installed.

## 4b. CLI homes (CLAUDE_CONFIG_DIR)

Where a fact below comes from session-transporter, it is that skill's measurement or code excerpt: its
`references/mechanics.md` and `references/evidence-base.md`, harvested 2026-08-01 from a real migration (CLI
2.1.215 reading transcripts written by 2.1.170 to 2.1.187). The CLI-home feature itself was specified in writing
from the facts below and implemented to that spec; what was measured for it is said item by item.

- **A CLI home is a Claude Code config dir** [C]: Claude Code's `getClaudeConfigDir` reads `$CLAUDE_CONFIG_DIR` and
  falls back to `~/.claude`, and a transcript is `$CLAUDE_CONFIG_DIR/projects/<key>/<id>.jsonl` (session-transporter
  mechanics.md §1.1 and §1.2). [M, 2026-11-08, Claude Code CLI 2.1.319]: a real 0.5 MB transcript that this code
  had moved from one synthetic home to another was found and loaded by `claude --resume <id>` with
  `CLAUDE_CONFIG_DIR` set to the target home (it reached the network; the API was pointed at a closed port, so no
  turn was spent), and the same command in the source home reported "No conversation found". That is the one
  measurement so far: the orchestrator's run on 2026-11-08 with Claude Code 2.1.319 (the agent that coordinated
  the 0.11.0 review), whose log is not kept here and whose OS was not recorded. It will be re-run with the
  project's `tests/e2e_real_cli.py`, a manual test (not part of `run_all.py`) that does the same on two synthetic
  homes with a small synthetic transcript: `move`, then `claude -p --resume <id> ping` in both homes with the API at
  a closed port, then `rollback` and the reverse; each new run is to be recorded here with its date, CLI version
  and OS. Recorded runs of `tests/e2e_real_cli.py`: 2026-11-09, Claude Code 2.1.319, Linux 7.0 x86_64, Python 3.14.4, against the final 0.11.0 code: all six steps passed (move; found in the target home, "No conversation found" in the source; rollback; the reverse). An earlier run on the same day against the second-round code also passed. No move has run on a real signed-in home. That people run one home per account (`alias claude-work='CLAUDE_CONFIG_DIR=~/.claude-work
  claude'`), each with its own `settings.json`, `sessions/` and login, is [I] (Claude Code's documented setting; not
  measured here). A folder counts as a home when it has `projects/`, `.claude.json`, `.credentials.json` or
  `settings.json` and no `config.json` (a Desktop profile has one) [D: the tool's rule].
- **Inside a home**: [M] (session-transporter evidence-base.md §1, a real `~/.claude`, 2026-08-01, CLI 2.1.215):
  `projects/<key>/<session-id>.jsonl` and the same-named sidecar dir (`subagents/`, `tool-results/`,
  `workflows/`), `projects/<key>/memory/` (keyed by project, shared by its sessions), `tasks/<id>/`,
  `session-env/<id>/` (empty, recreated at session start), `sessions/<pid>.json` (a live-process registry with
  `pid`, `sessionId`, `cwd` and more) beside `sessions/<pid>.<hash>.key` (a SECRET), `history.jsonl` (the
  terminal's prompt history), `settings.json`, `.credentials.json`, `shell-snapshots/`, `debug/`. [I] (from the
  spec, not seen there): `todos/<id>*.json` (that host had no `todos/` at all), what `file-history/<id>/` holds
  (it was empty), a `status` key in `sessions/<pid>.json`, and `plans/`. The tool moves `todos/` and
  `file-history/` items when they exist and never needs to read them.
- **Account and login**: `~/.claude.json` `oauthAccount` holds `accountUuid`, `emailAddress`, `organizationUuid`,
  `organizationName` for the default home [M] (§6 below, 2026-11-07; and session-transporter evidence-base.md §1.3,
  2026-08-01). That any other home keeps it in `<home>/.claude.json` is [I] (spec; not measured). The login is
  `.credentials.json` where it exists [M] (session-transporter evidence-base.md §1.3: `claudeAiOauth`, 2026-08-01);
  that on macOS it is normally in the Keychain, keyed to the config dir, is [I] (never tested here). So the tool
  checks existence and size only, never contents, and on macOS reports `unknown` when no file exists [D].
- **No per-account filing**: transcript records contain no account or org ids [M] (session-transporter
  evidence-base.md §2.13: an exhaustive key enumeration, 2026-08-01, transcripts of CLI 2.1.170 to 2.1.187). That
  the CLI's session picker lists the current project folder's sessions whatever account is signed in is [I] (spec;
  not measured). Hence inside one home nothing is stranded after a sign-in change, and another account means
  another home [D].
- **Project key**: normally `mangle(realpath(cwd))` [M] (session-transporter mechanics.md §2 and §3.3,
  2026-08-01). That `CLAUDE_CODE_PROJECT_DIR_NAME` can pin the folder name is [I] (spec), so the tool reads the
  actual folder and takes a session's `cwd` from its transcript instead of computing the key.
- **Retention** [D: Claude Code's documentation, https://code.claude.com/docs/en/claude-directory, section
  "Cleaned up automatically", read 2026-11-09; not measured here]: at startup a home deletes transcripts older than
  `cleanupPeriodDays` from its settings (default 30 days; the minimum is 1, and `0` is a validation error). The same
  table lists `projects/<project>/<session>/subagents/` ("removed with the parent session transcript"),
  `tool-results/` and `mcp-tasks/` there, each deleted "once they're older than `cleanupPeriodDays`". A
  separate rule covers Desktop: Claude Code "keeps the transcript of a session you started or most recently
  continued in Claude Desktop or Cowork at any age", unless `desktopSessionCleanupPeriodDays` gives them an age
  limit; that needs Claude Code 2.1.248 or later, and earlier versions delete them after `cleanupPeriodDays`. Even
  then `cleanupPeriodDays` applies to them when managed settings set it or the HIPAA configuration applies. The same
  page says the cleanup pauses on a settings error with either setting explicitly set. That age means the file's
  mtime is [I] (the page says "older than"; not measured). The tool reads which rule applies from the transcript's
  most recent records: the `entrypoint` of the last record that has one, read from the tail (the last 256 KB after
  the first 400 lines), never the whole file; `claude-desktop` is a Desktop turn [M, §4a]. A Cowork turn's
  entrypoint is not known [I], so a Cowork transcript gets `cleanupPeriodDays`, the rule that warns; so does one whose
  tail holds no entrypoint.
- **Managed settings** [D: https://code.claude.com/docs/en/managed-settings, "Deploy a managed settings file" and
  "How Claude Code combines managed sources", and https://code.claude.com/docs/en/settings, "Settings precedence",
  read 2026-11-09; not measured here]: managed settings rank above every settings file. The managed sources rank:
  remote (server-managed) settings, then MDM or OS-level policies (the macOS plist, the HKLM registry key), then the
  managed settings files (`managed-settings.d/*.json` and `managed-settings.json`, in `/etc/claude-code/` on Linux
  and WSL, `/Library/Application Support/ClaudeCode/` on macOS, `C:\Program Files\ClaudeCode\` on Windows). Under
  `"merge"` Claude Code takes `cleanupPeriodDays` "from the highest-ranked source that sets it"; under the default
  `"first-wins"` it reads keys only from the highest-ranked source that delivers any policy key. The
  claude-directory page lists `remote-settings.json` in the config dir as the "Cached copy of server-managed
  settings for your organization, or `{}` when your organization has configured none". Claude Code "merges
  `managed-settings.json` first, then every `*.json` file in the directory in alphabetical order", and "ignores
  hidden files and files that don't end in `.json`"; for a single value such as `cleanupPeriodDays` "the later
  file's value replaces the earlier one". The tool reads `cleanupPeriodDays` and `desktopSessionCleanupPeriodDays`
  from the target's `settings.json`, its `remote-settings.json`, `managed-settings.json` and every
  `managed-settings.d/*.json` drop-in next to it (hidden files and other names skipped, as above; in the sandbox the
  same folder under `CCD_REHOME_HOME`) [D for the sources and their paths]. It does not model how Claude Code
  combines them (`"first-wins"`, `"merge"`, the drop-in order): for each setting it takes the shortest whole number
  of days that any of them sets (the target's `cleanupPeriodDays` counts as 30, the default, when its
  `settings.json` sets none), and the message names the source of that value. That rule is the tool's own choice,
  made on purpose [D, from the page above, for why: under `"first-wins"` a remote cache that delivers any policy key
  hides the file's value, so the target's own value, or the default, applies; a drop-in replaces the file's value;
  MDM, which the tool cannot read, can hide the file too]: Claude Code applies one of these values, so the
  shortest makes the tool warn, re-date and refuse `--keep-dates` wherever Claude Code could delete the transcript,
  more often than it would, never less. A managed value comes first on a tie. A managed `cleanupPeriodDays` (the
  shortest one) also applies to a Desktop transcript; the target's own does not. That the cache holds the settings
  keys at its top level, as `settings.json` does, is [I] (the page shows no example; no cache was seen here). Not
  read: MDM profiles, the registry, and the HIPAA configuration. Until the seventh round the tool took each key from
  the higher of two sources (the cache, then `managed-settings.json`) and read no drop-in, so a cache with other
  keys only, or a drop-in, made it miss a shorter value that Claude Code applies [D, reproduced on synthetic homes in
  the final review of round 6].
- **What a move does about it** [D, from the rules above]: a transcript the target's rule would delete is re-dated
  when it is moved or copied (its mtime set to now), and so is every file of its sidecar folders
  (`projects/<key>/<id>/`: `subagents/`, `tool-results/`, `mcp-tasks/`, `workflows/`), so the target does not delete
  its spilled tool outputs and its subagents' transcripts at its next start either; the archive records each file's
  mtime, and the in-flight undo and `rollback` give each back the mtime it had (unless its content changed since).
  `tasks/<id>/` and `file-history/<id>/` are not re-dated (see "No check"). One last continued in Desktop and
  older than `cleanupPeriodDays`, where the target's rule keeps it (no `desktopSessionCleanupPeriodDays` limit it is
  past, no managed `cleanupPeriodDays`), depends on the Claude Code version, on a move and on a `--copy` alike: the
  tool reads `claude --version` (the terminal CLI on `PATH`, once per run, as `resume-cli` does): 2.1.248 or later,
  it is not re-dated (a warning on a move, a note naming the version on a `--copy`); older, or not known (no
  `claude` on `PATH`, or no version in its output), it is re-dated as a terminal transcript would be. On a `--copy`
  whatever the target would delete (a terminal transcript, such a Desktop one, or one past a managed limit) is
  re-dated in the target: the copy (never the source), with its sidecar files, and the source keeps its dates.
  `--keep-dates` is refused on a move; on a `--copy` it keeps the copy's dates, and the warning says that the target
  would delete the copy at its next start (the source keeps its own). A rollback of a `--copy` removes a copy only
  when its content (size and sha256 of every file) is what was copied, so a re-dated copy is still the tool's and a
  copy that changed since is kept. The warning says which applied. Until the seventh round a `--copy` of such a
  Desktop transcript was never re-dated, whatever the version [D, final review of round 6: the `--copy` that
  `sessions PROFILE` prints for a window, with Claude Code 2.1.100]. Which Claude Code runs a home's cleanup is not known
  [I]: Desktop bundles its own, and a terminal `claude` older than Desktop's is the case the version check covers.
  Re-dating only postpones the deletion [D, from the documented rule]: a transcript's mtime moves only when it is
  written, so a conversation that gets no new turn in the target (opening it in Desktop is not a turn) is deleted
  there one period later. A home that is never started keeps its old transcripts, which is how a backup of
  `~/.claude` (`~/.claude-backup`) ends up with the only copy of a profile's old conversations. A plain move from such
  a backup into `~/.claude` would then lose the conversation a month later (the backup no longer has it, and a
  CLI-move archive holds a manifest only) [D, reproduced on synthetic homes in the 0.11.0 final review of round 3,
  by file mtime; the deletion itself is the documented rule above]. A plain move with `--keep-dates` would lose it at
  the target's next start, so the tool refuses that combination for a transcript the target's rule would delete
  [D, reproduced in the final review of round 4]. So every `move` command the tool prints for a conversation in
  another home, or for a whole home, is a `--copy` (the copy into `~/.claude` that `sessions PROFILE`, `register`
  and a rollback's warning print, and the copy into another account's home that `status` and `rehome` print; the
  round-4 claim to this effect was not true of `status` and `rehome` until the fifth round), and every warning on a
  plain move of a transcript older than `cleanupPeriodDays` (whatever its entrypoint, re-dated or not) says that
  the source no longer has it and names `--copy`, never `--keep-dates` [D; until the sixth round the not-re-dated
  Desktop case had only a note that said neither, final review of round 5]. A re-dated warning also says that
  re-dating only postpones the deletion.
- **Desktop reads one home** [C]: Claude Desktop reads its Code sessions' transcripts through `getClaudeConfigDir`,
  so `CLAUDE_CONFIG_DIR ?? ~/.claude` (session-transporter mechanics.md §1.1). So a Desktop window started with
  `CLAUDE_CONFIG_DIR` set keeps its conversations there [D; no such window was tried].
- **Which home a window reads is not known, so the tool assumes `~/.claude`** [D]: a window's environment is not
  recorded in its profile, so nothing on disk says whether it was started with `CLAUDE_CONFIG_DIR`. Every rule
  takes each Desktop profile to read `~/.claude`, Desktop's default. A CLI move refuses to take a session out of
  `~/.claude` while ANY Desktop profile has a record whose `cliSessionId`, or one of whose `priorCliSessionIds`, is
  that session (unless `--copy`). Whether Desktop still reads a record's earlier conversations is not known [I];
  `cli-sessions` and the open-file check already counted them as listed, and the move rule now does too. For an
  earlier conversation the refusal advises `--copy` only: unregistering the record would also take its current
  conversation out of the window, and the record would still name an earlier conversation outside `~/.claude`
  [D, the final review of round 4]. A move
  INTO `~/.claude` is always allowed (it repairs a record shown `in cli:NAME`; the advice is a `--copy`, by the
  CLI id that `sessions PROFILE` shows next to the flag, see "Retention"); a move between two other homes goes
  ahead, with a note that Desktop looks for its conversations in `~/.claude` (or in the folder its own
  `CLAUDE_CONFIG_DIR` names). The rollback of a move restores the exact earlier state even when that takes a
  session a record lists back out of `~/.claude` (or removes a `--copy` there): it warns, with the `--copy` that
  gives the window its conversation back, so the undo a move prints always works; only an open session refuses it.
  `register` always accepts a conversation in `~/.claude` and refuses one in another home, with the copy INTO
  `~/.claude`. `~/.claude` is recognised by identity (`os.path.samefile`: `st_dev` and `st_ino`), never by its
  name: on macOS's default case-insensitive APFS `~/.Claude` is the same folder and `realpath` does not fold case,
  `/System/Volumes/Data/Users/…` is a firmlink `realpath` does not resolve, and a bind mount is a second path on
  Linux [D; reproduced on synthetic homes with a bind mount in the final review of round 3, where such a name skipped
  the refusal out of `~/.claude`]. A CLI home named by any such path goes by the realpath of `~/.claude` itself, so
  the move and rollback rules, its name and the paths the tool remembers all see one folder.
- **Where a profile's records' transcripts are is a display hint only** [D]: `profile_cli_home` names `~/.claude`
  unless none of a profile's records' transcripts is there and some are in another known home (then the home with
  most of them, the first in discovery order on a tie). It labels: the `desktop:` flag of `sessions <CLI home>`, a
  note at the end of `sessions PROFILE`, and notes in `register` and `resume-cli`; and `resume-cli`, and
  `unregister`'s hint, name the copy in that home first when a transcript has copies in several homes. It decides
  nothing, because a backup home fools it: once retention has deleted a profile's older transcripts from
  `~/.claude`, a backup copy (`~/.claude-backup`, found as a CLI home because it has `projects/`) holds all of
  them. The first repair round let it gate the move and rollback refusals and register's advice (an older rule, "the
  home holding most of them", even let a backup outvote a record in `~/.claude`); the second let it decide
  register: a new terminal conversation in `~/.claude` was refused for such a profile, with the advice to move it
  out of `~/.claude` into the backup, after which `claude --resume` no longer found it and the tool refused every way
  back but `--copy` [D, each reproduced on synthetic homes in the 0.11.0 reviews].
- **Names a Desktop profile can shadow** [D]: a Desktop profile `~/.claude-instances/cli` (or `cli` in any other
  profile root, §9) has the name `cli`, so
  `cli` is refused as ambiguous while one exists, and the tool prints `~/.claude`, and the instance called `cli`, by
  its path (whose archive folder stays `archive/cli`). `cli:NAME` is never ambiguous: `Profile("cli:NAME")` names
  the folder `~/.claude-instances/cli:NAME`, never `cli-NAME`, and an instance `cli-NAME` is named `cli-NAME` [C].
  The first repair round refused `cli:NAME` too while `~/.claude-instances/cli-NAME` existed, for an archive key
  the two once shared. CLI-move archives live in `<state>/cli-archive/<key>/`, apart from the Desktop profiles'
  `<state>/archive/<name>/`, and an archive name is unique across all CLI homes, since `rollback` finds one by name
  from either home.
- **Which folders can be a CLI home** [D]: the marker test (`projects/`, `.claude.json`, `.credentials.json`,
  `settings.json`) alone accepts HOME, because the default home keeps its `.claude.json` in HOME (fact above). A
  shell line such as `alias c='CLAUDE_CONFIG_DIR=~ claude'` or `export CLAUDE_CONFIG_DIR=$HOME` then made HOME a
  "home", and a move into it put `projects/` and `tasks/` in the home folder, outside every config dir
  [D, reproduced on synthetic homes in the 0.11.0 review]. So HOME, every folder above `~/.claude`,
  `~/.claude-instances` (and the folders above it), every folder that is or holds a Desktop profile, and the
  tool's state folder (§9) are never CLI homes; `~/.claude` itself always is one. Shell files are read line by line with comments removed, and only a
  real assignment counts: `CLAUDE_CONFIG_DIR=` at the start of a word (line start, or after whitespace, `;`, `&`,
  `|`, `(` or a quote), with no spaces around `=`, and an absolute path once `~`, `$HOME` and `${HOME}` are
  expanded (a relative one is relative to wherever that shell runs). A home found in a shell file is not
  remembered, so it goes when its line goes; one named on the command line is.
- **Sign-in state is only partly visible** [D, from the login facts above]: a missing `.credentials.json` means
  signed out on Linux and Windows.
  On macOS it is the normal case (the login is in the Keychain), so the verdict is `unknown` and a move into such a
  home prints a note that the state cannot be read, never "sign in there".
- **Shell syntax for the continue command** [I]: cmd.exe and PowerShell do not accept a `VAR=value command` prefix
  (a POSIX shell feature), so on Windows the tool prints `set "CLAUDE_CONFIG_DIR=…" && claude …` for cmd and
  `$env:CLAUDE_CONFIG_DIR='…'; claude …` for PowerShell (single quotes: a literal string), with `cd /d` and
  `Set-Location -LiteralPath` for the folder. Neither form was run on a real Windows machine for this release.
- **Resume by id with duplicates** [I]: the spec for this feature says that within one home, two project folders
  holding the same session id make `claude --resume <id>` report not-found. Nobody measured that, and
  session-transporter's measurements (mechanics.md §3.2 and §3.4) suggest otherwise for unrelated folders:
  `--resume <id>` looks only under the launch folder's key (and its git worktrees' keys), so a copy under another
  key is not even seen. Either way a duplicate id inside one home is never useful, so the tool never creates one,
  and it refuses to move an id that already has a transcript in two project folders of the source [D]: moving both
  would put the duplicate in the target, and moving one would leave it split; which copy is right is the user's
  call.
- **One transcript, two keys** [D]: a project folder can be a symlink to another one (for example an alias kept
  after renaming a repo; that this is a common workaround is inferred [I]). Its transcripts then appear under both
  keys, so the tool counts a transcript once by its real path, prefers the path with no symlink in it, and drops
  the alias's copy of each side file. An item reached ONLY through a symlinked folder, an item that is a symlink,
  and a project memory folder that is (or contains, or sits below) a symlink are refused, never followed: a link
  can lead anywhere, including another home or `~/.claude` itself with its `.credentials.json`. The memory checks
  run before any memory file is opened.
- **A walk never enters a link** [D]: on Windows `os.path.islink` is False for a directory junction, and `os.walk`
  before Python 3.12 walks into one [I: Python's documentation; no real Windows ran]. So each walk inside a
  session's items, its project memory and a copy in the target (which a `--copy` rollback hashes) prunes a folder
  that is a link (a symlink, or on Windows any reparse point) before it would descend; the link checks then refuse
  it as a symlink, and a `--copy` rollback keeps a copy that now holds one, as changed. Before the fourth repair
  round the walk inside an item listed everything under a junction (a large tree, another home, a loop) before it
  refused it [D, the final review of round 3; simulated in the self-test, whose test-only switch reports any listing
  of a simulated junction's contents].
- **Paths are not patterns** [D]: a home or profile path may contain `[`, `]`, `*` or `?`; the tool escapes the
  path in every `glob` (unescaped, `work[1]` is a character class that never matches the folder itself, so a home
  looked empty and the duplicate check found nothing).
- **Moving sessions between homes** [D]: the transcript and its side files are independent of the home, so a move
  is a file move; the project memory is copied because the source home's other sessions still use it; sign-in and
  the global config stay with each home and are never touched. The self-test checks these rules on synthetic homes;
  the table at the end of this section says which rule has a check, and which has none.
- **One filesystem is not one mount** [M]: two bind mounts of one ext4 filesystem report the same `st_dev`, yet
  `rename` between them fails with `EXDEV` (measured on Linux, 2026-11-08, during the 0.11.0 review; not with the
  tool). So a move tries `rename` and, on `EXDEV`, falls back to the verified copy it uses between filesystems. The
  self-test simulates that `EXDEV`; a real one was never run through the tool.
- **A move is a transaction** [D]: a move touches up to five paths per session plus memory files, and any of them
  can fail (a permission, a full disk, Ctrl-C, a SIGTERM such as an agent's command timeout, a SIGHUP from a closed
  terminal). Each step is journaled before it runs and a failure undoes the started ones newest first, so a session
  is never left split between two homes, where the CLI would list it in one home with its file history or tasks in
  the other. For the duration of the move, SIGTERM and SIGHUP raise an exception like Ctrl-C does (a signal the
  caller ignores, as under `nohup`, stays ignored), and the caller's handlers are put back afterwards. The undo
  decides each step from what is on disk, never from how far the run got to noting it: before each rename into the
  target the journal records the `st_dev` and `st_ino` of what is about to get the name (a rename keeps both), so
  an item renamed just before an interruption is still known as this run's, and an item that is in the target and
  no longer in the source goes back. The 0.11.0 review's first fix trusted a flag set after the rename; an
  interruption between the two left the item in the target while the tool said "nothing was changed" and deleted
  the archive [D, reproduced on synthetic homes in the second review round]. The tool now says "nothing was changed"
  and removes the archive only after checking that every item is back in the source as the move found it (size and
  sha256 of every file) and nothing this run placed is left in the target; otherwise it keeps the archive and names
  the rollback. Proving an item is this run's needs inode numbers; on a filesystem that reports none (`st_ino` 0), a
  cross-device copy renamed into place just before an interruption is not recognised [D; no such filesystem was
  tried]. A copy lives under `<name>.rehome-tmp-<pid>` until it is verified, so a killed run never leaves a truncated
  transcript that the target lists as a session. Only a run killed outright (`kill -9`, a power cut) can leave a
  split, and rollback is built for that: it moves back what is in the target, skips what never left, and refuses
  only an item found in both homes.
- **Special files are never opened** [D]: a FIFO (named pipe) blocks the reader until a writer opens it, so hashing
  one waits for ever; a socket cannot be opened at all; neither can be copied. A move refuses a FIFO, socket or
  device file anywhere in a session's items or its project memory, and at a destination in the target, before
  anything is written or hashed (a FIFO named `<id>.jsonl` is listed by `sessions` without being read, then
  refused). The hash itself never opens anything but a regular file, and records a symlink as its target's text
  (never followed), so a rollback that hashes what the target holds now cannot hang either. Claude Code creating
  such files in a home is not known [I]; the rule only keeps the tool from hanging or copying one.
- **The receiving home is checked too** [D]: every path a move writes in the target, and each existing folder above
  it inside the target, must resolve inside the target and must not be a symlink, even one that leads back inside
  it (a linked `tasks/` or `projects/<key>/` would take the session elsewhere, or under another key); a project
  memory file in the target is checked before it is read. A rollback checks the source home the same way before it
  moves anything back into it.
- **A copy is removed only while its original exists** [D]: a `--copy` rollback used to remove unchanged copies even
  when the original had been deleted from the source since, which left neither home with the conversation (and the
  archive holds only a manifest) [D, reproduced on synthetic homes in the 0.11.0 review]. Now a session's copies go
  only while every original is still in the source, and a copied memory file only while its original is; otherwise
  they are kept and the rollback says so.
- **Rollback lists the session again** [D]: a session that runs on can create per-session paths
  (`projects/<key>/<id>/tool-results/`, `file-history/<id>/`, `todos/<id>-agent-*.json`, `tasks/<id>/`) [I], so a
  session continued in the target may have paths the move never saw. Rollback lists them in the target again, leaving
  what the target had of the session before the move (`pre_existing` in the manifest). Memory a move copied stays
  when a session of that project that came to the target later still lives there (`dest_sessions_before` tells
  those apart from sessions that were there before the move and never had the file).

### What the self-test checks, and what it does not

[M, 2026-11-08, Linux, Python 3.14.4, during the 0.11.0 review]: each rule below was removed from a copy of
`ccd-rehome`, one at a time, and the self-test then failed at least the check quoted next to it (quoted from
`scripts/selftest.py`; `tests/test_docs_evidence.py` in the repository fails when a quoted check is gone). 56 of
57 removals failed a check; the one that did not is the first item under "No check" below. In the second review
round [M, 2026-11-09, Linux, Python 3.14.4] 25 more removals were made the same way: the rules that round added
(the rows from "undone from what is on disk" down) and three older rules that had no check until then (a symlink
inside an item, an item the target already has, and the content condition on rollback's mtime restore). Each of
the 25 failed the check quoted for it. In the same round [M, 2026-11-09, Linux, Python 3.14.4] 21 more changes were
made the same way, to the Desktop-record rule, the `cli` name, `register`, the login-file verdict and four messages
(each new rule removed, reversed or widened, and each guard broken): each failed at least one check quoted in the
rows from "an empty `.credentials.json`" and "`register` accepts" on, and in the rows for records, names and
rollback. In the same round [M, 2026-11-09, Linux, Python 3.14.4] 5 more changes (the `--help` line about a Desktop
move put back, the `does not exist` or the config-dir message reworded, a CLI move's target or a source path taken
as a CLI home) each failed a check quoted in the last row. In the third round [M, 2026-11-09, Linux, Python 3.14.4]
18 more changes were made the same way, to the rules that take every Desktop profile to read `~/.claude` (move,
rollback, register, the two display notes) and to the Windows junction checks: each failed at least one check
quoted in the rows for records and rollback, from "`register` always accepts" down to the junction row, and in
"rollback refuses while the session is OPEN". In the fourth round [M, 2026-11-09, Linux, Python 3.14.4] 19 more
changes were made the same way, to the tool and (once) to a self-test fixture: each piece of `--copy` advice put
back to a move, the retention warning's two new sentences, `~/.claude` recognised by name at five places, the CLI
id in `sessions PROFILE`, a fixture record id given its CLI id's prefix, the record's earlier conversations, and
three walks. 18 failed at least one check quoted in the rows from "advice for a conversation in another home" down;
the memory walk is under "No check". In the fifth round [M, 2026-11-09, Linux, Python 3.14.4] 19 more changes were
made the same way, to the status and rehome advice (its `--copy`, the account test, the same-account and
unknown-account cases, `move_why`, the new-home and `sessions` lines), the `--keep-dates` refusal and the warning's
wording, the refusal for a record's earlier conversation, and the retention rule (the entrypoint, the tail,
`desktopSessionCleanupPeriodDays`, the note, the listing, and whose settings are read): each failed at least one
check quoted in the last four rows. In the sixth round [M, 2026-11-09, Linux, Python 3.14.4] 23 more changes were
made the same way, to the plain move of a Desktop transcript (the note given instead, the source sentence dropped,
an unknown or any version taken as 2.1.248 or later, the `--keep-dates` refusal removed, the Desktop limit applied
under an old version), to the managed settings (none read, no cache, the file ranked first, a managed
`cleanupPeriodDays` ignored or not applied to Desktop transcripts, a managed `desktopSessionCleanupPeriodDays`
ignored, the old note, a wrong path, a FIFO cache opened), to the sidecar files (not re-dated, not journaled, not
restored, not recorded) and to `status` (no line, the default home counted, the field dropped from a Desktop or a
CLI row): each failed at least one check quoted in the four rows that follow the retention row. In the seventh
round [M, 2026-11-09, Linux, Python 3.14.4] 22 more changes were made the same way, to the shortest-value rule (the
higher source winning again, the longest value taken, no drop-ins, hidden or non-`.json` drop-ins read, a FIFO
opened, the target's default not counted, the target named first on a tie, a drop-in named as the file, a managed
`cleanupPeriodDays` not applied to Desktop transcripts or the target's own applied to them, a managed
`desktopSessionCleanupPeriodDays` ignored, the kept-until text without the managed limit) and to the `--copy`
(a Desktop copy never re-dated, re-dated whatever the version, the source re-dated instead, `--keep-dates` refused
or silent, the messages saying `it` or the old tail, a terminal copy's `--keep-dates` silent, a rollback comparing
mtimes): each failed at least one check quoted in the two rows that follow the managed-settings row.

| Rule (SKILL.md "CLI homes"; in full in `cli-homes.md`) | A check that fails without it |
|---|---|
| the transcript moves byte for byte and leaves the source | "transcript moved byte-for-byte into cli:work and gone from cli" |
| the sidecar folder, `tasks/`, `todos/` and `file-history/` go with it | "tasks/, todos/<id>*.json and file-history/ moved" |
| sibling-key sidecar folders (git worktrees) go with it | "carries its sibling-key sidecar and its todos too" |
| `history.jsonl` never moves | "history.jsonl is never moved" |
| project memory is copied, never moved; a different file in the target is kept and reported | "memory copied file by file; a different existing file is kept", "the memory conflict is reported" |
| `--no-memory` moves the session without its memory | "--no-memory moves the session and leaves the linked memory alone" |
| `--copy` keeps the source | "--copy is allowed and warns the copies diverge" |
| a copy keeps a temporary name until size and sha256 match | "leaves it only under a temporary name", "never gets its real name" |
| a rename that fails with EXDEV falls back to the verified copy | "falls back to copy, verify, remove, and says so" |
| all or nothing: a failed step undoes the steps done | "is undone: the moved items go back, its archive is removed" |
| the archive name is printed before the first change | "the archive name is printed before the first change" |
| refused: an OPEN session | "an OPEN session refuses and nothing is written" |
| refused: a transcript another process holds open | "move refuses a transcript another process holds open" |
| refused: a move OUT of `~/.claude` of a session that ANY Desktop profile has a record for (unless `--copy`); a move INTO `~/.claude` always goes ahead; one between two other homes goes ahead with a note | "a Desktop record for the session refuses; the message says unregister or --copy", "the real move refuses it too and nothing is written", "#14: and the move of that live conversation into the backup home is refused", "a move INTO ~/.claude goes ahead though acct-w", "goes ahead and its note names both", "may move INTO ~/.claude, the home acct-d reads", "a move between two homes other than ~/.claude goes ahead" |
| refused: a different transcript with that id in the target | "a different transcript with the same id in the target refuses on its own" |
| an identical transcript is "already there" | "skipped, not an error" |
| refused: an id with a transcript in two project folders | "the real move refuses it up front (no archive, no half move, no duplicate id in cli:work)" |
| refused: an item that is a symlink | "a sidecar folder that is a symlink to a folder inside the home is refused as a symlink" |
| refused: an item reached through a symlinked folder | "a transcript whose project folder is a symlink (to a folder inside the home) is refused up front" |
| refused, and never read: a project memory that is, holds or sits below a symlink | "the linked folder is never read: an unreadable file in it does not reach the tool" |
| refused: the same home, a Desktop profile or no config dir as the target | "move cli --to-profile cli (the same home) is refused", "is refused with 'is not a CLI home'" |
| refused: HOME, a folder above `~/.claude`, `~/.claude-instances`, a folder holding a Desktop profile | "there, move --to-profile ~ (dry run) is refused: it is your home folder" |
| refused: `cli` while a Desktop profile is named `cli`; `cli:NAME` never | "is refused as ambiguous when ~/.claude-instances/cli is a Desktop profile", "`cli:work` is NOT refused as ambiguous though ~/.claude-instances/cli-work is a Desktop profile" |
| a dry run writes nothing; one that finds a refusal exits 1 | "leaves every CLI home and the tool's state byte-identical", "a dry run that finds a refusal shows the plan and the REFUSE line" |
| an old transcript is re-dated by the TARGET's `cleanupPeriodDays`; `--keep-dates` keeps its mtime (since the fifth round only with `--copy`, row below) | "an old transcript warns with the DESTINATION's cleanupPeriodDays", "--keep-dates leaves the old mtime" |
| warned: different organizations; a signed-out target; on macOS a note instead | "a different org is warned about (unverified)", "Linux: a target without a login file is signed out", "macOS: the same target is unknown, not signed out" |
| an empty `.credentials.json` is no login, and is called empty (on macOS `unknown`) | "an empty .credentials.json is reported as empty (signed out)", "macOS: an empty .credentials.json holds no login either", "a move into it warns that it is signed out because its login file is empty", "a home with no .credentials.json at all still says 'no login file'" |
| the sign-in state comes from file existence and size only | "a mode-000 .credentials.json still says signed-in: the file is never opened" |
| shell files: only a real `CLAUDE_CONFIG_DIR=` assignment counts | "OLD_CLAUDE_CONFIG_DIR= is another variable: not an assignment of it" |
| rollback restores every home exactly, and refuses an item in both homes | "rollback from the destination restores every CLI home exactly", "rollback refuses when an item is in both homes, and changes nothing" |
| refused: a symlink INSIDE an item (a `--copy` never follows it) | "a symlink INSIDE a session folder (tool-results/x.txt -> the home's .credentials.json) is refused" |
| refused: an item the target already has (never overwritten) | "an item cli:work already has (its own todos/<id>-agent-*.json) is refused: never overwritten" |
| rollback restores the original mtime only when the content is unchanged | "a transcript that grew in cli:work keeps its current mtime" |
| undone from what is on disk: an item renamed into the target just before an interruption goes back (rename and cross-device copy; memory too) | "Ctrl-C right after an item got its name in cli:work, before the move noted it: still undone", "the same for a cross-device copy that got its name in cli:work", "the same for a project memory file copied into cli:work" |
| SIGTERM and SIGHUP undo a move as Ctrl-C does; one the caller ignores stays ignored; the caller's handlers come back | "a SIGTERM during the move", "a SIGHUP during the move", "a SIGHUP the caller ignores (nohup) stays ignored", "the caller's SIGINT, SIGTERM and SIGHUP handlers are back" |
| the archive is removed only once the undo is verified on disk | "the move keeps its archive, names the rollback, and never says that nothing was changed" |
| refused: a FIFO, socket or device file in an item, as an item, or in the project memory, before anything is hashed | "a FIFO inside a session's sidecar folder is refused (exit 1), without waiting on it", "a socket in tasks/<id>/ is refused the same way", "a transcript that is itself a FIFO: sessions does not wait on it", "a FIFO in the project memory is refused before any memory file is read" |
| refused: a FIFO, socket or device file where the target would put a file | "a FIFO where cli:work keeps a project memory file is refused before it is opened" |
| the hash never opens a special file (a rollback that hashes the target cannot hang) | "rollback of a --copy move whose copy now holds a FIFO keeps that copy as changed", "rollback: a copied memory file that is a FIFO in cli:work now is kept as changed, never opened" |
| refused: a target path that resolves outside the target, or a symlinked folder in the target | "a folder of cli:work that leads outside it (tasks -> another folder) is refused", "a symlinked folder inside cli:work (projects/<key> -> another project folder of it) is refused too", "a project memory folder in cli:work that leads outside it is refused" |
| rollback refuses to move back through a folder of the source that now leads outside it | "rollback refuses to move a session back through a folder of cli that now leads outside it" |
| rollback never removes a copy, or copied memory, whose original is gone | "rollback of a --copy move keeps the copy when the original was deleted from cli since", "rollback keeps a copied memory file whose original was deleted from cli since" |
| rollback refuses while the session is OPEN, or open in another process | "rollback refuses while the session is OPEN in cli:work", "rollback refuses while another process holds the transcript open" |
| a Desktop record never refuses a rollback: one that takes a listed session back out of `~/.claude` (or removes its `--copy` there) warns, with the `--copy` that gives it back, so the undo a move prints works | "the undo that move printed works", "the rollback of that --copy removes the copy from ~/.claude although acct-w shows the session", "a rollback that brings the session back INTO ~/.claude goes ahead", "a rollback back INTO ~/.claude is not refused" |
| rollback moves back what the session gained in the target, a grown transcript as it is | "and the grown transcript as it is now" |
| rollback gives a re-dated transcript its mtime back | "rollback gives a re-dated transcript its original mtime back" |
| rollback of a `--copy` treats the session as one unit | "rollback of a --copy move keeps the whole session copy" |
| rollback keeps copied memory a later session uses, and memory changed since | "keeps the project memory that a later-moved session", "keeps a copied memory file changed in the target since" |
| a rollback that stopped part-way finishes when run again | "running the same rollback again finishes it" |
| `rehome cli` changes nothing; `rehome --all` skips CLI homes; a Desktop profile's records never go to a CLI home | "rehome cli explains the CLI's model and changes nothing", "rehome --all skips the CLI homes silently", "is refused (records go to Desktop profiles only)" |
| reports: `profiles` RUNNING, `sessions` OPEN and `older than N days`, `cli-sessions` across homes | "a CLI home is RUNNING while a live sessions/<pid>.json", "sessions cli prints OPEN for it", "sessions cli flags a transcript older than", "cli-sessions lists the conversation of that home" |
| `resume-cli` names the home that holds the transcript | "resume-cli of a record whose transcript is in cli:work names CLAUDE_CONFIG_DIR=<cli:work>" |
| `register` always accepts a conversation in `~/.claude`, and refuses one in any other home with the copy INTO `~/.claude` | "register always accepts a conversation in ~/.claude, even for a profile whose other transcripts are only in", "#14: register files the new ~/.claude conversation", "no move into the backup is printed", "a cli:backup conversation is refused even for the profile", "a cli:work conversation is refused for the profile whose records' transcripts are all in cli:work" |
| where a profile's records' transcripts are is a display hint only: the `desktop:` flag, a note in `sessions PROFILE` and in `resume-cli` | "a backup home holding more of a profile's old transcripts never outvotes", "sessions PROFILE says when none of a profile's records' transcripts", "resume-cli's note says the conversation is not in ~/.claude" |
| on Windows a directory junction (a reparse point) inside an item, in the project memory or in the target is refused like a symlink | "the reparse-point helper: FILE_ATTRIBUTE_REPARSE_POINT (0x400) is a link", "a junction inside the session's sidecar folder", "a junction inside the sidecar folder, with --copy", "a junction inside the project memory", "a junction in the target (cli:work's tasks/)" |
| advice for a conversation in another home is a `--copy` into `~/.claude` (the `sessions PROFILE` line, `register`'s refusal, a rollback's warning), by the CLI id, which the `in cli:NAME` flag shows | "sessions PROFILE advises a COPY of conversations that live only in another home", "sessions PROFILE shows the CLI id of a record whose conversation is in another home", "and that line runs as printed", "register of a conversation in another home prints the COPY into ~/.claude", "a rollback that takes a listed conversation back out of ~/.claude prints the COPY" |
| the retention warning: re-dating only postpones the deletion; on a move (not `--copy`) the source no longer has it | "a real move (not --copy) of an old transcript warns that the source no longer has it", "with --copy the warning still says re-dating only postpones it" |
| `~/.claude` is recognised by identity, never by name: in a move, in rollback (and its archive lookup), and in discovery | "~/.claude named by a second path that realpath does not resolve is still ~/.claude", "that second name is never remembered or listed as a home of its own", "rollback from `cli` finds an archive that names ~/.claude by that second path" |
| a record's `priorCliSessionIds` keep a conversation in `~/.claude` like its `cliSessionId` | "a conversation a record names among its earlier ones (priorCliSessionIds) stays in ~/.claude" |
| a walk inside an item, or inside a copy a rollback hashes in the target, prunes a link (on Windows a junction) before it descends | "Windows: the walk inside a session's sidecar folder stops at a junction", "Windows: the rollback of a --copy whose copy now holds a junction keeps that copy as changed" |
| the fixtures: no Desktop record id shares its first 8 characters with its CLI id (so advice naming the wrong one cannot pass) | "(fixtures) no Desktop record id in this self-test shares its first 8 characters" |
| `status` and `rehome` advise a `--copy` into the home where another account is signed in, say so when every other home has the same account (and advise nothing then), and say when an account is not known; every move command `status`, `rehome` and `sessions` print for a CLI home is a `--copy` | "advises a COPY of its sessions into ~/.claude, the home where", "rehome cli:work prints the same copy, and it runs as printed", "status cli:backup (the same account as ~/.claude) advises the copy into cli:work", "with two homes of one account says they have the same account", "a home whose account is not known gets the copy", "every move command that status, rehome and sessions print for a CLI home is a --copy" |
| refused: a move (not `--copy`) with `--keep-dates` of a transcript the target's cleanup would delete; the warning on a move names `--copy`, never `--keep-dates` | "a move (not --copy) with --keep-dates of a transcript the target's cleanup would delete is refused", "the warning on a move (not --copy) of an old transcript names --copy and never suggests --keep-dates" |
| a record's earlier conversation: the refusal advises `--copy` only, not unregistering the record (also when another record has it as its current one) | "the refusal for a record's earlier conversation (priorCliSessionIds) advises --copy only", "a conversation that is one record's current one and another's earlier one" |
| retention follows the transcript's most recent records, read from its tail (when the tail holds no entrypoint, `cleanupPeriodDays`): one last continued in Claude Desktop is kept at any age (on a `--copy` with Claude Code 2.1.248 or later here: no warning, no re-dating, a note) unless the target's `settings.json` sets `desktopSessionCleanupPeriodDays`; the `sessions` flag follows the same rule | "a transcript last continued in Claude Desktop, older than cleanupPeriodDays, is copied with no retention", "with desktopSessionCleanupPeriodDays set (20) in the target's settings.json", "the most recent records decide", "a transcript whose last 256 KB hold no entrypoint", "sessions cli:backup flags the terminal transcripts older than 30 days, and not the one last continued in", "with desktopSessionCleanupPeriodDays (20) in that home's settings.json" |
| a plain move (not `--copy`) of a transcript last continued in Desktop and older than `cleanupPeriodDays`: not re-dated when `claude --version` is 2.1.248 or later, re-dated when it is older or not known (no version printed, no `claude` on `PATH`), `--keep-dates` refused then; every such warning says the source no longer has it and names `--copy` | "a plain move of a transcript last continued in Desktop, older than cleanupPeriodDays, with Claude Code", "the same move with Claude Code 2.1.100 here", "the same move when `claude --version` prints no version", "with no `claude` on PATH the version is not known either", "--keep-dates on that plain move with", "with desktopSessionCleanupPeriodDays 90 in the target, a 60-day-old Desktop transcript is still re-dated", "a plain move of a transcript whose most recent entrypoint is not known says the source no longer" |
| managed settings are read: `remote-settings.json` and `managed-settings.json` where the documentation puts it, for `cleanupPeriodDays` (terminal and Desktop transcripts, and the `sessions` flag) and `desktopSessionCleanupPeriodDays`; a shorter managed value wins over the target's `settings.json`; the note no longer says they cannot be seen | "managed-settings.json's cleanupPeriodDays (7) wins over the target's settings.json (90)", "sessions flags a transcript by the managed cleanupPeriodDays", "a managed cleanupPeriodDays applies to a transcript last continued in Desktop too", "the server-managed settings cached in the target's remote-settings.json win", "with remote settings 40 and managed-settings.json 7 the shorter applies", "a managed desktopSessionCleanupPeriodDays (20) wins", "the note on a copy no longer says that managed settings are not visible", "a FIFO named remote-settings.json is never opened", "outside the sandbox the tool reads managed-settings.json where the documentation puts it" |
| each setting is the shortest value that the target's `settings.json` (30 when it sets no `cleanupPeriodDays`), `remote-settings.json`, `managed-settings.json` or a `managed-settings.d/*.json` drop-in sets (hidden drop-ins and other names skipped, a FIFO never opened), named in the message; a managed `cleanupPeriodDays` applies to Desktop transcripts, the target's own does not | "a cache with other policy keys and no cleanupPeriodDays, managed-settings.json 90 and the target's", "the same layout with --keep-dates on a plain move is refused", "a drop-in managed-settings.d/20-retention.json 7 over managed-settings.json 90", "a drop-in's value is read, and the warning names that drop-in", "a hidden drop-in and one that does not end in .json are not read", "a FIFO among the drop-ins is never opened", "the shortest value wins whichever source ranks first", "a managed value never lengthens the target's", "sessions flags a transcript by the shortest value too", "a drop-in's cleanupPeriodDays applies to a transcript last continued in Desktop too", "the target's own cleanupPeriodDays (7) does not apply to a Desktop transcript", "the shortest desktopSessionCleanupPeriodDays" |
| a `--copy` the target would delete is re-dated in the target (the copy and its sidecar files, never the source), for a Desktop transcript by `claude --version` as on a move; with `--keep-dates` the copy keeps its dates and the warning says the target would delete the copy; a rollback removes a re-dated copy (content decides) and keeps one that changed | "the --copy that sessions PROFILE prints for a window, with Claude Code 2.1.100 here", "its rollback removes the re-dated copy", "with no version known (none printed, no `claude` on PATH) the copy would be re-dated too", "with Claude Code 2.1.300 here the copy keeps its date, and the note names the version", "--copy --keep-dates with Claude Code 2.1.100 here keeps the old dates", "a terminal transcript's --copy says the same", "a managed cleanupPeriodDays re-dates the copy of a Desktop transcript", "a re-dated copy that gained a turn after the copy is kept by the rollback" |
| the files of a re-dated transcript's sidecar folder are re-dated with it (a `--copy` leaves the source's alone), and the undo and the rollback give each its mtime back | "a move that re-dates a transcript re-dates every file of its sidecar folder", "its rollback gives the transcript and each sidecar file back the mtime", "a re-dating --copy re-dates the copy's sidecar files", "a move that fails after re-dating undoes it" |
| `status` of a Desktop profile counts its records whose conversation is only in another CLI home (`elsewhere`, text and JSON) and points to `sessions PROFILE` for the copy; `{}` otherwise and on a CLI row | "status of a Desktop profile counts the records whose conversation is only in another CLI home", "a profile whose conversations are in ~/.claude (or missing) has" |
| a refusal says "Nothing was changed." once; a dry run never | "says 'nothing was changed' once, not twice", "two refusals: both REFUSE lines, then 'nothing was changed' once", "the dry run of it says 'nothing was written'", "a rollback refusal (a folder of cli now leads outside it) says 'nothing was changed' once too" |
| `unregister`'s hint: cmd and PowerShell on Windows, the transcript's home named | "Windows: unregister's hint is in cmd and PowerShell syntax", "Windows: for a conversation in cli:work the hint sets CLAUDE_CONFIG_DIR", "elsewhere it names CLAUDE_CONFIG_DIR=<cli:work> on the POSIX line" |
| `status` (text) shows the newest three archives, and with more how many and that `--json` lists all | "with 4 archives, status (text) shows the newest 3, says there are 4 in all", "the same for a Desktop profile with 4 archives", "with 3 archives, status (text) shows all three and no count" |
| which refusal a name that is no CLI home prints (a path: `… does not exist`, `not a Desktop profile (no config.json)`, or as a CLI move's target `--to-profile '…' is not a CLI home`; `cli:NAME`: `is not a Claude Code config dir`), as the troubleshooting rows say; `--help` says a Desktop move leaves the conversation in its CLI home | "a path that does not exist, as what `move` works on", "a path that does not exist, as a CLI move's --to-profile", "a folder that is no CLI home, as a CLI move's --to-profile", "cli:NAME naming no folder", "--help: a Desktop move --to-profile moves the record only" |
| `cli:NAME` is `~/.claude-NAME`, else the one known CLI home whose folder is `NAME` or `.claude-NAME`; two are refused with their paths | "cli:NAME is ~/.claude-NAME, else the known CLI home whose folder is NAME or .claude-NAME" |
| the CLI homes among a profile root's subfolders are found; `profiles --add` takes a CLI home anywhere | "every Desktop profile and CLI home in its subfolders is found", "registers a Desktop profile or a CLI home anywhere" |
| the tool's state folder is never a CLI home (or a Desktop profile), even inside a profile root | "the state folder is never a Desktop profile or a CLI home, even inside a profile root" |

**No check** (each is a rule the code has and the self-test cannot or does not test):
- the escape refusal (`… escapes …`) on the source side. An item can lead out of its home only through a link, and
  the link rules refuse it first (symlinks; on Windows also directory junctions and other reparse points, which
  `os.path.islink` does not see), so removing the escape check changes nothing the self-test can see. It is a last
  backstop. (On the target side the order is the other way round, so a link leading out is refused by the
  "resolves … outside" rule, which has a check.)
- a real Windows directory junction: POSIX cannot make one, so the self-test simulates it on the emulated Windows
  layout with the test-only `CCD_REHOME_FAULT=reparse:PATH`, and checks the `st_file_attributes` test with a stat
  stand-in. Whether a real `os.lstat` reports `FILE_ATTRIBUTE_REPARSE_POINT` for a junction is [I] (Python's
  documentation); CI's Windows job runs the simulated checks only.
- the walk inside the project memory pruning a link: that walk stops at the first link it sees and returns, so it
  never descended into one before the fourth round either, and putting `os.walk` back there changes nothing a check
  can see (the guard "the same for a junction in the project memory" keeps it from listing one);
- which retention applies where the tool does not read it: the HIPAA configuration, a managed `cleanupPeriodDays`
  in an MDM profile or the registry, which Claude Code runs a home's cleanup (Desktop bundles its own; the tool
  reads the terminal's `claude --version` only), the shape of a real `remote-settings.json` [I], and a Cowork turn's
  entrypoint; and which of the values Claude Code applies where they differ: the tool takes the shortest on purpose
  (see "Managed settings"), so where Claude Code would apply a longer one the tool warns and re-dates more than it
  needs to, and no check says how much;
- the `tasks/<id>/` and `file-history/<id>/` files of a re-dated session are not re-dated, though the documentation
  lists `file-history/<session>/` and `tasks/` among the paths the cleanup deletes too: only the sidecar folders are;
- a real second name of `~/.claude` (a bind mount, a macOS firmlink, `~/.Claude` on a case-insensitive disk): the
  self-test makes one with a symlink and the test-only `CCD_REHOME_FAULT=alias:PATH`, which makes the tool's
  `realpath` leave it unresolved while `os.stat` still sees through it, as with a bind mount;
- the undo of a `--copy` move whose original vanished during the run (the undo keeps that copy and the archive);
  no self-test makes the original vanish mid-run;
- an interruption on a filesystem without inode numbers (see "A move is a transaction");
- a real SIGHUP from a terminal that closes, and a real agent timeout (the self-test sends the signals to the tool
  itself);
- the cmd and PowerShell continue lines in a real cmd.exe or PowerShell (they are checked as text);
- the symlink and real-failure checks on Windows, where the self-test skips them;
- the macOS Keychain itself (the `unknown` verdict is checked; the Keychain is never queried);
- a real Desktop window started with `CLAUDE_CONFIG_DIR`, and a real `EXDEV` between two mounts;
- any move on a real signed-in CLI home.

## 5a. Desktop 4.x per-account folders (first seen 4.23118.0, macOS)

- **Code store:** `waiting-input/` is new. Desktop's quit log mentions "N waiting-input snapshot(s) queued", so it
  holds pending input for paused sessions. Empty is fine. **Non-empty is DRIFT**: the snapshot format is unknown,
  so a move would leave them behind.
- **Cowork store:** it has become a per-account workspace:

  | Entry | Class | Handling |
  |---|---|---|
  | `local_*` | sessions (22 on the measured Mac) | moved with `--include-cowork` |
  | `rpm/`, `cowork_plugins/` (marketplaces, about 3 MB), `cowork-gb-cache.json` (feature-flag cache), `.claude.json` (+`.lock`, `backups/`), `debug/` (has a dangling `latest` symlink), `scheduled-tasks.json` | cache / config Desktop recreates | left in place, not drift |
  | `spaces.json` (`{"spaces": [...]}`), `agent/` (`local_ditto_<org>` + `.json`), `cowork_settings.json` | **user data**, link to sessions unknown | a Cowork move **refuses** while any of them holds content; Code moves are unaffected |

## 6. Where emails come from

| Source | Holds | Survives sign-out? |
|---|---|---|
| profile IndexedDB / Local Storage | the current account's `email_address` | no, replaced at the next sign-in |
| `~/.claude.json` `oauthAccount` | the CLI's account: uuid, email, org uuid and name | until the CLI logs in elsewhere |
| logs (C3, C4) | account/org pairs, no email | until the logs rotate |
| `<state>/accounts.json` (this tool) | union of everything ever seen | yes |

Measured: right after a profile switched accounts, no profile held the old account's email any more. The registry
and `~/.claude.json` still resolved it.

## 7. Per-account data outside the session stores

- `scratch-workspaces/<acct>/<org>/` holds cwd roots of scratch sessions. **Never moved**: a session's cwd
  decides where its transcript lives (mangled cwd), so moving the folder would orphan the conversation. The old
  path keeps working.
- `spaces-present/<acct8>/<org8>/link-key` is an encrypted per-identity key. A credential, never touched.
- `config.json` `dxt:allowlist*:<org>` are per-org caches that Desktop refreshes itself.
- `sessions` flags records whose `cliSessionId` has no `.jsonl` under `~/.claude/projects/`: typically sessions
  created on another machine. Desktop lists them but can't open them. Moving them is harmless.

## 8. Platforms

| | Linux (measured) | macOS (from Electron and Desktop conventions; unverified) | Windows (same; unverified) |
|---|---|---|---|
| default user-data-dir | `~/.config/Claude` | `~/Library/Application Support/Claude` | `%APPDATA%\Claude` |
| logs | `<profile>/logs/main*.log` | `~/Library/Logs/Claude/` (Electron's `logs` path is per app, so possibly shared by every instance) | `<profile>\logs` |
| profile lock | `SingletonLock` symlink `<host>-<pid>` | the same | `lockfile`, held open exclusively |
| Desktop binary | `/usr/bin/claude-desktop` | `/Applications/Claude.app/Contents/MacOS/Claude` | `%LOCALAPPDATA%\AnthropicClaude\claude.exe` |

- **Attribution in a shared log.** C3 carries no path; C4 does, and is logged at every init, the transitional one
  included (§3). So the tool takes (account, org) evidence from both and uses only C4 when the log dir is shared.
- **Process listing.** One snapshot per run: `/proc`, `ps -axww -o pid=,ppid=,command=`, or PowerShell
  `Get-CimInstance Win32_Process`. Never `os.kill(pid, 0)` on Windows: there, signal 0 is CTRL_C_EVENT, and any
  other value is TerminateProcess.
- **The Claude Code CLI binary is also named `claude`,** so the Desktop binary is matched exactly. A loose match
  made every terminal CLI session look like a running Desktop; the selftest guards this.

## 9. Any layout: where profiles and homes are found, their names, and the state folder

Nothing in Desktop or Claude Code ties a profile to `~/.claude-instances`: a user-data-dir and a `CLAUDE_CONFIG_DIR`
can be any folder [D]. `~/.claude-instances` is the example these docs use, and the tool treats it as one profile
root among others. Each rule below has a check in the self-test section "Any layout: profiles and homes outside
~/.claude-instances" that fails without it [M, 2026-11-09, Linux, Python 3.14.4: 29 changes to a copy of the tool,
one at a time (the state folder's three sources, `--add`, `--add-root` and `--forget` and their refusals, the roots
for profiles and for CLI homes and their hidden subfolders, `$CCD_REHOME_INSTANCES`, the shell-file rule's command, comment and anchoring, the
macOS log and its existence test, bare names, printed names, archive keys, `cli:NAME`, the state folder's
exclusion, `found_by` and the `profiles` text): each failed at least one check of that section].

- **State folder** [C]: `$CCD_REHOME_STATE`; else `~/.claude-instances/_rehome` when it exists (versions before
  0.11.0 made it there, so its archives and account registry keep working and `rollback` undoes earlier moves);
  else the platform's per-user state folder: `$XDG_STATE_HOME/session-rehome` (an absolute `XDG_STATE_HOME` only,
  as the XDG Base Directory spec says; default `~/.local/state/session-rehome`) on Linux,
  `~/Library/Application Support/session-rehome` on macOS, `%LOCALAPPDATA%\session-rehome` on Windows. The tool
  never creates `~/.claude-instances`. It holds `accounts.json`, `archive/`, `cli-archive/`, `profiles.json` (what
  `profiles --add` registered, and paths named before) and `roots.json` (what `--add-root` registered). The state
  folder is never a Desktop profile or a CLI home (`is the tool's state folder … (or inside it)`), wherever it is.
  In the sandbox (self-test) a real `XDG_STATE_HOME` or `LOCALAPPDATA` is ignored, so a self-test never writes the
  user's state folder.
- **Profile roots** [C]: folders whose subfolders are profiles or homes: `~/.claude-instances` while it exists,
  each folder added with `profiles --add-root DIR` (refused: a missing folder, HOME or a folder above it, a profile
  or home itself, the state folder), and each folder in `$CCD_REHOME_INSTANCES`. Every subfolder, hidden ones too, that
  is a Desktop profile (has `config.json`) or a CLI home is found, except names starting with `_` (the old state
  folder), `-3p` gateway profiles and the state folder.
- **Discovery** [C], in this order (the first source that finds a folder is its `found_by`, shown by `profiles`
  and in its `--json` with `found_in`): `default`; `root` (`env` for `$CCD_REHOME_INSTANCES`); `running` (the
  `--user-data-dir` of a running Desktop; never in the sandbox); `launcher` (`--user-data-dir=` in a `.desktop`
  file); `shell-file`; `log` (macOS); `added`; `env` (`$CCD_REHOME_PROFILES`, `$CCD_REHOME_CLI_HOMES`,
  `CLAUDE_CONFIG_DIR`). Only folders that exist and are Desktop profiles (or CLI homes) are kept.
- **Shell startup files** [C]: the files read for `CLAUDE_CONFIG_DIR=` (§4b) are also read for
  `--user-data-dir=PATH` and `--user-data-dir PATH`, with the same rules: comments removed, the flag at the start
  of a word, a leading `~`, `$HOME` or `${HOME}` expanded, a relative path skipped. The line must run the Desktop
  app before the flag: `claude-desktop`, `claude-desktop-unofficial`, or `Claude` as in `open -n -a Claude --args …`
  and `…/Claude.app/Contents/MacOS/Claude`. A Chromium alias or `x--user-data-dir=` is not read.
- **Desktop's shared macOS log** [I]: every instance logs to `~/Library/Logs/Claude/` (§8), and its `Loaded N
  persisted sessions from <profile>/claude-code-sessions/<acct>/<org>` line (C4) names the profile's path. So on
  macOS the tool takes each such `<profile>` (also for `local-agent-mode-sessions`) as a candidate; one that no
  longer exists or has no `config.json` is dropped. Not yet seen on a real Mac with several instances.
- **Names** [C]: a bare `NAME` is the folder `NAME` in a profile root (the Desktop profiles among them when any is),
  else a known Desktop profile (discovered or added) whose folder is called `NAME` (never the default profile, which
  is `default`). Several matches are refused, with their paths: `` `NAME` is ambiguous: N Desktop profiles have
  that folder name: … ``. A profile in a root is printed by its folder name only while that name, typed back,
  means it alone (and is not `default`, `cli`, or something that reads as a path or as `cli:NAME`); every other
  profile is printed by its path, so every printed command runs as printed. `cli:NAME` is `~/.claude-NAME`, else
  the one known CLI home whose folder is `NAME` or `.claude-NAME` (§4b, "Names").
- **Archive keys** [C] do not change: `default`, the folder name for `~/.claude-instances/NAME` (as before), and
  for every other folder, a profile root's included, the `path-<slug>-<hash>` key its path always had. Two folders
  with the same name therefore never share an archive folder, and archives made before a folder was in a root still
  roll back.
- **Registration** [C]: `profiles --add PATH` takes a Desktop profile (has `config.json`; not `-3p`) or a CLI home
  (§4b's markers), and refuses anything else with the reason (`cannot add …: it is neither a Desktop profile (no
  config.json) nor a CLI home …`, `it does not exist`, HOME, the state folder). `--forget PATH` drops a path added
  (or named before) or a root added, with the profiles remembered inside that root; it refuses a path never added
  (`is not registered with --add or --add-root`, with how it is found instead). A profile in a root is not
  remembered on its own, so it goes when its root goes. The three flags go with `profiles` only.
