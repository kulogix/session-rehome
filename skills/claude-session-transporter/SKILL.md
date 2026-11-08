---
name: claude-session-transporter
description: >-
  Migrate, transplant, clone, fork, mirror or rescue a Claude Code session, project and
  history across machines or accounts — "take over this session on another computer", "move
  my work from my Mac to this Linux box", "continue this conversation on my other laptop",
  "resume someone else's session", "my other machine has the real history", "copy my
  ~/.claude / skills / memories to this host", "re-sync my changes back to the origin",
  "why does --resume say No conversation found". Use for anything touching Claude Code /
  Claude Desktop session storage: the `~/.claude` tree, `projects/<mangled-cwd>/
  <sessionId>.jsonl` transcripts and their subagent/tool-result/workflow sidecars, the
  `memory/` corpus, the `tasks/` todo store, the Desktop's `claude-code-sessions/
  <accountUuid>/<orgUuid>/local_*.json` metadata, cross-account and cross-org moves,
  changing a project's directory (which changes its transcript key), recovering a session
  whose project dir was renamed, restoring from an offline archive, packing a session into ONE
  portable verified file ("bundle this session", "send this session to my other machine", "push this
  session to the Pi") and installing it on any OS, or auditing what in a `~/.claude` is safe to copy.
  Verified on macOS and Linux, in both roles and across them (bundle round trip Linux x86_64 →
  macOS arm64 and Linux aarch64, each loaded by that host's own CLI); Windows: the bundle path is
  pure Python, untested on a real Windows host. Includes the read-only checkpoint/verify protocol, the secrets
  whitelist, and the write-back-to-origin path. Prefer this over ad-hoc `rsync ~/.claude`,
  over the Desktop's "Recover CLI sessions" UI, and over any transcript rewriting.
---

# Session transporter

Moving a Claude Code session is not a file copy problem. The transcript is an append-only
DAG whose thinking blocks carry server-side signatures, whose sidecars resolve by filename
stem, and whose location is derived from a mangled `realpath(cwd)` with no global fallback.
Everything here was measured on a **completed, working cross-host cross-account migration**
(macOS/arm64 → Linux/x86_64, different account *and* org UUIDs, 216,236,906-byte
transcript, 2,157 files, verified byte-identical). Do not re-derive the mechanics — cite
them from `references/mechanics.md`.

## The core principle

> **Copy history verbatim and tell the model it moved. Never rewrite a transcript you
> cannot prove you can rewrite correctly.**

Three measured reasons. (1) Per-record `$.cwd` is **inert** — a control run rewrote every
record's `cwd` to a different path and the session still ran from the launch directory, so
relocating a session requires *no* transcript rewriting at all. (2) The file is not a
transcript, it is a **compacted DAG**: 27 in-band compaction boundaries, 100 deliberately
duplicated uuids, `logicalParentUuid` back-links — any edit that does not preserve line
order and count exactly breaks resume in ways no byte count detects. (3) Thinking blocks
carry **server-minted signatures**; you cannot regenerate one, and a rejection is fatal,
single-shot, no retry. So: byte-for-byte copy, keep the filename stem, place it under
`mangle(realpath(destination cwd))`, and **append** a relocation notice instead of editing
history. Tell the model twice — an appended notice record *and* a durable `CLAUDE.md` in
the destination project root, because the notice falls out of context on the next
compaction and `CLAUDE.md` is re-read every session.

**The provable property to advertise:** `sha256(first N bytes of the destination
transcript) == sha256(origin transcript)`, N = the origin size. History untouched, and it
stays true as the file grows.

**Scope of the cross-account evidence.** 166/166 signed thinking blocks were replayed
verbatim across an account boundary — but that was *two accounts belonging to one user, on
one origin lineage*. Cross-**org** acceptance is unverified; treat it as likely, not
established. If a signature is ever rejected, do not attempt repair (prohibition 2): fall
back to the memory-corpus briefing in "When NOT to use this skill".

## PROHIBITIONS — read before any instruction

Each of these causes loss that no later gate can undo.

1. **Never trigger the Desktop's CLI-session import, the "Recover CLI sessions" UI, or a
   `claude://resume?session=…` deep link against a real transcript.** All three call
   `stripThinkingBlocksFromFile`, which rewrites the file **in place**. Measured on the
   reference transcript: **6,331 of 21,859 assistant records deleted outright, ~6,332
   severed `parentUuid` links, walk-back depth collapsed to 1.** It also reads the whole
   file into one JS string (~2 GB peak). There is no undo. Make the session visible by
   *stopping the target Desktop instance, dropping the file, starting it* (§G7).
   To give an existing CLI conversation a Desktop session on the same host, use
   `ccd-rehome register` (claude-desktop-rehome): it writes the record and never touches the transcript.
2. **Never strip, summarize, re-sign or synthesize thinking blocks.** Same damage as above.
   A fabricated `signature` is guaranteed-invalid and makes any API-touching result
   uninterpretable.
3. **Never write to the origin without the user's typed authorization.** Read-only is the
   default and is *enforced at a single chokepoint with an allowlist* (`st_ssh_check_cmd`),
   not by intention — and that chokepoint applies to `--origin-host local` too. Ship remote
   helpers over stdin (`ssh host 'python3 -' < helper.py`) so "nothing was written to the
   origin" is literally true. Never `rsync --delete` toward the origin. The origin is
   **never deleted**, under any answer to any question.
4. **Never run `git gc`, `git prune`, or porcelain that may auto-trigger them on a rescued
   repo before commit #1 exists.** The reference origin had an unborn HEAD: 338 staged files
   living only as loose objects, the sole blob→name mapping in a 34 KB `.git/index`, all 427
   objects reported dangling by `fsck`. `gc.auto=0` is the literal first operation. Even
   `git status` without `--porcelain` can rewrite `.git/index`; use
   `git --no-optional-locks status --porcelain`.
5. **Never blacklist-copy from a `~/.claude` or a Desktop user-data-dir. Whitelist only.**
   A single `--include='backups/***'` swept five copies of another account's identity blob
   (`machineID`, `userID`, `oauthAccount`), 1,068 unrelated prompts, and two unrelated
   sessions' task stores. Enumerate the exact paths belonging to the session, then run an
   **independent denylist assertion over the staged bytes**. See `references/secrets.md`.
6. **Never advance a `latest`/`current` pointer before verification passes.** v1 of the
   checkpoint script did, and a failed run became the `--link-dest` baseline for the next
   one. Write the `COMPLETE` sentinel last; point `--link-dest` at the newest generation
   *containing* it.
7. **Never combine `--inplace`/`--append`/`--append-verify` with `--link-dest`**, and always
   seal a completed generation `a-w`. Writing through a shared inode silently rewrites every
   prior generation.
8. **Never rename a transcript without renaming its sidecar directory in the same
   operation.** Sidecars resolve as `<transcript path minus .jsonl>/{subagents,tool-results,
   workflows}`; renaming the `.jsonl` alone orphans them **silently** — 170 MB / 1,991 files
   in the reference run. `st-transplant.py --new-session-id` is the only supported way, and
   it renames both.
9. **Never blanket-`sed` a transcript.** `/Users/<origin-user>` occurred 54,157 times on
   33,959 lines; ~5,705 of those occurrences are *not paths* (`ls -l` owner columns, git
   author strings, `user@host`), and ~745 are macOS toolchain paths with no destination
   equivalent.
10. **Never derive a project-dir name by editing another one.** The mangler is not
    injective (`/a/b`, `/a-b`, `/a_b`, `/a.b`, `/a b` all collapse to `-a-b`). Always
    compute from `realpath`; carry the literal observed directory name as data.
11. **Never drop a session JSON in while the target Desktop instance is running.** There is
    no filesystem watcher; the debounced writer will overwrite or delete your file. The same
    reasoning applies to the CLI's host-wide `.claude.json`: every running process can flush
    its own full copy over yours.
12. **Never read the whole transcript into memory.** Stream, write a new file, `os.replace`.

## A worked run

Six commands. Everything else in this file explains why each one refuses what it refuses.
`--profile` carries the values so you type them once; **command-line flags always override
the profile**.

```bash
SK=~/.claude/skills/claude-session-transporter/scripts

# 0. DISCOVERY — you do not know the session id. Nobody does; it is a uuid inside a
#    directory whose name the mangler makes unguessable.
"$SK/st-preflight.sh" --origin-host mymac --list-sessions

# 1. G0/G1 PREFLIGHT — writes nothing. Emits a profile with everything it discovered.
"$SK/st-preflight.sh" \
    --origin-host mymac \
    --origin-root  /Users/me/Projects/thing \
    --session-id   <the id from step 0> \
    --dest-root    /home/me/Projects/thing \
    --checkpoint-root /home/me/checkpoints \
    --hazards --emit-profile ./mig.conf --report ./preflight.txt

# 2. G2 CONSENT — ask D1–D6 below, in chat, and record the answers. Then:

# 3. G3 CHECKPOINT — --plan first (accounting only), then --apply.
"$SK/st-checkpoint.sh" --profile ./mig.conf --exclude-file ./excludes.txt --plan
"$SK/st-checkpoint.sh" --profile ./mig.conf --exclude-file ./excludes.txt --apply

# 4. G4 RESCUE fragile git state, on a COPY (never on the origin).
"$SK/st-git-rescue.sh" --scan /home/me/checkpoints/latest-<SID>/project
"$SK/st-git-rescue.sh" --repo /home/me/checkpoints/latest-<SID>/project/thing \
    --work /home/me/rescue/thing --apply \
    --sensitive-list /home/me/checkpoints/latest-<SID>/manifest/SENSITIVE.txt

# 5. G5–G7 TRANSPLANT — --plan first, then --apply. st-transplant.py has no --profile:
#    it reads the same ST_* names from the ENVIRONMENT, so export them once.
set -a; . ./mig.conf; set +a
python3 "$SK/st-transplant.py" --plan
python3 "$SK/st-transplant.py" --apply --skill <name> --skill <name>

#    Desktop only: add --user-data-dir/--account/--org (or set them in mig.conf).
#    A CLI-only migration is complete without them.

# 6. G8 VERIFY — then ask the semantic question yourself.
"$SK/st-verify.sh" --profile ./mig.conf --checkpoint "$ST_CKPT"
```

Every `st-*.sh` takes `--profile`; `st-transplant.py` reads the same `ST_*` names from the
environment instead. Use `latest-<SID>`, not bare `latest`: one checkpoint root shared by
several migrated sessions leaves `latest` naming only the last of them — which is why
`--emit-profile` writes `ST_CKPT=$ST_CKPT_ROOT/latest-$ST_SESSION_ID`.

## The portable bundle (push, cross-OS, offline): `st-bundle.py`

Use it whenever the destination cannot ssh to the origin, which is the common "push from here to
there" case, and for any move between operating systems. It is the same procedure in a file:
**export packs exactly the checkpoint whitelist; import unpacks into the checkpoint layout and runs
`st-transplant.py`**, so every gate above still applies. Pure Python stdlib: no bash, no rsync, no
ssh needed on either side.

```bash
SK=~/.claude/skills/claude-session-transporter/scripts
# ON THE ORIGIN. --dry-run first: it prints the accounting and writes nothing.
python3 "$SK/st-bundle.py" export --session-id <SID> --project-root <DIR> \
    --exclude '/.pytest_cache/  # regenerated' [--no-memory] [--desktop-profile acct-x] -o s.csb.zip --dry-run
python3 "$SK/st-bundle.py" export ...same... -o s.csb.zip
# copy s.csb.zip any way you like (scp, USB, cloud drive). Then ON THE DESTINATION:
python3 "$SK/st-bundle.py" inspect s.csb.zip              # every member re-hashed; refuses zip-slip / extras
python3 "$SK/st-bundle.py" import s.csb.zip --dest-root <DIR> [--desktop-profile default [--to EMAIL]] --plan
python3 "$SK/st-bundle.py" import s.csb.zip --dest-root <DIR> [...] --apply
# BACK ON THE ORIGIN: prove nothing changed there, and hand the proof to st-verify on the destination
python3 "$SK/st-bundle.py" origin-proof s.csb.zip -o proof.json
bash "$SK/st-verify.sh" --checkpoint <staging printed by import> --dest-root <DIR> --session-id <SID> \
    --origin-proof proof.json
```

What it guarantees:
- **The transcript is a byte-exact prefix snapshot.** A half-written last line is left out, and a
  hash change while packing aborts.
- **Every member is listed with its sha256.** `inspect` and `import` refuse a modified, missing or
  unlisted member, and any path that escapes the staging dir (zip-slip).
- **Whitelist only,** the same as the checkpoint.
  - *Never packed:* credentials, `~/.claude.json`, history, `settings.json` and other sessions.
  - *Left out unless `--include-sensitive`:* project files that look like secrets (`.env`, keys,
    `id_*`), listed in the manifest.
  - *Counted and reported:* secret-looking strings *inside the transcript*, which cannot be edited
    (D4: rotate them).
- **Excludes follow the checkpoint rules:** anchored, justified, and counted.
- **Filename hazards are scanned at export:** NFC/casefold collisions and names Windows cannot
  store. Import refuses collisions on a case-insensitive destination, and invalid names on Windows.
- **The Desktop record travels as a `ccd-record/1`** (from claude-desktop-rehome). On import it is
  **adopted**: filed under the signed-in account (or `--to`), with the new cwd, fields bound to the
  old machine dropped, settings kept, archived, idempotent, undoable. Without claude-desktop-rehome,
  st-transplant.py writes a minimal record and says so.
- **The receiving CLI version is detected** and stamped into the appended notice.

D1–D6 still apply. In particular D3 (`--no-memory`: the project memory is project-wide, so on a
shared project key it holds other sessions' notes) and D4 (the transcript's secret hits).

## The gated procedure

`G0–G3` write **nothing outside the checkpoint directory** — they are free to run, free to
abort, and free to re-run. `G4` writes only local copies. `G5–G7` touch live destination
state. Nothing in any gate writes to the origin except the optional resync path.

| Gate | Writes live state? | Script and verb | Pass criterion | Rollback cost |
|---|---|---|---|---|
| **G0 discovery + preflight** | no | `st-preflight.sh --list-sessions`, then plain | origin reachable, session located, versions and headroom known, destination key computed | free |
| **G1 inventory** | no | `st-preflight.sh` (same run) | every byte to be moved is enumerated by category with counts | free |
| **G2 consent** | no | dialogue (below) | user answered D1–D5; answers recorded | free |
| **G3 checkpoint + verify** | no (checkpoint dir only) | `st-checkpoint.sh --plan` then `--apply` | coverage, fidelity and unexpected-files reported as **three separate gates**, remote manifest vs local manifest | free — delete the dir |
| **G4 rescue fragile state** | local copies only | `st-git-rescue.sh --scan`, then `--work DIR --apply` | `gc.auto=0` set first; every staged blob resolves; index commit; bundle + bare mirror verify | free |
| **G5 materialize destination** | **YES** | `st-transplant.py --plan` then `--apply` | prefix hash == origin hash; sidecar/memory/tasks counts ≥ checkpoint | delete dest tree + dest transcript |
| **G6 install shared assets** | **YES** | `st-transplant.py --apply` (asset phase) | skills present **at the destination path**, asserted there, not in the checkpoint; receipt written | remove installed assets |
| **G7 activate** | **YES** | `st-transplant.py --apply` (session mint) + launch | **CLI-only:** `cd <dest> && claude --resume=<SID>` loads. **Desktop:** instance stopped → JSON dropped → instance started → session listed and opens | delete the session JSON |
| **G8 semantic verify** | read-only + ≤1 turn | `st-verify.sh` | every check green **and** the resumed session answers a question only the real history can answer | nothing |

### G0 — discovery and preflight (writes nothing)

**Step 0 is `--list-sessions`.** It prints, per transcript, the session id, project key,
size, mtime and the opening words of the first user message — the only thing that lets a
human say "that one". Do not ask the user for a uuid they cannot know.

Then: reachability and RTT; free space **on both sides** (the reference origin had 38 GiB
free of 3.6 TiB — a hard design constraint); CLI version on the destination (**record it**;
`--emit-profile` writes it as `ST_CLI_VERSION` and `st-transplant.py --cli-version` stamps
it into any appended record); `realpath` of the proposed destination root and the mangled
key it produces; whether that key already exists locally; whether the destination
filesystem is case-insensitive; whether the destination root is already a git repo.

Capture an **origin fingerprint** now — `mtime + size + mode + inode + name`, sorted and
hashed, `atime` excluded by construction, `ctime` captured as a second advisory
fingerprint. Capture `pre` as well as `post`; a post-only fingerprint proves nothing.

If several project keys hold the session (git worktrees do this legitimately), preflight
**fails** rather than picking the alphabetically first. Resolve it with `--origin-key`, or
take them all with `st-checkpoint.sh --all-transcript-keys`.

### G1 — inventory (writes nothing)

Recurse the session's roots **fully** — a `-maxdepth 1` sweep misses `subagents/workflows/`,
which was **38% of all bytes**. Expect these categories (reference-run numbers, for shape,
not for equality — a short session legitimately has none of rows 2–8):

| Component | Path pattern | Reference |
|---|---|---|
| main transcript | `projects/<KEY>/<SID>.jsonl` | 216,236,906 B — 55.8% of the session |
| subagent transcripts + meta | `projects/<KEY>/<SID>/subagents/agent-*.{jsonl,meta.json}` | 51 agents |
| **workflow agents** | `…/subagents/workflows/wf_<runId>/…` | 1,765 files, 148 MB |
| tool-result overflow blobs | `…/<SID>/tool-results/<9char>.txt` | 11 files |
| workflow runs + scripts | `…/<SID>/workflows/{wf_*.json,scripts/*.js}` | 113 files |
| **sibling project keys** | `projects/<KEY><suffix>/<SID>/…` | 9 files — *easily missed* |
| task/todo store | `tasks/<SID>/` | 154 entries |
| **project memory** | `projects/<KEY>/memory/*.md` | 24 files — **highest value per byte in the tree** |
| shared assets | `skills/`, `agents/`, `commands/`, `output-styles/`, `settings.json`, `~/.claude/CLAUDE.md` | project-independent; see G6 |

A `.jsonl`-only copy loses **44% of bytes and 100% of subagent conversation content**.
Sub-agents are **not** reconstructable from the main transcript — only 16 of 51 `toolUseId`s
appear there. Enumerate the directory.

`agents/`, `commands/`, `output-styles/` and `~/.claude/CLAUDE.md` are startup-enumerated
and host-shared. They are **inventoried always and copied only on request**
(`--include-agents`, `--include-commands`, `--include-output-styles`,
`--include-user-memory`) — `~/.claude/CLAUDE.md` in particular applies to every project on
the host and usually names the origin's absolute paths, so it is copy-with-review.

Also run the **filename hazard scan** here (`--hazards`) — see Platform notes.

### G2 — consent (writes nothing)

Ask D1–D6 below, record the answers, then state the scope in bytes and files before
proceeding. Do not begin G3 with an unanswered D2 (origin fate).

### G3 — checkpoint and verify (writes only inside the checkpoint dir)

`st-checkpoint.sh --plan`, then `--apply`. Non-negotiable properties, each of which exists
because it was learned the hard way:

- **Every exclude is anchored and justified**, and printed with a **per-pattern match
  count**. An over-broad pattern must surface as a *number*, never as silence.
  `--exclude='_research/re/rust/'` dropped 26 files including the project's keystone source
  file; `target/` was assumed to be build output and was actually the ground-truth binary
  drop dir. **Never pattern-match on a directory name.** An unanchored pattern must be
  written `unanchored:PAT  # why`; there is no flag that turns the justification off.
- **The remote manifest is built first and independently.** Verification diffs a
  **remote-side** manifest against a **local-side** manifest, produced by the same walker
  shipped over stdin. Hashing the local copy and comparing it to itself is not verification.
- **Coverage, fidelity and unexpected-files are three separate gates.** A corpus can be 100%
  faithful and 60% complete. Unexpected files are a gate too, not an INFO line: the manifest
  uses one exclude engine and the transfer uses rsync's, and a divergence means
  over-collection passing green.
- **Symlinks are manifest rows,** not skipped oddities. A blind spot shared by the oracle
  and the copy is not a gate.
- **The whitelist entries that do not exist on the origin are skipped, not failed.** A short
  session has no `memory/`, no `tasks/<SID>/` and no sidecar dir; four rsync exit-23s used
  to turn a perfectly good checkpoint into an unrecoverable refusal.
- **The transcript uses the prefix invariant**, not whole-file equality:
  `sha256(remote[0:L]) == sha256(local[0:L]), L <= R`. JSONL is append-only.
- **Whitelist for the `~/.claude` side** + an independent denylist assertion over the staged
  bytes (`references/secrets.md`), with deliberately-copied shared assets exempted so the
  gate does not cry wolf.
- **Seal `a-w`, then publish.** `COMPLETE` sentinel last, then relative `latest` and
  `latest-<SID>` symlinks.

### G4 — rescue fragile state (local copies only)

Anything that has exactly one copy and no history: an unborn-HEAD git repo, uncommitted
work, a `.git/index` that is the only blob→name map. `gc.auto=0` **first**. Then verify
every staged blob resolves, and commit the index.

`--apply` requires `--work DIR` (rescue on a copy). `--in-place` exists, demands a typed
confirmation, and refuses when the repo is under `ST_ORIGIN_ROOT`.

**The index may be stale relative to the working tree** — the reference run's second commit
added 26 files and modified 6, including an entire required crate, that an index-only
rescue would have lost. For an **unborn-HEAD** repo the drift commit is the rescue. For a
repo with **real history** it is not: `git add -A` onto a branch with an upstream diverges
it and destroys a curated staging set, so the script writes `drift.patch` + `untracked.txt`
instead and says so. Pass `--sensitive-list <checkpoint>/manifest/SENSITIVE.txt`: a commit
propagates a private key into the bundle *and* the bare mirror. Details:
`references/integrity.md`.

### G5 — materialize the destination (first gate that touches live state)

Order matters and every step is idempotent and re-runnable:

1. `rsync -a --no-perms --chmod=u+rwX,go-w` the project tree out of the sealed checkpoint —
   plain `-a` propagates the checkpoint's read-only mode into the working tree. **Files at
   the destination whose content differs from the checkpoint are counted and refused**
   (`--overwrite-destination-work` overrides and backs them up under `.st-overwritten/<ts>/`):
   rsync's quick check is size+mtime and the checkpoint is always older, so without that gate
   every re-run silently reverts destination work and reports OK. If the destination root is
   already a git repo, `.git/` is **excluded** unless `--merge-git` — overwriting refs
   orphans destination-only commits *and* clobbers the reflog that would recover them.
2. Copy the transcript to `<claude-home>/projects/<mangle(realpath(dest root))>/<SID>.jsonl`,
   **same filename stem**, `chmod 0600` after copying, assert byte-identity. The key is
   computed by resolving the **deepest existing ancestor** and re-joining the remainder, then
   re-asserted after `mkdir` — a destination behind a symlinked parent otherwise lands under
   a key the CLI will never look in.
3. **Append** the relocation notice as a `type:"user"` record whose `parentUuid` is the last
   record that *has* a uuid (tail-scan backwards). Re-assert the prefix hash after appending.
   Content: origin and destination host/user/account, an explicit **old→new path table**, and
   the consequences — that tens of thousands of lines reference origin paths as *historical
   record, not live locations*; that old scripts hold hardcoded origin paths so a path failure
   is *expected, not surprising*; and whether the origin is reachable and on what terms.
4. Optionally append one `{"type":"relocated","sessionId":"<in-record sessionId>",
   "relocatedCwd":"<existing abs path>"}` line. It is **not honored on `--resume`** (only the
   in-REPL `/resume` picker) — free to add, never to rely on. It must land within the last
   64 KiB.
5. Sidecars, `memory/`, `tasks/<SID>/`, and **the sibling project keys'
   `<SID>/workflows/scripts/` and `memory/`**. Assert counts against G1: `destination <
   checkpoint` is the failure; `destination > checkpoint` is a session that has been used.
6. Write the durable `CLAUDE.md` in the destination project root, between **session-scoped**
   markers so migrating a second session into the same root does not delete the first one's
   path table.

An existing destination transcript is never deleted. If its first N bytes match the
checkpoint it is a **resumed session** and is left alone; anything else is renamed to
`<SID>.jsonl.st-displaced-<ts>` and only with `--allow-existing`.

Note `tool-results/` **decays** — the destination CLI's own retention sweeper pruned one blob
between transplant and first launch. A decrease there is a warning, not a failure.

### G6 — install shared assets (a gate, not a footnote)

Skills, agents, commands and the mergeable `settings.json` keys are **shared across every
instance on the host** — they live under plain `~/.claude`, not the user-data-dir. Two
measured constraints:

- **Skills are enumerated at CLI process startup and cached for the process lifetime.** A
  skill added mid-session does not appear in the next turn's system prompt. **Install before
  launching the destination.**
- **"Backed up" is not "installed."** In the reference run skills and plugins were copied
  into the checkpoint and never installed, and the gap was invisible because the backup
  looked complete. Assert presence **at the destination path**; `st-transplant.py` writes
  `<dest root>/.st-receipt.json` so `st-verify.sh` checks what was *meant* to be installed
  rather than everything the checkpoint happens to hold.

Whitelist skills by **name**: one skill in the reference corpus was 321 MB of `.venv` with
two bundled Node runtimes. Audit anything executable for `#!/bin/zsh`, `brew`, `otool`,
`codesign` and foreign-arch binaries before copying. A destination skill of the same name is
**never replaced without `--overwrite-skill`**, and is backed up when it is.
**Regenerate plugins, do not copy them** — they carry absolute `installPath` and native-arch
payloads. Origin `settings.json` keys that are *not* merged are listed as a warning: if the
session depended on `hooks`, `permissions` or `env`, copy them deliberately.

### G7 — activate

1. Assert the target Desktop instance is **not running**:
   `ps -eo pid,comm,args | awk '$2 ~ /claude|electron/ && index($0, "<dir>")'`.
   **Never `pgrep -af '<pattern>'`** — it self-matches the checking shell (2 false positives
   measured). **Never `pkill -f`** — it self-matched and killed a run mid-experiment.
   `--force` lets steps 1–6 proceed; it never permits the session mint.
2. Workspace trust: the app shows its dialog once and accepting it there is the safe path.
   `--trust` writes `projects["<dest root>"].hasTrustDialogAccepted = true` into the CLI's
   host-wide config — it is **off by default** and refuses while any claude process runs.
3. Mint the Desktop session JSON at
   `<user-data-dir>/claude-code-sessions/<accountUuid>/<orgUuid>/local_<uuid4>.json`.
   **Filename must equal the `sessionId` field** or the app rewrites it and leaves a
   permanent ghost that reloads every launch. Mode 0600, **every** directory level 0700,
   < 10 MiB. Required keys: `sessionId`, `cwd`, `cliSessionId` (missing ⇒ treated as
   never-started). **Do not write a `model` key** unless the user names one: model
   availability is account- and plan-scoped, and a hardcoded id produces a session the
   destination account cannot start, whose failure looks like a transplant failure. Wrong
   `<accountUuid>/<orgUuid>` is not a soft failure: the file is never read, *and* it
   suppresses its own transcript from the current account's recovery UI. Template and full
   key table: `references/mechanics.md`.
4. Start the instance **the way the user normally starts it**. The Desktop launcher's
   binary name is platform- and install-specific (AppImage, `.desktop` entry, bundle) and
   is **not** something this skill can assume — ask, or let the user do it.
5. **The CLI-direct path is a complete alternative on its own:**
   `cd <dest root> && claude --resume=<SID>`. Use it as the cheap smoke test before the
   Desktop, and as the whole of G7 for a CLI-only migration.

Note: absence of `claude-code-sessions/` means "no session yet", **not** "not signed in" —
check the user-data-dir's `config.json` for `oauth:tokenCache` and `lastKnownAccountUuid`
(without reading their values).

### G8 — semantic verify

Loaded ≠ faithful, and byte counts cannot tell the difference. `st-verify.sh` checks prefix
byte-identity, destination-tree coverage, sidecar/memory counts, session registration,
shared assets installed at the destination, the origin fingerprint, and runs a **dead-port
load probe** costing zero API turns against an isolated `CLAUDE_CONFIG_DIR` so the live
transcript is not appended to.

**Then ask the resumed session a question only the real history can answer** — a specific
artifact and tracker number from mid-history, not "what were we doing". Record the expected
answer *before* asking.

Two verification anti-patterns to refuse: a check that passes because the thing it checks
never ran (a signature-error grep "passed" on a run that died earlier at "Not logged in"),
and a green result on a corpus holding half of a byte-identical pair. **Every check must
first assert that the thing it is checking actually executed.** The probe therefore decides
on two independent *positive* signals — the probe transcript grew, and the run reached the
network layer — never on the exit code, and reports an auth/onboarding stop as
**inconclusive** rather than as either outcome.

## The user dialogue

Ask these before G3. Present defaults; do not proceed on an unanswered D2.

- **D1 — Destination root.** The exact absolute path. It determines the mangled project key
  and therefore where the transcript must live; changing it later means redoing G5–G7. Offer
  a path that mirrors the origin's layout as an alternative — it keeps any future
  path-rewrite a pure prefix swap. Confirm `realpath` differs from the typed string loudly
  rather than absorbing it silently.
- **D2 — Fate of the origin.** (A) origin authoritative, this host is a read-only mirror;
  (B) this host authoritative — which requires the user's **typed** authorization for the one
  write that marks the origin as migrated; (C) knowingly forked. State plainly: **the origin
  is never deleted.** (A) is the safest and is reversible.
- **D3 — Scope.** `minimal` (transcript only) · `session` (+ sidecars, tasks, memory) ·
  `full` (+ project source) · `everything` (requires typed confirmation; typically adds
  foreign-arch artifacts that cannot execute at the destination). Quote real byte counts
  from G1, not adjectives.
- **D4 — Secrets disposition.** If G1's `SENSITIVE.txt` is non-empty: keep quarantined at
  the destination (0700, `CONTAINS_SECRETS`, never git, never archive), leave on the origin
  and fetch on demand, or archive encrypted to external media. Ask separately whether any
  credential that rides in the transcript itself should be **rotated** — that is the only
  real remediation, since the history cannot be edited. `references/secrets.md`.
- **D5 — Privileged operations.** If anything needs `sudo` or a remote password, present the
  four options from `references/secrets.md` and take the user's pick. Default: **print the
  exact command and let the user run it.** State explicitly: *I will never type, store, echo
  or read your password, and I will never enter it into any prompt.*
- **D6 — Whose account is the destination?** If it belongs to a **different person**, a
  200 MB transcript of A's work is about to land in B's account, unredacted and uneditable.
  Name what it exposes (every file read, every command run, every prose exchange) and get an
  explicit yes before G3. This is a disclosure decision, not a technical one.

Ask **D7 — write-back** only if and when there is real local work to push. Dry-run by
default; three-way classification against the checkpoint base; `BOTH_CHANGED` never
auto-resolved; a file the origin **deleted** and you then edited is a conflict, not a
"modify"; deletion disabled by policy; a final confirmation that is a **typed file count**,
not a `y/n`. That confirmation needs a real terminal — inside an agent harness there is no
controlling TTY, so either the user runs `st-resync.sh --apply` themselves or you pass
`--confirm-count N` **after they have typed N in chat**. Pushing an extended transcript back
is legal *only* if the remote file is still a byte-exact prefix of the local one — if the
origin appended anything, the histories have forked: refuse and write to a new filename.

## Decision table

| You want to… | Technique | Avoid |
|---|---|---|
| Find the session id at all | `st-preflight.sh --list-sessions` — id, key, size, mtime, opening words | asking the user for a uuid, or guessing a mangled dirname |
| Continue a session on another machine | byte-verbatim transcript copy under `mangle(realpath(dest cwd))`, same stem, + appended notice + `CLAUDE.md` → `st-transplant.py` | rewriting `$.cwd`, renaming the file, the Desktop import path |
| Make the Desktop show a transplanted session | stop that instance → drop `local_<sid>.json` → start it | `claude://resume`, the Recover-CLI-sessions UI, dropping while running |
| Just check it resumes, cheaply | `st-verify.sh` (or a bare dead-port probe): decide on **transcript growth + network-layer text**, never the exit code — 124 is GNU-`timeout`-only, perl's `alarm` gives 142 | spending an API turn; reading an exit code as a verdict |
| Move a project to a new directory | recompute the key from `realpath`, move the transcript **and its sidecar dir** together | editing the old directory name into a new one |
| Fork instead of migrate | `st-transplant.py --new-session-id <uuid>` — renames `.jsonl` and sidecar dir in one operation, origin left live | renaming the `.jsonl` by hand (orphans the sidecars) |
| Mirror both ways | `st-resync.sh`, dry-run default, prefix check, typed confirmation | any `--delete` toward the origin |
| Bring skills/memories/history to a new host | install skills **before** launch; `memory/` is keyed by *project*, tasks by *session* | assuming a `~/.claude` copy carries them |
| Recover "my other machine has the real history" | G0–G3 read-only checkpoint first, verify, *then* decide | touching the origin before you have a verified copy |
| **Push** a session to a host that cannot reach back, or move it **across OSes** | `st-bundle.py export` → copy the file → `st-bundle.py import --plan` / `--apply`; `origin-proof` on the origin → `st-verify.sh --origin-proof` | running the checkpoint on the origin and hand-copying it (that is what the bundle automates, verified) |
| Restore from an **offline archive** (USB, Time Machine, extracted tarball) | `--origin-host local --origin-claude /mnt/archive/.claude`; add `--session-only` if the working tree is gone. D2, the origin fingerprint and `st-resync.sh` are all N/A | ssh anything; treating a missing project tree as a failure |
| Migrate **several sessions** from one host | loop the whole pipeline per session, with a **separate `--checkpoint-root` per session** (or always use `latest-<SID>`); `CLAUDE.md` blocks accumulate per session | one shared `--checkpoint-root` + bare `latest` — every later transplant re-installs the last session and reports "already-placed" |
| Salvage uncommitted/unborn-HEAD work | `st-git-rescue.sh --scan`, then `--work DIR --apply --sensitive-list …` | `git gc`; `git status` without `--porcelain`; `--apply` on the live repo |
| Give a fresh session the context without the history | memory-corpus briefing (see below) | a 200 MB transplant |

## Platform notes

**Path layout.** The CLI tree is `~/.claude` (override: `CLAUDE_CONFIG_DIR`, which also
relocates `.claude.json`) on macOS and Linux, `%USERPROFILE%\.claude` on Windows
`[INFERRED]`. The Desktop user-data-dir is `~/Library/Application Support/Claude` (macOS),
`~/.config/Claude` (Linux), `%APPDATA%\Claude` (Windows) `[INFERRED]`, overridden by
`--user-data-dir`. **The transcript lives under plain `~/.claude`, not the user-data-dir** —
so every Desktop instance on a host shares transcripts, skills, plugins and memory; separate
user-data-dirs give process isolation, not account isolation. Verify the real values from
the live process argv rather than assuming. Full templates: `references/mechanics.md`.

**Windows is documented, not supported.** Nothing has run on a real Windows host yet.
- **The bundle path is pure Python** (`st-bundle.py` → `st-transplant.py`). `st-transplant.py` falls
  back to a Python copy with rsync's exact contract (`ST_NO_RSYNC=1` forces it, and the self-test
  uses it), reads the tail without `tail`, and asks claude-desktop-rehome whether Desktop is running
  when `ps` is absent.
- **The checkpoint, verify and resync drivers** are POSIX bash + `python3` stdlib, verified on macOS
  and Linux in both roles; the Windows-specific crashes (`os.statvfs`, `os.uname`) are guarded so
they degrade rather than abort, but the path templates above are inferred from Electron
conventions and how the mangler treats `C:\Users\x` (drive letter and backslashes → dashes)
is **untested**. Verify before relying on any of it; run the scripts under WSL or Git-Bash.

**Mangler input.** Always `realpath(launch cwd)` — symlinked roots resolve through, and the
alias path is never consulted even when its directory exists. For a destination that does
not exist yet, resolve the **deepest existing ancestor** and re-join the remainder; that is
what the CLI computes once the directory is created. Never `$PWD` or `pwd -L`.

**Leading dashes.** Every project key begins with `-` (the mangler maps the leading `/` of
an absolute path to a dash). Pass such values as `--origin-key=<KEY>`, never
`--origin-key <KEY>`: argparse reads a leading-dash value as the next option.

**Filename hazards, and which direction they bite.** ext4 is case-**sensitive** and stores
NFC; APFS (default) is case-**insensitive** and normalizes toward NFD. The scan must fold
**case and Unicode normalisation together** — folding on `.lower()` alone reports 0
collisions for exactly the NFC/NFD pair that merges. It must run on the **origin manifest,
before the transfer**: on a case-insensitive destination the two names have already merged
by the time you could scan the copy, and the scan reports 0. The severity is decided by the
**destination filesystem**, measured not assumed: collisions landing on a case-insensitive
filesystem are FATAL in either direction (`Foo.md` and `foo.md` merge, one file's content is
destroyed, and **rsync reports success**); on a case-sensitive one they are a warning that
becomes fatal on any later move to a case-insensitive one, including a write-back to a macOS
origin. openrsync has no `--iconv` and nothing can fix it in flight.

**macOS-origin quirks.** No GNU `timeout` (use `perl -e 'alarm N; exec @ARGV'` — and note its
SIGALRM exit is 142, not 124); `stat -f` not `-c`; BSD `find` rejects `-newermt @epoch`; BSD
`grep` has no `\b`; `shasum -a 256` exists but `/sbin/sha256sum` is ~5× faster; `zstd` may be
absent (zstd-19 buys 9% over zstd-3 for 16× the CPU — use -3); the system `rsync` is
**openrsync**, which lacks `-H -X -A -S --iconv --fake-super --protect-args
--ignore-missing-args` but has `--link-dest --checksum --itemize-changes --numeric-ids
--partial -n`. Drop `.DS_Store` everywhere. Remote helper scripts go over stdin and must fit
the remote Python's stdlib.

## When NOT to use this skill

If the user wants a *fresh session that knows the context*, transplanting is the wrong tool.
A **memory-corpus briefing** is cheaper, safer and usually better: copy `projects/<KEY>/
memory/*.md` (the reference corpus was 24 files / 399 KB and the highest value per byte in
the entire tree) plus `tasks/<SID>/` (which carries the live agenda — the reference store was
141 completed / 8 pending / 3 in-progress), write a `CLAUDE.md`, and start clean. No signed
thinking blocks, no 200 MB file, no account coupling, no prohibitions to trip over. Reach
for the full transplant only when the user needs **the actual conversation** — the ability to
walk back through what was tried and rejected, or to resume mid-task with the model's own
reasoning intact. This is also the fallback if a thinking signature is ever rejected.

Also out of scope: a session that is merely *running in the wrong directory* on the same
host (recompute the key and move the transcript + sidecar dir together; no checkpoint
needed), anything asking for the history to be *edited*, and a Desktop profile that was signed in to a different account on the same host and now shows no sessions (use **claude-desktop-rehome**: it only moves the small `claude-code-sessions/<account>/<org>/` records; transcripts never move). If a path rewrite is genuinely
wanted, the acceptance test is **invertibility** — apply the inverse map and assert
`sha256(inverse(rewritten)) == sha256(original)`, no exceptions, and a rule is admissible
only if its target string occurs **zero** times in the input.

## References and scripts

- `references/mechanics.md` — the three-layer storage model with exact path templates per OS;
  the mangler with a reference implementation and its collision properties; resume
  resolution (cwd-scoping, realpath, worktrees, `--resume <path>.jsonl`); what is inert vs
  load-bearing; sidecar resolution; memory and tasks keying; compaction and what reaches the
  wire; version skew; and the **zero-token measurement techniques** (dead-port probe,
  recording mock API) that made all of this safe to establish.
- `references/integrity.md` — coverage vs fidelity as separate gates; the remote/local
  manifest diff; checkpoint generations, `--link-dest` and sealing; publish-only-on-success;
  filename hazards and the detection script; torn-read detection on a live transcript;
  fragile-git rescue including the stale-index trap; the origin-unchanged proof; rollback
  per gate.
- `references/secrets.md` — the NEVER-COPY list and what each file contains; why whitelisting
  is mandatory; remediation after over-collection; project-side secrets and the
  `.gitignore`-before-`git add -A` rule; the assistant's own conduct rules; the four options
  for privileged remote operations.
- `references/lessons.md` — the frank post-mortem: M1–M8 with real numbers, the near-miss
  that a green verification did not catch, what went right and should be repeated, and the
  subagent constraints-block template (an unstated containment constraint **will** be
  violated — one subagent told "install Rust without sudo" put 1.6 GB in `$HOME`).
- `references/evidence-base.md` — the source migration's distilled evidence, shipped as a
  historical record: §1 the COPY / NEVER-COPY lists, §2 the transcript record schema, §3 the
  Desktop session JSON schema, §4 the procedure as executed, §5 every measured constant,
  §6 twenty-four things that look true and are false, §7 the guards and tripwires, §8 open
  issues. Its paths and identifiers name **that** run, not yours; consult it when a claim
  made elsewhere here is disputed.
- `README.md` — the human guide (install, the bundle step by step on each OS, troubleshooting).
- `scripts/README.md` — what each script refuses to do, and why. `scripts/askpass-setup.md`
  — the four options for a privileged remote operation, with the clause `references/secrets.md`
  §6 retracts. `CHANGELOG.md` (skill root) records what changed, what was tested and what was
  not: read it before assuming a behaviour you remember still holds.
- `scripts/st-preflight.sh` (G0/G1) · `st-checkpoint.sh` (G3, `--plan`/`--apply`) ·
  `st-git-rescue.sh` (G4, `--scan`, `--work`+`--apply`) · `st-transplant.py` (G5–G7,
  `--plan`/`--apply`) · `st-verify.sh` (G8) · `st-resync.sh` (write-back, `--apply`) ·
  `mangle.py` (canonical, derived from the CLI binary, 22/22 against observations —
  **losing it means re-deriving the mangler before any transplant can be preflighted**) ·
  helpers `st-common.sh`, `st_walk.py`, `st_origin_probe.py` · templates
  `excludes.example`, `profile.example`.
- `scripts/st-bundle.py`: export / inspect / import / origin-proof (format: `references/bundle-format.md`).
  `scripts/selftest.py`: synthetic two-machine test of the bundle path and the transplant / verify
  options (36 checks, mutation-tested). Run it after any change: `python3 -I scripts/selftest.py`.
- **Companion:** claude-desktop-rehome (`ccd-rehome export-record` / `adopt`) owns Desktop-record
  knowledge. Install it next to this skill (or set `ST_REHOME`). Never re-implement record handling here.

## Extending this skill

It is meant to grow. The rules for changing it are the same ones it enforces:

- A new claim needs an **experiment**, not an argument. Tag it `[M]` measured, `[C]`
  code-lifted, `[D]` derived, `[I]` inferred, and say which run established it.
- A new guard is only real if it is **executable**. If it cannot be a refusal in a script,
  it is a note, and notes do not stop anyone.
- Any new gate must state what happens when it **cannot run** — and that state must count
  as a failure, never as a pass.
- Record what you changed in `CHANGELOG.md`, including what you *tested* and what you did
  not. The honest "not tested" list is the most useful part of it.
