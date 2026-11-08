# Running several Claude Desktop windows

Claude Desktop is an Electron app and accepts Chromium's `--user-data-dir` flag. Every distinct folder is an
independent **instance** (these pages also say *window* or *profile*): its own window, its own sign-in, and its own
list of Code sessions. That is how you keep a work account and a personal account open side by side.

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

**Shared by all instances** (and by the terminal `claude` command):
- `~/.claude/`: the conversation files, Claude Code settings, skills, memory;
- your project folders.

So two instances can work on different sessions of the same project at the same time. They must **not** have the
*same* session open at once: two writers fork its history.

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

## Good to know

- Never point two running windows at the same folder. Chromium refuses the second one.
- A sibling folder `<name>-3p` may appear. That is Desktop's own profile for a third-party inference gateway;
  leave it alone.
- `ccd-rehome profiles` lists every instance it can find: `~/.claude-instances/*`, running instances, launchers
  that use `--user-data-dir`, and any folder you have given it before. A folder anywhere else works too: pass its
  path once and the tool remembers it.

```bash
ccd-rehome profiles
```

Next: [change the account an instance is signed in to](switch-accounts.md) without losing its sessions.
