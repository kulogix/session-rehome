# Integrity — the zero-data-loss doctrine

Every claim in this file comes with the command that checks it. Nothing here is a
principle you are asked to hold in your head; each is a gate that either passes or
fails, with a defined rollback.

Evidence tags: `[M]` measured on the real migration · `[C]` lifted from code ·
`[D]` derived · `[LIVE]` re-verified on disk. Full evidence base:
`references/evidence-base.md`, shipped with this skill
(§1 file lists, §4 procedure, §5 constants, §6 false beliefs, §7 guards, §8 open issues).
Its §7 carries the risk model this section is built on (vectors V01–V27, checks
PF01–PF14 / PO01–PO14); the underlying recon documents `R01`–`R12` were **not** shipped —
where this file cites one, the claim it supports is restated here in full.

**The doctrine in one sentence:** nothing is believed because a tool exited 0 — every
byte that matters is proven by comparing two *independently produced* descriptions of
it, and no artifact is published until that comparison passes.

---

## 1. Coverage and fidelity are two different gates

This is mistake **M2**, and it is the mistake that makes a migration silently lossy.

| Gate | Question | What it compares | Failure looks like |
|---|---|---|---|
| **Coverage** | Is every file that exists on the origin *present* at the destination? | the **path set** from an independently-derived origin listing vs. the path set actually on disk | a `<` line in the manifest diff — a path the origin has and you do not |
| **Fidelity** | For the files that are present, do the bytes match? | the **hash at each shared path** | a differing hash on a path both sides have |

### Why a corpus can be 100 % faithful and 60 % complete

The v1 verifier hashed the local copy and compared it to itself. Every hash matched,
so it reported PASS. What it had actually proven was: *the files I copied are the files
I copied.* A transfer that dropped 40 % of the tree passes that check perfectly —
fidelity is measured only over the **intersection** of the two sets, and if the set of
paths is taken from the copy, the intersection *is* the copy.

This is not hypothetical. On the real run, `--exclude='_research/re/rust/'` (intended to
skip a cargo target dir) silently dropped **26 files / 1.44 MB** including
`fasp-core/src/cap.rs`, the CAP-TLV keystone `[M]`. Every surviving file hashed
correctly. A local-only verifier would have reported a green migration with the
project's most important source file missing.

> **Rule:** the path list used for coverage must be produced by a `find` executed on the
> **origin**, before or independently of the transfer. Never derive it from the transfer's
> own output, its log, or the destination tree.

### The remote-manifest / local-manifest diff pattern

Build the origin manifest **first**, then transfer, then build the destination manifest
with a *separate* walk, then `diff` the two. One `diff` catches both gates because the
lines carry `<hash>  <path>`: a `<` line means missing/differing on the local side, a
`>` line means unexpected locally.

```bash
# ---- 1. ORIGIN manifest. Runs on the origin, over ssh, writes only to the local side.
#         macOS has shasum; Linux has sha256sum. /sbin/sha256sum on macOS is 5x faster
#         than shasum -a 256 and produces identical digests [M].
ssh "$REMOTE" "cd '$RT' && find . -type f \
   -not -path './SimLab/acmeorg_simlab/rust/target/*' \
   -not -path './_research/re/rust/target/*' \
   -not -path './_research/re/.rust-env/*' \
   -not -path '*/node_modules/*' -not -path '*/__pycache__/*' \
   -not -path '*/.pytest_cache/*' -not -name '*.pyc' -not -name '.DS_Store' -print0 \
   | xargs -0 -P 8 shasum -a 256" 2>/dev/null \
  | sed 's|  \./|  |' | sort -k2 > "$DEST/manifest/remote-project.sha256"

# ---- 2. Sanity FLOOR. An over-broad exclude must show up as a NUMBER, not as silence.
RN=$(wc -l < "$DEST/manifest/remote-project.sha256")
[ "$RN" -lt 24000 ] && die "remote project manifest suspiciously small ($RN)"

# ---- 3. Transfer (pull direction only).
rsync -a --stats --no-perms --no-owner --no-group "${LD[@]}" "${EXCL[@]}" \
  "$REMOTE:$RT/" "$DEST/project/" >> "$DEST/logs/rsync-project.log" 2>&1
rc=$?; [ $rc -ne 0 ] && die "rsync project rc=$rc"

# ---- 4. LOCAL manifest — an independent walk of what actually landed.
( cd "$DEST/project" && find . -type f -print0 | xargs -0 -P 8 sha256sum ) 2>/dev/null \
  | sed 's|  \./|  |' | sort -k2 > "$DEST/manifest/local-project.sha256"

# ---- 5. The gate. Report coverage and fidelity SEPARATELY.
if diff <(sort "$DEST/manifest/remote-project.sha256") \
        <(sort "$DEST/manifest/local-project.sha256") \
        > "$DEST/manifest/DIFF-project.txt" 2>&1; then
  log "project: VERIFIED — every file byte-identical to $REMOTE"
else
  MISS=$(grep -c '^<' "$DEST/manifest/DIFF-project.txt" 2>/dev/null || echo 0)
  EXTRA=$(grep -c '^>' "$DEST/manifest/DIFF-project.txt" 2>/dev/null || echo 0)
  die "project: MISMATCH — $MISS missing/differing, $EXTRA unexpected"
fi
```

Achieved on the real run `[LIVE]`: **24,538 project files + 6,245 session files**,
`DIFF-project.txt` and `DIFF-claude.txt` both **0 bytes**.
Verify a checkpoint's claim at any later time with:

```bash
wc -c "$CKPT"/manifest/DIFF-*.txt          # both must be 0
wc -l "$CKPT"/manifest/*.tsv               # remote==local counts
```

### Split the diff into two named numbers

`diff` output is one stream; the report must not be. Coverage failures and fidelity
failures have different causes and different fixes, and collapsing them hides the
dangerous one:

```bash
# coverage: paths on the origin that are absent or different locally
awk '/^< /{print $NF}' DIFF-project.txt | sort > /tmp/left.paths
awk '/^> /{print $NF}' DIFF-project.txt | sort > /tmp/right.paths
comm -23 /tmp/left.paths /tmp/right.paths > MISSING.txt      # coverage failure: not here at all
comm -12 /tmp/left.paths /tmp/right.paths > CORRUPT.txt      # fidelity failure: here, wrong bytes
wc -l MISSING.txt CORRUPT.txt
```

A path appearing on **both** sides of the diff is a fidelity failure (present, wrong
bytes). A path appearing only as `<` is a coverage failure (never arrived). `MISSING`
non-empty is usually an exclude bug (M1); `CORRUPT` non-empty is usually a torn read
(§3) or a truncated transfer.

### Excludes are part of the coverage gate (M1)

Two excludes destroyed or nearly destroyed data on the real run `[M]`:

- `--exclude='_research/re/rust/'` — unanchored, meant to skip `re/rust/target/`.
  Dropped 26 files of irreplaceable source. Anchored form: `--exclude='/_research/re/rust/target/'`.
- `--exclude='_research/re/target/'` — assumed "target == build output". It was the
  ground-truth **oracle drop dir** (`ascp`, `ascp.i64` at 134,176,621 B, `aspera-license`).
  Verified present and identical, 7/7, after being un-excluded `[M]`.

> **Rule:** every exclude is ANCHORED (leading `/`), and every exclude is justified
> against a listing of what it actually matches. Never pattern-match on a directory
> **name**. Print a per-pattern match count so an over-broad pattern shows as a number.

```bash
# Justify each exclude before trusting it.
for pat in '/SimLab/acmeorg_simlab/rust/target' '/_research/re/rust/target' '/_research/re/.rust-env'; do
  n=$(ssh "$REMOTE" "cd '$RT' && find .${pat} -type f 2>/dev/null | wc -l")
  echo "EXCLUDE ${pat}: ${n} files"
  ssh "$REMOTE" "cd '$RT' && find .${pat} -maxdepth 2 2>/dev/null | head -20"
done
```

### An independent second opinion

`rsync -n -a -c --itemize-changes` re-checksums both sides with rsync's own MD4/MD5
rolling checksums — a genuinely different mechanism from the SHA-256 manifests, which is
the entire point. Any output beyond expected excluded-dir noise is a verification failure.
Available in openrsync (protocol 29) on macOS `[M]`.

```bash
rsync -n -a -c --itemize-changes "${EXCL[@]}" "$REMOTE:$RT/" "$DEST/project/" | head -50
```

### Coverage is measured again at the destination (M4)

"Backed up" and "installed" are different gates at different paths. On the real run,
skills and plugins were copied into the checkpoint and **never installed** at the
destination; the gap was invisible because the backup looked complete. This class of
failure is still open — see `SKILL-SOURCE-FACTS.md` §8 O1: nine sibling workflow scripts
sit in the checkpoint and were never installed `[LIVE]`.

Assert counts at the **destination path**, never at the checkpoint path:

```bash
K=$(python3 -c 'import os,sys;print(os.path.realpath(sys.argv[1]))' "$DEST_ROOT")
D=$(python3 "$SKILL/tools/mangle.py" "$K")            # the mangler; see SKILL.md
P="$HOME/.claude/projects/$D"

printf 'subagents   %s (origin 1867)\n' "$(find "$P/$SID/subagents"    -type f | wc -l)"
printf 'tool-results %s (origin 11, decays — see below)\n' "$(find "$P/$SID/tool-results" -type f | wc -l)"
printf 'workflows   %s (origin 113)\n'  "$(find "$P/$SID/workflows"    -type f | wc -l)"
printf 'memory      %s (origin 24)\n'   "$(find "$P/memory" -name '*.md' | wc -l)"
printf 'tasks       %s (origin 152+2)\n' "$(find "$HOME/.claude/tasks/$SID" -type f | wc -l)"
printf 'skills      %s\n'               "$(ls -1 "$HOME/.claude/skills" | wc -l)"
```

Achieved `[LIVE]`: `subagents 1867 · tool-results 11→10 · workflows 113 · tasks 152 · memory 24`.

**`tool-results/` decays and that is not a bug.** The destination CLI's own retention
sweeper pruned `bmdwv27oc.txt` after the transplant (dest mtime 14:33 vs transplant 14:18)
`[LIVE]`. The origin store was *already* inconsistent: 5 keys referenced, 11 on disk, 3
dangling, 9 orphaned `[M]`. Copy sidecars late, verify counts **after** the first launch,
and treat a `tool-results` shortfall as informational, everything else as a hard gate.

**A `-maxdepth 1` sweep of `subagents/` misses 38 % of the entire session** —
`subagents/workflows/` alone is 148,506,101 B `[M]`. Recurse fully, always.

---

## 2. Fidelity for the transcript: the prefix invariant

The transcript is append-only JSONL `[M]` — resume is a pure append, and the first N
bytes are byte-identical after three resumes `[M]`. That gives a stronger and cheaper
guarantee than "hash the whole thing twice and hope it didn't move".

Let `L` = local copy size, `R` = origin size. The copy is **valid** iff

```
sha256(origin_bytes[0:L]) == sha256(local_bytes[0:L])   and   L <= R
```

```bash
L=$(stat -c%s "$LOCAL_TX" 2>/dev/null || stat -f%z "$LOCAL_TX")
ssh "$REMOTE" "head -c $L '$REMOTE_TX' | /sbin/sha256sum"     # macOS: /sbin/sha256sum
sha256sum "$LOCAL_TX"
```

Properties this buys:

- **Tolerates concurrent appends.** The origin session can be actively writing.
- **Detects truncation or rewrite immediately** — and it is precisely the experiment that
  would falsify the append-only hypothesis, which is why it is the right check.
- **Gives a resumable delta**: extend with `tail -c +$((L+1))`, append, re-verify the new
  prefix. 216 MB → 220 MB costs 4 MB, not 216 MB.

The same invariant is the **non-destructiveness proof for history** after the transplant:

```bash
head -c 216236906 "$DEST_TX" | sha256sum
# must equal 074487a7bd31324ece84462f5ff46a07703feeab94941e62f5b76d9af6d2a32a   [LIVE]
```

Verified live on a file that has since grown to 218,813,752 B / 47,551 lines through
normal use `[LIVE]`. **A byte-count decrease, or a prefix-hash change, means a
thinking-block-stripping import path ran. Halt and restore from quarantine.**

Record-boundary invariants (all measured true, all cheap):

```bash
tail -c1 "$TX" | xxd | grep -q '0a$'          || die "does not end on a newline"
tail -n1 "$TX" | python3 -c 'import json,sys; json.loads(sys.stdin.read())' || die "last line unparseable"
wc -l "$TX"                                    # must be monotone non-decreasing, never shrink
```

Structural invariants to re-assert after any placement (E7 baseline, `SKILL-SOURCE-FACTS.md` §2.7):
33,805 records with uuid · 33,705 distinct (100 known duplicates, contiguous at lines
1784–1883) · **0 dangling parents** · 28 roots · 3,436 leafUuids with 0 orphans · 21,859
assistant records of which 6,344 carry a thinking block · first `compact_boundary` at line 1884.

---

## 3. Live-file races — detecting a torn read

The origin transcript may be written while you copy it (V03). Two distinct tears:

| Tear | Symptom | Check | Fix |
|---|---|---|---|
| **Trailing tear** — copy stopped at a record boundary, origin has since grown | `L < R`, prefix hash matches | prefix invariant (§2) | none needed; optionally fetch `tail -c +$((L+1))` |
| **Mid-line tear** (V04) — copy stopped inside a 128 KB JSON line | last byte is not `\n`, or last line fails `json.loads` | the two commands above | truncate back to the last `\n`, **record `discarded_bytes`**, re-fetch the tail |

```bash
# Mid-line tear repair — never leave a half-record in place.
python3 - "$TX" <<'PY'
import sys, os
p = sys.argv[1]; sz = os.path.getsize(p)
with open(p, 'rb') as f:
    f.seek(max(0, sz - 1_000_000)); tail = f.read()
cut = tail.rfind(b'\n')
if cut == -1: sys.exit("no newline in last 1 MB — refuse to guess")
newsz = sz - (len(tail) - cut - 1)
print(f"size {sz} -> {newsz}  discarded_bytes={sz-newsz}")
if newsz != sz:
    os.truncate(p, newsz)
PY
```

**Quiesce detection before the copy** (PF06). Never assume; measure:

```bash
ssh "$REMOTE" "lsof '$REMOTE_TX' 2>/dev/null | tail -n +2"      # any writer?
a=$(ssh "$REMOTE" "stat -f%m '$REMOTE_TX'"); sleep 10
b=$(ssh "$REMOTE" "stat -f%m '$REMOTE_TX'")                     # Linux origin: stat -c%Y
[ "$a" = "$b" ] || echo "WARN: transcript still being written (mtime $a -> $b)"
```

**Sidecars have no prefix invariant** — they are many small files that appear and are
rewritten. Use a **quiesce loop** (V22): re-run the delta pass until two consecutive
passes transfer 0 bytes, max 3 attempts, then fail loudly rather than looping forever.

```bash
for i in 1 2 3; do
  out=$(rsync -a --stats "$REMOTE:$RC/projects/$PROJKEY/$SID/" "$DEST/claude/.../$SID/")
  n=$(printf '%s' "$out" | awk '/Number of regular files transferred/{print $NF}')
  echo "pass $i: $n files"; [ "$n" = "0" ] && break
done
[ "$n" = "0" ] || die "sidecars never quiesced — origin session is active"
```

**Clock skew is not a change signal** (V25). Measured skew between the two hosts was
within seconds, but the rule stands regardless: **mtime is an index, hash is the truth.**
Never use mtime as the sole change signal; compare mtimes only at 1-second resolution
(`--modify-window=1`) because APFS and ext4 both store ns but protocol-29 rsync rounds.

---

## 4. Checkpoint generations, `--link-dest`, and why SEALED is not cosmetic

Layout that worked `[LIVE]`:

```
_backups/mac1/
├── 20260801T120624Z/{project,claude,manifest,logs}   generation 1
├── 20260801T133617Z/{project,claude,manifest,logs}   generation 2  + SEALED
└── latest -> 20260801T133617Z
```

Each generation is built with `--link-dest` pointing at the previous one, so unchanged
files cost **one inode entry (~0 bytes)**. Marginal generation ≈ 250–450 MiB (the 206 MiB
transcript is always re-copied because its content changes) ⇒ ~4,000–7,000 generations
against 1.8 TiB free `[M]`. Space is a non-issue by three orders of magnitude.

### The sealing rule (V05)

**A hardlink farm is only safe if nobody writes through it.** A file in generation N that
is hardlinked from generations N-1, N-2, … shares one inode. Writing through that inode —
`--inplace`, `--append`, an editor that truncates and rewrites, a `chmod` on the wrong
tree, a `shutil.copy2` in the wrong direction — **silently rewrites every prior
generation**. Your entire backup history changes at once, and nothing reports it.

```bash
chmod -R a-w "$DEST/project" "$DEST/claude"    # seal the payload subtrees
touch "$DEST/SEALED"                            # sentinel at the generation root
```

Note the sentinel lives at the generation root, which stays writable; only `project/` and
`claude/` go read-only (`dr-xr-xr-x` on disk `[LIVE]`).

Detection that sealing held — re-verify an **older** generation, not the newest:

```bash
PREV=$CKPT_ROOT/<the generation you are rolling back to>
( cd "$PREV/project" && find . -type f -print0 | xargs -0 -P8 sha256sum ) \
  | sed 's|  \./|  |' | sort -k2 | diff - <(sort "$PREV/manifest/local-project.sha256") \
  && echo "prior generation intact"
```

Hard prohibitions in any script that passes `--link-dest`:

```bash
# PF13 — grep your own argv before running it.
case " ${RSYNC_ARGS[*]} " in
  *" --inplace "*|*" --append "*|*" --append-verify "*)
     die "FATAL: in-place flags with --link-dest would corrupt prior generations (V05)";;
esac
```

**Related hardlink fact `[M]`:** the origin project tree holds 62,273 hardlinked files
across 20,819 inodes, but **62,267 of them live under excluded dirs**; only 6 survive
(three inode-pairs of `aspera-scp-transfer{,.0}.log`). openrsync has no `-H`, so those 6
explode into independent copies — which costs nothing. **Document that the exclusion list
is load-bearing for hardlink safety, not just for size**, and check it has not drifted:

```bash
ssh "$REMOTE" "cd '$RT' && find . -type f -links +1 \
  -not -path './*/rust/target/*' -not -path './_research/re/*' | wc -l"   # expect <= 10
```

---

## 5. Publish only on success (M5)

v1 of `pull-checkpoint.sh` ran `ln -sfn "$DEST" "$ROOT/latest"` unconditionally. A crashed
run therefore became `latest`, and `latest` is the next run's `--link-dest` source — so a
gap propagated forward into every future generation, invisibly. That is a **C**ritical
vector (V02) because the corruption is in the *baseline*, not in the run that failed.

The correct shape:

```bash
if [ "$FAIL" -ne 0 ]; then
  log "INCOMPLETE — 'latest' NOT advanced. Inspect $DEST then re-run."
  touch "$DEST/INCOMPLETE"
  exit 1
fi
chmod -R a-w "$DEST/project" "$DEST/claude" 2>/dev/null
touch "$DEST/SEALED"                       # sentinel written LAST, after verification
ln -sfn "$DEST" "$ROOT/latest"             # ONLY now
```

Three sub-rules, each learned:

1. **`set -uo pipefail` without `-e`, plus an explicit `FAIL` accumulator.** With `-e` a
   partial failure aborts mid-tree and you learn about exactly one problem; with the
   accumulator you get the full damage report and a single gate at the end. rsync's exit
   code alone is insufficient (V01).
2. **`--link-dest` must point at the newest generation *containing the sentinel*, never at
   `latest` blindly.** `latest` is a convenience for humans; the sentinel is the contract.
   ```bash
   PREV=$(ls -1d "$ROOT"/*/ 2>/dev/null | sort -r | while read -r d; do
            [ -f "$d/SEALED" ] && { printf '%s' "${d%/}"; break; }; done)
   LD=(); [ -n "$PREV" ] && LD=(--link-dest="$PREV")
   ```
3. **`latest` must be a RELATIVE symlink.** It is currently absolute `[LIVE]`, so moving
   `_backups` silently breaks every baseline lookup (`SKILL-SOURCE-FACTS.md` §8 O7).
   ```bash
   ( cd "$ROOT" && ln -sfn "$(basename "$DEST")" latest )
   readlink "$ROOT/latest"        # must print a bare timestamp, not a leading /
   ```

**M6 corollary — sealing propagates.** `shutil.copy2` and plain `rsync -a` carry the
sealed `a-w` mode into the destination, which made the destination transcript read-only
and killed two `--apply` runs partway `[M]`. Every copy **out of** a sealed tree chmods
after, and every apply step is idempotent (delete-if-exists, after chmod, before re-copy):

```python
subprocess.run(["rsync","-a","--no-perms","--chmod=u+rwX,go-w", f"{CKPT}/project/", f"{DEST_ROOT}/"], check=True)
...
if os.path.exists(dest_tx):
    os.chmod(dest_tx, 0o600); os.unlink(dest_tx)      # idempotent re-run
shutil.copy2(src_tx, dest_tx)
os.chmod(dest_tx, 0o600)                               # copy2 carried a-w over — M6
assert sha256(dest_tx) == sha256(src_tx), "copy is not byte-identical"
```

---

## 6. Filename hazards — which direction each one bites

The two filesystems are asymmetric in two independent ways, and each asymmetry bites in
only **one** direction. Getting the direction wrong means either a false alarm on pull or
silent destruction on push.

| Hazard | macOS/APFS (origin) | Linux/ext4 (destination) | Bites on PULL? | Bites on PUSH? |
|---|---|---|---|---|
| **Case** | case-**insensitive** (preserving) | case-**sensitive** | **No** — the origin cannot hold `Foo.md` and `foo.md` simultaneously, so no collision can arrive | **YES, C-severity** — two files created on Linux merge into one on APFS; **one file's content is destroyed and rsync reports success** |
| **Unicode NFD/NFC** | APIs emit NFD; APFS normalizes on lookup, so `café`(NFC) and `café`(NFD) are the *same* file | bytes stored verbatim; the two are *different* files | **Warn** — NFD names arrive intact, but any later NFC-normalizing tool creates a second file | **YES, H-severity** — openrsync has **no `--iconv`**; nothing can fix it in flight |
| **Control chars / trailing space or dot** | hazardous in Finder/APFS | legal | warn | warn |

Current state on the real corpus `[M]`: **0 NFD names, 0 case collisions, 0 non-ASCII
filenames, 0 AppleDouble (`._*`), 0 sparse files, 0 files > 4 GB, 0 devices/FIFOs, 0
absolute symlinks, 0 broken symlinks, 0 ACLs, 0 BSD flags.** The risk is entirely
prospective — which is exactly why the scan must run every time rather than being
retired as "we checked once".

### The detection script

Runs on **both** sides, on **every** direction. **WARN on pull, FATAL on push.**

```python
#!/usr/bin/env python3
# hazard-scan.py <root> [--fatal]   exit 1 on any FATAL-class finding
import os, sys, unicodedata, collections
root = sys.argv[1]; fatal = "--fatal" in sys.argv
nfd, ctrl = [], []
case = collections.defaultdict(set)
for base, dirs, files in os.walk(root):
    for n in dirs + files:
        if unicodedata.normalize('NFC', n) != n:
            nfd.append(os.path.join(base, n))
        if any(ord(c) < 0x20 for c in n) or n.endswith((' ', '.')):
            ctrl.append(os.path.join(base, n))
        # fold NFC *and* case together so the compound case is caught too
        case[(base, unicodedata.normalize('NFC', n).lower())].add(n)
coll = {k: v for k, v in case.items() if len(v) > 1}
print(f"NFD-normalized (macOS-style) names: {len(nfd)}")
for p in nfd[:50]:  print("  NFD ", p)
print(f"case/NFC-fold collisions: {len(coll)}  (safe on ext4, FATAL if pushed to APFS)")
for k, v in list(coll.items())[:50]: print("  CASE", k[1], sorted(v))
print(f"control-char or trailing space/dot names: {len(ctrl)}")
for p in ctrl[:50]: print("  CTRL", p)
if fatal and (nfd or coll):
    sys.exit(1)
```

Expected output on a clean corpus, and the assertion to make about it:

```bash
python3 hazard-scan.py "$DEST"                       # pull: report
python3 hazard-scan.py "$LOCAL_TREE" --fatal || die  # push: hard gate, no exceptions
head -2 "$DEST/manifest/filename-hazards.txt"
# NFD-normalized (macOS-style) names: 0
# case-only collisions: 0  (safe on ext4, FATAL if pushed back to APFS)
```

### The `core.ignorecase` trap `[LIVE]`

A `.git/config` copied verbatim from macOS carries settings that describe *the origin's*
filesystem, and git honors them wherever the repo lands:

```
$ git config --local --list | grep -E 'ignorecase|precompose'
core.ignorecase=true          # <- git init on APFS wrote this. It is FALSE on ext4.
core.precomposeunicode=true   # macOS-only knob; inert on Linux, but a marker of Mac origin
```

`core.ignorecase=true` tells git the filesystem is case-insensitive. On ext4 that is a
lie, and git may then treat `Foo.md` and `foo.md` as one path — reintroducing the APFS
merge hazard *inside git* on a filesystem that does not have it. Check and correct on the
rescued copy (never on the origin):

```bash
git -C "$RESCUE" config --local core.ignorecase   # if 'true' on ext4:
git -C "$RESCUE" config --local core.ignorecase false
git -C "$RESCUE" --no-optional-locks status --porcelain | head   # confirm nothing appeared/vanished
```

---

## 7. Fragile-git rescue — the 0-commit index case

The origin repo `SimLab/acmeorg_simlab` had an **unborn HEAD**: `git init` + `git add`,
`git commit` never run `[M]`.

| Check | Origin value | What it means |
|---|---|---|
| `refs/` file count | **0** | no branch or tag ref was ever written |
| `logs/` (reflog) | **does not exist** | git creates it on the first ref update; none occurred |
| object type histogram | **427 blob, 0 tree, 0 commit** | the exact signature of add-without-commit |
| `.git/index` | **34,016 B, 338 entries** | the **only** copy of the blob→filename mapping |
| `git fsck` | all 427 loose objects **dangling** | one `git gc` deletes the entire project |

**The 338 staged files are one 34 KB file away from unrecoverable.** Blobs are
content-addressed: without the index there are 427 nameless zlib blobs and no way to
recover filenames except heuristic content matching.

### The order of operations, and why each step is where it is

```bash
# 0. COPY .git/ VERBATIM AND FIRST, before anything else touches the tree.
#    Then work only on the copy. The origin is never mutated.
RESCUE=/path/to/a/writable/copy/of/the/repo        # NEVER the origin's own .git

# 1. gc.auto=0 IS THE LITERAL FIRST OPERATION on the copy. Many porcelain commands
#    auto-trigger gc, and gc deletes dangling blobs outright — i.e. everything.
git -C "$RESCUE" config --local gc.auto 0
git -C "$RESCUE" config --local gc.autodetach false
git -C "$RESCUE" config --local gc.pruneexpire never
git -C "$RESCUE" config --local --list | grep '^gc\.'    # verify before proceeding [LIVE]

# 2. Verify the transferred state matches the origin's, BEFORE changing anything.
git -C "$RESCUE" --no-optional-locks ls-files | wc -l                    # expect 338
sha256sum "$RESCUE/.git/index"                                           # expect the recorded hash
find "$RESCUE/.git/objects" -type f -not -path '*/pack/*' | wc -l        # expect 427
git -C "$RESCUE" --no-optional-locks cat-file --batch-all-objects \
    --batch-check='%(objecttype)' | sort | uniq -c                       # expect 427 blob, 0 tree, 0 commit

# 3. Verify EVERY staged blob actually resolves. An index entry pointing at a missing
#    object is a coverage failure inside the object store, and it will only surface
#    when write-tree fails halfway.
git -C "$RESCUE" --no-optional-locks ls-files -s | awk '{print $2}' | sort -u \
  | while read -r oid; do git -C "$RESCUE" cat-file -e "$oid" || echo "MISSING $oid"; done
# real run: 320 unique OIDs, 0 missing [M]

# 4. DRY RUN the commit with plumbing. write-tree materializes the tree WITHOUT
#    moving any ref, so it is a pure test of whether the index is coherent.
TREE=$(git -C "$RESCUE" write-tree)     # real run: ef35e80119a3fc93e0b75d5d01f15099b48d9414 [LIVE]
git -C "$RESCUE" ls-tree -r "$TREE" | wc -l                              # expect 338
# only after the tree verifies, mint the commit and move the ref:
C1=$(GIT_AUTHOR_DATE='2026-07-02T11:01:28-07:00' GIT_COMMITTER_DATE='2026-07-02T11:01:28-07:00' \
     git -C "$RESCUE" commit-tree "$TREE" -m 'Rescue commit: import staged working state from mac1')
git -C "$RESCUE" update-ref HEAD "$C1"

# 5. PROVE commit #1 == the index, byte for byte.
git -C "$RESCUE" ls-tree -r HEAD | awk '{print $3, $4}' | sort > /tmp/tree.oids
git -C "$RESCUE" --no-optional-locks ls-files -s | awk '{print $2, $4}' | sort > /tmp/index.oids
diff /tmp/tree.oids /tmp/index.oids && echo "commit #1 byte-matches all 338 staged files"
```

### The crucial detail: **the index may be stale relative to the working tree**

An index-only rescue is *not* a rescue. The `.git/index` records the state at the moment
of the last `git add` — 2026-07-02 on this repo — and the session kept working afterwards.
Measured on the rescued repo `[LIVE]`, commit #1 → commit #2 is:

```
$ git diff --name-status d628074 ecd0687 | awk '{print $1}' | sort | uniq -c
     26 A      # untracked: never added at all
      6 M      # modified: newer on disk than the blob the index points at
```

The 26 untracked files include **an entire Rust crate**, `rust/crates/control` (16
files: `Cargo.toml`, `src/{assets,compat,lib,observ,proxy,registry,toxics,wire}.rs`,
5 integration tests, 2 vector JSONs, 3 assets). E12 later proved that crate is a
**required workspace member** — without it the Rust build does not even configure `[M]`.
The 6 stale-index files are `python/acmeorg_simlab/{rust_datapath,toxics,toxiproxy}.py`
and `rust/crates/{cli/src/main.rs,datapath/src/lib.rs,datapath/tests/udp_fanout.rs}`
`[LIVE]`. Total delta: **32 files, 4,090 insertions, 51 deletions**.

> A naive index-only rescue would have produced a green "338/338 verified" report and
> lost a required crate plus six files of newer work. **Coverage again: the index is a
> path list produced by the *thing being rescued*, so it cannot be the coverage oracle.**

Detect the staleness explicitly before you believe the index:

```bash
git -C "$RESCUE" --no-optional-locks status --porcelain | wc -l          # total dirt
git -C "$RESCUE" --no-optional-locks diff-files --name-only | wc -l      # stale index entries
git -C "$RESCUE" --no-optional-locks ls-files --others --exclude-standard | wc -l   # untracked
```

The second commit captures both categories, and is deliberately separate so the
historical staging decision stays auditable:

```bash
git -C "$RESCUE" add -A
git -C "$RESCUE" commit -m 'Working-tree state at time of migration'
git -C "$RESCUE" ls-tree -r HEAD | wc -l          # 364 = 338 + 26  [LIVE]
```

Also note: `.gitignore` excludes `_research/`, `_vetting/`, `_conda/`, `_scratch/`,
`rust/target` — so **everything ignored is not represented in git at all** and must be
preserved by file copy, not by git. Git is a rescue mechanism for the 338 names, not a
transport for the tree.

### Prohibitions during a git rescue

1. **Never run any mutating git command on the origin** — `add`, `commit`, `stash`,
   `checkout`, `switch`, `restore`, `reset`, `gc`, `prune`, `repack`, `fetch`, `pull`,
   `push`, `worktree`, `config`.
2. **`git status` without `--porcelain` can rewrite `.git/index`** (stat-cache refresh).
   Always `git --no-optional-locks status --porcelain`, or read `.git/index` bytes directly.
3. `git fsck` is read-only but **may create `.git/gc.log`** in some versions. Treat it as
   a one-time, deliberately-approved exception; assert `gc.log` absent afterwards.
4. **19 nested `.git` dirs exist in the tree** (18 vendored upstream clones + the real
   one). Treat every `.git` as opaque bytes; never `--recurse-submodules` — they are not
   submodules, they are plain nested clones.
5. **The durable fix (creating commit #1 on the origin) is a write to the origin.** Report
   it; do not perform it. Creating or pushing a GitHub repo publishes content under the
   user's identity and requires an explicit, separate go-ahead.

---

## 8. Non-destructiveness proof for the origin

### Scope the claim honestly

The provable claim is **"no modification to the N target subtrees"**, not "no byte on the
machine changes". ssh login shells write `.zsh_history`; some git subcommands write
`stats-cache.json`. Anything stronger is a false claim. **atime drift is explicitly
accepted** — reading updates it, and a `noatime` remount is a forbidden system-settings
change.

### The exact command

```bash
# fingerprint.sh — runs on the origin over ssh; output captured LOCALLY, never written remotely.
# macOS (BSD stat):
cd "$SUBTREE" && find . \( -type f -o -type l -o -type d \) \
  -exec stat -f '%m %z %Sp %i %N' {} + | LC_ALL=C sort -k5 | /sbin/sha256sum
# Linux origin (GNU stat):
cd "$SUBTREE" && find . \( -type f -o -type l -o -type d \) \
  -exec stat -c '%Y %s %A %i %n' {} + | LC_ALL=C sort -k5 | sha256sum
```

Fields are chosen deliberately: **mtime, size, mode, inode, name**.

- **`atime` excluded** — reading updates it, so including it would make the fingerprint
  fail by construction. Not data loss; no consumer reads atime.
- **`ctime` excluded from the primary** — it is a *good* tamper signal but also changes on
  unrelated system activity (Spotlight, Time Machine). Capture it as a **second, advisory**
  fingerprint so a difference distinguishes "we changed it" from "something else touched it".
- **`inode` included** — it detects a delete+recreate that coincidentally preserves mtime
  and size, the exact signature of a botched atomic replace.

**Capture `pre` as well as `post`.** The original script captured only `post`, leaving
nothing to compare against. Also keep the full per-file `remote-project.stat` both times
so a mismatch can be **localised**, not merely detected.

```bash
ssh "$REMOTE" 'bash -s' < fingerprint.sh > "$DEST/manifest/fingerprint.pre"    # before any pull
...
ssh "$REMOTE" 'bash -s' < fingerprint.sh > "$DEST/manifest/fingerprint.post"   # after
diff "$DEST/manifest/fingerprint.pre" "$DEST/manifest/fingerprint.post" \
  && echo "ORIGIN UNCHANGED" || die "origin subtree changed during the run"
```

Ship remote helper scripts **over stdin** (`ssh host 'python3 -' <<script`) and never
write them to the origin — that is what makes "we wrote nothing to the origin" literally
true rather than merely intended. Constrain to the remote Python's stdlib (3.9.6 on the
measured origin).

### The dedicated git-untouched assertion

Run pre and post, in addition to the fingerprint:

```bash
ssh "$REMOTE" "cd '$RT/SimLab/acmeorg_simlab' && \
  git --no-optional-locks ls-files | wc -l && \
  shasum -a 256 .git/index && \
  find .git/objects -type f -not -path '*/pack/*' | wc -l && \
  stat -f '%m %c %z' .git/index && \
  test -e .git/gc.log && echo 'GC.LOG PRESENT — FAIL' || echo 'no gc.log'"
```

Worked example from the real survey `[M]` — this is the evidence format every run should
emit, and it is cheap:

| Assertion | Baseline | After | Result |
|---|---|---|---|
| `.git/index` size | 34,016 B | 34,016 B | pass |
| `.git/index` mtime | 2026-07-02T11:01:28 | same | pass |
| `.git/index` **ctime** | 2026-07-02T11:01:28 | same | pass (no metadata write either) |
| loose objects | 427 | 427 | pass |
| index entries | 338 | 338 | pass |
| `.git/gc.log` created by `fsck`? | absent | absent | pass |
| transcript size | 216,236,906 | 216,236,906 | pass |
| transcript sha256 | `074487a7…` | `074487a7…` | pass |

### Enforce it, do not intend it

Route every origin command through **one ssh chokepoint with a deny-regex**, so
read-only-ness is a property of the code rather than of your attention:

```bash
ro_ssh() {   # usage: ro_ssh '<command>'
  case "$1" in
    *" > "*|*" >> "*|*tee*|*rm\ *|*mv\ *|*cp\ *|*mkdir*|*touch*|*chmod*|*chown*|*ln\ *|\
    *"git add"*|*"git commit"*|*"git gc"*|*"git prune"*|*"git repack"*|*"git checkout"*|\
    *"git reset"*|*"git stash"*|*"git fetch"*|*"git pull"*|*"git push"*|*rsync*--delete*)
       echo "DENIED (origin is read-only): $1" >&2; return 9;;
  esac
  ssh -o BatchMode=yes "$REMOTE" "$1"
}
```

Serialize ssh calls or set `ControlMaster=auto` with retries — a burst of parallel calls
produced `mux_client_request_session: session request failed` / `ControlSocket … already
exists`, which falls back to a non-multiplexed connection and is easily misread as a
remote failure `[M]`.

---

## 9. Rollback at each gate

Every gate has a defined rollback, and the rollback is itself a destructive act — so it
starts by sealing the current state.

These twelve **RB** points are the *internal* checkpoints of the pull-and-install machinery
and are deliberately finer-grained than the nine procedure gates `G0`–`G8` in `SKILL.md`.
They map on as: RB0 → G0/G1 · RB1–RB7 → G3 (the checkpoint's own build, verify, seal and
publish steps) · RB8 → G5 · RB9 → G6 · RB10 → G8's origin-unchanged proof · RB11 → G8's
post-launch re-verify. `SKILL.md`'s `G`-numbers are the ones to quote to a user; these are
the ones to quote in a post-mortem.

| # | Gate | Check | On failure — rollback |
|---|---|---|---|
| **RB0** | Preflight | PF01–PF14 (evidence base §7): ssh reachable, paths exist, free space ≥ 3× payload, prior generation has its sentinel, no `--inplace` with `--link-dest`, git baseline 338/427 | Nothing has been created. Fix the precondition and re-run. No cleanup. |
| **RB1** | Origin manifest built | line count ≥ floor (`RN -lt 24000 && die`) | An exclude is over-broad or the origin moved. **Do not transfer.** Print per-pattern match counts, fix the anchor, re-run. `$DEST` holds only manifests; `rm -rf "$DEST"`. |
| **RB2** | Transfer | every `rsync` rc == 0 | Re-run the same generation — rsync is resumable and `--link-dest` makes a re-run nearly free. Never advance `latest`. If it fails twice, `touch "$DEST/INCOMPLETE"` and stop. |
| **RB3** | **Coverage** | `grep -c '^<'` == 0 after separating MISSING from CORRUPT | Read `MISSING.txt`. If the paths sit under an exclude, the exclude is the bug — fix and re-run the whole generation. Never hand-copy the missing files into a generation that failed its gate; the generation is the unit. |
| **RB4** | **Fidelity** | `grep -c '^>'` == 0; `CORRUPT.txt` empty | Suspect a torn read (§3) or a truncated transfer. Re-transfer only the listed paths, then **re-run RB3 and RB4 in full** — a targeted repair does not re-establish the gate. |
| **RB5** | Hazard scan | 0 NFD, 0 case collisions (WARN on pull, FATAL on push) | On push: **halt**. There is no in-flight fix (openrsync has no `--iconv`); a human must rename. On pull: record and continue. |
| **RB6** | Seal | `project/` and `claude/` are `a-w`; `SEALED` present | If sealing failed, do not publish — an unsealed generation used as `--link-dest` puts every prior generation at risk. Retry the `chmod`; if the filesystem refuses, mark `INCOMPLETE`. |
| **RB7** | Publish | `latest` advanced *only* now, relative symlink | If `latest` was advanced in error: `( cd "$ROOT" && ln -sfn "$(basename "$LAST_GOOD")" latest )`, then re-verify the restored generation against its own manifest before using it as `--link-dest`. |
| **RB8** | Destination placement | `test -s "$P/$SID.jsonl"`; `sha256(dest) == sha256(src)`; after any append, `sha256(dest[0:prefix_len]) == sha256(src)` | The transplant is idempotent by construction (chmod → unlink → copy → chmod). Delete the destination transcript and re-run `--apply`. **Never** repair a transcript in place. |
| **RB9** | Destination install coverage (M4) | counts at the **destination** paths match the origin inventory (§1) | Re-run only the failing install step; then re-assert **all** counts, not just the one you fixed. A `tool-results` shortfall after the first launch is expected decay, not a failure. |
| **RB10** | Origin non-destructiveness | `fingerprint.pre` == `fingerprint.post`; git-untouched assertion identical | A difference means something wrote to the origin. **Stop everything**, diff the per-file `.stat` captures to localise it, and report to the user. Do not attempt to "restore" the origin. |
| **RB11** | Post-launch re-verify | transcript prefix hash unchanged; `wc -l` monotone; structural invariants (§2) hold | A prefix change or a byte-count **decrease** means a stripping import path ran (`claude://resume`, CLI-session import, or the recovery UI). Halt; restore the transcript from the sealed checkpoint into the destination path (chmod → unlink → copy → chmod) and re-verify. |

### Rehearsed rollback of a whole generation

```bash
# 1. Seal the current state FIRST — rollback is itself destructive.
tar --zstd -cf "_backups/sealed/pre-rollback-$(date -u +%Y%m%dT%H%M%SZ).tar.zst" -C "$TARGET" .
# 2. Verify the generation you are rolling back TO, before you trust it.
diff <(cd "$GEN/project" && find . -type f -print0 | xargs -0 -P8 sha256sum | sed 's|  \./|  |' | sort -k2) \
     <(sort "$GEN/manifest/local-project.sha256") && test -f "$GEN/SEALED" || die "generation not trustworthy"
# 3. Dry run, show the diff, get confirmation. NO --inplace. --delete only after the dry run.
rsync -a --delete -n "$GEN/project/" "$TARGET/"
# 4. Restore, then re-verify against the generation's manifest.
rsync -a --delete --no-perms --chmod=u+rwX,go-w "$GEN/project/" "$TARGET/"
```

**An unrehearsed backup is not a backup** (PO14). Periodically restore a generation into a
scratch dir and re-verify its manifest there.

---

## 10. Two meta-rules that catch the checks themselves

**M7 — a check must first assert that the thing it checks actually executed.** A grep for
signature errors "passed" because the run had died earlier at `Not logged in` and never
reached the API `[M]`. Absence of an error is not evidence of success.

> Prefer **positive** signals over negative ones. The E13 script encodes this correctly:
> its PASS condition is the **presence** of `ECONNREFUSED|fetch failed|connect` — proof
> that the loader got all the way to the network layer — not the absence of an error string.

```bash
# WRONG:  grep -q 'signature is not valid' log || echo PASS
# RIGHT:
grep -qE 'ECONNREFUSED|fetch failed|connect' log || die "run never reached the network — check is vacuous"
grep -q  'signature is not valid' log && die "signature rejected"
echo PASS
```

**M3 — whitelist, never blacklist, when copying out of a `~/.claude`.** The origin
`~/.claude` is 5.5 GB; the session is 370 MiB of it. `--include='backups/***'` swept
another account's `machineID`/`userID`/`oauthAccount`, 1,068 unrelated prompts, and two
unrelated sessions' task stores `[M]`. The enforcement shape that works is **an allowlist
of paths to copy plus an independent denylist assertion executed over the staged bytes** —
the allowlist alone is what M3 defeated:

```bash
# Independent denylist assertion over what was actually staged.
for bad in .credentials.json .claude.json backups history.jsonl telemetry sessions \
           shell-snapshots policy-limits.json stats-cache.json config.json ant-did; do
  n=$(find "$DEST/claude" -name "$bad" | wc -l)
  [ "$n" -eq 0 ] || die "DENYLIST VIOLATION: $n × $bad staged"
done
find "$DEST/claude" -name '*.DS_Store' -delete
grep -rl 'sk-ant-' "$DEST/claude" 2>/dev/null | head && die "token material staged"
```

Never read, print, or checksum `.credentials.json` — it *is* the account identity.

---

## 11. Known gaps in this doctrine (do not re-litigate; do close)

| # | Gap | Status |
|---|---|---|
| O1 | Nine sibling-project workflow scripts backed up, never installed — the M4 pattern, still open `[LIVE]` | Fix: install each sibling key's `<SID>/workflows/scripts/` under `mangle(realpath(<corresponding dest subdir>))`. |
| O2 | `tool-results/` decays at the destination (11 → 10) `[LIVE]` | Expected. Verify counts *after* first launch; treat as informational. |
| O7 | `_backups/mac1/latest` is an **absolute** symlink `[LIVE]` | Make it relative (§5). |
| O11 | The coverage diff (E0) was never formally re-run with a printed exclusion list and per-pattern match counts | ~10 s, read-only, probably already green (both DIFF files are 0 bytes). Add `rsync -n -a -c --itemize-changes` as the second opinion. |
| O12 | RISK-01 open on the **origin**: the unborn HEAD still has no commit #1 there | The rescue copy is safe; the origin's 338 names still hang on one 34 KB file. The fix is a write to the origin and must be done by the user. |
| — | The brief-level count of stale-index files was recorded as "6 modified + 18 untracked"; the rescued repo on disk shows **26 added + 6 modified = 32** `[LIVE]` | Trust the disk. Re-derive with `git diff --name-status d628074 ecd0687`. |

---

## 12. Cross-platform notes for every script in this file

- POSIX-ish bash or `python3` **stdlib only**. Must run on macOS *and* Linux — the origin
  may be either.
- macOS: no GNU `timeout` (use `perl -e 'alarm N; exec @ARGV'`); `stat -f` not `-c`; BSD
  `find` rejects `-newermt @epoch`; `shasum -a 256` exists but `/sbin/sha256sum` is **5×
  faster** and byte-identical; `zstd` may be absent.
- macOS `rsync` is **openrsync** (protocol 29): **no** `-H`, `-X`, `-A`, `-S`, `--iconv`,
  `--fake-super`, `--protect-args`. It **does** have `--link-dest`, `--checksum`,
  `--itemize-changes`, `--numeric-ids`, `--delay-updates`, `--partial`, `-n`.
- `realpath` differs across platforms. Compute the physical path with
  `python3 -c 'import os,sys;print(os.path.realpath(sys.argv[1]))'` or `cd "$d" && pwd -P`.
  Never `$PWD`, never `pwd -L`, never a raw user string.
- **Never `pgrep -af '<pattern>'` to test whether an instance is running** — it
  self-matches (2 false positives measured). Use
  `ps -eo pid,comm,args --no-headers | awk '$2 ~ /claude/ && /acct-b/'`.
  **Never `pkill -f <pattern>`** — it self-matched and killed a run mid-experiment (exit 144).
