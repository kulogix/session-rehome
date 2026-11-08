# Troubleshooting

Every refusal says why, and nothing was changed when a command refuses. Find the message below.

## Installing

| You see | Do |
|---|---|
| `REFUSED: … exists and was not installed by this installer` | an older copy is in the way. `install.py --force` moves it to `~/.claude/skill-backups/` (nothing is deleted) |
| `an older install of claude-session-transporter` | the old `session-transporter` folder is present; both would load. `install.py --force` moves it aside |
| `ccd-rehome: command not found` | the launcher folder is not on your `PATH`, or you installed without `--bin`. Re-run `install.py --bin ~/.local/bin` and add that folder to `PATH` |
| `could not create a symlink` (Windows) | use `install.py --copy` |
| the agent does not find the skills | start a new Claude Code session: skills are read when a session starts. `install.py --status` shows what is installed |

## One machine (`ccd-rehome`)

| You see | Do |
|---|---|
| `is running … Quit it` | quit that window (File > Quit), or `ccd-rehome quit work` on macOS / Linux |
| `Desktop ignored the quit signal` | quit it from its menu. If it is frozen, force-close it and start it again; your sessions on disk are safe |
| `refusing: this command is running INSIDE …` | you (or your agent) are inside that window; quit it yourself |
| `not signed in` | sign that window in, quit, re-run |
| `no org known … ambiguous` | open the Code tab once while signed in, quit, re-run (or pass `--to-org`) |
| `matches 0 known accounts` | check the spelling with `ccd-rehome accounts`; the account must have been signed in once somewhere on this machine |
| `not a Desktop profile (no config.json)` | wrong folder, or that window was never started: start it once |
| `these conversations are open in another process` | the session is open in a terminal or another window: close it there |
| `cannot find the Desktop app` | start it yourself, or set `CCD_REHOME_DESKTOP=/path/to/app` |
| `verify … MISMATCH` | quit and start the window again, then verify again; if it persists, look at `ccd-rehome sessions work` for unreadable records |
| `verify: has not logged loading … yet` | it is still starting: wait, open the Code tab, re-run |
| `DRIFT` (from `doctor` or a move) | a newer Desktop stores something the tool does not know. Update this project first. If it is still there, look at it with `--dry-run`, then use `--accept-drift` or report it (CONTRIBUTING.md) |
| `ERROR … refusing` | a file is not in the expected format. Nothing was changed; please report it |
| `Cowork move refused` | Cowork spaces or agents hold data whose link to sessions is not understood yet. Code sessions move fine without `--include-cowork` |
| a session shows `transcript MISSING` | its conversation file is not on this machine (usually a session made elsewhere). Moving it is harmless, but it will not open |
| signed in, but the Code tab stays empty or the app seems frozen | quit (or force-close) and start it again: on some builds the sign-in only lands on the next start |
| after upgrading the Raspberry Pi package, Desktop hangs or is signed out | see [get-claude-desktop.md](get-claude-desktop.md): the keyring line |

## Between machines (`st-bundle`, `st-verify`)

| You see | Do |
|---|---|
| `NOT VERIFIED: do not import` | the file was damaged or changed on the way: copy it again |
| `the destination filesystem is case-insensitive and the bundle has name collisions` | two project files differ only in case. Rename one on the original machine and export again |
| `exclude … is unanchored` / `has no justification` | write it as `'/folder/  # why'` |
| `names Windows cannot store` | a project file name is not valid on Windows (for example it contains `:`). Rename it on the original machine |
| `REFUSING to mint the Desktop session while that instance is running` | quit Desktop on this machine and re-run the import; it is safe to re-run |
| `No conversation found` when resuming | start `claude --resume` from the `--dest-root` folder you gave the import |
| verify: `origin proof … CHANGED` | something wrote to the conversation on the original machine after the export: export again |
| verify: `GROWN` | the session was used on the original after the export: the copies have forked |
| the session opens, but the model was rejected | the new machine's Claude Code is older than the one that wrote the session: update it |

## Still stuck

Open an issue with the output of `ccd-rehome report doctor` and `ccd-rehome doctor` (they contain nothing
identifying). See [CONTRIBUTING.md](../CONTRIBUTING.md).
