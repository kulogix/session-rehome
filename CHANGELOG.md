# Changelog

One version for the whole project: both tools (`ccd-rehome`, `st-bundle`) and the plugin carry it. Each entry
says what changed, what was tested, and what was not. Dates are when the change was made; Desktop and CLI
versions are the ones it was measured against.

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
