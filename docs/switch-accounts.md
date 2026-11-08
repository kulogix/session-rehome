# Switching accounts, and moving sessions on one machine

After you sign a Desktop window in to a different account, its Code tab is empty. Nothing was deleted: Desktop
files each session under the account that created it and only shows the signed-in account's sessions
([how-it-works.md](how-it-works.md)). `ccd-rehome` moves them to where Desktop looks.

In the commands below, `work` is the name of a Desktop window: `default` for the plain one, the folder name for an
instance under `~/.claude-instances/`, or the full path of any user-data-dir.

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

## Undo

```bash
ccd-rehome rollback work 20261107T120000Z-move
```

Every move prints its archive name and this command, and `ccd-rehome status work` lists them. The window must be
quit. Rollback restores the exact earlier state and keeps a safety copy of what it replaced. Archives live in
`~/.claude-instances/_rehome/archive/` (a few KB each); old ones are safe to delete.

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
| `CCD_REHOME_DESKTOP` | per OS | the Desktop program `launch` starts |
| `CCD_REHOME_STATE` | `~/.claude-instances/_rehome` | where archives and the account registry live |
| `CCD_REHOME_FALLBACK_MODEL` | `claude-opus-5-5` | model for sessions whose model only exists on a local gateway |
| `CCD_REHOME_LOCAL_MODEL_RE` | `^claude-local-.*$` | which model names count as local-gateway-only |
