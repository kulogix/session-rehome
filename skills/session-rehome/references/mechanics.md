# mechanics.md: how Claude Desktop ties Code sessions to accounts

This is the evidence behind every rule in SKILL.md. It was first measured on 2026-11-07 on Linux, with Claude
Desktop 2.31226.1 (Electron 44), five profiles and two accounts. Accounts are shown as `<A>` (old) and `<B>`
(new), orgs as `<OA>` and `<OB>`. **When Desktop changes, this file is updated together with the code** (see
SKILL.md "Maintaining this skill").

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
~/.claude/projects/<mangled-cwd>/<cliSessionId>.jsonl   the conversation; shared by every profile; never touched
```

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
