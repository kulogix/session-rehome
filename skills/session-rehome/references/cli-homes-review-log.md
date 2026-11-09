# CLI homes in 0.11.0: the historical review log

This is a historical record, not a manual. It is the `## 0.11.0` entry of the project's CHANGELOG.md as it stood
after the seventh review round (2026-11-09), moved here verbatim when that entry was condensed into a release note.
It tells round by round how the CLI-home feature was reviewed and repaired. Its commands, messages, check counts,
file names and test names are as of each round, and some describe rules that a later round replaced: they are not
instructions for today's tool. For the rules as they are now, read `SKILL.md` and `cli-homes.md`; for the evidence
behind them, `mechanics.md` §4b.

## The 0.11.0 entry as of the seventh round

**CLI homes: rehome terminal sessions between accounts.** The terminal CLI keeps one config dir per account, chosen
with `CLAUDE_CONFIG_DIR` (`~/.claude` by default), and each home has its own `projects/`. It does not file sessions
by account, so after a sign-in change nothing inside a home is stranded. To use sessions with another account, move
or copy them to the home where that account is signed in: `move cli` moves the conversation byte for byte (with
`--copy`, copies it), and what the tool advises is a copy.

**How it was made.** The feature was implemented by a local DeepSeek V4.1 model from a written spec (the facts now
in `skills/session-rehome/references/mechanics.md` §4b, and the behaviour wanted), reviewed by Claude in two
adversarial rounds, and repaired by Claude. The first round confirmed 47 findings (data safety and rollback,
refusals, Desktop interplay, discovery, portability, documentation). The second, a completeness pass over that
repair, found 13 more items: five in move and rollback (one of them data loss: a `--copy` rollback deleted the only
copy left), four about Desktop windows, names and messages, and four about the documents and their evidence. A
final review of that repair found that its `register` rule brought back a first-round finding (#14: advice to move
a live conversation out of `~/.claude` into a backup home), so a third repair round settled the Desktop rules on
one assumption (below) and also made the link checks see Windows directory junctions. A final review of that
round found that its new advice moved an old conversation out of a backup home into `~/.claude`, where retention
would delete it a month later, so a fourth round made every such piece of advice a `--copy` (below). A final
review of that round found the same advice left in `status` and `rehome` (a plain move of a whole backup home into
`~/.claude`, offered as a switch to another account between two homes of one account), so a fifth round made it a
`--copy` too, refused `--keep-dates` where it loses the only copy, and followed Claude Code's documented retention
rule for transcripts last continued in Desktop (below). A final review of that round found that a plain move of
such a transcript was no longer re-dated and said only that it was kept, so a sixth round made that depend on the
Claude Code version, read managed settings, re-dated the sidecar files too and made `status` show a window's
conversations in another home (below). A final review of that round found that its reading of managed settings
could miss a shorter limit Claude Code applies, and that the `--copy` advised for a window was never re-dated, so a
seventh round made the tool take the shortest limit any source sets and re-date such a copy (below). Every
item was repaired test first: each fix came with a check that failed before it (or, for a rule that had no check,
one that fails when the rule is removed), and each fix was then broken on purpose to show that its check catches
it. The bullets below describe the result, review fixes included.

- **Naming:** `cli` is `~/.claude`; `cli:NAME` is `~/.claude-NAME`; any path to a Claude Code config dir works.
  `profiles`, `status`, `sessions`, `rehome`, `move` and `rollback` accept all three. A folder is a CLI home when it
  has `projects/`, `.claude.json`, `.credentials.json` or `settings.json`, and is not a Desktop profile. While a
  Desktop profile `~/.claude-instances/cli` exists, `cli` fits both and is refused as ambiguous; the message names
  both paths, and the tool prints `~/.claude` (and the instance called `cli`) by its path, so every command it
  prints works as printed. `cli:NAME` is never ambiguous: a Desktop profile `~/.claude-instances/cli-NAME` is named
  `cli-NAME` (it used to be refused as ambiguous too).
- **Discovery:** `~/.claude`, `~/.claude-*` and `~/.claude_*` (never `~/.claude-instances`), every real
  `CLAUDE_CONFIG_DIR=/absolute/path` assignment in the usual shell startup files, the tool's own
  `CLAUDE_CONFIG_DIR`, `$CCD_REHOME_CLI_HOMES`, and every CLI home named on the command line before. Shell files
  are read line by line without their comments, and only an assignment at the start of a word with no spaces
  around `=` counts (not `OLD_CLAUDE_CONFIG_DIR=`, not `[ "$CLAUDE_CONFIG_DIR" = ~ ]`, not a relative path). The
  home folder itself (it holds the default home's `.claude.json`), every folder above `~/.claude`,
  `~/.claude-instances` and every folder that is or holds a Desktop profile are never CLI homes: they are skipped
  when found and refused with the reason when named (`--to-profile ~` used to move sessions into the home folder).
  A home found in a shell file is not remembered, so removing its line removes it.
- **Signed-in state without secrets:** only file existence and size are checked. A non-empty `.credentials.json`
  means signed in; an empty one holds no login and is reported as empty (signed out on Linux/Windows); on macOS a
  missing or empty one means `unknown` (the Keychain is never queried).
  `.credentials.json` and `sessions/*.key` are never opened, printed or copied.
- **Reports:** `profiles` adds CLI rows (`kind`, verdict, e-mail, session count, live count, org); `status`
  explains that the CLI lists every session whatever account is signed in, prints the exact copy
  (`move … --to-profile … --copy`) into the home where another account is signed in, and lists the home's `cli-move`
  archives (the newest three, with how many there are in all and that `--json` lists them when there are more;
  `archives` in JSON; Desktop rows the same way). When every other home has the same account it says so and prints
  no command (copying there switches no account); when a home's account is not known it says so and prints the copy
  (JSON `move_why`: `another-account`, `account-unknown`, `same-account` or `no-other-home`). With no other CLI home
  it prints no move command (JSON `move` is null) but how to make one: start
  `CLAUDE_CONFIG_DIR=~/.claude-NAME claude` once and sign in there, then the copy into it. A CLI row of
  `status --json` carries every key a Desktop row has, with neutral values (`stranded` `{}`, `elsewhere` `{}`,
  `cowork_stranded` 0, `visible` `[]`, `active_dir`, `blocker`, `cookie_expires`, `last_account_email` null), so a
  consumer of 0.10's rows reads it unchanged; `sessions cli` lists each transcript with its folder, title, `OPEN`,
  `desktop: PROFILE`, and an `older than N days` flag from that home's retention (none for a transcript last
  continued in Desktop unless `desktopSessionCleanupPeriodDays` is set; JSON `last_entrypoint`). A transcript reached
  under a second project folder through a symlink (a renamed repo's alias) is one session, listed by its real folder.
  A `sessions/<pid>.json` that is not a JSON object (`null`, `[]`, a truncated write) is skipped.
- **`move` between CLI homes** takes `--only ID …`, `--project DIR`, `--copy`, `--no-memory`, `--keep-dates` and
  `--dry-run`. It moves the transcript byte for byte, the sidecar folder, sibling-key sidecars, `tasks/<id>/`,
  `todos/<id>*.json` and `file-history/<id>/`; it **copies** the project memory file by file (a different file
  already in the target is kept and reported). It never moves `history.jsonl`, `sessions/`, `session-env/`,
  `settings.json`, `.claude.json`, `.credentials.json`, `plans/`, `shell-snapshots/` or `debug/`. It refuses, before
  anything is written, an OPEN session, a move that would take a session out of `~/.claude` while any Desktop
  profile has a record for it, as its current or one of its earlier conversations (`priorCliSessionIds`) (unregister
  it first, or `--copy`; for an earlier conversation only `--copy`, since unregistering that record would also take
  its current conversation out of the window; a move INTO `~/.claude` is always allowed, which is how a record shown
  `in cli:work` gets its conversation back, and a move between two other homes goes ahead with a note: see "Desktop
  windows" below), a differing transcript already in the target, an id that has a transcript in two project folders
  of the source (resume by id cannot pick one; moving both would put the duplicate in the target), an item that is a
  symlink or is reached through a symlinked folder, or holds a symlink (a `--copy` never follows one; on Windows a
  directory junction or any other reparse point counts as a symlink in every link check, and no walk inside an item,
  the project memory or a copy in the target descends into one), a project memory folder that is, contains or sits
  below a symlink (never followed or read; `--no-memory` moves the session without it), a path that escapes the
  home, a FIFO, socket or device file anywhere in an item or the project memory (never opened, so a named pipe can
  no longer hang the hashing), an item the target already has (such as its own `todos/<id>-agent-*.json`, never
  overwritten), a move (not `--copy`) with `--keep-dates` of a transcript the target's cleanup would delete (it
  would go at the target's next start, and nothing else would have it; for one last continued in Desktop, when
  `claude --version` is older than 2.1.248 or not known), and any path in the target that resolves
  outside it, has a symlink at or above it inside the target (a linked `tasks/` or `projects/<key>/`, even one that
  leads back inside), or is a FIFO, socket or device file; an identical transcript is reported as already there. A
  dry run that finds a refusal shows the plan and the `REFUSE` lines, says the real run would REFUSE, and exits 1,
  like the real run. Same-filesystem moves use an atomic rename, with a fallback to the copy when the rename fails
  with EXDEV (two mounts of one filesystem). Other moves copy to a temporary name in the target folder, verify size
  and sha256, and only then rename the copy into place and remove the source; a partial copy is removed.
- **A move is all or nothing:** it prints its archive name before the first change. When a step fails (a
  permission, a full disk, Ctrl-C, and, for the duration of the move, a SIGTERM such as an agent's command timeout
  or a SIGHUP from a closed terminal; one the caller ignores, as under `nohup`, stays ignored, and the caller's
  handlers come back afterwards), the steps already started are undone newest first, including a re-dated
  transcript's mtime and those of its sidecar files. The undo decides each step from what is on disk: the identity
  (`st_dev`, `st_ino`) of what a rename is about to place is recorded before the rename, so an item renamed into the
  target just before an interruption goes back too. The tool says nothing was changed, and removes the archive, only
  after checking that every item is back in the source as the move found it and nothing it placed is left in the
  target. If the undo cannot finish or cannot confirm that, the archive is kept and the message names the rollback
  that finishes the job.
- **Warnings:** an old transcript that the target home would clean up (re-dated, with the files of its sidecar
  folder, which only postpones the deletion: the target deletes it again after `cleanupPeriodDays` without new
  activity; with `--copy`, `--keep-dates` keeps the old date instead; on a move, not `--copy`, the warning also says
  that the source no longer has it and names `--copy`, never `--keep-dates`). `cleanupPeriodDays` and
  `desktopSessionCleanupPeriodDays` are read from the target's `settings.json`, the server-managed settings cached in
  its `remote-settings.json`, `managed-settings.json` where the documentation puts it, and each
  `managed-settings.d/*.json` drop-in next to it; the tool takes the shortest value any of them sets, on purpose (it
  does not model how Claude Code combines them, so it may warn more often than Claude Code would delete, never
  less), and the warning names where that value is set. Which limit applies is read from the tail
  of the transcript, never the whole file: one whose most recent records were written by Claude Desktop is kept at
  any age by Claude Code 2.1.248 and later unless `desktopSessionCleanupPeriodDays` (or a managed
  `cleanupPeriodDays`) is set. An earlier Claude Code deletes it after `cleanupPeriodDays`, so a move or a `--copy`
  of one older than that reads `claude --version`: 2.1.248 or later, it is not re-dated (on a `--copy`, a note says
  what still deletes it); older or not known, it is re-dated; the warning says which, and after a move that the
  source no longer has it. On a `--copy` the copy is re-dated, never the source; with `--keep-dates` the copy keeps
  its dates and the warning says the target would delete it (the source keeps its own). Also warned: a move between different organizations (signed thinking may be
  rejected; unverified); a target that is signed out. On macOS a target without a login file is `unknown` (the login
  is in the Keychain): a note says so, never "sign in there".
- **Continue commands on Windows:** after a move, and in `resume-cli`, Windows gets a cmd line
  (`cd /d "…" && set "CLAUDE_CONFIG_DIR=…" && claude --resume ID`) and a PowerShell line
  (`Set-Location -LiteralPath '…'; $env:CLAUDE_CONFIG_DIR='…'; claude --resume ID`): neither shell accepts the POSIX
  `VAR=value command` prefix.
- **The account registry reads each profile once per run:** a profile named on the command line was passed twice
  (and its IndexedDB and Local Storage read twice).
- **Archive and undo:** a `<timestamp>-cli-move` archive records every source and destination path with size, sha256
  and mtime, and the memory files copied. `rollback SOURCE|TARGET ARCHIVE` moves back what is in the target, files
  the session added there after the move included (a transcript that grew is moved as it is now), and skips what
  never left the source, so it also repairs a move that was killed part-way; an item in both homes refuses. An
  unchanged transcript gets its original mtime back, and so does each unchanged file of its sidecar folder. Copied
  memory that is unchanged is removed, unless a session of that project that came to the target later still lives
  there, or whose original in the source was deleted since. A `--copy` session is one unit: its copies are removed
  only when none of them changed and every original is still in the source (a rollback used to remove the only copy
  left once the original had been deleted); it compares their content, never their mtimes, so a re-dated copy is
  removed like any other. It refuses when a folder of the source it would move back into is now a
  symlink or leads out of the source. It refuses, like a move, while the session is open in the target (registry
  entry or another process). A Desktop record never refuses it, since it restores the state before the move (so the
  undo a move prints always works): when it takes a session a profile lists back out of `~/.claude`, or removes its
  `--copy` there, it warns and prints the `--copy` that gives that window its conversation back. A rollback that
  stops part-way finishes when run again. CLI-move archives live in `~/.claude-instances/_rehome/cli-archive/`, apart
  from the Desktop profiles' archive folders (so a Desktop instance called `cli` or `cli-work` never shares one with
  a CLI home), and their names are unique across all homes.
- **Desktop windows now follow their records:** `sessions PROFILE` shows `in cli:NAME, CLI id …` when a record's
  transcript lives in another home than `~/.claude`, and prints the exact copy that brings those conversations into
  `~/.claude` (`move cli:NAME --only <CLI ids> --to-profile cli --copy`: a copy, so a backup home keeps its own, and
  by the CLI id a move takes, not the record id); `status PROFILE` counts those records per home
  (`N of these records' conversations are only in cli:NAME, not in ~/.claude`, with `sessions PROFILE` for the copy;
  JSON `elsewhere`); `cli-sessions` lists every known home. Desktop reads
  `CLAUDE_CONFIG_DIR ?? ~/.claude`, and nothing on disk says whether a window set it, so every rule takes each
  Desktop profile to read `~/.claude`: a move out of `~/.claude` of a session any profile lists is refused, a move
  into it is always allowed, a move between two other homes gets a note, and `register` always accepts a
  conversation in `~/.claude` and refuses one in any other home with the copy INTO `~/.claude`
  (`move cli:work --to-profile cli --only ID --copy`, then run the register again); a rollback's warning prints a
  copy too. `~/.claude` is recognised by identity (`os.path.samefile`), so a second name for it (a bind mount, a
  macOS firmlink, `~/.Claude` on a case-insensitive disk) is still `~/.claude` in every rule. Where a profile's records'
  transcripts happen to be (`~/.claude` unless none is there and most are in one other home) is a display hint
  only: the `desktop:` flag of `sessions cli:NAME`, a note at the end of `sessions PROFILE`, and notes in
  `register` and `resume-cli`. It decides nothing, because a backup copy of `~/.claude` fools it. `resume-cli` and
  `unregister`'s hint name `CLAUDE_CONFIG_DIR=` the home that holds that conversation's transcript (on Windows in
  cmd and PowerShell syntax; `unregister` printed a POSIX line there).
- **Refusals say "Nothing was changed." once:** a CLI move's or rollback's reasons no longer carry it, so the final
  line is the only one that does (it used to read "nothing was changed. Nothing was changed.").
- **Paths are paths, not patterns:** a CLI home or Desktop profile path with `[`, `]`, `*` or `?` in it (say
  `~/homes/work[1]`) works in every command; the tool escapes the path in every `glob`. Unescaped, such a home
  listed no sessions and the duplicate check missed a transcript already there.
- **Desktop `rollback` gives a recreated folder its permissions back:** a folder the undo has to create again (a
  moved Cowork session folder, for example) now gets the mode it had in the archive; it used to come back as 0700.
- **Documentation says what the code does and how far it is tested:**
  - the README no longer says that one-machine moves never copy a conversation: each `CLAUDE_CONFIG_DIR` home has
    its own `projects/`, and `move cli` moves (or copies) the conversation between homes;
  - `ccd-rehome --help` no longer says the tool never copies a transcript or touches another profile; it says what
    each kind of move writes, and that `profiles` lists CLI homes too;
  - `docs/troubleshooting.md` and SKILL.md have a row for every refusal the CLI-home code can print (15 of its 43
    messages had no row in the guide, 25 none in SKILL.md, among them `--to-profile '…' is not a CLI home`), and the
    `is not a Claude Code config dir` row no longer says that a Desktop profile as the target prints it;
  - `references/mechanics.md` §4b tags `[M]` only what was measured, with when and on what, and its table names,
    rule by rule, a self-test check that fails without the rule, and the rules that have none (it used to say the
    self-test "exercises every rule");
  - SKILL.md, `docs/switch-accounts.md`, `docs/multiple-instances.md` and the README say that `move cli` has not
    yet run on a real signed-in CLI home, and to dry-run first;
  - `docs/multiple-instances.md`, `references/mechanics.md` §1 and `ccd-rehome --help` no longer say that every
    Desktop window, every profile and the terminal share the conversations in `~/.claude`: the instances that read
    the same CLI home share it, Desktop and the terminal read `CLAUDE_CONFIG_DIR ?? ~/.claude`, and each
    `CLAUDE_CONFIG_DIR` home has its own `projects/` (a Desktop `move --to-profile` moves the record; the
    conversation stays in its CLI home);
  - every message a troubleshooting row quotes (`docs/troubleshooting.md` and SKILL.md) is now what the tools print,
    word for word. Nine quotes of six messages were not: `verify: MISMATCH` and `verify … MISMATCH` (it prints
    `PROFILE: MISMATCH  Desktop loaded …`), `verify: has not logged loading … yet` (`Desktop has not logged loading
    … yet`), `no org known … ambiguous` (`no org known for … in this profile`, `ambiguous: N orgs known for this
    account`), `ERROR … refusing` (two lines), `Cowork move refused` (`Cowork user data (spaces / agents / settings,
    Desktop 4.x)`), and the installer's `an older install of session-transporter` (`looks like an earlier install
    of …, and both would load` / `an OLDER install is still present`);
  - the `is not a Claude Code config dir (no projects/, …)` rows no longer say a path prints it: only `cli:NAME`
    does. A path prints `… does not exist` (now a row of its own) or `not a Desktop profile (no config.json)` when
    it names what a command works on, and `--to-profile '…' is not a CLI home` as a CLI move's target;
  - the one run with the real Claude Code CLI is attributed (below), and the project has a manual test that repeats
    it, `tests/e2e_real_cli.py` (AGENTS.md says how to run it).
- **Repository tests:** `tests/test_docs_evidence.py` fails when a CLI-home refusal has no troubleshooting row, when
  the README contradicts `move cli`, when a guide drops the evidence statement (until `tested.json` records a live
  `move-cli` run), when the coverage table quotes a check `selftest.py` does not have, or when an `[M]` in §4b names
  no date or version. Since the second round it also fails when a troubleshooting row quotes a message that no tool
  prints word for word (a value the tool fills in may stand only for `…` or one placeholder such as `N`, `ID` or
  `cli:work`, never for words), when the `is not a Claude Code config dir` row ascribes that message to a path or
  `… does not exist` has no row, when a guide, mechanics.md or the tool says every window and the terminal share
  `~/.claude`'s conversations, when the real-CLI claim in §4b does not say whose run it was or name
  `tests/e2e_real_cli.py`, when that test is missing, would be collected by `run_all.py` or does not skip without
  `SESSION_REHOME_E2E=1` and a `claude` on `PATH`, and when this entry drops how the feature was made. Since the
  fourth round it also fails when a documented command that brings a conversation into `~/.claude` is not a
  `--copy`, or a retention row does not say that re-dating only postpones the deletion; since the fifth, when a
  retention row or mechanics.md's Retention fact leaves out the rule for Desktop transcripts (with the
  documentation's URL in mechanics.md) or offers `--keep-dates` on a move, or the advice for a new home is a move of
  the whole home; since the sixth, when a document says that the tool cannot see managed settings, mechanics.md
  has no Managed settings fact from the documentation (every path, the cache's shape tagged `[I]`), or a retention
  row leaves out what the tool reads (`remote-settings.json`, managed settings, `claude --version`, the sidecar
  folder); since the seventh, when a document says the tool skips the `managed-settings.d/` drop-ins, that a `--copy` of a Desktop
  transcript is not re-dated, or that the higher of two managed sources wins, when mechanics.md's Managed settings
  fact does not say that the tool takes the shortest value on purpose, or when a retention row or the move fact
  leaves out the shortest value, the drop-ins or the re-dated copy. On Linux, `tests/run_all.py` compares the counts below with the run and fails when they differ.

**Tested:** `python3 tests/run_all.py` on Linux (Python 3.14.4): session-rehome 513 checks (401 new: 5 in "the
self-test's own hash sees hidden paths, modes and symlink targets", 47 in "CLI homes (CLAUDE_CONFIG_DIR)", 41 in
"CLI moves that fail part-way, partial states, and rollback", 35 in "CLI moves: which sessions, symlinks, glob
characters and refusals", 48 in "Desktop windows and CLI homes: every window taken to read ~/.claude, records that
keep a session there, shadowed names", 54 in "Reports and discovery: CLI-home archives in status, the status --json
shape, shell-file discovery, the move hint, sign-in warnings, Windows commands", 13 in "What the tool says about
itself, the target of a CLI move, and rules that had no check", 31 in "Second review of CLI moves: links in the
target, rules that had no check, special files, interruptions, the only copy left", 22 in "Second review of
messages: an empty login file, a refusal said once, unregister on Windows, how many archives status shows", 10 in
"Second review of the docs: where a Desktop move leaves the conversation, and which refusal a name that is no home
prints", 6 in "Third review: Windows directory junctions inside a session, its project memory and the target", 18
in "Fourth review: copies for a conversation in another home, ~/.claude by a second name, CLI ids in the advice, a
record's earlier conversations, walks that stop at a junction", 25 in "Fifth review: the status and rehome advice is
a copy into the home of another account, --keep-dates refused where it loses the only copy, a record's earlier
conversation, transcripts last continued in Desktop kept at any age", 25 in "Sixth review: a plain move of an old
transcript last continued in Desktop, managed settings, the sidecar files of a re-dated transcript, and the
conversations of a Desktop window that are only in another home", 21 in "Seventh review: the shortest retention
any settings source sets (managed-settings.d too), and a --copy re-dated where the destination would delete it"),
session-transporter 39 checks, repository tests
pass. The whole session-rehome self-test also passes with the macOS and the Windows layout emulated
(`CCD_REHOME_PLATFORM=darwin`, `win32`). The new self-test builds a synthetic `~/.claude`, `~/.claude-work` and an alias-only home, and checks discovery,
sign-in without reading credentials (including a mode-000 file, and the verdict pinned per OS: `unknown` on macOS),
reports, dry run byte-identity, moves, memory conflicts, retention (that the destination's `cleanupPeriodDays` is
the one read), `--project`, rollback (including `--copy`), each refusal on its own, and register's cross-home
refusal. The self-test's folder hash now covers hidden files and folders, file modes and symlink targets. The hash
it used before was a glob, which skips dot-names: its byte-identity, nothing-written and exact-rollback checks could
not see `~/.claude`, any `~/.claude-*` home or `~/.claude-instances`. Injected defects now fail a check: a dry run
that writes into another home, a rollback that leaves copied memory behind or changes a mode, a refusal that writes
an archive first. The self-test no longer hands the tool the caller's `CLAUDE_CONFIG_DIR`, `CCD_REHOME_CLI_HOMES`,
`CCD_REHOME_PROFILES` or any other `CCD_REHOME_*` setting except `CCD_REHOME_PLATFORM`.
Failed and cut-off moves are tested with real failures where a test can make them (a read-only target folder on
POSIX, a file-size limit that cuts a copy short) and otherwise with `CCD_REHOME_FAULT`, a test-only switch the tool
honours only in its sandbox (an EXDEV rename, a copy that does not verify, a failure or a kill after N steps or in
the middle of a copy, a destination another process creates during the copy); `CCD_REHOME_OPEN_FILES` stands in
for another process holding a transcript open. 23 injected defects in move and rollback (no undo, an undo that
removes a destination this run did not create, no EXDEV fallback, no temporary name, no verification, partial
copies left, rollback refusing partial states or not refusing an item in both homes, no re-listing in the target,
per-item `--copy` rollback, mtime not restored, memory removed while a later session uses it, each missing
open-session or Desktop check) each fail at least one check.
The selection and refusal checks build a symlinked project folder (one session, moved once, rolled back exactly), a
project folder that is a symlink to elsewhere in the home, an id under two real project folders (`--project`,
`--only`, every session, dry run), a source home, a target home and a Desktop profile whose paths hold glob
characters, a memory folder linked outside every home, linked to the home itself, holding a linked folder or a
linked file (an unreadable file in the linked folder shows it is never read), registry entries that are `null`,
`[]`, a string or a number, and dry runs with and without a refusal. 28 injected defects there (no realpath dedupe,
the alias preferred, no item dedupe, no parent-symlink refusal, no duplicate-id refusal, `--only` counting rows,
each memory check removed or run after reading, the registry crash, a dry run that falls through or exits 0, and an
unescaped `glob` in the shared helper or at each of nine call sites) fail at least one check, except one: dropping
the dedupe of items across sessions changes nothing while the duplicate-id refusal stands (with that refusal also
removed, 4 checks fail).
The Desktop-and-CLI-homes checks build Desktop profiles whose records' transcripts are in `~/.claude`, in a
`~/.claude-work` and in a `~/.claude-backup` (a backup holding a profile's older transcripts), and a Desktop instance
called `cli` and one called `cli-work`. In the first round, 19 injected defects there each failed at least one
check: the old majority vote, `resume-cli` taking the profile's home or not looking there first, no ambiguity
refusal, a shadowed home keeping its short name, an instance `cli` keeping its name or losing its archive folder,
CLI archives back in the Desktop archive folders, archive names unique per home only, the default home told by its
name at each of four places, and six about the Desktop-record rules of that round (a move's or a rollback's record
check gated on the inferred home, a `--copy` rollback refused by any record, the inferred home always the default
one, register not accepting `~/.claude` or advising the inferred home). Those rules have changed since (the third
round, below): a rollback is never refused for a record, and every rule now takes each profile to read
`~/.claude` on purpose, so "always the default home" now describes the rules (that injected defect made the
inference always name it; today the inference only labels). The third round's own changes were checked against
the rules as they are now.
The reports-and-discovery checks build three homes with moves between them, a home with no second home, a fresh
machine with no state folder and no Desktop, and a `.bashrc` with every false-positive line found in review (`~`,
`$HOME`, `.`, `~/..`, `OLD_CLAUDE_CONFIG_DIR=`, a commented-out line, a trailing comment, spaces around `=`, a
relative path, a folder holding a Desktop profile, `~/.claude-instances`) next to four real assignments. They
count the opens of a profile's IndexedDB file (one per run), and pin the platform for the sign-in warning (Linux,
macOS) and the Windows command forms. 32 injected defects there (no archives, all archives, unreadable manifests
listed, no archives in the text, the Desktop keys missing or one not neutral, no registry dedupe, the sign-in
warning on `unknown` or never, no Keychain note, the POSIX prefix on Windows, cmd without `/d`, PowerShell given
cmd's syntax, resume-cli's old line, the literal `cli:work` fallback, the setup step in POSIX syntax on Windows,
the old unanchored regex, spaces around `=`, no comment removal, whole-line comments only, relative paths guessed,
HOME and the folders above `~/.claude` allowed, HOME refused only as a folder above `~/.claude`, the folders above
`~/.claude` allowed, `~/.claude-instances` allowed, a folder above a Desktop profile allowed, `~/.claude` not
exempt, every discovered home remembered, a named home not remembered, a refused folder handed to the Desktop
code, and the default home told by its name on the two rewritten continue lines) each fail at least one check.

The last section checks `--help` and eight rules that had no check: `rehome --all` skipping CLI homes, RUNNING in
`profiles`, the `older than N days` flag, an item that is a symlink to a folder inside the home, the same-home
refusal, a target that is a Desktop profile (by name or by path), a Desktop profile's move into a CLI home, and a
changed memory file kept by rollback. Then each documented CLI-home rule was removed from a copy of the tool, one
at a time (57 removals): 56 failed at least one check. The exception is the escape refusal: on POSIX only a
symlink can lead out of a home, and the symlink refusals catch it first. `references/mechanics.md` §4b names the
check for each rule.
A second review round (a completeness pass over the repair) found five more problems in move and rollback, and
three rules that still had no check; each was fixed test first. The last section builds them on synthetic homes:
a Ctrl-C between a rename into the target and the move's note of it (rename, cross-device copy, memory file), a
real SIGTERM and SIGHUP sent to the tool mid-move, a SIGHUP ignored as under `nohup`, the caller's signal handlers
checked after a move run in-process, an item that vanishes from the target before the undo (the archive must
stay), a `--copy` rollback after the original was deleted, copied memory whose original was deleted, a FIFO in a
sidecar, in the memory, as a transcript and at a memory destination, a socket in `tasks/`, a FIFO a rollback
would hash in the target, a target `tasks/` linked outside the home, a `projects/<key>` linked to another folder
of the target, a target memory folder linked outside, a source folder linked outside before a rollback, a symlink
inside a sidecar pointing at `.credentials.json` (with `--copy`), the target's own todo file, and a transcript
that grew after a re-dating move. Against the tool before this round (with only the test-only fault switches
added), 21 of its 26 checks failed, six of them by hanging until the self-test killed the run. The other five
passed: the three older rules, the nohup rule (that tool installed no signal handler at all) and the check that no
output shows a decoy; for those the removal below is the proof. Then each rule was removed from a copy of the
tool, one at a time (25 removals): each failed the check quoted for it in §4b. With the new hash, removing the symlink-inside-an-item refusal no longer
lets a `--copy` place the link's target under its real name (the verification fails and the move is undone); the
check still fails, because the move is no longer refused up front.
The same pass found that the any-record refusal blocked the move that repairs a record shown `in cli:work` (and
the guide still advised that move), that `cli:NAME` was refused as ambiguous although only the bare `cli` can be,
that `register` departed from the spec for a profile with positive evidence of another home (both Desktop-record
rules of this round were replaced in the third round, below), and four messages
(an empty login file shown as "no login file", "nothing was changed" said twice, `unregister`'s POSIX hint on
Windows, `status` not saying it shows only the newest three archives). Each was fixed test first. The Desktop
section now also builds a session two profiles show (one reading `~/.claude`, one `cli:work`), the repair move
of an `in cli:work` record and its rollback, a move into a home the profile does not read, and rollbacks into
and out of a profile's home; the last section builds `~/.claude`, `~/.claude-work` (no login file) and
`~/.claude-empty` (an empty one) with a Desktop profile. Against the tool before this round, 31 of the new and
changed checks fail; the others guard what must stay (a move away from the home a profile reads, a move between
two homes it does not read, register in the profile's own home, the POSIX hint elsewhere, three archives shown
without a count, a missing login file still called that). Then 21 changes were made to a copy of the tool, one at
a time (each new rule removed, reversed or widened, and each guard broken): each failed at least one check.
The same pass found four problems in the documents and their evidence: two places (`docs/multiple-instances.md`,
`references/mechanics.md` §1) and `--help` still said that every window and the terminal share `~/.claude`'s
conversations; nine troubleshooting quotes were not what the tools print; the `is not a Claude Code config dir`
rows said a path prints it; and the real-CLI claim below had no recorded source. Each was fixed test first. Six
repository tests are new: five fail on the documents as they were before this round, and the sixth tests the
word-for-word matcher itself. The last self-test section's `--help` check fails on the tool before this round; its
nine other checks pin which refusal each kind of name prints (a path that does not exist, a folder that is neither
a profile nor a home, a profile name with no folder, `cli:NAME` with no folder or naming a Desktop window folder,
the home folder), as the source and as a CLI move's target. Then 5 changes to a copy of the tool (the `--help` line
put back, the `does not exist` or the config-dir message reworded, a CLI move's target or a source path taken as a
CLI home) and 14 to a copy of the documents (each old sentence or quote put back, a quote made stale, the `does not
exist` row removed, the manual test removed or made to run unasked, its AGENTS.md line, its §4b attribution, and
this entry's provenance or its mention of the manual test removed) each failed the check written for it.
A third repair round followed a final review of the second. That review found that the second round's `register`
rule brought back finding #14: for a profile whose old records' transcripts survive only in a backup home, a new
terminal conversation in `~/.claude` was refused with the advice to move it into the backup, after which
`claude --resume` no longer found it and the tool refused every way back but `--copy`. It also found that the undo
a move into a window's home printed was refused, and that `in cli:NAME` and the move rule came from different
inferences. The tool cannot see whether a window was started with `CLAUDE_CONFIG_DIR`, so the rules no longer
weigh where a profile's transcripts are: every profile is taken to read `~/.claude` (the bullets above). The same
round made the link checks see a Windows directory junction inside a session folder, in the project memory and on
a target path (`os.path.islink` does not, and Python 3.9 has no `os.path.isjunction`; the tool reads
`FILE_ATTRIBUTE_REPARSE_POINT`). The Desktop section now builds the #14 case for real (register, then the move
into the backup refused) and runs the undo a move prints; the new junction section simulates a junction on the
emulated Windows layout with a test-only switch. Against the tool before this round, 22 of the self-test's checks
fail (all new or changed in this round). Then 18 changes to a copy of the tool, one at a time (the refusal out of
`~/.claude` removed, or widened to every direction; a move between two other homes refused, or its note dropped;
the rollback's warning dropped, or made a refusal; its open-session refusal removed; register refusing a
`~/.claude` conversation by the hint, advising the hinted home, accepting a conversation there, or dropping its
note; the two display notes changed; the reparse test or its test-only switch turned off; each of the three link
checks put back to `os.path.islink`) each failed at least one check quoted for it in `references/mechanics.md`
§4b.
A fourth repair round followed a final review of the third. That review found one blocker: the new note at the end
of `sessions PROFILE`, and the `in cli:NAME` repair in the guides, advised MOVING a profile's old conversations out
of a backup home into `~/.claude`. In that layout the backup holds the only copy, older than `~/.claude`'s
`cleanupPeriodDays`; the move re-dates it, which only postpones the retention, so after a month without a new turn
`~/.claude` deletes it, and the backup no longer has it. Every piece of advice for a conversation in another home
(that note, `register`'s refusal, a rollback's warning, the guides; `status` and `rehome` only since the fifth round,
below) is now a `--copy`, and the warning on a plain
move of an old transcript says that re-dating only postpones the deletion and that the source no longer has it. The
same review found that `~/.claude` named by a second path that `realpath` does not resolve (a bind mount; on macOS
`~/.Claude` or a firmlink) skipped the refusal out of `~/.claude`, that the repair it advised named an id the text
output did not show (a move takes the CLI id; `sessions PROFILE` showed only the record id), and two older gaps: a
record's `priorCliSessionIds` were not weighed by the move rule, and the walk inside an item listed a Windows
junction's contents before refusing it. The tool now recognises `~/.claude` by identity (`os.path.samefile`),
shows the CLI id in the `in cli:NAME` flag and prints the copy by full CLI id, keeps a record's earlier
conversations in `~/.claude` like its current one, and prunes links from every walk inside an item, the project
memory and a copy in the target before it descends. The new self-test section builds a backup home with old
conversations, record ids that never share a prefix with their CLI ids (a check now scans every fixture record for
that), a second name of `~/.claude` (a symlink that the test-only `CCD_REHOME_FAULT=alias:PATH` makes `realpath`
leave unresolved, as it leaves a bind mount), a record with an earlier conversation, and junctions whose contents
the test-only switch reports if anything lists them. Against the tool before this round (with only those two
test-only switches added), 13 of the section's 18 checks fail; the other five are fixtures and guards (a `--copy`
that must still go ahead, a junction in the project memory, the fixture scan). Then 19 changes to a copy of the
tool or the self-test, one at a time (each piece of `--copy` advice put back to a move, either new sentence of the
warning dropped, `~/.claude` recognised by its name again at each of five places, the CLI id dropped from the flag
or the record id printed instead, a fixture record id given its CLI id's prefix, the earlier conversations not
weighed, and each of three walks put back to `os.walk`) were made: 18 failed at least one check. Discovery by name
first survived, because the check named the second path only on the command line (which is normalised before it
is remembered); the check now also names it in `$CCD_REHOME_CLI_HOMES`, and that change fails it. The memory walk
put back to `os.walk` fails nothing: that walk stops at the first link it sees, so it never descended into one. One
repository test is new: every documented move into `~/.claude` is a `--copy`, and the retention rows say that
re-dating only postpones the deletion; it fails on the documents as they were before this round (eight commands).
A fifth repair round followed a final review of the fourth. That review found one blocker: `status` and `rehome`
still printed a plain move of the whole home into the first other home (a signed-in one first) as the way to use
its sessions "with another account". For a backup home signed in to the same account as `~/.claude`, that drained
the backup into `~/.claude`, the loss the fourth round had removed elsewhere (its claim that every such piece of
advice was a `--copy` was not true of these two commands); for `~/.claude` it advised moving everything into the
backup. The advice is now a `--copy` into the home where another account is signed in; when every other home has
the same account it says so and advises nothing (a copy there switches no account), when an account is not known
it says so, and `status --json` gives the reason (`move_why`). The advice for a new home and the `sessions` line of
a CLI home are copies too, so every `move` command the tool prints between CLI homes is now a `--copy`. The same
review found that `--keep-dates` on a plain move of an old transcript leaves it to be deleted at the target's next
start with no copy anywhere, while the warning itself offered `--keep-dates`: that combination is now refused, and
the warning on a move names only `--copy`. For a record's earlier conversation the refusal now advises `--copy`
only (unregistering that record would also take its current conversation out of the window). And Claude Code's
documentation (https://code.claude.com/docs/en/claude-directory, "Cleaned up automatically") says that it keeps the
transcript of a session last continued in Claude Desktop or Cowork at any age unless
`desktopSessionCleanupPeriodDays` is set (Claude Code 2.1.248 and later; earlier versions, managed settings that set
`cleanupPeriodDays` and the HIPAA configuration delete it after `cleanupPeriodDays`): the warning, the re-dating and
the `older than N days` flag now read the transcript's most recent records, from its tail, and apply that rule,
with a note for what still deletes it. The new self-test section builds `~/.claude` and a backup signed in to one
account and a home of another, two homes of one account alone, a home with no account, backup transcripts last
continued in the terminal, in Desktop and the other way round, one whose tail holds no entrypoint, and records with
earlier conversations. Against the tool before this round, 19 of the section's 25 checks fail; the other six are
guards (`--copy` with `--keep-dates`, the unregister advice for a record's current conversation, a terminal
transcript that still warns, `--keep-dates` on a Desktop transcript, a transcript whose tail holds no entrypoint)
and the section's own undo check. Two older checks changed: the `--keep-dates` check now uses `--copy` (a move with
it is refused), and the shadowed-names fixture signs its second home in to another account (between homes of one
account `status` advises nothing). Then 19 changes to a copy of the tool, one at a time (the advice without
`--copy`, offered for any account, printed for one account, or calling an unknown account another; the new-home and
`sessions` lines without `--copy`; `move_why` dropped; the `--keep-dates` refusal removed, or the warning offering
`--keep-dates` again; the earlier conversation's refusal advising unregister, or naming the record whose current
conversation it is; the entrypoint ignored, `desktopSessionCleanupPeriodDays` ignored, the move or the listing
applying `cleanupPeriodDays` to every transcript, the first entrypoint taken for the last, the note dropped, the
source's settings read for the target's, and the first lines deciding when the tail holds no entrypoint) each
failed at least one check. One repository test is new: the retention rows and mechanics.md's Retention fact state
the Desktop rule (mechanics.md with the documentation's URL), no row offers `--keep-dates` on a move, and the
advice for a new home is a `--copy`; it fails on the documents as they were before this round, and 6 changes to a
copy of the documents each fail it or the refusal-row test.
A sixth repair round followed a final review of the fifth. A plain move of a transcript last continued in Desktop
and older than `cleanupPeriodDays` was no longer re-dated, and its note named neither `--copy` nor that the source
no longer had it: a Claude Code before 2.1.248 would delete it at the target's next start. Such a move now reads
`claude --version` and re-dates it unless that is 2.1.248 or later; `--keep-dates` is refused then; and every
warning on a plain move of an old transcript says the source no longer has it. The tool now also reads managed
settings (`remote-settings.json`, then `managed-settings.json`), which rank above `settings.json`; the documents
had called them invisible. It re-dates and restores the files of the sidecar folder with the transcript, and
`status` counts a window's records whose conversation is only in another home (`elsewhere`). The new self-test
section uses stand-in `claude` commands (2.1.300, 2.1.100, no version, none on `PATH`), a managed-settings file and
cache (and a FIFO in its place), a sidecar folder with a failure after the re-dating, and a window whose
conversations are in a backup. Against the tool before this round, 19 of its 25 checks fail; the other six are
guards and fixtures. Three fifth-round checks now use `--copy` or pin the version. Then 23 changes to a copy of the
tool, one at a time, each failed at least one check, and 7 changes to a copy of the documents each failed the new
repository test.
A seventh repair round followed a final review of the sixth. The sixth round took each limit from the higher of two
managed sources, but Claude Code's default `"first-wins"` ignores `managed-settings.json` once a higher source
delivers any policy key, and a `managed-settings.d/` drop-in (not read) replaces the file's value: with 7 days in the
target and 90 in the file, an old transcript was moved without a warning or re-dating. The tool now takes the
shortest limit that the target's `settings.json` (30 days when it sets none), `remote-settings.json`,
`managed-settings.json` or a drop-in sets, and names it: it may warn more often than Claude Code would delete, never
less. A `--copy` of a transcript last continued in Desktop (the one `sessions PROFILE` advises) now reads
`claude --version` as a move does and re-dates the copy, never the source; `--keep-dates` keeps the copy's dates and
says the target will delete it. Against the tool before this round, 16 of the new section's 21 checks fail; the
others are four guards and its undo check. One sixth-round check now expects the shorter of remote 40 and file 7,
and three copy checks pin the version. Then 22 changes to a copy of the tool, one at a time, each failed at least
one check, and 11 changes to a copy of the documents each failed the new repository test.
**With the real Claude Code CLI** (2026-11-08, CLI 2.1.319): a real 0.5 MB transcript was moved between two
synthetic CLI homes with this code. `claude --resume` found and loaded it in the destination home (it reached the
network; the API was pointed at a closed port, so no turn was spent) and reported "No conversation found" in the
source home. That is one measurement, the orchestrator's run on 2026-11-08 with Claude Code 2.1.319 (the agent
that coordinated this review); its log is not kept here and its OS was not recorded. `tests/e2e_real_cli.py`
repeats it on two synthetic homes with a small synthetic transcript (`move`, `claude -p --resume ID ping` in both
homes with the API at a closed port, then `rollback` and the reverse); it is manual (`SESSION_REHOME_E2E=1`), and
in this repair only its skip path ran, plus its own logic against a stand-in `claude` script that answers found or
not found the way the real CLI is expected to: the real CLI did not run here.

**Not tested:** a move on a real signed-in CLI home (no live `move-cli` entry in `tested.json` yet: dry-run first);
`tests/e2e_real_cli.py` with the real CLI (see above); Python 3.9 itself (the changed files parse with
`feature_version=(3, 9)`; CI runs 3.9); whether the troubleshooting rows' explanations are right (the tests check
that each quoted message is printed word for word, and the `is not a Claude Code config dir` row's explanation, not
the other explanations);
the cmd and PowerShell continue lines in a real cmd.exe or PowerShell (they are checked as text on an emulated
Windows layout only); the macOS Keychain; a real Desktop window started with `CLAUDE_CONFIG_DIR` set; a real EXDEV
between two mounts (only simulated by the self-test); a SIGHUP from a terminal that really closes and a real agent
timeout (the self-test sends the signals to the tool itself, on POSIX only); an interrupted cross-device copy on a
filesystem without inode numbers, where the undo cannot prove the copy is its own; the real-failure checks on macOS
(they ran on Linux only here; Windows skips them, they need POSIX); the symlink refusals on Windows, where the
self-test skips them when it cannot create a symlink; a real directory junction (the self-test simulates one on the
emulated Windows layout, and that a real Windows `os.lstat` reports `FILE_ATTRIBUTE_REPARSE_POINT` for one is from
Python's documentation); a real second name of `~/.claude` (a bind mount, a macOS firmlink, `~/.Claude` on a
case-insensitive disk: the self-test simulates one with `CCD_REHOME_FAULT=alias:PATH`); whether Desktop still
reads a record's `priorCliSessionIds` (the move rule keeps them in `~/.claude` without knowing); the retention rule
for Desktop transcripts with the real CLI (it is from Claude Code's documentation: whether the age is the file's
mtime, the entrypoint a Cowork turn writes, a Claude Code older than 2.1.248, managed settings and the HIPAA
configuration were not tried); a real `remote-settings.json`, `managed-settings.json` or `managed-settings.d/`
drop-in (the cache's shape is inferred; MDM profiles and the registry are not read, nor is the HIPAA configuration),
and how often the shortest value warns where Claude Code would keep a transcript; which
Claude Code runs a home's cleanup (Desktop bundles its own; the tool reads the terminal's `claude --version`, which
ran here only as stand-in scripts); the sweep of `tasks/` and `file-history/` (not re-dated). What the CLI-home code
assumes about Claude Code is tagged in `references/mechanics.md`
§4b: measured where it says `[M]` (session-transporter's evidence of 2026-08-01 and the
CLI run above), read from Claude Code's code where it says `[C]`, taken from Claude Code's documentation where its
`[D]` says so with the page's address (the retention rule), and otherwise derived or inferred from the spec.
