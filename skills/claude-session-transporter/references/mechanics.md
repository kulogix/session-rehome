# mechanics.md — how Claude Code session storage actually works

**Purpose.** This is the measured, citable mechanics of Claude Code session storage. It exists so a
future run of `session-transporter` does **not** re-derive any of it. Every non-obvious claim below
was established empirically in the migration of session
`5e55105e-0000-4000-8000-000000000001` (mac1/macOS/arm64 → Linux/x86_64, cross-account **and**
cross-org), or lifted from the CLI ELF / Desktop `app.asar`. Where a claim is inferred, it says so.

**Evidence tags.** `[M]` measured · `[C]` lifted from shipped code · `[D]` derived from `[M]`+`[C]`
· `[I]` inferred, never verified · `[LIVE]` re-verified on disk after the migration completed.

**Citation keys.** `E-RIG`, `E2`, `E3`, `E4`, `E5`, `E7`, `E11`, `E12`, `E13` are the experiments;
`R01`–`R12` the forensic recon docs; `K1`–`K22` the confirmed-known list; `F1`–`F24` the
"looks true but is false" list. `K`, `F`, `E` and the risk-model checks are all restated in
`references/evidence-base.md`, shipped with this skill. The `R01`–`R12` recon documents
themselves were **not** shipped — where one is cited, the claim it supports is stated in
full here or in the evidence base, so no reader ever has to go and find it.

**Versions this was measured against.** Writer CLI `2.1.170` / `2.1.181` / `2.1.187`; reader CLI
`2.1.215`; Desktop `@ant/desktop 1.22209.3` on Electron 42.5.1, bundling
`@anthropic-ai/claude-agent-sdk 0.3.215`. Re-confirm §9 before trusting anything here against a
much newer build.

---

## 1. The three-layer storage model

A "session" is **not one file**. It is three independently-keyed layers that only meet at runtime.
Confusing them is the source of most migration failures.

```
LAYER 1  Desktop metadata      keyed by  accountUuid + orgUuid + sessionId   (per user-data-dir)
   |     "which sessions exist, and what CLI session does each point at"
   |     <user-data-dir>/claude-code-sessions/<accountUuid>/<orgUuid>/<sessionId>.json
   |          field cliSessionId  ────────┐
   v                                      │
LAYER 2  CLI transcript                   │ keyed by  mangle(realpath(cwd)) + cliSessionId
   |     "the conversation"               └────────►  ~/.claude/projects/<KEY>/<cliSessionId>.jsonl
   |
   v
LAYER 3  sidecars + shared state    keyed by  the transcript's filename stem, or by project, or by sid
         ~/.claude/projects/<KEY>/<cliSessionId>/{subagents,tool-results,workflows}/
         ~/.claude/projects/<KEY>/memory/*.md          <- PROJECT-keyed, session-independent
         ~/.claude/tasks/<cliSessionId>/               <- SESSION-keyed, project-invisible
```

### 1.1 The single most consequential structural fact

**Layer 1 lives in the Electron user-data dir. Layers 2 and 3 live in plain `~/.claude`.** `[M]`
`[C]` (R03 §3.1: `getClaudeConfigDir` reads `$CLAUDE_CONFIG_DIR` or falls back to
`join(homedir(), ".claude")`, and the Desktop reads transcripts through it with plain `fs`.)

Consequences, all measured:

- Every Desktop instance on a host — however many `--user-data-dir`s you run — **shares one
  transcript store, one skills dir, one plugins dir, one memory store and one tasks store.**
  Instance separation is process isolation, not data isolation `[M]`, `F6`.
- Therefore "install the skills for the destination instance" is a host-level operation, not a
  per-instance one.
- Therefore two instances resuming the same `cliSessionId` would append to the same `.jsonl`.

### 1.2 Path templates per platform

`<UD>` = the Electron user-data dir. It is `app.getPath("userData")`, which **`--user-data-dir`
overrides wholesale** `[C]` (R03: `this.userDataPath = app.getPath("userData")`).

| Platform | Default `<UD>` | `~/.claude` (CLI config dir) | Evidence |
|---|---|---|---|
| **macOS** | `~/Library/Application Support/Claude` | `~/.claude` | `[M]` — verified on mac1 |
| **Linux** | `~/.config/Claude` | `~/.claude` | `[M]` — verified locally |
| **Windows** | `%APPDATA%\Claude` (= `C:\Users\<u>\AppData\Roaming\Claude`) | `%USERPROFILE%\.claude` | **`[I]` INFERRED** — never observed. Standard Electron `userData` resolution + `homedir()`. The only *positive* Windows signal in the code is that `getClaudeConfigDir` explicitly handles a `~\`-prefixed `CLAUDE_CONFIG_DIR` `[C]`, and one `.watch(` call site is a win32 log path `[C]` (R03 §4). Treat every Windows path in this document as a hypothesis to verify before use. |

Overrides that always win, on every platform:

- `CLAUDE_CONFIG_DIR` — replaces `~/.claude` entirely. Supports `~`, `~/…` and `~\…` expansion `[C]`.
  **This is the single most important safety lever in the whole skill**: every experimental CLI
  invocation must set it to a rig-local directory behind an abort guard (§10.4).
- `--user-data-dir=<path>` — replaces `<UD>` entirely `[C]` `[M]`.

Full expansion of the three layers:

```
# LAYER 1 — Desktop metadata
<UD>/claude-code-sessions/<accountUuid>/<orgUuid>/<sessionId>.json          # sessionId = "local_<uuid4>"
<UD>/local-agent-mode-sessions/<accountUuid>/<orgUuid>/                     # Cowork sibling
<UD>/local-agent-mode-sessions/skills-plugin/<orgUuid>/<accountUuid>/       # NOTE: org/account REVERSED

# LAYER 2 — CLI transcript
$CLAUDE_CONFIG_DIR/projects/<KEY>/<cliSessionId>.jsonl                      # KEY = mangle(realpath(cwd))

# LAYER 3 — sidecars and shared state
$CLAUDE_CONFIG_DIR/projects/<KEY>/<cliSessionId>/subagents/agent-<17hex>.jsonl
$CLAUDE_CONFIG_DIR/projects/<KEY>/<cliSessionId>/subagents/agent-<17hex>.meta.json
$CLAUDE_CONFIG_DIR/projects/<KEY>/<cliSessionId>/subagents/workflows/wf_<runId>/agent-*.{jsonl,meta.json}
$CLAUDE_CONFIG_DIR/projects/<KEY>/<cliSessionId>/tool-results/<9char-base36>.txt
$CLAUDE_CONFIG_DIR/projects/<KEY>/<cliSessionId>/workflows/wf_<12char>.json
$CLAUDE_CONFIG_DIR/projects/<KEY>/<cliSessionId>/workflows/scripts/<name>-wf_<id>.js
$CLAUDE_CONFIG_DIR/projects/<KEY>/memory/*.md
$CLAUDE_CONFIG_DIR/tasks/<cliSessionId>/{<n>.json,.highwatermark,.lock}
```

### 1.3 Layer-size reality check

On the migrated session `[M]`:

| Layer | Files | Bytes | Share |
|---|---:|---:|---:|
| Transcript (`.jsonl`) alone | 1 | 216,236,906 | **55.8 %** |
| `subagents/` (incl. `workflows/`) | 1,867 | ~157 MB | 40 % |
| `workflows/` + `tool-results/` + `tasks/` | 278 | ~13 MB | 3 % |
| **Total session footprint** | **2,157** | **387,805,915** | 100 % |

**A "copy the `.jsonl`" migration loses 44 % of the bytes and 100 % of the sub-agent conversation
content** `[M]`. `subagents/workflows/` alone is 38 % of the session and is invisible to any
`-maxdepth 1` sweep.

Project memory is separately the highest value per byte in the whole tree: 24 files / 399,050 B
carrying the project's standing directives (R05).

### 1.4 Layer 1 is not a source of truth, and there is no watcher

- The Desktop metadata file is a **pointer and a UI record**. Delete it and the conversation still
  exists; the CLI resumes it fine. Corrupt Layer 2 and no amount of Layer 1 helps.
- There is **no `sessionStore` mirror** in the shipped configuration — `sessionStore` is an optional
  SDK adapter, guarded by `sessionStore cannot be used with persistSession: false`, and the live
  Desktop argv contains no `--session-mirror` `[C]` `[M]` (`E6`, `F20`). **Local files are
  authoritative.**
- There is **no filesystem watcher.** `chokidar` appears 0 times in the bundle; `.watch(` has six
  call sites, all unrelated `[C]` (R03 §4). `loadSessions()` runs only on app start / first account
  resolution, on `lastActiveOrg` cookie change, on account change, and lazily when account or org is
  null. **A metadata file dropped in while the app is running will not appear — and the debounced
  writer may destroy it.** Stop that one instance, drop the file, start it.
- Wrong `<accountUuid>/<orgUuid>` is not a soft failure: such files are **never read**, and worse,
  `addOnDiskCliSessionIdsFromAllOrgs()` walks every account/org dir and feeds the result to the
  recovery scanner as an **exclusion** set — so a misfiled metadata file *additionally suppresses*
  its own transcript from the current account's recovery UI `[C]` (R03 §5).

---

## 2. The mangler

The project-directory name is `mangle(realpath(launch cwd))`. Derived two independent ways —
lifted from the CLI ELF at offset 239728033 and confirmed against 22/22 observations
(11 CLI probe dirs + 7 real origin dirs + 4 boundary cases) — in `E-RIG` and `E5`.

### 2.1 The shipped code `[C]`

```js
Jvt = 200
function nQe(e){ let t=0; for(let r=0;r<e.length;r++) t=(t<<5)-t+e.charCodeAt(r)|0; return t }
function bzm(e){ return Math.abs(nQe(e)).toString(36) }
function Pw(e){ let t = e.replace(/[^a-zA-Z0-9]/g,"-");
                if (t.length <= Jvt) return t;
                return `${t.slice(0,Jvt)}-${bzm(e)}` }
function h4(){ return join(CLAUDE_CONFIG_DIR, "projects") }
function a9(e){ return join(h4(), Pw(e)) }
async function j0(e){ try { return await realpath(e) } catch { return e } }
```

Note `(t<<5)-t` is `t*31`, `charCodeAt` yields **UTF-16 code units**, and the hash is computed over
the **original** path, not the sanitized one.

### 2.2 Reference implementation

Canonical copy: `scripts/mangle.py` in this skill — lifted verbatim from the source session's
measurement rig, scored **22/22** against observations, and re-verified byte-identical when this
skill was packaged. **Lift it, do not reimplement it.** Losing it means re-deriving the mangler from a 265 MB ELF before any transplant
can be preflighted.

```python
MAX = 200

def _u16(s):
    b = s.encode('utf-16-le')
    return [b[i] | (b[i+1] << 8) for i in range(0, len(b), 2)]

def java_hash_utf16(s):
    """nQe: h = (h*31 + code_unit) as signed int32."""
    h = 0
    for c in _u16(s):
        h = (h * 31 + c) & 0xFFFFFFFF
        if h >= 0x80000000:
            h -= 0x100000000
    return h

def to_base36(n):
    if n == 0:
        return '0'
    d = '0123456789abcdefghijklmnopqrstuvwxyz'
    out = ''
    while n:
        out = d[n % 36] + out
        n //= 36
    return out

def sanitize(path):
    """[^a-zA-Z0-9] -> '-', applied per UTF-16 code unit (JS regex semantics)."""
    out = []
    for c in _u16(path):
        ch = chr(c)
        out.append(ch if ('a' <= ch <= 'z' or 'A' <= ch <= 'Z' or '0' <= ch <= '9') else '-')
    return ''.join(out)

def mangle(path):
    """path MUST already be os.path.realpath()'d."""
    t = sanitize(path)
    if len(t) <= MAX:
        return t
    return t[:MAX] + '-' + to_base36(abs(java_hash_utf16(path)))
```

### 2.3 Behavioural properties — every one measured, none may be "improved"

| Property | Behaviour | Confirmed by |
|---|---|---|
| leading `/` | → leading `-` | all 11 `E-RIG` probes |
| `_`, `.`, space, `-`, every punctuation mark | **all → `-`**, mutually indistinguishable | `under_score_dir`, `dot.ted.dir`, `with space dir`; 19 punctuation chars → 19 dashes |
| case | **preserved, no folding** | `MiXeDCase` → `MiXeDCase` |
| repeated separators | **NOT collapsed** — n separators → n dashes | `a_-_b..c` → `a---b--c` |
| trailing separator | preserved as a trailing `-` | `trail_` → `…-trail-` |
| non-ASCII BMP | one `-` per code unit | `uni_café_日本` → `uni-caf----` |
| astral plane (emoji) | **two** dashes (surrogate pair) | `[D]`, not exercised |
| length ≤ 200 | kept verbatim | boundary measured at 199 / **200** / 201 / 260 in `E5` |
| length > 200 | `sanitized[0:200] + '-' + base36(abs(hash(ORIGINAL)))` → **202–207 chars, never fixed-length** | `E5` |
| input | **`realpath`**, symlinks resolved through | `E4` C1/C2, with both the symlink dir and the real dir present simultaneously |

### 2.4 Collision properties — the mapping is not injective

`/a/b`, `/a-b`, `/a_b`, `/a.b`, `/a b` **all collapse to `-a-b`** `[M]`. Real-world instance:
`net.sim`, `net_sim` and `net-sim` share one project directory.

Counter-intuitively, **paths longer than 200 chars are *less* collision-prone than short ones**,
because the appended hash re-injects the information the sanitizer destroyed. Two 210-char paths
differing only `_` vs `.` produced hashes `5lftp7` vs `qa4tka` `[M]` (`E5`).

Two rules follow, both of which were violated in planning before being measured (`F1`, `F24`):

1. **Never derive a project-dir name by editing another one.** Always compute it from
   `realpath(cwd)` through `mangle()`.
2. **Carry the literal observed directory name** in your manifest; you cannot invert the mangle.
   The authoritative inverse mapping is the `cwd` / `originCwd` fields in the Layer-1 metadata.

### 2.5 The Desktop has three manglers and they differ `[C]`

| Bundle chunk | Symbol | Owner | Behaviour when > 200 |
|---|---|---|---|
| `index.chunk-BnvC1Fh-.js` | `cliSanitizeCwdSimple` | `ClaudeCodeConfig` / trust helpers, consumed by `LocalSessionManager` | **returns `undefined`, no hash** |
| `index.chunk-CgLXpPH8.js` | `zo` | vendored agent SDK | identical to the CLI's `Pw` |
| `index.chunk-DfuT5fCe.js` | `zo` (inlined) | `LocalAgentModeSessionManager` | identical to the CLI's `Pw` |

This divergence is **write/fork-side only**, and does *not* create a "CLI-resumable but
Desktop-invisible" regime — see `F7` and §3.5. Treat a >200-char key as a **warning**, not a gate.

Worked keys from the real migration `[M]`:

```
/Users/jamiedoe/Projects/CLAUDE/transporter        -> -Users-jamiedoe-Projects-CLAUDE-transporter   (43)
…/transporter/_research/re/tools/devio_fasp/diag   -> …--research-re-tools-devio-fasp-diag          (78)  deepest real key
/home/dana/Projects/transporter                    -> -home-dana-Projects-transporter               (31)  the one used
/home/dana/Projects/SimLab                         -> -home-dana-Projects-SimLab                    (26)
```

122 chars of headroom at the deepest real key ⇒ the overflow regime was unreachable for this
migration.

---

## 3. Resume resolution

### 3.1 The resolver, exactly `[C]` (`E4` §4)

`--resume=<id>` goes `R$e` → `wVe(e)` → `VOd(e, undefined)` → **`$8y(e)`**:

```js
async function $8y(e){
  let t = zW(),                          // sessionProjectDir override, usually null
      r = ln(),                          // the launch cwd
      n = `${e}.jsonl`,
      o = join(t ?? bb(r), n);
  if (t !== null) return o;              // explicit override short-circuits
  for (let i of await cM(r)) {           // candidate project dirs derived from r
    let s = join(i, n);
    try { await stat(s); return s } catch {}
  }
  return o;                              // stat fails -> "No conversation found with session ID"
}

async function cM(e){
  let t = a9(e), r = [];                 // a9 = join(projects, Pw(realpath(e)))
  try { await readdir(t); r.push(t) } catch {}
  let n = Pw(e);
  if (n.length <= 200) return r;         // short key: EXACTLY ONE candidate
  let o = n.slice(0,200) + "-";          // long key: also accept siblings sharing the 200-char prefix
  for (let s of await readdir(h4(), {withFileTypes:true}))
    if (s.isDirectory() && s.name.startsWith(o) && join(h4(), s.name) !== t)
      r.push(join(h4(), s.name));
  return r;
}

// the only other widener:
async function SGg(e){ for (let t of await Mwe(ln())) /* `git worktree list --porcelain` */ … }
```

### 3.2 Resume is cwd-scoped. There is no global fallback.

**`K10`, `F2`.** `nGe(sessionId, cwdHint)` *does* contain a global `readdir` branch — but only when
the hint is absent, and **`$8y` never calls it**. Measured three independent times (`E4` A1, `E3`
§3.4, `E5` §5):

- transcript in a decoy dir, and it is **the only `.jsonl` anywhere under `projects/`** → `exit 1`,
  `No conversation found with session ID: <uuid>`;
- transcript in a *different real cwd's* project dir → not found;
- transcript in the project dir of the **parent** of the launch cwd → not found. There is no parent
  walk.

**Dirname correctness is a requirement, not a convenience.** Any plan branch predicated on "a global
fallback might save us" does not fire.

### 3.3 realpath, not `$PWD`

`K11`. The mangle input is `await realpath(cwd)`. `E4` C1/C2 created both a symlink path and its
target as project dirs simultaneously: the **realpath** dir was found; the alias dir was never
consulted. So:

```python
C_phys = os.path.realpath(C)     # never $PWD, never `pwd -L`, never a raw user string
if C_phys != C:
    warn_loudly()                # do not absorb the difference silently
KEY = mangle(C_phys)
```

Portability: `realpath(1)` differs across platforms. Compute the physical path with
`python3 -c 'import os,sys;print(os.path.realpath(sys.argv[1]))'` or `cd "$d" && pwd -P`.

### 3.4 Git worktrees widen the search (never narrow it)

`K13` `[M]` (`E4` §5a). A fresh throwaway repo with `main` plus a linked worktree `feat`: the
transcript was placed under `mangle(.../wt/main)` and the CLI was launched from `.../wt/feat`.
Result: **found** (exit 124 = loaded), and the resume **appended in place in the sibling worktree's
project dir** — no new directory was created. The control (same launch cwd, file in a decoy dir)
was not found.

⇒ If the destination root is a git repo with linked worktrees, a session parked under **any**
worktree's key is resumable from **any** other. Convenience only. Never design around it.

### 3.5 Desktop discovery is directory-name-agnostic

`K15`, `F7` `[C]` (`E5`). `resolveProjectDirForSession` probes candidates derived from `cwd`,
`worktreePath` and `originCwd`, drops an `undefined` fast-path candidate, and **falls through to a
full `readdir(projects)` + parallel `access(<dir>/<cliSessionId>.jsonl)` across every project dir**.
`scanRecoverableCliTranscripts` likewise enumerates all project dirs, filtering only on
`startsWith("ssh-")`. Both find a hashed >200-char dir.

So the CLI is *stricter* than the Desktop about placement. Satisfy the CLI and the Desktop follows.

### 3.6 `--resume <abspath>.jsonl` — works, and is forbidden here

`K14` `[M]` (`E4` §5b). Gate: `function hrn(e){ return isAbsolute(e) && e.endsWith(".jsonl") }`.
It loads a transcript from **anywhere**, including outside `projects/` entirely. But its write
semantics are the opposite of the project-dir path:

| | project-dir path | `--resume <abs>.jsonl` |
|---|---|---|
| source file | appended in place | **left untouched** |
| new file | none | **a duplicate is materialised beside it** |
| new file's name | n/a | the **in-record `sessionId`** — the reverse convention from the project-dir path, where the **filename** wins (`K1`) |
| historical records | byte-identical | **`cwd` rewritten on every replayed record** (`fields differing: ['cwd']`) |
| record order | preserved | **normalised** (`custom-title` hoisted to line 1) |

For a 216 MB transcript that means a full duplicate plus 47,088 mutated records — exactly the
guarantee Tier 0 exists to preserve. **Do not use it for a migration.** Use it, if ever, only for
read-only inspection of a copy.

Two adjacent observations, recorded so they are not rediscovered as bugs:

- A **relative** `./<uuid>.jsonl` also resumes, despite `hrn()` requiring `isAbsolute` — something
  absolutises the argument earlier. Mechanism `[I]`.
- A **missing** absolute `.jsonl` path reports a **freshly minted, never-requested** session id
  (`F23`): asking for `…/00000000-0000-4000-8000-000000000000.jsonl` printed
  `No conversation found with session ID: f0f0f0f0-0000-4000-8000-000000000002`, an id appearing
  nowhere in the config dir. **Never parse a uuid out of that message.**

### 3.7 What actually sets the effective cwd

`K8` `[M]`. **The launch directory.** Nothing on the `--resume` path chdirs anywhere else.

### 3.8 `relocated` records — a real record type, almost never honored

`K7`, `K22`, `F3`, `F4` `[M]` `[C]` (`E3`, a 4-cell matrix over one fixture).

Shape: `{"type":"relocated","sessionId":"<SID>","relocatedCwd":"<abs path>"}`.

Three consumers `[C]`:

| # | Consumer | Must `sessionId` match? | Scope |
|---|---|---|---|
| 1 | `D$e` streaming parser → `relocatedCwds` map | **yes** (keyed by the record's own sessionId, last wins) | full-file parse |
| 2 | `Qvt(buf,"relocated","relocatedCwd")` reverse line scan | **no** (sessionId ignored) | **last 65,536 bytes only** (`rR=65536`) |
| 3 | `FUd` reducer (fork/copy) | **yes** | full-file parse |

But the chdir happens only inside `ubt(worktreeSession, projectPath)` — and **only when the second
argument is passed**. Call-site arity `[C]`:

| Path | args | chdir? |
|---|---|---|
| `--resume=<id>` (interactive or `--print`) | 1 | **no** |
| `--continue` | 1 | **no** |
| startup session picker | 1 | **no** |
| in-REPL `/resume` | 2 | **yes** |

Measured: with a correctly-formed `relocated` record present and *demonstrably consumed* (the CLI
re-emitted it re-stamped with the new session id), the effective cwd stayed at the launch dir and
`cwdB` appeared **0 times** in the request body.

**Append one anyway** — it is one line, free, and the sole lever on the in-REPL `/resume` path —
under three hard constraints:

1. `sessionId` must be the **in-record** session id, not the filename uuid (satisfies all three
   consumers);
2. `relocatedCwd` must be an **existing absolute path** — `process.chdir` is inside `try/catch`, so
   a wrong value **degrades silently to no-chdir** rather than erroring;
3. it must land **within the last 64 KiB** of the file. Re-verify after any later append.

Communicate relocation to the **model** instead: an appended human-readable notice record, plus a
durable `CLAUDE.md` in the destination project root. The notice falls out of context on compaction;
`CLAUDE.md` is re-read every session.

---

## 4. Inert vs load-bearing — the table that matters most

This is the table that turned a 42,650-pointer rewrite project into a byte-for-byte copy.

### 4.1 LOAD-BEARING — get these wrong and the migration fails

| Thing | Why | Failure mode | Cite |
|---|---|---|---|
| **The project directory name** = `mangle(realpath(launch cwd))` | the resolver searches only cwd-derived candidates | `exit 1`, `No conversation found with session ID: <uuid>` | `K10`, `E4` |
| **The transcript filename stem** = the origin `cliSessionId` | resume keys off the **filename**, not in-record `sessionId`; `metadata.session_id` and the `x-claude-code-session-id` header are stamped from it | session not found, or found-but-sidecars-orphaned | `K1`, `E2`, `E13` |
| **The filename stem, again, for sidecars** | sidecars resolve as `<transcript path minus .jsonl>/{subagents,tool-results,workflows}` | **silent** orphaning of 170 MB / 1,991 files | §6, `WUd` `[C]` |
| **File is non-empty** | the resolver skips zero-byte candidates | fails *identically* to a missing file | `E4` |
| **Byte fidelity of the prefix** | thinking-block signatures are server-side attestations over exact content | `400 messages.N.content.M.thinking.signature: The signature provided is not valid for this content` — **one request, no retry, no fallback, exit 1** | `K5`, `K6`, `E2` |
| **All thinking blocks present** | stripping deletes 6,331 assistant records and severs ~6,332 `parentUuid` links | walk-back depth collapses to **1** | §5.4 of the evidence base |
| **Layer-1 `accountUuid`/`orgUuid` directory** | mismatched files are never read *and* suppress their own transcript from recovery | session invisible in the app | `[C]`, R03 §5 |
| **Layer-1 filename == `${sessionId}.json`** | the filename is only a `local_*.json` filter; the map key is the file's `sessionId` field. A mismatch loads under the field value, is rewritten to `<field>.json`, and leaves the original as a **permanent ghost reloaded every launch** | duplicate ghost sessions | `[C]`, R03 §2 |
| **Layer-1 `cliSessionId` present** | `undefined` ⇒ `isFirstTurn:true` ⇒ the session is treated as never-started | transcript never loaded | `[C]` |
| **Layer-1 size < 10 MiB** | hard load gate + Sentry warning | file silently skipped | `[C]` |
| **Workspace trust** | `~/.claude.json` → `projects[<path>].hasTrustDialogAccepted`, checked up the ancestor chain | session will not start | `[C]` |
| **Shared assets installed before launch** | skills are enumerated at CLI **process startup** and cached for the process lifetime | a skill added mid-session never appears; only a fresh process sees it | `[M]` |

### 4.2 INERT — measured to have no runtime effect

| Thing | Occurrences | What was measured | Cite |
|---|---:|---|---|
| **`$.cwd` on every record** | 33,805 | **The control experiment.** Every message record's `cwd` rewritten to a different path, no `relocated` record; the session still ran from the launch directory. Nothing on the resume path chdirs to a historical `cwd`. | `K9`, `F5`, `E3` body_030 |
| `$.slug` | 32,414 | reaches the API **0 times** | `K3`, `E2` |
| `type:"mode"` records | 3,432 | reaches the API 0 times; not even emitted by 2.1.215 | `K3`, `K4` |
| `$.uuid`, `$.parentUuid` | 33,805 | reach the API 0 times (they structure the local DAG only) | `K3` |
| `$.version` | all | 0 times; 2.1.215 loads 2.1.170 records without complaint | `K3`, `K4` |
| `$.leafUuid` on `last-prompt` | 3,436 | 0 times | `K3` |
| `$.isSidechain`, `$.userType`, `$.entrypoint`, `$.gitBranch` | all | 0 times | `K3` |
| **in-record `$.sessionId`** | all nine record types | **0 times, and need not match the filename.** Origin-sessionId and rewritten-sessionId variants produced **byte-identical 429,452 B** requests | `K1`, `E2` |
| `$.attachment.displayPath` | — | relative by construction — never rewrite it | R02 |
| historical absolute paths in prose/tool results | 54,157 occurrences of `/Users/jamiedoe` on 33,959 lines | historical record, not live locations | `[M]` |

**The conclusion that follows:** relocating a session requires **no transcript rewriting at all**.
This is the single most important finding of the source session. Do not re-derive a rewrite tier
from plan text that predates the measurement (`F3`).

### 4.3 If a rewrite is ever attempted anyway

The acceptance test is **invertibility**: apply the inverse map and assert
`sha256(inverse(rewritten)) == sha256(original)`. No exceptions, no "close enough". A substitution
rule is admissible **only if its target string occurs zero times in the input** — measured on the
real corpus, `/home/dana` occurred on 2 lines (⇒ the obvious broad rule is **inadmissible**) while
`/home/dana/Projects/transporter`, `/home/dana/.claude` and `/tmp/claude-1000` occurred 0 times
(⇒ admissible).

Also: a blanket `sed` over `/Users/jamiedoe` would hit 54,157 occurrences of which **~5,705 are not
paths at all** (`ls -l` owner columns, `jamiedoe@host` strings, git author lines) and **~745 are
macOS toolchain paths with no Linux equivalent** `[M]`.

---

## 5. Transcript file shape, briefly

Enough to validate one; the full record schema is in the evidence base §2.

**File-level invariants** `[M]` (`E7`): one JSON object per line, UTF-8, LF-terminated (last byte
`0x0a`); **0 parse failures in 47,088 lines**; **0 occurrences of `\/` escaping**; max line length
128,423 B; **resume is a pure append** — the first 200 lines were byte-identical (`sha256
f9a2ceb1…`) after three resumes (`K2`).

**Exactly nine record types.** `assistant` (21,859) · `user` (9,569) · `ai-title` (3,466) ·
`last-prompt` (3,452) · `mode` (3,432) · `attachment` (1,949) · `custom-title` (1,769) ·
`queue-operation` (1,164) · `system` (428). Five of them (`ai-title`, `last-prompt`, `mode`,
`custom-title`, `queue-operation` — 13,283 records) carry **no `uuid`** and are not in the DAG;
33,805 records do. A "find the last uuid" scan must therefore **tail-scan backwards past records
that have none** — the origin file ends with a `custom-title` / `ai-title` / `mode` triple. A tenth type,
`relocated`, exists in the CLI and appeared **0 times** in the origin (`K22`).
**There is no `type:"summary"` record** in this format version.

**DAG assertions to re-run post-transplant** `[M]` (`E7`):

```
records with uuid        33,805        distinct uuids   33,705   (100 duplicates)
dangling parents         0             roots            28  = 1 genuine + 27 compact_boundary
branch points (>1 child) 119           max fan-out      4
last-prompt leafUuids    3,436         orphans          0        (the LAST leafUuid must resolve)
assistant records        21,859        with thinking    6,344
first compact_boundary   line 1884     boundaries       27
```

Three traps for any tool that walks this DAG:

1. **uuids are not unique** — 100 duplicates at lines 1784–1883 (100 contiguous records re-emitting
   uuids first written at lines 12–702, immediately before the first compaction). uuid→record maps
   must be **last-write-wins**.
2. A naive "is my parent earlier in the file?" check reports **94 false violations**, an artifact of
   that duplicate block — not forward references.
3. A walker must follow **`logicalParentUuid` on `compact_boundary`** or it sees 28 disconnected
   conversations instead of one.

Any rewriting tool must preserve line **order and count exactly** (47,088 in → 47,088 out), and must
**never read the file whole** — stream, write a new file, `os.replace`.

---

## 6. Sidecar resolution from the filename stem

`[C]`, corroborated `[M]`.

```js
function Et(){ return qL()?.sessionId ?? kt.sessionId }        // == the FILENAME uuid on resume
function bx(e){ … join(projectDir, Et(), "subagents", `agent-${e}.jsonl`) }
function YUu(){ … join(projectDir, Et(), "workflows") }
function N8n(){ … join(a9(At()), Et(), "workflows", "scripts") + sep }   // per-CURRENT-cwd project dir
async function WUd(e,t){ let r = await nGe(e,t); if(!r) return null;
  return join(r.filePath.replace(/\.jsonl$/, ""), "subagents") }         // transcript path MINUS .jsonl
```

**The rule:** sidecars live at `<transcript path with .jsonl stripped>/…`. Rename the transcript and
all of it is orphaned **silently** — no warning, no error, no log line. On the source session that
was 170 MB / 1,991 files.

Status: `[D]`. The premise (`Et()` == the filename uuid on resume) is measured; the derivation
(`WUd`) is lifted code; the end-to-end confirmation (`E14`) was never run. The rule is cheap to
honour and costless if wrong, so it stands regardless.

### 6.1 Sidecar contents and their linkage

- Sidecar `.jsonl` files use the **same envelope**, plus `agentId`, with `isSidechain: true` and
  their own root (`parentUuid: null`).
- **Sub-agents link to the parent by `toolUseId`, not by uuid** — `meta.toolUseId` equals the `id`
  of the `tool_use` block in the parent's assistant turn.
- **The tree is two levels deep.** Of 51 `toolUseId`s, only **16 appear in the main transcript**;
  the other **35 appear inside another sub-agent's `.jsonl`** `[M]` (`F18`). ⇒ **You cannot
  reconstruct the sub-agent set by scanning the main transcript. Enumerate the directory.**
- Workflow-agent metas are degenerate (`{"agentType":"workflow-subagent","spawnDepth":1}` — no
  `toolUseId`, no `description`); linkage is **by directory name** `wf_<runId>`.
- `wf_<id>.json` carries the **full text** of its `.js` in a `script` field. All 85 were non-empty
  `[M]` ⇒ **any missing workflow script is regenerable** — which matters, because 47 of 85
  `scriptPath` targets were already dead on the origin *before* any migration.
- `tool-results/` **decays.** The destination CLI's own retention sweeper pruned one blob after
  install (11 → 10) `[LIVE]`; the origin store was already inconsistent (5 keys referenced, 11 on
  disk, 3 dangling, 9 orphaned). Copy sidecars late, verify counts after the first launch, and treat
  this store as best-effort.

### 6.2 Off-transcript offload — exactly three places

All three are **absolute-path pointers** `[M]`:

1. `<persisted-output>\nOutput too large (NN KB). Full output saved to: <abs>/tool-results/<9char>.txt`
   inside a `tool_result.content` **string** — the key is recoverable only by parsing that path;
2. `toolUseResult.transcriptDir` → `…/<SID>/subagents/workflows/wf_<runId>` (89 refs);
3. `toolUseResult.scriptPath` → `…/<SID>/workflows/scripts/<name>-wf_<id>.js` (89 refs).

Note what is **not** offloaded: attachments **inline the full text** in
`attachment.content.file.content`. There is no content-addressed blob store and no paste-cache
reference anywhere `[M]`.

### 6.3 The one place sidecars fragment across project dirs

The transcript never fragments: the source session ran under **46 distinct `cwd` values** yet all
47,088 records live in **one** `.jsonl`, in the project dir of the cwd the session was *created* in
(`F17`). Only the **Workflow tool** writes into the *current* cwd's project dir — via `N8n()` above.
On the source session that was 9 files / 76,374 B of `workflows/scripts/*.js` scattered across five
**sibling** project keys that contain no transcript of their own.

Those five sibling keys were backed up and **never installed** at the destination — the migration's
one still-open coverage gap. Any complete transplant must, for each sibling key, copy
`<sibling>/<SID>/workflows/scripts/` into
`mangle(realpath(<corresponding destination subdirectory>))/<SID>/workflows/scripts/`.

---

## 7. Memory and the tasks store

Two shared stores with **different keys**, neither of which is discoverable from the other.

### 7.1 `projects/<KEY>/memory/*.md` — PROJECT-keyed

- Keyed by the **mangled project key**, not by session. Shared by every session in that project
  `[M]` (R05, R09).
- Source corpus: 24–25 `.md`, 399,050 B of content (862 KB with front-matter). Largest:
  `simlab-roadmap.md` 144,716 B, `simlab-project.md` 57,797 B, `phase2-progress.md` 25,784 B,
  `validation-discipline.md` 25,849 B, `MEMORY.md` 7,834 B (a plain index).
- Front-matter schema on every file except the index `[M]`:

```yaml
---
name: <slug>
description: "<one-line>"
metadata:
  node_type: memory
  type: project | reference | feedback
  originSessionId: <the session that wrote it>
---
```

- **This is the highest value per byte in the entire tree.** It carries the project's standing
  directives and survives compaction, session death and session migration.
- **Implication for migration:** because the key is the *project* key, memory does **not** follow a
  session automatically — you must copy `projects/<ORIGIN_KEY>/memory/` → `projects/<DEST_KEY>/memory/`
  explicitly. It is not part of the session manifest and a `find ~/.claude -name '*<SID>*'` sweep
  **will not find it**.
- Migrated `[LIVE]`: 24 files.

### 7.2 `tasks/<cliSessionId>/` — SESSION-keyed

- `~/.claude/tasks/<sessionId>/`, one directory per session, at the **top level of `~/.claude`** —
  **not** under `projects/`. Therefore **not discoverable from the project path** `[M]` (R09 §7).
- **There is no `~/.claude/todos/`** (`F15`). That directory does not exist.
- Contents: `<n>.json` per task, plus `.highwatermark` (1 byte, content `3`, purpose unverified
  `[I]`) and a 0-byte `.lock`.
- Record schema, verified across all 152 `[M]`:

```json
{"id":"105","subject":"…","description":"…","activeForm":"…",
 "status":"completed","blocks":[],"blockedBy":[]}
```
(`activeForm` is optional; absent on older records.)

- Status histogram on the source session: **completed 141 / pending 8 / in_progress 3**. The 11
  non-completed tasks are **live agenda** and must survive.
- **No absolute paths in the records** ⇒ the store is host-portable. But the **directory name is the
  sessionId**, so any session-id rewrite must rename it — another reason not to rewrite session ids.
- **Copy only `tasks/<SID>/`.** Sweeping `tasks/` collects other sessions' agendas.

### 7.3 Stores that look relevant and are not

| Store | Reality | Cite |
|---|---|---|
| `~/.claude/sessions/<PID>.json` | **live-process registry**, keyed by PID, existing only while a CLI process is alive: `{pid,sessionId,cwd,startedAt,procStart,version,peerProtocol,kind,entrypoint,name,nameSource}`. Not an archive. A copied stale entry advertises a non-existent peer. | `F12` |
| `~/.claude/history.jsonl` | the interactive-**TTY up-arrow buffer**. **0 records for the source session** — Desktop-spawned sessions (`entrypoint:"claude-desktop"`) never write it. Leaks 1,068 unrelated prompts and other projects' absolute paths. | `F13` |
| `~/.claude/backups/` | a 5-deep ring of `~/.claude.json` **only** — identity blobs, not session data. **Nothing in `~/.claude` backs up the transcript or the memory store.** | `F14` |
| `~/.claude/file-history/` | empty on both hosts; its purpose as a `/rewind` snapshot store is `[I]`, never observed. Accepted loss: no pre-edit snapshots at the destination. | `F16` |
| `~/.claude/session-env/<SID>/` | empty; recreated at session start. | R09 |
| `~/.claude/shell-snapshots/*.sh` | full zsh function/alias/PATH dumps. Copying gives the destination a broken shell. | R09 |
| `<UD>/Local Storage/`, `IndexedDB/` | 7 keys of disposable UI state (selection, composer drafts, pane layout, a cost cache) + the cloud chat cache. **No session records.** Touching the leveldb of a running instance corrupts it. | R03 |
| `content-replacement` records | **not** a path-substitution facility — `{kind:"tool-result", toolUseId, replacement}`, i.e. oversized-tool-result offloading, behind a feature flag. Cannot rewrite a path. | `F19` |

---

## 8. Compaction, and what actually reaches the wire

### 8.1 Compaction is fully in-band: two adjacent records

```jsonc
// 1. the boundary
{"type":"system","subtype":"compact_boundary","level":"info","content":"Conversation compacted",
 "parentUuid":null,                       // <- boundaries are ROOTS
 "logicalParentUuid":"<pre-compact tail uuid>",
 "compactMetadata":{"trigger":"auto","preTokens":1004402,"postTokens":17775,"durationMs":137609,
   "preCompactDiscoveredTools":[…],
   "preservedSegment":{"headUuid":…,"anchorUuid":…,"tailUuid":…},
   "preservedMessages":{"anchorUuid":…,"uuids":[…],"allUuids":[…]}},
 "uuid":"…", …envelope…}

// 2. the summary, as a synthetic user turn
{"type":"user","parentUuid":"<boundary uuid>","promptId":"…",
 "message":{"role":"user","content":"This session is being continued from a previous conversation…\n\nSummary:\n1. Primary Request and Intent:…"},
 "isVisibleInTranscriptOnly":true,"isCompactSummary":true,"uuid":"…", …envelope…}
```

27 boundaries × ~1 M `preTokens` each is **why the file is 216 MB**: nothing is deleted at
compaction, the pre-compaction history stays on disk in full.

Detector `[C]`: `gAl(line)` returns non-null only for `type==="system" && subtype==="compact_boundary"`,
and reports `hasPreservedSegment = Boolean(compactMetadata?.preservedSegment || …preservedMessages)`.
That is the hook a "resume from the last compact boundary" fallback rides on.

### 8.2 What a 216 MB resume actually puts on the wire — `E13`, measured

The real 216,236,906-byte / 47,088-line transcript, loaded in full:

| Quantity | Value |
|---|---|
| Peak RSS | **1,044,296 KB = 1.02 GB** (with `NODE_OPTIONS=--max-old-space-size=8192`) |
| Wall clock to first request | **2 m 56.70 s** |
| OOM | **none** |
| File afterwards | **byte-identical**, hash unchanged; nothing else written |
| Request body #1 | **2,191,582 B (2.19 MB)** |
| Messages on the wire | **422** — user 191 / assistant 190 / **system 41** |
| Content blocks | text 162 · **thinking 166, 166/166 signed** · tool_use 183 · tool_result 183 · bare-string 47 |
| Tools / model / max_tokens | 27 / `claude-opus-4-8` / 64000 |
| Replay start point | **the last compact boundary** — the compact-summary text is present in the body |
| `/Users/jamiedoe` on the wire | **349 occurrences**, from historical prose and tool results |
| Estimated context | **~521k tokens** |
| Request header | `x-claude-code-session-id: <the FILENAME uuid>` |

**Read this table twice.** A 206 MiB transcript costs ~3 minutes and ~1 GB of RSS to load, then puts
~2.2 MB / ~521k tokens on the wire — because the replay starts at the **last compact boundary**, not
at line 1. The disk size and the context size are almost unrelated.

`role:"system"` inside `messages` is **not** a version-skew artifact: a fresh 2.1.215 session emits
it too (the deferred-tools notice) `[M]` (`E2` §3.2).

### 8.3 Thinking blocks

- Thinking blocks **are** transmitted, with their signatures, verbatim: 28/28, 34/34, 166/166 across
  three independent runs (`K5`).
- The signature is a **server-side attestation over exact content**. A rejection is
  `400 messages.N.content.M.thinking.signature: The signature provided is not valid for this content`
  — **one request, no retry, no fallback, exit 1**. `keep:"all"` is hardcoded in `Fsd` with no flag
  or env knob (`K6`).
- **Never fabricate a signature** in a test fixture: a fabricated signature is guaranteed-invalid and
  makes any API-touching outcome uninterpretable. Lift a real one from a genuine record, and keep a
  `-notext` control variant (text block instead of thinking) to separate "signature rejected" from
  "placement wrong".
- **Stripping thinking blocks is prohibited.** `stripThinkingBlocksFromFile` deletes **6,331 of
  21,859** assistant records outright and severs **~6,332** `parentUuid` links, collapsing walk-back
  depth to **1**. It reads the whole file into one JS string (~2 GB peak, near Node's ~512 M-char
  cap) and rewrites **in place** via `.tmp`+rename. Three code paths call it: the Desktop's
  CLI-session import, `claude://resume`, and the recovery UI. **Never trigger any of them.**
- Cross-account replay: `E13` put 166 thinking blocks signed by the **origin** account/org onto the
  wire under the **destination** account/org, and the session subsequently ran — strong evidence it
  is accepted, but the controlled single-turn test was never run. If it ever does fail, the
  alternatives are (a) resume from the last compact boundary, or (b) read-only history plus a fresh
  session seeded from `memory/` and `tasks/`. **Minting a new session id is known not to help** —
  `E2` already resumed with a filename uuid differing from every record's `sessionId` and the
  signatures went out verbatim.

---

## 9. Version skew

### 9.1 What actually changed, 2.1.170 → 2.1.215 `[M]`

| Field | 2.1.170–2.1.187 | 2.1.215 |
|---|---|---|
| `slug` | present ×32,414 | **absent** |
| `effort` on `assistant` | absent | present (`"xhigh"`) |
| `type:"mode"` records | 3,432 | **none emitted** |
| `attachment.queued_command.timestamp` | usually absent | present |
| `message.model` | `claude-opus-4-8` | `claude-opus-5` |
| everything else | — | identical |

**No structural drift across 2.1.170 → 2.1.187 at all** — every apparent gap in the census is
rarity, not schema change.

### 9.2 What is tolerated

- 2.1.215 **loads 2.1.170 records without complaint**, including `compact_boundary` and the
  now-unemitted `mode` records (`K4`, `E2`).
- Unknown/obsolete envelope fields are simply carried; they reach the API **0 times** (`K3`), so a
  `field_patch` rule class for version skew is **dead work**.
- The reader is a hand-written mapper. **There is no zod schema and no version field** anywhere in
  the Layer-1 metadata `[C]`; unknown keys are silently ignored on read (no `...e` spread) **and
  therefore permanently erased on the next save**. `{"sessionId":"local_x"}` alone loads without
  error.
- Only `remoteMcpServersConfig` entries are zod-validated — malformed entries are silently dropped.

### 9.3 What to re-verify against a newer build

Before trusting this document against a CLI more than a few minor versions newer:

1. The mangler (`Pw`, `Jvt = 200`) — re-run `mangle.py` against ≥3 live probe dirs (§10.1).
2. `$8y` / `cM` — confirm no global fallback branch appeared, by probing a decoy placement.
3. Whether `sessionStore` / `--session-mirror` is now configured (`E6` — "re-check at every G0").
4. The Layer-1 writer key order and the reader's required set (§4.1).
5. Whether `stripThinkingBlocksFromFile` gained new call sites.

---

## 10. Zero-token measurement techniques

**Every experiment in the source session ran at zero API tokens.** These two techniques are why the
mechanics above could be measured at all, and why doing so was safe. Use them for anything you need
to establish rather than assume.

The dead-port probe is implemented, hardened and parameterised as `st-verify.sh` §7 in this
skill — use that rather than an ad-hoc script; it decides on two independent positive signals
rather than on an exit code. The recording mock API is shipped as `scripts/st_mock_api.py`.

### 10.1 The dead-port probe — "did the transcript load?"

`F22`. The CLI creates and touches `$CLAUDE_CONFIG_DIR/projects/<mangled>/<sid>.jsonl` **during
startup, before the first API call.** Point `ANTHROPIC_BASE_URL` at a dead port under a timeout and
the whole resolver runs for free:

```bash
timeout 25 env ANTHROPIC_BASE_URL=http://127.0.0.1:1 \
    CLAUDE_CONFIG_DIR="$RIG/cfg" ANTHROPIC_API_KEY=dummy \
    "$CLI" --resume=<sid> --print 'reply with exactly: OK'
```

| exit | stdout/stderr | meaning |
|---:|---|---|
| `1` | stderr `No conversation found with session ID: <uuid>` | the resolver did **not** find the file |
| `124` | stdout `Execution error` | the transcript **was** found, parsed and replayed, then hung on the dead port |

**Corroborate independently of the exit code** — this is the `M7`/`F11` discipline, and it is what
makes the probe trustworthy: every **LOADED** run appended to its transcript (2,089 B →
13,388–13,398 B) while every **NOT-FOUND** run left the file at exactly 2,089 B. Assert the byte
growth, not just the exit code.

`probe.sh`, the placement variant (creates a dir, cds into it, runs a *fresh* session, then reads
which project dir the CLI created):

```bash
#!/bin/bash
S=<rig root>
export CLAUDE_CONFIG_DIR="$S/cfg"
CLI=<path to the claude binary>
[[ "$CLAUDE_CONFIG_DIR" == "$S/cfg" ]] || { echo "SAFETY ABORT"; exit 9; }
d="$1"; mkdir -p "$d"; cd "$d" || exit 1
echo "### PWD=$(pwd -P)  (logical: $(pwd -L))"
timeout 12 env ANTHROPIC_BASE_URL=http://127.0.0.1:1 \
    CLAUDE_CONFIG_DIR="$S/cfg" ANTHROPIC_API_KEY=dummy \
    "$CLI" --print 'hi' >/dev/null 2>&1
echo "  exit=$?"
```

Then `ls "$CLAUDE_CONFIG_DIR/projects/"` and compare against `mangle.py`'s prediction. This is how
the mangler reached 22/22 without a single API call.

### 10.2 The recording mock API — "what does the CLI actually send?"

`mock_api.py` is ~100 lines of `http.server` with **no third-party deps**. It records every request
verbatim and answers `/v1/messages` with a well-formed SSE stream, so **a full turn completes
locally at zero cost**. This converts "what does the CLI send" from speculation into measurement.

```bash
setsid nohup python3 mock_api.py "$CAPDIR" 8793 >mock.log 2>&1 &
timeout 90 env ANTHROPIC_BASE_URL=http://127.0.0.1:8793 \
    CLAUDE_CONFIG_DIR="$RIG/cfg" ANTHROPIC_API_KEY=dummy \
    "$CLI" --resume=<sid> --print 'reply with exactly: OK'
```

It writes, per capture dir:

- `requests.ndjson` — one line per request: index, timestamp, method, path, **headers with
  `x-api-key` / `authorization` redacted**, body length;
- `body_<NNN>_<path>.json` — the verbatim request body.

Essentials of the implementation (copy it rather than rewriting; the SSE frame order matters):

- `protocol_version = "HTTP/1.1"`, `log_message` silenced;
- `/v1/messages/count_tokens` → `{"input_tokens": 1234}`;
- `/v1/messages` → SSE: `message_start` → `content_block_start`(text) →
  `content_block_delta`(text_delta "OK") → `content_block_stop` → `message_delta`(stop_reason
  end_turn) → `message_stop`, then close.

Findings that only the mock could produce: the 429,452 B byte-identical-request comparison that
settled `K1`; the "envelope fields reach the wire 0 times" result (`K3`); the `E13` wire census in
§8.2.

**Reading the system prompt.** The captured body is the *complete* request, so it exposes the
system prompt the CLI assembled — something available nowhere else. Captured top-level keys
`[M]`:

```
['context_management','max_tokens','messages','metadata','model',
 'output_config','stream','system','thinking','tools']
```

`system` is a **list of three text blocks** `[M]`:

1. `x-anthropic-billing-header: cc_version=2.1.215.0cd; cc_entrypoint=claude-desktop;` — the
   version/entrypoint attribution, in-band as a system block;
2. `You are a Claude agent, built on Anthropic's Claude Agent SDK.` — the preset preamble;
3. the full `claude_code` preset body plus whatever the caller appended.

That is how you answer questions like "does the destination see the skill I just installed?"
(compare the skill listing inside block 3 across two runs) or "did the entrypoint/version change
after the transplant?" — with a diff, not a guess. It is the measurement behind the finding that
**skills are enumerated at process startup and cached for the process lifetime**, which in turn is
why shared assets must be installed **before** launching the destination.

`mock_sig400.py` is the fail-mode simulator: it returns the API's own error shape for any request
carrying a signed thinking block, so the cross-account signature-rejection handling path can be
exercised without ever provoking a real 400.

### 10.3 Two more reusable techniques

- **The 4-cell matrix.** `E3` isolated the `relocated` chdir by running four PTY sessions over *one*
  fixture, varying exactly one thing each: `relocated` present with the in-record sessionId ·
  present with the filename uuid · absent · absent-but-every-record-says-`cwdB`. Rows 1-vs-3 differ
  by a single line and prove causation; row 4 is what proved `$.cwd` inertness (`K9`). When a
  mechanism has two plausible causes, build the matrix instead of arguing.
- **Synthetic fixtures.** `make_synthetic.py` builds 4-line transcripts (`user` → `assistant`
  (thinking) → `last-prompt` → `custom-title`) shaped for 2.1.215: **no `slug`, no `mode`, `effort`
  present**, `JSON.stringify`-equivalent compact separators `(',',':')`, `ensure_ascii=False`,
  LF-terminated. The thinking block **and its signature are lifted verbatim from a genuine record**
  (see §8.3).

### 10.4 Rig discipline — non-negotiable, each learned the hard way

- **Every CLI invocation sets `CLAUDE_CONFIG_DIR` inside the rig, behind a guard clause that aborts,
  and re-passes it on the `env` line:**

```bash
[[ "$CLAUDE_CONFIG_DIR" == "$S/cfg" ]] || { echo "SAFETY ABORT"; exit 9; }
case "$CLAUDE_CONFIG_DIR" in /home/*/.claude|/home/*/.claude/*) echo "SAFETY ABORT: live config"; exit 9;; esac
```

- **Give each experiment its own `CLAUDE_CONFIG_DIR`.** `E4` was contaminated mid-run by a
  concurrent agent creating probe dirs inside a shared `cfg/projects`, silently changing the search
  space the scoping test depended on. It had to be restored and re-run in a private dir.
- **Never `pkill -f <pattern>`** — it self-matched and killed a run mid-experiment (exit 144).
  Likewise **never `pgrep -af 'user-data-dir=.*acct-b'`**: it self-matches and returned 2 false
  positives (the checking shell and its `eval` child) (`F21`). The correct form is:
  `ps -eo pid,comm,args --no-headers | awk '$2 ~ /claude/ && /acct-b/'`.
- **Serialize `ssh` calls**, or set `ControlMaster=auto` with retries — a burst of parallel calls
  produced `mux_client_request_session: session request failed` / `ControlSocket … already exists`,
  which silently falls back to a non-multiplexed connection and is easily misread as a remote
  failure. Warm multiplexed round trip: 20–120 ms; cold: 0.7 s.
- Cross-platform, for anything that may run on the origin: **macOS has no GNU `timeout`** (use
  `perl -e 'alarm N; exec @ARGV'`); `stat -f` not `-c`; BSD `find` rejects `-newermt @epoch`;
  `shasum -a 256` exists but `/sbin/sha256sum` is **5× faster** (0.11 s vs 0.54 s on 216 MB, all
  digests identical); `zstd` may be absent; macOS `rsync` may be **openrsync** (no `-H`, `-X`,
  `-A`, `-S`, `--iconv`, `--fake-super`, `--protect-args`; but `--link-dest`, `--checksum`,
  `--itemize-changes`, `--append`, `--inplace`, `-n` are all present).
- Ship remote helper scripts **over stdin** (`ssh host 'python3 -' <<'PY'`), never write them to the
  origin — that is what makes "we wrote nothing to the origin" literally true rather than merely
  intended. Constrain to the remote Python's stdlib.

---

## 11. Quick reference — the ten things to get right

1. Project dir = `mangle(realpath(launch cwd))`. Compute it; never edit another key. §2, §3.3
2. Filename stem = the **origin** `cliSessionId`. Never rename. §4.1, §6
3. Copy the transcript **byte-for-byte**; append only. Historical `$.cwd` is inert. §4.2
4. Copy the sidecar dir, `memory/` (project-keyed!) and `tasks/<SID>/` (session-keyed!). §1.3, §7
5. Never strip thinking blocks; never use `claude://resume`, the import path, or the recovery UI. §8.3
6. Layer-1 metadata goes under the **destination** account/org, named `${sessionId}.json`, with
   `cliSessionId` set, < 10 MiB, mode 0600. §1.2, §4.1
7. Drop Layer-1 files only while that instance is **stopped**. §1.4
8. Install skills/plugins **before** launching — they are cached at process startup. §4.1, §10.2
9. Prove it: `sha256(destination[0:N]) == sha256(origin)` where N = the origin byte size. §5
10. Measure, don't guess: dead-port probe for placement, recording mock for the wire. §10
