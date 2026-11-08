# How it works

## Where a session lives

A Claude Code session has two parts.

1. **The conversation**: one file, `~/.claude/projects/<folder key>/<session id>.jsonl`, plus a folder of the same
   name next to it for sub-agent conversations and saved tool output. The terminal `claude` command and every
   Desktop window on the machine share these files.
2. **For Desktop sessions, a small record** in the window's own folder (its user-data-dir):
   `claude-code-sessions/<account id>/<org id>/local_<id>.json`. It holds the title, the settings (model, effort,
   permissions) and which conversation file it belongs to.

The **folder key** is the session's working folder with every character other than letters and digits turned into
`-`: `/home/dana/Projects/my app` becomes `-home-dana-Projects-my-app`. Very long paths get a hash suffix. Claude
Code finds a conversation only under the key of the folder you start it in, which is why a session belongs to a
folder.

## Why Desktop sessions "vanish" after a sign-in change

Desktop lists only the records under the **signed-in account and org**. Sign a window in to another account, and
the old records are still there, in the old account's folder, just not listed. The conversations are untouched.

`ccd-rehome` moves the small record into the folder Desktop now reads, and that is the whole fix. Records contain
no account ids, so the folder alone decides which account owns a session. Along the way it:
- **checks every file first** against the formats it knows (ERROR, DRIFT, NOTE), so a Desktop update that changes
  something makes it stop instead of guess;
- **drops what belongs to the old account** (connector settings, Remote Control state) and keeps everything else;
- **brings the side files**: task suggestions, scheduled tasks, deletion markers;
- **archives first,** so `rollback` restores the exact earlier state;
- **confirms from Desktop's own log** (`verify`) that Desktop loaded every session.

It learns which e-mail belongs to which account id from Desktop's own storage and logs, and from the account
entry of the terminal CLI's `~/.claude.json`, never from a password or token. It remembers every pairing it has
seen in `~/.claude-instances/_rehome/accounts.json`.

## Why terminal ↔ Desktop needs no copying

A Desktop session is a Claude Code conversation plus a record. `register` writes a record for a terminal
conversation; `unregister` removes one. The conversation file never changes. Desktop's own "Recover CLI
sessions" import does change it: it rewrites the file in place and strips the reasoning blocks.

## Why another machine needs care

Copying a conversation to another machine looks like a file copy, but three things make it delicate:
- **The folder key changes** when the project lives in a different folder, so the file must be placed under the
  key of the new folder, with its sub-agent folder renamed alongside.
- **The file is an append-only history** with internal links between records. Editing it, even to fix paths,
  breaks resuming in ways that are hard to see. So the transporter never edits it: it appends a note that says
  the session moved, with a table of old and new paths, and writes the same into the project's `CLAUDE.md`.
- **The reasoning blocks carry signatures** made by Anthropic's servers. They cannot be recreated, so they must
  arrive byte for byte.

The bundle (`claude-session-bundle/1`) is a zip that holds exactly what belongs to the session, a manifest with a
sha256 for every file, and the Desktop record in a portable form without account ids. `inspect` and `import`
re-check every hash; `import` then installs it the same careful way the ssh-based procedure does. The proof file
from the original machine shows that the original conversation still has exactly the bytes that were packed.

## Further reading

- [`skills/claude-desktop-rehome/references/mechanics.md`](../skills/claude-desktop-rehome/references/mechanics.md):
  the Desktop storage layout, the log lines the tool reads, and the evidence for every rule.
- [`skills/claude-session-transporter/references/mechanics.md`](../skills/claude-session-transporter/references/mechanics.md):
  the conversation format, the folder key, resuming, and what is safe to change.
- [`skills/claude-session-transporter/references/bundle-format.md`](../skills/claude-session-transporter/references/bundle-format.md):
  the bundle and proof formats.
- [`skills/claude-session-transporter/references/integrity.md`](../skills/claude-session-transporter/references/integrity.md)
  and [`secrets.md`](../skills/claude-session-transporter/references/secrets.md): verification, and what must
  never be copied.
