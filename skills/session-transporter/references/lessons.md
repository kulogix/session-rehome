# lessons.md — post-mortem of the reference migration

The reference run **succeeded**: a 216 MB Claude Code session was moved from a macOS host under one
Anthropic account to a Linux host under a different account, byte-for-byte, and resumed. It also made
eight distinct mistakes on the way, several of which destroyed or nearly destroyed data, and one of
which is **still open at the time of writing**.

This file is deliberately blunt. Its only value is honesty. A softened version of it is worse than no
version, because a softened version reads as reassurance and this file exists to be alarming.

Everything below is measured. Numbers are real. Evidence lives in
`references/evidence-base.md`, shipped with this skill — the distilled index of the source
session's recon, experiments and plans. The underlying corpus (the `R01`–`R12` recon documents,
`MASTER-PLAN.md`, `LADDER-RESULTS.md`) was **not** shipped; every number quoted here is restated
in the evidence base.
Identifiers used here — `M1`–`M8` (mistakes), `F1`–`F24` (things that look true but are false),
`O1`–`O12` (open issues), `K1`–`K22` (confirmed facts), `T1`–`T12` (tripwires) — are stable across
the skill.

---

## Part 1 — The eight mistakes

### M1 — An over-broad exclude destroyed the payload

**What was done.** `pull-checkpoint.sh` v1 carried two rsync excludes on one line:

```
--exclude='_research/re/rust/'      # intended: skip ~1.1 GB of cargo output
--exclude='_research/re/target/'    # intended: skip build output, because it is called "target"
```

**The damage.** The first exclude did not skip a build directory. It dropped the **entire subtree**:
**26 files / 1,472,179 bytes** of unversioned, never-committed FASP Rust source. Among them
`_research/re/rust/fasp-core/src/cap.rs`, 6,547 bytes — the **CAP-TLV keystone, tracker item #148**,
which the session's own final assistant message named as the load-bearing piece of work in progress
— and `rust/parity/codec_vectors.json`, the 412-vector golden corpus. None of it existed in any git
repository on either host. Only `_research/re/rust/target/` was cargo output. The coverage diff, when
finally run, read **26 files on the origin vs 0 locally**.

The second exclude was a near-miss of the same shape. `_research/re/target/` is **not** cargo output.
It is the ground-truth oracle drop directory: `ascp`, `ascp_lic` (the license-patched binary, an
irreproducible RE output), `ascp_srv`, `ascp.i64` (134,176,621 B), `ascp_srv.i64` (51,186,707 B),
`aspera-license`, `aspera.conf`. The project's own standing law is that the genuine binary, not the
Python oracle, is ground truth. At audit time these were confirmed present on the origin and **absent
locally**. After the exclude was rewritten and the pull redone, E11 verified all seven byte-identical,
**7/7**.

**Why it was not caught immediately.** Three reinforcing reasons.
1. Both patterns name a directory that in almost every repository *is* build output. The excludes
   looked not merely acceptable but obviously correct.
2. `rsync` prints no per-pattern match count. An exclude that skips 26 irreplaceable files and one
   that skips 24,000 object files produce **identical log output**: silence.
3. The checkpoint's own verification (see M2) hashed only what had been pulled, so files that were
   never pulled were invisible **by construction**. And the checkpoint was 1.6 GB — a 1.44 MB hole is
   0.09 % of the byte count, well inside the noise of any size-based sanity check anyone would think
   to write.

**What caught it.** An adversarial re-read of the script's own exclude list *against a remote
directory listing* — not against the script's intent. One of four independent critiques run over the
plan and artifacts. Recorded as blockers C1/S1 and C2.

**The guard now in the skill.**
- Every exclude is **anchored** with a leading `/` (`--exclude='/_research/re/rust/target/'`, never
  `--exclude='target/'`). Anchoring is what turns "any directory named X anywhere" into "this one
  path".
- Every exclude is **justified against a listing** before it is written, and the run prints a
  **per-pattern match count**. An over-broad pattern must show up as a **number**, never as silence.
- A **magnitude floor** on the manifest: `[ "$RN" -lt 24000 ] && die "remote manifest suspiciously
  small ($RN)"`. This is the cheapest possible detector for "an exclude ate a subtree".
- **Never pattern-match on a directory name** (F8, F9). Names are not semantics. `target/` was the
  oracle; `_research/re/rust/` was the source.

---

### M2 — Verification that verified nothing

**What was done.** v1's verification built `local-project.sha256` by hashing the local tree, and
compared it against `remote-project.stat`, which held size/mtime/name only — and covered **nothing**
under `~/.claude`, i.e. nothing of the 733 MB that includes the 216 MB transcript and all 1,991
sidecar files. In effect the checkpoint hashed the local copy and compared it to itself. It then
logged `VERIFIED`.

**The damage.** No bytes were lost to M2 directly. The damage is that M2 is what made M1 invisible,
and would have made a torn transfer, a truncated file, or a dropped subtree equally invisible. It
issued a certificate of completeness for a checkpoint that was missing the keystone source file.

**Why it was not caught immediately.** It produced a green result and a manifest file on disk. That is
exactly what a working verification produces. The word "verified" in the log line was **true about
fidelity and silent about coverage**, and nothing in the output distinguished the two.

**What caught it.** Blocker C3/S12, then a coverage diff run directly against the origin — which
returned **26 missing files that every candidate design's verification would have called "fully
verified"**.

**The guard now in the skill.**
- The reference manifest is built on the **remote side**, by an independent `find` on the origin, and
  diffed against a locally-generated manifest. Phase B.
- **Coverage and fidelity are two separate gates, separately reported.** In the diff output,
  `grep -c '^<'` is a coverage failure (files present on the origin, absent locally);
  `grep -c '^>'` and any differing hash on a shared path are fidelity failures. A single "VERIFIED"
  line is forbidden — it hides one of them. *A corpus can be 100 % faithful and 60 % complete.*
- An **independent second opinion** using a different digest family: `rsync -n -a -c
  --itemize-changes` (MD4/MD5 rolling checksums) must also come back empty. Uncorrelated mechanism,
  uncorrelated failure modes.
- For the transcript specifically, the **prefix invariant**, which is stronger and cheaper:
  `sha256(remote_bytes[0:L]) == sha256(local_bytes[0:L])` for `L = local size`, `L <= remote size`.
  JSONL is append-only, so this tolerates concurrent appends, makes extension cost only the delta, and
  *is* the test that would falsify the append-only hypothesis if it were wrong.

---

### M3 — Over-collection of secrets

**What was done.** The `~/.claude` include list carried `--include='backups/***'`.

**The damage.** Onto this disk, into `/home/dana/Projects/SimLab/` — a tree earmarked for `git init` —
landed:
- **five copies of another Anthropic account's `~/.claude.json`**, 54,354 B each, each containing
  `machineID`, `userID`, and a 19-key `oauthAccount` block with email address, account UUID
  `aaaaaaaa-…`, organization UUID, organization role and billing type, plus 21 absolute macOS project
  paths;
- that account's **`history.jsonl`**: 1,068 records / 433,604 B, of which **1,060 lines belong to a
  completely unrelated project** — an interactive prompt history that has nothing to do with the
  session being migrated (it contains **0** records for the session id);
- **two unrelated sessions' task stores**.

Separately and in the same spirit of over-collection, `_research/re/server_keys/host_rsa.key`
(1,679 B) and 78 MB / 500 files of `_research/re/captures/` arrived at mode 0755/0644 in that same
git-initializable tree — and per the project's own reverse-engineering finding, those captures record
the SSH channel in which the FASP session AES key travels **in cleartext**.

**Why it was not caught immediately.** `backups/` reads as "the backup directory — obviously take
it". It is in fact a five-deep rolling ring of `~/.claude.json` and **nothing else** (F14). Nothing
anywhere in `~/.claude` backs up the 216 MB transcript or the 432 KB memory store. The include line is
one word long and feels conservative, which is precisely the problem: a blacklist mindset makes
"take the directory that sounds like backups" seem safe.

**What caught it.** Blockers C5 and C7. And separately, the **user** named
`<user-data-dir>/config.json` explicitly — a file that appeared in **zero** candidate design denylists
despite carrying `oauth:tokenCache` (668 chars) and `oauth:tokenCacheV2` (1,308 chars) of encrypted
OAuth material (U1, F6).

**The guard now in the skill.**
- **Whitelist, never blacklist, when copying out of a `~/.claude`.** The origin `~/.claude` was 5.5 GB
  across 48 project directories; the session is 370 MiB of it. `find ~/.claude -name '*<SID>*'`
  returns exactly **8 roots**. Enumerate them; recurse them fully (a `-maxdepth 1` sweep of
  `subagents/` shows 104 entries and misses `subagents/workflows/`, which is **38 % of all session
  bytes**); copy nothing else.
- **Plus an independent denylist assertion executed over the staged bytes**, exiting non-zero on any
  hit. This is not redundancy. *The allowlist alone is what M3 defeated* — one over-broad include line
  is one typo from disaster, and the five foreign `oauthAccount` blobs are the proof.
- **The only file the skill reads or writes inside a user-data-dir is
  `claude-code-sessions/<acct>/<org>/local_*.json`.** Not `config.json`, not `Cookies*`, not
  `Local State`, not `Local Storage/`, not `IndexedDB/`, not `ant-did`.
- `.credentials.json` is **never read, never printed, never checksummed** — it *is* the account
  identity.
- Secrets found in the payload are quarantined at 0700 **outside any git-initializable path**, tagged
  `CONTAINS_SECRETS` so archive/git/artifact code paths refuse them, and `.gitignore` is written as
  the **first** operation of any git work, before `git init`/`git add`.

---

### M4 — Backed up but never installed

**What was done.** Skills and plugins were pulled into the checkpoint. They were then never installed
at the destination. The gap was invisible because the backup looked complete.

**The damage — and this one is still live.** Measured fact K8: **skills are enumerated at CLI process
startup and cached for the process lifetime.** A skill added mid-session does **not** appear in the
next turn's system prompt; only a fresh process sees it. So a session launched before the install runs
its entire life without them, and nothing announces the absence.

Verified on disk while writing this file: the checkpoint holds **five sibling project keys** carrying
**9 workflow scripts / 76,374 B** (`<ORIGIN_KEY>--research-re`, `…--research-re-rust`,
`…--research-re-tools-devio-fasp-diag`, `…-SimLab-acmeorg-simlab`, `…-SimLab-acmeorg-simlab-rust`).
`~/.claude/projects/` at the destination contains **no sibling keys at all**. `transplant.py` copies
`<ORIGIN_KEY>/<SID>/` and `<ORIGIN_KEY>/memory/` and nothing else. Those 9 scripts are unreachable
today. That is **O1**, the exact M4 pattern, **still open**.

A second instance of the same failure, in the opposite direction (O6): the whitelist entry for skills
was a bare `"skills"`, so everything came across wholesale. Measured live today: `~/.claude/skills` is
**323 MB, of which 321 MB is one skill** — `scholarly-pdf-acquisition`, whose ~331 MB `.venv` bundles
two ~114 MB Node runtimes and is hard-bound to `/opt/anaconda3/envs/pvt_asyncvnc`, an interpreter that
cannot exist on the destination. The recon document R01 had **explicitly recommended excluding it**.
Total *authored* content across all 12 skills is ~2.5–2.9 MB. Also copied and installed:
`non-invasive-host-automation.skill` (32 KB) — a founding-revision **zip** carrying 8 tripwires
against the live skill's 18, i.e. exactly the "silently lose a month of evolution" failure that had
already been written down as a known hazard.

**Why it was not caught immediately.** "Backed up" and "installed" produce the same feeling of
doneness, and the checkpoint manifest is green for both. There was no assertion executed **at the
destination path**. Every check in the run pointed at the checkpoint.

**What caught it.** Nothing, during the run. O1 was found by the post-hoc audit that produced this
file, and is still unfixed. That is the honest answer.

**The guard now in the skill.**
- An explicit **"shared assets installed at destination"** gate, distinct from "shared assets backed
  up", asserting file counts and paths **at the destination**, never at the checkpoint.
- The install gate is sequenced **before launch**, because of K8.
- The gate covers the **sibling project keys**: for each sibling, copy its `<SID>/workflows/scripts/`
  into `mangle(realpath(<corresponding destination subdirectory>))/<SID>/workflows/scripts/`.
- Skill copying whitelists skill **names**, not the `skills/` directory, and audits any `scripts/`
  for `#!/bin/zsh`, `brew`, `otool`, `codesign` and architecture-specific binaries before copying
  anything executable.
- Related, and worth its own line: after the first launch, re-verify sidecar counts. The destination
  CLI's own retention sweeper prunes `tool-results/`. Checkpoint has **11** blobs; the destination has
  **10** (`bmdwv27oc.txt` is gone, and the directory mtime is *after* the transplant). Verified live.
  Treat `tool-results/` as a decaying store, copy sidecars late, and count after launch, not before.

---

### M5 — Unconditional publish

**What was done.** `pull-checkpoint.sh` v1 ran `set -uo pipefail` **without `-e`**, logged each
rsync's return code without gating on it, and then executed
`ln -sfn "$DEST" "$ROOT/latest"` **unconditionally**, at line 108. The torn-read check merely
`touch`ed a warning file.

**The damage.** `latest` pointed at a generation with no completeness sentinel — and there was no
sentinel to point at, because none was ever written (`ls manifest/ | grep -i complete` → nothing). The
next run selects its `--link-dest` baseline from `latest`, so **a crashed or partial generation
becomes the hardlink baseline for every subsequent generation.** With `chmod -R a-w` not yet applied,
a single in-place write through a shared inode (`sed -i`, an editor, `rsync --inplace`) then rewrites
**every prior generation** at once. A failed run does not merely fail; it poisons the future.

**Why it was not caught immediately.** Publishing on failure produces no error output whatsoever. The
symlink is present, it points somewhere real, the directory has files in it. The failure is only
observable on the *next* run, as corruption of a baseline nobody is looking at.

**What caught it.** Blocker C4/S7/U10, from reading the script's own tail (`tail -3` shows the
unconditional `ln`) and checking for a sentinel that did not exist.

**The guard now in the skill.**
- An explicit `FAIL` accumulator (`set -uo pipefail` deliberately without `-e`, so a partial failure
  is *recorded* rather than aborting mid-tree) checked before publish. `die()` sets `FAIL=1`.
- The `SEALED`/`COMPLETE` sentinel is written **last**, after verification passes.
- `ln -sfn` runs **only** when `FAIL -eq 0` **and** both DIFF files are empty. On failure: `touch
  INCOMPLETE`, leave `latest` where it was, `exit 1`.
- `--link-dest` selects the newest generation **containing the sentinel**, never `latest` blindly.
- `chmod -R a-w` on seal, before publishing — this is what makes the hardlink ratchet
  one-directional.
- **Never** combine `--inplace` / `--append` / `--append-verify` with `--link-dest`. Preflight greps
  the rsync argv and fails if they co-occur.
- Make `latest` a **relative** symlink. It is absolute today (O7), so moving `_backups` would silently
  break every baseline lookup.

---

### M6 — Sealed-source permission propagation

**What was done.** The seal step (`chmod -R a-w` on the checkpoint) is correct and load-bearing — see
M5. `transplant.py` then used `shutil.copy2` to place the transcript, and `copy2` carries mode bits.
The destination transcript therefore arrived **read-only**.

**The damage.** Two `--apply` runs failed partway. The failure is self-perpetuating: a partial run
leaves a read-only file at the destination, so the naive retry fails **identically**, and stays
failing until someone chmods by hand and works out why.

**Why it was not caught immediately.** Correct hygiene at one step became a defect at the next. The
seal and the copy were written at different times, by different reasoning, each locally correct. The
interaction is only visible at runtime.

**What caught it.** The runs themselves. Twice.

**The guard now in the skill.**
- `chmod` after **every** copy out of a sealed tree. For rsync: `--no-perms --chmod=u+rwX,go-w`. For
  Python: an explicit `os.chmod(dst, 0o600)` immediately after `shutil.copy2`.
- Every apply step is **idempotent and re-runnable**: chmod-then-`unlink` if the destination exists,
  then re-copy. A re-run of a half-finished apply must be a no-op or a fix, never a hard failure.
- This is a general rule, not a transcript rule: any pipeline with a *sealed* intermediate stage has
  this bug latent in every step that reads from it.

---

### M7 — A false PASS

**What was done.** A grep for `thinking.signature` rejection errors was run over a run log, found
nothing, and reported **PASS**.

**The damage.** A gate that could never fail was counted as positive evidence that cross-account
signature replay works. The run it inspected had died earlier at `Not logged in` and **never reached
the API**. There had never been a request for a signature to be rejected on.

**Why it was not caught immediately.** The check's output is **identical** in the two cases "ran, and
was clean" and "never ran". Absence of an error is not evidence of success. This is the single most
seductive shape of bad check, because it is also the easiest one to write.

**What caught it.** Reading the run log instead of the check's verdict.

**The guard now in the skill.**
- **Every check first asserts that the thing it is checking actually executed.** No exceptions.
- **Prefer positive signals over negative ones.** The canonical example now in the skill is
  `e13-fullfile-load.sh`, whose PASS signal is the **presence** of `ECONNREFUSED|fetch failed|connect`
  — proof that the loader got all the way to the network layer — not the absence of an error string.
- Corroborate with an independent side effect. The zero-token probe (F22) is the model: exit 124 +
  `Execution error` means the transcript was found, parsed and replayed; exit 1 +
  `No conversation found with session ID` means the resolver did not find it. And independently of the
  exit code, **every loaded run appended to its transcript** (2,089 B → 13,388–13,398 B) while **every
  not-found run left the file at exactly 2,089 B**. Two uncorrelated observables agreeing is a result;
  one grep finding nothing is not.

**Stated honestly, because M7 is about honesty:** the thing that grep was supposed to test is **still
untested**. O5 is open. E13 put **166 signed thinking blocks**, minted under org `0a0a0a0a` / account
`aaaaaaaa`, onto the wire under org `0b0b0b0b` / account `bbbbbbbb`, and the session subsequently ran
— strong evidence, not proof. The controlled single-turn test was never run. If cross-account
signature replay ever does fail, it is **fatal, single-shot, no retry, exit 1**
(`API Error: 400 messages.N.content.M.thinking.signature: The signature provided is not valid for this
content`), and `keep:"all"` is hardcoded with no flag or env knob. The sanctioned fallbacks are:
resume from the last compact boundary, or accept read-only history and start a fresh session seeded
from `memory/` + `tasks/`. Minting a new sessionId is **known not to help** — E2 already resumed with
a filename uuid differing from every record's `sessionId` and the signatures went out verbatim.
**Stripping thinking blocks remains PROHIBITED** regardless (6,331 records deleted, ~6,332 severed
parent links, walk-back depth collapses to 1).

---

### M8 — Host pollution

**What was done.** A subagent was told to "install Rust without sudo". It did exactly that. `rustup.rs`
installs entirely under `$HOME`, no root required.

**The damage.** **~1.6 GB of toolchain deposited into `$HOME`** (`~/.cargo` + `~/.rustup`) on a host
whose containment rule was implicit and had never been written down. Measured today, after
remediation: the trees now live at `Projects/SimLab/_conda/{cargo,rustup}` — **336 MB + 1.5 GB** — and
`~/.cargo` and `~/.rustup` remain as **symlinks pointing into the workspace**. So the fix was a
relocation, and the relocation left its own durable host-level artifact behind. That is what cleanup
after this class of mistake actually looks like: not removal, a residue.

**Why it was not caught immediately.** The subagent honored its constraint **perfectly**. "Without
sudo" is a **privilege** constraint. It says nothing about **location**. Nothing in the prompt named a
prefix, so `$HOME` was the default — and given what it was told, `$HOME` was the *correct* default.
There was no misbehaviour to detect, which is exactly why nothing detected it.

**What caught it.** A `du` of `$HOME` afterwards.

**The guard now in the skill.** A **constraints block**, pasted verbatim into every subagent prompt
that might install, download, build, or write outside the workspace — naming the workspace-local
prefix and forbidding `apt`, `~/.cargo`, `~/.rustup`, `~/.local` and the host conda **by name**. The
template is in Part 4 below.

**Follow-on worth recording:** `--no-modify-path` was used, so `~/.cargo/bin` is **not** on `PATH` for
new shells. Record the canonical interpreter and toolchain paths in the destination `CLAUDE.md`, or a
resumed session will conclude that cargo is missing and reinstall it — repeating M8 from inside the
migrated session.

---

## Part 2 — The near-miss that matters most

**The checkpoint was complete, verified, green — and held exactly one half of a byte-identical parity
pair.**

`_research/re/reimpl/fasp_cap.py` was present. `_research/re/rust/fasp-core/src/cap.rs` was not. Those
two files are a golden parity pair: the Rust golden-parity test asserts the exact bytes the Python
implementation emits, with **9 tests green across both languages** (`reimpl/test_fasp_cap.py`:
stock-floor-empty, round-trip, two-sided-AND, hostile-byte-safe parse). They are the artifact tracker
item #148 is *about*.

**Half a parity pair is not half a capability. It is zero.** The Python half alone cannot be checked
against anything; the invariant the pair encodes becomes unverifiable; and the missing half existed
nowhere else — not in git, not on any other host, not in any backup, on a machine whose Time Machine
target fails to mount and which has 38 GiB free on a 99 %-full volume.

### How a verification can be green and wrong

Every hash in that checkpoint was correct. Every file that was present was byte-identical to the
origin. **Fidelity was 100 %.** On that subtree, **coverage was 0 %.** The two properties are
orthogonal, and a verification that computes only over the set it actually pulled **cannot see the
difference** — the set it is checking and the set it is checking against are the same set.

The sharpest statement of this is in the decision log (D6): the strongest verification any candidate
design proposed — an inverse round-trip through a content-addressed store — **would have returned a
clean 100 %** on this corpus, because the CAS had been **ingested from the broken checkpoint**. A
verification whose reference set is derived from the artifact under test can only ever prove
self-consistency. It is a mirror, not a measurement.

### The class of check that catches it

1. **The reference must be built on the other side of the transfer.** An independent enumeration
   (`find` on the origin) producing an independent manifest, generated *before or during* the pull —
   never derived from what arrived. This is the whole content of the M2 guard, and it is the only
   check in the entire pipeline that could have found this.
2. **Coverage and fidelity are separate gates with separate reports.** One "VERIFIED" line is a bug.
3. **Named semantic invariants, not just counts.** The specific guard added:
   *`reimpl/fasp_cap.py` **and** `rust/fasp-core/src/cap.rs` are both present, or the checkpoint is
   REJECTED.* Counts are a floor; a named pair is a tripwire on the thing that actually matters.
   Generalize it: **for every artifact whose value depends on a partner, write the pair into the
   invariant list by name.** Parity pairs. Generator + golden corpus. Binary + its `.i64` database.
   Transcript + its sidecar directory. A file that is worthless without its twin should never be
   verifiable alone.
4. **Magnitude sanity floors**, so that an over-broad pattern manifests as a number rather than as
   silence: `[ "$RN" -lt 24000 ] && die`.
5. **An independent second mechanism.** `rsync -n -a -c --itemize-changes` uses MD4/MD5 rolling
   checksums — a genuinely different digest family from the SHA-256 manifests, so its failure modes
   are uncorrelated with theirs. That is the entire point of running it.

### The same error, one level up

This is not a quirk of one Rust file. The identical shape sits in the session itself: the transcript
is **55.8 %** of the session's bytes. A `.jsonl`-only migration is **100 % faithful** and loses **44 %
of the bytes and 100 % of all subagent conversation content** — 1,867 subagent transcripts, 113
workflow records, 11 tool-result blobs, 170 MB. It would pass every hash check ever written against
it. Ask, always: *faithful to what, and complete with respect to what?*

---

## Part 3 — What went right, and should be repeated

**1. Adversarial review of one's own artifacts.** Four independent critiques were run against the plan
and the scripts — binary-RE, checkpoint-audit, sequencing, and user-ask — with every finding carried
into a blocker table and **none dropped**. Those critiques found M1, M2, M3 and M5: *every single one
of the checkpoint defects.* Nothing else found them; no test, no manifest, no size check. The
discipline that makes it work: **read the artifact back against the ground truth it claims to
describe, not against its own intent.** The exclude list was checked against a remote `find` listing,
not against what the comment said it was for.

**2. Zero-token measurement before committing to a mechanism.** Two techniques carried the entire
experimental program at zero API cost:
- **The dead-port probe** (F22): the CLI creates `projects/<mangled>/<sid>.jsonl` during startup,
  *before* the first API call. Point `ANTHROPIC_BASE_URL` at `http://127.0.0.1:1` under `timeout`;
  exit 124 = the transcript was found, parsed and replayed; exit 1 = the resolver did not find it.
- **The recording mock**: ~100 lines of `http.server` that records every request body verbatim and
  answers `/v1/messages` with a well-formed SSE stream, so a **full turn completes locally at zero
  cost** and "what does the CLI actually send" becomes a measurement rather than an opinion.

Every experiment in the session ran free on these. More importantly they **overturned the plan's
central hypothesis before a single byte was rewritten**: E3's 4-cell matrix (one fixture, one variable
changed per cell) proved that per-record `$.cwd` is completely inert, which retired Tier 1's entire
33,805-record rewrite payload. Measurement is not merely cheaper than assumption here — it changed the
architecture.

**3. Sealing backups.** `chmod -R a-w` on each generation immediately after verification passes. Not
cosmetic: with `--link-dest` hardlink generations, unchanged files cost one inode entry, which means
**writing through an inode in the newest generation silently rewrites every prior generation**.
Sealing is what makes the checkpoint ratchet one-directional.

**4. Proving the origin unchanged — and scoping the claim honestly.** The origin fingerprint is
`mtime + size + mode + inode + name`, sorted and hashed.
- `atime` is **excluded** — it would fail by construction, since reading changes it, and remounting
  `noatime` would be a forbidden system-settings change.
- `ctime` is captured as a **second, advisory** fingerprint, so a difference distinguishes "we changed
  it" from "something else touched it".
- `inode` is in the set because it detects a delete-and-recreate that preserves mtime and size — the
  signature of a botched atomic replace.
- Capture **pre** as well as **post**. The first version captured only post, leaving nothing to
  compare against.
- And the claim is stated as **"no modification to the two target subtrees"**, not "no byte on the
  machine changed". ssh login shells write `.zsh_history`; some git subcommands write
  `stats-cache.json`; atime drifts. An overclaim that is falsifiable in five seconds destroys trust in
  the claims that are true.

**5. Asking the user before irreversible choices.** The destination root was settled *before*
materializing anything, because changing it afterwards means redoing every downstream phase.
Privileged operations were resolved as "the agent prints the exact command, the user runs it" — no
password ever typed, stored, echoed or read, and none entered into any prompt. Secrets disposition was
decided by the user, not assumed. Write-back to the origin requires the user's **typed** authorization
and **the origin is never deleted**. The rule underneath: *an agent may not authorize the one class of
action it cannot undo.*

**6. Writing down the corrections, not just the conclusions.** `LADDER-RESULTS.md` §7 is a
line-by-line correction table against the plan's own text. The F1–F24 list exists because someone
recorded not only what is true but the **plausible falsehood it replaced**. This prevents a specific,
observed failure mode: a recon document asserted a global resume fallback; an adversarial review
disputed it; the review was right *and itself incomplete*; without the written correction, the next
reader re-derives the abandoned Tier 1 straight out of the plan text and spends a day rewriting
33,805 records for no runtime effect. **A correction that is not written down will be un-made.**

**7. Getting the tooling out of the scratchpad.** The entire measurement rig — `mangle.py` (the 22/22
canonical mangler), the probe, both mocks, the PTY drivers — lived in the session scratchpad and would
have been garbage-collected. This was noticed and acted on. It matters more than it sounds: **losing
`mangle.py` alone means re-deriving the mangler out of a 265 MB unstripped ELF before any transplant
can even be preflighted.** When a throwaway tool works, it stops being throwaway. Copy it out
immediately.

---

## Part 4 — The meta-lesson on subagents

**Constraints not stated in a prompt will be violated.** Not through disobedience — an unstated
constraint is indistinguishable from no constraint. M8 is the clean case: the constraint that was
given ("without sudo") was honored **exactly**, and the constraint that mattered (containment) was
never said. The subagent's behaviour was correct with respect to its instructions and wrong with
respect to the world.

A second instance, with no misbehaviour at all: E4 was contaminated **mid-run** by a *concurrent*
agent creating probe directories inside a shared `CLAUDE_CONFIG_DIR`, silently changing the search
space that a scoping experiment depended on. E4 had to restore the shared directory and re-run
everything in a private one. Neither agent did anything wrong under its own prompt. The shared
namespace was the bug.

Three rules follow.

1. **State the containment boundary, not the privilege boundary.** "Without sudo" is not containment.
   Name the writable prefix explicitly and forbid the specific alternatives by path.
2. **Give every parallel agent its own scratch and config namespace**, and make the guard clause
   **abort**, not warn. The pattern that works:
   ```bash
   [[ "$CLAUDE_CONFIG_DIR" == "$S/cfg" ]] || { echo "SAFETY ABORT"; exit 9; }
   case "$CLAUDE_CONFIG_DIR" in /home/*/.claude*) echo "SAFETY ABORT: live config"; exit 9;; esac
   ```
3. **Constraints go in the prompt itself.** Not in a linked document. Not in a skill the subagent may
   or may not load. Not "as previously discussed". The prompt is the only thing guaranteed to be read.

### Constraints block — paste this into every subagent prompt

```
CONSTRAINTS (these override anything in your task description)

CONTAINMENT
- Write ONLY under: <WORKSPACE>  and  <SCRATCHPAD>
- Do NOT write anywhere else in $HOME. Specifically forbidden, by name:
  ~/.cargo  ~/.rustup  ~/.local  ~/.npm  ~/.cache  ~/.config  ~/.claude
  and any system-wide conda/homebrew/pyenv prefix.
- Any toolchain, venv, model, dataset or dependency you install goes under
  <WORKSPACE>/<tool-prefix>/ . Set the tool's own prefix env var
  (CARGO_HOME, RUSTUP_HOME, PIP_TARGET, npm --prefix, ...) to point there.
  Do NOT rely on the tool's default location.
- Do NOT modify PATH in any shell rc file. Print the export line instead.
- No `sudo`, no `apt`, no `brew`, no system package manager. If a task needs
  privilege, STOP and print the exact command for the user to run.

READ-ONLY BOUNDARIES
- <ORIGIN_HOST> is STRICTLY READ-ONLY. No writes, no mkdir, no temp files,
  no helper scripts written there. Ship helpers over stdin.
- Do not touch: <LIVE_SESSION_PATHS>  (a live session is running there)

ISOLATION
- Your CLAUDE_CONFIG_DIR is <PRIVATE_CFG>. Assert it before any CLI call and
  exit 9 if it is anything else. Never use a shared config dir.
- Your scratch dir is <SCRATCHPAD>/<agent-name>/ . Do not write into a sibling
  agent's scratch dir; other agents are running concurrently.

REPORTING
- Report the exact byte footprint you added to disk, and where.
- If you could not satisfy a constraint, say so explicitly. Do not work around
  it silently.
```

Fill every `<PLACEHOLDER>`. An unfilled placeholder is an unstated constraint, which is M8 again.

---

## Part 5 — Effort calibration

The session produced roughly **138,000 words** of documentation across recon, plans and experiments.
Retrospectively, the return on that was extremely uneven.

### What was worth it

| Investment | Words | Return |
|---|---:|---|
| **Seven experiments** (E-RIG, E2–E5, E11, E12) | ~17k | Settled **every decision that mattered**, at zero API cost. E-RIG produced the mangler (22/22) *and* the dead-port probe that made everything after it free. E3 killed a 33,805-record rewrite. E4's three wrong placements established that project-directory correctness is a **requirement**, not a convenience. |
| **The consolidation pass** (`LADDER-RESULTS.md`) | 7.2k | Disproportionately valuable. It found a constraint **no single experiment reached**: the transcript's filename stem must remain the origin session id, or 170 MB / 1,991 sidecar files orphan **silently**. Consolidation is where cross-experiment constraints live; nothing else finds them. |
| **The four adversarial critiques** | (embedded) | Found M1, M2, M3, M5 — every checkpoint defect. Cheapest high-yield activity in the entire session. |
| **R02 / R09 / R12** (transcript format, sidecars, risk model) | ~18k | Directly load-bearing. The record schema, the sidecar resolution rule, and the integrity model are all consumed by the skill verbatim. |

### What was not worth it

- **~83k words of reconnaissance across 14 documents produced perhaps a dozen load-bearing facts —
  and two of the most prominent were wrong.** R01 asserted the mangler maps `/` and `_` to `-` (F1:
  in fact *every* character outside `[a-zA-Z0-9]` maps to `-`, including dots, spaces and existing
  hyphens). R03 asserted a global resume fallback (F2: `--resume=<id>` never reaches the function that
  has one). **Both survived into planning.** A recon document's confidence is uncorrelated with its
  accuracy; only the experiments distinguished them. Reconnaissance that can be replaced by a
  30-second experiment should be.
- **R06** — 11.9k words on the skills corpus — produced exactly one actionable recommendation (exclude
  `scholarly-pdf-acquisition`), which was then **not followed**. 321 MB copied and installed, verified
  live today. A recommendation nobody wires into a gate is a recommendation that does not exist.
- **R07** (8.7k, automation corpus) and **R11** (5.5k, Linux automation landscape) are off the
  transporter path entirely. The decision log demoted GUI automation from mechanism to diagnostic
  fallback, which retired most of R11's surface after it was written.
- **Three full candidate designs were written in parallel, and all three were wrong on the same three
  points**: all three made bulk transcript rewrite the primary strategy; all three verified fidelity
  only, never coverage; all three gated on a destination sign-in that had **already happened**
  (`config.json` carried `oauth:tokenCache` and `lastKnownAccountUuid` all along). Parallel design did
  **not** buy independence — the three shared an inherited premise and therefore shared its errors.
  One design plus an adversarial pass **against measurement** would have been cheaper and strictly
  better.

### The calibrated rule for the next run

- **Budget recon to *locating* artifacts and their sizes. Budget measurement to *deciding* anything.**
  If a claim would change what you do, measure it. If it merely describes, one paragraph is enough.
- **Parallel fan-out multiplies coverage, not independence.** Agents given the same framing return the
  same blind spot N times, with N times the confidence. Independence comes from a *different method*
  (measurement vs. reading), not from a different agent.
- **Spend the savings on consolidation and adversarial review.** They were the two highest-yield
  activities in the session and together cost less than any single recon document.
- **Prefer durable numbered facts to prose.** Every hour that produced an `M-`, `F-`, `O-` or `K-`
  entry paid for itself and is being consumed right now. Every hour that produced explanatory prose
  did not.
- **A migration of this kind is a ~1-day job with the facts in hand.** The reference run took far
  longer, and most of that was spent establishing facts that are now written down. Do not re-establish
  them. Cite them.
