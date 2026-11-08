#!/usr/bin/env bash
# st-verify.sh — G8. Prove that a transplanted session is intact, loadable, and that the
# origin was never touched.
#
# Every check here is written so that it first asserts THE THING IT CHECKS ACTUALLY RAN.
# A grep for signature errors once "passed" because the run had died earlier at "Not
# logged in" and never reached the API. Absence of an error is not evidence of success:
# the load probe's PASS signal is therefore the PRESENCE of a positive event that can
# only happen after the transcript has been fully parsed and replayed.
#
# The load probe costs ZERO API tokens: ANTHROPIC_BASE_URL points at a dead port, so the
# CLI does all of its transcript loading and only then fails on the first network call.
#
# By default the probe runs against an ISOLATED CLAUDE_CONFIG_DIR holding a COPY of the
# transcript, so the live file is not appended to. That still proves what matters: the
# project-dir name is computed by the CLI itself from the launch directory, so if the CLI
# finds our copy under our computed key, our key is the CLI's key for that cwd — and the
# live file is asserted to exist, be non-empty and be readable at exactly that key.
#
# The isolation is complete: CLAUDE_CONFIG_DIR relocates `.claude.json` as well (measured —
# the rig grows its own cfg/.claude.json, cfg/sessions/, cfg/backups/, cfg/.last-cleanup,
# and the real ~/.claude.json is not touched, mtime unchanged). The rig is therefore also
# SEEDED with an onboarding + workspace-trust config, so the probe does not stop at a
# first-run gate and get misread as a placement failure.
set -uo pipefail

ST_SELF="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=st-common.sh
. "$ST_SELF/st-common.sh"

usage() {
  cat <<'EOF'
st-verify.sh — postflight proof for a transplanted session.

  --profile FILE        shell file presetting ST_* variables (FLAGS WIN)
  --dest-root PATH      destination project root (the launch cwd)
  --session-id UUID     transcript stem
  --claude-home PATH    destination ~/.claude (default $HOME/.claude)
  --checkpoint DIR      the sealed checkpoint the transplant came from
  --user-data-dir PATH  Desktop instance dir  (optional)
  --account UUID        destination accountUuid (optional)
  --org UUID            destination organizationUuid (optional)
  --cli PATH            claude binary to probe with (auto-detected if omitted)
  --origin-host HOST    if given, re-prove the origin is unchanged (read-only)
  --origin-claude PATH  origin ~/.claude
  --origin-key KEY      origin project key
  --origin-proof FILE   a proof made ON the origin by `st-bundle.py origin-proof` (when this host cannot reach
                        the origin: push migrations, air-gapped hosts)
  --skill NAME          assert this skill is installed at the destination (repeatable).
                        Default: whatever st-transplant.py recorded in .st-receipt.json,
                        falling back to every skill in the checkpoint.
  --no-probe            skip the CLI load probe (it copies the transcript and takes minutes)
  --allow-live-probe    probe against the LIVE config dir instead of an isolated copy.
                        This APPENDS to the live transcript. Off by default.
  --rig-credentials     byte-copy the destination's .credentials.json into the isolated
                        rig so the probe can authenticate. The file is never opened, read,
                        printed or hashed, and the rig is deleted afterwards. Only needed
                        when the probe reports that it stopped at an auth gate.
  --probe-timeout N     seconds (default 420)
  --no-tree-check       skip the destination project-tree coverage check
  -h | --help
EOF
}

st_preparse_profile "$@"

ST_DEST_ROOT="${ST_DEST_ROOT:-}"; ST_SESSION_ID="${ST_SESSION_ID:-}"
ST_CLAUDE_HOME="${ST_CLAUDE_HOME:-$HOME/.claude}"; ST_CKPT="${ST_CKPT:-}"
ST_USER_DATA_DIR="${ST_USER_DATA_DIR:-}"; ST_ACCOUNT="${ST_ACCOUNT:-}"; ST_ORG="${ST_ORG:-}"
ST_CLI="${ST_CLI:-}"; ST_ORIGIN_HOST="${ST_ORIGIN_HOST:-}"; ORIGIN_PROOF=""
ST_ORIGIN_CLAUDE="${ST_ORIGIN_CLAUDE:-}"; ST_ORIGIN_KEY="${ST_ORIGIN_KEY:-}"
SKILLS=""; NO_PROBE=0; LIVE_PROBE=0; PROBE_TIMEOUT=420; RIG_CREDS=0; NO_TREE=0

while [ $# -gt 0 ]; do
  case "$1" in
    --profile)          shift 2 ;;
    --profile=*)        shift ;;
    --dest-root)        ST_DEST_ROOT="$2"; shift 2 ;;
    --session-id)       ST_SESSION_ID="$2"; shift 2 ;;
    --claude-home)      ST_CLAUDE_HOME="$2"; shift 2 ;;
    --checkpoint)       ST_CKPT="$2"; shift 2 ;;
    --user-data-dir)    ST_USER_DATA_DIR="$2"; shift 2 ;;
    --account)          ST_ACCOUNT="$2"; shift 2 ;;
    --org)              ST_ORG="$2"; shift 2 ;;
    --cli)              ST_CLI="$2"; shift 2 ;;
    --origin-host)      ST_ORIGIN_HOST="$2"; shift 2 ;;
    --origin-claude)    ST_ORIGIN_CLAUDE="$2"; shift 2 ;;
    --origin-key)       ST_ORIGIN_KEY="$2"; shift 2 ;;
    --origin-proof)     ORIGIN_PROOF="$2"; shift 2 ;;
    --skill)            SKILLS="$SKILLS $2"; shift 2 ;;
    --no-probe)         NO_PROBE=1; shift ;;
    --allow-live-probe) LIVE_PROBE=1; shift ;;
    --rig-credentials)  RIG_CREDS=1; shift ;;
    --probe-timeout)    PROBE_TIMEOUT="$2"; shift 2 ;;
    --no-tree-check)    NO_TREE=1; shift ;;
    -h|--help)          usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done
st_need python3
st_require_var ST_DEST_ROOT  --dest-root
st_require_var ST_SESSION_ID --session-id
SID="$ST_SESSION_ID"

# pick up provenance from the checkpoint when available
if [ -n "$ST_CKPT" ] && [ -f "$ST_CKPT/PROVENANCE" ]; then
  [ -z "$ST_ORIGIN_KEY" ]    && ST_ORIGIN_KEY="$(sed -n 's/^origin_key=//p' "$ST_CKPT/PROVENANCE")"
  [ -z "$ST_ORIGIN_CLAUDE" ] && ST_ORIGIN_CLAUDE="$(sed -n 's/^origin_claude=//p' "$ST_CKPT/PROVENANCE")"
  [ -z "$ST_ORIGIN_HOST" ]   && ST_ORIGIN_HOST="$(sed -n 's/^origin_host=//p' "$ST_CKPT/PROVENANCE")"
  case "$ST_ORIGIN_HOST" in local|bundle) ST_ORIGIN_HOST="" ;; esac   # bundle: prove the origin with --origin-proof
fi

DEST_KEY="$(st_mangle "$ST_DEST_ROOT")" || st_die "mangle failed"
DEST_DIR="$ST_CLAUDE_HOME/projects/$DEST_KEY"
DEST_TX="$DEST_DIR/$SID.jsonl"
RECEIPT="$ST_DEST_ROOT/.st-receipt.json"

st_banner "ST-VERIFY   session $SID"
st_log "destination root  $ST_DEST_ROOT"
st_log "mangled key       $DEST_KEY"
st_log "live transcript   $DEST_TX"

# ------------------------------------------------------------------ 1. placement
st_banner "1  PLACEMENT"
if [ -f "$DEST_TX" ]; then
  SZ=$(st_size "$DEST_TX")
  if [ "$SZ" -gt 0 ]; then
    st_ok "transcript present, $SZ bytes ($(st_human "$SZ"))"
  else
    st_bad "transcript is ZERO BYTES — the resolver skips empty candidates, so this fails identically to a missing file"
  fi
  MODE=$(python3 -c 'import os,stat,sys;print(oct(stat.S_IMODE(os.stat(sys.argv[1]).st_mode)))' "$DEST_TX")
  st_info "mode $MODE (must be writable by the CLI — it appends every turn)"
  [ -w "$DEST_TX" ] && st_ok "transcript is writable" || st_bad "transcript is READ-ONLY — a sealed checkpoint's mode propagated (M6)"
  BASENAME="$(basename "$DEST_TX" .jsonl)"
  [ "$BASENAME" = "$SID" ] && st_ok "filename stem is unchanged — sidecars resolve from it" \
                           || st_bad "filename stem is '$BASENAME', not '$SID' — sidecars are orphaned"
else
  st_bad "no transcript at $DEST_TX"
  st_bad "  resume is cwd-scoped with NO global fallback: the directory name must be exactly"
  st_bad "  mangle(realpath(launch cwd)). If a transcript exists under a NEARBY key, the"
  st_bad "  destination root was resolved differently (a symlinked parent) — do not rename"
  st_bad "  the file, re-run st-transplant.py with the correct --dest-root."
  for near in "$ST_CLAUDE_HOME"/projects/*/"$SID.jsonl"; do
    [ -f "$near" ] || continue
    st_bad "  found the same session id at: $near"
  done
fi

# ------------------------------------------------------------------ 2. prefix identity
st_banner "2  HISTORY UNTOUCHED (prefix byte-identity)"
CKPT_TX=""
if [ -n "$ST_CKPT" ] && [ -n "$ST_ORIGIN_KEY" ]; then
  CKPT_TX="$ST_CKPT/claude/projects/$ST_ORIGIN_KEY/$SID.jsonl"
fi
if [ -n "$CKPT_TX" ] && [ -f "$CKPT_TX" ] && [ -f "$DEST_TX" ]; then
  N=$(st_size "$CKPT_TX")
  CSHA=$(st_sha256 "$CKPT_TX")
  LSHA=$(st_sha256 "$DEST_TX" "$N" 2>/dev/null)
  if [ -z "$LSHA" ]; then
    st_bad "the live transcript is SHORTER than the checkpoint ($(st_size "$DEST_TX") < $N) — a byte-count DECREASE means a stripping import path ran. Halt and restore."
  elif [ "$LSHA" = "$CSHA" ]; then
    st_ok "first $N bytes are byte-identical to the checkpoint"
    st_ok "  sha256 $CSHA"
    GROWN=$(( $(st_size "$DEST_TX") - N ))
    st_ok "  the file has grown by $GROWN bytes since — resume is a pure append, that is expected"
  else
    st_bad "PREFIX MISMATCH — history was modified. Expected $CSHA, got $LSHA."
    st_bad "  Suspect the CLI-session import / claude://resume / recovery UI: all three run"
    st_bad "  stripThinkingBlocksFromFile IN PLACE (measured: 6,331 assistant records deleted)."
  fi
else
  st_skip "prefix byte-identity (need --checkpoint and --origin-key)"
fi

if [ -f "$DEST_TX" ]; then
  LB=$(tail -c 1 "$DEST_TX" | od -An -tx1 | tr -d ' \n')
  [ "$LB" = "0a" ] && st_ok "ends with LF" || st_bad "does not end with LF"
  if tail -n 1 "$DEST_TX" | python3 -c 'import json,sys; json.loads(sys.stdin.readline())' 2>/dev/null; then
    st_ok "last line parses as JSON"
  else
    st_bad "last line does not parse as JSON"
  fi
  while IFS= read -r line; do
    case "$line" in
      "OK "*)   st_ok   "${line#OK }" ;;
      "WARN "*) st_warn "${line#WARN }" ;;
      *) st_info "$line" ;;
    esac
  done < <(python3 - "$DEST_TX" <<'PY'
import json, os, sys
p = sys.argv[1]
size = os.path.getsize(p)
with open(p, 'rb') as f:
    f.seek(max(0, size - 65536))
    tail = f.read().decode('utf-8', 'replace')
print("OK   relocation notice present in the file tail" if "[WORKSPACE RELOCATION NOTICE" in tail
      else "WARN no relocation notice in the last 64 KiB (it may have scrolled out; CLAUDE.md is the durable half)")
print("OK   `relocated` record is inside the 64 KiB reverse-scan window" if '"type":"relocated"' in tail
      else "WARN no `relocated` record in the last 64 KiB — harmless for --resume, but the in-REPL /resume will not chdir")
PY
)
fi

# ------------------------------------------------------------------ 3. sidecars
st_banner "3  SIDECARS, MEMORY, TASKS"
# nd < ns is the failure. nd > ns means the session has been USED since the checkpoint —
# new subagents, new tasks — which is the healthy state. Asserting equality made every
# post-launch run red, and a gate that fails on the normal case teaches operators to
# disbelieve the gates.
cmp_counts() {  # cmp_counts LABEL SRC DST [soft]
  local label="$1" src="$2" dst="$3" soft="${4:-}"
  if [ ! -d "$src" ]; then st_info "$label: nothing in the checkpoint"; return; fi
  if [ ! -d "$dst" ]; then st_bad "$label: MISSING at the destination ($dst)"; return; fi
  local ns nd
  ns=$(find "$src" -type f 2>/dev/null | wc -l | tr -d ' ')
  nd=$(find "$dst" -type f 2>/dev/null | wc -l | tr -d ' ')
  if [ "$ns" -eq "$nd" ]; then
    st_ok "$label: $nd files (matches the checkpoint)"
  elif [ "$nd" -gt "$ns" ]; then
    st_ok "$label: $nd files, checkpoint had $ns — $((nd - ns)) created since; expected on a used session"
  elif [ -n "$soft" ]; then
    st_warn "$label: $nd files, checkpoint had $ns — this store is swept by the destination CLI's own retention pass; a small decrease after the first launch is expected, a large one is not"
  else
    st_bad "$label: $nd files, checkpoint had $ns — something from the checkpoint is missing"
  fi
}
if [ -n "$ST_CKPT" ] && [ -n "$ST_ORIGIN_KEY" ]; then
  SRC_SIDE="$ST_CKPT/claude/projects/$ST_ORIGIN_KEY/$SID"
  cmp_counts "subagents   " "$SRC_SIDE/subagents"    "$DEST_DIR/$SID/subagents"
  cmp_counts "tool-results" "$SRC_SIDE/tool-results" "$DEST_DIR/$SID/tool-results" soft
  cmp_counts "workflows   " "$SRC_SIDE/workflows"    "$DEST_DIR/$SID/workflows"
  cmp_counts "memory      " "$ST_CKPT/claude/projects/$ST_ORIGIN_KEY/memory" "$DEST_DIR/memory"
  cmp_counts "tasks       " "$ST_CKPT/claude/tasks/$SID" "$ST_CLAUDE_HOME/tasks/$SID"
else
  st_skip "sidecar/memory/task count comparison (need --checkpoint and --origin-key)"
fi
SUBA=$(find "$DEST_DIR/$SID/subagents" -name '*.jsonl' 2>/dev/null | wc -l | tr -d ' ')
st_info "subagent transcripts reachable at the destination: $SUBA"
st_info "  (the subagent set CANNOT be reconstructed from the main transcript — most"
st_info "   toolUseIds appear only inside another subagent's file. The directory is the truth.)"

# ------------------------------------------------------------------ 3b. project tree
st_banner "3b  DESTINATION PROJECT TREE (coverage measured at the destination paths)"
if [ "$NO_TREE" -eq 1 ]; then
  st_info "skipped (--no-tree-check)"
elif [ -z "$ST_CKPT" ] || [ ! -s "$ST_CKPT/manifest/local-project.tsv" ]; then
  st_skip "destination project-tree coverage (need --checkpoint with manifest/local-project.tsv)"
elif [ ! -d "$ST_DEST_ROOT" ]; then
  st_bad "destination root does not exist: $ST_DEST_ROOT"
else
  TMPM="$(mktemp "${TMPDIR:-/tmp}/st-destmanifest.XXXXXX")"
  TMPD="$(mktemp "${TMPDIR:-/tmp}/st-destdiff.XXXXXX")"
  python3 "$ST_SELF/st_walk.py" --root "$ST_DEST_ROOT" --jobs 8 > "$TMPM" 2>/dev/null
  python3 "$ST_SELF/st_walk.py" --compare "$ST_CKPT/manifest/local-project.tsv" "$TMPM" \
    --label CHECKPOINT DEST > "$TMPD" 2>&1
  MISS=$(sed -n 's/^  GATE 1  COVERAGE  : \([0-9]*\) .*/\1/p' "$TMPD" | tail -1)
  DIFFN=$(sed -n 's/^  GATE 2  FIDELITY  : \([0-9]*\) .*/\1/p' "$TMPD" | tail -1)
  if [ "${MISS:-1}" -eq 0 ]; then
    st_ok "coverage: every checkpoint file is present at the destination"
  else
    st_bad "coverage: $MISS checkpoint file(s) are MISSING at the destination — a silently"
    st_bad "  truncated rsync passes every other gate in this script"
    grep '^      MISSING' "$TMPD" | head -10 | while IFS= read -r l; do st_log "    $l"; done
  fi
  if [ "${DIFFN:-0}" -eq 0 ]; then
    st_ok "fidelity: every shared path is byte-identical to the checkpoint"
  else
    st_warn "$DIFFN file(s) differ from the checkpoint. On a working destination that is"
    st_warn "  LOCAL WORK and is expected. Confirm it is: the same number would appear if"
    st_warn "  the copy had been corrupted."
    grep '^      DIFFER' "$TMPD" | head -10 | while IFS= read -r l; do st_log "    $l"; done
  fi
  rm -f "$TMPM" "$TMPD"
fi

# ------------------------------------------------------------------ 4. CLAUDE.md
st_banner "4  DURABLE RELOCATION MESSAGE"
CMD="$ST_DEST_ROOT/CLAUDE.md"
if [ -f "$CMD" ]; then
  if grep -q "BEGIN session-transporter relocation notice: $SID" "$CMD" 2>/dev/null; then
    st_ok "CLAUDE.md carries this session's transporter block ($(st_size "$CMD") bytes)"
    st_ok "  this is the half of the message that survives compaction — the appended notice does not"
    NBLOCK=$(grep -c 'BEGIN session-transporter relocation notice' "$CMD")
    [ "$NBLOCK" -gt 1 ] && st_info "  $NBLOCK sessions have been migrated into this root; each keeps its own block"
  elif grep -q 'BEGIN session-transporter relocation notice' "$CMD" 2>/dev/null; then
    st_bad "CLAUDE.md has a transporter block, but not one for $SID"
  else
    st_bad "CLAUDE.md exists but has no transporter block"
  fi
else
  st_bad "no CLAUDE.md at $CMD — after the first compaction the model will have no record of the move"
fi

# ------------------------------------------------------------------ 5. shared assets
st_banner "5  SHARED ASSETS INSTALLED AT THE DESTINATION (not merely backed up)"
# What SHOULD be installed is what st-transplant.py says it installed, not everything the
# checkpoint happens to contain: --skill / --no-skills install a deliberate subset, and
# reporting the rest as FAIL is a red gate for correct behaviour.
if [ -z "$SKILLS" ] && [ -f "$RECEIPT" ]; then
  SKILLS="$(python3 -c '
import json,sys
try:
    print(" ".join(json.load(open(sys.argv[1])).get("skills") or []))
except Exception:
    pass' "$RECEIPT")"
  st_info "skill list taken from $RECEIPT (what the transplant actually installed)"
  [ -z "$SKILLS" ] && st_info "  the receipt records no skills — none were meant to be installed"
  RECEIPT_USED=1
fi
if [ -z "$SKILLS" ] && [ -z "${RECEIPT_USED:-}" ] && [ -n "$ST_CKPT" ] && [ -d "$ST_CKPT/claude/skills" ]; then
  SKILLS="$(ls -1 "$ST_CKPT/claude/skills" 2>/dev/null | tr '\n' ' ')"
  st_warn "no $RECEIPT — falling back to every skill in the checkpoint. If the transplant"
  st_warn "  installed a deliberate subset, the extra rows below are not real failures."
fi
if [ -n "$SKILLS" ]; then
  for s in $SKILLS; do
    if [ -d "$ST_CLAUDE_HOME/skills/$s" ]; then
      NS=$(find "$ST_CLAUDE_HOME/skills/$s" -type f 2>/dev/null | wc -l | tr -d ' ')
      if [ -n "$ST_CKPT" ] && [ -d "$ST_CKPT/claude/skills/$s" ]; then
        NC=$(find "$ST_CKPT/claude/skills/$s" -type f 2>/dev/null | wc -l | tr -d ' ')
        [ "$NS" -ge "$NC" ] && st_ok "skill $s installed ($NS files, checkpoint $NC)" \
                            || st_bad "skill $s incomplete: $NS files at the destination, $NC in the checkpoint"
      else
        st_ok "skill $s installed ($NS files)"
      fi
    else
      st_bad "skill $s is NOT installed at $ST_CLAUDE_HOME/skills/$s — backed up is not installed (M4)"
    fi
  done
else
  st_info "no skills to check"
fi
st_info "skills are enumerated at CLI process STARTUP and cached for the process lifetime:"
st_info "  anything installed after the destination launches will not be visible to it"

# ------------------------------------------------------------------ 6. desktop
st_banner "6  DESKTOP SESSION REGISTERED"
if [ -n "$ST_USER_DATA_DIR" ] && [ -n "$ST_ACCOUNT" ] && [ -n "$ST_ORG" ]; then
  SDIR="$ST_USER_DATA_DIR/claude-code-sessions/$ST_ACCOUNT/$ST_ORG"
  if [ -d "$SDIR" ]; then
    while IFS= read -r line; do
      case "$line" in
        "OK "*)   st_ok   "${line#OK }" ;;
        "WARN "*) st_warn "${line#WARN }" ;;
        "FAIL "*) st_bad  "${line#FAIL }" ;;
        *) st_info "$line" ;;
      esac
    done < <(python3 - "$SDIR" "$SID" "$ST_DEST_ROOT" <<'PY'
import json, os, stat, sys
sdir, sid, dest = sys.argv[1], sys.argv[2], sys.argv[3]
found = []
for fn in sorted(os.listdir(sdir)):
    if not (fn.startswith("local_") and fn.endswith(".json")):
        continue
    p = os.path.join(sdir, fn)
    try:
        d = json.load(open(p))
    except Exception as e:
        print("FAIL %s does not parse: %s (the loader skips it silently)" % (fn, e)); continue
    if d.get("cliSessionId") != sid:
        continue
    found.append(fn)
    print("OK   %s registers cliSessionId %s" % (fn, sid))
    if d.get("sessionId") != fn[:-5]:
        print("FAIL filename stem '%s' != sessionId field '%s' — it will load under the field "
              "value and be rewritten, leaving a ghost file that reloads every launch"
              % (fn[:-5], d.get("sessionId")))
    else:
        print("OK   filename stem == sessionId field")
    for k in ("sessionId", "cwd", "cliSessionId"):
        if not d.get(k):
            print("FAIL required key '%s' is missing/empty" % k)
    if d.get("cwd") != dest:
        print("WARN cwd is '%s', expected '%s'" % (d.get("cwd"), dest))
    else:
        print("OK   cwd matches the destination root")
    sz = os.path.getsize(p)
    print("OK   %d bytes (limit 10 MiB)" % sz if sz < (10 << 20) else "FAIL %d bytes exceeds the 10 MiB load limit" % sz)
    m = stat.S_IMODE(os.stat(p).st_mode)
    print("OK   file mode %s" % oct(m) if m == 0o600 else "WARN file mode %s (expected 0600)" % oct(m))
    if d.get("completedTurns"):
        print("OK   the app has run %s turn(s) from this session already" % d["completedTurns"])
if not found:
    print("FAIL no session file in this account/org dir references %s." % sid)
    print("FAIL a session placed under a NON-matching account/org pair is never read, AND it "
          "suppresses its transcript from the correct account's recovery UI")
if len(found) > 1:
    print("FAIL %d files claim the same cliSessionId — duplicates are silently dropped on load" % len(found))
# every level, not only the leaf: os.makedirs(p, mode) applies the mode to the leaf alone
d = sdir
for _ in range(3):
    m = stat.S_IMODE(os.stat(d).st_mode)
    print("OK   dir mode %s on %s" % (oct(m), os.path.basename(d)) if m == 0o700
          else "WARN dir mode %s on %s (expected 0700)" % (oct(m), os.path.basename(d)))
    d = os.path.dirname(d)
PY
)
  else
    st_bad "no such directory: $SDIR"
  fi
else
  st_info "skipped (no --user-data-dir/--account/--org) — this is a CLI-ONLY migration and"
  st_info "  needs none of it: G7 is 'cd $ST_DEST_ROOT && claude --resume=$SID'"
fi

# ------------------------------------------------------------------ 7. load probe
st_banner "7  CLI LOAD PROBE (zero API tokens: dead port under a timeout)"
if [ -z "$ST_CLI" ]; then
  ST_CLI="$(command -v claude 2>/dev/null)"
  if [ -z "$ST_CLI" ]; then
    for c in "$HOME"/.claude-instances/*/claude-code/*/claude "$HOME"/.local/share/claude-code/*/claude; do
      [ -x "$c" ] && ST_CLI="$c"
    done
  fi
fi
if [ "$NO_PROBE" -eq 1 ]; then
  st_skip "CLI load probe (--no-probe). Placement is UNPROVEN without it."
elif [ -z "$ST_CLI" ] || [ ! -x "$ST_CLI" ]; then
  st_skip "CLI load probe (no claude binary; pass --cli)"
elif [ ! -f "$DEST_TX" ]; then
  st_skip "CLI load probe (no transcript to load)"
else
  RIG=""; PROBE_TX="$DEST_TX"; PROBE_CFG="$ST_CLAUDE_HOME"
  if [ "$LIVE_PROBE" -eq 1 ]; then
    st_warn "--allow-live-probe: this appends ~11 KB of probe records to the LIVE transcript"
  else
    RIG="$(mktemp -d "${TMPDIR:-/tmp}/st-probe.XXXXXX")" || st_die "mktemp -d failed"
    PROBE_CFG="$RIG/cfg"
    case "$PROBE_CFG" in
      "$HOME/.claude"|"$HOME/.claude/"*) st_die "SAFETY ABORT: probe config dir resolved inside the live ~/.claude" ;;
    esac
    mkdir -p "$PROBE_CFG/projects/$DEST_KEY"
    # Seed the rig so the probe does not stop at a first-run gate and get misread as a
    # placement failure. CLAUDE_CONFIG_DIR relocates .claude.json too, so this file is
    # the rig's own and the real one is untouched.
    python3 - "$PROBE_CFG/.claude.json" "$ST_DEST_ROOT" <<'PY'
import json, os, sys
p, dest = sys.argv[1], sys.argv[2]
json.dump({"hasCompletedOnboarding": True, "bypassPermissionsModeAccepted": True,
           "projects": {dest: {"hasTrustDialogAccepted": True,
                               "hasCompletedProjectOnboarding": True}}},
          open(p, "w"))
os.chmod(p, 0o600)
PY
    if [ "$RIG_CREDS" -eq 1 ] && [ -f "$ST_CLAUDE_HOME/.credentials.json" ]; then
      # byte-copy only. Never opened, never read, never printed, never hashed. The rig is
      # removed at the end of this block.
      cp "$ST_CLAUDE_HOME/.credentials.json" "$PROBE_CFG/.credentials.json" 2>/dev/null \
        && chmod 600 "$PROBE_CFG/.credentials.json" \
        && st_info "--rig-credentials: credentials byte-copied into the rig (never opened; rig is deleted after)"
    fi
    st_info "copying the transcript into an isolated rig ($(st_human "$(st_size "$DEST_TX")"))"
    cp "$DEST_TX" "$PROBE_CFG/projects/$DEST_KEY/$SID.jsonl" || st_die "copy failed"
    chmod u+rw "$PROBE_CFG/projects/$DEST_KEY/$SID.jsonl"
    PROBE_TX="$PROBE_CFG/projects/$DEST_KEY/$SID.jsonl"
  fi
  BEFORE=$(st_size "$PROBE_TX")
  OUT="$(mktemp "${TMPDIR:-/tmp}/st-probe-out.XXXXXX")"
  ERR="$(mktemp "${TMPDIR:-/tmp}/st-probe-err.XXXXXX")"
  st_info "launching from $ST_DEST_ROOT with ANTHROPIC_BASE_URL=http://127.0.0.1:1"
  st_info "  a 216 MB transcript took 2m57s and 1.02 GB RSS on the run that worked"
  # macOS has no GNU `timeout`; perl's alarm is the portable stand-in. NOTE the exit
  # codes differ (124 vs 142) — which is exactly why nothing below decides on the exit
  # code alone.
  if command -v timeout >/dev/null 2>&1; then
    TO=(timeout "$PROBE_TIMEOUT")
  else
    TO=(perl -e "alarm $PROBE_TIMEOUT; exec @ARGV" --)
  fi
  ( cd "$ST_DEST_ROOT" 2>/dev/null && \
    "${TO[@]}" env ANTHROPIC_BASE_URL=http://127.0.0.1:1 CLAUDE_CONFIG_DIR="$PROBE_CFG" \
        ANTHROPIC_API_KEY=dummy NODE_OPTIONS=--max-old-space-size=8192 \
        "$ST_CLI" --resume="$SID" --print 'reply with exactly: OK' </dev/null ) >"$OUT" 2>"$ERR"
  rc=$?
  AFTER=$(st_size "$PROBE_TX")
  st_info "probe exit=$rc (GNU timeout kills with 124; perl's alarm gives 142 — neither is"
  st_info "  the verdict; the verdict is the signals below)"

  # TWO INDEPENDENT POSITIVE SIGNALS, one definitive negative, and one INCONCLUSIVE state.
  # Neither positive is "no error was printed" — both are things that can only happen
  # after the resolver has found the file and the loader has replayed it.
  #
  #   P1  the probe's OWN transcript grew. Measured across every experiment: every LOADED
  #       run appended to its transcript, every NOT-FOUND run left it at exactly its
  #       original size. This signal is robust to the process being killed silently.
  #   P2  the run reached the network layer (ECONNREFUSED / fetch failed / connect).
  #       Stronger prose, but it only appears if the CLI got far enough to print before
  #       the timeout fired — with a short --probe-timeout it often does not.
  #   N1  "No conversation found with session ID" — the resolver did not find the file.
  #   N2  an AUTH / ONBOARDING / TRUST stop — the CLI never reached the resolver at all.
  #       That is INCONCLUSIVE about placement, and must not be reported as either.
  LOADED=0
  NOTFOUND=0; NETSIG=0; GREW=0; AUTHSTOP=0
  grep -qiE 'no conversation found|could not find session' "$ERR" "$OUT" 2>/dev/null && NOTFOUND=1
  grep -qiE 'ECONNREFUSED|fetch failed|ENOTFOUND|connect' "$ERR" "$OUT" 2>/dev/null && NETSIG=1
  grep -qiE 'not logged in|please run .*login|onboarding|trust this folder|do you trust' "$ERR" "$OUT" 2>/dev/null && AUTHSTOP=1
  [ "${AFTER:-0}" -gt "${BEFORE:-0}" ] && GREW=1
  st_info "signals: not-found=$NOTFOUND  network-reached=$NETSIG  transcript-grew=$GREW  auth-stop=$AUTHSTOP  exit=$rc"
  if [ "$NOTFOUND" -eq 1 ]; then
    st_bad "SESSION NOT FOUND — the resolver did not find the transcript from this cwd."
    st_bad "  Resume is cwd-scoped with no global fallback: the directory name must be exactly"
    st_bad "  mangle(realpath(launch cwd)) = $DEST_KEY"
  elif [ "$GREW" -eq 1 ] || [ "$NETSIG" -eq 1 ]; then
    LOADED=1
    st_ok "LOADED. The transcript was found, parsed and replayed from $ST_DEST_ROOT."
    [ "$GREW" -eq 1 ] && st_ok "  positive signal: the probe transcript grew $BEFORE -> $AFTER bytes"
    [ "$NETSIG" -eq 1 ] && st_ok "  positive signal: reached the network layer on the dead port"
    [ "$GREW" -eq 1 ] && [ "$NETSIG" -eq 0 ] && st_info \
      "  no network-layer text: the process was killed by the timeout before printing. That is"
    [ "$GREW" -eq 1 ] && [ "$NETSIG" -eq 0 ] && st_info \
      "  not a failure — growth already proves the loader adopted the file."
  elif [ "$AUTHSTOP" -eq 1 ]; then
    st_skip "CLI load probe — INCONCLUSIVE: the run stopped at an auth/onboarding/trust gate"
    st_log "        before the resolver ran. This says NOTHING about placement, in either"
    st_log "        direction. Re-run with --rig-credentials (byte-copies the credential"
    st_log "        file into the throwaway rig, never opens it), or with --allow-live-probe"
    st_log "        if appending ~11 KB to the live transcript is acceptable."
    head -6 "$ERR" | while IFS= read -r l; do st_log "        $l"; done
  else
    st_bad "NEITHER positive signal fired and the resolver did not report 'not found':"
    st_bad "  the probe died before it got anywhere. Do NOT read this as a pass."
    st_bad "  exit=$rc, stderr follows (empty stderr usually means it was killed while blocked):"
    head -8 "$ERR" | while IFS= read -r l; do st_log "        $l"; done
    head -4 "$OUT" | while IFS= read -r l; do st_log "        out: $l"; done
  fi
  if grep -qiE 'heap out of memory|Allocation failed|FATAL ERROR' "$ERR" 2>/dev/null; then
    st_bad "OOM during load — retry with a larger NODE_OPTIONS=--max-old-space-size"
  else
    st_ok "no OOM"
  fi
  if grep -qiE 'signature provided is not valid|thinking.signature' "$ERR" "$OUT" 2>/dev/null; then
    st_bad "THINKING SIGNATURE REJECTED — fatal, single-shot, no retry. Do NOT attempt to"
    st_bad "  strip or re-sign the blocks: that is prohibition 2 and it deletes thousands of"
    st_bad "  records in place. Fall back to a fresh session seeded from memory/ and tasks/"
    st_bad "  (the 'When NOT to use this skill' path in SKILL.md)."
  fi
  if [ "$LIVE_PROBE" -eq 0 ]; then
    st_ok "the LIVE transcript was not touched by this probe (isolated rig)"
    # Only claim the key inference when the probe actually LOADED. Printing it after a
    # NOT-FOUND is the M7 failure mode inside the M7 guard: a success sentence emitted
    # without checking that the thing it describes happened.
    if [ "$LOADED" -eq 1 ]; then
      st_ok "  the CLI computed the project-dir name itself from the launch cwd and found our"
      st_ok "  copy under $DEST_KEY => that key is correct for the live location too"
    else
      st_info "  no inference about the key can be drawn from a probe that did not load"
    fi
  fi
  rm -rf "$RIG" "$OUT" "$ERR" 2>/dev/null
fi

# ------------------------------------------------------------------ 8. origin
st_banner "8  ORIGIN UNCHANGED"
ORIGIN_IS_LOCAL=0
if [ -z "$ST_ORIGIN_HOST" ] && [ -n "$ST_ORIGIN_CLAUDE" ] && [ -d "$ST_ORIGIN_CLAUDE" ]; then
  ORIGIN_IS_LOCAL=1                      # same-host migration: read the origin directly
fi
if [ -n "$ORIGIN_PROOF" ]; then
  # A proof made ON the origin (`st-bundle.py origin-proof`) for when the destination cannot reach it (push
  # migrations, air-gapped hosts). It must name this session and this checkpoint's exact prefix length and hash.
  if [ -z "$CKPT_TX" ] || [ ! -f "$CKPT_TX" ]; then
    st_skip "origin-unchanged proof (need --checkpoint to compare the proof against)"
  else
    N=$(st_size "$CKPT_TX"); CSHA=$(st_sha256 "$CKPT_TX")
    PV="$(python3 - "$ORIGIN_PROOF" "$SID" "$N" "$CSHA" <<'PY'
import json, sys
f, sid, n, sha = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]
try:
    d = json.load(open(f, encoding="utf-8"))
except Exception as e:
    print("BAD unreadable proof: %s" % e); sys.exit()
if d.get("format") != "st-origin-proof/1":
    print("BAD not an st-origin-proof/1 file"); sys.exit()
if d.get("session_id") != sid:
    print("BAD proof is for session %s, not %s" % (d.get("session_id"), sid)); sys.exit()
if d.get("prefix_len") != n:
    print("BAD proof covers %s bytes, the checkpoint transcript is %s" % (d.get("prefix_len"), n)); sys.exit()
if not d.get("found"):
    print("BAD the origin transcript was not found when the proof was made"); sys.exit()
print(("OK %s %s" % (d.get("size_now"), d.get("created_utc"))) if d.get("prefix_sha256") == sha else
      "CHANGED %s" % d.get("created_utc"))
PY
)"
    case "$PV" in
      OK*)      set -- $PV
                st_ok "origin proof ($ORIGIN_PROOF, made $3): the origin's first $N bytes are identical to the checkpoint"
                if [ "$2" -gt "$N" ] 2>/dev/null; then
                  st_warn "the origin transcript had GROWN to $2 bytes: the session was resumed there; the histories fork"
                else
                  st_ok "the origin transcript was unchanged in size ($2 bytes) when the proof was made"
                fi ;;
      CHANGED*) st_bad "origin proof: the origin's first $N bytes CHANGED: something wrote to the origin" ;;
      *)        st_bad "origin proof rejected: ${PV#BAD }" ;;
    esac
  fi
elif [ -z "$ST_ORIGIN_HOST" ] && [ "$ORIGIN_IS_LOCAL" -eq 0 ]; then
  st_skip "origin-unchanged proof (pass --origin-host, --origin-claude for a same-host origin, or --origin-proof FILE made on the origin with st-bundle.py origin-proof)"
elif [ -z "$ST_ORIGIN_KEY" ] || [ -z "$CKPT_TX" ] || [ ! -f "$CKPT_TX" ]; then
  st_skip "origin-unchanged proof (need --checkpoint and --origin-key)"
elif [ -z "$ST_ORIGIN_CLAUDE" ]; then
  st_skip "origin-unchanged proof (need --origin-claude: the remote path must be absolute, no shell expansion happens there)"
else
  RC_HOME="$ST_ORIGIN_CLAUDE"
  N=$(st_size "$CKPT_TX")
  CSHA=$(st_sha256 "$CKPT_TX")
  if [ "$ORIGIN_IS_LOCAL" -eq 1 ]; then
    REM="$(python3 "$ST_SELF/st_walk.py" \
          --root "$RC_HOME/projects/$ST_ORIGIN_KEY/$SID.jsonl" --prefix-sha "$N" 2>/dev/null)"
  else
    REM="$(st_ssh_py "$ST_ORIGIN_HOST" "$ST_SELF/st_walk.py" \
          --root "$RC_HOME/projects/$ST_ORIGIN_KEY/$SID.jsonl" --prefix-sha "$N" 2>/dev/null)"
  fi
  RSHA=$(printf '%s' "$REM" | cut -f1); RSIZE=$(printf '%s' "$REM" | cut -f3)
  if [ -z "$RSHA" ]; then
    st_skip "origin prefix hash (the remote command did not execute)"
  elif [ "$RSHA" = "$CSHA" ]; then
    st_ok "the origin's first $N bytes are still identical to the checkpoint"
    if [ -n "$RSIZE" ] && [ "$RSIZE" -gt "$N" ]; then
      st_warn "the origin transcript has GROWN to $RSIZE bytes — someone resumed the session there."
      st_warn "  The two histories have now forked; a write-back of the transcript is illegal."
    else
      st_ok "the origin transcript is unchanged in size ($RSIZE bytes)"
    fi
  else
    st_bad "the origin's first $N bytes CHANGED — something wrote to the origin"
  fi
fi

st_banner "VERIFY VERDICT"
st_log "A green run proves the session LOADS and the bytes match. It does not prove the"
st_log "session is FAITHFUL. Finish G8 by asking the resumed session a question only the"
st_log "real history can answer — a specific artifact or number from mid-history — with the"
st_log "expected answer written down BEFORE you ask."
st_summary "VERIFY"
exit $?
