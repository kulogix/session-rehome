# Running several Claude Desktop windows

Claude Desktop is an Electron app and accepts Chromium's `--user-data-dir` flag. Every distinct folder is an
independent **instance** (these pages also say *window* or *profile*): its own window, its own sign-in, and its own
list of Code sessions. That is how you keep a work account and a personal account open side by side.

**Any folder works.** These pages use `~/.claude-instances/work` as an example; `~/data/claude/work`, a folder on
another disk, or anything else is just as good. `ccd-rehome` finds a folder in `~/.claude-instances` by itself, and
any other one once you register it ([below](#your-own-folders)) or start it from a launcher or shell alias it reads.

```bash
mkdir -p ~/.claude-instances/work ~/.claude-instances/personal
```

```bash
claude-desktop --user-data-dir="$HOME/.claude-instances/work"
```

| OS | Start an extra instance |
|---|---|
| Linux | `claude-desktop --user-data-dir="$HOME/.claude-instances/work"` |
| Raspberry Pi (community package) | `claude-desktop-unofficial --user-data-dir="$HOME/.claude-instances/work"` |
| macOS | `open -n -a Claude --args --user-data-dir="$HOME/.claude-instances/work"` (`-n`: a new instance even if Claude is open) |
| Windows | `"%LOCALAPPDATA%\AnthropicClaude\claude.exe" --user-data-dir="%USERPROFILE%\.claude-instances\work"` |

The Linux and Raspberry Pi commands are verified. The macOS and Windows commands follow the same Electron rules
but have not been confirmed on those systems yet; please report what you find.

Sign each instance in to the account it should use. The window started with no flag is the **default** instance.
Its folder is `~/.config/Claude` (Linux), `~/Library/Application Support/Claude` (macOS) or `%APPDATA%\Claude`
(Windows).

## What is separate, and what is shared

**Separate per instance:**
- sign-in and cookies;
- the list of Code (and Cowork) sessions;
- window state and app settings;
- claude.ai connectors.

**Shared by the instances that read the same CLI home** (and by the terminal `claude` command when it uses that
home):
- the CLI home: its conversation files (`projects/`), Claude Code settings, skills and memory. Desktop and the
  terminal both read the folder in `CLAUDE_CONFIG_DIR` when it is set, and `~/.claude` when it is not, so every
  instance started without `CLAUDE_CONFIG_DIR` shares `~/.claude/`. Each `CLAUDE_CONFIG_DIR` home has its own
  `projects/`: an instance or a terminal started with another one sees other conversations (see
  [Several CLI accounts](#several-cli-accounts-claude_config_dir) below);
- your project folders, always.

So two instances that read the same home can work on different sessions of the same project at the same time.
They must **not** have the *same* session open at once: two writers fork its history.

## Launcher shortcuts

- **Linux:** create `~/.local/share/applications/claude-work.desktop`. `Exec=` does not expand `~` or `$HOME`, so
  write the full path:

  ```ini
  [Desktop Entry]
  Type=Application
  Name=Claude (work)
  Exec=claude-desktop --user-data-dir=/home/YOU/.claude-instances/work
  Icon=claude-desktop
  ```

- **macOS:** an Automator "Application", or a Shortcuts "Run Shell Script" action, running the `open -n …` line
  above.
- **Windows:** a shortcut whose Target is the `claude.exe … --user-data-dir=…` line above.

## Several CLI accounts (CLAUDE_CONFIG_DIR)

The terminal `claude` command uses the same idea with an environment variable instead of a flag. The default config
dir is `~/.claude`; each additional one is a separate login and a separate session history:

```bash
alias claude-work='CLAUDE_CONFIG_DIR=~/.claude-work claude'
```

A home made that way is named `cli:work`; `cli` is `~/.claude`. Start it once (`claude-work`) and sign in, so the
folder exists. A home can be any folder: `ccd-rehome profiles` finds homes from `~/.claude-*`, from the folders of a
profile root, from `CLAUDE_CONFIG_DIR=/absolute/path` assignments in the usual shell startup files (commented-out
lines and relative paths are skipped), from its own environment and from `$CCD_REHOME_CLI_HOMES`; a path anywhere else
works once you pass it or add it (`ccd-rehome profiles --add PATH`), and is remembered. A home found only in a shell
file is forgotten when you remove the line. `cli:NAME` is `~/.claude-NAME`, else the one known home whose folder is
called `NAME` or `.claude-NAME`. Your home folder itself, a folder above `~/.claude`, `~/.claude-instances`, a folder
that holds a Desktop window folder and the tool's state folder are never CLI homes. Avoid naming a Desktop window
folder in a profile root `cli`: the name `cli` then fits both it and `~/.claude`, the tool refuses it as ambiguous,
and you type paths instead. A window folder `cli-work` is fine: it is named `cli-work`, and `cli:work` still means
`~/.claude-work`.

```bash
ccd-rehome profiles
```

Moving sessions between homes is new: it has not yet run on a real signed-in CLI home (see
[switch-accounts.md](switch-accounts.md#terminal-cli-accounts) for how far it is tested), so start with the dry run:

```bash
ccd-rehome move cli --only 1a2b3c4d --to-profile cli:work --dry-run
```

```bash
ccd-rehome move cli --only 1a2b3c4d --to-profile cli:work
```

Desktop reads the default home unless it was started with `CLAUDE_CONFIG_DIR` set, so its Code tab may not list a
non-default home's conversations. `ccd-rehome cli-sessions` says which home each unlisted conversation is in.
Nothing on disk records how a window was started, so the tool takes every window to read `~/.claude`. Where a
window's records' conversations happen to be is only a hint (`ccd-rehome sessions PROFILE` adds a note when none of
them is in `~/.claude`): a backup copy of `~/.claude` would fool it. `ccd-rehome register` accepts a conversation in
`~/.claude`, and for one in another home prints the copy that brings it into `~/.claude`. A move that takes a
conversation a window shows INTO `~/.claude` is always allowed; for a session marked `in cli:work`, `sessions
PROFILE` prints the `--copy` that gives the window its conversation back while `cli:work` keeps its own; a move out
of `~/.claude` is refused; a move between two other homes goes ahead with a note.
`ccd-rehome resume-cli` names the home that holds the conversation. If you started a window with
`CLAUDE_CONFIG_DIR`, these rules do not fit it: keep its conversations in the home it reads yourself.
Moving sessions between homes is described in [switch-accounts.md](switch-accounts.md#terminal-cli-accounts).

## Your own folders

`ccd-rehome profiles` lists every instance and CLI home it finds, and says where it found each one (`found: default`,
`root ~/data/claude`, `running`, `launcher …`, `shell file ~/.bashrc`, `log …`, `added`, `env …`):

```bash
ccd-rehome profiles
```

It looks in:
- the default instance, and every subfolder of a **profile root**: `~/.claude-instances` while it exists, each
  folder you add with `--add-root`, and each folder in `$CCD_REHOME_INSTANCES`;
- the `--user-data-dir` of every running instance, of `.desktop` launchers, and of `claude-desktop`,
  `claude-desktop-unofficial` or `Claude` (`open -n -a Claude --args …`) in your shell startup files (`~/.bashrc`,
  `~/.zshrc`, …; commented-out lines are skipped);
- on macOS, every instance named in Desktop's shared log (`~/Library/Logs/Claude/main*.log`);
- every folder you added with `--add` or named on its command line before, and `$CCD_REHOME_PROFILES`.

Register a folder that holds several instances (or CLI homes) once, and every one in it is found, those you create
later too:

```bash
ccd-rehome profiles --add-root ~/data/claude
```

Or register one instance, or one CLI home, wherever it is:

```bash
ccd-rehome profiles --add /mnt/disk2/claude-acct
```

`--forget` undoes either. Instead of registering, you can set `CCD_REHOME_INSTANCES` (folders of instances) or
`CCD_REHOME_PROFILES` (single instances), `:`-separated (`;` on Windows), for example in your shell startup file.

An instance in a profile root goes by its folder name (`work`); one anywhere else by its path, though its folder name
works too. A name must fit exactly one folder: with `~/.claude-instances/work` and `~/data/claude/work` both there,
`work` is refused and the message lists both paths, so type the path.

## Good to know

- Never point two running windows at the same folder. Chromium refuses the second one.
- A sibling folder `<name>-3p` may appear. That is Desktop's own profile for a third-party inference gateway;
  leave it alone.
- `ccd-rehome` keeps its own state (the archives behind every change, the account registry, what you registered) in
  `~/.local/state/session-rehome` on Linux (`$XDG_STATE_HOME`, if set), `~/Library/Application Support/session-rehome`
  on macOS and `%LOCALAPPDATA%\session-rehome` on Windows. If an earlier version made
  `~/.claude-instances/_rehome`, that folder keeps being used, so its archives still roll back. It never creates
  `~/.claude-instances`.

Next: [change the account an instance is signed in to](switch-accounts.md) without losing its sessions.
