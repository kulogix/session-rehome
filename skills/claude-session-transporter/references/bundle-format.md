# claude-session-bundle/1

A zip file (deflate, zip64) that Python's stdlib reads on every OS. Suggested extension: `.csb.zip`.

```
manifest.json                                   the contract (below); not itself listed in members
payload/claude/projects/<KEY>/<SID>.jsonl       transcript: byte-exact PREFIX snapshot (prefix_len bytes)
payload/claude/projects/<KEY>/<SID>/...         sidecars: subagents/, tool-results/, workflows/, custom-title.json
payload/claude/projects/<KEY>/memory/...        project memory (absent when no_memory)
payload/claude/projects/<SIBLING>/<SID>/...     sibling project keys' data for this session (worktrees)
payload/claude/tasks/<SID>/...                  the session's task store
payload/project/...                             project tree minus excludes and secret-looking files
record/record.json                              optional: the Desktop record as ccd-record/1 (claude-desktop-rehome)
```

`payload/` is exactly a st-checkpoint.sh generation's `claude/` + `project/`. `import` extracts it, adds
`PROVENANCE`, `COMPLETE`, `manifest/transcript-sha256.txt`, `manifest/transcript-prefix-len.txt`,
`manifest/local-project.tsv` and `manifest/bundle-manifest.json`, then runs st-transplant.py against it.

## manifest.json

| key | meaning |
|---|---|
| `format` | `claude-session-bundle/1` (import refuses anything else) |
| `tool`, `created_utc` | producer and time (UTC `%Y%m%dT%H%M%SZ`) |
| `session` | `{id, title}` |
| `origin` | `{os, arch, claude_home, project_root, key, siblings, cli_versions: {version: records}, desktop}` |
| `transcript` | `{path, prefix_len, sha256}`: the provable property (dest first prefix_len bytes hash to sha256) |
| `members` | `[{path, size, sha256}]`: every file except manifest.json; nothing more, nothing less |
| `excludes` | `[{pattern, why, unanchored, files, bytes}]`: the accounting, as in st-checkpoint.sh |
| `sensitive_left_out`, `symlinks_left_out` | project paths deliberately not packed |
| `transcript_secret_hits` | `{kind: count}`: secret-looking strings inside the (uneditable) transcript |
| `hazards` | NFC/casefold collisions, NFD names, names Windows cannot store |
| `no_memory` | the project memory was deliberately left out |
| `record` | `record/record.json` or null |

## Verification rules (inspect and import)

1. Every member name is relative, uses `/`, and has no `..` and no drive letter (zip-slip guard).
2. The set of zip members equals `members` ∪ {manifest.json}: extra or missing members are refused.
3. Every member re-hashes to its sha256 and size. The transcript entry matches `transcript.sha256`.
4. Import re-hashes each file after extraction.

## st-origin-proof/1 (made on the origin by `st-bundle.py origin-proof`)

`{format, session_id, prefix_len, prefix_sha256, size_now, found, created_utc, bundle_created_utc}`.
`st-verify.sh --origin-proof` accepts it only when `session_id` and `prefix_len` match the checkpoint, and
passes only when `prefix_sha256` equals the checkpoint transcript's hash. If `size_now > prefix_len`, the
session was resumed on the origin after export (the histories fork; a write-back is illegal).

## Measured (2026-11-07)

- **The round trip:** a real 929,178-byte session (64 MB of sidecars, Desktop record, 3 project files)
  was exported on Linux x86_64 (CLI 2.1.295), imported on macOS 26.6 arm64 (Python 3.9.6, openrsync)
  and on Debian 13 aarch64, and **LOADED by each host's own CLI** (2.1.119 and 2.1.121) in the
  isolated dead-port probe. `st-verify.sh`: PASS on both, origin proven unchanged through
  `--origin-proof`.
- **Not yet measured:** a real Windows host; cross-ORG signature acceptance.
