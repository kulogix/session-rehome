# Changelog

One version for the whole project: both tools (`ccd-rehome`, `st-bundle`) and the plugin carry it. Each entry
says what changed, what was tested, and what was not. Dates are when the change was made; Desktop and CLI
versions are the ones it was measured against.

## 0.11.2 — 2026-11-12

**Claude Desktop 5.** On a real Mac, Desktop 4.23118.1 wrote a record field the tool did not know
(`subagentsTruncatedFor`), and every move there refused it; the same day Desktop updated itself to 5.11492.0.
Desktop 5's own code was then read for everything the tool relies on (`references/mechanics.md` §5a).
- **Record fields:** Desktop 5 can write 214; 138 were unknown. Each is now classified, from its writers and
  readers in Desktop's code, and checked again by a second reader trying to refute it (9 changed):
  - 20 belong to the old account and are dropped by a move: its email (`emailAddress`), its claude.ai cloud,
    Remote Control, connector, artifact and Space ids, `sshReattach`, an SSH turn owed a continuation (`cutTurn`),
    and the quit-resume marks, with which `interruptedAwaitingPerson` (known since 4.x) now goes;
  - 6 are transient, 32 machine-bound (kept on this machine, dropped by `adopt --cwd`; `cuGrantFlags`, known since
    4.x, joins them), 80 plain session state;
  - every field, its class and the reason: `references/desktop5-fields.md`.
- **What a move, `export-record` and `adopt` carry over** (`portable()`; `adopt` now applies it itself, so a record
  exported by 0.11.1 or written by hand keeps none of the old account's fields either):
  - a session started from Remote Control keeps both Desktop clamps: never bypass permissions
    (`remoteClientLimits`) and the Remote Control restrictions (`remoteControlDescendant`);
  - a held first start loses `remoteControlAtStart`, which Desktop would otherwise read as a Remote Control request
    under the new account;
  - an SSH session whose first turn was cut keeps its conversation id (copied from `sshReattach` to
    `cliSessionId`, as Desktop does at load).
- **New files in the account folders**, checked per session moved (another session's files, and anything in the
  target folder, do not block a move):
  - `archived-sessions.idx` (a cache) and `owed-bridge-delete_*` (Remote Control deletes the old account owes) are
    known and left in place. A move refuses (DRIFT) while one of those deletes is in progress for a session it
    takes.
  - An imported session not resumed yet keeps its conversation in `imported-staging/` inside the account folder.
    It moves within its window (Desktop keeps reading it there); `move --to-profile`, `export-record` and
    `unregister` refuse it. `rollback` refuses to bring back a staged conversation Desktop has resumed since.
  - A `local_<id>.json.tmp` of a session being moved, at most 30 days old (Desktop would turn it back into a
    record), is DRIFT. A special file (FIFO, socket) where Desktop keeps one of these is an ERROR, before anything
    is written.
  - `move --to-profile` now runs these checks on the source folder too; before, it validated only a copy of the
    record.
- **Log lines:** Desktop 5 adds ` (K archived deferred, …)` to `Loaded N persisted sessions from <folder>` and logs
  the deferred ones on a line of their own. `verify` and the target-org lookup misread the folder whenever
  archived sessions existed; both now read it, and `verify` adds the deferred count (and says "wait and re-run"
  while that pass is still loading). `User logged out during account ID wait` (5.x name of a 4.x line) counts as
  signed out.
- **Log reading, older bugs found by the review:** sign-in lines of the same second are read in the log's order;
  on macOS, when two or more windows share Desktop's one log, lines that name no window no longer sign another
  window out (its cookie decides); a transitional (old account, new org) line is skipped even when its "Loaded"
  line is a second later; `verify` counts every load since Desktop last started, so a sign-out and sign-in of the
  same account in one launch no longer reads as MISMATCH.
- **Scratch workspaces:** moving a session whose folder is the old account's scratch workspace now warns. Desktop
  may delete that folder once the old account is signed in there again and it has been idle for 7 days. The old
  note said it "still works", which is only true until then.
- **Desktop's own importer** (Settings › Import) cannot move Code sessions between claude.ai accounts in one
  profile (third-party mode or an admin setting only), so this tool is still the way, and the two cannot create
  duplicates of each other.

**Conversations Claude Code would delete for their age.** On the same Mac, the terminal `claude` was 2.1.119 with
no `cleanupPeriodDays`. Claude Code before 2.1.248 deletes every conversation older than `cleanupPeriodDays` (30
days by default) at its next start, Desktop's included, and two of the Mac's Desktop sessions had lost theirs.
`status` (text and `--json` `retention_risk`) and `doctor` now name the conversations at risk, why, and the fix
(raise the setting, or update Claude Code). Nothing is changed by the tool.
- A record's earlier conversations count too, each conversation once, with one row per setting.
- Claude Code's other desktop surfaces (`claude-desktop-3p`, Cowork's `local-agent`) are now recognised, here and in
  CLI moves.
- A `cleanupPeriodDays` that is not a whole number of days (`0`, `1e999`) pauses Claude Code's cleanup, so it warns
  of nothing (it crashed before).
- `claude --version` runs only when its answer changes the warning, and odd output from it crashes nothing.
- **Not yet:** Claude Code 2.1.319 combines `desktopSessionCleanupPeriodDays` with `cleanupPeriodDays`, and decides
  "Desktop" by who created or last wrote a transcript, differently from the documentation this models. The warning
  therefore says "may delete" under that rule, and can over-warn (mechanics.md §4b, "Not yet modelled").

**Docs:** SKILL.md (ownership wording, "What moves", troubleshooting), mechanics.md (§0 contract, §1 layout, §2
log lines, §4b retention, §5a Desktop 5), `references/desktop5-fields.md`, and the guides: a later account switch
strands the sessions again (switch-accounts.md), new messages (troubleshooting.md).

**Reviewed** before release: four reviewers (validation and entries, logs and verify, retention, classification)
reported 29 findings, each re-checked by a second reader trying to refute it, mostly with sandboxed reproductions;
27 held and are fixed above, 2 did not hold.

**Tested:** `tests/run_all.py`: session-rehome 593 checks (56 new: 7 in "Desktop conversations an older terminal
Claude Code deletes for their age (doctor, status)", 16 in "Desktop 5 (5.11492.0, macOS): log lines, per-account
files, imported and scratch sessions", 18 in "0.11.2 review: the Desktop 5 guards per session, --to-profile,
rollback, adopt and the Remote Control clamps", 6 in "0.11.2 review: reading Desktop's log (shared macOS log,
same-second order, transitional lines, verify)", 9 in "0.11.2 review: the retention warning (crashes, cost, earlier
conversations, rows, Desktop entrypoints)"; each failed on the code before its fix, except fixture and guard
checks), session-transporter 40 checks, repository tests.

## 0.11.1 — 2026-11-09

- **A Desktop record field first seen on a real Mac** (Desktop 4.23118.0, macOS 26.6), `startedFromEnvironmentId`,
  made `doctor` report DRIFT and every move refuse there. Desktop's own code validates it next to `sshConfig` and
  `wslConfig` as an id or null: the environment (SSH, WSL, ...) a session was started in, on that machine. It is now
  known: kept when a session moves between accounts or windows on one machine, dropped (like the other
  machine-bound fields) when `adopt --cwd` files the record on another machine.
- Installed from GitHub on a Raspberry Pi (Debian 13 aarch64, Python 3.13) and a Mac (macOS 26.6, Python 3.9.6) with
  `install.py`; `doctor` ready on both.

**Tested:** `tests/run_all.py`: session-rehome 537 checks (0 new; two fixtures now carry the field),
session-transporter 40 checks, repository tests.

## 0.11.0 — 2026-11-08

**CLI homes: terminal accounts as profiles.** The terminal CLI keeps one config dir per account (`CLAUDE_CONFIG_DIR`;
`~/.claude` by default) with its own `projects/`, settings and login, and files no session by account: sessions reach
another account by being moved or copied to its home. `ccd-rehome` takes `cli`, `cli:NAME` (`~/.claude-NAME`) or a
config dir's path wherever it takes a profile.

- **Listing:** `profiles` lists CLI homes beside Desktop windows; `status cli:NAME` names a home's account and
  archives and prints the `--copy` into another account's home (JSON `move`, `move_why`); `sessions cli` flags
  `OPEN`, the Desktop profile showing a session and `older than N days`. Credentials are never opened.
- **Move and `--copy` between homes:** `move cli[:NAME] [--only ID …] [--project DIR] --to-profile cli[:NAME]` moves
  each transcript byte for byte with its sidecars, tasks, todos and file history, and copies the project memory;
  `--copy` keeps the source. Every move the tool advises between homes is a copy.
- **Refusals** (nothing written; a dry run lists them and exits 1), among them: an open session; a move out of
  `~/.claude` of a conversation a Desktop record names; a different transcript with that id in the target; links,
  special files, paths escaping a home; an item the target has; `--keep-dates` where it loses the only copy.
- **Warnings, retention included:** a transcript older than the shortest `cleanupPeriodDays` (or
  `desktopSessionCleanupPeriodDays`) of the target's `settings.json`, `remote-settings.json`, `managed-settings.json`
  or `managed-settings.d/` is re-dated (on a `--copy`, only the copy), which only postpones deletion; one last
  continued in Desktop only if `claude --version` is below 2.1.248 or unknown. Also warned: homes in different
  organizations, a signed-out target.
- **All-or-nothing moves, exact undo:** a failed step (a full disk, Ctrl-C, SIGTERM, SIGHUP) undoes the move, checked
  on disk; `rollback P ARCHIVE` restores the state before the move (mtimes too) and finishes a cut-off one.
- **Desktop windows and CLI homes:** Desktop reads `CLAUDE_CONFIG_DIR ?? ~/.claude` and nothing on disk says which,
  so every rule takes each window to read `~/.claude`. For a record whose conversation is only in another home,
  `sessions PROFILE` prints the copy into `~/.claude` (`move cli:NAME --only CLI_ID --to-profile cli --copy`);
  `status` counts them; `register` files only a conversation in `~/.claude`.
- **Any layout:** Desktop profiles and CLI homes can be in any folder (`~/.claude-instances` is only an example, used
  while it exists, never created): `profiles --add PATH` / `--add-root DIR` / `--forget PATH` or
  `$CCD_REHOME_INSTANCES` register them; discovery also reads `--user-data-dir` in shell startup files and Desktop's
  shared macOS log; `profiles` says where each was found (`found_by`). `st-bundle --desktop-profile NAME` resolves a bare name through session-rehome, so the transporter follows the same rules. A bare name, or `cli:NAME`, also matches a
  known folder of that name, never two. The state moved to the platform's state folder
  (`~/.local/state/session-rehome` on Linux); an existing `~/.claude-instances/_rehome` keeps being used.

**Changed behaviour:** `rehome --all` skips CLI homes; `--help` says what each kind of move writes; a refusal says
"Nothing was changed." once; glob characters in paths work; a Desktop `rollback` restores a recreated folder's mode;
the guides no longer say that every window and the terminal share one home's conversations.

**How it was made.** The feature was implemented by a local DeepSeek V4.1 model from a written spec (the facts now in
`skills/session-rehome/references/mechanics.md` §4b), reviewed by Claude in seven adversarial rounds, and repaired by
Claude. Round 1 had five reviewers and 48 verifiers, and 47 findings were confirmed; rounds 2 to 7 each reviewed the
previous repair and fixed what they found with fix agents, verifiers and critics. Each fix came with a check that
failed before it, and was broken on purpose to prove that check. The round-by-round history is in the skill's
[`references/cli-homes-review-log.md`](skills/session-rehome/references/cli-homes-review-log.md).

**Tested:** `python3 tests/run_all.py` on Linux (Python 3.14.4): session-rehome 537 checks (425 new: 5 in "the
self-test's own hash sees hidden paths, modes and symlink targets", 24 in "Any layout: profiles and homes outside
~/.claude-instances", 47 in "CLI homes (CLAUDE_CONFIG_DIR)", 41 in "CLI
moves that fail part-way, partial states, and rollback", 35 in "CLI moves: which sessions, symlinks, glob characters
and refusals", 48 in "Desktop windows and CLI homes: every window taken to read ~/.claude, records that keep a
session there, shadowed names", 54 in "Reports and discovery: CLI-home archives in status, the status --json shape,
shell-file discovery, the move hint, sign-in warnings, Windows commands", 13 in "What the tool says about itself, the
target of a CLI move, and rules that had no check", 31 in "Second review of CLI moves: links in the target, rules
that had no check, special files, interruptions, the only copy left", 22 in "Second review of messages: an empty
login file, a refusal said once, unregister on Windows, how many archives status shows", 10 in "Second review of the
docs: where a Desktop move leaves the conversation, and which refusal a name that is no home prints", 6 in "Third
review: Windows directory junctions inside a session, its project memory and the target", 18 in "Fourth review:
copies for a conversation in another home, ~/.claude by a second name, CLI ids in the advice, a record's earlier
conversations, walks that stop at a junction", 25 in "Fifth review: the status and rehome advice is a copy into the
home of another account, --keep-dates refused where it loses the only copy, a record's earlier conversation,
transcripts last continued in Desktop kept at any age", 25 in "Sixth review: a plain move of an old transcript last
continued in Desktop, managed settings, the sidecar files of a re-dated transcript, and the conversations of a
Desktop window that are only in another home", 21 in "Seventh review: the shortest retention any settings source sets
(managed-settings.d too), and a --copy re-dated where the destination would delete it"), session-transporter 40
checks, repository tests pass; the session-rehome self-test also passes with the macOS and Windows layouts emulated,
and each documented CLI-home rule, removed from a copy of the tool, fails a check (`mechanics.md` §4b). **With the
real Claude Code CLI:** one measurement, the orchestrator's run on 2026-11-08 with Claude Code 2.1.319: a moved
transcript (0.5 MB) resumed in the target home, not in the source. `tests/e2e_real_cli.py` repeats it; it is manual,
and here only its skip path and a stand-in `claude` ran.

**Not tested / not read:** the macOS shared-log discovery on a real Mac with several instances; a move on a real
signed-in CLI home (no live `move-cli` entry in `tested.json`: dry-run
first); `tests/e2e_real_cli.py` with the real CLI; Python 3.9 itself (CI runs it); the cmd and PowerShell lines in a
real shell; the macOS Keychain; a Desktop window started with `CLAUDE_CONFIG_DIR`; a real EXDEV, terminal SIGHUP,
agent timeout, directory junction or second name of `~/.claude` (all simulated), or a cut-off copy on a filesystem
without inode numbers; the real-failure checks on macOS and the symlink refusals on Windows; whether Desktop still
reads `priorCliSessionIds`; the Desktop retention rule with the real CLI (it is from Claude Code's documentation),
which Claude Code runs a home's cleanup, and a real managed-settings file, drop-in or `remote-settings.json`; the
troubleshooting rows' explanations. `tasks/` and `file-history/` are not re-dated. Not read by the tool:
project-level settings (`.claude/settings*.json` in a project, `--settings`), which can also set `cleanupPeriodDays`;
MDM profiles and the Windows registry; the HIPAA configuration.

## 0.10.0 — 2026-11-08

**Renamed: the project is now `session-rehome`** (https://github.com/kulogix/session-rehome; GitHub redirects the
old address), and its skills are **`session-rehome`** (one machine) and **`session-transporter`** (between
machines). The Agent Skills rules say a skill's name "cannot contain reserved words: `anthropic`, `claude`", so
`claude-desktop-rehome` and `claude-session-transporter` could never have been uploaded to claude.ai or the Skills
API (Claude Code itself accepted them). The plugin keeps its name, `session-rehome@kulogix`; the commands keep
theirs (`ccd-rehome`, `st-bundle`, `st-verify`).

- **Upgrading needs no clean-up by hand:** `install.py` removes its own 0.9.x links and unchanged copies, refuses a
  folder under an old name that it did not make (moves it aside with `--force`), and recognises its 0.9.x
  launchers. See docs/install.md, "Moving from earlier versions".
- **Projects moved with 0.9.x keep working:** their `CLAUDE.md` block (marker `claude-session-transporter`) is
  recognised by `st-verify.sh` and upgraded in place by the next transplant, never duplicated. `st-transplant.py`
  also finds the rehome tool under its 0.9.x folder name.
- **A test enforces the naming rule:** no skill name may contain `claude` or `anthropic`, or exceed 64 characters.

**Tested:** `python3 tests/run_all.py` (both self-tests and the repository tests), including the installer's
upgrade paths (an old link, an old launcher, a foreign folder under an old name).

## 0.9.3 — 2026-11-08

- **Every text file is read and written as UTF-8, on every OS.** 36 text-mode `open()` calls named no encoding, so
  on Windows they used the ANSI code page (cp1252). Found by the Windows CI run: `st-transplant.py` wrote the
  destination `CLAUDE.md` in cp1252, and it appends the relocation notice to the transcript the same way (the
  notice keeps non-ASCII characters verbatim, so on Windows it would have put non-UTF-8 bytes into a
  conversation file, or crashed). Fixed in all scripts (the tools, their helpers and both self-tests); a new
  static test fails on any text-mode `open()` without an explicit encoding.
- `ccd-rehome` writes UTF-8 to a pipe too, like the transporter's tools.

**Tested:** `python3 tests/run_all.py` on Linux: rehome 112/112, transporter 39/39, repository tests pass. Windows
results come from CI.

## 0.9.2 — 2026-11-07

- **`st-bundle.py` and `st-transplant.py` write UTF-8 on every OS.** On Windows, output to a pipe defaulted to the
  ANSI code page (cp1252), where characters these tools print (such as `→`) cannot be encoded, and the output
  arrived garbled at whatever read it. Found by the Windows CI run. The transporter self-test writes UTF-8 too
  (`python -I` ignores `PYTHONIOENCODING`), so its report of a failure can no longer crash.

**Tested:** `python3 tests/run_all.py` on Linux: rehome 112/112, transporter 39/39, repository tests pass. Windows
results come from CI.

## 0.9.1 — 2026-11-07

Fixes from the first CI run on Windows (Windows remains experimental).

- **`ccd-rehome resume-cli` warns inside a Desktop session on Windows too.** It used to stay silent there, because
  its remedy (`env -i`) does not exist on Windows. The hazard does: a `claude` started from a shell inside Desktop
  inherits Desktop's environment. On Windows the remedy is now a new terminal window. New self-test check, which
  runs the Windows branch on every OS.
- **Line endings:** `.gitattributes` keeps every text file LF on checkout, on every OS. A Windows checkout had
  turned them into CRLF, which broke the SKILL.md frontmatter and the shell scripts under Git Bash.
- **Tests:** the self-test's stand-in `claude` is a `.cmd` file on Windows, so the "older CLI" warning is tested
  there too; the repository tests read CRLF files the same as LF; `tests/run_all.py` prints the tool output under
  each failing self-test check (and the traceback when one crashes), so a CI log shows why. The transporter
  self-test tests whether `bash` actually runs (on Windows, PATH can find the WSL launcher, which runs nothing
  without a distribution): its pure-Python checks run everywhere, and on Windows it says which `.sh` checks it
  skipped. CI uses the current major versions of its actions.

**Tested:** `python3 tests/run_all.py` on Linux (rehome self-test 112/112, transporter 39/39, repository tests).
Windows results come from CI.

## 0.9.0 — 2026-11-07

The first release of **claude-session-rehome**, which joins two projects into one: the account and window tool
`claude-desktop-rehome` (previously its own repository, last at 0.8.0) and the cross-machine
`session-transporter` (previously unpublished; its bundle tool was `st-bundle 0.1.0`). Versions before this one
belong to those projects; their history follows below.

**New**
- **One project, two skills:** `skills/claude-desktop-rehome` (one machine) and `skills/claude-session-transporter`
  (between machines), each with a routing table at the top of its SKILL.md that sends an agent to the other when
  it was loaded for the wrong job.
- **`install.py`:** links (macOS, Linux) or copies (Windows) the skills into `~/.claude/skills`, and with `--bin`
  writes `ccd-rehome`, `st-bundle` and `st-verify` launchers. `--status`, `--uninstall`, `--dry-run`. It never
  deletes anything it did not create unchanged: a folder it did not make, or a copy edited after installing, is
  moved to `~/.claude/skill-backups/`.
- **A Claude Code plugin:** `session-rehome` in the `kulogix` marketplace (`.claude-plugin/`).
- **`st-bundle list`:** every session on this machine with its id, folder, title and opening words, so the
  bundle path no longer starts with a uuid nobody knows. Pure Python, so it also works on an origin without bash.
  The folder is the newest record's `cwd`, so a transplanted session shows its local folder, not the origin's.
- **Human guides in `docs/`:** install, getting Claude Desktop per OS, several Desktop windows, switching accounts,
  terminal ↔ Desktop, other machines, troubleshooting, how it works.
- **Repository tests (`tests/`):** a privacy scan of every file; skill structure and routing; every command line in
  the docs checked against the tools' own `--help`; links and anchors; manifest formats; one version everywhere;
  the installer. `tests/run_all.py` runs them with both self-tests.

**Changed**
- The transporter is renamed `claude-session-transporter`. Projects migrated before the rename keep working: their
  `CLAUDE.md` relocation block (old marker) is recognised and upgraded in place, never duplicated.
- The transporter's SKILL.md leads with the bundle (the common case). The ssh-based gated procedure moved,
  unchanged in substance, to `references/gated-procedure.md`.
- Both SKILL.md files run their scripts through `${CLAUDE_SKILL_DIR}`, so they work as personal skills, plugin
  skills, or from a checkout. No fixed install path remains.
- `tested.json` lives in each skill folder (it must travel with a copied skill). The transporter has its own.
- `ccd-rehome doctor` reports how far this OS is verified from `tested.json`, instead of a hard-coded "Linux
  only". `doctor` is in the command parser's list (the usage text and the parser now agree, and a test keeps them
  so). Pointers to files that exist only in the repository now use the project URL.

**Tested:** both self-tests (rehome: 111 checks; transporter: 39), the repository tests, `claude plugin validate`
(Claude Code 2.1.319), and the installer in a temporary home (link, copy, launchers, refusals, backups,
uninstall). Not tested in this release: a real Windows machine; a live account move on macOS; moves between
different organisations.

## Before 0.9.0: claude-desktop-rehome

All on 2026-11-07.

- **0.8.0:** `move --to-profile` moves sessions to another Desktop window (user-data-dir) on the same machine:
  adopted there first, then removed from the source, both archived, task suggestions included.
- **0.7.2:** measured a full terminal → Desktop → terminal round trip with real turns (Desktop 2.31226.1, CLI
  2.1.319). `quit` and every running check count Desktop's per-session wrapper processes. `resume-cli` warns when
  run from inside a Desktop session and prints a clean-environment command.
- **0.7.1:** `register` restores a session's Desktop settings from its archived record. `resume-cli` warns when the
  terminal CLI is signed in to another account, is older than the CLI that last wrote the conversation (2.1.263
  did not know `claude-opus-5-5`), or is not signed in.
- **0.7.0:** terminal ↔ Desktop: `cli-sessions`, `register`, `resume-cli`, `unregister`. The mangler mirrors the
  transporter's canonical one, cross-checked by the self-test.
- **0.6.2:** the community Debian package's rename at Desktop 4.x (`claude-desktop` → `claude-desktop-unofficial`);
  the keyring setting it then needs (Desktop 4.23118.0, Debian 13 aarch64).
- **0.6.1:** sign-in detection for older builds without `lastKnownAccountUuid` or login-state lines; `quit` reports
  a build that ignores SIGTERM (Desktop 1.9255.2, Debian 13 aarch64).
- **0.6.0:** `export-record` and `adopt`, the interface the transporter's bundle uses for Desktop records.
- **0.5.0:** Desktop 4.x support found by `doctor` on the first real Mac: 18 new record fields classified, the
  Cowork 4.x layout understood, Cowork moves refused while spaces or agents hold data (Desktop 4.23118.0 macOS
  26.6 arm64; 2.31226.1 Ubuntu 26.04; 1.4758.0 Debian 13 aarch64).
- **0.4.1:** UTF-8 everywhere on Windows (non-ASCII titles), console output that cannot crash, CI on Python 3.9.
- **0.4.0:** validation before every move (ERROR, DRIFT, `--accept-drift`), true dry runs, `tested.json`,
  `doctor` and `report`, MIT license.
- **0.3.0:** drift checks in `doctor`; the "Maintaining this skill" rules; fixes for `--json`, paths with spaces,
  session cookies, dotfiles in rollback; macOS and Windows layouts.
- **0.2.0:** any user-data-dir and any number of accounts; `move --to/--from/--only/--to-org`; queued work and task
  suggestions travel; Cowork with `--include-cowork`.
- **0.1.0:** `status`, `accounts`, `rehome`, `rollback`, `quit`, `launch`, `verify`, verified on 5 windows and 2
  accounts (Desktop 2.31226.1, Linux).

## Before 0.9.0: session-transporter

- **st-bundle 0.1.0 (2026-11-07):** the portable bundle (`export`, `inspect`, `import`, `origin-proof`): the
  checkpoint whitelist in one hash-verified zip; import hands over to `st-transplant.py`. Fixes found on a live
  push migration: `--settings-key` defaults that could not be turned off; `--no-memory`; `st-verify.sh
  --origin-proof` for a destination that cannot reach the origin; Desktop records adopted through
  claude-desktop-rehome; Python fallbacks where rsync, `tail` or `ps` are missing. Verified: exported on Linux
  x86_64, imported on macOS 26.6 arm64 and Debian 13 aarch64, loaded by each machine's own CLI, origin proven
  unchanged.
- **Founding revision:** the gated procedure (preflight, checkpoint, git rescue, transplant, verify, write-back),
  packaged from one completed cross-host, cross-account migration (macOS arm64 → Linux x86_64, a 216 MB
  transcript, 2,157 files, byte-identical) and reviewed adversarially. Its evidence is in
  `skills/claude-session-transporter/references/evidence-base.md`.
