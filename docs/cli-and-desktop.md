# Terminal (CLI) ↔ Desktop

Every Desktop Code session is a Claude Code conversation underneath: the same file in `~/.claude/projects/`,
plus a small Desktop record that points at it. So a session can move between the terminal `claude` command and
Desktop without copying or changing the conversation.

## Terminal → Desktop

```bash
ccd-rehome cli-sessions
```

```bash
ccd-rehome register default --cli-session-id 1a2b3c4d
```

`cli-sessions` lists the terminal conversations that no Desktop window shows. `register` makes one appear in
that window (`default` here), in the folder it ran in. Quit the window first and start it afterwards. `register`
refuses if the folder no longer exists, or while the conversation is open anywhere.

With several CLI homes (`CLAUDE_CONFIG_DIR`, see [switch-accounts.md](switch-accounts.md#terminal-cli-accounts)),
remember that Desktop looks for its conversations in `~/.claude` unless the window was started with
`CLAUDE_CONFIG_DIR`, which the tool cannot see. So `register` always accepts a conversation in `~/.claude`, and
refuses one in another home with the exact copy that brings it into `~/.claude`
(`ccd-rehome move cli:work --to-profile cli --only ID --copy`), after which you run the `register` again. It is a
copy so that the other home keeps its own: that home may be a backup holding an old conversation that `~/.claude`'s
retention (`cleanupPeriodDays`) already deleted. The copy is re-dated wherever `~/.claude` would delete it (the copy
only, never the original; for a conversation last continued in Desktop, when `claude --version` is older than 2.1.248
or not known), and a re-dated copy is deleted there again once it goes that long without a new turn (for a
conversation last continued in Desktop, by a Claude Code before 2.1.248, by `desktopSessionCleanupPeriodDays` or by
managed settings that set `cleanupPeriodDays`). Once a window lists a
conversation (as its current one or an earlier one), a move that would take it out of `~/.claude` is refused
(unregister it first, or use `--copy`; for an earlier one only `--copy`, since unregistering that record would also
take its current conversation out of the window); a move into `~/.claude` is always allowed; a move between two other
homes goes ahead with a note. `ccd-rehome sessions PROFILE` marks a record whose conversation is elsewhere `in
cli:work, CLI id …` and prints the copy that brings each such conversation into `~/.claude`, by its CLI id (the id a
move takes, not the record id); `ccd-rehome status PROFILE` counts them (`3 of these records' conversations are only
in cli:backup, not in ~/.claude`; JSON `elsewhere`) and points to that `sessions` line. A rollback of a move never
stops for a Desktop record: when it takes the conversation back out of `~/.claude`, it warns and prints the copy that
gives the window its conversation back.

**Don't use Desktop's own "Recover CLI sessions" button** for this. It rewrites the conversation file in place
and removes its reasoning content, with no undo. `register` does the same job without touching the file.

## Desktop → terminal

```bash
ccd-rehome resume-cli default --only 1a2b3c4d
```

It prints the exact `cd … && claude --resume …` command (on Windows one line for cmd and one for PowerShell, which
do not accept the `CLAUDE_CONFIG_DIR=… claude` form), after checking the conversation is not open anywhere. When the
conversation is in another CLI home, the command sets `CLAUDE_CONFIG_DIR` to that home, and a note says it is not
in `~/.claude`, where Desktop looks.
The session stays listed in Desktop. To make it terminal-only, remove its Desktop record (undo with `rollback`):

```bash
ccd-rehome unregister default --only 1a2b3c4d
```

**Start that terminal command in a normal terminal, not in a shell inside Claude Desktop.** A `claude` started
inside a Desktop session inherits Desktop's environment and is recorded as Desktop. On macOS and Linux you can
also start it with a clean environment: `env -i HOME="$HOME" USER="$USER" PATH="$PATH" TERM="$TERM" claude --resume
ID`. On Windows, open a new terminal window from the Start menu. `resume-cli` warns you when it detects this.

**Never have the same session open in both at once.** Two writers fork its history.

## What carries over

The conversation itself carries over completely in both directions: it is one file, and nothing edits it. What
can differ is the context around it.

| | Desktop → terminal | terminal → Desktop |
|---|---|---|
| The conversation (every turn, reasoning, tool output, sub-agents, todos) | kept: same file | kept: same file |
| Desktop's per-session settings (title, model, effort, permissions, UltraCode) | kept in the Desktop record; `unregister` archives them | restored from that archive if the session was `unregister`ed before; otherwise Desktop's defaults |
| Which account runs the next turn | the terminal CLI's own login. `resume-cli` warns if it differs from Desktop's | the Desktop window's account |
| The model | an older terminal CLI may not know Desktop's model. `resume-cli` warns | Desktop's own Claude Code is usually the newest |
| Tools | Desktop-only tools (its MCP servers, computer use, browser pane, scheduled tasks) are not available in the terminal | the terminal's MCP setup, if any |
| Background work queued at quit | stays with Desktop | — |

**Measured:** a full round trip on Linux (Desktop 2.31226.1, Claude Code 2.1.319, same account). A terminal turn
planted a code word; `register`; a Desktop turn recalled it and planted a second; a terminal `--resume` recalled
both, in order. The file's earlier bytes were unchanged at every stage, and the history did not fork.

Moving a terminal session to **another machine** is a different job: [other-machines.md](other-machines.md).
