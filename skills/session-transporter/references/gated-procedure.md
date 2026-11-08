# The gated procedure (path 2): pull a session from a machine you can reach over ssh

Read this file **in full before running any `st-*.sh` script**. SKILL.md routes here when the portable bundle
(path 1) is not the right tool:

- this machine can **ssh to the origin**, and you want a read-only checkpoint of the origin with manifests built on
  both sides ("my other machine has the real history");
- you are restoring from an **offline archive** (USB disk, Time Machine, an extracted tarball);
- you need **write-back** to the origin later (`st-resync.sh`);
- the session must be rescued with **fragile git state** (an unborn HEAD, uncommitted work).

The prohibitions and the user dialogue (D1–D7) in SKILL.md apply here unchanged.

In the commands below, `S` is this skill's `scripts/` folder: the folder SKILL.md calls
`${CLAUDE_SKILL_DIR}/scripts`. Each code block sets it on its first line; replace the path with the real one.
Shell variables do not survive between an agent's separate commands, so set `S` again in each.

## A worked run

Six commands. Everything else in this file explains why each one refuses what it refuses. `--profile` carries the
values so you type them once; **command-line flags always override the profile**.

```bash
S=/path/to/session-transporter/scripts

# 0. DISCOVERY — you do not know the session id. Nobody does; it is a uuid inside a
#    directory whose name the mangler makes unguessable.
bash "$S/st-preflight.sh" --origin-host mymac --list-sessions

# 1. G0/G1 PREFLIGHT — writes nothing. Emits a profile with everything it discovered.
bash "$S/st-preflight.sh" \
    --origin-host mymac \
    --origin-root  /Users/me/Projects/thing \
    --session-id   <the id from step 0> \
    --dest-root    /home/me/Projects/thing \
    --checkpoint-root /home/me/checkpoints \
    --hazards --emit-profile ./mig.conf --report ./preflight.txt

# 2. G2 CONSENT — ask D1–D6 (SKILL.md, "The user dialogue") in chat, and record the answers. Then:

# 3. G3 CHECKPOINT — --plan first (accounting only), then --apply.
bash "$S/st-checkpoint.sh" --profile ./mig.conf --exclude-file ./excludes.txt --plan
bash "$S/st-checkpoint.sh" --profile ./mig.conf --exclude-file ./excludes.txt --apply

# 4. G4 RESCUE fragile git state, on a COPY (never on the origin).
bash "$S/st-git-rescue.sh" --scan /home/me/checkpoints/latest-<SID>/project
bash "$S/st-git-rescue.sh" --repo /home/me/checkpoints/latest-<SID>/project/thing \
    --work /home/me/rescue/thing --apply \
    --sensitive-list /home/me/checkpoints/latest-<SID>/manifest/SENSITIVE.txt

# 5. G5–G7 TRANSPLANT — --plan first, then --apply. The transplant step reads the same
#    ST_* names from the ENVIRONMENT (not from a profile file), so export them once.
set -a; . ./mig.conf; set +a
python3 "$S/st-transplant.py" --plan
python3 "$S/st-transplant.py" --apply --skill <name> --skill <name>

#    Desktop only: add --user-data-dir/--account/--org (or set them in mig.conf).
#    A CLI-only migration is complete without them.

# 6. G8 VERIFY — then ask the semantic question yourself.
bash "$S/st-verify.sh" --profile ./mig.conf --checkpoint "$ST_CKPT"
```

Every `st-*.sh` takes `--profile`; `st-transplant.py` reads the same `ST_*` names from the environment instead.
Use `latest-<SID>`, not bare `latest`: one checkpoint root shared by several migrated sessions leaves `latest`
naming only the last of them, which is why `--emit-profile` writes `ST_CKPT=$ST_CKPT_ROOT/latest-$ST_SESSION_ID`.
The templates `scripts/profile.example` and `scripts/excludes.example` show every setting.

## The gates

`G0–G3` write **nothing outside the checkpoint directory**: they are free to run, free to abort, and free to
re-run. `G4` writes only local copies. `G5–G7` touch live destination state. Nothing in any gate writes to the
origin except the optional write-back path.

| Gate | Writes live state? | Script and verb | Pass criterion | Rollback cost |
|---|---|---|---|---|
| **G0 discovery + preflight** | no | `st-preflight.sh --list-sessions`, then plain | origin reachable, session located, versions and headroom known, destination key computed | free |
| **G1 inventory** | no | `st-preflight.sh` (same run) | every byte to be moved is enumerated by category with counts | free |
| **G2 consent** | no | dialogue (SKILL.md) | user answered D1–D6; answers recorded | free |
| **G3 checkpoint + verify** | no (checkpoint dir only) | `st-checkpoint.sh --plan` then `--apply` | coverage, fidelity and unexpected-files reported as **three separate gates**, remote manifest vs local manifest | free: delete the dir |
| **G4 rescue fragile state** | local copies only | `st-git-rescue.sh --scan`, then `--work DIR --apply` | `gc.auto=0` set first; every staged blob resolves; index commit; bundle + bare mirror verify | free |
| **G5 materialize destination** | **YES** | `st-transplant.py --plan` then `--apply` | prefix hash == origin hash; sidecar/memory/tasks counts ≥ checkpoint | delete dest tree + dest transcript |
| **G6 install shared assets** | **YES** | `st-transplant.py --apply` (asset phase) | skills present **at the destination path**, asserted there, not in the checkpoint; receipt written | remove installed assets |
| **G7 activate** | **YES** | `st-transplant.py --apply` (session mint) + launch | **CLI-only:** `cd <dest> && claude --resume=<SID>` loads. **Desktop:** instance stopped → JSON dropped → instance started → session listed and opens | delete the session JSON |
| **G8 semantic verify** | read-only + ≤1 turn | `st-verify.sh` | every check green **and** the resumed session answers a question only the real history can answer | nothing |

### G0 — discovery and preflight (writes nothing)

**Step 0 is `--list-sessions`.** It prints, per transcript, the session id, project key, size, mtime and the
opening words of the first user message: the only thing that lets a human say "that one". Do not ask the user for
a uuid they cannot know.

Then: reachability and RTT; free space **on both sides** (the reference origin had 38 GiB free of 3.6 TiB, a hard
design constraint); CLI version on the destination (**record it**; `--emit-profile` writes it as `ST_CLI_VERSION`
and `st-transplant.py --cli-version` stamps it into any appended record); `realpath` of the proposed destination
root and the mangled key it produces; whether that key already exists locally; whether the destination filesystem
is case-insensitive; whether the destination root is already a git repo.

Capture an **origin fingerprint** now: `mtime + size + mode + inode + name`, sorted and hashed, `atime` excluded by
construction, `ctime` captured as a second advisory fingerprint. Capture `pre` as well as `post`; a post-only
fingerprint proves nothing.

If several project keys hold the session (git worktrees do this legitimately), preflight **fails** rather than
picking the alphabetically first. Resolve it with `--origin-key`, or take them all with
`st-checkpoint.sh --all-transcript-keys`.

### G1 — inventory (writes nothing)

Recurse the session's roots **fully**: a `-maxdepth 1` sweep misses `subagents/workflows/`, which was **38% of
all bytes**. Expect these categories (reference-run numbers, for shape, not for equality; a short session
legitimately has none of rows 2–8):

| Component | Path pattern | Reference |
|---|---|---|
| main transcript | `projects/<KEY>/<SID>.jsonl` | 216,236,906 B: 55.8% of the session |
| subagent transcripts + meta | `projects/<KEY>/<SID>/subagents/agent-*.{jsonl,meta.json}` | 51 agents |
| **workflow agents** | `…/subagents/workflows/wf_<runId>/…` | 1,765 files, 148 MB |
| tool-result overflow blobs | `…/<SID>/tool-results/<9char>.txt` | 11 files |
| workflow runs + scripts | `…/<SID>/workflows/{wf_*.json,scripts/*.js}` | 113 files |
| **sibling project keys** | `projects/<KEY><suffix>/<SID>/…` | 9 files: *easily missed* |
| task/todo store | `tasks/<SID>/` | 154 entries |
| **project memory** | `projects/<KEY>/memory/*.md` | 24 files: **highest value per byte in the tree** |
| shared assets | `skills/`, `agents/`, `commands/`, `output-styles/`, `settings.json`, `~/.claude/CLAUDE.md` | project-independent; see G6 |

A `.jsonl`-only copy loses **44% of bytes and 100% of subagent conversation content**. Sub-agents are **not**
reconstructable from the main transcript: only 16 of 51 `toolUseId`s appear there. Enumerate the directory.

`agents/`, `commands/`, `output-styles/` and `~/.claude/CLAUDE.md` are startup-enumerated and host-shared. They are
**inventoried always and copied only on request** (`--include-agents`, `--include-commands`,
`--include-output-styles`, `--include-user-memory`). `~/.claude/CLAUDE.md` in particular applies to every project
on the host and usually names the origin's absolute paths, so it is copy-with-review.

Also run the **filename hazard scan** here (`--hazards`); see "Platform notes" in SKILL.md.

### G2 — consent (writes nothing)

Ask D1–D6 (SKILL.md), record the answers, then state the scope in bytes and files before proceeding. Do not begin
G3 with an unanswered D2 (origin fate).

### G3 — checkpoint and verify (writes only inside the checkpoint dir)

`st-checkpoint.sh --plan`, then `--apply`. Non-negotiable properties, each of which exists because it was learned
the hard way:

- **Every exclude is anchored and justified**, and printed with a **per-pattern match count**. An over-broad
  pattern must surface as a *number*, never as silence. `--exclude='_research/re/rust/'` dropped 26 files including
  the project's keystone source file; `target/` was assumed to be build output and was actually the ground-truth
  binary drop dir. **Never pattern-match on a directory name.** An unanchored pattern must be written
  `unanchored:PAT  # why`; there is no flag that turns the justification off.
- **The remote manifest is built first and independently.** Verification diffs a **remote-side** manifest against
  a **local-side** manifest, produced by the same walker shipped over stdin. Hashing the local copy and comparing
  it to itself is not verification.
- **Coverage, fidelity and unexpected-files are three separate gates.** A corpus can be 100% faithful and 60%
  complete. Unexpected files are a gate too, not an INFO line: the manifest uses one exclude engine and the
  transfer uses rsync's, and a divergence means over-collection passing green.
- **Symlinks are manifest rows,** not skipped oddities. A blind spot shared by the oracle and the copy is not a
  gate.
- **The whitelist entries that do not exist on the origin are skipped, not failed.** A short session has no
  `memory/`, no `tasks/<SID>/` and no sidecar dir; four rsync exit-23s used to turn a perfectly good checkpoint
  into an unrecoverable refusal.
- **The transcript uses the prefix invariant**, not whole-file equality: `sha256(remote[0:L]) ==
  sha256(local[0:L]), L <= R`. JSONL is append-only.
- **Whitelist for the `~/.claude` side** plus an independent denylist assertion over the staged bytes
  (`references/secrets.md`), with deliberately-copied shared assets exempted so the gate does not cry wolf.
- **Seal `a-w`, then publish.** `COMPLETE` sentinel last, then relative `latest` and `latest-<SID>` symlinks.

### G4 — rescue fragile state (local copies only)

Anything that has exactly one copy and no history: an unborn-HEAD git repo, uncommitted work, a `.git/index` that
is the only blob→name map. `gc.auto=0` **first**. Then verify every staged blob resolves, and commit the index.

`--apply` requires `--work DIR` (rescue on a copy). `--in-place` exists, demands a typed confirmation, and refuses
when the repo is under `ST_ORIGIN_ROOT`.

**The index may be stale relative to the working tree.** The reference run's second commit added 26 files and
modified 6, including an entire required crate, that an index-only rescue would have lost. For an
**unborn-HEAD** repo the drift commit is the rescue. For a repo with **real history** it is not: `git add -A` onto
a branch with an upstream diverges it and destroys a curated staging set, so the script writes `drift.patch` +
`untracked.txt` instead and says so. Pass `--sensitive-list <checkpoint>/manifest/SENSITIVE.txt`: a commit
propagates a private key into the bundle *and* the bare mirror. Details: `references/integrity.md`.

### G5 — materialize the destination (first gate that touches live state)

Order matters and every step is idempotent and re-runnable:

1. `rsync -a --no-perms --chmod=u+rwX,go-w` the project tree out of the sealed checkpoint: plain `-a` propagates
   the checkpoint's read-only mode into the working tree. **Files at the destination whose content differs from
   the checkpoint are counted and refused** (`--overwrite-destination-work` overrides and backs them up under
   `.st-overwritten/<ts>/`): rsync's quick check is size+mtime and the checkpoint is always older, so without that
   gate every re-run silently reverts destination work and reports OK. If the destination root is already a git
   repo, `.git/` is **excluded** unless `--merge-git`: overwriting refs orphans destination-only commits *and*
   clobbers the reflog that would recover them.
2. Copy the transcript to `<claude-home>/projects/<mangle(realpath(dest root))>/<SID>.jsonl`, **same filename
   stem**, `chmod 0600` after copying, assert byte-identity. The key is computed by resolving the **deepest
   existing ancestor** and re-joining the remainder, then re-asserted after `mkdir`: a destination behind a
   symlinked parent otherwise lands under a key the CLI will never look in.
3. **Append** the relocation notice as a `type:"user"` record whose `parentUuid` is the last record that *has* a
   uuid (tail-scan backwards). Re-assert the prefix hash after appending. Content: origin and destination
   host/user/account, an explicit **old→new path table**, and the consequences: that tens of thousands of lines
   reference origin paths as *historical record, not live locations*; that old scripts hold hardcoded origin paths
   so a path failure is *expected, not surprising*; and whether the origin is reachable and on what terms.
4. Optionally append one `{"type":"relocated","sessionId":"<in-record sessionId>","relocatedCwd":"<existing abs
   path>"}` line. It is **not honored on `--resume`** (only the in-REPL `/resume` picker): free to add, never to
   rely on. It must land within the last 64 KiB.
5. Sidecars, `memory/`, `tasks/<SID>/`, and **the sibling project keys' `<SID>/workflows/scripts/` and
   `memory/`**. Assert counts against G1: `destination < checkpoint` is the failure; `destination > checkpoint` is
   a session that has been used.
6. Write the durable `CLAUDE.md` in the destination project root, between **session-scoped** markers so migrating
   a second session into the same root does not delete the first one's path table.

An existing destination transcript is never deleted. If its first N bytes match the checkpoint it is a **resumed
session** and is left alone; anything else is renamed to `<SID>.jsonl.st-displaced-<ts>` and only with
`--allow-existing`.

Note `tool-results/` **decays**: the destination CLI's own retention sweeper pruned one blob between transplant and
first launch. A decrease there is a warning, not a failure.

### G6 — install shared assets (a gate, not a footnote)

Skills, agents, commands and the mergeable `settings.json` keys are **shared across every instance on the host**:
they live under plain `~/.claude`, not the user-data-dir. Two measured constraints:

- **Skills are enumerated at CLI process startup and cached for the process lifetime.** A skill added mid-session
  does not appear in the next turn's system prompt. **Install before launching the destination.**
- **"Backed up" is not "installed."** In the reference run skills and plugins were copied into the checkpoint and
  never installed, and the gap was invisible because the backup looked complete. Assert presence **at the
  destination path**; `st-transplant.py` writes `<dest root>/.st-receipt.json` so `st-verify.sh` checks what was
  *meant* to be installed rather than everything the checkpoint happens to hold.

Whitelist skills by **name**: one skill in the reference corpus was 321 MB of `.venv` with two bundled Node
runtimes. Audit anything executable for `#!/bin/zsh`, `brew`, `otool`, `codesign` and foreign-arch binaries before
copying. A destination skill of the same name is **never replaced without `--overwrite-skill`**, and is backed up
when it is. **Regenerate plugins, do not copy them**: they carry absolute `installPath` and native-arch payloads.
Origin `settings.json` keys that are *not* merged are listed as a warning: if the session depended on `hooks`,
`permissions` or `env`, copy them deliberately.

### G7 — activate

1. Assert the target Desktop instance is **not running**:
   `ps -eo pid,comm,args | awk '$2 ~ /claude|electron/ && index($0, "<dir>")'`. **Never `pgrep -af '<pattern>'`**:
   it self-matches the checking shell (2 false positives measured). **Never `pkill -f`**: it self-matched and
   killed a run mid-experiment. `--force` lets steps 1–6 proceed; it never permits the session mint.
   `ccd-rehome status P` (session-rehome) answers the same question on every OS.
2. Workspace trust: the app shows its dialog once and accepting it there is the safe path. `--trust` writes
   `projects["<dest root>"].hasTrustDialogAccepted = true` into the CLI's host-wide config. It is **off by
   default** and refuses while any claude process runs.
3. The Desktop session record. With session-rehome installed (the normal case), `st-transplant.py` hands
   the record to `ccd-rehome adopt`: validated, filed under the signed-in account (or `--account`), archived,
   undoable. Without it, a minimal record is minted at
   `<user-data-dir>/claude-code-sessions/<accountUuid>/<orgUuid>/local_<uuid4>.json`, with these rules:
   **filename must equal the `sessionId` field** or the app rewrites it and leaves a permanent ghost that reloads
   every launch; mode 0600, **every** directory level 0700, < 10 MiB; required keys `sessionId`, `cwd`,
   `cliSessionId` (missing ⇒ treated as never-started). **Do not write a `model` key** unless the user names one:
   model availability is account- and plan-scoped, and a hardcoded id produces a session the destination account
   cannot start, whose failure looks like a transplant failure. A wrong `<accountUuid>/<orgUuid>` is not a soft
   failure: the file is never read, *and* it suppresses its own transcript from the current account's recovery UI.
   Template and full key table: `references/mechanics.md`.
4. Start the instance **the way the user normally starts it**. The Desktop launcher's binary name is platform- and
   install-specific (AppImage, `.desktop` entry, bundle); `ccd-rehome launch P` knows the common ones. Otherwise
   ask, or let the user do it.
5. **The CLI-direct path is a complete alternative on its own:** `cd <dest root> && claude --resume=<SID>`. Use it
   as the cheap smoke test before the Desktop, and as the whole of G7 for a CLI-only migration.

Note: absence of `claude-code-sessions/` means "no session yet", **not** "not signed in". `ccd-rehome status P`
reports the sign-in state without reading any credential.

### G8 — semantic verify

Loaded ≠ faithful, and byte counts cannot tell the difference. `st-verify.sh` checks prefix byte-identity,
destination-tree coverage, sidecar/memory counts, session registration, shared assets installed at the
destination, the origin fingerprint, and runs a **dead-port load probe** costing zero API turns against an
isolated `CLAUDE_CONFIG_DIR`, so the live transcript is not appended to.

**Then ask the resumed session a question only the real history can answer**: a specific artifact and tracker
number from mid-history, not "what were we doing". Record the expected answer *before* asking.

Two verification anti-patterns to refuse: a check that passes because the thing it checks never ran (a
signature-error grep "passed" on a run that died earlier at "Not logged in"), and a green result on a corpus
holding half of a byte-identical pair. **Every check must first assert that the thing it is checking actually
executed.** The probe therefore decides on two independent *positive* signals (the probe transcript grew, and the
run reached the network layer), never on the exit code, and reports an auth/onboarding stop as **inconclusive**
rather than as either outcome.

## D7 — write-back to the origin (`st-resync.sh`)

Ask D7 only if and when there is real local work to push. Dry-run by default; three-way classification against the
checkpoint base; `BOTH_CHANGED` never auto-resolved; a file the origin **deleted** and you then edited is a
conflict, not a "modify"; deletion disabled by policy; a final confirmation that is a **typed file count**, not a
`y/n`. That confirmation needs a real terminal. Inside an agent harness there is no controlling TTY, so either the
user runs `st-resync.sh --apply` themselves or you pass `--confirm-count N` **after they have typed N in chat**.
Pushing an extended transcript back is legal *only* if the remote file is still a byte-exact prefix of the local
one. If the origin appended anything, the histories have forked: refuse and write to a new filename.

## Restoring from an offline archive

`--origin-host local --origin-claude /mnt/archive/.claude` makes the archive the origin; add `--session-only` if
the working tree is gone. D2, the origin fingerprint and `st-resync.sh` are all N/A: an archive is not a live
machine. Nothing is ever written into the archive.

## Several sessions from one host

Loop the whole pipeline per session, with a **separate `--checkpoint-root` per session** (or always use
`latest-<SID>`). The destination `CLAUDE.md` accumulates one marked block per session. A single shared
`--checkpoint-root` with bare `latest` makes every later transplant re-install the last session and report
"already-placed".
