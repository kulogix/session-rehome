<!-- shipped with the claude-session-transporter skill -->

> **What this file is.** The distilled evidence base of the source migration — the one
> completed cross-host, cross-account move this skill was built from. It is a **historical
> record**, not a set of instructions: the absolute paths, hostnames, account UUIDs and
> session ids in it name that specific run and will not exist on your machine. Read it when
> a claim made elsewhere in this skill is disputed and you need to know how it was
> established, or what its exact numbers were. Everything actionable has been restated,
> generalised and made executable in `SKILL.md`, the other three reference files, and
> `scripts/`. Nothing here should be copy-pasted and run.
>
> Where it names a script (`scripts/pull-checkpoint.sh`, `scripts/transplant.py`,
> `scripts/oracle-run.sh`, `scripts/e13-fullfile-load.sh`), those are the **one-off scripts of
> that run**, not files in this skill. Their generalised, guarded successors are
> `scripts/st-checkpoint.sh`, `scripts/st-transplant.py` and `st-verify.sh` §7.
>
> Evidence tags used throughout: `[M]` measured · `[C]` lifted from code · `[D]` derived ·
> `[I]` inferred · `[LIVE]` re-verified on disk while writing.

# SKILL-SOURCE-FACTS — evidence base for `claude-session-transporter`

Harvested 2026-08-01 from a **completed, working** cross-host / cross-account Claude Code session
migration. This file is the skill's evidence base. It replaces reading the 113k words of recon.

**Evidence tags used throughout:** `[M]` measured this session · `[C]` lifted from code (CLI ELF or
Desktop `app.asar`) · `[D]` derived from `[M]`+`[C]` · `[I]` inferred, not verified · `[LIVE]`
re-verified on disk while writing this file.

**Source documents** (all under `/home/dana/Projects/SimLab/_transporter/`):
`plans/MASTER-PLAN.md` · `plans/AUTOMATION-WORKSTREAM.md` (not on the transporter path) ·
`inventory/R01…R12` + `D-operator-first…` + `D-FED-…` · `experiments/LADDER-RESULTS.md` ·
`experiments/{E-RIG,E2,E3,E4,E5,E11,E12}*.md` · `experiments/E13.log` ·
`scripts/{pull-checkpoint.sh,transplant.py,e13-fullfile-load.sh,oracle-run.sh,askpass-setup.md}` ·
`scripts/measurement/` (the rig).

---

## 0. THE RUN THAT HAPPENED — identifiers and constants

| Role | Value |
|---|---|
| ORIGIN host | `mac1` (`jamiedoe@192.0.2.5`), macOS 26.5.2, arm64 T6031, APFS (case-**insensitive**) |
| ORIGIN home / user | `/Users/jamiedoe` |
| ORIGIN account / org UUID | `aaaaaaaa-1111-4111-8111-111111111111` / `0a0a0a0a-1111-4111-8111-111111111111` (`origin1@example.com`) |
| ORIGIN project root | `/Users/jamiedoe/Projects/CLAUDE/transporter` |
| ORIGIN project key | `-Users-jamiedoe-Projects-CLAUDE-transporter` (43 chars) |
| DEST host | Linux x86_64, Ubuntu 24.04, ext4 (case-**sensitive**), user `dana` |
| DEST account / org UUID | `bbbbbbbb-2222-4222-8222-222222222222` / `0b0b0b0b-2222-4222-8222-222222222222` (`dest@example.com`) |
| DEST project root | `/home/dana/Projects/transporter` |
| DEST project key | `-home-dana-Projects-transporter` (31 chars) |
| SID (session id, **unchanged** across the move) | `5e55105e-0000-4000-8000-000000000001` |
| Desktop instance dirs | `~/.claude-instances/acct-a` (was running), `~/.claude-instances/acct-b` (target) |
| CLI binary | `~/.claude-instances/acct-a/claude-code/2.1.215/claude` — ELF x86-64, **not stripped**, 265,239,536 B, sha256 `c1efffaaf370aa18…` |
| Desktop app | `/usr/lib/claude-desktop/resources/app.asar`, `@ant/desktop` v1.22209.3, Electron 42.5.1, bundles `@anthropic-ai/claude-agent-sdk` 0.3.215 |
| ORIGIN transcript versions | `2.1.170` (3,559 recs) → `2.1.181` (13,318) → `2.1.187` (16,928) |
| DEST CLI version | `2.1.215` |
| Checkpoint root | `/home/dana/Projects/SimLab/_backups/mac1/<UTC-ts>/`, `latest` symlink |

**Cross-account is real** (different account AND org UUIDs). **Cross-instance is not** — acct-a and
acct-b on the destination share one account/org; that is process isolation only `[M]`.

---

## 1. WHAT CONSTITUTES "A SESSION" — the two explicit lists (the M3 guard)

> **Rule: whitelist, never blacklist, when copying out of a `~/.claude`.** The origin `~/.claude` is
> 5.5 GB across 48 project dirs; the session is 370 MiB of it. Enumerate exact paths.

### 1.1 LIST A — COPY. Everything belonging to session `<SID>` under a `~/.claude`

`find ~/.claude -name '*<SID>*'` returns exactly **8 roots** `[M]`. Recurse them **fully** — a
`-maxdepth 1` sweep misses `subagents/workflows/`, which is 38 % of all bytes.

| # | Component | Files | Bytes | Path pattern |
|---:|---|---:|---:|---|
| 1 | **main transcript** | 1 | 216,236,906 | `projects/<ORIGIN_KEY>/<SID>.jsonl` |
| 2 | Task/Agent subagent transcripts | 51 | 9,833,741 | `projects/<ORIGIN_KEY>/<SID>/subagents/agent-<17hex>.jsonl` |
| 3 | Task/Agent subagent meta | 51 | 6,527 | `…/subagents/agent-<17hex>.meta.json` |
| 4 | **workflow agent transcripts + meta** | 1,765 | 148,506,101 | `…/subagents/workflows/wf_<runId>/agent-*.{jsonl,meta.json}` — 85 run dirs, 840 agents |
| 5 | tool-results overflow blobs | 11 | 5,911,806 | `…/<SID>/tool-results/<9-char base36>.txt` |
| 6 | workflow run records | 85 | 6,770,682 | `…/<SID>/workflows/wf_<12char>.json` |
| 7 | workflow scripts (root cwd) | 28 | 328,890 | `…/<SID>/workflows/scripts/<name>-wf_<id>.js` |
| 8–12 | **workflow scripts under 5 SIBLING project keys** | 9 | 76,374 | `projects/<ORIGIN_KEY><suffix>/<SID>/workflows/scripts/*.js` |
| 13 | Task-tool store (todos) | 154 | 122,592 | `tasks/<SID>/` — 152 × `<n>.json` + `.highwatermark` + `.lock` |
| 14 | macOS junk (drop) | 2 | 12,296 | `.DS_Store` ×2 |
| | **TOTAL** | **2,157** | **387,805,915** (370 MiB) | |

Excluding the two `.DS_Store`: **2,155 files / 387,793,619 B**.

**Sibling project keys (rows 8–12)** — created because `cwd` changed mid-session; each contains
**only** `<SID>/workflows/scripts/`, no transcript:

```
<ORIGIN_KEY>--research-re                              4 files  35,940 B
<ORIGIN_KEY>--research-re-rust                         1 file   10,523 B
<ORIGIN_KEY>--research-re-tools-devio-fasp-diag        2 files  17,407 B
<ORIGIN_KEY>-SimLab-acmeorg-simlab                     1 file    5,823 B
<ORIGIN_KEY>-SimLab-acmeorg-simlab-rust                1 file    6,681 B
<ORIGIN_KEY>-DevIO-acmeorg-devio                       0 files  (its <SID>/ subtree was already deleted)
```

### 1.2 LIST A′ — COPY TOO, but **project**-scoped, not session-scoped

| Component | Files | Bytes | Path | Note |
|---|---:|---:|---|---|
| **project memory** | 24 (25 on origin at survey) | 399,050 (862 KB w/ front-matter per R05) | `projects/<ORIGIN_KEY>/memory/*.md` | **Highest value per byte in the whole tree.** Shared by every session in the project. Keyed by PROJECT key, not SID. |
| user settings | 1 | 112 | `settings.json` | MERGE 2 keys only (`skipWorkflowUsageWarning`, `enabledPlugins`) |
| global skills | ~12 dirs | ~2.9 MiB of authored content (341 MB on disk) | `skills/` | Install at DEST **before** launching (see §5 K8) |
| plugins | — | 4.4 MB | `plugins/` | **REGENERATE, do not copy** — arm64 payload + absolute `installPath` |

### 1.3 LIST B — **NEVER COPY.** Account-coupled or host-coupled

Each row is a *measured* reason, not a guess.

| Path | Why it must not be copied |
|---|---|
| `~/.claude/.credentials.json` (322 B, 0600) | **IS the account identity** — `claudeAiOauth.{accessToken,refreshToken,expiresAt}`. Never read, never print, never checksum. |
| `~/.claude.json` (54,354 B, **outside** the dir) | `machineID` (host), `userID` + `oauthAccount{19 keys}` (account), `projects{21 absolute paths}` (host), 442 feature flags, per-org caches. **Hand-add exactly one entry at DEST**: `projects["<dest root>"].hasTrustDialogAccepted = true`. |
| `~/.claude/backups/` (5 × 54,354 B) | Rolling ring of `~/.claude.json` — same identity blobs. **This is what M3 swept.** |
| `~/.claude/history.jsonl` (1,068 lines, 433,604 B) | TTY up-arrow buffer. **0 records for `<SID>`** (Desktop sessions never write it). Leaks 1,068 unrelated prompts + absolute paths of other projects. |
| `~/.claude/tasks/<other-SID>/` | Other sessions' task stores. Copy **only** `tasks/<SID>/`. |
| `~/.claude/sessions/<PID>.json` | **Live-process registry**, not an archive: `{pid,sessionId,cwd,startedAt,procStart,version,peerProtocol,kind,entrypoint,name,nameSource}`. A stale entry advertises a non-existent peer. |
| `~/.claude/session-env/<SID>/` | Empty on both hosts; recreated at session start. |
| `~/.claude/shell-snapshots/*.sh` (11 files, 616 KB) | Full **zsh** function/alias/PATH dump with sdkman/asdf/wasmer/arm64-clangd paths. Copying gives the destination a broken shell. |
| `~/.claude/telemetry/*.json` (1.7 MB) | Undelivered analytics carrying `device_id`, `auth`, `env.platform:"darwin"`. |
| `~/.claude/policy-limits.json` (125 B) | **This org's** server-pushed policy. Copying applies the wrong org's restrictions. |
| `~/.claude/stats-cache.json` (1,450 B) | Account usage; also badly stale (`lastComputedDate 2026-03-18`). |
| `~/.claude/cache/changelog.md` (255,309 B) | Regenerated on demand. |
| `~/.claude/debug/latest` | Dangling **absolute** symlink. |
| `~/.claude/file-history/`, `paste-cache/`, `downloads/` | Empty on both hosts (swept). Accepted loss: `/rewind` has no pre-edit snapshots at DEST. |
| `~/.claude/.last-cleanup` | Destination writes its own. |
| `~/.claude/plugins/` | Absolute `installPath`/`installLocation` + arm64 `clangd` binary. Reinstall from the marketplace. |
| **all** `.DS_Store` | 39 in the project tree, several in `~/.claude`. Pure macOS Finder junk. |
| `<user-data-dir>/config.json` | Contains `oauth:tokenCache` + `oauth:tokenCacheV2` — encrypted OAuth material. **The user named this file explicitly; no candidate design listed it.** |
| `<user-data-dir>/{Cookies*,Local State,Local Storage/,IndexedDB/,ant-did,ant-device-registry.json}` | Chromium leveldb + device attestation. Touching leveldb of a running instance corrupts it. Verified to hold **only** disposable UI state (selected folder, composer drafts, pane layout, a cost cache). |
| origin `_research/re/server_keys/`, `_research/re/captures/` | Probable live FASP session keys. Quarantine 0700, `CONTAINS_SECRETS`, never git, never archive. |

**Enforcement shape that works:** an allowlist of paths to copy **plus an independent denylist
assertion executed over the staged bytes**. The allowlist alone is what M3 defeated.

### 1.4 The `~/.claude` layout, for orientation

```
projects/<mangled-cwd>/
├── <cliSessionId>.jsonl        the transcript (append-only JSONL)
├── <cliSessionId>/             sidecar dir, keyed by SESSION ID
│   ├── subagents/{agent-<17hex>.jsonl,.meta.json, workflows/wf_<runId>/…}
│   ├── tool-results/<9char>.txt
│   └── workflows/{wf_<id>.json, scripts/<name>-wf_<id>.js}
└── memory/*.md                 keyed by PROJECT KEY, session-independent
tasks/<sessionId>/{<n>.json,.highwatermark,.lock}
```

**The transcript is NOT fragmented across project dirs.** The session ran under **46 distinct `cwd`
values** yet all 47,088 records live in one `.jsonl`, in the project dir of the cwd the session was
*created* in. Only the Workflow tool writes into the *current* cwd's project dir `[M]`.

---

## 2. TRANSCRIPT RECORD SCHEMA — enough to validate a transcript

### 2.1 File-level invariants (assert all of these)

| Invariant | Origin value |
|---|---|
| One JSON object per line, UTF-8, LF-terminated | last byte `0x0a` (`tail -c1 \| xxd`) |
| Parse failures | **0 / 47,088** |
| `\/` slash-escaping | **0 occurrences** → a byte-level `sed` on paths is JSON-*safe* (but semantically forbidden, §7 M7/T7) |
| Append-only | resume is a **pure append**; first N bytes byte-identical after 3 resumes `[M]` |
| Max line length | 128,423 B |
| Line count | 47,088 |

### 2.2 The nine record types — the complete census. There are **exactly nine**.

| `type` | count | has `uuid`? | in DAG? | purpose |
|---|---:|---|---|---|
| `assistant` | 21,859 | yes | yes | exactly one model content block per record |
| `user` | 9,569 | yes | yes | human turn, tool_result, or compact summary |
| `ai-title` | 3,466 | **no** | no | auto title, last-write-wins |
| `last-prompt` | 3,452 | **no** | no | truncated prompt + `leafUuid` resume-head pointer |
| `mode` | 3,432 | **no** | no | UI mode; **not emitted by 2.1.215** |
| `attachment` | 1,949 | yes | yes | injected context |
| `custom-title` | 1,769 | **no** | no | user-set title |
| `queue-operation` | 1,164 | **no** | no | prompt-queue journal |
| `system` | 428 | yes | yes | compact boundaries, API errors, hook summaries, fallbacks |

Records with `uuid`: **33,805**. Stateless housekeeping lines: **13,283**.
**There is no `type:"summary"` record** in this format version (0 across all 51 origin project dirs).
A 10th type, **`relocated`**, exists in the CLI but appears **0 times** in the origin.

### 2.3 The common envelope (on `assistant`/`user`/`attachment`/`system`)

| field | type | notes |
|---|---|---|
| `uuid` | UUIDv4 | node identity. **Not unique** — 100 duplicates, see §2.7 |
| `parentUuid` | str \| null | `null` = root or post-compact root |
| `isSidechain` | bool | **`false` for all 33,805 main-transcript records**; `true` only in sidecar files |
| `type` | str | one of the nine |
| `timestamp` | str | ISO-8601 UTC, ms, `Z` |
| `sessionId` | str | on **all nine types**; 100 % constant in the origin. **Need not match the filename** (§4 K1) |
| `cwd` | str | absolute, varies mid-file (46 values). **INERT at runtime** (§5 K9) |
| `gitBranch` | str | `"HEAD"` on all 33,805 (project is not a git repo) |
| `version` | str | writer CLI version |
| `userType` | str | `"external"` (100 %) |
| `entrypoint` | str | `"claude-desktop"` (100 %) |
| `slug` | str | `"scalable-riding-crown"`, 32,414 records. **Removed in 2.1.215** |

### 2.4 `assistant`

Envelope + `message` (the Messages-API assistant message) + `requestId` (`req_…`, 21,852/21,859)
+ optional `effort` (2.1.215 only), `attributionMcpServer`/`attributionMcpTool` (2,431 each),
`attributionSkill` (398), `isApiErrorMessage` (34), `error`/`apiErrorStatus`/`errorDetails` (30/27/1).

`message`: `id` (`msg_…`, **shared across the several records of one API message**), `type`,
`role`, `model`, `content` (exactly one block in practice), `stop_reason`
(`tool_use` 21,204 / `end_turn` 621 / `stop_sequence` 34), `usage{…}`, `context_management`.

Four content-block variants:

| block | count | shape |
|---|---:|---|
| `text` | 7,920 | `{"type":"text","text":…}` |
| **`thinking`** | **6,344** | `{"type":"thinking","thinking":…,"signature":…}` — signature is a server-side attestation |
| `tool_use` | 9,090 | `{"type":"tool_use","id":"toolu_…","name":…,"input":{…},"caller":{"type":"direct"}}` (`caller` 100 % direct) |
| `fallback` | 11 | `{"type":"fallback","from":…,"to":…}` |

Tool-call census: Bash 4092, Edit 2671, Read 1195, Write 474, TaskUpdate 241, TaskCreate 137,
Workflow 97, `mcp__ccd_session__mark_chapter` 73, ToolSearch 37, Monitor 23, Agent 19,
AskUserQuestion 11, WebSearch 7, Skill 3, + singletons.

### 2.5 `user`

Envelope + `message{role,content}` + `promptId` (**383 distinct = 383 human turns**, max 285 records
under one) + `sourceToolAssistantUUID` (9,090 — **verified identical to `parentUuid` in 9,090/9,090**,
a redundant back-pointer) + `toolUseResult` (dict 8,750 / str 263 / list 77) + `permissionMode` (383,
only on real human turns) + `promptSource` (383, `"sdk"`) + `origin` (241: `{kind:"human"}` 138,
`{kind:"task-notification"}` 103) + the compact triple `isMeta`/`isVisibleInTranscriptOnly`/
`isCompactSummary` (27 each) + `sourceToolUseID` (3).

Content blocks: `text` and `{"type":"tool_result","tool_use_id":"toolu_…","content":…,"is_error":bool}`.

`toolUseResult` key sets per tool (needed to find structural path pointers):

| tool | keys |
|---|---|
| Bash | `stdout,stderr,interrupted,isImage,noOutputExpected`; opt `backgroundTaskId`(145), `returnCodeInterpretation`(10), **`persistedOutputPath`+`persistedOutputSize`**(5), `assistantAutoBackgrounded`(2), `staleReadFileStateHint`(1) |
| Read | `type:"text"`, `file:{filePath,content,numLines,startLine,totalLines}` |
| Write | `type:"create"`, `filePath`, `content`, `structuredPatch[]`, `originalFile`, `userModified` |
| Edit | `filePath,oldString,newString,originalFile,structuredPatch[],userModified,replaceAll` |
| Agent | `status,prompt,`**`agentId`**`,agentType,content[],totalDurationMs,totalTokens,totalToolUseCount,usage,toolStats`; async adds `isAsync,description,`**`outputFile`**`,canReadOutputFile` |
| Workflow | `status,taskId,taskType,workflowName,runId,summary,`**`transcriptDir`**`,`**`scriptPath`** |
| Task* / ToolSearch / WebSearch / WebFetch / AskUserQuestion / Monitor / Skill | see R02 §3 |
| MCP tools | bare list |

### 2.6 `attachment` — how injected context is offloaded

Envelope + `attachment:{type:…,…}`. **Attachments do NOT reference on-disk blobs** — file
attachments **inline the full text** in `attachment.content.file.content`. There is no
content-addressed blob store and no paste-cache reference anywhere `[M]`.

| `attachment.type` | n | payload |
|---|---:|---|
| `task_reminder` | 1357 | `content[]` (task objects), `itemCount` |
| `queued_command` | 187 | `prompt` (often XML `<task-notification>` with absolute temp paths), `commandMode` |
| `file` | 76 | `filename`(abs), `content.file{filePath,content,numLines,startLine,totalLines}`, `displayPath`(**relative**) |
| `edited_text_file` | 64 | `filename`(abs), `snippet` |
| `compact_file_reference` | 59 | `filename`(abs), `displayPath` — **a pointer only** |
| `ultra_effort_enter` | 50 | `reminderType` |
| `deferred_tools_delta` | 34 | `addedNames[],addedLines[],removedNames[],readdedNames[],pendingMcpServers[],needsAuthMcpServers[]` |
| `invoked_skills` | 27 | `skills[]={name,path:"userSettings:<skill>",content}`; `content` begins `Base directory for this skill: <HOME>/.claude/skills/<name>` |
| `date_change` | 26 | `newDate` |
| `mcp_instructions_delta` | 26 | |
| `agent_listing_delta` | 26 | |
| `skill_listing` | 9 | `content,skillCount,isInitial,names[]` |
| `diagnostics` | 5 | `files[]={uri(abs),diagnostics[…]}` |
| `command_permissions` | 3 | `allowedTools[]` |

**Real off-transcript offload happens in exactly three places**, all absolute-path pointers:
1. `<persisted-output>\nOutput too large (NN KB). Full output saved to: <abs>/tool-results/<9char>.txt` inside a `tool_result.content` string — **the key is only recoverable by parsing that path**;
2. `toolUseResult.transcriptDir` → `…/<SID>/subagents/workflows/wf_<runId>` (85 values);
3. `toolUseResult.scriptPath` → `…/<SID>/workflows/scripts/<name>-wf_<id>.js` (89 values).

### 2.7 DAG structure — the validation assertion set (E7 baseline)

```
records with uuid   : 33,805
distinct uuids      : 33,705      (100 duplicates)
dangling parents    : 0           every non-null parentUuid resolves
roots (parent=null) : 28          = 1 genuine root (line 3, type=user) + 27 compact_boundary
branch points (>1 child): 119     max fan-out 4
last-prompt leafUuids: 3,436      0 orphans; the LAST leafUuid must resolve
assistant records   : 21,859      of which 6,344 carry a thinking block
```

**The 100 duplicate uuids are at lines 1784–1883** (exactly 100 contiguous records), re-emitting
uuids first written at lines 12…702, immediately before the first `compact_boundary` at line 1884.
No later boundary produces duplicates. `[I]` a one-off context replay under 2.1.170.

Consequences for any tool:
- uuid→record maps must be **last-write-wins**;
- a naive "is my parent earlier in the file?" check reports **94 false violations** — an artifact of the duplicate block, not forward references;
- any rewriting tool must preserve line **order and count exactly** (47,088 in → 47,088 out);
- a DAG walker must follow `logicalParentUuid` on `compact_boundary`, or it sees 28 disconnected conversations.

### 2.8 Compaction — two adjacent records, 27 times

```jsonc
// boundary (line 1884 is the first)
{"type":"system","subtype":"compact_boundary","level":"info","content":"Conversation compacted",
 "parentUuid":null,"logicalParentUuid":"<pre-compact tail uuid>","isMeta":false,"uuid":"…",
 "compactMetadata":{"trigger":"auto","preTokens":1004402,"postTokens":17775,"durationMs":137609,
   "preCompactDiscoveredTools":["WebFetch","WebSearch"],
   "preservedSegment":{"headUuid":…,"anchorUuid":…,"tailUuid":…},
   "preservedMessages":{"anchorUuid":…,"uuids":[…],"allUuids":[…]}}, …envelope…}

// the summary, as a synthetic user turn
{"type":"user","parentUuid":"<boundary uuid>","promptId":"…",
 "message":{"role":"user","content":"This session is being continued from a previous conversation…\n\nSummary:\n1. Primary Request and Intent:…"},
 "isVisibleInTranscriptOnly":true,"isCompactSummary":true,"uuid":"…", …envelope…}
```

Compaction is fully in-band. 27 boundaries × ~1 M `preTokens` each is what makes the file 216 MB.
`gAl(line)` in the CLI returns non-null only for `type==="system" && subtype==="compact_boundary"`
and reports `hasPreservedSegment = Boolean(compactMetadata?.preservedSegment || …preservedMessages)`
`[C]` — that is the hook a "resume from last compact boundary" fallback would ride on.

### 2.9 `system` subtypes

| subtype | n | level | extras |
|---|---:|---|---|
| `stop_hook_summary` | 342 | suggestion | `hookCount,hookInfos[],hookErrors[],hookAdditionalContext[],preventedContinuation,stopReason,hasOutput,toolUseID` |
| `api_error` | 46 | error | `error{message,formatted,connection{…},isNetworkDown,rateLimits}`, `retryInMs`, `retryAttempt`, `maxRetries` |
| `compact_boundary` | 27 | info | §2.8 |
| `model_refusal_fallback` | 13 | warning | `direction:"retry"`, `trigger:"refusal"`, `originalModel`, `fallbackModel`, `requestId`, `apiRefusalCategory`, `apiRefusalExplanation` |

### 2.10 Housekeeping record shapes (no uuid, append-only, last-write-wins cells)

```json
{"type":"custom-title","customTitle":"…","sessionId":"<SID>"}
{"type":"ai-title","aiTitle":"…","sessionId":"<SID>"}
{"type":"mode","mode":"normal","sessionId":"<SID>"}
{"type":"last-prompt","lastPrompt":"…~200 chars…","leafUuid":"<uuid>","sessionId":"<SID>"}
{"type":"queue-operation","operation":"enqueue|dequeue|remove","timestamp":"…","sessionId":"<SID>","content":"<FULL untruncated prompt>"}
{"type":"relocated","sessionId":"<SID>","relocatedCwd":"<abs path>"}
```

The origin file **ends** with a `custom-title` / `ai-title` / `mode` triple — so a "last uuid" scan
must walk backwards past records that have none. `queue-operation.content` is present only on
`enqueue` (582 of 1,164) and carries the **full untruncated** user prompt.

### 2.11 Sidecar record schema

Sidecar `.jsonl` files use the **same envelope**, plus `agentId`, with `isSidechain: true` and their
own root (`parentUuid: null`). Sidechains are **referenced, not inlined** — a "copy the .jsonl"
migration loses **44 % of bytes and 100 % of subagent conversation content**.

Meta files, two shapes only (verified across all 51):
```json
{"agentType":"general-purpose","description":"…","toolUseId":"toolu_…"}
{"agentType":"Explore","description":"…","toolUseId":"toolu_…","spawnDepth":1}
```
Workflow-agent metas are degenerate: `{"agentType":"workflow-subagent","spawnDepth":1}` — no
`toolUseId`, no `description`. Linkage is **by directory name** (`wf_<runId>`) and by agentId string.

**Subagents link to the parent by `toolUseId`, not by uuid.** `meta.toolUseId` == the `id` of the
`tool_use` block in the parent's assistant turn. **The tree is two levels deep**: of 51 toolUseIds
only **16 appear in the main transcript**; the other **35 appear inside another subagent's `.jsonl`**.
⇒ **You cannot reconstruct the subagent set by scanning the main transcript. Enumerate the directory.**

`wf_<id>.json` schema (18 keys, identical across 84 files; 1 adds `error`):
`runId, timestamp, taskId, script (FULL TEXT of the .js), scriptPath (ABS — host-coupled), result,
agentCount, logs, durationMs, summary, workflowName, status, startTime, phases, defaultModel,
workflowProgress, totalTokens, totalToolCalls [, error]`.
**Every one of the 85 `script` fields is non-empty** ⇒ any missing `.js` is regenerable.

### 2.12 Version drift 2.1.187 → 2.1.215 (the reader)

| field | 2.1.170–187 | 2.1.215 |
|---|---|---|
| `slug` | present ×32,414 | **absent** |
| `effort` on `assistant` | absent | present (`"xhigh"`) |
| `type:"mode"` records | 3,432 | **none emitted** |
| `attachment.queued_command.timestamp` | usually absent | present |
| `message.model` | `claude-opus-4-8` | `claude-opus-5` |
| everything else | — | identical |

**No structural drift across 2.1.170 → 2.1.187** — every apparent gap is rarity, not schema change.
2.1.215 loads 2.1.170 records without complaint, including `compact_boundary` and `mode` `[M]`.

### 2.13 Identity/path field inventory (for a resolvability sweep)

`/Users/jamiedoe` appears **54,157 times on 33,959 of 47,088 lines**. `\/Users\/jamiedoe`: **0**.

Structural (machine-consumed) path fields, with occurrence counts:

| JSON pointer | n |
|---|---:|
| `$.cwd` | 33,805 |
| `$.message.content[].input.file_path` (Edit / Read / Write) | 2,649 / 1,130 / 457 |
| `$.toolUseResult.filePath` (Edit / Write) | 2,569 / 453 |
| `$.toolUseResult.file.filePath` (Read) | 1,129 |
| `$.toolUseResult.transcriptDir` | 89 |
| `$.toolUseResult.scriptPath` / `$…input.scriptPath` | 89 / 5 |
| `$.toolUseResult.persistedOutputPath` | 5 |
| `$.toolUseResult.outputFile` (async Agent) | 4 |
| `$.attachment.filename` | 199 records |
| `$.attachment.content.file.filePath` | 76 |
| `$.attachment.files[].uri` | 5 records |
| `$.attachment.skills[].content` (header line) | 27 |
| `$.attachment.displayPath` | **relative — never rewrite** |

Non-project absolute-path families: `/private/tmp/claude-501/<mangled>/<SID>/tasks/<taskid>.output`
(1,137 + 151 variants), `…/scratchpad` (213), `<HOME>/.claude/projects/<mangled>/memory/*.md`
(1,046 refs across 25 files), subagent/workflow sidecar paths (233), the transcript itself (27),
and ~745 macOS toolchain paths (`.local` 470, `.cargo` 154, `.asdf` 50, `.rustup` 29, `.zshrc` 18,
`.gradle` 8, `.idapro`/`.venv`/`.wasmer`/`.sdkman` 2 each) **with no valid Linux equivalent**.

**No account identity is stored in the transcript.** Exhaustive key enumeration found **no**
`accountUuid`, `organizationUuid`, `account_uuid`, `org_uuid`, and **no `sk-ant-` token anywhere**.
Only 3 lines mention `origin1@example`, all free prose. ⇒ **The account problem is a placement
problem, not a content problem.**

---

## 3. THE DESKTOP SESSION JSON — schema and the working template

### 3.1 Location, naming, permissions

```
<user-data-dir>/claude-code-sessions/<accountUuid>/<orgUuid>/local_<uuid4>.json
```
Constants lifted from the bundle `[C]`:
`CCD_SESSIONS_BASE_DIR="claude-code-sessions"` · `LOCAL_SESSION_PREFIX="local_"` ·
`SESSION_FILE_MAX_BYTES=10 MiB` · `REMOTE_MCP_PERSIST_MAX_BYTES=1 MiB` ·
`SESSION_FILE_READ_BATCH=8` · `SAVE_SESSION_DEBOUNCE_MS=1000` /
`SAVE_SESSION_ACTIVE_DEBOUNCE_MS=3000` · dir mode `0700`, file mode `0600` ·
`sessionId` regex `/^[a-zA-Z0-9_-]+$/` · deep-link uuid regex
`/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i` ·
web route `/epitaxy/<encodeURIComponent(sessionId)>` · transcript tail window `50 MiB`.

`getStorageDir()` = `join(userDataPath, "claude-code-sessions", currentAccountId, currentOrgId)`
where `userDataPath` == `--user-data-dir` when passed. `accountUuid` comes from the auth state
(`waitForAccountId()`); `orgUuid` comes from the **`lastActiveOrg` cookie** on
`session.defaultSession`, with a live cookie listener that reinitializes on change `[C]`.

**The filename is only a filter (`local_*.json`); the map key comes from the file's `sessionId`
field.** A file named `local_A.json` containing `"sessionId":"local_B"` loads as `local_B` and is
then *rewritten* to `local_B.json`, leaving `local_A.json` as a permanent ghost that reloads every
launch. ⇒ **filename must be exactly `${sessionId}.json`** `[C]`.

### 3.2 Schema — there is **no zod schema and no version field**

The whole contract is two hand-written mappers, `activeToPersisted` (writer) /
`persistedToActive` (reader) `[C]`. Only `remoteMcpServersConfig` entries get zod-validated
(malformed entries silently dropped).

**Writer emits exactly these keys, in this order** (`JSON.stringify` drops the `undefined` ones,
which is why real files are small):

```
sessionId, cliSessionId, cwd, originCwd, worktreePath, worktreeName, worktreePinned,
lastFocusedAt, sourceBranch, branch, createdAt, lastActivityAt, model, effort,
sessionSettings, agent, isArchived, title, titleSource, permissionMode, planPath,
enabledMcpTools, remoteMcpServersConfig, sshConfig, wslConfig, sshRemoteTranscriptPath,
prNumber, prUrl, prRepository, prState, prs, writtenBranches, autoFixEnabled,
autoArchiveExempt, keptDirtyWorktree, seenCommentIds, chromePermissionMode,
chromeAllowedDomains, chromeTabGroupId, cuAllowedApps, cuGrantFlags, cuLastScreenshotDims,
cuSelectedDisplayId, promptSuggestion, recap, recapAt, scheduledTaskId, spaceId,
contextExceededCount, completedTurns, transcriptUnavailable, error, errorCategory,
tccFolderKind, errorAt, queryCrashes, dispatchParentId, dispatchParentOrigin,
forkedFromSessionId, spawnedFrom, spawnedFromEndNotified, emailAddress, bridgeSessionIds,
alwaysAllowedReasons, sessionPermissionUpdates, color, classifierSummaryEnabled, spawnSeed
```

Three fields transformed on write: `originCwd: e.originCwd || ""`,
`remoteMcpServersConfig: cn(…)` (>1 MiB ⇒ tool inputSchemas stripped to `{type:"object"}`),
`alwaysAllowedReasons: Array.from(…)` (Set → array).

**Reader defaults — the definitive required/optional table** `[C]`:

| Field | On missing/undefined | Verdict |
|---|---|---|
| `sessionId` | **no default** — becomes the Map key; `undefined` poisons the map | **REQUIRED** |
| `cwd` | **no default** — everything downstream assumes a string | **REQUIRED** |
| `cliSessionId` | `undefined` ⇒ `isFirstTurn:true` ⇒ session treated as never-started | **REQUIRED to load the transcript** |
| `originCwd` | `""` then tilde-expanded | required in practice |
| `createdAt`, `lastActivityAt` | `undefined` | required in practice (ordering/UI) |
| `isArchived` | `false` | optional |
| `title` | `undefined` | optional |
| `permissionMode` | `PermissionMode.Default` | optional |
| `sessionPermissionUpdates` | `[]` | optional |
| `alwaysAllowedReasons` | `new Set([])` | optional |
| `prs` | synthesised from `prNumber`+`prUrl`+`prRepository`+`branch` if all present | optional |
| `tccFolderKind` | dropped unless a member of `TccFolderKind` | optional |
| `cuLastScreenshotDims.{displayId,originX,originY}` | `0` | optional |
| everything else | `undefined` | genuinely optional |

**Unknown fields are silently ignored on read** (there is no `...e` spread in `persistedToActive`)
**and therefore permanently erased on the next save.** There is no schema-version check and no
rejection path — `{"sessionId":"local_x"}` alone loads without error.

Non-persisted runtime fields the reader synthesises: `sshRemoteProjectDir`, `query:null`,
`inputStream:null`, `isRunning:false`, `isFirstTurn`, `messageBuffer:[]`, `backend`.

### 3.3 The load gates, in order `[C]`

| Gate | Effect on failure |
|---|---|
| account/org unresolved (`getStorageDir()` → null) | **entire load skipped**, logs `Skipping session load: storage directory path unavailable` |
| filename `startsWith("local_") && endsWith(".json")` | file ignored entirely |
| **size > 10 MiB** | skipped + Sentry warning |
| empty (`!content.trim()`) | skipped |
| JSON parse error | that file skipped, load continues |
| duplicate `sessionId` already in map | later file silently dropped |
| mid-delete | dropped |

`isArchived` does **not** block loading. A **missing transcript** does not block loading either —
it is discovered lazily at warm/resume, the session stays listed with `transcriptUnavailable:true`,
and the stale `cliSessionId` is cleared.

Additional gates on *starting* (not loading): workspace trust
(`~/.claude.json` → `projects[<path>].hasTrustDialogAccepted`, checked up the ancestor chain),
`assertWorkingDirAllowed`, token cap, UNC/symlink-hop rejection for remote cwds,
`sessionId` must match `/^[a-zA-Z0-9_-]+$/`.

### 3.4 THE WORKING TEMPLATE — 18 keys written, 19 after the app touched it `[LIVE]`

What `transplant.py` wrote (18 keys):

```json
{"sessionId":"local_<uuid4>",
 "cliSessionId":"5e55105e-0000-4000-8000-000000000001",
 "cwd":"/home/dana/Projects/transporter",
 "originCwd":"/home/dana/Projects/transporter",
 "lastFocusedAt":<epoch_ms>, "createdAt":<epoch_ms>, "lastActivityAt":<epoch_ms>,
 "model":"claude-opus-4-8", "effort":"high",
 "isArchived":false,
 "title":"Transporter / SimLab (migrated from mac1)", "titleSource":"custom",
 "permissionMode":"acceptEdits",
 "remoteMcpServersConfig":[], "alwaysAllowedReasons":[],
 "sessionPermissionUpdates":[], "classifierSummaryEnabled":true, "spawnSeed":{}}
```

What is on disk now, after the Desktop opened and ran it (19 keys) `[LIVE]`:
same set, **plus `completedTurns: 1`**, with `model` rewritten by the app to **`claude-opus-5`**
and `sessionPermissionUpdates` populated with three session-scoped `addRules` allow entries
(`Read //usr/lib/**`, `Read //proc/**`, `Read //tmp/**`).

⇒ **`model` in the template is advisory.** Write the destination's own model
(`claude-opus-5`), not the origin's historical `claude-opus-4-8`; the app corrects it anyway.

Reference key set of a *native* Desktop session (20 keys, 7,544 B) for comparison:
`alwaysAllowedReasons, classifierSummaryEnabled, cliSessionId, completedTurns, createdAt, cwd,
effort, isArchived, lastActivityAt, lastFocusedAt, model, originCwd, permissionMode,
remoteMcpServersConfig, sessionId, sessionPermissionUpdates, sessionSettings, spawnSeed, title,
titleSource`.

### 3.5 Visibility rules — how a drop-in becomes visible

**There is no watcher.** `chokidar` appears **0 times** in the bundle; `.watch(` has exactly 6 call
sites, all unrelated. `loadSessions()` is reached only via `SessionAccountManager.doInitialize()`,
whose triggers are: app startup / first account resolution; the `lastActiveOrg` cookie changing;
account UUID change or logout→login; and lazily from `startSession`/`importCliSession`/
`scanRecoverableCliSessions` **only when account or org is null** `[C]`.

⇒ **A session JSON dropped in while the app is running will NOT appear — and can be destroyed**
(any `saveSession` of a same-named in-memory session overwrites it; `deleteSession` `rm -f`s both
`<file>` and `<file>.tmp`).

Ranked ways to make a drop-in appear:
1. **Stop that one instance, drop the file, start it.** Instances are keyed by `--user-data-dir`
   (`requestSingleInstanceLock` is per-user-data-dir), so this touches only the target instance.
   **This is the only path that is safe against the debounced writer. Use it.**
2. `claude://resume?session=<cliSessionId>` deep link — **PROHIBITED** here: it calls
   `importCliSession`, which writes `~/.claude.json` trust AND runs
   `stripThinkingBlocksFromFile` **in place** on the live transcript (§7 T1).
3. Toggling the org in the UI — works, but tears down every running session with `"account_switch"`.

**Wrong-account/org placement is not a soft failure.** Sessions under a non-matching
`<accountUuid>/<orgUuid>` are **never read** — not hidden-by-flag, not migrated, not deleted, just
invisible. Worse: `addOnDiskCliSessionIdsFromAllOrgs()` walks *every* account/org dir and feeds the
result to `scanRecoverableCliTranscripts` as an **exclusion** set, so a session file under the wrong
UUID pair **additionally suppresses its transcript from the current account's recovery UI** `[C]`.

Sibling layouts under the same user-data dir: `local-agent-mode-sessions/<account>/<org>/` (Cowork)
and `local-agent-mode-sessions/skills-plugin/<org>/<account>/` — **note the reversed order** (org
first); that is the dir passed to the CLI as `--plugin-dir`.

### 3.6 How the Desktop spawns and resumes the CLI

Exact resume flag: **`--resume=<cliSessionId>`** (single token, `=`-joined). Rewind adds
`--fork-session --resume-session-at=<messageUuid>`. `cliSessionId` is **not** derived from
`sessionId` — it is learned from the CLI's `system/init` message and saved.

Base SDK options: `settingSources:["user","project","local"]`, `includePartialMessages:true`,
`extraArgs {"thinking-display":"summarized", "replay-user-messages":null}`,
`systemPrompt:{type:"preset",preset:"claude_code",append:…}`.

Observed live argv of a Desktop-spawned CLI `[M]`:
```
…/claude-code/2.1.215/claude --output-format stream-json --verbose --input-format stream-json \
  --effort xhigh --model claude-opus-5 --permission-prompt-tool stdio --allowedTools … \
  --setting-sources=user,project,local --permission-mode acceptEdits --include-partial-messages \
  --plugin-dir <userData>/local-agent-mode-sessions/skills-plugin/<org>/<account> \
  --thinking-display summarized --replay-user-messages --settings {"fastMode":false}
```

Transcript reads are **tail-windowed at 50 MiB** with
`[CCD] Session <id> transcript is <size> bytes; loading chain entries from offset <a>` and
`transcriptTruncated` set. IPC channels are origin-gated and reachable only from the app's own
renderer — **there is no local HTTP/RPC entry point for sessions**; the deep link is the only
non-GUI one.

**Electron state stores hold nothing load-bearing.** `Local Storage/leveldb` has 7 keys
(`ccd-session-store` = UI selection only; `epitaxy-session-result:<sid>` = a cost cache;
composer drafts; pane layout). IndexedDB holds the *cloud* chat cache and device attestation. No
local/CCD session records anywhere. Worst case after a drop-in: missing cost badge, empty draft.
**Touching either store would corrupt the running Chromium leveldb.**

---

## 4. THE PROCEDURE THAT WORKED — numbered, with commands

Derived from `scripts/pull-checkpoint.sh` and `scripts/transplant.py` **as they now stand** (both
post-adversarial-review v2). Phases: **PULL → VERIFY → SEAL/PUBLISH → PREFLIGHT → TRANSPLANT →
ACTIVATE → CONFIRM**.

### Phase A — PULL a verified checkpoint (`pull-checkpoint.sh`)

Shell prelude — note `set -uo pipefail` **without `-e`**, plus an explicit `FAIL` accumulator, so a
partial failure is recorded rather than aborting mid-tree:

```bash
set -uo pipefail
REMOTE=mac1; RT=<origin project root>; RC=<origin ~/.claude>
SESSION=<SID>; PROJKEY=<ORIGIN_KEY>
ROOT=<backups root>; TS=$(date -u +%Y%m%dT%H%M%SZ); DEST="$ROOT/$TS"
PREV=$(readlink -f "$ROOT/latest" 2>/dev/null || true)
mkdir -p "$DEST"/{project,claude,manifest,logs}
LD=(); [ -n "$PREV" ] && [ -d "$PREV" ] && LD=(--link-dest="$PREV")
FAIL=0; die(){ log "FATAL: $*"; FAIL=1; }
```

**A1 — Excludes must be ANCHORED (leading `/`) and each justified against a listing.** This is the
M1 guard:

```bash
EXCL=(
  --exclude='/SimLab/acmeorg_simlab/rust/target/'   # cargo output
  --exclude='/_research/re/rust/target/'            # cargo output — NOT /_research/re/rust/
  --exclude='/_research/re/.rust-env/'              # vendored toolchain, 2.8 GB
  --exclude='node_modules/' --exclude='__pycache__/' --exclude='*.pyc'
  --exclude='.pytest_cache/' --exclude='.DS_Store'
)
# _research/re/target/ is NOT cargo output — it is the ground-truth ORACLE drop dir. It STAYS.
```

**A2 — Build the REMOTE manifest FIRST.** It is the source of truth you verify against (M2 guard).

```bash
ssh "$REMOTE" "cd '$RT' && find . -type f \
   -not -path './SimLab/acmeorg_simlab/rust/target/*' \
   -not -path './_research/re/rust/target/*' -not -path './_research/re/.rust-env/*' \
   -not -path '*/node_modules/*' -not -path '*/__pycache__/*' -not -path '*/.pytest_cache/*' \
   -not -name '*.pyc' -not -name '.DS_Store' -print0 \
   | xargs -0 -P 8 shasum -a 256" 2>/dev/null \
  | sed 's|  \./|  |' | sort -k2 > "$DEST/manifest/remote-project.sha256"
RN=$(wc -l < "$DEST/manifest/remote-project.sha256")
[ "$RN" -lt 24000 ] && die "remote project manifest suspiciously small ($RN)"
```

The `-lt 24000` sanity floor is the second half of the M1/M2 guard: an over-broad exclude shows up
as a **number**, not as silence.

**A3 — `~/.claude` artifacts by STRICT WHITELIST** (the M3 guard). The literal array used:

```bash
CLAUDE_PATHS=(
  "projects/$PROJKEY"
  "projects/${PROJKEY}--research-re"
  "projects/${PROJKEY}--research-re-rust"
  "projects/${PROJKEY}--research-re-tools-devio-fasp-diag"
  "projects/${PROJKEY}-DevIO-acmeorg-devio"
  "projects/${PROJKEY}-SimLab-acmeorg-simlab"
  "projects/${PROJKEY}-SimLab-acmeorg-simlab-rust"
  "tasks/$SESSION"
  "skills"
  "plugins"
  "settings.json"
)
# Deliberately NOT taken: .credentials.json, .claude.json*, backups/, history.jsonl,
# telemetry/, sessions/, shell-snapshots/, session-env/, cache/, stats-cache.json,
# policy-limits.json, and any tasks/ store not belonging to $SESSION.
RSPEC=$(printf "'%s' " "${CLAUDE_PATHS[@]}")
ssh "$REMOTE" "cd '$RC' && find $RSPEC -type f -not -name '.DS_Store' -print0 2>/dev/null \
   | xargs -0 -P 8 shasum -a 256" 2>/dev/null | sort -k2 > "$DEST/manifest/remote-claude.sha256"
CN=$(wc -l < "$DEST/manifest/remote-claude.sha256"); [ "$CN" -lt 100 ] && die "…too small ($CN)"
```

**A4 — Transfer (pull direction only).**

```bash
rsync -a --stats --no-perms --no-owner --no-group "${LD[@]}" "${EXCL[@]}" \
  "$REMOTE:$RT/" "$DEST/project/" >> "$DEST/logs/rsync-project.log" 2>&1
rc=$?; [ $rc -ne 0 ] && die "rsync project rc=$rc"

for p in "${CLAUDE_PATHS[@]}"; do
  mkdir -p "$DEST/claude/$(dirname "$p")"
  rsync -a --no-perms --no-owner --no-group "${LD[@]}" --exclude='.DS_Store' \
    "$REMOTE:$RC/$p" "$DEST/claude/$(dirname "$p")/" >> "$DEST/logs/rsync-claude.log" 2>&1
  rc=$?; [ $rc -ne 0 ] && die "rsync claude '$p' rc=$rc"
done
```

### Phase B — VERIFY: remote manifest vs local manifest (the M2 guard)

```bash
( cd "$DEST/project" && find . -type f -print0 | xargs -0 -P 8 sha256sum ) 2>/dev/null \
  | sed 's|  \./|  |' | sort -k2 > "$DEST/manifest/local-project.sha256"
( cd "$DEST/claude"  && find . -type f -print0 | xargs -0 -P 8 sha256sum ) 2>/dev/null \
  | sed 's|  \./|  |' | sort -k2 > "$DEST/manifest/local-claude.sha256"

for side in project claude; do
  if diff <(sort "$DEST/manifest/remote-$side.sha256") \
          <(sort "$DEST/manifest/local-$side.sha256") > "$DEST/manifest/DIFF-$side.txt" 2>&1; then
    log "  $side: VERIFIED — every file byte-identical to $REMOTE"
  else
    MISS=$(grep -c '^<' "$DEST/manifest/DIFF-$side.txt" || echo 0)
    EXTRA=$(grep -c '^>' "$DEST/manifest/DIFF-$side.txt" || echo 0)
    die "$side: MISMATCH — $MISS missing/differing, $EXTRA unexpected"
  fi
done
```

**Coverage and fidelity are separate gates.** `diff` of the two manifests catches both because the
remote side is generated by an independent `find` — a `<` line is a coverage failure, a differing
hash on a shared path is a fidelity failure. Report them separately.

**Transcript-specific fidelity — the prefix invariant.** JSONL is append-only, so:
```
copy is valid  iff  sha256(remote_bytes[0:L]) == sha256(local_bytes[0:L])  and  L <= R
ssh mac1 "head -c $L '<transcript>' | /sbin/sha256sum"
```
This **tolerates concurrent appends**, makes extension cost only the delta, and *is* the test that
would falsify the append-only hypothesis. Record-boundary invariants: last byte `0x0A`, last line
`json.loads`-able, `wc -l` monotone. On a tear, truncate back to the last `\n`, record
`discarded_bytes`, re-fetch the tail.

### Phase C — HAZARD SCAN + SECRETS INVENTORY (no reads of secret contents)

```bash
python3 - "$DEST" > "$DEST/manifest/filename-hazards.txt" 2>&1 <<'PY'
import os, sys, unicodedata, collections
root = sys.argv[1]; nfd, case = [], collections.defaultdict(list)
for base, dirs, files in os.walk(root):
    for n in dirs + files:
        if unicodedata.normalize('NFC', n) != n: nfd.append(os.path.join(base, n))
        case[os.path.join(base, n.lower())].append(n)
coll = {k: v for k, v in case.items() if len(set(v)) > 1}
print(f"NFD-normalized (macOS-style) names: {len(nfd)}")
print(f"case-only collisions: {len(coll)}  (safe on ext4, FATAL if pushed back to APFS)")
PY

{ echo "# Sensitive paths present in this checkpoint — gitignore, never commit."
  find "$DEST/project" \( -path '*/server_keys/*' -o -path '*/captures/*' \
       -o -name '*.key' -o -name '*.pem' -o -name 'id_*' -o -name '*license*' \) \
       -type f 2>/dev/null | sed "s|$DEST/||" | head -500
} > "$DEST/manifest/SENSITIVE.txt"
```
Result on the real run `[LIVE]`: **0 NFD names, 0 case collisions, 500 sensitive paths flagged.**
Both DIFF files are **0 bytes**.

### Phase D — SEAL, then PUBLISH (the M5 guard)

```bash
if [ "$FAIL" -ne 0 ]; then
  log "INCOMPLETE — 'latest' NOT advanced. Inspect $DEST then re-run."
  touch "$DEST/INCOMPLETE"; exit 1
fi
chmod -R a-w "$DEST/project" "$DEST/claude" 2>/dev/null   # protects hardlinked inodes (V05)
touch "$DEST/SEALED"
ln -sfn "$DEST" "$ROOT/latest"                            # ONLY after verification passed
```
Sealing is not cosmetic: with `--link-dest` hardlink chains, writing through an inode in the newest
generation silently **rewrites every prior generation**.

### Phase E — PREFLIGHT the placement

```python
C_phys = os.path.realpath(C)            # never $PWD, never `pwd -L`, never a raw user string
if C_phys != C: WARN loudly             # do not absorb the difference silently
D    = mangle(C_phys)                   # §5.2
dest = f"{CLAUDE_CONFIG_DIR}/projects/{D}/{SID}.jsonl"
assert len(sanitize(C_phys)) <= 200     # WARNING level only — see §6 F7
```
Blocking gate after placement: `test -s "$CLAUDE_CONFIG_DIR/projects/$D/$SID.jsonl"` — **the
resolver skips zero-byte candidates**, so an empty or partially-copied file fails *identically* to a
missing one.

### Phase F — TRANSPLANT (`transplant.py --plan` then `--apply`)

Six steps, each idempotent and re-runnable (the M6 guard).

**F1 — materialize the project tree.**
```python
os.makedirs(DEST_ROOT, exist_ok=True)
subprocess.run(["rsync","-a","--no-perms","--chmod=u+rwX,go-w",
                f"{CKPT}/project/", f"{DEST_ROOT}/"], check=True)
```
`--no-perms --chmod=u+rwX,go-w` is mandatory: the checkpoint is sealed `a-w` and plain `-a` would
propagate read-only into the working tree.

**F2 — place the transcript, byte-for-byte.**
```python
os.makedirs(dest_dir, exist_ok=True)
if os.path.exists(dest_tx):            # a previous partial run may have left a read-only copy
    os.chmod(dest_tx, 0o600); os.unlink(dest_tx)
shutil.copy2(src_tx, dest_tx)
os.chmod(dest_tx, 0o600)               # copy2 carries the sealed a-w mode over — M6
prefix_len = os.path.getsize(src_tx)
assert sha256(dest_tx) == sha256(src_tx), "copy is not byte-identical"
```
**The filename stem MUST remain the origin `<SID>`** — sidecars resolve as
`<transcript path minus .jsonl>/{subagents,tool-results,workflows}` (`WUd`). Renaming orphans
170 MB / 1,991 files **silently**.

**F3 — APPEND the relocation notice. Never rewrite.**
```python
rec = {"parentUuid": last_uuid(dest_tx), "isSidechain": False, "type": "user",
       "message": {"role":"user","content":[{"type":"text","text": NOTICE}]},
       "uuid": str(uuid.uuid4()),
       "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
       "origin": {"kind":"system"}, "userType":"external", "cwd": DEST_ROOT,
       "sessionId": SID, "version": "2.1.215", "gitBranch": ""}
with open(dest_tx, "a") as f: f.write(json.dumps(rec) + "\n")
assert sha256(dest_tx, limit=prefix_len) == sha256(src_tx), "prefix changed — ABORT"
```
`last_uuid()` must **tail-scan and take the last record that HAS a uuid** — the file ends with
`mode`/`ai-title`/`custom-title` records that have none:
```python
tail = subprocess.run(["tail","-n","400",path], capture_output=True, text=True).stdout
u = None
for line in tail.splitlines():
    try: d = json.loads(line)
    except Exception: continue
    if d.get("uuid"): u = d["uuid"]
```
The notice content (what actually shipped) states: origin host/user/account, current
host/user/account, an explicit **old→new path mapping table**, and four consequences — that ~33,959
lines of history reference the origin paths and are *historical record, not live locations*; that
old scripts hold hardcoded origin paths and a path failure is *expected, not surprising*; where the
toolchain now lives and that nothing may be installed into the host system; and that the origin is
reachable **read-only**.

**F4 — sidecars, memory, tasks.**
```python
subprocess.run(["rsync","-a","--no-perms","--chmod=u+rwX",
                f"{src_side}/", f"{dest_dir}/{SID}/"], check=True)      # subagents/tool-results/workflows
subprocess.run(["rsync","-a","--no-perms","--chmod=u+rwX",
                f"{src_mem}/",  f"{dest_dir}/memory/"], check=True)     # project-scoped
subprocess.run(["rsync","-a","--no-perms","--chmod=u+rwX",
                f"{src_tasks}/", f"{CLAUDE_HOME}/tasks/{SID}/"], check=True)
```
Then **assert file counts and bytes against the origin inventory** — this is the A6/M4 gate.
Achieved `[LIVE]`: `subagents 1867 · tool-results 11→10 · workflows 113 · tasks 152 · memory 24`.
See §8 for the two counts that did **not** match.

**F5 — durable `CLAUDE.md` in the destination project root.** This is the half of the relocation
message that **survives compaction** — the appended notice falls out of context, `CLAUDE.md` is
re-read every session. Contents that shipped: the old→new path table; "toolchain is workspace-local,
do not `apt install`, do not install into `~/.cargo`/`~/.local`"; "the arm64 oracle cannot run here";
"origin is read-only, `ssh mac1` works"; "old scripts may hold hardcoded origin paths"; and a
**Provenance** paragraph naming the verified checkpoint and its file counts.

**F6 — mint the Desktop session JSON** (§3.4), into
`<user-data-dir>/claude-code-sessions/<accountUuid>/<orgUuid>/local_<uuid4>.json`,
filename **exactly** `${sessionId}.json`, mode 0600, dir 0700, size < 10 MiB.

### Phase G — ACTIVATE

1. Assert the target Desktop instance is **not running**:
   `ps -eo pid,comm,args --no-headers | awk '$2 ~ /claude/ && /acct-b/'` → empty.
   **Never `pgrep -af '…acct-b'`** — it self-matches the checking shell (2 false positives measured).
   **Never `pkill -f <pattern>`** — it self-matched and killed a run mid-experiment (exit 144).
2. Install shared assets (skills, plugins) **before** launch — §5 K8.
3. Add the one trust entry to the local `~/.claude.json`:
   `projects["<dest root>"].hasTrustDialogAccepted = true`.
4. Launch: `claude-desktop --user-data-dir="$HOME/.claude-instances/acct-b"`.
   CLI-direct equivalent (a complete path on its own): `cd <dest root> && claude --resume=<SID>`.

### Phase H — CONFIRM

| Check | Expected |
|---|---|
| Transcript prefix still origin-identical | `head -c 216236906 <live> \| sha256sum` == `074487a7bd31324ece84462f5ff46a07703feeab94941e62f5b76d9af6d2a32a` `[LIVE]` |
| Line count | monotone increasing, never decreasing |
| Structural invariants re-asserted | §2.7 set, ± declared appends |
| Origin unchanged | sealed checkpoint hash + origin fingerprint |
| Semantic fidelity | ask the resumed session what it was last working on; expected answer **"CAP-TLV keystone, tracker #148"** |

**A byte-count *decrease* or a hash change on the prefix means a stripping import path ran.
Halt and restore from quarantine.**

---

## 5. EVERY MEASURED CONSTANT — the baseline for a future run

### 5.1 Sizes, counts, hashes

| Quantity | Value | Source |
|---|---|---|
| **Transcript size** | **216,236,906 B** (206 MiB) | `[M]` |
| **Transcript sha256** | **`074487a7bd31324ece84462f5ff46a07703feeab94941e62f5b76d9af6d2a32a`** | `[M]`, re-verified 5× incl. `[LIVE]` |
| Transcript lines | 47,088 | `[M]` |
| Max line length | 128,423 B | `[M]` |
| Complete session footprint | **387,805,915 B / 2,157 files** across 8 dirs | `[M]` |
| Transcript share of that | **55.8 %** — a `.jsonl`-only copy loses **44 % of bytes, 100 % of subagent content** | `[M]` |
| `subagents/` | 157 MB, 1,867 files (51 agents + 1,765 workflow-agent files + junk) | `[M]` |
| `subagents/workflows/` alone | **148,506,101 B = 38 % of the whole session** — missed by any `-maxdepth 1` sweep | `[M]` |
| `workflows/` | 7.0 MB, 113 files (85 `wf_*.json` + 28 scripts) | `[M]` |
| `tool-results/` | 5,911,806 B, 11 files (33,674 B – 4,922,995 B) | `[M]` |
| `tasks/<SID>/` | 122,592 B, 154 entries (152 tasks + `.highwatermark` + `.lock`) | `[M]` |
| Task status histogram | **completed 141 / pending 8 / in_progress 3** — the 11 open ones are live agenda | `[M]` |
| `memory/` | 24–25 `.md`, 399,050 B (862 KB incl. front-matter) | `[M]` |
| Largest memory files | `simlab-roadmap.md` 144,716 · `simlab-project.md` 57,797 · `phase2-progress.md` 25,784 · `validation-discipline.md` 25,849 · `MEMORY.md` 7,834 | `[M]` |
| Origin `~/.claude` total | 5.5 GB, 48 project dirs (not 51 — `ls -a1` counted `.`/`..`/`.DS_Store`) | `[M]` |
| Origin `projects/` | 5.1 GB = 93 % of the tree | `[M]` |
| Origin project tree | **9.4 GB**, 106,204 files / 8,734 dirs / 1,151 symlinks | `[M]` |
| Hardlinked files in project tree | 62,273 files → 20,819 inodes; **62,267 of them live under excluded dirs**, only **6** survive | `[M]` |
| Checkpoint actually taken | **24,538 project files + 6,245 claude files**, all sha256-matched, 0-byte DIFF files | `[LIVE]` |
| Checkpoint on disk | `project/` 1.1 GB, `claude/` 729 MB | `[LIVE]` |
| Sensitive paths flagged | 500 | `[LIVE]` |
| Filename hazards | **0 NFD names, 0 case collisions, 0 non-ASCII filenames, 0 AppleDouble, 0 sparse, 0 files >4 GB, 0 devices/FIFOs, 0 absolute symlinks, 0 broken symlinks, 0 ACLs, 0 BSD flags** | `[M]` |
| `.DS_Store` in project tree | 39 | `[M]` |
| Nested git repos in project tree | 19 (18 vendored clones + `acmeorg_simlab`) | `[M]` |
| Skills corpus | 341 MB across 12 skills, of which `scholarly-pdf-acquisition` is **338 MB (321 MB installed)** and ~331 MB of that is a `.venv` bundling two ~114 MB Node runtimes; **authored content across all 12 ≈ 2.5–2.9 MB** | `[M]` |

### 5.2 The manglers — two of them, and they differ

**CLI `Pw` (authoritative for transcript placement)** `[C]` from the ELF at offset 239728033:
```js
Jvt = 200
function nQe(e){let t=0;for(let r=0;r<e.length;r++)t=(t<<5)-t+e.charCodeAt(r)|0;return t}
function bzm(e){return Math.abs(nQe(e)).toString(36)}
function Pw(e){let t=e.replace(/[^a-zA-Z0-9]/g,"-");
               if(t.length<=Jvt)return t; return `${t.slice(0,Jvt)}-${bzm(e)}`}
function h4(){return join(CLAUDE_CONFIG_DIR,"projects")}
function a9(e){return join(h4(),Pw(e))}
async function j0(e){try{return await realpath(e)}catch{return e}}
```
Stated precisely — **do not "improve" any of these properties, each is measured**:
```
mangle(p):                       # p MUST already be realpath()'d
  t = every UTF-16 CODE UNIT of p not in [A-Za-z0-9] -> exactly one '-'
  if len(t) <= 200: return t     # <=200 KEEPS. 201 hashes. Boundary measured at 199/200/201/260.
  h = fold over UTF-16 code units of p (the ORIGINAL, not t): h = (h*31 + u) as signed int32
  return t[0:200] + '-' + base36(abs(h))     # result is 202..207 chars, NEVER a fixed length
```
| Property | Behaviour | Confirmed by |
|---|---|---|
| leading `/` | → leading `-` | all 11 probes |
| `_`, `.`, space, `-` | all → `-`, indistinguishable | `under_score_dir`, `dot.ted.dir`, `with space dir` |
| case | **preserved, no folding** | `MiXeDCase` → `MiXeDCase` |
| repeated separators | **NOT collapsed**, n separators → n dashes | 19 punctuation chars → 19 dashes; `a_-_b..c` → `a---b--c` |
| trailing separator | preserved as trailing `-` | `trail_` → `…-trail-` |
| non-ASCII BMP | one `-` per code unit | `uni_café_日本` → `uni-caf----` |
| astral (emoji) | **two** dashes (surrogate pair) | `[D]`, not exercised |
| >200 | truncate-200 + `-` + 1–6 base36 chars | 201→206, 260→207 |
| hash input | the **original** path, so two paths that sanitize identically get different hashes | measured: `5lftp7` vs `qa4tka` on two 210-char paths differing only `_` vs `.` |
| input | **realpath**, symlinks resolved | E4 C1/C2 with both dirs present simultaneously |

**Score: `mangle.py` is 22/22** — 11 CLI probe dirs + 7 real origin dirs + 4 boundary cases.
Canonical implementation lives at `scripts/measurement/anchor-rig/mangle.py`. **Lift it verbatim.**

**Desktop has THREE manglers in one bundle** `[C]`:

| chunk | owner | behaviour >200 |
|---|---|---|
| `index.chunk-BnvC1Fh-.js` `cliSanitizeCwdSimple` | `ClaudeCodeConfig` / trust helpers, consumed by `LocalSessionManager` | **returns `undefined`, no hash** |
| `index.chunk-CgLXpPH8.js` `zo` | vendored agent SDK | identical to the CLI's `Pw` |
| `index.chunk-DfuT5fCe.js` `zo` (inlined) | `LocalAgentModeSessionManager` | identical to the CLI's `Pw` |

Worked keys:
```
/Users/jamiedoe/Projects/CLAUDE/transporter                     -> -Users-jamiedoe-Projects-CLAUDE-transporter          (43)
…/transporter/_research/re/tools/devio_fasp/diag                -> …--research-re-tools-devio-fasp-diag                 (78)  <- deepest real key
/home/dana/Projects/transporter                                 -> -home-dana-Projects-transporter                      (31)  <- the one used
/home/dana/Projects/SimLab                                      -> -home-dana-Projects-SimLab                           (26)
/home/dana/Projects/SimLab/_transporter                         -> -home-dana-Projects-SimLab--transporter              (39)
```
**122 chars of headroom at the deepest real key** ⇒ the overflow regime is unreachable for this
migration. E5 is insurance.

### 5.3 Timings and resource use

| Measurement | Value |
|---|---|
| **E13 full-file load: peak RSS** | **1,044,296 KB = 1.02 GB** (with `NODE_OPTIONS=--max-old-space-size=8192`) |
| **E13 full-file load: wall clock** | **2 m 56.70 s** |
| E13 result | `session was located` · `no OOM` · `reached the network call` · file **UNCHANGED** afterward, hash identical · nothing else written |
| E13 wire body #1 | **2,191,582 B** (2.19 MB), **422 messages** (user 191 / assistant 190 / **system 41**) |
| E13 wire blocks | text 162 · **thinking 166, 166/166 signed** · tool_use 183 · tool_result 183 · bare-string 47 |
| E13 wire tools / model | 27 tools · `claude-opus-4-8` · `max_tokens 64000` |
| E13 `/Users/jamiedoe` on the wire | **349 occurrences from a resumed 216 MB file** |
| E13 replay start | at the **last compact boundary** — the compact-summary text is present in the body |
| E13 request header | `x-claude-code-session-id: 5e55105e-…` (the **filename** id) |
| Estimated context put on the wire | **~521k tokens** |
| sha256 throughput, mac1 | `/sbin/sha256sum` **0.11 s** for 216 MB · `openssl dgst` 0.11 s · `shasum -a 256` **0.54 s** (5× slower) — all three digests identical |
| sha256 throughput, local | ~1.8 GB/s (SHA-NI) |
| zstd on transcript | zstd-3 **3.73×**, zstd-19 4.08× → ~55 MiB / ~50 MiB. **16× CPU for 9 % — use zstd-3.** `zstd` is NOT on mac1. |
| ssh mac1 round trip | cold 0.696 s; **warm 20–120 ms** with `ControlPersist 30m` |
| oracle-run.sh round trip | **~0.2 s** per invocation (4 ssh round trips on the persistent socket) |
| Transfer throughput mac1→local | `ssh cat`/`dd` multiplexed **22–86 MB/s** · `rsync` 39 · `rclone mount` warm 80 / cold 16 · **`rclone cat` per-call 6.4 — avoid** (fresh SSH handshake per call) |
| Free space | LOCAL 1.8 TiB free of 7.3 T (74 % used) · **REMOTE 38.3 GiB free of 3.6 TiB (99 % used) — hard design constraint** |
| Marginal checkpoint generation | ~250–450 MiB ⇒ ≈4,000–7,000 generations against 1.8 TiB |

### 5.4 Cost of the prohibited operations

| Operation | Measured cost |
|---|---|
| `stripThinkingBlocksFromFile` (import / `claude://resume` / recovery UI) | **6,331 of 21,859 assistant records deleted outright**, **~6,332 severed `parentUuid` links**, walk-back depth collapses to **1**. Reads the whole file into one JS string (~2 GB peak, near Node's ~512 M-char cap) and rewrites **in place** via `.tmp`+rename. |
| `--resume <abs>.jsonl` | Loads from anywhere, **but** duplicates the file (naming the copy after the **in-record** sessionId — the opposite convention) and **rewrites `cwd` on every replayed record**. Field-level diff: `fields differing: ['cwd']`. Record order also normalised. |
| Blanket `sed` on `/Users/jamiedoe` | 54,157 occurrences: ~33,957 lines project paths, **~5,705 occurrences are NOT paths** (`ls -l` owner columns, `jamiedoe@host`, git author strings), **~745 macOS toolchain paths with no Linux equivalent**. |
| Wrong project dir | `exit 1`, `No conversation found with session ID: <uuid>`. Measured **three independent times**, including when the target was the **only** `.jsonl` under `projects/`. |
| Cross-account `thinking.signature` rejection (if it happens) | **One request. No retry. No fallback. exit 1.** `API Error: 400 messages.N.content.M.thinking.signature: The signature provided is not valid for this content.` `keep:"all"` is hardcoded in `Fsd` with no flag/env knob. |

### 5.5 The E7 / E-RIG invariant baselines (assert these post-transplant)

```
lines 47,088 in -> 47,088 out (± declared appends)   every line json.loads
type multiset unchanged                              100 duplicate uuids still contiguous at 1784-1883
28 roots                                             0 dangling parentUuid
3,436 leafUuids, 0 orphans, the LAST leafUuid resolves
21,859 assistant records, 6,344 with thinking
first compact_boundary at line 1884 (of 27 total)
head -n 200 slice: 200 lines / 717,661 B, 164 uuids, 0 orphan parents, 1 root at line 3,
                   28 thinking blocks 28/28 signed, chain depth 154 to root
sed -n '1884,2083p' slice: 200 lines / 776,210 B, 34 thinking blocks, 1 compact_boundary,
                   16 `mode` records, self-rooted (boundaries have parentUuid:null)
```

### 5.6 Confirmed-KNOWN facts (LADDER K1–K22), condensed

| # | Fact |
|---|---|
| K1 | Resume keys off the **filename**, not in-record `sessionId`; `metadata.session_id` is stamped from it. Origin-sessionId and rewritten-sessionId variants gave **byte-identical 429,452 B** requests. |
| K2 | Resume is a **pure append**; first 200 lines byte-identical (`sha256 f9a2ceb1…`) after **3** resumes; new turns thread onto the origin DAG via `parentUuid`. |
| K3 | Envelope fields (`slug`,`mode`,`uuid`,`parentUuid`,`cwd`,`version`,`leafUuid`,`isSidechain`,`userType`) reach the API **0 times**. Only `effort` appears — emitted by 2.1.215 itself as `output_config`. |
| K4 | 2.1.215 loads 2.1.170 records including `compact_boundary` and `mode`. |
| K5 | Thinking blocks **are** transmitted with signatures (28/28, 34/34, 166/166). |
| K6 | A signature rejection is fatal, single-shot, greppable. |
| K7 | `relocated` is **not** honored on `--resume=<id>`, `--continue`, or the startup picker; **is** honored on in-REPL `/resume`. |
| K8 | Effective cwd comes from the **launch directory**. |
| K9 | Historical per-record `$.cwd` is **completely inert** (control: every record's cwd set to `cwdB`, session still ran from `cwdD`). |
| K10 | **No global fallback** on `--resume=<id>`; wrong project dir → exit 1. |
| K11 | The mangle input is the **realpath**; the alias path is never consulted even when its dir exists. |
| K12 | Mangler rule exact incl. the `<=200` boundary and hash-over-original; `mangle.py` 22/22. |
| K13 | git-worktree siblings widen the resume search (can only widen, never narrow). |
| K14 | `--resume <abs>.jsonl` duplicates + rewrites `cwd`. |
| K15 | Desktop **discovery** is directory-name-agnostic → no "CLI-resumable but Desktop-invisible" regime. |
| K16–K18 | Oracle realm 100 % local (7/7 sha256-identical); mac1 executes arm64 on demand ~0.2 s; the byte-exactness gate is frozen-corpus and architecture-independent — only 23 interop files need mac1. |
| K19–K21 | Destination toolchain green: Python **661 passed / 0 failed / 0 skipped**; Rust 7 crates / 0 warnings / **141/141** tests / working abi3 wheel; 4 undeclared host deps, all sudo-free; `rust/crates/control` is a required workspace member. |
| K22 | The origin transcript contains **0** pre-existing `relocated` records. |

### 5.7 The resume resolver, exactly `[C]`

`--resume=<id>` goes `R$e` → `wVe(e)` → `VOd(e, undefined)` → **`$8y(e)`**:
```js
async function $8y(e){ let t=zW(), r=ln(), n=`${e}.jsonl`, o=join(t??bb(r),n);
  if(t!==null) return o;                                    // sessionProjectDir override
  for(let i of await cM(r)){ let s=join(i,n); try{ await stat(s); return s }catch{} }
  return o }                                                 // -> stat fails -> "No conversation found"
async function cM(e){ let t=a9(e), r=[]; try{ await readdir(t); r.push(t) }catch{}
  let n=Pw(e); if(n.length<=200) return r;                   // >200: also accept siblings sharing
  let o=n.slice(0,200)+"-";                                  //  the 200-char prefix (hash tolerance)
  for(let s of await readdir(h4(),{withFileTypes:true}))
    if(s.isDirectory()&&s.name.startsWith(o)&&join(h4(),s.name)!==t) r.push(join(h4(),s.name));
  return r }
// only other widener: SGg(e) retries across git worktrees of ln()  (Mwe = `git worktree list`)
```
`nGe(sessionId, cwdHint)` **does** have a global `readdir` branch — but **only when the hint is
absent**, and `$8y` never calls it. Sidecar helpers:
```js
function Et(){ return qL()?.sessionId ?? kt.sessionId }                 // == the FILENAME uuid on resume
function bx(e){ …join(projectDir, Et(), "subagents", `agent-${e}.jsonl`) }
function YUu(){ …join(projectDir, Et(), "workflows") }
function N8n(){ …join(a9(At()), Et(), "workflows","scripts") + sep }    // per-CURRENT-cwd project dir
async function WUd(e,t){ let r=await nGe(e,t); if(!r) return null;
  return join(r.filePath.replace(/\.jsonl$/,""), "subagents") }         // <- the transcript path minus .jsonl
```
The `relocated` consumers, and how strict each is:

| # | Consumer | `sessionId` must match? | Scope |
|---|---|---|---|
| 1 | `D$e` streaming parser → `relocatedCwds` map | **yes** (keyed by the record's own sessionId, last wins) | full-file parse |
| 2 | `Qvt(buf,"relocated","relocatedCwd")` reverse line scan | **no** (sessionId ignored) | **last 65,536 bytes only** (`rR=65536`) |
| 3 | `FUd` reducer (fork/copy) | **yes** | full-file parse |

The chdir itself happens only in `ubt(worktreeSession, projectPath)` — and **only when the second
argument is passed**. Call sites: `--resume=<id> --print`, `--continue --print`, `--resume=<id>`
interactive, startup picker → **1 arg, no chdir**. In-REPL `/resume` → **2 args, chdir**.

If you append a `relocated` record anyway (recommended — one line, free, and the sole lever on the
in-REPL `/resume` path), three hard constraints:
1. `sessionId` **must be the in-record session id**, not the filename uuid (satisfies all three consumers);
2. `relocatedCwd` **must be an existing absolute path** — `process.chdir` is inside `try/catch`, so a wrong value **degrades silently to no-chdir**, it will not error;
3. it **must land within the last 64 KiB** of the file. Re-verify after any later append.

---

## 6. THINGS THAT LOOK TRUE BUT ARE FALSE

Each row: the wrong belief, what it would have cost, and **what disproved it**.

### F1 — "The mangler maps `/` and `_` to `-`."
**False.** Every character not in `[a-zA-Z0-9]` becomes `-`: dots, spaces, existing hyphens,
every punctuation mark, every non-ASCII code unit. The `[/_]` hypothesis was written into R01 and
survived into early planning.
**Disproved by:** `cliSanitizeCwdSimple = t.replace(/[^a-zA-Z0-9]/g,"-")` read out of the asar,
then confirmed empirically — `dot.ted.dir` → `dot-ted-dir`, `with space dir` → `with-space-dir`,
19 punctuation chars → 19 dashes.
**Cost avoided:** any key derived by editing another key would silently miss. Corollary rule:
**never derive a project-dir name by editing another one — always compute from `realpath`.**

### F2 — "There is a global fallback: the CLI scans every project dir for `<sid>.jsonl`."
**False on the `--resume=<id>` path.** R03 asserted it; an adversarial review disputed it; the
review was right *and* incomplete — `--resume=<id>` never reaches `nGe` at all, it calls `$8y`,
which has no global branch.
**Disproved by:** three independent measurements. E4 A1 placed the transcript in a decoy dir when
it was the **only** `.jsonl` anywhere under `projects/` → `exit 1 / No conversation found`. E3 §3.4
and E5 §5 reproduced it. Also A2 (different real cwd's dir) and A3 (**parent** of the launch cwd) →
both not found; there is no parent walk either.
**Cost avoided:** MASTER-PLAN's "if (a) unexpectedly succeeds → dirname correctness is a
convenience" branch **does not fire**. Dirname correctness is a **requirement**.

### F3 — "The `relocated` record is what makes Tier 0 work; if E3 fails, Tier 1 is required."
**Both halves false.** E3's literal result was a FAIL by the plan's own criterion, and the FAIL
branch still does not follow.
**Disproved by:** a 4-cell matrix over one fixture. `--resume=<id>`, `--continue` and the startup
picker all kept the effective cwd at the launch dir with the record present, correctly formed, and
demonstrably *consumed* (the CLI re-emitted it re-stamped with the new session id). `cwdB` appeared
**0 times** in the request body. Only in-REPL `/resume` honored it. Root cause: `ubt()` arity.
**What actually makes Tier 0 work:** the launch directory sets the effective cwd (K8), the
transcript is adopted **in place** and resume is a pure append (K2), and historical `$.cwd` is inert
(K9). **Do not re-derive Tier 1 from the plan text.**

### F4 — "`relocated` records are honored on `--resume`."
**False** — same measurement as F3, stated as its own trap because it is the tempting half of the
split result. They are honored **only** on the in-REPL `/resume` picker. Append one anyway (free,
and it fixes that one path), but **never rely on it** for the migration path.

### F5 — "Per-record `$.cwd` must be rewritten or the session will run in the wrong directory."
**False.** This was Tier 1's headline payload — 33,805 rewrites.
**Disproved by:** E3 body_030, a control with **every** message record's `cwd` set to `cwdB` and no
`relocated` record. The session stayed at `cwdD`. Nothing on the resume path chdirs to a historical
`cwd`.
**Consequence:** the origin's 47,088 records full of `/Users/jamiedoe/...` **cannot** cause a chdir
attempt. Relocating a session requires **no transcript rewriting at all**. This is the single most
important finding of the session.

### F6 — "acct-b is not signed in, so a human must sign in first."
**False.** All three candidate designs gated on this.
**Disproved by:** `<user-data-dir>/config.json` carries `oauth:tokenCache`, `oauth:tokenCacheV2`
and `lastKnownAccountUuid = bbbbbbbb-…`, with the org recoverable from `dxt:allowlist*:<org>` key
suffixes. **The absence of `claude-code-sessions/` means "no session yet", not "not signed in"** —
that directory is created lazily at first *session*, not at sign-in.
**Also false:** "acct-a vs acct-b is an account boundary." They are the **same account and org**;
it is process isolation. The only real cross-account boundary was mac1 vs local.
**Cost avoided:** a spurious human sign-in gate on the critical path.

### F7 — "A >200-char mangled key makes the session CLI-resumable but Desktop-invisible."
**False; that regime does not exist.**
**Disproved by:** reading all three Desktop code paths. `resolveProjectDirForSession` drops the
`undefined` fast-path candidate (`g && h.add(g)`) and **falls through to `readdir(projects)` +
parallel `access(<dir>/<sid>.jsonl)` across every project dir**. `scanRecoverableCliTranscripts`
enumerates all project dirs, filtering only on `startsWith("ssh-")`. Both find the hashed dir.
**What is actually true:** the divergence is **write/fork-side only** — `forkSession` /
`forkSessionSsh` land in the **parent's** project dir with a `logger.warn`;
`migrateTranscriptOnWorktreeFallback` hard-returns `false`; `scratchpadCandidateRoots` silently
yields **zero** candidates. So the >200 check belongs at **warning** level with those reasons, not
as a Desktop-visibility failure.

### F8 — "`target/` is a build-output directory, so exclude it."
**False, and it destroyed data.** `_research/re/target/` is the **ground-truth oracle drop dir**:
`ascp`, `ascp_lic`, `ascp_srv`, `ascp.i64` (134,176,621 B), `ascp_srv.i64` (51,186,707 B),
`aspera-license`, `aspera.conf`.
**Disproved by:** E11 — all 7 files sha256-identical between mac1 and the checkpoint, 7/7.
**Rule:** never pattern-match on a directory **name**. Anchor every exclude (`/_research/re/rust/target/`,
not `target/`) and justify each one against a listing.

### F9 — "`--exclude='_research/re/rust/'` skips a cargo target dir."
**False.** It dropped **26 files / 1.44 MB of irreplaceable FASP Rust source**, including
`fasp-core/src/cap.rs` — the CAP-TLV keystone, tracker #148. Only `re/rust/target/` is cargo output.
**Rule:** the anchored form is `--exclude='/_research/re/rust/target/'`.

### F10 — "Verification passed, so the transfer is intact."
**False if the verification hashed only the local copy.** v1 of `pull-checkpoint.sh` hashed the
local tree and compared it to itself; a truncated transfer would have "passed".
**Rule:** diff a **remote-side** manifest against a **local-side** manifest. And treat **coverage**
(are all files present?) as a **separate gate** from **fidelity** (do the bytes match?) — a corpus
can be 100 % faithful and 60 % complete.

### F11 — "A grep that finds no errors means the thing worked."
**False.** A signature-error grep "passed" because the run had died earlier at `Not logged in` and
never reached the API.
**Rule:** every check must first assert that the thing it is checking actually **executed**.
Absence of an error is not evidence of success. The E13 script encodes this correctly — its PASS
signal is the **presence** of `ECONNREFUSED|fetch failed|connect`, i.e. proof the loader got all
the way to the network layer.

### F12 — "`~/.claude/sessions/` is a session index / archive."
**False.** It is the **live-process registry**, keyed by **PID**:
`{pid, sessionId, cwd, startedAt, procStart, version, peerProtocol, kind, entrypoint, name,
nameSource}` — ~279 bytes, existing only while the CLI process is alive, used for cross-session peer
discovery. It is empty on mac1 because nothing is running there.
**Disproved by:** finding `~/.claude/sessions/440604.json` on the *local* host describing the
running session. **Never copy it** — a stale entry advertises a non-existent peer.

### F13 — "`~/.claude/history.jsonl` is this session's prompt log."
**False.** Last write **2026-04-27**, three months before the session ran; **0 records for `<SID>`**;
1,060 of its 1,068 lines belong to an unrelated project. It is the **interactive-TTY up-arrow recall
buffer**; Desktop-spawned sessions (`entrypoint:"claude-desktop"`) do not write to it.

### F14 — "`~/.claude/backups/` backs up the session."
**False.** It is a 5-deep ring of `~/.claude.json` **only**. **Nothing in `~/.claude` protects the
216 MB transcript or the 432 KB memory store.** Sweeping it (M3) collected another account's
`machineID`, `userID` and `oauthAccount` instead.

### F15 — "There is a `~/.claude/todos/` directory."
**False, it does not exist.** The todo store is `~/.claude/tasks/<sessionId>/<n>.json`, keyed by
**session id, not project** — therefore **not discoverable from the project path**.

### F16 — "`~/.claude/file-history/` holds the undo store we must migrate."
**Empty on both hosts** (only a 12,292 B `.DS_Store` on mac1, absent entirely on Linux). Its purpose
as an undo/`/rewind` snapshot store is `[I]`, never observed. Nothing to migrate; the accepted loss
is that `/rewind` on the transplanted session has no pre-edit snapshots.

### F17 — "The transcript is fragmented across the six project dirs the session touched."
**False for the transcript.** All 47,088 records are in **one** `.jsonl`, under the project dir of
the cwd the session was **created** in, despite 46 distinct `cwd` values. What *is* per-cwd is only
`workflows/scripts/*.js` — 9 files / 76,374 B across 5 sibling dirs.

### F18 — "The sub-agent set can be reconstructed from the main transcript."
**False.** Only **16 of 51** `toolUseId`s appear in the main transcript; the other **35** appear
inside *another sub-agent's* `.jsonl` (sub-agents spawning sub-agents, two levels deep). All 35 were
traced, 0 unaccounted. **Enumerate the directory.**

### F19 — "`content-replacement` records are a path-substitution facility."
**False.** Verified at three offsets: the `replacements` array is
`{kind:"tool-result", toolUseId, replacement}` — **oversized-tool-result content offloading keyed by
toolUseId**, gated behind feature flag `tengu_hawthorn_steeple`. It cannot rewrite a path anywhere.

### F20 — "A `sessionStore` in the Desktop would make a filesystem drop-in non-authoritative."
**False.** `sessionStore` is an optional SDK `Options` field — a **mirror adapter**. Two guard
clauses settle it: `sessionStore cannot be used with persistSession: false — the storage adapter
requires local writes to mirror from`, and `--session-mirror  Emit transcript_mirror frames on
stdout (SDK-internal; set by ProcessTransport when sessionStore is configured)`. The live argv
contains no `--session-mirror`. **Local files are the source of truth.**

### F21 — "`pgrep -af 'user-data-dir=.*acct-b'` tells you whether acct-b is running."
**False — it self-matches**, returning 2 false positives (the `bash -c` wrapper running the check
and its `eval` child, whose command lines contain the pattern string).
**Correct form:** `ps -eo pid,comm,args --no-headers | awk '$2 ~ /claude/ && /acct-b/'`.
Related: **never use `pkill -f <pattern>` in rig scripts** — it self-matched and killed a run
mid-experiment (exit 144).

### F22 — "Probing the CLI costs an API turn."
**False.** The CLI creates `$CLAUDE_CONFIG_DIR/projects/<mangled>/<sid>.jsonl` **during startup,
before the first API call**. Point `ANTHROPIC_BASE_URL` at a dead port under `timeout`:
```bash
timeout 25 env ANTHROPIC_BASE_URL=http://127.0.0.1:1 CLAUDE_CONFIG_DIR="$RIG/cfg" \
  ANTHROPIC_API_KEY=dummy "$CLI" --resume=<sid> --print 'reply with exactly: OK'
```
| exit | meaning |
|---|---|
| `1` + stderr `No conversation found with session ID: <uuid>` | the resolver did **not** find the file |
| `124` + stdout `Execution error` | the transcript **was** found, parsed and replayed, then hung on the dead port |

Corroborated independently of the exit code: **every LOADED run appended to its transcript**
(2,089 B → 13,388–13,398 B) while **every NOT-FOUND run left the file at exactly 2,089 B**.
**Every experiment in this session ran at zero API tokens on this trick.**

### F23 — "A missing `.jsonl` path reports the session id you asked for."
**False.** Passing `…/00000000-0000-4000-8000-000000000000.jsonl` printed
`No conversation found with session ID: f0f0f0f0-0000-4000-8000-000000000002` — a **freshly minted,
never-requested** id that appears nowhere in the config dir. **Never parse a uuid out of that
message.** (Mechanism `[I]`.)

### F24 — "The mangled key can be re-derived, so carrying the observed directory name is redundant."
**False — the mapping is not injective.** `/a/b`, `/a-b`, `/a_b`, `/a.b`, `/a b` all collapse to
`-a-b`. Paths **>200 chars are *less* collision-prone** than short ones, because the hash re-injects
the information the sanitizer destroyed. Carry the literal observed directory name; use
`cwd`/`originCwd` from the session metadata as the authoritative inverse mapping.


---

## 7. GUARDS — the mistakes made, as executable checks

### 7.1 The eight mistakes (M1–M8) and the check that would have caught each

| # | Mistake | Cost | The check |
|---|---|---|---|
| **M1** | Over-broad exclude destroyed the payload. `--exclude='_research/re/rust/'` dropped 26 files / 1.44 MB incl. the keystone `cap.rs`; `--exclude='_research/re/target/'` assumed "target == build output" and would have dropped the oracle. | 26 irreplaceable source files | Every exclude **anchored** (leading `/`) and accompanied by a printed **per-pattern match count**. Plus a manifest-size floor (`[ "$RN" -lt 24000 ] && die`). An over-broad pattern must show up as a **number**, never as silence. |
| **M2** | Verification that verified nothing — v1 hashed the local copy and compared it to itself. | a truncated transfer would have "passed" | Diff a **remote** manifest against a **local** manifest. Keep **coverage** and **fidelity** as two separate gates: `grep -c '^<'` (missing) vs `grep -c '^>'` (unexpected). |
| **M3** | Over-collection of secrets. `--include='backups/***'` swept another account's `machineID`/`userID`/`oauthAccount`, 1,068 unrelated prompts, and two unrelated sessions' task stores. | identity blobs + unrelated prompt history copied | **Whitelist, never blacklist**, when copying from a `~/.claude`. Enumerate the exact paths belonging to the session (§1.1) **plus an independent denylist assertion over the staged bytes** (§1.3). |
| **M4** | Backed up but never installed. Skills and plugins were copied into the checkpoint and never installed at the destination; the gap was invisible because the backup looked complete. | shared assets missing at DEST | An explicit **"shared assets installed at destination"** gate, distinct from "shared assets backed up". Assert file counts at the DEST path, not the checkpoint path. |
| **M5** | Unconditional publish — v1 advanced `latest` even on failure, poisoning the next run's `--link-dest`. | a crashed run becomes the baseline | `ln -sfn` gated on `FAIL -eq 0` **and** verification passing; write the `SEALED`/`COMPLETE` sentinel **last**; `--link-dest` must point at the newest generation **containing** the sentinel, never at `latest` blindly. |
| **M6** | Sealed-source permission propagation. `copy2` from a read-only sealed checkpoint made the destination transcript read-only; two `--apply` runs failed partway. | two failed partial runs | `chmod` after every copy out of a sealed tree (`--no-perms --chmod=u+rwX` for rsync, explicit `os.chmod(…, 0o600)` after `shutil.copy2`). Make every apply step **idempotent**: delete-if-exists (after chmod) before re-copying. |
| **M7** | A false PASS. A grep for signature errors "passed" because the run had died earlier at "Not logged in" and never reached the API. | a gate that could never fail | Every check first asserts the thing it checks actually **executed**. Absence of an error is not evidence of success. Prefer positive signals (`reached the network call`) over negative ones (`no error found`). |
| **M8** | Host pollution. A subagent told "install Rust without sudo" put 1.6 GB in `$HOME`. | 1.6 GB of unwanted host state | **State containment constraints in every prompt that might install something**: name the workspace-local prefix, and forbid `apt`, `~/.cargo`, `~/.local`, and the host conda explicitly. |

### 7.2 The twelve tripwires (prohibitions, stated before instructions)

1. **Never** invoke `claude://resume`, the Recover-CLI-sessions UI, or `importCliSession` against this session — all three call `stripThinkingBlocksFromFile` (§5.4).
2. **Never** write to the origin — enforced by a **deny-regex in a single ssh chokepoint**, not by intention.
3. **Never** combine `--inplace` / `--append` / `--append-verify` with `--link-dest` — writing through a hardlink mutates every prior generation.
4. **Never** pass `--delete` toward the origin.
5. **Never** copy `.credentials.json`, `~/.claude.json`, `backups/`, `telemetry/`, `policy-limits.json`, `sessions/`, `shell-snapshots/`, `history.jsonl`, or any user-data-dir file other than `claude-code-sessions/<acct>/<org>/local_*.json` — specifically **not** `config.json`, `Cookies`, `Local State`, `Local Storage/`, `IndexedDB/`, `ant-did`.
6. **Never** drop a session file in while the target Desktop instance is running (§3.5).
7. **Never** blanket-`sed` the transcript (§5.4).
8. **Never** derive a project-dir name by editing another one (§6 F1/F24).
9. **Never** run `git gc` — or any porcelain that may auto-trigger it — on a rescued repo before commit #1. Set `gc.auto=0` as the literal first operation. Note **`git status` without `--porcelain` can rewrite `.git/index`** (stat-cache refresh); prefer `git --no-optional-locks status --porcelain`.
10. **Never** read the 216 MB transcript whole. Stream, write a new file, `os.replace`.
11. **Never** strip thinking blocks.
12. **Never** `org.gnome.Shell.Eval`, XTEST/XSendEvent/`XCompositeRedirectWindow` on a shared display, or the global `toolkit-accessibility` gsetting. Every modifier press in `try/finally` with an XKB force-release teardown.

### 7.3 Rig discipline (learned the hard way)

- **Every CLI invocation sets `CLAUDE_CONFIG_DIR` inside the rig, behind a guard clause that aborts with `exit 9`**, and re-passes it on the `env` line:
  ```bash
  [[ "$CLAUDE_CONFIG_DIR" == "$S/cfg" ]] || { echo "SAFETY ABORT"; exit 9; }
  case "$CLAUDE_CONFIG_DIR" in /home/dana/.claude*) echo "SAFETY ABORT: live config"; exit 9;; esac
  ```
- **Give each experiment its own `CLAUDE_CONFIG_DIR`.** E4 was contaminated mid-run by a concurrent agent creating probe dirs inside the shared `cfg/projects`, silently changing the search space a scoping test depended on. E4 had to restore the shared dir and re-run everything in a private one.
- **Serialize ssh calls** or set `ControlMaster=auto` with retries — a burst of parallel `ssh mac1` calls produced `mux_client_request_session: session request failed` / `ControlSocket … already exists`, which falls back to a non-multiplexed connection and is easily misread as a remote failure.
- **mac1 has no GNU `timeout`.** Use `perl -e 'alarm N; exec @ARGV'`.
- **mac1's `rsync` is openrsync** ("protocol version 29, rsync 2.6.9 compatible"): **no** `-H`, `-X`, `-A`, `-S`, `--iconv`, `--fake-super`, `--protect-args`. It **does** have `--link-dest`, `--checksum`, `--itemize-changes`, `--numeric-ids`, `--delay-updates`, `--partial`, `--append`, `--inplace`, `--backup-dir`, `-n`.
- The non-destructiveness claim must be scoped honestly: **"no modification to the two target subtrees"**, not "no byte on the machine changes" — ssh login shells and some git subcommands write `.zsh_history`, `stats-cache.json`, etc. **atime drift is explicitly accepted** (reading changes it; `noatime` remount is a forbidden system-settings change).
- Origin fingerprint = `mtime + size + mode + **inode** + name`, sorted, hashed. `atime` **excluded** (would fail by construction); `ctime` captured as a **second, advisory** fingerprint so a difference distinguishes "we changed it" from "something else touched it". `inode` is included because it detects a delete+recreate preserving mtime and size — the signature of a botched atomic replace. **Capture `pre` as well as `post`**; the original script captured only `post`, leaving nothing to compare against.

### 7.4 Standing rig tooling (all zero-token), now durable under `scripts/`

| Path | What it does |
|---|---|
| `scripts/measurement/anchor-rig/mangle.py` | Canonical project-dir mangler, **22/22**. Must be fed `realpath(cwd)`. **Losing this means re-deriving the mangler from the ELF before any transplant can be preflighted.** |
| `scripts/measurement/anchor-rig/probe.sh` | Zero-API-turn dead-port probe. exit 124 = loaded; exit 1 = not found. |
| `scripts/measurement/anchor-rig/make_synthetic.py` | Builds synthetic 4-line transcripts (`user` → `assistant`(thinking) → `last-prompt` → `custom-title`), 2.1.215-shaped: **no `slug`, no `mode`, `effort` present**, `JSON.stringify`-equivalent compact separators `(',',':')`, `ensure_ascii=False`, LF-terminated. The thinking block + signature are **lifted verbatim from a genuine record** — a fabricated signature is guaranteed-invalid and makes any API-touching outcome uninterpretable. A `-notext` control variant (text block instead of thinking) separates "signature rejected" from "placement wrong". |
| `scripts/measurement/{dag,leafchk,striprisk,xref,manifest,list,extract,extract2,extract_paths,pp,ctx}.py` | DAG walk / leafUuid resolution / thinking-strip damage model / workflow⇄agent cross-reference / footprint manifest / roster tables / path census. |
| `scripts/measurement/e3/{pty2,pty3,pty_picker,wire,ctx}.py` | Startup picker and in-REPL `/resume` under a PTY; reads the effective cwd straight off the wire; byte-offset context printer for a carved bundle. |
| `scripts/e13-fullfile-load.sh` | The full-file load test, with the correct PASS signal (§6 F11). |
| `scripts/oracle-run.sh` | Proven remote runner with a **verified-sensitive** tripwire. |
| *(in the session scratchpad, not yet durable)* `e2/mock_api.py`, `e2/mock_sig400.py`, `asar/asar_read.py` | Recording mock of `api.anthropic.com` (SSE); signed-thinking-rejection simulator; dependency-free read-only asar reader (works where `npx @electron/asar` fails on Node 18). |

Two reusable techniques worth naming:
- **The recording mock** turns "what does the CLI actually send" into a measurement. `mock_api.py` is ~100 lines of `http.server` that records every request body verbatim and answers `/v1/messages` with a well-formed SSE stream, so a **full turn completes locally at zero cost**.
- **The 4-cell matrix.** E3 isolated the `relocated` chdir by running four PTY sessions on one fixture, varying exactly one thing each: `relocated` present w/ in-record sessionId · present w/ filename uuid · absent · absent-but-records-say-cwdB. Rows 1-vs-3 differ by one line and prove causation; row 4 proves `$.cwd` inertness.

---

## 8. OPEN ISSUES — real gaps in the run that happened

These are **not** hypotheticals; each was verified on disk while writing this file.

| # | Issue | Evidence | Consequence / fix |
|---|---|---|---|
| **O1** | **The 9 sibling workflow scripts were backed up but never installed** — the exact M4 pattern, still open. The checkpoint holds `<ORIGIN_KEY>--research-re` (4 files), `…--research-re-rust` (1), `…--research-re-tools-devio-fasp-diag` (2), `…-SimLab-acmeorg-simlab` (1), `…-SimLab-acmeorg-simlab-rust` (1). `~/.claude/projects/` at the destination contains **only** `-home-dana-Projects-transporter`. `transplant.py` copies `<ORIGIN_KEY>/<SID>/` and `<ORIGIN_KEY>/memory/` and nothing else. | `[LIVE]` | 9 workflow scripts / 76,374 B unreachable. Fix: copy each sibling key's `<SID>/workflows/scripts/` into `mangle(realpath(<corresponding dest subdir>))/<SID>/workflows/scripts/`. This is LADDER assumption **A6**, never exercised. |
| **O2** | **One `tool-results` blob disappeared after install.** Checkpoint has **11**; the destination has **10** — `bmdwv27oc.txt` is gone, and the dest `tool-results/` mtime (14:33) is *after* the transplant (14:18). | `[LIVE]` | The destination CLI's own retention sweeper prunes this store (cf. `~/.claude/.last-cleanup`). Copy sidecars **late**, verify counts **after** the first launch, and treat `tool-results/` as decaying. The origin store was **already inconsistent**: 5 keys referenced / 11 on disk / **3 dangling** / **9 orphaned**. |
| **O3** | **No `{"type":"relocated"}` record was ever appended.** `grep -c '"type":"relocated"'` on the live transcript → **0**. `transplant.py` appends only the human-readable notice (`type:"user"`). | `[LIVE]` | The in-REPL `/resume` path will not chdir. Harmless for `--resume`/Desktop; one free line to fix, with the three constraints in §5.7. |
| **O4** | **47 of 85 workflow `scriptPath` targets were already dead on mac1** before any migration — the dirs they point into were partly deleted (`-…-transporter-DevIO-acmeorg-devio/<SID>` gone; `-…-devio-{rust,python,js,swift}` and `-…--research-re-tools-devio-fasp` never/no-longer exist). | `[M]` | Workflow resume needs the `.js` at that absolute path **plus** `wf_<runId>.json`. **All 85 `script` fields are non-empty**, so every missing `.js` is regenerable into `workflows/scripts/<workflowName>-<runId>.js`. |
| **O5** | **Cross-account `thinking.signature` replay was never tested against the real API** (LADDER **A1**). E13 put **166 signed thinking blocks minted under org `0a0a0a0a` / account `aaaaaaaa`** onto the wire under org `0b0b0b0b` / account `bbbbbbbb`. | `[M]` | The session subsequently ran, which is strong evidence it is accepted — but the controlled single-turn test (`--resume=1c4ec3a8-…` against the `compact200` maximal-hazard slice) was never run. If it ever fails: **fatal, single-shot, no retry**; alternatives are (2) resume from the last compact boundary or (3) read-only history + fresh session seeded from `memory/` + `tasks/`. Alternative (1) "mint a new sessionId" is **known not to help** — E2 already resumed with a filename uuid differing from every record's sessionId and the signatures went out verbatim. |
| **O6** | **`scholarly-pdf-acquisition` (321 MB installed, ~331 MB of it a `.venv` with two bundled Node runtimes) was copied wholesale.** The whitelist entry was a bare `"skills"`. | `[LIVE]` | R01 explicitly recommended excluding it. A skill-copy step should whitelist skill **names**, and audit `scripts/` for `#!/bin/zsh`, `brew`, `otool`, `codesign` and arm64 binaries before copying anything executable. |
| **O7** | **`_backups/mac1/latest` is an absolute symlink.** | `[LIVE]` | Moving `_backups` silently breaks every baseline lookup. Make it **relative**. |
| **O8** | **E14 (sidecar resolution) was never run end-to-end.** The rule "SID must stay the origin session id because sidecars resolve from the filename stem" is `[D]` — a measured premise (`Et()` == filename uuid on resume) plus lifted code (`WUd`), not an end-to-end measurement. | LADDER **A3** | Cheap to honour and costless if wrong, so the rule stands regardless. Confirming experiment: place a slice as `<sid>.jsonl` with a populated `<sid>/subagents/` beside it, resume, observe whether a subagent record resolves and where a new one is written. |
| **O9** | **E8 (Desktop drop-in) was never formally run**, though the real migration exercised it successfully — the JSON loaded, the app opened the session, ran a turn, and rewrote the file with `completedTurns:1` and `model:"claude-opus-5"`. | `[LIVE]` | Treat §3.4 as the validated template. |
| **O10** | **E9 (semantic verification) was never run.** "Loaded" ≠ "faithful"; byte counts cannot detect the difference. | LADDER **A5** | Expected answer: **CAP-TLV keystone, tracker #148**. |
| **O11** | **E0 (coverage diff) was never formally re-run** with a printed exclusion list and per-pattern match counts. | LADDER **A7** | ~10 s, read-only, and probably already green: the DIFF files are 0 bytes and the 7 `_research/re/target` files are confirmed present and identical. Add `rsync -n -a -c --itemize-changes` as an independent second opinion (it uses MD4/MD5 rolling checksums — a genuinely different mechanism from the SHA-256 manifests, which is the point). |
| **O12** | **RISK-01 remains open on the origin.** `SimLab/acmeorg_simlab` has an **unborn HEAD**: 338 staged files exist as content-addressed blobs with no names, the only copy of the blob→filename mapping is a 34,016 B `.git/index`, and `git fsck` reports all **427 loose objects** as dangling. `.gitignore` excludes `_research/`, `_vetting/`, `_conda/`, `_scratch/`, `rust/target` — so the 26 untracked files and everything ignored are not represented in git at all. | `[M]` | Copy `.git/` **verbatim and first**, every time; verify `ls-files \| wc -l == 338` and `sha256sum .git/index`. Set `gc.auto=0` on the local copy before touching it. The durable fix (creating commit #1) is a **write to the origin** and must be done by the user. |

### 8.1 Things deliberately NOT done, and why

| Not done | Reason |
|---|---|
| Tier 1 (structural path rewrite of ~42,650 pointers) | Measured-inert (`$.cwd`), measured-unnecessary (`slug`/`mode`/`sessionId`), or cosmetic. It buys **addressability of historical file references** for a human reading scrollback — genuinely useful, never on the critical path. If ever attempted, the acceptance test is **invertibility**: apply the inverse map and assert `sha256(inverse(rewritten)) == sha256(original)`. No exceptions, no "close enough". A rule is admissible **only if its target string occurs zero times in the input**. Measured: `/home/dana` occurs on **2** lines ⇒ the obvious broad rule is **inadmissible**; `/home/dana/Projects/transporter`, `/home/dana/.claude`, `/tmp/claude-1000` all occur 0 times ⇒ admissible. |
| `sessionId` rewrite across 47,088 lines | The CLI keys resume off the **filename**. The stronger statement: the filename **must** be the origin sessionId, so the rewrite is not merely unnecessary — it is **contraindicated**. |
| `field_patch` rule class (version skew) | Envelope fields reach the wire **0 times**. Dead. |
| Copying `plugins/` bytes | arm64 payload + absolute `installPath`. Reinstall from the marketplace. |
| Write-back to the origin | Requires the user's **typed** authorization; it is the only origin-mutating action in the plan. **The origin is never deleted.** The protocol, if needed, is seven-staged with stages 1–5 making **no remote writes**, a three-way classification against the SOURCE_CHECKPOINT base (`UNCHANGED / LOCAL_ONLY / REMOTE_ONLY / BOTH_CHANGED / NEW_LOCAL / DELETED_LOCAL`), `BOTH_CHANGED` **never** auto-resolved, deletion disabled by policy, and a final confirmation that is a **typed file count**, not a `y/n`. |
| Pushing an extended transcript back | Legal **only** if the remote file is still a byte-exact **prefix** of the local one. If the origin appended anything, the histories have forked: **refuse and write to a new filename** — never overwrite `<SID>.jsonl` in place. |
| Case/NFD gates on the pull direction | ext4 is case-sensitive, APFS here is case-**insensitive**; a push that merges `Foo.md` and `foo.md` **silently destroys one file's content and rsync reports success**. Currently 0 collisions and 0 non-ASCII names, so the risk is prospective — but the scan must be **FATAL on push** (openrsync has no `--iconv`; nothing can fix it in flight) and warn-only on pull. |

### 8.2 Cross-platform notes for the scripts

- POSIX-ish bash or `python3` stdlib only, must run on **macOS and Linux** (the origin may be either).
- macOS: no GNU `timeout`; `stat -f` not `-c`; BSD `find` rejects `-newermt @epoch`; `shasum -a 256` exists but `/sbin/sha256sum` is 5× faster; openrsync flag set (above); `zstd` may be absent.
- Remote helper scripts should be shipped **over stdin** (`ssh host 'python3 -' <<script`) and **never written to the origin** — that is what makes "we wrote nothing to the origin" literally true rather than merely intended. Constrain to the remote Python's stdlib (3.9.6 on mac1).
- `realpath` differs; compute the physical path with `python3 -c 'import os,sys;print(os.path.realpath(sys.argv[1]))'` or `cd "$d" && pwd -P`.
- ext4 vs APFS: case sensitivity and NFC/NFD are the two asymmetries that bite.

### 8.3 Provable properties to advertise

1. **History untouched.** `sha256(first N bytes of the destination transcript) == sha256(origin transcript)` where N = the origin size. Verified `[LIVE]` at N = 216,236,906 → `074487a7bd31324ece84462f5ff46a07703feeab94941e62f5b76d9af6d2a32a`, on a file that has since grown to 218,813,752 B / 47,551 lines through normal use.
2. **Origin unmodified.** Before/after fingerprints over exactly the two target subtrees, plus the dedicated git-untouched assertion (`.git/index` size **and** ctime, 338 index entries, 427 loose objects, no `gc.log`).
3. **Transfer complete and faithful.** Remote-vs-local manifest diff, both sides 0 bytes.
4. **Nothing secret collected.** The whitelist is enumerable and short; the denylist assertion runs over the staged bytes independently.
