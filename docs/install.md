# Installing

You need:
- **Python 3.9 or newer.** macOS includes it with the Xcode command line tools (`xcode-select --install`); most
  Linux systems ship it; on Windows, install it from python.org (this gives you the `py` command).
- **Claude Code**, if an agent should use the tools as skills. The scripts also run on their own.
- **Claude Desktop**, only if you use Desktop sessions: [get-claude-desktop.md](get-claude-desktop.md).

To move a session **between machines**, install on both of them.

## Option 1: the plugin (your agent uses the tools)

In a Claude Code session:

```
/plugin marketplace add kulogix/session-rehome
/plugin install session-rehome@kulogix
```

Or from a shell:

```bash
claude plugin marketplace add kulogix/session-rehome
```

```bash
claude plugin install session-rehome@kulogix
```

The two skills then appear as `session-rehome:session-rehome` and
`session-rehome:session-transporter`, and your agent picks the right one when you describe what you want
("my Desktop sessions are gone after I switched accounts", "move this session to my laptop").

- **Updating:** third-party marketplaces do not update automatically unless you turn it on (`/plugin`, the
  Marketplaces tab, Enable auto-update). To update now: `claude plugin update session-rehome@kulogix`, then start
  a new session.
- **Removing:** `claude plugin uninstall session-rehome@kulogix`.

The plugin keeps its files in Claude Code's plugin cache. To type the commands yourself, use option 2 instead.

## Option 2: a clone and the installer (your agent, and you)

```bash
git clone https://github.com/kulogix/session-rehome ~/Projects/session-rehome
```

```bash
python3 ~/Projects/session-rehome/install.py --bin ~/.local/bin
```

This links both skills into `~/.claude/skills/` and writes three small launchers into `~/.local/bin`:
`ccd-rehome`, `st-bundle` and `st-verify`. Make sure that folder is on your `PATH` (the installer tells you if it
is not). Start a new Claude Code session afterwards: skills are read when a session starts.

- **Linked, not copied** (the default on macOS and Linux): the installed skills *are* the clone. `git pull` updates
  them, and a fix made there is in the place you can share it from.
- **`--copy`** copies instead. Re-run the installer after each `git pull`. A copy you edit is never thrown away:
  the installer moves it to `~/.claude/skill-backups/` before replacing it.
- **`--dry-run`** shows what it would do. **`--status`** shows what is installed, from where, and which versions.
- **It never overwrites a folder it did not create.** If `~/.claude/skills/session-rehome` already exists
  (for example an older clone), it stops and explains. `--force` moves that folder to `~/.claude/skill-backups/`
  and continues; nothing is deleted.

Check the machine:

```bash
ccd-rehome doctor
```

`doctor` checks Python, the Desktop app, your Desktop windows and their logs, and whether this Desktop version
still matches what the tool expects. It writes nothing. To run every test (synthetic data in a temporary folder;
nothing of yours is touched):

```bash
python3 ~/Projects/session-rehome/tests/run_all.py
```

**Updating:**

```bash
git -C ~/Projects/session-rehome pull
```

**Removing** (only what the installer installed):

```bash
python3 ~/Projects/session-rehome/install.py --uninstall --bin ~/.local/bin
```

## Windows

Use `py -3` where these pages say `python3`, and copy mode (symlinks need Developer Mode on Windows). The
`.cmd` launchers go in any folder on your `PATH`:

```bat
git clone https://github.com/kulogix/session-rehome %USERPROFILE%\session-rehome
py -3 %USERPROFILE%\session-rehome\install.py --copy --bin %USERPROFILE%\bin
```

Add `%USERPROFILE%\bin` to your `PATH` (System Properties, Environment Variables) if it is not there yet.
`ccd-rehome` and `st-bundle` then work in any terminal. `st-verify` and the other `.sh` scripts need bash: run
them in WSL or Git Bash. Windows support is experimental: please report what works (see
[CONTRIBUTING.md](../CONTRIBUTING.md)).

## Without installing

Everything also runs straight from the clone, for example:

```bash
python3 ~/Projects/session-rehome/skills/session-rehome/scripts/ccd-rehome status
```

```bash
python3 ~/Projects/session-rehome/skills/session-transporter/scripts/st-bundle.py list
```

## Moving from earlier versions

**From 0.9.x** (the project was called `claude-session-rehome`, its skills `claude-desktop-rehome` and
`claude-session-transporter`; skill names may not contain the word "claude", so they were renamed in 0.10.0):

1. Update your clone. GitHub redirects the old address, but point it at the new one:

   ```bash
   git -C ~/Projects/claude-session-rehome remote set-url origin https://github.com/kulogix/session-rehome
   ```

   ```bash
   git -C ~/Projects/claude-session-rehome pull
   ```

2. Run the installer again. It removes the old links (and unchanged old copies) itself, installs the skills
   under their new names, and refreshes the launchers:

   ```bash
   python3 ~/Projects/claude-session-rehome/install.py --bin ~/.local/bin
   ```

   A plugin install: `claude plugin uninstall session-rehome@kulogix`, then add the marketplace again from
   `kulogix/session-rehome` and install.

**From the original `kulogix/claude-desktop-rehome` repository** (before 0.9), or the unpublished
`session-transporter` skill: clone this project, then run the installer with `--force`. It moves the old
`~/.claude/skills/claude-desktop-rehome` folder (and any other folder in the way) to `~/.claude/skill-backups/`;
nothing is deleted.

```bash
python3 ~/Projects/session-rehome/install.py --force --bin ~/.local/bin
```

In every case nothing else changes: `ccd-rehome` keeps using the state folder an earlier version made
(`~/.claude-instances/_rehome`), so `rollback` still undoes moves made with an earlier version, and projects
moved with an earlier transporter keep working (their `CLAUDE.md` note is recognised, and upgraded the next time
a session is moved into that project).

## What goes where

| Path | What |
|---|---|
| `~/.claude/skills/session-rehome/` | the one-machine skill and `ccd-rehome` (a link to the clone, or a copy) |
| `~/.claude/skills/session-transporter/` | the between-machines skill, `st-bundle.py` and the `st-*` scripts |
| `~/.local/bin/ccd-rehome`, `st-bundle`, `st-verify` | launchers (with `--bin`) |
| `~/.local/state/session-rehome/` (Linux; `$XDG_STATE_HOME/session-rehome` if set), `~/Library/Application Support/session-rehome/` (macOS), `%LOCALAPPDATA%\session-rehome\` (Windows) | `ccd-rehome`'s state folder: the account registry, the archive behind every change, and the profiles and roots registered with `profiles --add` / `--add-root`. If `~/.claude-instances/_rehome/` exists (an earlier version made it), it is used instead; `CCD_REHOME_STATE` overrides both. `ccd-rehome profiles` prints the one in use. The tool never creates `~/.claude-instances` |
| `~/.local/share/st-bundles/` | unpacked bundles after `st-bundle import --apply` (safe to delete once verified) |
