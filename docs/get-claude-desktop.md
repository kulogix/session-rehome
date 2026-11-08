# Getting Claude Desktop

| OS | How | The program |
|---|---|---|
| macOS | Anthropic's installer, from claude.ai | `/Applications/Claude.app` |
| Windows | Anthropic's installer, from claude.ai | `%LOCALAPPDATA%\AnthropicClaude\claude.exe` |
| Linux x86_64 | Anthropic's Linux package `claude-desktop`, where it is available to you | `claude-desktop` |
| Raspberry Pi and other ARM64 Linux | the **unofficial** community repackage from `pkg.claude-desktop-debian.dev` (package `claude-desktop-unofficial`; not made by Anthropic) | `claude-desktop-unofficial` |

Claude Code, the terminal program, is separate: see Anthropic's
[Claude Code setup](https://code.claude.com/docs/en/setup). Desktop brings its own copy of Claude Code for its
Code tab; the terminal `claude` command is installed on its own.

## Raspberry Pi: the community package

Found on a Raspberry Pi (Debian 13, labwc desktop) on 2026-11-07:

- **The rename.** From Desktop 4.x the package is `claude-desktop-unofficial`, and so is the command;
  `claude-desktop` became an empty transitional package. **Quit Desktop before upgrading.** The upgrade removes the
  old program files under a running window, which then cannot quit and has to be force-closed.
- **The keyring.** The new launcher no longer forces the system keyring. If your login was saved by an older
  build, add this line to `~/.config/claude-desktop-debian/environment`, or Desktop may hang or sign you out:

  ```
  CLAUDE_PASSWORD_STORE=gnome-libsecret
  ```

- **Starting it from a terminal or over ssh** needs your desktop session's environment (`DISPLAY`,
  `WAYLAND_DISPLAY`, `XDG_*`). Without it the launcher says "No display detected". The menu entry has it.
- **After signing in, the Code tab can stay empty** until the next start on some builds. Quit (or force-close) and
  start it again; your sessions on disk are safe.

`ccd-rehome launch` and `doctor` know both program names. To use another program, set
`CCD_REHOME_DESKTOP=/path/to/it`.

Next: [run several Desktop windows](multiple-instances.md), each signed in to its own account.
