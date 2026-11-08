# Moving a session to another computer or OS

Move a Claude Code session (a terminal session, or a Claude Desktop Code session) to another computer, another
operating system, or another folder, with its full history, and prove afterwards that nothing was lost or changed.

The tool is `st-bundle`, from the skill claude-session-transporter. It packs one session into a single verified
file that you carry over any way you like (scp, a USB stick, a cloud drive). Neither machine needs to reach the
other.

## What it guarantees

- **The conversation is copied byte for byte.** Its original bytes are proven unchanged at the destination. A note
  is *appended* to tell the model it moved; history is never edited.
- **Everything that belongs to the session comes along:** its sub-agent conversations, saved tool output, todo
  list, project files and (optionally) the project's memory. If it is a Desktop session, its Desktop record comes
  too: title, effort, permissions and settings.
- **Nothing private comes along:** no passwords, login tokens, `~/.claude.json`, shell history, settings or other
  sessions. Project files that look like secrets (`.env`, private keys) are left out unless you ask, and
  secret-looking text *inside* the conversation is counted and reported (it cannot be removed, so rotate those
  credentials).
- **The original machine is never changed,** and a proof file made there afterwards confirms it.

## Before you start

- Install this project on **both** machines ([install.md](install.md)), with Python 3.9+. The bundle needs nothing
  else: no bash, rsync or ssh. (Only the final verification uses bash, so on Windows run it under WSL or Git Bash.)
- **Use the session on one machine at a time.** If you keep working on the original after exporting, the two
  copies fork.

## Step by step

**1. Find the session** on the machine that has it:

```bash
st-bundle list
```

It lists every session, newest first, with its id, folder, title and opening words.

**2. Pack it.** Run with `--dry-run` first: it shows exactly what would be packed, and writes nothing.

```bash
st-bundle export --session-id ID --project-root ~/Projects/myproject --exclude '/node_modules/  # reinstallable' --desktop-profile default -o myproject.csb.zip --dry-run
```

Then the same command without `--dry-run`.
- `--project-root` is the project folder to bring along. Use `--no-project` to bring only the conversation.
- `--desktop-profile` names the Desktop window the session is listed in (`default` is the plain window). Leave it
  out for a terminal-only session.
- `--no-memory` leaves out the project's memory folder. Memory is shared by every session in that project, so it
  can hold notes from other sessions.
- Every `--exclude` must start with `/` (relative to the project folder) and give a reason after `#`. The export
  reports how many files each exclude matched.

**3. Copy the file** to the other machine.

**4. Check it there.** Every byte is verified again:

```bash
st-bundle inspect myproject.csb.zip
```

**5. Install it there.** The `--plan` step writes nothing.
- If the session should appear in Desktop, **quit Desktop** on this machine first.
- `--dest-root` is where the project folder goes on this machine. It can differ from the original folder.
- `--desktop-profile` names the window that should list it. It is filed under that window's signed-in account, or
  under `--to EMAIL`.

```bash
st-bundle import myproject.csb.zip --dest-root ~/Projects/myproject --desktop-profile default --plan
```

```bash
st-bundle import myproject.csb.zip --dest-root ~/Projects/myproject --desktop-profile default --apply
```

The import ends by printing the exact command for step 6.

**6. Prove the original was not touched.** On the original machine:

```bash
st-bundle origin-proof myproject.csb.zip -o proof.json
```

Copy `proof.json` over. On the new machine, run the command the import printed, adding `--origin-proof proof.json`.
It looks like this (the import fills in the staging folder):

```bash
st-verify --checkpoint ~/.local/share/st-bundles/ID-TIME --dest-root ~/Projects/myproject --session-id ID --origin-proof proof.json
```

It checks every byte and loads the conversation with your Claude Code without spending a turn.

**7. Use it.** Start Desktop, or in a terminal:

```bash
cd ~/Projects/myproject && claude --resume ID
```

A good final check: ask the session something only its real history can answer.

## Things to know

- **Accounts.** Moving to a machine where you use the same Claude account is the safe case. Between *different
  accounts of the same person* it has worked. Between **different organisations** it is untested: the
  conversation's reasoning blocks are signed, and may be rejected.
- **Paths in the history are old paths.** Commands in the conversation refer to the original machine's folders.
  The appended note and a section in the project's `CLAUDE.md` tell the model so; an old script that fails on an
  old path is expected.
- **Skills and plugins** are not packed. Install the ones you use on the new machine before starting the session.
- **Never use Desktop's "Recover CLI sessions"** on a moved conversation. It rewrites the file and strips its
  reasoning. The import makes the session appear without it.
- **A copy for someone else** (another person's account) exposes everything the conversation saw: every file it
  read and every command it ran. Decide that on purpose.

## Other ways to move a session

- **Pull it over ssh** from a machine this one can reach, with a read-only checkpoint and manifests built on both
  sides, or **restore it from a backup** (a USB disk, an extracted archive): the transporter's gated procedure,
  [`references/gated-procedure.md`](../skills/claude-session-transporter/references/gated-procedure.md). Your
  agent knows it; it needs bash and rsync on both sides.
- **Fork a session** into a new id, keeping the original: `st-bundle import … --new-session-id NEW_UUID`.
- **A fresh session that knows the context,** without the history: copy the project's memory folder and write a
  `CLAUDE.md`. Cheaper and often better (see the transporter's SKILL.md, "When NOT to use this skill").

## Tested

On 2026-11-07, a real session (a 0.9 MB conversation, 64 MB of saved tool output, a Desktop record, project files)
was exported on Linux x86_64 and imported on macOS 26.6 (Apple Silicon, Python 3.9.6) and on a Raspberry Pi
(Debian 13, ARM64). Each machine's own Claude Code loaded it, and the original was proven unchanged. Not yet
tested: a real Windows machine, and moves between different organisations. See
[`tested.json`](../skills/claude-session-transporter/tested.json).
