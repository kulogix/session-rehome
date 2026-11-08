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
/plugin marketplace add kulogix/claude-session-rehome
/plugin install session-rehome@kulogix
```

Or from a shell:

```bash
claude plugin marketplace add kulogix/claude-session-rehome
```

```bash
claude plugin install session-rehome@kulogix
```

The two skills then appear as `session-rehome:claude-desktop-rehome` and
`session-rehome:claude-session-transporter`, and your agent picks the right one when you describe what you want
("my Desktop sessions are gone after I switched accounts", "move this session to my laptop").

- **Updating:** third-party marketplaces do not update automatically unless you turn it on (`/plugin`, the
  Marketplaces tab, Enable auto-update). To update now: `claude plugin update session-rehome@kulogix`, then start
  a new session.
- **Removing:** `claude plugin uninstall session-rehome@kulogix`.

The plugin keeps its files in Claude Code's plugin cache. To type the commands yourself, use option 2 instead.

## Option 2: a clone and the installer (your agent, and you)

```bash
git clone https://github.com/kulogix/claude-session-rehome ~/Projects/claude-session-rehome
```

```bash
python3 ~/Projects/claude-session-rehome/install.py --bin ~/.local/bin
```

This links both skills into `~/.claude/skills/` and writes three small launchers into `~/.local/bin`:
`ccd-rehome`, `st-bundle` and `st-verify`. Make sure that folder is on your `PATH` (the installer tells you if it
is not). Start a new Claude Code session afterwards: skills are read when a session starts.

- **Linked, not copied** (the default on macOS and Linux): the installed skills *are* the clone. `git pull` updates
  them, and a fix made there is in the place you can share it from.
- **`--copy`** copies instead. Re-run the installer after each `git pull`. A copy you edit is never thrown away:
  the installer moves it to `~/.claude/skill-backups/` before replacing it.
- **`--dry-run`** shows what it would do. **`--status`** shows what is installed, from where, and which versions.
- **It never overwrites a folder it did not create.** If `~/.claude/skills/claude-desktop-rehome` already exists
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
python3 ~/Projects/claude-session-rehome/tests/run_all.py
```

**Updating:**

```bash
git -C ~/Projects/claude-session-rehome pull
```

**Removing** (only what the installer installed):

```bash
python3 ~/Projects/claude-session-rehome/install.py --uninstall --bin ~/.local/bin
```

## Windows

Use `py -3` where these pages say `python3`, and copy mode (symlinks need Developer Mode on Windows). The
`.cmd` launchers go in any folder on your `PATH`:

```bat
git clone https://github.com/kulogix/claude-session-rehome %USERPROFILE%\claude-session-rehome
py -3 %USERPROFILE%\claude-session-rehome\install.py --copy --bin %USERPROFILE%\bin
```

Add `%USERPROFILE%\bin` to your `PATH` (System Properties, Environment Variables) if it is not there yet.
`ccd-rehome` and `st-bundle` then work in any terminal. `st-verify` and the other `.sh` scripts need bash: run
them in WSL or Git Bash. Windows support is experimental: please report what works (see
[CONTRIBUTING.md](../CONTRIBUTING.md)).

## Without installing

Everything also runs straight from the clone, for example:

```bash
python3 ~/Projects/claude-session-rehome/skills/claude-desktop-rehome/scripts/ccd-rehome status
```

```bash
python3 ~/Projects/claude-session-rehome/skills/claude-session-transporter/scripts/st-bundle.py list
```

## Moving from the older repositories

This project replaces `kulogix/claude-desktop-rehome` and the unpublished `session-transporter` skill.

1. Clone this project (above).
2. Run the installer with `--force`. It moves the old `~/.claude/skills/claude-desktop-rehome` and
   `~/.claude/skills/session-transporter` folders to `~/.claude/skill-backups/` (two copies of a skill must not
   load at once) and installs the new ones:

   ```bash
   python3 ~/Projects/claude-session-rehome/install.py --force --bin ~/.local/bin
   ```

3. Nothing else changes. `ccd-rehome` keeps its state and archives in the same folder
   (`~/.claude-instances/_rehome`), so `rollback` still undoes moves made with the old version. Projects moved with
   the old transporter keep working: their `CLAUDE.md` note is recognised, and upgraded the next time a session
   is moved into that project.

## What goes where

| Path | What |
|---|---|
| `~/.claude/skills/claude-desktop-rehome/` | the one-machine skill and `ccd-rehome` (a link to the clone, or a copy) |
| `~/.claude/skills/claude-session-transporter/` | the between-machines skill, `st-bundle.py` and the `st-*` scripts |
| `~/.local/bin/ccd-rehome`, `st-bundle`, `st-verify` | launchers (with `--bin`) |
| `~/.claude-instances/_rehome/` | `ccd-rehome`'s account registry and the archive behind every change |
| `~/.local/share/st-bundles/` | unpacked bundles after `st-bundle import --apply` (safe to delete once verified) |
