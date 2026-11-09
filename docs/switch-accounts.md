# Switching accounts, and moving sessions on one machine

After you sign a Desktop window in to a different account, its Code tab is empty. Nothing was deleted: Desktop
files each session under the account that created it and only shows the signed-in account's sessions
([how-it-works.md](how-it-works.md)). `ccd-rehome` moves them to where Desktop looks.

In the commands below, `work` is the name of a Desktop window: `default` for the plain one, the folder name of an
instance (in `~/.claude-instances/`, in a folder you registered with `ccd-rehome profiles --add-root`, or any instance
the tool knows; a name two folders share is refused), or the full path of any user-data-dir. Your instances can live
in any folder: [multiple-instances.md](multiple-instances.md#your-own-folders) says how the tool finds them.

## Change the account of a window

1. In that window, sign out of the old account and in to the new one, then **quit it** (File > Quit).
2. See what is where:

   ```bash
   ccd-rehome status
   ```

   For every window it shows who it is signed in as, whether it is running, what Desktop shows, and what is
   **STRANDED** under other accounts, with the exact command that fixes it.

3. Preview, then run, the fix it printed:

   ```bash
   ccd-rehome rehome work --dry-run
   ```

   ```bash
   ccd-rehome rehome work
   ```

   Or fix every window at once with `ccd-rehome rehome --all`.

4. Start the window and confirm:

   ```bash
   ccd-rehome launch work
   ```

   ```bash
   ccd-rehome verify work
   ```

   `OK` means Desktop's own log says it loaded every session.

If it says *"no org known"*, open the Code tab once while signed in, quit, and run it again.

**Before it moves anything, the tool checks every file involved** against the formats it knows:
- `ERROR`: a format changed. It refuses.
- `DRIFT`: a newer Desktop stores something new. A real run refuses until you have looked: `--dry-run` shows what
  is new, and `--accept-drift` proceeds.
- `NOTE`: your Desktop version or OS is not in `tested.json` yet. Nothing is wrong, but start with `--dry-run`.

A dry run never writes anything, and it works while the window is open. A real move needs the window quit.

## See and move individual sessions

```bash
ccd-rehome sessions work
```

For every session: its id, whether Desktop shows it now, the account (e-mail) it is filed under, last activity,
size and title. It also flags archived sessions, queued background work, and conversations whose file is not on
this machine.

```bash
ccd-rehome move work --only 1a2b3c4d 5e6f7a8b
```

```bash
ccd-rehome move work --to someone@example.com --only 1a2b3c4d
```

```bash
ccd-rehome move work --from old@example.com
```

- **`--only`** takes id prefixes from `sessions`.
- **`--to`** defaults to the signed-in account. It can also name an account that is not signed in (any account a
  window or the terminal CLI has used on this machine); Desktop shows those sessions once you sign in to it.
- **`--from`** limits the move to sessions filed under that account.
- **`--include-cowork`** also moves Cowork sessions (refused while Cowork spaces or agents hold data; see
  [troubleshooting.md](troubleshooting.md)).
- **`--json`** gives machine-readable output on `profiles`, `status`, `sessions` and `accounts`.

## Move a session to another window on this machine

```bash
ccd-rehome move work --only 1a2b3c4d --to-profile personal --dry-run
```

```bash
ccd-rehome move work --only 1a2b3c4d --to-profile personal
```

Quit both windows first. The session is filed under the other window's signed-in account (or `--to`), keeps its
settings, and takes its task suggestions along. Undo it with `rollback` in each window.

## Terminal (CLI) accounts

The terminal `claude` command keeps a **config dir** per account, chosen with `CLAUDE_CONFIG_DIR` (the default is
`~/.claude`):

```bash
alias claude-work='CLAUDE_CONFIG_DIR=~/.claude-work claude'
```

Each home has its own settings, session history and login. Unlike Desktop, the CLI does **not** file sessions by
account: it lists the current project folder's sessions whatever account is signed in. So inside one home nothing is
lost after a sign-in change. To use sessions with another account, move or copy them to the home where that account
is signed in; `ccd-rehome status` prints the copy (it always advises `--copy`, and none between two homes of the
same account, which need no move). `cli` means `~/.claude`, `cli:work` means `~/.claude-work` (or, when there is
none, the one known home whose folder is called `work` or `.claude-work`), and any path to a Claude Code config dir
works too. If you also have a Desktop window folder called `cli` in a profile root (`~/.claude-instances/cli`), the
name `cli` fits both and is refused: use the path (`~/.claude`, `~/.claude-instances/cli`) instead. (`cli:work` is
never ambiguous with a window: a window folder `cli-work` is named `cli-work`.)

**How far this is tested.** The self-test checks these moves on synthetic homes, and on 2026-11-08 the real Claude
Code CLI (2.1.319) found and loaded a transcript that this code had moved between two synthetic homes, and no longer
found it in the home it came from (one run so far; `tests/e2e_real_cli.py` repeats it). A move has not yet run on
a real signed-in CLI home. So always do the `--dry-run` first and read the plan, and after the move resume one
session in the target home (the printed `continue` line) before you rely on it. If it worked for you, please say so:
`ccd-rehome report selftest move-cli` prints an entry you can submit ([CONTRIBUTING.md](../CONTRIBUTING.md)).

```bash
ccd-rehome profiles
```

```bash
ccd-rehome status cli:work
```

```bash
ccd-rehome sessions cli
```

```bash
ccd-rehome move cli --only 1a2b3c4d --to-profile cli:work --dry-run
```

```bash
ccd-rehome move cli --only 1a2b3c4d --to-profile cli:work
```

The transcript moves byte for byte with its sidecar folder, tasks, todos and file history; the project memory is
**copied** (other sessions of that project still use it; a different file already in the target is kept and
reported). Add `--project DIR` to move every session of one folder, `--copy` to keep the source, or `--no-memory` to
skip memory. A transcript older than the target's retention is re-dated, with the files of its sidecar folder,
which only postpones it (`cleanupPeriodDays`): without a new turn there, the target deletes the transcript again
after that many days, and after a move (not `--copy`) the source no longer has it. The warning says so; for an old
conversation from a backup home, use `--copy`. On a `--copy` the copy is re-dated, never the source; with `--copy`,
`--keep-dates` keeps the copy's old mtime instead, and the warning says the target would delete the copy at its next
start (the source keeps its own); on a move (not `--copy`) it is refused for such a transcript, which the target
would delete at its next start. The limit is the shortest one set in the target's `settings.json`, in the
server-managed settings cached in its `remote-settings.json`, in `managed-settings.json` (`/etc/claude-code/` on
Linux, `/Library/Application Support/ClaudeCode/` on macOS, `C:\Program Files\ClaudeCode\` on Windows) or in a
drop-in file of the `managed-settings.d/` folder next to it, and the warning names where. The tool takes the
shortest on purpose: it does not model how Claude Code combines these sources, so it may warn about a transcript
Claude Code would keep, never the other way round. A conversation last continued in Claude Desktop is kept at any age
by Claude Code 2.1.248 and later unless `desktopSessionCleanupPeriodDays` (or a managed `cleanupPeriodDays`) is set;
an earlier Claude Code deletes it after `cleanupPeriodDays`. So a move or a `--copy` of one older than that reads
`claude --version`: with 2.1.248 or later it is not re-dated, and with an older version, or none it can read, it is
re-dated (on a `--copy`, the copy); the warning says which, and after a move that the source no longer has it.

It refuses while the session is open, and while a Desktop window has it in its list and the move would take it out
of `~/.claude` (unregister it first, or use `--copy`; for a record's earlier conversation only `--copy`). Desktop
looks for its conversations in `~/.claude` unless the window was started with `CLAUDE_CONFIG_DIR`, and the tool
cannot see that, so it takes every window to read `~/.claude`: a move INTO `~/.claude` is always allowed (a session
marked `in cli:work` gets its conversation back with the `--copy` that `ccd-rehome sessions PROFILE` prints), and a
move between two other homes goes ahead with a note saying where Desktop looks. It also refuses when the target
already has a different transcript with that id, when the id is filed under two project folders of the source (keep
one first), when a session file, the project memory, a folder above them or anything inside them is a symlink (on
Windows also a directory junction; it never follows one; `--no-memory` moves a session without its memory), when
they hold a named pipe, a socket or a device file (never opened or copied), when the target already has one of the
session's files (it never overwrites one), and when a folder of the target it would write into is a link (to
anywhere). An identical transcript is reported as already there. A dry run shows those refusals too: it then says
the real run would refuse, and exits 1.

```bash
ccd-rehome rollback cli:work 20261108T120000Z-cli-move
```

A move is all or nothing: if a step fails (a permission, a full disk, Ctrl-C, a `kill`, or the terminal closing),
it puts back what it had moved, checks that each item is back as it was, and only then says "nothing was changed"
(if it cannot confirm that, it keeps the archive and names the rollback). Its archive name is printed before the
first change, so if the run is cut off outright (the machine went down), `rollback` with that name finishes the
job. Rollback brings back everything of the session that
is in the target now, files the session added there included, gives an unchanged transcript its old date back, and
removes the memory files it copied unless another session of that project now uses them there. It refuses while the
session is open there, and when a folder it would move back into has become a link. A Desktop window never stops a
rollback, since it only puts back the state from before the move (so the undo a move prints always works): when
it takes a session back out of `~/.claude` (or removes a copy there) while a window lists that session, it warns
and prints the copy that gives the window its conversation back.
For a `--copy` move it removes a session's copies only when none of them changed and every original is still in
the source. A copy, or a copied memory file, whose original was deleted since is kept: it may be the only one
left.

After the move it prints, for each session, the command that continues it in the terminal from its folder:
`CLAUDE_CONFIG_DIR=<target> claude --resume ID` (just `claude --resume ID` for `~/.claude`). On Windows it prints
that once for cmd (`set "CLAUDE_CONFIG_DIR=…" && claude --resume ID`) and once for PowerShell
(`$env:CLAUDE_CONFIG_DIR='…'; claude --resume ID`), because neither accepts the `VAR=value command` form; the
variable then stays set in that window. It warns when the target is signed out (no login file, or an empty one).
On a Mac the login is in the Keychain, which the tool never reads, so there it only notes that it cannot tell.

`ccd-rehome status cli:work` lists that home's newest three move archives (newest last) and says how many there
are; `ccd-rehome status cli:work --json` lists them all, so you can find a name again. If you
have only `~/.claude`, `status` and `rehome cli` say so and tell you how to make a second home instead of printing a
move that cannot work: start Claude Code once with it and sign in there with the other account:

```bash
CLAUDE_CONFIG_DIR=~/.claude-work claude
```

`ccd-rehome rehome cli` does nothing and explains why; `ccd-rehome rehome --all` skips CLI homes.

## Undo

```bash
ccd-rehome rollback work 20261107T120000Z-move
```

Every move prints its archive name and this command, and `ccd-rehome status work` lists them. The window must be
quit. Rollback restores the exact earlier state and keeps a safety copy of what it replaced. Archives live in the
tool's state folder, in `archive/` (moves between CLI homes: `cli-archive/`), a few KB each; old ones are safe to
delete. The state folder is `~/.local/state/session-rehome` on Linux (`$XDG_STATE_HOME/session-rehome` if that is
set), `~/Library/Application Support/session-rehome` on macOS, `%LOCALAPPDATA%\session-rehome` on Windows; an
existing `~/.claude-instances/_rehome` (made by an earlier version) keeps being used, so its archives still roll
back. `ccd-rehome profiles` prints the one in use.

## What moves, and what never does

**Carried over:**
- the session and its settings (effort, UltraCode, permissions, title);
- background work queued when the app quit;
- its task suggestions and scheduled tasks;
- deletion markers, so deleted sessions stay deleted.

**Not carried over,** because they belong to an account: claude.ai connectors, Remote Control links, and sidebar
custom groups. Reconnect or re-create them under the new account.

**Never touched:** conversation files (`~/.claude/projects/`), passwords, cookies, tokens, other windows.

**It refuses** while the window is running, while a session is open in another process, when the target is
ambiguous, or when any file is unreadable. All checks happen before anything is written.

## Settings (optional)

| Variable | Default | Purpose |
|---|---|---|
| `CCD_REHOME_PROFILES` | — | extra window folders, `:`-separated (`;` on Windows) |
| `CCD_REHOME_INSTANCES` | — | folders whose subfolders are window folders (like `~/.claude-instances`), `:`-separated (`;` on Windows) |
| `CCD_REHOME_CLI_HOMES` | — | extra CLI homes, `:`-separated (`;` on Windows) |
| `CCD_REHOME_DESKTOP` | per OS | the Desktop program `launch` starts |
| `CCD_REHOME_STATE` | the state folder (see [Undo](#undo)) | where archives, the account registry and what `profiles --add` registered live |
| `CCD_REHOME_FALLBACK_MODEL` | `claude-opus-5-5` | model for sessions whose model only exists on a local gateway |
| `CCD_REHOME_LOCAL_MODEL_RE` | `^claude-local-.*$` | which model names count as local-gateway-only |
