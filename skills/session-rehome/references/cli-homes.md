# CLI homes: the rules in full

Read this before a real `move cli` between CLI homes, before rolling one back, and whenever a message about a CLI
home appears. SKILL.md's "CLI homes" section is the summary; this file has every rule, refusal, warning and message
in full. `R` is the command prefix of SKILL.md ("How to run the tool"), and `P`, `ID` and the profile names are as
defined there. The evidence for each rule, and the self-test check that fails without it, is in `mechanics.md` §4b.
How these rules were reviewed and repaired, round by round, is in `cli-homes-review-log.md` (a historical record).

## What a CLI home is

The terminal CLI keeps one **config dir** per account, chosen with `CLAUDE_CONFIG_DIR` (the default is
`~/.claude`), for example `alias claude-work='CLAUDE_CONFIG_DIR=~/.claude-work claude'`. Each home has its own
settings, session history and login. **The CLI does not file sessions by account**: its picker lists the sessions
of the current project folder, whatever account is signed in, and transcripts carry no account ids. So inside one
home nothing is stranded after a sign-in change. To use sessions with another account, move or copy them to the home
where that account is signed in; two homes signed in to the same account need neither.

## How far `move cli` is tested

Say so to the user before the first real move. The self-test checks `move cli` on synthetic homes
(`references/mechanics.md` §4b lists which rules have a check, and which do not). On 2026-11-08 a real 0.5 MB
transcript was moved between two synthetic CLI homes with this code, and the real Claude Code CLI 2.1.319 found and
loaded it in the target home (`claude --resume` reached the network; no turn was spent) and reported "No
conversation found" in the source home. That is one run so far, by the 0.11.0 review's orchestrator
(`references/mechanics.md` §4b says how it is re-run). A move has not yet run on a real signed-in CLI home, and
`move cli` prints no `NOTE` about that (SKILL.md's rule 10 does not fire). So always run the dry run first
(`R move cli --only ID --to-profile cli:NAME --dry-run`) and show the plan; after the real move, have the user
resume one session with the printed `continue` line before relying on it; when it worked, run
`R report selftest move-cli` and offer to submit it.

## The rules

- **Names:** `cli` = `~/.claude`, `cli:NAME` = `~/.claude-NAME`, or any path to a Claude Code config dir. A home can
  be any folder. When `~/.claude-NAME` is no CLI home, `cli:NAME` is the one known home (found as below) whose folder
  is called `NAME` or `.claude-NAME`; two such homes are refused as **ambiguous**, with both paths (name it by its
  path). Such a home is still printed by its path. A folder
  is a CLI home when it has `projects/`, `.claude.json`, `.credentials.json` or `settings.json` and is not a
  Desktop profile (those have `config.json`). Its account comes from `.claude.json` (`oauthAccount`): the default
  home keeps it next to `~/.claude`, every other home inside itself. When a profile root holds a Desktop profile
  `cli` (`~/.claude-instances/cli`, say), `cli` is refused as **ambiguous** (that profile is named `cli` too): name
  the one meant by its path (`~/.claude`, `~/.claude-instances/cli`). The tool then prints `~/.claude` (and the
  instance called `cli`) by its path, so every command it prints runs as printed. `cli:NAME` is never ambiguous with
  a Desktop profile: one in a root's `cli-NAME` is named `cli-NAME`, another name. Never a CLI home, and refused
  with the reason: the home folder itself (it holds the default home's `.claude.json`), a folder above `~/.claude`,
  `~/.claude-instances`, a folder that holds a Desktop profile, or the tool's state folder.
- **Found by** `R profiles` (its `found_by` / `found_in` say which), `R status` and `--all`: `~/.claude`,
  `~/.claude-*` / `~/.claude_*` (never `~/.claude-instances`), the CLI homes among the subfolders of a profile root
  (`~/.claude-instances` while it exists, each root added with `R profiles --add-root DIR`, `$CCD_REHOME_INSTANCES`),
  each real `CLAUDE_CONFIG_DIR=/absolute/path` assignment in the shell startup files
  (`~/.bashrc`, `~/.bash_aliases`, `~/.bash_profile`, `~/.profile`, `~/.zshrc`, `~/.zprofile`,
  `~/.config/fish/config.fish`; not a comment, not another variable such as `OLD_CLAUDE_CONFIG_DIR`, not
  `CLAUDE_CONFIG_DIR = x`, not a relative path), the tool's own `CLAUDE_CONFIG_DIR`, `$CCD_REHOME_CLI_HOMES`, every
  home added with `R profiles --add PATH` (`--forget PATH` drops it) and every home named on the command line before.
  A home found only in a shell file is not remembered: it goes away with its line.
- **Signed-in state without secrets:** the tool checks only whether `.credentials.json` exists and is non-empty.
  An empty one holds no login and is reported as empty (signed out; on macOS `unknown`). On macOS a missing or
  empty one means `unknown`, because the login is in the Keychain and the tool does not query it. It never opens
  `.credentials.json` or `sessions/*.key`, and never prints or copies them.
- **Reports:**
  - `R profiles` shows every home with `kind` (`desktop`/`cli`), verdict, e-mail, session count, and `RUNNING` when
    a live `sessions/<pid>.json` entry names a process that is alive;
  - `R status cli:work` says who it is signed in as (and the org), how many sessions it has, how many are live, the
    exact copy (`move … --copy`) into the home where another account is signed in (a signed-in one first), and the
    home's `cli-move` archives (the newest three, newest last; with more it says how many there are in all and that
    `--json` lists them; `archives` in JSON: every archive whose move had this home as source or target). Desktop
    rows list their archives the same way. The advice is always a `--copy`: a move of the whole home would leave it
    without every conversation it holds, and a backup home's old ones would then depend on the target's retention
    alone. When every other home has the same account it says so and prints no command (copying there switches no
    account; JSON `move` is null, `move_why` `same-account`); when a home's account is not known it says so and
    still prints the copy (`account-unknown`). When there is no other CLI home it prints no move command (JSON
    `move` is null, `move_why` `no-other-home`) but how to make one: start `CLAUDE_CONFIG_DIR=~/.claude-NAME claude`
    once and sign in there (on Windows it gives the cmd and PowerShell forms), then the copy into it. Its `--json`
    row has every key a Desktop row has, with neutral values (`stranded` `{}`, `elsewhere` `{}`, `cowork_stranded`
    0, `visible` `[]`, `active_dir`, `blocker`, `cookie_expires`, `last_account_email` null), plus `org`, `org_name`,
    `sessions`, `live`, `move` and `move_why` (`another-account`, `account-unknown`, `same-account` or
    `no-other-home`);
  - `R sessions cli` lists each transcript (newest first) with its folder, title, `OPEN`, `desktop: PROFILE`, and
    `older than N days` when that home's cleanup would delete it (see "Warns" for which limit applies: a transcript
    last continued in Claude Desktop has none unless `desktopSessionCleanupPeriodDays` is set; JSON
    `last_entrypoint` is what its most recent records say). A transcript reached under a second project folder
    through a symlink (a renamed repo's alias) is one session, listed by its real folder.
- **Moving:** `R move cli --only ID --to-profile cli:work` (or `--project DIR` instead of `--only`; both are
  optional). Per session it moves the transcript `projects/<key>/<id>.jsonl` byte for byte, the sidecar folder
  `projects/<key>/<id>/`, sibling-key sidecar folders (git worktrees), `tasks/<id>/`, `todos/<id>*.json` and
  `file-history/<id>/`. It **copies, never moves**, the project memory `projects/<key>/memory/` (other sessions of
  that project still use it): a file missing in the target is copied, an identical one is skipped, a different one
  is kept and reported as a conflict; `--no-memory` skips it. It never touches `session-env/`, `sessions/`,
  `history.jsonl`, `.credentials.json`, `.claude.json`, `settings.json`, `plans/`, `shell-snapshots/` or `debug/`.
- **Verified move:** same filesystem: atomic `rename` (when that fails with EXDEV, as between two mounts of one
  filesystem, the item is copied instead); otherwise copy to a temporary name in the target folder, check size and
  sha256 of every file, and only then give the copy its real name and remove the source. A partial copy is removed
  and never carries the real name. `--copy` keeps the source (the two copies diverge if both are used).
- **All or nothing:** the archive name is printed before the first change. When any step fails (a permission, a
  full disk, Ctrl-C, a SIGTERM such as an agent's command timeout, a SIGHUP from a closed terminal), the steps
  already started are undone newest first, each decided from what is on disk (an item the run had just renamed
  into the target, before it could note that, goes back too), and the tool exits 1 with "It was undone: nothing
  was changed". It says that, and removes the archive, only after checking that every item is back in the source
  as the move found it (size and sha256) and nothing it placed is left in the target. A SIGTERM or SIGHUP the
  caller ignores (`nohup`) stays ignored. When the undo cannot finish or cannot confirm that, or the run was killed
  outright (`kill -9`, a power cut), the archive is kept and `R rollback P ARCHIVE` finishes the job (relay the
  message; do not move files by hand).
- **Refuses** (nothing written; the refusal ends "Nothing was changed." once): the target is not a CLI home or is
  the same home; the session is `OPEN`; the move would take the session **out of `~/.claude`** while ANY Desktop
  profile has a record whose `cliSessionId`, or one of whose `priorCliSessionIds` (its earlier conversations), is
  that session (unregister it first, `R unregister P --only RECORD_ID`, or use `--copy`; for an earlier conversation
  only `--copy`, since unregistering that record would also take its current conversation out of the window); a move
  (not `--copy`) with `--keep-dates` of a transcript the target's cleanup would delete (see "Warns"; for one last
  continued in Desktop, when `claude --version` is older than 2.1.248 or not known): it would be deleted at the
  target's next start, and nothing else would have it. `~/.claude` is recognised by identity (the
  same folder), so a second name for it (a bind mount, `~/.Claude` on a case-insensitive disk) is still `~/.claude`.
  Every Desktop profile is taken to read `~/.claude` (see "Which home a Desktop window reads" below). A move
  **into** `~/.claude` is always allowed: it gives a window that lists the session its conversation back. For a
  record `sessions` shows as `in cli:NAME, CLI id …`, advise a COPY, by the CLI id, not the record id:
  `R move cli:NAME --only CLI_ID --to-profile cli --copy` (`R sessions P` prints that line with the full ids). A
  plain move would leave cli:NAME without it, and cli:NAME is often a backup home that kept an old conversation
  `~/.claude`'s retention deleted: re-dated, it is deleted from `~/.claude` again after `cleanupPeriodDays` without
  a new turn (one last continued in Desktop by a Claude Code before 2.1.248, by `desktopSessionCleanupPeriodDays`
  or by a managed `cleanupPeriodDays`), and then no home has it. A move between two other homes goes ahead; when a
  profile lists the session, a note says that Desktop looks for its conversations in `~/.claude` (or in the folder
  its own `CLAUDE_CONFIG_DIR` names, if it was started with one). The target already has a **different** transcript
  with that id; the id has a transcript in two project folders of the source (`claude --resume` cannot pick one; the
  user keeps one, then re-run); an item, or a folder above it inside the home, is a symlink, or it escapes the home,
  or anything inside an item is a symlink (a `--copy` never follows it); the project memory folder, a folder above
  it, or anything in it is a symlink (it is never followed or read; `--no-memory` moves the session without it); a
  FIFO, socket or device file anywhere in an item or the project memory (never opened, never hashed, never copied);
  the target already has one of the session's items, such as its own `todos/<id>-agent-*.json` (never overwritten); a
  path the move would write in the target resolves outside it, or has a symlink at or above it inside the target
  (even one leading back inside), or is a FIFO, socket or device file. On Windows a directory junction (any reparse
  point) counts as a symlink in each of these checks, and the message says `is a symlink`. An **identical**
  transcript in the target is "already there" and skipped without error.
- **Dry run:** prints the whole plan, including every `REFUSE` line. When there is one, it ends "The real run
  would REFUSE: …" and exits 1, as the real run would; relay the refusal instead of running the move.
- **Warns:** the transcript is older than the target's `cleanupPeriodDays` (default 30), so the target would delete it
  at its next start: its mtime is set to now, with the files of its sidecar folder (`subagents/`, `tool-results/`,
  `mcp-tasks/`, `workflows/`; with `--copy`, `--keep-dates` keeps the old dates), which only POSTPONES the deletion
  (the target deletes it again after that many days without new activity there; opening it in Desktop without a new
  turn does not count). On a move (not `--copy`) the warning also says that the source no longer has it (the archive
  holds no copy) and names `--copy`, never `--keep-dates`: for an old conversation from a backup home, use `--copy`.
  The tool reads `cleanupPeriodDays` and `desktopSessionCleanupPeriodDays` from the target's `settings.json`, the
  server-managed settings cached in its `remote-settings.json`, `managed-settings.json` (`/etc/claude-code/` on Linux,
  `/Library/Application Support/ClaudeCode/` on macOS, `C:\Program Files\ClaudeCode\` on Windows) and every
  `managed-settings.d/*.json` drop-in next to it, and takes the SHORTEST value any of them sets (30 when none sets
  `cleanupPeriodDays`), on purpose: it does not model which one Claude Code applies, so it may warn where Claude Code
  would keep a transcript, never the other way round. The warning names the source of that value
  (`cleanupPeriodDays in the managed settings …`); MDM profiles and the registry are not read. Which limit applies is
  read from the transcript's most recent records (from its tail, never the whole file): one last continued in Claude
  Desktop (`entrypoint` `claude-desktop`) is kept at any age by Claude Code 2.1.248 and later, unless
  `desktopSessionCleanupPeriodDays` is set (then the warning names that limit) or managed settings set
  `cleanupPeriodDays` (then that applies to it). Claude Code before 2.1.248 deletes it after `cleanupPeriodDays` like
  any other, so for a move or a `--copy` of one older than `cleanupPeriodDays` the tool reads `claude --version`:
  2.1.248 or later, it is not re-dated and the warning says so ("`claude --version` here is X, so it is not re-dated";
  on a `--copy` a note says so, and that Claude Code before 2.1.248 and any version under the HIPAA configuration,
  which the tool cannot read, delete it after `cleanupPeriodDays`); older, or not known (no `claude` on PATH, or no
  version printed), it is re-dated like a terminal transcript and the warning says which version it saw. On a move
  that warning says the source no longer has it: relay it, and use `--copy` for an old conversation. A `--copy` is
  re-dated in the target only, the copy and its sidecar files, never the source
  (`… would delete the copy at its next start; the copy's mtime is set to now …`); with `--keep-dates` the copy keeps
  its dates and the warning says the target would delete the copy (the source keeps its own). A rollback of a `--copy`
  removes a re-dated copy too (it compares content, not mtimes). Also warned: the two homes are signed in to different
  organizations (continuing under the other may have its signed thinking rejected; unverified); the target is signed
  out (no login file, or an empty one: the warning says which). On macOS a target without a login file is `unknown`,
  because the login is in the Keychain: the tool prints a note saying it cannot tell, not a warning.
- **After a move** it prints, per session, the command that continues it from its folder:
  `cd DIR && CLAUDE_CONFIG_DIR=<target> claude --resume ID` (no variable for `~/.claude`). On Windows, where
  neither cmd nor PowerShell takes a `VAR=value command` prefix, it prints a cmd line
  (`cd /d "DIR" && set "CLAUDE_CONFIG_DIR=…" && claude --resume ID`) and a PowerShell line
  (`Set-Location -LiteralPath 'DIR'; $env:CLAUDE_CONFIG_DIR='…'; claude --resume ID`); the variable then stays set
  in that window. `R resume-cli` prints the same forms.
- **Undo:** every move writes a `<timestamp>-cli-move` archive with every source/destination path (size, sha256,
  mtime) and the memory files copied. `R rollback cli:work ARCHIVE` (or `R rollback cli ARCHIVE`):
  - moves back what is in the target, including what the session gained there after the move (sidecars, tasks,
    file history, todos), and skips what is still in the source (a move cut off part-way); an item in BOTH homes
    refuses;
  - refuses, like a move, while the session is open in the target (a live registry entry, or another process
    holding the transcript). A Desktop record never refuses a rollback, because it restores the exact state before
    the move (the undo the move printed always works): when it takes the session back out of `~/.claude` (or, for a
    `--copy`, removes the copy there) while a Desktop profile lists it, it prints a `warning:` with the copy
    (`--copy`) that gives the window its conversation back; relay it to the user;
  - moves a transcript that grew as it is now (keeping its current mtime), and gives an unchanged one its original
    mtime back (a move may have re-dated it);
  - refuses when a folder of the source it would move back into is now a symlink or leads outside the source;
  - for `--copy`, treats each session as one unit: its copies go only if none of them changed or was added to,
    and only while every original is still in the source; otherwise all of them are kept, and it says so (a copy
    whose original was deleted since may be the only one left);
  - removes copied memory files that are unchanged, unless a session of that project that came to the target
    after the move still lives there (the file is kept and the session named), or the original file in the source
    was deleted since (kept: it may be the only one left);
  - when it stops part-way, running it again finishes it.
- **Which home a Desktop window reads:** Desktop reads `CLAUDE_CONFIG_DIR` if it was started with it, else
  `~/.claude`, and nothing on disk says which. So every rule (move, rollback, register) takes each Desktop profile
  to read `~/.claude`. Where a profile's records' transcripts happen to be is a display hint only (the
  `desktop:` flag of `R sessions cli:NAME`, and notes), never a rule: a backup copy of `~/.claude` (old transcripts
  that retention has since deleted from `~/.claude`) would fool it. When none of a profile's records' transcripts
  is in `~/.claude` and most are in another home, `R sessions PROFILE` ends with a note that says so. If the user
  says a window was started with `CLAUDE_CONFIG_DIR`, the rules here do not fit that window: ask before moving its
  conversations.
- **Desktop windows follow their records:** `R sessions PROFILE` shows `in cli:NAME, CLI id XXXXXXXX` when a
  record's transcript lives in another home (not in `~/.claude`) instead of `transcript MISSING`, and ends with the
  exact copy into `~/.claude` (`R move cli:NAME --only <full CLI ids> --to-profile cli --copy`) for each such home.
  `R status PROFILE` counts them too: `N of these records' conversations are only in cli:NAME, not in ~/.claude`,
  with `R sessions PROFILE` for the copy (JSON `elsewhere`, such as `{"cli:backup": 3}`; `{}` when there are
  none, and on every CLI row). So `status --json` alone shows a window whose conversations it cannot open: when
  `elsewhere` is not empty, run `R sessions PROFILE` and offer the copy it prints. `R cli-sessions` lists every known
  home (and notes that Desktop reads a non-default home only when started with `CLAUDE_CONFIG_DIR` set to it);
  `R register` always accepts a conversation in `~/.claude` (with a note when the profile's other records'
  transcripts are mostly elsewhere), and refuses one in any other home, printing the copy INTO `~/.claude`
  (`R move cli:NAME --to-profile cli --only ID --copy`, then run the register again); `R resume-cli` and `R unregister`'s
  hint name `CLAUDE_CONFIG_DIR=` the home that holds that conversation's transcript (on Windows in cmd and
  PowerShell syntax), with a note when that is not `~/.claude`.
- **`R rehome cli`** does nothing and explains the rule above, with the move command (or, when there is no other
  CLI home, how to make one); `R rehome --all` skips CLI homes silently.

## Troubleshooting (CLI-home messages and what to do)

Every message the CLI-home code can print has a row here (the project's tests check that, and that each quoted
message is printed word for word). The messages of Desktop windows are in SKILL.md's table.

| Message | Meaning | Action |
|---|---|---|
| `is OPEN in …` (CLI move or rollback) | a live `sessions/<pid>.json` entry names the session | close that terminal session, then re-run |
| `… is open in another process` (CLI move or rollback) | a process holds the transcript open (a terminal `claude`, a Desktop window) | the user closes it there, then re-run; nothing was changed |
| `is shown by Desktop profile …, and Desktop looks for its conversations in …: moving it out of … would leave that window without it; unregister it first` / `… (record … names it among its earlier conversations), and Desktop looks for its conversations in …: … would leave that window without it; use --copy` | a Desktop record (in ANY profile) points at this conversation, which is in `~/.claude` (as its `cliSessionId`, or among its earlier `priorCliSessionIds`: the message then names the record); every profile is taken to read `~/.claude`, so moving it out would leave that window without it. `~/.claude` by another name (a bind mount, `~/.Claude` on a case-insensitive disk) is still `~/.claude`. A move INTO `~/.claude` is always allowed; a move between two other homes goes ahead with a note | for the record's own conversation `R unregister PROFILE --only RECORD_ID`, or use `--copy`; for an earlier conversation only `--copy` (unregistering that record would also take its current conversation out of the window); nothing was changed |
| `already has a DIFFERENT transcript` | the target home has another conversation with the same id | pick the right home, or remove the other copy yourself; nothing was changed |
| `already there in …; skipped` | the target already has a byte-identical transcript | no error: that session was skipped |
| `already has …, which a move never overwrites` (CLI move) | the target has one of the session's side files (sidecar, `tasks/<id>`, `file-history/<id>`, a todo) but not its transcript | show the user that path; they keep or remove it, then re-run |
| `… escapes … (it resolves outside that home)` (CLI move) | a session file or the project memory resolves outside the home (a last check: the link checks, which see symlinks and on Windows junctions, normally refuse first) | as for a symlink: the user replaces the link; `--no-memory` for the memory. Nothing was changed |
| `is … (not a regular file or folder)` (CLI move: a FIFO, socket or device file) | a session's folder, its project memory, or the target's place for a file holds a named pipe, socket or device file; it is never opened or copied | the user moves that file away, then re-run; `--no-memory` for the memory. Nothing was changed |
| `… resolves to …, outside …` (CLI move or rollback) | a folder of the home being written to (a move's target, a rollback's source) leads outside it | the user replaces the link with a real folder, then re-run. Nothing was changed |
| `… in … is a symlink` (CLI move or rollback) | a folder or file of the home being written to is a symlink (on Windows also a directory junction or another reparse point), even one leading back inside it | the user replaces the link with a real folder, then re-run. Nothing was changed |
| `the move stopped while … It was undone: nothing was changed` | a step failed (permission, full disk, Ctrl-C, SIGTERM, SIGHUP) and every started step was put back, checked on disk | fix the cause the message names, then re-run the move |
| `undoing it did not finish … The archive … is kept` | the failed move could not put everything back, or could not confirm it (`NOT undone` lines) | fix the cause, then run the printed `R rollback P ARCHIVE`; never move files by hand |
| `kept the copy of …: its original … is no longer in …` / `kept copied memory …: its original …` (rollback) | not an error: the original was deleted after the move, so the copy may be the only one left | tell the user it was kept; they delete it only once sure |
| `is in both … and …` (rollback) | an item of the session is in both homes | the user compares them and moves one away; then roll back again |
| `rollback stopped while …` | a rollback step failed | fix the cause, then run the same rollback again: it finishes |
| `this rollback takes it back to …, so that window cannot open it` / `this rollback removes the copy there, so that window cannot open it` (rollback, after `warning: … is shown by Desktop profile …`) | not a refusal: the rollback restored the state before the move, which takes the session out of `~/.claude` (or removes its copy there) while a Desktop profile lists it | tell the user; the warning prints the copy that gives the window its conversation back (`R move cli:NAME --only ID --to-profile cli --copy`; cli:NAME keeps its own) |
| `not an archive name` / `no cli-move archive named …` / `no complete archive at …` (rollback) | not an archive of a move from or into this home (an incomplete one was cut off before the move changed anything) | `R status cli:NAME` shows the newest three and how many there are; `R status cli:NAME --json` lists them all; every move prints its own |
| `archive name … is ambiguous` (rollback) | two CLI-move archives of that name involve this home | roll back from the move's other home (`R rollback cli ARCHIVE` instead of `cli:NAME`, or the reverse) |
| `has a transcript in N project folders of …` | the same session id is filed under two project folders of the source home, so `claude --resume` cannot pick one | the user compares them and moves all but one out of that home; then re-run. Nothing was changed |
| `is reached through the symlink …` / `is a symlink` (CLI move) | an item, anything inside an item, the project memory (or anything in it), or a folder above them is a symlink (on Windows also a directory junction or another reparse point); the tool never follows one | the user replaces the link with what it points to; for the memory, `--no-memory` moves the session without it. Nothing was changed |
| `dry run complete … The real run would REFUSE: …` (exit 1) | the dry run found a refusal | relay the `REFUSE` line(s); the real run would change nothing |
| `older than N days (cleanupPeriodDays …)` / `older than N days (desktopSessionCleanupPeriodDays …)` / `… was last continued in Claude Desktop: Claude Code 2.1.248 and later keep such a transcript …, so it is not re-dated` / `…, and --keep-dates keeps that date: … would delete it at its next start` (refused) / `… would delete the copy at its next start` (`--copy`) | the target home would delete it at its next start, by the shortest `cleanupPeriodDays` or `desktopSessionCleanupPeriodDays` that its `settings.json`, managed settings or the server-managed settings set (the message then names `the managed settings …managed-settings.json`, a drop-in `…managed-settings.d/NAME.json`, or `the server-managed settings …remote-settings.json`); the tool takes the shortest on purpose, as it does not model which one Claude Code applies. A conversation last continued in Claude Desktop is kept at any age by Claude Code 2.1.248 and later unless `desktopSessionCleanupPeriodDays` or a managed `cleanupPeriodDays` is set; an earlier Claude Code deletes it after `cleanupPeriodDays`, so on a move or a `--copy` the tool reads `claude --version` and re-dates it unless that is 2.1.248 or later (the warning says which; on a `--copy` of a version 2.1.248 or later a note says so instead) | the tool re-dates it, with the files of its sidecar folder, which only postpones the deletion: the target deletes it again after N days without new activity there. On a `--copy` it re-dates the copy, never the source; with `--keep-dates` the copy keeps its dates and the target will delete it (the source keeps its own). On a move (not `--copy`) every one of these warnings says the source no longer has it, even when it is not re-dated; for an old conversation from a backup home, stop and use `--copy` so the backup keeps it. `--keep-dates` on a move (not `--copy`) of such a transcript is refused (for one last continued in Desktop, when `claude --version` is older than 2.1.248 or not known): relay it, and use `--copy` |
| `different organizations … unverified` | the two homes are signed in to different orgs | continuing may have signed thinking rejected; sign the target in to the same org to be safe |
| `is not a Claude Code config dir (no projects/, .claude.json, .credentials.json or settings.json), or it is a Desktop profile` | `cli:NAME` names a folder `~/.claude-NAME` that does not exist, has no `projects/` / `.claude.json` / `.credentials.json` / `settings.json`, or is a Desktop profile (has `config.json`). A path prints other messages: `… does not exist` or `not a Desktop profile (no config.json)` as what a command works on, `--to-profile '…' is not a CLI home` as a CLI move's target, `is your home folder …` for HOME | check `R profiles`; a new home exists once the user started `CLAUDE_CONFIG_DIR=~/.claude-NAME claude` in it and signed in |
| `is your home folder …` / `is a folder above …` / `holds the Desktop profile …` / `is or holds ~/.claude-instances, where the Desktop profiles live`, each followed by `: it is not a Claude Code config dir. Name the config dir itself` | that folder can never be a CLI home | name the config dir itself: `cli`, `cli:NAME` or its path |
| `--to-profile '…' is not a CLI home` (CLI move) | the target is a Desktop profile (by name or path) or no config dir | a conversation moves only between CLI homes (`R profiles` lists them); to show it in a Desktop window, `R register P --cli-session-id ID` |
| `--to-profile is a CLI home` (a Desktop profile's `move`) | records move only between Desktop profiles | to continue it in a terminal, `R resume-cli P --only ID`; to move the conversation to another home, `R unregister P --only RECORD_ID`, then `R move cli --only CLI_ID --to-profile cli:NAME` (the record's `cli` in `R sessions P --json`) |
| `--to-profile names the same CLI home` / `moving sessions out of … needs --to-profile P2` | no target, or the source itself | name the other home: `--to-profile cli:NAME` |
| `--only … matches N sessions in …` / `--project … matches no session in …` (CLI move) | the prefix or folder fits no session, or several | `R sessions cli:NAME` (ids and folders); use a longer prefix |
| `bad CLI home name` | `cli:NAME` with `/`, `\` or `:` in NAME | give the home's path instead |
| `… works on a Desktop profile; … is a CLI home` | `quit`, `launch`, `verify`, `register`, `resume-cli`, `unregister`, `export-record`, `adopt` take a Desktop profile | for a CLI home use `profiles`, `status`, `sessions`, `rehome`, `move`, `rollback` |
| `is not on this machine (no ….jsonl in any known CLI home)` (`resume-cli`) | the record's transcript is in no known home: made on another machine, or in a home never named | if the user knows the home, `R status PATH` once (it is then remembered) and re-run; from another machine: session-transporter |
| `that conversation lives in …, but Desktop looks for its conversations in …` | `register` files only a conversation in `~/.claude`: every profile is taken to read it (a conversation there is always accepted, with a note when the profile's other records' transcripts are mostly elsewhere) | run the printed `R move … --to-profile cli --only ID --copy` (a copy into `~/.claude`; the other home keeps its own), then run the register again |
| `` `cli` is ambiguous here `` | a Desktop profile `cli` in a profile root (`~/.claude-instances/cli`) is named `cli` too | name the one meant by the path the message prints (`~/.claude`, `~/.claude-instances/cli`); `cli:NAME` is never ambiguous with a Desktop profile |
| `` `cli:NAME` is ambiguous: N CLI homes have the folder name … `` | there is no `~/.claude-NAME`, and two known homes are called `NAME` or `.claude-NAME` | name the one meant by its path (the message lists both) |
| `is a CLI home (a Claude Code config dir), not a Desktop profile` | a bare name (a Desktop profile name) fits a CLI home in a profile root | name it by its path, or as `cli:NAME` |
| `is the tool's state folder … (or inside it)` | the tool's own state folder (`R profiles` prints it) is never a CLI home or a Desktop profile | name the config dir itself |

## Test-only switches

`CCD_REHOME_FAULT` injects failures into a CLI move or rollback, and `CCD_REHOME_OPEN_FILES` names files that
another process "holds open". Both are for the self-test only, and the tool honours them only with
`CCD_REHOME_SANDBOX=1`. `CCD_REHOME_FAULT` is a comma-separated list of `exdev`, `short-copy:N`, `fail-after:N`,
`kill-after:N`, `kill-in-copy:N`, `appear:N`, `int-after-place:N`, `term-after:N`, `hup-after:N`, `vanish:N`,
`reparse:PATH` and `alias:PATH`; the tool's `_faults()` says what each one does.
