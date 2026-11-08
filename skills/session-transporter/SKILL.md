---
name: session-transporter
description: >-
  Moves a Claude Code session to ANOTHER machine or operating system with its full history (transcript, subagent
  and workflow sidecars, memory, tasks, project files, and the Desktop record), verified byte for byte: "continue
  this session on my other laptop", "move my work from my Mac to this Linux box", "bundle this session", "push
  this session to the Pi", "my other machine has the real history", "restore a session from a backup", "fork this
  session". Packs one portable, hash-verified file (pure Python, any OS) or takes a read-only checkpoint over ssh,
  then installs it without rewriting history. Also audits what in ~/.claude is safe to copy. Never edits a
  transcript and never uses Desktop's "Recover CLI sessions". For a sign-in change, another Desktop window, or
  CLI ↔ Desktop on the SAME machine, use session-rehome.
license: MIT
compatibility: >-
  Python 3.9+, standard library only. The bundle path is pure Python (verified on Linux and macOS; Windows
  untested). The ssh checkpoint, verify and write-back drivers also need bash, rsync and ssh. Works best with
  session-rehome installed alongside (it files the Desktop record).
metadata:
  homepage: https://github.com/kulogix/session-rehome
---

# session-transporter

**Which skill?** This one moves a session **between machines** (or operating systems, or from an archive). The
companion skill **session-rehome** works on **one machine**.

| The user wants to… | Use |
|---|---|
| continue a session on another computer or OS; send it to another machine | **this skill**, path 1 (the bundle) |
| pull a session from a machine this one can ssh to, or restore one from a backup or archive | **this skill**, path 2 (the gated procedure) |
| fork a session into a new id | **this skill** (`st-transplant.py --new-session-id`, or `st-bundle.py import --new-session-id`) |
| get sessions back after a sign-in change, or move them to another account, on this machine | **session-rehome** |
| move a session to another Desktop window on this machine, or between the terminal CLI and Desktop | **session-rehome** |

**How to run the scripts.** They are in `${CLAUDE_SKILL_DIR}/scripts` (if you see that text literally, it means
the `scripts/` folder next to this SKILL.md):

    python3 "${CLAUDE_SKILL_DIR}/scripts/st-bundle.py" <command> ...          the bundle (any OS)
    python3 "${CLAUDE_SKILL_DIR}/scripts/st-transplant.py" --plan | --apply   the install step
    bash "${CLAUDE_SKILL_DIR}/scripts/st-verify.sh" ...                       the verifier (also st-preflight.sh,
                                                                              st-checkpoint.sh, st-git-rescue.sh,
                                                                              st-resync.sh)

On Windows, use `py -3` (or `python`) instead of `python3`; the `.sh` drivers need WSL or Git-Bash. Type the full
path each time: shell variables do not survive between your commands. Both machines need this skill (install the
project on each), and Python 3.9+.

## Start here

| The user says | Do |
|---|---|
| "continue this session on my other machine", "send it to the Pi", any move across OSes | **Path 1.** On the origin: `st-bundle.py list`, then `export --dry-run`, then `export`. Copy the file. On the destination: `inspect`, `import --plan`, `import --apply`, then verify |
| "my other machine has the real history" (and this machine can ssh to it) | **Path 2.** Read `references/gated-procedure.md` in full, then start with `st-preflight.sh --origin-host HOST --list-sessions` |
| "restore my session from this backup / USB disk / archive" | **Path 2** with `--origin-host local --origin-claude <archive>/.claude` |
| "fork this session" | `st-transplant.py --new-session-id <uuid>` (renames the transcript and its sidecar folder together) |
| "start fresh but keep the context" | not a transplant: a memory-corpus briefing (see "When NOT to use this skill") |
| "my project folder moved; `--resume` says No conversation found" (same machine) | not a transplant: see "When NOT to use this skill" |

Before **any** step that writes, ask the user the questions in "The user dialogue" (D1–D6).

## The core principle

> **Copy history verbatim and tell the model it moved. Never rewrite a transcript you cannot prove you can rewrite
> correctly.**

Moving a Claude Code session is not a file copy problem. The transcript is an append-only DAG whose thinking blocks
carry server-side signatures, whose sidecars resolve by filename stem, and whose location is derived from a mangled
`realpath(cwd)` with no global fallback. Everything here was measured on a **completed, working cross-host
cross-account migration** (macOS/arm64 → Linux/x86_64, different account *and* org UUIDs, 216,236,906-byte
transcript, 2,157 files, verified byte-identical). Do not re-derive the mechanics: cite them from
`references/mechanics.md`.

Three measured reasons for the principle:
1. **Per-record `$.cwd` is inert.** A control run rewrote every record's `cwd` to a different path and the session
   still ran from the launch directory, so relocating a session requires *no* transcript rewriting at all.
2. **The file is a compacted DAG**, not a transcript: 27 in-band compaction boundaries, 100 deliberately
   duplicated uuids, `logicalParentUuid` back-links. Any edit that does not preserve line order and count exactly
   breaks resume in ways no byte count detects.
3. **Thinking blocks carry server-minted signatures.** You cannot regenerate one, and a rejection is fatal,
   single-shot, no retry.

So: byte-for-byte copy, keep the filename stem, place it under `mangle(realpath(destination cwd))`, and **append**
a relocation notice instead of editing history. Tell the model twice: an appended notice record *and* a durable
`CLAUDE.md` in the destination project root, because the notice falls out of context on the next compaction and
`CLAUDE.md` is re-read every session.

**The provable property to advertise:** `sha256(first N bytes of the destination transcript) == sha256(origin
transcript)`, N = the origin size. History untouched, and it stays true as the file grows.

**Scope of the cross-account evidence.** 166/166 signed thinking blocks were replayed verbatim across an account
boundary, but that was *two accounts belonging to one user, on one origin lineage*. Cross-**org** acceptance is
unverified; treat it as likely, not established. If a signature is ever rejected, do not attempt repair
(prohibition 2): fall back to the memory-corpus briefing in "When NOT to use this skill".

## PROHIBITIONS — read before any instruction

Each of these causes loss that no later gate can undo.

1. **Never trigger the Desktop's CLI-session import, the "Recover CLI sessions" UI, or a
   `claude://resume?session=…` deep link against a real transcript.** All three call `stripThinkingBlocksFromFile`,
   which rewrites the file **in place**. Measured on the reference transcript: **6,331 of 21,859 assistant records
   deleted outright, ~6,332 severed `parentUuid` links, walk-back depth collapsed to 1.** It also reads the whole
   file into one JS string (~2 GB peak). There is no undo. Make the session visible by *stopping the target Desktop
   instance, filing the record, starting it* (`references/gated-procedure.md`, G7). To give an existing CLI
   conversation a Desktop session on the same host, use `ccd-rehome register` (session-rehome): it writes
   the record and never touches the transcript.
2. **Never strip, summarize, re-sign or synthesize thinking blocks.** Same damage as above. A fabricated
   `signature` is guaranteed-invalid and makes any API-touching result uninterpretable.
3. **Never write to the origin without the user's typed authorization.** Read-only is the default and is
   *enforced at a single chokepoint with an allowlist* (`st_ssh_check_cmd`), not by intention, and that chokepoint
   applies to `--origin-host local` too. Ship remote helpers over stdin (`ssh host 'python3 -' < helper.py`) so
   "nothing was written to the origin" is literally true. Never `rsync --delete` toward the origin. The origin is
   **never deleted**, under any answer to any question.
4. **Never run `git gc`, `git prune`, or porcelain that may auto-trigger them on a rescued repo before commit #1
   exists.** The reference origin had an unborn HEAD: 338 staged files living only as loose objects, the sole
   blob→name mapping in a 34 KB `.git/index`, all 427 objects reported dangling by `fsck`. `gc.auto=0` is the
   literal first operation. Even `git status` without `--porcelain` can rewrite `.git/index`; use
   `git --no-optional-locks status --porcelain`.
5. **Never blacklist-copy from a `~/.claude` or a Desktop user-data-dir. Whitelist only.** A single
   `--include='backups/***'` swept five copies of another account's identity blob (`machineID`, `userID`,
   `oauthAccount`), 1,068 unrelated prompts, and two unrelated sessions' task stores. Enumerate the exact paths
   belonging to the session, then run an **independent denylist assertion over the staged bytes**. See
   `references/secrets.md`.
6. **Never advance a `latest`/`current` pointer before verification passes.** v1 of the checkpoint script did, and
   a failed run became the `--link-dest` baseline for the next one. Write the `COMPLETE` sentinel last; point
   `--link-dest` at the newest generation *containing* it.
7. **Never combine `--inplace`/`--append`/`--append-verify` with `--link-dest`**, and always seal a completed
   generation `a-w`. Writing through a shared inode silently rewrites every prior generation.
8. **Never rename a transcript without renaming its sidecar directory in the same operation.** Sidecars resolve as
   `<transcript path minus .jsonl>/{subagents,tool-results,workflows}`; renaming the `.jsonl` alone orphans them
   **silently** (170 MB / 1,991 files in the reference run). `st-transplant.py --new-session-id` is the only
   supported way, and it renames both.
9. **Never blanket-`sed` a transcript.** `/Users/<origin-user>` occurred 54,157 times on 33,959 lines; ~5,705 of
   those occurrences are *not paths* (`ls -l` owner columns, git author strings, `user@host`), and ~745 are macOS
   toolchain paths with no destination equivalent.
10. **Never derive a project-dir name by editing another one.** The mangler is not injective (`/a/b`, `/a-b`,
    `/a_b`, `/a.b`, `/a b` all collapse to `-a-b`). Always compute from `realpath`; carry the literal observed
    directory name as data.
11. **Never drop a session JSON in while the target Desktop instance is running.** There is no filesystem watcher;
    the debounced writer will overwrite or delete your file. The same reasoning applies to the CLI's host-wide
    `.claude.json`: every running process can flush its own full copy over yours.
12. **Never read the whole transcript into memory.** Stream, write a new file, `os.replace`.

## Path 1 — the portable bundle (the default for any move to another machine)

Use it whenever the destination cannot ssh to the origin (the common "push from here to there" case), and for any
move between operating systems. It is the gated procedure in a file: **export packs exactly the checkpoint
whitelist; import unpacks into the checkpoint layout and runs `st-transplant.py`**, so every guarantee of path 2
still applies. Pure Python standard library: no bash, rsync or ssh needed on either side.

```bash
# ON THE ORIGIN. First find the session: nobody knows its id. `list` shows id, folder, title, opening words.
python3 "${CLAUDE_SKILL_DIR}/scripts/st-bundle.py" list
# --dry-run first: it prints the accounting and writes nothing.
python3 "${CLAUDE_SKILL_DIR}/scripts/st-bundle.py" export --session-id <SID> --project-root <DIR> \
    --exclude '/.pytest_cache/  # regenerated' [--no-memory] [--desktop-profile acct-x] -o s.csb.zip --dry-run
python3 "${CLAUDE_SKILL_DIR}/scripts/st-bundle.py" export ...same... -o s.csb.zip

# Copy s.csb.zip any way you like (scp, USB, cloud drive). Then ON THE DESTINATION:
python3 "${CLAUDE_SKILL_DIR}/scripts/st-bundle.py" inspect s.csb.zip     # every member re-hashed; refuses zip-slip / extras
python3 "${CLAUDE_SKILL_DIR}/scripts/st-bundle.py" import s.csb.zip --dest-root <DIR> [--desktop-profile default [--to EMAIL]] --plan
python3 "${CLAUDE_SKILL_DIR}/scripts/st-bundle.py" import s.csb.zip --dest-root <DIR> [...] --apply

# BACK ON THE ORIGIN: prove nothing changed there, and hand the proof to the verifier on the destination.
python3 "${CLAUDE_SKILL_DIR}/scripts/st-bundle.py" origin-proof s.csb.zip -o proof.json
bash "${CLAUDE_SKILL_DIR}/scripts/st-verify.sh" --checkpoint <staging printed by import> --dest-root <DIR> \
    --session-id <SID> --origin-proof proof.json
```

What it guarantees:
- **The transcript is a byte-exact prefix snapshot.** A half-written last line is left out, and a hash change while
  packing aborts.
- **Every member is listed with its sha256.** `inspect` and `import` refuse a modified, missing or unlisted member,
  and any path that escapes the staging dir (zip-slip).
- **Whitelist only,** the same as the checkpoint.
  - *Never packed:* credentials, `~/.claude.json`, history, `settings.json` and other sessions.
  - *Left out unless `--include-sensitive`:* project files that look like secrets (`.env`, keys, `id_*`), listed in
    the manifest.
  - *Counted and reported:* secret-looking strings *inside the transcript*, which cannot be edited (D4: rotate
    them).
- **Excludes follow the checkpoint rules:** anchored, justified, and counted.
- **Filename hazards are scanned at export:** NFC/casefold collisions and names Windows cannot store. Import refuses
  collisions on a case-insensitive destination, and invalid names on Windows.
- **The Desktop record travels as a `ccd-record/1`** (from session-rehome). On import it is **adopted**:
  filed under the signed-in account (or `--to`), with the new cwd, fields bound to the old machine dropped,
  settings kept, archived, idempotent, undoable. Without session-rehome, `st-transplant.py` writes a minimal
  record and says so.
- **The receiving CLI version is detected** and stamped into the appended notice.

After `import --apply`, the session resumes with `cd <DIR> && claude --resume <SID>`, or opens in the Desktop window
named by `--desktop-profile` (quit that window before `--apply`; start it after). D1–D6 still apply. In particular
D3 (`--no-memory`: the project memory is project-wide, so on a shared project key it holds other sessions' notes)
and D4 (the transcript's secret hits). The format is specified in `references/bundle-format.md`.

## Path 2 — the gated procedure (ssh pull, offline archive, write-back)

**Read `references/gated-procedure.md` in full before running any `st-*.sh` script.** It has the worked run, the
gate table and the details of each gate. In one screen:

| Gate | Writes live state? | Script |
|---|---|---|
| G0 discovery + preflight, G1 inventory | no | `st-preflight.sh --list-sessions`, then `st-preflight.sh ... --emit-profile` |
| G2 consent | no | the user dialogue below |
| G3 checkpoint + verify | checkpoint dir only | `st-checkpoint.sh --plan`, then `--apply` |
| G4 rescue fragile git state | local copies only | `st-git-rescue.sh --scan`, then `--work DIR --apply` |
| G5–G7 materialize, install shared assets, activate | **YES** | `st-transplant.py --plan`, then `--apply` |
| G8 semantic verify | read-only + ≤1 turn | `st-verify.sh`, then a question only the real history can answer |
| D7 write-back to the origin | the origin, with typed consent | `st-resync.sh` (dry run by default) |

## The user dialogue

Ask these before G3 (path 2) or before `export` (path 1). Present defaults; do not proceed on an unanswered D2.

- **D1 — Destination root.** The exact absolute path. It determines the mangled project key and therefore where
  the transcript must live; changing it later means redoing the install. Offer a path that mirrors the origin's
  layout as an alternative: it keeps any future path-rewrite a pure prefix swap. If `realpath` differs from the
  typed string, say so loudly rather than absorbing it silently.
- **D2 — Fate of the origin.** (A) origin authoritative, this host is a read-only mirror; (B) this host
  authoritative, which requires the user's **typed** authorization for the one write that marks the origin as
  migrated; (C) knowingly forked. State plainly: **the origin is never deleted.** (A) is the safest and is
  reversible.
- **D3 — Scope.** `minimal` (transcript only) · `session` (+ sidecars, tasks, memory) · `full` (+ project source) ·
  `everything` (requires typed confirmation; typically adds foreign-arch artifacts that cannot execute at the
  destination). Quote real byte counts from the inventory or the export dry run, not adjectives.
- **D4 — Secrets disposition.** If anything sensitive was found: keep it quarantined at the destination (0700,
  `CONTAINS_SECRETS`, never git, never archive), leave it on the origin and fetch on demand, or archive it encrypted
  to external media. Ask separately whether any credential that rides in the transcript itself should be
  **rotated**: that is the only real remediation, since the history cannot be edited. `references/secrets.md`.
- **D5 — Privileged operations.** If anything needs `sudo` or a remote password, present the four options from
  `references/secrets.md` and take the user's pick. Default: **print the exact command and let the user run it.**
  State explicitly: *I will never type, store, echo or read your password, and I will never enter it into any
  prompt.*
- **D6 — Whose account is the destination?** If it belongs to a **different person**, a 200 MB transcript of A's
  work is about to land in B's account, unredacted and uneditable. Name what it exposes (every file read, every
  command run, every prose exchange) and get an explicit yes first. This is a disclosure decision, not a technical
  one.
- **D7 — Write-back** (path 2 only): ask only when there is real local work to push. See
  `references/gated-procedure.md`.

## Decision table

| You want to… | Technique | Avoid |
|---|---|---|
| Find the session id at all | `st-bundle.py list` (here) or `st-preflight.sh --list-sessions` (over ssh): id, folder, size, time, opening words | asking the user for a uuid, or guessing a mangled dirname |
| Continue a session on another machine | the bundle (path 1); or a byte-verbatim transcript copy under `mangle(realpath(dest cwd))`, same stem, + appended notice + `CLAUDE.md` via `st-transplant.py` | rewriting `$.cwd`, renaming the file, the Desktop import path |
| Make the Desktop show a transplanted session | stop that instance → file the record (`ccd-rehome adopt`, which `st-transplant.py` calls) → start it | `claude://resume`, the Recover-CLI-sessions UI, dropping while running |
| Just check it resumes, cheaply | `st-verify.sh` (or a bare dead-port probe): decide on **transcript growth + network-layer text**, never the exit code (124 is GNU-`timeout`-only, perl's `alarm` gives 142) | spending an API turn; reading an exit code as a verdict |
| Move a project to a new directory | recompute the key from `realpath`, move the transcript **and its sidecar dir** together | editing the old directory name into a new one |
| Fork instead of migrate | `st-transplant.py --new-session-id <uuid>`: renames `.jsonl` and sidecar dir in one operation, origin left live | renaming the `.jsonl` by hand (orphans the sidecars) |
| Mirror both ways | `st-resync.sh`, dry-run default, prefix check, typed confirmation | any `--delete` toward the origin |
| Bring skills/memories/history to a new host | install skills **before** launch; `memory/` is keyed by *project*, tasks by *session* | assuming a `~/.claude` copy carries them |
| Recover "my other machine has the real history" | path 2: G0–G3 read-only checkpoint first, verify, *then* decide | touching the origin before you have a verified copy |
| Restore from an **offline archive** | path 2 with `--origin-host local --origin-claude /mnt/archive/.claude`; add `--session-only` if the working tree is gone | ssh anything; treating a missing project tree as a failure |
| Migrate **several sessions** from one host | one bundle per session; on path 2, a **separate `--checkpoint-root` per session** (or always `latest-<SID>`) | one shared `--checkpoint-root` + bare `latest` |
| Salvage uncommitted/unborn-HEAD work | `st-git-rescue.sh --scan`, then `--work DIR --apply --sensitive-list …` | `git gc`; `git status` without `--porcelain`; `--apply` on the live repo |
| Give a fresh session the context without the history | memory-corpus briefing (below) | a 200 MB transplant |

## Platform notes

**Path layout.** The CLI tree is `~/.claude` (override: `CLAUDE_CONFIG_DIR`, which also relocates `.claude.json`)
on macOS and Linux, `%USERPROFILE%\.claude` on Windows `[INFERRED]`. The Desktop user-data-dir is
`~/Library/Application Support/Claude` (macOS), `~/.config/Claude` (Linux), `%APPDATA%\Claude` (Windows)
`[INFERRED]`, overridden by `--user-data-dir`. **The transcript lives under plain `~/.claude`, not the
user-data-dir**, so every Desktop instance on a host shares transcripts, skills, plugins and memory; separate
user-data-dirs give process isolation, not account isolation. Full templates: `references/mechanics.md`.

**Windows is documented, not verified.** Nothing has run on a real Windows host yet.
- **The bundle path is pure Python** (`st-bundle.py` → `st-transplant.py`). `st-transplant.py` falls back to a
  Python copy with rsync's exact contract (`ST_NO_RSYNC=1` forces it, and the self-test uses it), reads the tail
  without `tail`, and asks session-rehome whether Desktop is running when `ps` is absent.
- **The checkpoint, verify and resync drivers** are POSIX bash + `python3` stdlib, verified on macOS and Linux in
  both roles. The Windows-specific crashes (`os.statvfs`, `os.uname`) are guarded so they degrade rather than
  abort, but how the mangler treats `C:\Users\x` (drive letter and backslashes → dashes) is **untested**. Run the
  drivers under WSL or Git-Bash, and verify before relying on any of it.

**Mangler input.** Always `realpath(launch cwd)`: symlinked roots resolve through, and the alias path is never
consulted even when its directory exists. For a destination that does not exist yet, resolve the **deepest
existing ancestor** and re-join the remainder; that is what the CLI computes once the directory is created. Never
`$PWD` or `pwd -L`.

**Leading dashes.** Every project key begins with `-` (the mangler maps the leading `/` of an absolute path to a
dash). Pass such values as `--origin-key=<KEY>`, never `--origin-key <KEY>`: argparse reads a leading-dash value as
the next option.

**Filename hazards, and which direction they bite.** ext4 is case-**sensitive** and stores NFC; APFS (default) is
case-**insensitive** and normalizes toward NFD. The scan folds **case and Unicode normalisation together** (folding
on `.lower()` alone reports 0 collisions for exactly the NFC/NFD pair that merges), and runs on the **origin
side, before the transfer**: on a case-insensitive destination the two names have already merged by the time you
could scan the copy. Severity is decided by the **destination filesystem**, measured not assumed: collisions
landing on a case-insensitive filesystem are FATAL in either direction (`Foo.md` and `foo.md` merge, one file's
content is destroyed, and **rsync reports success**); on a case-sensitive one they are a warning that becomes fatal
on any later move to a case-insensitive one, including a write-back to a macOS origin.

**macOS-origin quirks** (path 2): no GNU `timeout` (use `perl -e 'alarm N; exec @ARGV'`, whose SIGALRM exit is
142, not 124); `stat -f` not `-c`; BSD `find` rejects `-newermt @epoch`; BSD `grep` has no `\b`; the system `rsync`
is **openrsync**, which lacks `-H -X -A -S --iconv --fake-super --protect-args --ignore-missing-args` but has
`--link-dest --checksum --itemize-changes --numeric-ids --partial -n`. Drop `.DS_Store` everywhere. Remote helper
scripts go over stdin and must fit the remote Python's stdlib.

## When NOT to use this skill

If the user wants a *fresh session that knows the context*, transplanting is the wrong tool. A **memory-corpus
briefing** is cheaper, safer and usually better: copy `projects/<KEY>/memory/*.md` (the reference corpus was 24
files / 399 KB and the highest value per byte in the entire tree) plus `tasks/<SID>/` (which carries the live
agenda: the reference store was 141 completed / 8 pending / 3 in-progress), write a `CLAUDE.md`, and start clean.
No signed thinking blocks, no 200 MB file, no account coupling, no prohibitions to trip over. Reach for the full
transplant only when the user needs **the actual conversation**: the ability to walk back through what was tried
and rejected, or to resume mid-task with the model's own reasoning intact. This is also the fallback if a thinking
signature is ever rejected.

Also out of scope:
- a session that is merely *running in the wrong directory* on the same host: recompute the key and move the
  transcript and its sidecar dir together; no checkpoint needed;
- anything asking for the history to be *edited*;
- a Desktop window that was signed in to a different account and now shows no sessions, a move between Desktop
  windows, or CLI ↔ Desktop on one machine: use **session-rehome**. It moves only the small
  `claude-code-sessions/<account>/<org>/` records; transcripts never move.

If a path rewrite is genuinely wanted, the acceptance test is **invertibility**: apply the inverse map and assert
`sha256(inverse(rewritten)) == sha256(original)`, no exceptions, and a rule is admissible only if its target string
occurs **zero** times in the input.

## Maintaining this skill (agents: this is part of the job)

There is **one** copy of this skill: the project at https://github.com/kulogix/session-rehome. A local
install is normally a link to a clone of it, so the folder you are reading may be inside that clone
(`git -C "${CLAUDE_SKILL_DIR}" rev-parse --show-toplevel` names it). Fix it **there**: never copy a script
elsewhere to patch it, never write a variant, never hand-move files around a refusal. If the skill is not inside
a git checkout (a copy or plugin install), tell the user, and suggest cloning the project and installing from it,
so the fix is not stranded.

The rules for changing it are the same ones it enforces:
- A new claim needs an **experiment**, not an argument. Tag it `[M]` measured, `[C]` code-lifted, `[D]` derived,
  `[I]` inferred, and say which run established it.
- A new guard is only real if it is **executable**. If it cannot be a refusal in a script, it is a note, and notes
  do not stop anyone.
- Any new gate must state what happens when it **cannot run**, and that state must count as a failure, never as a
  pass.
- **Test first:** add the failing check to `scripts/selftest.py`, make it pass, then break the fix on purpose and
  watch the check fail. Run `python3 -I scripts/selftest.py`, then the whole project's `python3 tests/run_all.py`.
- Update the docs in the same change (this file, the `references/`, the project's `docs/`), and record in the
  project's `CHANGELOG.md` what you changed, what you *tested* and what you did not. The honest "not tested" list
  is the most useful part of it.
- **Offer** the user to share the fix upstream as a pull request (the project's CONTRIBUTING.md). Push only with
  their go-ahead, and never include their paths, hosts or ids. Add a `tested.json` entry once it ran for real.

## References and scripts

- `references/gated-procedure.md`: path 2 in full (worked run, G0–G8, write-back, archives, several sessions).
- `references/bundle-format.md`: the `claude-session-bundle/1` format and the `st-origin-proof/1` proof.
- `references/mechanics.md`: the three-layer storage model with exact path templates per OS; the mangler with a
  reference implementation and its collision properties; resume resolution (cwd-scoping, realpath, worktrees,
  `--resume <path>.jsonl`); what is inert vs load-bearing; sidecar resolution; memory and tasks keying; compaction
  and what reaches the wire; version skew; and the **zero-token measurement techniques** (dead-port probe,
  recording mock API) that made all of this safe to establish.
- `references/integrity.md`: coverage vs fidelity as separate gates; the remote/local manifest diff; checkpoint
  generations, `--link-dest` and sealing; publish-only-on-success; filename hazards and the detection script;
  torn-read detection on a live transcript; fragile-git rescue including the stale-index trap; the
  origin-unchanged proof; rollback per gate.
- `references/secrets.md`: the NEVER-COPY list and what each file contains; why whitelisting is mandatory;
  remediation after over-collection; project-side secrets and the `.gitignore`-before-`git add -A` rule; the
  assistant's own conduct rules; the four options for privileged remote operations.
- `references/lessons.md`: the frank post-mortem: M1–M8 with real numbers, the near-miss that a green verification
  did not catch, what went right and should be repeated, and the subagent constraints-block template (an unstated
  containment constraint **will** be violated: one subagent told "install Rust without sudo" put 1.6 GB in
  `$HOME`).
- `references/evidence-base.md`: the source migration's distilled evidence, shipped as a historical record. Its
  paths and identifiers name **that** run, not yours; consult it when a claim made elsewhere here is disputed.
- `scripts/README.md`: what each script refuses to do, and why. `scripts/askpass-setup.md`: the four options for a
  privileged remote operation.
- `scripts/st-bundle.py`: list / export / inspect / import / origin-proof. `scripts/st-transplant.py`: the install
  step (G5–G7). `scripts/st-preflight.sh` (G0/G1), `scripts/st-checkpoint.sh` (G3), `scripts/st-git-rescue.sh`
  (G4), `scripts/st-verify.sh` (G8), `scripts/st-resync.sh` (write-back). Helpers: `scripts/st-common.sh`,
  `scripts/st_walk.py`, `scripts/st_origin_probe.py`, `scripts/st_mock_api.py`. Templates:
  `scripts/excludes.example`, `scripts/profile.example`.
- `scripts/mangle.py`: the canonical mangler, derived from the CLI binary, 22/22 against observations. **Losing it
  means re-deriving the mangler before any transplant can be preflighted.**
- `scripts/selftest.py`: a synthetic two-machine test of the bundle path and the transplant / verify options
  (mutation-tested). Run it after any change.
- `tested.json`: the combinations that passed, per side (export / import).
- **Companion:** session-rehome (`ccd-rehome export-record` / `adopt`) owns Desktop-record knowledge.
  Install it next to this skill (or set `ST_REHOME`). Never re-implement record handling here.
- Human guides (installing on a new machine, moving a session step by step on each OS, troubleshooting): the
  project's `docs/` folder, https://github.com/kulogix/session-rehome/tree/main/docs.
