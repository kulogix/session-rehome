# Secrets and privacy discipline

A `~/.claude` and a Claude Desktop user-data-dir are **credential stores that happen to also
contain a conversation**. Migrating a session means walking through both of them. This file is the
containment discipline for that walk.

Evidence tags: `[M]` measured in the migration session · `[C]` lifted from code · `[D]` derived ·
`[I]` inferred · `[LIVE]` re-verified on disk while writing this file.

Cross-refs: `mechanics.md` (what a session is made of, and where it lives) · `integrity.md`
(coverage vs fidelity, `--link-dest`/SEALED, publish-on-success, the non-destructiveness proof) ·
`lessons.md` (the eight mistakes; **M3 is this file's subject**) · `SKILL.md` (the phase order and
the top-level gates).

This file owns one question: **what must never move, and what to do when it already did.**

---

## 0. The five laws

1. **Whitelist, never blacklist.** Enumerate the exact paths belonging to the session. Never
   express the copy set as "everything except…".
2. **The whitelist is not the enforcement.** Run an **independent denylist assertion over the
   staged bytes** after the copy. The allowlist alone is what M3 defeated.
3. **Never open a credential-bearing file.** Not `cat`, not `head`, not `jq`, not `sha256sum`,
   not `python -c 'json.load'`. Metadata (`stat`, `ls -l`) is fine; content is not.
4. **Not-reading is not a licence to copy.** These are two independent rules and rule 4 is the one
   the last run got wrong (§6).
5. **A secret read once is unremovable.** The transcript is append-only, 216 MB, and blanket-`sed`
   and record-stripping are both prohibited tripwires. Anything you print lands in the payload you
   are about to copy to another host **and another account**, permanently.

---

## 1. Why this is not a generic "be careful with secrets" section

The artifact being migrated is a conversation transcript. The transcript is:

| Property | Value | Consequence |
|---|---|---|
| Append-only | resume is a pure append; first N bytes byte-identical after 3 resumes `[M]` | you cannot delete a line |
| Rewriting | blanket `sed` prohibited — 54,157 occurrences of the origin home, ~5,705 of them not paths `[M]` | you cannot redact in place |
| Stripping | `stripThinkingBlocksFromFile` deletes 6,331 records and severs ~6,332 parent links `[M]` | the one in-product rewriter is a tripwire, not a tool |
| Destination | a **different account** (`aaaaaaaa-…` → `bbbbbbbb-…`) on a **different host** `[M]` | anything in it crosses an account boundary |

So the ordinary mitigation ("oops, I'll scrub it") does not exist here. Prevention is the only
control. That is why the conduct rules below are absolute rather than best-effort.

Corollary: **the same applies to `memory/`.** The 24-file / 399,050 B memory corpus `[M]` is
re-read at the start of every session and is copied verbatim. Never write a credential into a
memory file "temporarily".

---

## 2. LIST B — NEVER COPY

Each row is a measured reason, not a guess. Sizes are from the two hosts of the reference run;
`[LIVE]` rows were re-`stat`ed while writing this file (metadata only — no file below was opened).

### 2.1 Under `~/.claude` (and its one sibling outside it)

| Path | Size / mode | What is in it | Why never |
|---|---|---|---|
| `~/.claude/.credentials.json` | 322 B origin, **11,027 B local** `[LIVE]`, `0600` | `claudeAiOauth.{accessToken (108 chars), refreshToken (108 chars), expiresAt}` — shape derived programmatically, values never printed `[M]` | **IS the account identity.** A live OAuth bearer + refresh pair. Copying it moves one account's credentials onto another machine. The destination already has its own. |
| `~/.claude.json` (**outside** the dir) | 54,354 B origin, **39,993 B local** `[LIVE]`, `0600` | `machineID` (host), `userID` + 19-key `oauthAccount{emailAddress, accountUuid, organizationUuid, organizationRole, billingType, …}` (account), `projects{21 absolute paths}` (host), 442 feature flags, per-org caches `[M]` | Host **and** account coupled. **Hand-add exactly one key at the destination:** `projects["<dest root>"].hasTrustDialogAccepted = true`. Nothing else. |
| `~/.claude/backups/` | 5 × 54,354 B | a rolling ring of `~/.claude.json` — i.e. **five more copies of the identity blob** | **This is what M3 swept** (§4). "backups" is a false friend: it backs up the *config*, not the session. Nothing in `~/.claude` protects the 216 MB transcript `[M]`. |
| `~/.claude/history.jsonl` | 433,604 B, 1,068 lines, `0600` | `{display, pastedContents, timestamp, project, sessionId}` per submitted prompt | **0 records for the target session** — Desktop-spawned sessions (`entrypoint:"claude-desktop"`) never write it. 1,060 of 1,068 lines belong to an **unrelated project**; last write three months before the session `[M]`. Pure third-party prompt leakage plus absolute paths of other work. |
| `~/.claude/tasks/<other-SID>/` | — | other sessions' todo stores | Copy **only** `tasks/<SID>/`. The reference run's over-collection took two unrelated sessions' stores (`4f109e01-…`, `76d5d130-…`) `[M]`. |
| `~/.claude/projects/<other-KEY>/` | 5.1 GB across 48 dirs `[M]` | every other project's transcripts | The session is 370 MiB of a 5.5 GB tree. See §3.1 for the **directory-whitelist trap** inside your own project key. |
| `~/.claude/telemetry/*.json` | 1.7 MB, 5 files | JSONL despite the extension; each record carries `device_id`, an `auth` block, `env.platform`, `betas`, `session_id` of **other** sessions `[M]` | Undelivered analytics. Device + auth identifiers, zero session content. |
| `~/.claude/sessions/<PID>.json` | ~279 B each | `{pid, sessionId, cwd, startedAt, procStart, version, peerProtocol, kind, entrypoint, name, nameSource}` `[M]` | **Live-process registry keyed by PID, not an archive.** A stale entry advertises a non-existent peer to the destination's cross-session discovery. |
| `~/.claude/shell-snapshots/*.sh` | 11 files, 616 KB | full zsh function/alias/PATH dump (sdkman, asdf, wasmer, arm64 clangd paths) `[M]` | Host-coupled; also a common place for exported tokens to appear in a function body. Gives the destination a broken shell. |
| `~/.claude/policy-limits.json` | 125 B | **this org's** server-pushed policy | Applies the wrong org's restrictions at the destination. |
| `~/.claude/stats-cache.json` | 1,450 B | account usage totals | Account-coupled and stale. |
| `~/.claude/plugins/` | 4.4 MB | absolute `installPath`/`installLocation`, arm64 `clangd` | **Regenerate from the marketplace, never copy bytes.** |
| `~/.claude/cache/`, `debug/`, `paste-cache/`, `downloads/`, `file-history/`, `session-env/`, `.last-cleanup` | ~0–255 KB | regenerable / empty on both hosts `[M]`; `debug/latest` is a dangling absolute symlink | No value, host-coupled. Accepted loss: `/rewind` has no pre-edit snapshots at the destination. |
| all `.DS_Store` | 39 in the project tree + several in `~/.claude` | macOS Finder metadata | Exclude explicitly. |

### 2.2 Under the Desktop `<user-data-dir>`

Exactly **one** path under a user-data-dir is ever written by this procedure:
`claude-code-sessions/<accountUuid>/<orgUuid>/local_<uuid4>.json`. Everything else is off-limits in
both directions.

| Path | Size / mode `[LIVE]` | Contents | Why never |
|---|---|---|---|
| `config.json` | 2,620 B, `0600` | `oauth:tokenCache` **and** `oauth:tokenCacheV2` — both `safeStorage.encryptString(...)` → base64 in an electron-store JSON `[C]` | **Encrypted OAuth material.** The user named this file explicitly and **no candidate design had listed it** — the single most-missed item in the whole survey. |
| `Cookies`, `Cookies-journal` | 28,672 B, `0600` | Chromium cookie leveldb — including the `lastActiveOrg` cookie the app derives `orgUuid` from `[C]` | Session cookies for `claude.ai`. Touching the leveldb of a **running** instance corrupts it. |
| `Local State` | 136 B, `0600` | `{"os_crypt":{"portal":…},"uninstall_metrics":…}` `[M]` | On Linux this holds **no `encrypted_key`** — the master key lives in gnome-keyring (`'Chrome Safe Storage'` items) `[M]`. So a cross-host copy is simultaneously a credential leak *and* undecryptable garbage at the far end. On macOS/Windows the equivalent file *does* carry the wrapped key. |
| `Trust Tokens`, `Trust Tokens-journal` | 36,864 B, `0600` | Privacy Pass / anti-fraud token store | Device-bound attestation material. |
| `ant-did`, `ant-device-registry.json`, `buddy-tokens.json`, `SingletonCookie`, `TransportSecurity` | 48 / 61 / 68 / — / 1,689 B, `0600` `[LIVE]` | device identity, device registration, bearer-ish tokens, HSTS pin state | Device attestation. Duplicating a device identity onto a second host is both a leak and a correctness bug. |
| `IndexedDB/`, `Local Storage/`, `Session Storage`, `SharedStorage*`, `DIPS*`, `WebStorage`, `Partitions/` | — | the **cloud** chat cache (`conversations_v2`, `mutations`, `queries`), `claude-device-binding`, composer drafts, pane layout, a per-session cost cache | Verified to hold **only disposable UI state** for local sessions `[M]`. Nothing load-bearing is lost by skipping them; everything is risked by copying them. |
| `Cache/`, `Code Cache/`, `GPUCache/`, `Dawn*Cache/`, `blob_storage/`, `fcache/`, `Crashpad/`, `sentry/`, `logs/` | — | HTTP + code caches, crash dumps, breadcrumb logs | Crash dumps and breadcrumbs routinely contain request URLs, headers and heap fragments. |
| `claude_desktop_config.json` | — | MCP server definitions | **Frequently holds API keys in `env` blocks.** If MCP config must be carried, transcribe server entries by hand, omitting every `env` value, and let the user re-enter them. |

### 2.3 Outside both trees

| Path | Measured shape | Why never |
|---|---|---|
| `~/.config/gh/hosts.yml` | 82 B, `0600` on both hosts `[LIVE]` | On the origin the token was in the macOS Keychain and the file's `users.kulogix:` key was **empty** — no token on disk `[M]`. **Do not generalise from that.** On many hosts `gh` writes `oauth_token:` in plaintext into this exact file. The token measured for this account carried scopes `gist, read:org, repo` — `repo` is write access to private repositories `[M]`. Never copy, never read, never `gh auth token`. |
| `~/.ssh/`, `~/.aws/`, `~/.docker/config.json`, `~/.netrc`, `~/.npmrc`, `~/.pypirc`, `~/.git-credentials`, `~/.gitconfig` credential-helper lines | — | out of scope by construction | They are not part of a session. If a step seems to need one, the step is wrong. |
| `~/.zsh_history`, `~/.bash_history` | — | — | Not in scope; also a routine plaintext-secret location. |

---

## 3. The whitelist that is actually used

The copy set is the **8 session roots + memory + settings + skills**, enumerated in
`mechanics.md` §1 and §7. The literal array from `pull-checkpoint.sh`:

```bash
CLAUDE_PATHS=(
  "projects/$PROJKEY"                       # see §3.1 — DIRECTORY whitelist, sharpen this
  "projects/${PROJKEY}--research-re"        # sibling keys: <SID>/workflows/scripts/ only
  "projects/${PROJKEY}--research-re-rust"
  "projects/${PROJKEY}--research-re-tools-devio-fasp-diag"
  "projects/${PROJKEY}-DevIO-acmeorg-devio"
  "projects/${PROJKEY}-SimLab-acmeorg-simlab"
  "projects/${PROJKEY}-SimLab-acmeorg-simlab-rust"
  "tasks/$SESSION"                          # NOT bare "tasks"
  "skills"                                  # see §3.2
  "plugins"                                 # regenerate at DEST; do not install these bytes
  "settings.json"                           # merge 2 keys; see §3.3
)
# Deliberately NOT taken: .credentials.json, .claude.json*, backups/, history.jsonl,
# telemetry/, sessions/, shell-snapshots/, session-env/, cache/, stats-cache.json,
# policy-limits.json, and any tasks/ store not belonging to $SESSION.
```

Note the deliberate `tasks/$SESSION` rather than `tasks` — that specificity is the M3 fix, and it
is the pattern the remaining entries should follow.

### 3.1 The directory-whitelist trap (a real gap, not a hypothetical)

`projects/$PROJKEY` is a **directory** whitelist. A project directory contains
`<SID>.jsonl` for **every session ever run in that cwd**, not just yours.

Measured on the origin `[LIVE]`: 48 project dirs; the target key held exactly **1** transcript, so
no damage occurred — but `-…-MusicRights` and `-…-exampleapp-2026-website` hold **2 each**. On
either of those, this whitelist entry would have quietly copied a stranger's entire conversation.

**Sharpen it.** Take the four session-scoped members explicitly and `memory/` separately:

```bash
"projects/$PROJKEY/$SESSION.jsonl"
"projects/$PROJKEY/$SESSION"          # sidecars: subagents/ tool-results/ workflows/
"projects/$PROJKEY/memory"            # project-scoped, intentionally shared
```

Then assert it held: `find <staged>/claude/projects -maxdepth 2 -name '*.jsonl' | wc -l` must equal
**1**, and the one filename must be `$SESSION.jsonl`.

### 3.2 `skills/` is a bare directory whitelist too

The reference run copied the whole `skills/` tree: **341 MB across 12 skills**, of which
`scholarly-pdf-acquisition` is **338 MB** — mostly a `.venv` bundling two ~114 MB Node runtimes —
against ~2.5–2.9 MB of authored content across all twelve `[M]`. It had been explicitly
recommended for exclusion and was copied anyway because the whitelist entry was the bare word
`skills`.

Skills are third-party-ish code you are about to install and execute at the destination. Before
copying any of them:

- whitelist skill **names**, not the directory;
- grep each skill's `scripts/` for `#!/bin/zsh`, `brew`, `otool`, `codesign` and arm64 binaries
  (they will not run at a Linux destination);
- grep each skill tree for credential shapes (§5) — a skill's `references/` or `.env` is a
  plausible place for an API key;
- skip any bundled `.venv`, `node_modules`, or vendored runtime outright.

### 3.3 `settings.json` is merged, never copied

The reference `settings.json` was 112 B and exactly **two** keys were merged
(`skipWorkflowUsageWarning`, `enabledPlugins`) `[M]`. Keep it that way. A Claude settings file can
legitimately carry `env`, `apiKeyHelper`, `awsAuthRefresh` and hook command lines — all of which
are credential surfaces. Merge named keys; never `cp` the file.

---

## 4. M3 — what over-collection actually cost, and why blacklisting fails

**The mistake.** v1 of the pull expressed part of the copy set as an rsync include pattern:
`--include='backups/***'`. Intent: "grab the backups, they might matter." Effect `[M]`:

| Swept | Quantity | Content |
|---|---|---|
| `~/.claude/backups/` | **5 files × 54,354 B** | five copies of **another Anthropic account's** global config: `machineID`, `userID`, and a 19-key `oauthAccount` block carrying email address, account UUID `aaaaaaaa-…`, org UUID, org role and **billing type**, plus 21 absolute macOS project paths |
| `history.jsonl` | 433,604 B, **1,068 records** | that user's prompt history — 1,060 lines from an **unrelated project** |
| `tasks/<other-SID>/` | 2 session stores | two unrelated sessions' todo state |

None of it had any bearing on the session. All of it landed on a second host, under a second
account, inside a tree that was earmarked for `git init`.

**Why a blacklist cannot work here.** A blacklist is a claim about a set you have not enumerated.
`~/.claude` is 5.5 GB across 48 project directories, and the CLI adds new top-level entries between
versions (`telemetry/`, `session-env/`, `stats-cache.json`, `policy-limits.json` are all recent).
Every future addition is admitted by default. A whitelist's failure mode is a **missing file**,
which the coverage gate catches loudly; a blacklist's failure mode is a **leaked credential**,
which nothing catches.

**Why the whitelist alone is also not enough.** M3 *was* inside an include-list-shaped script. The
pattern `backups/***` was written by hand, at 4 a.m., with a plausible-sounding justification. The
control that catches that class of error is not a better allowlist — it is an **independent
assertion, written separately, that runs over the bytes actually staged**.

### 4.1 The independent denylist assertion

Run after Phase A (pull) and again after Phase F (transplant). It must exit non-zero and it must be
loud. Python 3 stdlib only; runs on macOS and Linux.

```python
#!/usr/bin/env python3
"""denylist-assert.py <staged-root> [<staged-root> ...]
Exit 40 on any hit, 0 when clean. Filename/path matching only — NEVER opens a file.
python3 stdlib only; runs on macOS and Linux."""
import os, sys, re

DENY_NAMES = {
    ".credentials.json", ".claude.json", "history.jsonl", "stats-cache.json",
    "policy-limits.json", "config.json", "Local State", "Cookies", "Cookies-journal",
    "Trust Tokens", "Trust Tokens-journal", "ant-did", "ant-device-registry.json",
    "buddy-tokens.json", "SingletonCookie", "TransportSecurity", "hosts.yml",
    ".netrc", ".npmrc", ".pypirc", ".git-credentials", "claude_desktop_config.json",
    ".DS_Store",
}
DENY_DIRPARTS = {
    "backups", "telemetry", "sessions", "shell-snapshots", "session-env",
    "paste-cache", "file-history", "downloads", "debug", "IndexedDB",
    "Local Storage", "Session Storage", "Crashpad", "sentry", "Partitions",
    "server_keys", "captures", ".ssh", ".aws", ".gnupg",
}
DENY_RE = re.compile(r"(\.claude\.json\.backup\.\d+|\.pem$|\.key$|^id_(rsa|ed25519|ecdsa)$"
                     r"|\.p12$|\.pfx$|\.keystore$|\.jks$|secrets?\.env|credentials?\.txt$)")

# Vendored/third-party subtrees. NOT scanned — their fixtures and bundled CA stores fire
# every rule above and would bury a real hit (measured: 6 false positives, 0 true, on the
# reference checkpoint). They are REPORTED, not silenced: a vendored tree inside a staged
# checkpoint is itself a finding (see §3.2 — nothing vendored should be staged at all).
PRUNE_DIRS = {"node_modules", ".venv", "venv", "site-packages", "vendor",
              "marketplaces", "external_plugins", ".git", "__pycache__"}

def main(roots):
    hits, pruned = [], []
    for root in roots:
        for base, dirs, files in os.walk(root):
            for d in list(dirs):
                if d in PRUNE_DIRS:
                    pruned.append(os.path.join(base, d))
                    dirs.remove(d)                      # do not descend
                elif d in DENY_DIRPARTS:
                    hits.append(os.path.join(base, d) + "/  [denied dir]")
                    dirs.remove(d)                      # do not descend; do not enumerate
            for f in files:
                if f in DENY_NAMES or DENY_RE.search(f):
                    hits.append(os.path.join(base, f))
    if pruned:
        print(f"NOT SCANNED — {len(pruned)} vendored subtree(s) present in the staged set:")
        for p in sorted(pruned):
            print("  " + p)
        print("  (each is a staging finding in its own right — see secrets.md §3.2)")
    if hits:
        print(f"DENYLIST VIOLATION: {len(hits)} path(s) staged that must never be copied:")
        for h in sorted(hits):
            print("  " + h)
        return 40
    print(f"denylist clean across {len(roots)} root(s)")
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or ["."]))
```

Four properties that matter:

- **It matches on paths, never contents.** It cannot itself leak what it is looking for.
- **It is written independently of the allowlist.** If both were derived from one list, a wrong
  entry would appear in both and cancel out.
- **It runs over *existing* state, not just future stages.** M3's damage was already on disk when
  it was found; a gate that only guards new runs would have reported clean.
- **Pruning is reported, never silent.** A rule that produces mostly false positives gets ignored,
  and an ignored gate is worse than no gate — that is how M3-class errors survive review. Prune the
  vendored trees, but print what was pruned.

**Validated both ways `[LIVE]`:** against a synthetic tree with five planted paths
(`.credentials.json`, `backups/.claude.json.backup.<epoch>`, `history.jsonl`, `server_keys/`,
`deploy.pem`) it reported 5/5 and exited 40; against the real sealed checkpoint it exits 0 and
reports five vendored subtrees (`plugins/marketplaces`, `scholarly-pdf-acquisition/.venv`, three
`__pycache__`). Before pruning was added, that same checkpoint produced **6 hits, all
false** — four `.npmrc` files inside a cloned plugin marketplace, `certifi/cacert.pem` inside a
bundled `.venv`, and a setuptools test fixture named `downloads/`. Those six are also independent
confirmation that `plugins/` bytes and the 338 MB `scholarly-pdf-acquisition` `.venv` were staged
wholesale — exactly the §3.2 problem, found by the secrets gate rather than by the inventory gate.

Also assert the positive shape:

```bash
test "$(find "$STAGE/claude/projects" -maxdepth 2 -name '*.jsonl' | wc -l)" -eq 1
test -d "$STAGE/claude/tasks/$SESSION" && test "$(ls -1 "$STAGE/claude/tasks" | wc -l)" -eq 1
find "$STAGE" -name '*.jsonl' -newer "$STAGE/.start" -print   # nothing unexpected appeared
```

### 4.2 Manifests and logs leak too

The SHA-256 manifests (`manifest/remote-claude.sha256`, `manifest/local-claude.sha256`) and the
rsync logs record **paths and hashes** of everything transferred. If over-collection happened, those
files enumerate the leaked paths, and a SHA-256 of a 322-byte credential file is a tractable offline
target. Remediation must purge the manifest and log lines and regenerate, not just delete the
payload (§5.2 step 4).

---

## 5. Remediation when over-collection has already happened

Assume it has. In the reference run it had, and the checkpoint is clean today `[LIVE]` — `backups/`,
`history.jsonl` and the two foreign `tasks/` stores are absent from
`_backups/mac1/latest/claude/`, and `tasks/` contains exactly one entry, the target SID. That state
was reached by the procedure below.

### 5.1 Order of operations

**Rotation first, deletion second.** Deletion is best-effort; rotation is definitive. Tell the user
what was exposed, on which host, and let them decide. Do not rotate anything yourself — that is a
credential operation you may not perform.

### 5.2 The five steps

**Step 1 — enumerate without opening.**

```bash
find "$CKPT" \( -name '.credentials.json' -o -name '.claude.json*' -o -name 'history.jsonl' \
   -o -path '*/backups/*' -o -path '*/telemetry/*' -o -path '*/sessions/*' \) -type f \
   -exec ls -l {} +      # sizes and modes only — never cat, never hash
```

**Step 2 — find every hardlinked twin.** This is the step people miss. Checkpoints are pulled with
`--link-dest`, so one over-collected file exists as a **hardlink in every prior generation**.
Deleting one path leaves the content live in the others. Conversely, *overwriting* one path
rewrites the shared inode in all of them — which for a secret is what you want, but it also means
you must know exactly which generations you are touching.

```bash
# list the inode's other names (POSIX-ish; works on macOS and Linux)
f="$CKPT/claude/backups/.claude.json.backup.1785582592474"
ino=$(ls -i "$f" | awk '{print $1}')
find "$BACKUPS_ROOT" -xdev -inum "$ino" -print
```

Sealed checkpoints are `chmod -R a-w`; `chmod u+w` the specific paths first, then delete, then leave
them deleted (do not restore the mode on a path that no longer exists).

**Step 3 — overwrite then unlink, with an honest caveat.**

```bash
# Linux (coreutils)
shred -u -n 3 -z "$f"
# macOS: no shred. Prefer GNU coreutils if present, else BSD rm -P, else plain rm.
command -v gshred >/dev/null && gshred -u -n 3 -z "$f" || rm -P "$f" 2>/dev/null || rm -f "$f"
```

> **`shred` does not guarantee anything on the filesystems in play.** It overwrites the *logical*
> blocks; APFS is copy-on-write, ext4 is journaled, and SSD wear-levelling relocates writes. Prior
> versions can survive in snapshots, in the journal, and in unmapped flash `[I]`. Treat overwriting
> as hygiene, and treat **rotation of the exposed credential as the actual remediation**. Say this
> plainly to the user rather than implying the file is gone.

Also remember `--link-dest` again: after unlinking your copy, run step 2's `find -inum` once more
and confirm the link count is what you expect.

**Step 4 — purge the derived records.** Delete or filter the manifest and log lines naming the
purged paths, then **regenerate the manifests from the cleaned tree** so the coverage/fidelity gates
still pass honestly:

```bash
grep -v -F -f <(printf '%s\n' "${purged_relpaths[@]}") manifest/local-claude.sha256 > tmp && mv tmp manifest/local-claude.sha256
grep -v -F -f <(printf '%s\n' "${purged_relpaths[@]}") logs/rsync-claude.log > tmp && mv tmp logs/rsync-claude.log
```

Then re-run the pull's remote-manifest step with the **corrected whitelist** so the remote and local
manifests are once again generated from the same (narrower) definition. A diff against the old
remote manifest will otherwise report every purged file as a coverage failure — which is correct
behaviour, and the reason the remote manifest must be regenerated, not edited.

**Step 5 — re-pull with the whitelist, and re-assert.**

```bash
./scripts/pull-checkpoint.sh          # corrected CLAUDE_PATHS, no include-globs
python3 ./scripts/denylist-assert.py "$NEWCKPT/claude" "$NEWCKPT/project"   # must print "clean"
```

The re-pull is cheap: with `--link-dest` against the previous generation, a marginal checkpoint is
~250–450 MiB `[M]`.

**Step 6 — sweep the transcript for credential shapes.** If a credential file was ever `cat`'d
during the session, the content is in the 216 MB transcript and **cannot be removed** (§1). Detect
it by shape, **counting only**:

```bash
LC_ALL=C grep -a -c \
  -e 'sk-ant-[A-Za-z0-9_-]\{20,\}' \
  -e 'gh[pousr]_[A-Za-z0-9]\{30,\}' \
  -e '-----BEGIN [A-Z ]*PRIVATE KEY-----' \
  -e 'AKIA[0-9A-Z]\{16\}' \
  -e '"refreshToken"' \
  "$TX"
```

Three mechanical notes, each of which bit during validation `[LIVE]`:

- **Use `-e` for every pattern.** `-----BEGIN …` starts with dashes; passed positionally it is eaten
  as an option (`grep: unrecognized option`) and the check silently becomes a usage error — an M7
  false PASS in miniature.
- **Use `-a`.** Without it, grep may classify a 216 MB JSONL as binary. Confirm the scan was
  complete by asserting `grep -a -c '' "$TX"` equals the known line count (47,088 for the reference
  file) — again, prove the check executed.
- **It is cheap.** 216,236,906 B scans in ~0.04 s warm; there is no excuse for skipping it.

**Triage by structure, never by content.** A non-zero count is not a verdict. Resolve it by
extracting only the *metadata* of the matching records — tool name, `filePath`, record type — and
never the matched text:

```bash
LC_ALL=C grep -a -e '-----BEGIN [A-Z ]*PRIVATE KEY-----' "$TX" \
| python3 -c '
import json,sys,collections
paths, types = collections.Counter(), collections.Counter()
for ln in sys.stdin:
    d = json.loads(ln); types[d.get("type")] += 1
    tur = d.get("toolUseResult"); p = None
    if isinstance(tur, dict):
        p = tur.get("filePath") or (tur.get("file") or {}).get("filePath")
    c = (d.get("message") or {}).get("content")
    if isinstance(c, list):
        for b in c:
            if b.get("type") == "tool_use":
                p = p or b.get("input", {}).get("file_path")
    paths[p] += 1
print("record types:", dict(types)); print("paths:", dict(paths))'
```

**Measured result on the reference transcript `[LIVE]` — a worked example of the whole rule:**

| Pattern | Hits | Verdict |
|---|---:|---|
| `sk-ant-…` | **0** | clean |
| `gh[pousr]_…` | **0** | clean |
| `"refreshToken"` | **0** | clean |
| `AKIA[0-9A-Z]{16}` | **7** (7 records) | all in **one** file |
| `-----BEGIN RSA PRIVATE KEY-----` | **8** (6 records) | all in the **same** file |

Structural triage resolved all 15 in one command, with nothing printed: every one is in
`…/DevIO/acmeorg_devio/python/tests/test_secscan.py` — a **secret-scanner's own test fixtures** —
reached through `Write` / `Edit` / `tool_result` records on 2026-06-23. Synthetic bait, not
credentials. Word-boundary anchoring (`(^|[^A-Za-z0-9+/])AKIA…`) still returned 7, so these are not
base64-interior accidents either; and 0 of the matching records carry a `"signature"` field, ruling
out thinking-block base64 as the source.

Two lessons from that: a credential-shape sweep on a real transcript **will** be non-zero, and the
resolution path must be structural, because the one thing you may not do is look at the match.

Note also what the sweep confirms about the account boundary: the reference transcript contains
**no `sk-ant-` token anywhere** and no `accountUuid`/`organizationUuid` keys at all `[M]` — the
cross-account problem is a **placement** problem, not a content problem. Verify that for your own
run rather than assuming it.

If triage does *not* clear the hits, it is a **user decision**, not something you fix: report the
count, the record types and the file paths, state plainly that the transcript cannot be edited, and
recommend rotation.

---

## 6. The assistant's own conduct rule (and the clause that has to be retracted)

### 6.1 The rules

1. **Never read a credential-bearing file.** No `cat`, `head`, `tail`, `jq`, `grep`, `python -c
   'json.load'`, no editor, no `Read` tool. `stat`, `ls -l`, `wc -c` and "shape only" derivations
   that replace every string value with its length are acceptable — that is how
   `.credentials.json`'s three-field structure was documented without its values ever existing in
   the transcript `[M]`.
2. **Never print or log one.** Not even partially, not even redacted-looking. A prefix is still a
   prefix.
3. **Never checksum one.** A hash of a 322-byte file with a known JSON skeleton is a search
   problem, not a one-way function. It also puts a stable identifier for that exact credential into
   a permanent record.
4. **Never accept a credential in chat.** If the user pastes a password, token, or key: do not use
   it, do not echo it, tell them it is now in the transcript, and recommend rotation. Ask them to
   use one of the §7 mechanisms instead.
5. **Never type a credential into a prompt, form, or field**, and never create accounts or
   authenticate on the user's behalf.
6. **Where a credential-bearing file is unavoidably inside a whole-tree copy** (a project directory
   the user has asked you to migrate in full), copy it **byte-wise, without opening it** — `rsync`
   / `cp` move bytes without them entering your context. Then record it in `SENSITIVE.txt` (§8) so
   the user knows it travelled.

### 6.2 The retraction

The reference session's `askpass-setup.md` said:

> "…where they must be copied for fidelity, they're copied byte-wise without being opened."

That sentence is true and **it is the reasoning that produced M3.** "I am not reading it, therefore
copying it is safe" is a non-sequitur: the harm of `backups/` was not that anyone read it — nobody
did — it was that five copies of another account's identity blob **moved to a second host**. The
plan's own remediation list makes the retraction explicit (P0.9: *"retracting the 'copied byte-wise
without being opened' clause… that clause is the reasoning that produced P0.4"*) `[M]`.

**Corrected form — two independent rules, in this order:**

> **(a) Do not collect it.** Credential-bearing files are excluded by the whitelist and re-checked
> by the denylist assertion. The default is that they do not move.
> **(b) If (a) is genuinely impossible** — the file is interior to a tree the user has asked to be
> migrated whole — copy it byte-wise without opening it, and declare it in `SENSITIVE.txt`.
>
> Rule (b) is a **fallback for rule (a)**, never a justification for it. Rule (b) never applies to
> anything under `~/.claude`, `~/.claude.json`, or a Desktop user-data-dir: for those, (a) is always
> possible, because §2 enumerates them completely.

---

## 7. Credentials for privileged remote operations

Source: `scripts/askpass-setup.md`. The reference migration needed **no `sudo` at all** — SSH,
reading `~/.claude`, reading `~/Projects` and the rsync pull all worked as the unprivileged origin
user with an existing key `[M]`. Start from "not needed" and make anything else justify itself.

If a genuinely privileged origin-side operation does come up, four options, best first. In all four
the password lands in the kernel, the keychain, or a process's stdin — never in the assistant's
context, never in a file the assistant reads, never in shell history, never in the transcript.

| # | Option | Mechanism | Trade-off |
|---|---|---|---|
| **1** | **Scoped passwordless sudo** — *recommended* | User runs `sudo visudo -f /etc/sudoers.d/claude-transporter` in **their own** terminal and adds one line scoped to one binary, e.g. `jamiedoe ALL=(root) NOPASSWD: /usr/sbin/tcpdump` | **Nothing is transmitted at all.** Revocable by deleting one file. Scoped to a named binary. Requires the user to have sudo and to act once. Quote the exact command string you want authorised *before* they add it, and accept "no". |
| 2 | `SSH_ASKPASS` / `SUDO_ASKPASS` handoff | User creates `~/.private/askpass.sh` (0700) that `cat`s `~/.private/.p` (0600), and writes the password there with `read -rs` in **their own** terminal. Assistant then runs `ssh host 'SUDO_ASKPASS=$HOME/.private/askpass.sh sudo -A <cmd>'` | Works for many commands without re-prompting. **Puts a plaintext password on the origin's disk** for the duration. Requires an explicit commitment — never read, `cat`, checksum, or run any command whose output could contain that file — and an explicit teardown (`shred -u ~/.private/.p`, with §5.2's caveat). |
| 3 | macOS Keychain | `security add-generic-password -a "$USER" -s claude-transporter -w` (prompts interactively, stores encrypted in the login keychain), then `ssh host 'security find-generic-password -a "$USER" -s claude-transporter -w \| sudo -S <cmd>'` | **No plaintext on disk.** But a non-interactive SSH session usually cannot unlock the login keychain, so it needs the keychain already unlocked by a GUI login — reliable when the user is sitting at the machine, unreliable otherwise. macOS-only. |
| 4 | User runs it, assistant reads the output | Assistant supplies the exact command; user pastes it into their terminal and pastes the output back | **Zero trust required**, works everywhere. Best for genuine one-offs. Does not scale past a handful of commands and blocks on a human. |

**Recommendation: do nothing until sudo is actually required, then use Option 1 scoped to exactly
the command needed.** If Option 1 is unavailable and the operation is a one-off, use Option 4. Reach
for Option 2 only for a burst of privileged commands, and only with the teardown scheduled in the
same message that sets it up.

**Never, under any option:** type a password into a prompt/form/field; store one in a shell
variable, a script, or a file the assistant has read; pass one on a command line (it lands in `ps`
and in history); or read `.credentials.json`, `oauth:tokenCache` values, `~/.config/gh/hosts.yml`
tokens, or key material.

---

## 8. Project-side secrets

The `~/.claude` side is enumerable. The **project tree** is not — it is whatever the user has been
working on, and in the reference run it contained live key material.

### 8.1 What was actually there

| Path | Measured | Hazard |
|---|---|---|
| `_research/re/server_keys/host_rsa.key` | 1,679 B | probable live demo-server host key |
| `_research/re/captures/` | 78 MB, ~500 files, dir `0755` / files `0644`, inside a `0775` chain | packet captures of an SSH channel in which — per the project's own reverse-engineering finding — the **FASP session AES key travels in cleartext** `[M]` |
| `_research/re/target/` | 7 files, ~209 MB incl. `aspera-license` (1,627 B) | vendor licence blob; also the irreplaceable ground-truth oracle — **do not exclude it**, see the M1/F8 trap |
| flagged by the sweep | **741 paths**, of which only **500** were recorded `[LIVE]` | `*.key`, `*.pem`, `id_*`, `*license*`, anything under `server_keys/` or `captures/` — see §8.3, the inventory was silently truncated |

Both key-material directories sat **inside a tree earmarked for `git init`**, at world-readable
modes.

### 8.2 The rule: `.gitignore` before the first `git add -A`

This is an ordering rule, and the order is the whole rule. `git add -A` on a tree containing a
plaintext credential writes that credential into an object that survives `git rm`, survives
`--amend`, and is trivially recoverable from any clone.

**Sequence, no steps reordered:**

1. `chmod -R go-rwx` the backup/checkpoint root. (It was `0775` `[M]`.)
2. `mkdir -m 700 <project>/_transporter/quarantine` and **move** `captures/`, `server_keys/` and any
   other confirmed key material into it, **outside** any git-initializable path.
3. `touch quarantine/CONTAINS_SECRETS` — a sentinel that archive, git, and artifact code paths
   check for and refuse on.
4. **Write `.gitignore` — this is the first write of any git operation, before `git init`, before
   `git add`, before `git status`.** Minimum contents for this shape of tree:
   `_backups/`, `_transporter/quarantine/`, `_transporter/cas/`, `_transporter/runs/`,
   `_transporter/mnt/`, plus every path in `SENSITIVE.txt` that remains in-tree.
5. `git config gc.auto 0 && git config gc.autoDetach false` — a rescued repo may have dangling
   objects that are one porcelain command from deletion (427 of them, in the reference run `[M]`).
   Prefer `git --no-optional-locks status --porcelain`; plain `git status` can rewrite `.git/index`.
6. Only now `git init` / `git add -A`.
7. After the first commit, `git log --stat -1` and confirm nothing from `SENSITIVE.txt` appears.

If step 6 has already happened before you arrived: **do not try to clean the history yourself.**
Report which paths are in which objects, and treat the exposed credentials as compromised —
rotation, again, is the real fix.

### 8.3 `SENSITIVE.txt` — the checkpoint's own inventory

The pull produces it, from filenames only, without opening anything:

```bash
{ echo "# Sensitive paths present in this checkpoint — gitignore, never commit."
  find "$DEST/project" \( -path '*/server_keys/*' -o -path '*/captures/*' \
       -o -name '*.key' -o -name '*.pem' -o -name 'id_*' -o -name '*license*' \) \
       -type f 2>/dev/null | sed "s|$DEST/||" | head -500
} > "$DEST/manifest/SENSITIVE.txt"
```

Extend the predicate for your own tree — worthwhile additions seen in adjacent corpora `[M]`:
`*.p12`, `*.pfx`, `*.jks`, `*.keystore`, `*secrets*.env`, `*credentials*.txt`, `*.ovpn`,
`.env`, `.env.*`, `id_rsa*`, `id_ed25519*`, `*.ppk`, `known_hosts` is fine, `authorized_keys` is not.

Three properties to preserve:

- **Filenames only, never contents.** It is an inventory, not a scanner.
- **It is an input to the `.gitignore`**, not just a report. If it lists a path, that path is either
  quarantined or gitignored before commit #1.
- **`head -500` truncates, and in the reference run it truncated.** The same `find` without the cap
  returns **741** matches; `SENSITIVE.txt` records **500** `[LIVE]`. **241 flagged paths are absent
  from the inventory that the `.gitignore` is built from** — silently, because the file looks full
  and complete. This is the M2 pattern in a new place: a gate that reports a healthy-looking number
  while under-reporting the thing it exists to count.

  Fix: drop the cap, or keep it and print the untruncated count beside it, and fail the gate when
  they differ.

  ```bash
  RAW=$(find "$DEST/project" \( … \) -type f 2>/dev/null | wc -l)
  KEPT=$(( $(wc -l < "$DEST/manifest/SENSITIVE.txt") - 1 ))
  [ "$RAW" -ne "$KEPT" ] && echo "SENSITIVE.txt TRUNCATED: $KEPT of $RAW recorded" && exit 41
  ```

### 8.4 Ask, then record

Secrets disposition is a **user decision**, and it should be asked once, explicitly, with the
options laid out:

> (a) keep quarantined at 0700 on this host, (b) keep only on the origin and fetch on demand,
> (c) encrypted archive to external media.

Default in the reference run: **(a), with `CONTAINS_SECRETS` set** `[M]`. Also ask separately
whether the exposed credentials should be **rotated** — for anything that rode in the transcript,
recommend yes, because the transcript cannot be edited.

---

## 9. Gate checklist

Run these; each must be an explicit pass, and each must first prove it actually executed (the M7
rule: absence of an error is not evidence of success).

| # | Gate | Command / assertion | Pass |
|---|---|---|---|
| S1 | Whitelist is path-explicit | no `--include=` glob with `***`; no bare `tasks`, no bare `backups` | grep the pull script |
| S2 | One transcript staged | `find "$STAGE/claude/projects" -maxdepth 2 -name '*.jsonl' \| wc -l` | `== 1`, named `$SESSION.jsonl` |
| S3 | One task store staged | `ls -1 "$STAGE/claude/tasks" \| wc -l` | `== 1`, named `$SESSION` |
| S4 | Denylist assertion, staged bytes | `python3 scripts/denylist-assert.py "$STAGE/claude" "$STAGE/project"` | prints `denylist clean`, exit 0 |
| S5 | Denylist assertion, **existing** checkpoints | same, over every generation under the backups root | exit 0 everywhere |
| S6 | No user-data-dir file staged except the session JSON | `find "$STAGE" -path '*/claude-code-sessions/*' -prune -o -name 'config.json' -print` etc. | empty |
| S7 | Transcript credential-shape sweep | §5.2 step 6, `-a -c -e …`, plus `grep -a -c ''` == known line count | count reported; each hit triaged **structurally**; anything uncleared ⇒ rotation recommendation |
| S8 | `SENSITIVE.txt` complete, not truncated | `wc -l manifest/SENSITIVE.txt` vs the uncapped `find \| wc -l` | **equal**; unequal ⇒ exit 41 (reference run: 500 vs 741) |
| S9 | `.gitignore` precedes `git init` | `git log --diff-filter=A --format= --name-only \| grep -x .gitignore` present in commit #1, or no repo yet | pass |
| S10 | Quarantine mode | `stat -c '%a' quarantine` (Linux) / `stat -f '%A' quarantine` (macOS) | `700`, `CONTAINS_SECRETS` present |
| S11 | Nothing secret was read | no `Read`/`cat`/`jq`/hash of any §2 path anywhere in this run | self-audit before declaring done |
| S12 | Manifests regenerated after any purge | remote manifest re-derived from the corrected whitelist, not hand-edited | DIFF files 0 bytes |

**Advertisable property when all twelve pass:** *"the whitelist is enumerable and short; the
denylist assertion runs over the staged bytes independently; nothing secret was collected, read, or
hashed."*
