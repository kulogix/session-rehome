#!/usr/bin/env bash
# st-preflight.sh — G0/G1 gate for a Claude Code session migration.
#
# WRITES NOTHING. Not to the origin (every remote call goes through the read-only ssh
# chokepoint in st-common.sh), and not to the destination (unless you pass --report /
# --json / --emit-profile, which write exactly the files you name).
#
# STEP 0 IS DISCOVERY. You almost never know the session id:
#     st-preflight.sh --origin-host HOST --list-sessions
# lists every transcript on the origin, newest first, with the opening words of its first
# user message. Pick one, then run the real preflight with --session-id.
#
# It then answers, before anything is copied:
#   * is the origin reachable, and what does it actually run?
#   * where does this session really live?  (the LITERAL observed project key — never a
#     key derived by editing another key: the mangler is not injective, F1/F24)
#   * is the transcript intact enough to move (LF-terminated, last line parses)?
#   * what is the complete inventory, with byte counts by category?
#   * what is the destination's mangled project key, and is anything already there?
#   * is there disk headroom for a checkpoint AND a materialised destination?
#   * is the destination Desktop instance signed in, and is it stopped?
#
# Exit 0 = all gates pass. Exit 1 = at least one gate failed. A check that could not be
# executed counts as a FAILURE, never as a pass (guard M7/F11).
#
# All human output goes to STDERR. Capture it with --report FILE, or `2>&1 | tee`.
set -uo pipefail

ST_SELF="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=st-common.sh
. "$ST_SELF/st-common.sh"

usage() {
  cat <<'EOF'
st-preflight.sh — inspect an origin/destination pair before migrating a session.

  --profile FILE        shell file presetting any ST_* variable below (FLAGS WIN)

DISCOVERY (step 0 — no --session-id or --dest-root needed)
  --list-sessions       enumerate every transcript on the origin, newest first
  --list-limit N        how many to show (default 40)

ORIGIN
  --origin-host HOST    ssh host of the origin            (ST_ORIGIN_HOST)
                        omit, or pass "local", for a same-host migration
  --origin-root PATH    origin project root               (ST_ORIGIN_ROOT)
  --origin-claude PATH  origin ~/.claude                  (ST_ORIGIN_CLAUDE, default ~/.claude there)
  --origin-key KEY      LITERAL project-dir name to use when several hold this session
  --session-id UUID     CLI session id = transcript stem  (ST_SESSION_ID)

DESTINATION
  --dest-root PATH      destination project root          (ST_DEST_ROOT)
  --claude-home PATH    destination ~/.claude             (ST_CLAUDE_HOME, default $HOME/.claude)
  --user-data-dir PATH  Desktop instance dir              (ST_USER_DATA_DIR)
  --account UUID        destination accountUuid           (ST_ACCOUNT)
  --org UUID            destination organizationUuid      (ST_ORG)
  --checkpoint-root DIR where checkpoints will live       (ST_CKPT_ROOT)
  --cli PATH            destination claude binary (for the version check)

OPTIONS
  --session-only        the origin project TREE is gone or irrelevant (offline archive,
                        session-only migration): its absence stops being a failure
  --deep                full streaming version census of the transcript (slower)
  --hazards             remote filename-hazard scan of the project tree (slower)
  --json FILE           save the raw origin probe JSON here
  --report FILE         tee the human report here
  --emit-profile FILE   write a profile.example-shaped file with everything discovered
  -h | --help

Everything else is read-only. Nothing is copied and nothing is installed.
EOF
}

# Flags must beat the profile, so the profile is sourced BEFORE the argument loop.
st_preparse_profile "$@"

ST_ORIGIN_HOST="${ST_ORIGIN_HOST:-}"
ST_ORIGIN_ROOT="${ST_ORIGIN_ROOT:-}"
ST_ORIGIN_CLAUDE="${ST_ORIGIN_CLAUDE:-}"
ST_ORIGIN_KEY="${ST_ORIGIN_KEY:-}"
ST_SESSION_ID="${ST_SESSION_ID:-}"
ST_DEST_ROOT="${ST_DEST_ROOT:-}"
ST_CLAUDE_HOME="${ST_CLAUDE_HOME:-$HOME/.claude}"
ST_USER_DATA_DIR="${ST_USER_DATA_DIR:-}"
ST_ACCOUNT="${ST_ACCOUNT:-}"
ST_ORG="${ST_ORG:-}"
ST_CKPT_ROOT="${ST_CKPT_ROOT:-}"
ST_CLI="${ST_CLI:-}"
DEEP=0; HAZ=0; JSON_OUT=""; REPORT=""; LIST=0; LIST_LIMIT=40; SESSION_ONLY=0; EMIT_PROFILE=""

while [ $# -gt 0 ]; do
  case "$1" in
    --profile)         shift 2 ;;                       # already sourced by the pre-parse
    --profile=*)       shift ;;
    --origin-host)     ST_ORIGIN_HOST="$2"; shift 2 ;;
    --origin-root)     ST_ORIGIN_ROOT="$2"; shift 2 ;;
    --origin-claude)   ST_ORIGIN_CLAUDE="$2"; shift 2 ;;
    --origin-key)      ST_ORIGIN_KEY="$2"; shift 2 ;;
    --session-id)      ST_SESSION_ID="$2"; shift 2 ;;
    --dest-root)       ST_DEST_ROOT="$2"; shift 2 ;;
    --claude-home)     ST_CLAUDE_HOME="$2"; shift 2 ;;
    --user-data-dir)   ST_USER_DATA_DIR="$2"; shift 2 ;;
    --account)         ST_ACCOUNT="$2"; shift 2 ;;
    --org)             ST_ORG="$2"; shift 2 ;;
    --checkpoint-root) ST_CKPT_ROOT="$2"; shift 2 ;;
    --cli)             ST_CLI="$2"; shift 2 ;;
    --list-sessions)   LIST=1; shift ;;
    --list-limit)      LIST_LIMIT="$2"; shift 2 ;;
    --session-only)    SESSION_ONLY=1; shift ;;
    --deep)            DEEP=1; shift ;;
    --hazards)         HAZ=1; shift ;;
    --json)            JSON_OUT="$2"; shift 2 ;;
    --report)          REPORT="$2"; shift 2 ;;
    --emit-profile)    EMIT_PROFILE="$2"; shift 2 ;;
    -h|--help)         usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[ -n "$REPORT" ] && ST_LOGFILE="$REPORT"
st_need python3

LOCAL_ORIGIN=0
case "${ST_ORIGIN_HOST:-local}" in local|localhost|"") LOCAL_ORIGIN=1 ;; esac
# ssh is only needed for a remote origin. An offline archive mounted locally, or a
# same-host move, must not die on a host that has no ssh client installed.
[ "$LOCAL_ORIGIN" -eq 1 ] || st_need ssh

PROBE_JSON="$(mktemp "${TMPDIR:-/tmp}/st-probe.XXXXXX")" || st_die "mktemp failed"
PROBE_ERR="$(mktemp "${TMPDIR:-/tmp}/st-probe-err.XXXXXX")" || st_die "mktemp failed"
cleanup() { rm -f "${PROBE_JSON:-}" "${PROBE_ERR:-}"; }
trap cleanup EXIT

run_probe() {   # run_probe ARGS... -> JSON on stdout of $PROBE_JSON, stderr kept
  if [ "$LOCAL_ORIGIN" -eq 1 ]; then
    python3 "$ST_SELF/st_origin_probe.py" "$@" > "$PROBE_JSON" 2>"$PROBE_ERR"
  else
    st_ssh_py "$ST_ORIGIN_HOST" "$ST_SELF/st_origin_probe.py" "$@" > "$PROBE_JSON" 2>"$PROBE_ERR"
  fi
}

probe_failed() {  # probe_failed RC
  st_bad "origin probe failed (rc=$1)"
  st_log "  the probe's own stderr — the reason lives here, and used to be thrown away:"
  head -20 "$PROBE_ERR" 2>/dev/null | while IFS= read -r l; do st_log "    $l"; done
  if [ -s "$PROBE_JSON" ] && ! head -c 1 "$PROBE_JSON" | grep -q '{'; then
    st_log "  what landed on stdout instead of JSON:"
    head -5 "$PROBE_JSON" | while IFS= read -r l; do st_log "    $l"; done
  fi
}

# =============================================================== DISCOVERY MODE
if [ "$LIST" -eq 1 ]; then
  st_banner "ST-PREFLIGHT   session discovery on ${ST_ORIGIN_HOST:-<local>}"
  if [ "$LOCAL_ORIGIN" -eq 0 ] && ! st_ssh_alive "$ST_ORIGIN_HOST"; then
    st_bad "ssh $ST_ORIGIN_HOST unreachable (BatchMode; is the key/agent set up?)"
    st_summary "PREFLIGHT-DISCOVER"; exit 1
  fi
  set -- --list-sessions --list-limit "$LIST_LIMIT"
  [ -n "$ST_ORIGIN_CLAUDE" ] && set -- "$@" --claude-home "$ST_ORIGIN_CLAUDE"
  run_probe "$@"; rc=$?
  if [ $rc -ne 0 ] || [ ! -s "$PROBE_JSON" ]; then probe_failed "$rc"; st_summary "PREFLIGHT-DISCOVER"; exit 1; fi
  [ -n "$JSON_OUT" ] && cp "$PROBE_JSON" "$JSON_OUT"
  python3 - "$PROBE_JSON" >&2 <<'PY'
import json, sys, time
d = json.load(open(sys.argv[1]))
rows = d.get("sessions") or []
print("  claude home: %s%s" % (d.get("claude_home"),
      "" if d.get("claude_home_exists") else "   <-- DOES NOT EXIST"))
if not rows:
    print("  no transcripts found. Wrong --origin-claude, or this host has never run the CLI.")
    raise SystemExit(0)
print("")
print("  %-38s %10s %-17s %s" % ("session id (= transcript stem)", "bytes", "last modified", "project key"))
for r in rows:
    print("  %-38s %10d %-17s %s" % (r["session_id"], r["bytes"],
          time.strftime("%Y-%m-%d %H:%M", time.localtime(r["mtime"])), r["project_key"]))
    tag = []
    if r.get("has_sidecar_dir"):
        tag.append("%d sidecar files" % r.get("sidecar_files", 0))
    if r.get("has_tasks"):
        tag.append("task store")
    if tag:
        print("  %-38s %s" % ("", ", ".join(tag)))
    if r.get("first_user_message"):
        print("  %-38s \"%s\"" % ("", r["first_user_message"]))
    print("")
print("  Pick the session id you mean, then:")
print("    st-preflight.sh --session-id <id> --origin-root <origin project root> \\")
print("                    --dest-root <destination project root> [--origin-host HOST]")
PY
  st_summary "PREFLIGHT-DISCOVER"
  exit $?
fi

st_require_var ST_SESSION_ID  --session-id
st_require_var ST_DEST_ROOT   --dest-root
if [ -z "$ST_ORIGIN_ROOT" ]; then
  [ "$SESSION_ONLY" -eq 1 ] || st_die "missing --origin-root (or pass --session-only if the origin project tree is gone / irrelevant)"
fi

st_banner "ST-PREFLIGHT   session $ST_SESSION_ID"
st_log "origin      ${ST_ORIGIN_HOST:-<local>}:${ST_ORIGIN_ROOT:-<session only>}"
st_log "destination $ST_DEST_ROOT"
st_log "read-only — this script writes nothing except files you named explicitly"

# --------------------------------------------------------------- G0 reachability
st_banner "G0  ORIGIN REACHABILITY AND CAPABILITY"
if [ "$LOCAL_ORIGIN" -eq 1 ]; then
  st_ok "origin is this host (no ssh)"
  st_info "same-host / offline-archive mode: the origin-unchanged proof and st-resync.sh"
  st_info "  still work, but D2 (fate of the origin) is usually moot for a frozen archive"
else
  if st_ssh_alive "$ST_ORIGIN_HOST"; then
    REMOTE_UNAME="$(st_ssh_ro "$ST_ORIGIN_HOST" "uname -sr")"
    st_ok "ssh $ST_ORIGIN_HOST reachable — $REMOTE_UNAME"
  else
    st_bad "ssh $ST_ORIGIN_HOST unreachable (BatchMode; is the key/agent set up?)"
    st_summary "PREFLIGHT"; exit 1
  fi
  T0=$(date -u +%s)
  RTS="$(st_ssh_ro "$ST_ORIGIN_HOST" "date -u +%s" 2>/dev/null)"
  T1=$(date -u +%s)
  if [ -n "$RTS" ]; then
    SKEW=$(( RTS - (T0 + T1) / 2 ))
    [ "${SKEW#-}" -le 5 ] && st_ok "clock skew ${SKEW}s" \
      || st_warn "clock skew ${SKEW}s — never use mtime as the sole change signal (V25)"
  else
    st_skip "clock skew"
  fi
fi

set -- --session-id "$ST_SESSION_ID"
[ -n "$ST_ORIGIN_ROOT" ]   && set -- "$@" --project-root "$ST_ORIGIN_ROOT"
[ -n "$ST_ORIGIN_CLAUDE" ] && set -- "$@" --claude-home "$ST_ORIGIN_CLAUDE"
# `--opt=VALUE`, never `--opt VALUE`: every project key begins with '-' and argparse
# reads a leading-dash value as the next option.
[ -n "$ST_ORIGIN_KEY" ]    && set -- "$@" "--origin-key=$ST_ORIGIN_KEY"
[ "$DEEP" -eq 1 ] && set -- "$@" --deep
[ "$HAZ"  -eq 1 ] && set -- "$@" --hazard-scan

st_info "probing the origin (read-only; helper shipped over stdin, never written there)"
run_probe "$@"; rc=$?
if [ $rc -ne 0 ] || [ ! -s "$PROBE_JSON" ]; then
  probe_failed "$rc"
  st_bad "cannot inventory the session"
  st_summary "PREFLIGHT"; exit 1
fi
st_ok "origin probe returned $(st_size "$PROBE_JSON") bytes of JSON"
[ -s "$PROBE_ERR" ] && { st_info "probe stderr:"; head -6 "$PROBE_ERR" | while IFS= read -r l; do st_log "    $l"; done; }
[ -n "$JSON_OUT" ] && { cp "$PROBE_JSON" "$JSON_OUT"; st_info "probe JSON saved to $JSON_OUT"; }

# --------------------------------------------------------------- G1 the session
st_banner "G1  THE SESSION ON THE ORIGIN"
while IFS= read -r line; do
  case "$line" in
    "OK "*)   st_ok   "${line#OK }" ;;
    "WARN "*) st_warn "${line#WARN }" ;;
    "FAIL "*) st_bad  "${line#FAIL }" ;;
    "INFO "*) st_info "${line#INFO }" ;;
    *) st_log "        $line" ;;
  esac
done < <(python3 - "$PROBE_JSON" "$ST_SESSION_ID" "$LOCAL_ORIGIN" "$SESSION_ONLY" "${ST_ORIGIN_KEY:-}" <<'PY'
import json, sys

d = json.load(open(sys.argv[1]))
sid = sys.argv[2]
local_origin = sys.argv[3] == "1"
session_only = sys.argv[4] == "1"
forced_key = sys.argv[5]
say = print


def human(n):
    n = float(n or 0)
    for u in ("B", "KiB", "MiB", "GiB", "TiB"):
        if n < 1024 or u == "TiB":
            return "%.1f %s" % (n, u)
        n /= 1024


say("INFO host %s  python %s  %s" % (d.get("host"), d.get("python"), d.get("uname")))

t = d.get("tools", {})
missing = [k for k in ("rsync", "python3") if not t.get(k)]
if missing:
    say("FAIL origin is missing required tools: %s" % ", ".join(missing))
else:
    say("OK   rsync and python3 present on the origin")
if not t.get("timeout"):
    say("INFO no GNU `timeout` on the origin — use `perl -e 'alarm N; exec @ARGV'` there")
rv = (d.get("rsync_version") or [""])[0]
if "openrsync" in rv or "protocol version 29" in rv:
    say("WARN origin runs openrsync (%s): no -H -X -A -S --iconv --protect-args" % rv.strip()[:60])
elif rv:
    say("INFO origin rsync: %s" % rv.strip()[:80])

procs = d.get("claude_processes") or []
if procs and local_origin:
    say("INFO %d claude process(es) are running ON THIS HOST. For a same-host or offline-archive"
        % len(procs))
    say("     origin that is usually YOUR OWN session, not something writing the archive.")
elif procs:
    say("WARN %d claude process(es) running on the origin — the transcript may grow "
        "mid-copy. The prefix invariant tolerates that; a torn line does not." % len(procs))
else:
    say("OK   no claude process running on the origin")

kt = d.get("keys_with_transcript") or []
cand = d.get("transcript_candidates") or {}
if not kt:
    say("FAIL no project key on the origin contains %s.jsonl — wrong session id, wrong "
        "--origin-claude, or the session was never written" % sid)
elif len(kt) > 1 and not forced_key:
    say("FAIL %d project keys each contain %s.jsonl. A session that ran under git worktrees "
        "legitimately has content under more than one key, and taking only one silently "
        "drops the rest. Choose with --origin-key, or pass --all-transcript-keys to "
        "st-checkpoint.sh to take them all:" % (len(kt), sid))
    for k in kt:
        c = cand.get(k) or {}
        say("     %-58s %12d B" % (k, c.get("bytes", 0)))
        if c.get("first_user_message"):
            say("       \"%s\"" % c["first_user_message"][:100])
else:
    say("OK   origin project key (LITERAL, observed — never derive one by editing another): %s"
        % d.get("origin_key"))
    if len(kt) > 1:
        say("WARN %d keys hold this session; --origin-key selected %s and the others are NOT "
            "in the plan" % (len(kt), d.get("origin_key")))
if d.get("origin_key_error"):
    say("FAIL %s" % d["origin_key_error"])
say("INFO origin has %d project keys in total" % (d.get("project_keys_total") or 0))

tr = d.get("transcript") or {}
if tr.get("exists"):
    say("OK   transcript %s" % tr["path"])
    say("     %d bytes (%s), %d lines, mode %s" %
        (tr["size"], human(tr["size"]), tr["lines"], tr.get("mode")))
    if tr.get("ends_with_lf"):
        say("OK   transcript ends with LF")
    else:
        say("FAIL transcript does not end with 0x0a — the last record is torn")
    if tr.get("last_line_parses"):
        say("OK   last line is valid JSON")
    else:
        say("FAIL last line does not parse as JSON — the file is mid-write or truncated")
    vers = tr.get("writer_versions") or {}
    if vers:
        say("INFO writer versions%s: %s" %
            ("" if tr.get("deep_scan") else " (sampled — pass --deep for the full census)",
             ", ".join("%s x%d" % (k, v) for k, v in sorted(vers.items()))))
    ids = tr.get("in_record_session_ids") or {}
    if ids:
        say("INFO in-record sessionId(s): %s" % ", ".join(sorted(ids)))
        if sid not in ids:
            say("WARN no record carries the filename session id. Resume keys off the "
                "FILENAME (K1), so this still works — but a `relocated` record must use "
                "the IN-RECORD id, not the filename one.")
else:
    say("FAIL transcript not found")

sib = (d.get("inventory") or {}).get("sibling_keys") or {}
if sib:
    say("WARN %d SIBLING project key(s) also hold data for this session — plan a "
        "destination path for each:" % len(sib))
    for k, v in sorted(sib.items()):
        extra = []
        if v.get("has_memory"):
            extra.append("HAS ITS OWN memory/")
        if v.get("has_transcript"):
            extra.append("HAS ITS OWN transcript")
        say("     %-58s %5d files %12d B %s" % (k, v["files"], v["bytes"], " ".join(extra)))
else:
    say("OK   no sibling project keys hold data for this session")

inv = d.get("inventory") or {}
order = ["transcript", "sidecar_subagents", "sidecar_subagents_workflows",
         "sidecar_tool_results", "sidecar_workflows", "sidecar_workflow_scripts",
         "sidecar_total", "memory", "tasks", "settings_json", "user_memory", "plugins"]
say("")
say("     INVENTORY — what would be migrated")
say("     %-32s %8s %16s  %s" % ("category", "files", "bytes", "note"))
total_f = total_b = 0
for k in order:
    v = inv.get(k)
    if not v:
        continue
    note = ""
    if k == "sidecar_total":
        note = "(= the four rows above; not added twice)"
    elif k == "plugins":
        note = "REGENERATE at the destination — do not copy (abs installPath + arch)"
    elif k == "memory":
        note = "project-scoped, highest value per byte"
    elif k == "tasks":
        note = "tasks/<SID> only — never the whole tasks/ dir"
    elif k == "user_memory":
        note = "~/.claude/CLAUDE.md — HOST-wide; copy only with --include-user-memory"
    if v.get("missing"):
        note = "(absent on the origin — that is normal for a short session) " + note
    say("     %-32s %8d %16d  %s" % (k, v["files"], v["bytes"], note))
    if k not in ("sidecar_subagents_workflows", "sidecar_workflow_scripts",
                 "sidecar_subagents", "sidecar_tool_results", "sidecar_workflows",
                 "plugins", "user_memory"):
        total_f += v["files"]
        total_b += v["bytes"]
for k, v in sorted(sib.items()):
    total_f += v["files"]
    total_b += v["bytes"]
say("     %-32s %8d %16d  %s" % ("SESSION TOTAL", total_f, total_b, human(total_b)))
tr_b = (inv.get("transcript") or {}).get("bytes", 0)
if total_b:
    say("     the transcript alone is %.1f%% of that — a .jsonl-only copy loses the rest, "
        "including 100%% of subagent content" % (100.0 * tr_b / total_b))

assets = inv.get("shared_assets") or {}
for adir in ("skills", "agents", "commands", "output-styles", "hooks"):
    entry = assets.get(adir) or {}
    if not entry:
        continue
    say("")
    say("     %s/ on the origin — whitelist by NAME (a single skill was 321 MB of venv)" % adir)
    for k, v in sorted(entry.items(), key=lambda kv: -kv[1]["bytes"]):
        flag = "  <-- large, exclude unless needed" if v["bytes"] > (50 << 20) else ""
        say("     %-40s %6d files %14d B%s" % (k, v["files"], v["bytes"], flag))
    if adir != "skills":
        say("     st-checkpoint.sh takes these only with --include-%s" % adir)

pt = d.get("project_tree")
if pt:
    say("")
    say("INFO project tree (unfiltered): %d files, %d bytes (%s)" %
        (pt["files"], pt["bytes"], human(pt["bytes"])))
    if pt.get("capped"):
        say("WARN project-tree walk hit its file cap — the real tree is larger")
    gits = d.get("git_repos") or []
    if gits:
        say("INFO %d git repo(s) in the project tree: %s%s" %
            (len(gits), ", ".join(gits[:6]), " ..." if len(gits) > 6 else ""))
        say("     run st-git-rescue.sh --scan on the tree BEFORE relying on the copy")
elif session_only:
    say("INFO no origin project tree (--session-only). The session moves; the working tree "
        "does not. st-checkpoint.sh --session-only, st-transplant.py --no-project-tree.")
elif not d.get("project_root_given"):
    say("INFO no --origin-root given and --session-only was not passed")
else:
    say("FAIL origin project root does not exist: %s" % d.get("project_root"))
    say("     If the tree is genuinely gone (offline archive, session-only move), pass "
        "--session-only and this stops being a failure.")

nc = d.get("never_copy_present") or {}
if nc:
    say("")
    say("INFO deliberately NOT copied (present on the origin, left behind by policy):")
    for k, v in sorted(nc.items()):
        say("     %-24s %s" % (k, v))
    say("     none of these is opened or hashed by any transporter script")

hz = d.get("hazards")
if hz is not None:
    n_nfd = len(hz["nfd"]); n_case = len(hz["case_collisions"])
    n_na = len(hz["non_ascii"]); n_big = len(hz["over_4gib"]); n_sp = len(hz["special_files"])
    lvl = "WARN" if (n_nfd or n_case or n_na or n_big or n_sp) else "OK  "
    say("%s filename hazards: %d NFD, %d case/normalisation collisions, %d non-ASCII, "
        "%d >4GiB, %d special" % (lvl, n_nfd, n_case, n_na, n_big, n_sp))
    say("     The fold is NFC+casefold, not lower(): APFS collides across normalisation too.")
    say("     Warn-only when the DESTINATION filesystem is case-sensitive; FATAL when it is")
    say("     not, in either direction — openrsync has no --iconv and cannot fix it in flight.")
    for p in hz["nfd"][:5]:
        say("     NFD  %s" % p)
    for grp in hz["case_collisions"][:5]:
        say("     COLLIDE %s" % grp)
else:
    say("INFO filename hazard scan skipped (pass --hazards)")

disk = d.get("disk") or {}
pr = disk.get("project_root")
if pr:
    say("INFO origin free space at the project root: %s of %s" %
        (human(pr["free_bytes"]), human(pr["total_bytes"])))
    if pr["free_bytes"] < (5 << 30):
        say("WARN origin has under 5 GiB free — any future write-back must be size-gated")
PY
)

# --------------------------------------------------------------- G2 destination
st_banner "G2  THE DESTINATION"

DEST_REAL="$(st_realpath "$ST_DEST_ROOT")"
if [ "$DEST_REAL" != "$ST_DEST_ROOT" ]; then
  st_warn "destination realpath differs from the string you gave:"
  st_warn "  given: $ST_DEST_ROOT"
  st_warn "  real : $DEST_REAL   <-- the mangler is fed THIS one, symlinks resolve through (K11)"
  st_warn "  (this holds even when the directory does not exist yet: the deepest existing"
  st_warn "   ancestor is resolved and the remainder re-joined, which is what the CLI computes"
  st_warn "   once the directory is created)"
fi
DEST_KEY="$(st_mangle "$ST_DEST_ROOT")" || st_die "mangle failed"
st_ok "destination project key: $DEST_KEY  (${#DEST_KEY} chars)"
if [ "${#DEST_KEY}" -gt 200 ]; then
  st_warn "key is >200 chars: it carries a base36 hash suffix. CLI resume and Desktop"
  st_warn "discovery both still find it; what breaks is fork/worktree/scratchpad (F7)."
fi

# case-insensitivity of the DESTINATION filesystem decides whether a filename collision is
# a warning or a catastrophe, and it is cheap to measure rather than assume.
CI_PROBE_DIR="$(dirname "$DEST_REAL")"
[ -d "$CI_PROBE_DIR" ] || CI_PROBE_DIR="$ST_CLAUDE_HOME"
DEST_CI="$(python3 - "$CI_PROBE_DIR" <<'PY'
import os, sys, tempfile
d = sys.argv[1]
while d and not os.path.isdir(d):
    n = os.path.dirname(d)
    if n == d:
        break
    d = n
try:
    fd, p = tempfile.mkstemp(prefix="STcase", dir=d or "/tmp")
    os.close(fd)
    other = os.path.join(os.path.dirname(p), os.path.basename(p).replace("STcase", "stCASE"))
    print("insensitive" if os.path.exists(other) else "sensitive")
    os.unlink(p)
except Exception:
    print("unknown")
PY
)"
case "$DEST_CI" in
  insensitive) st_warn "the destination filesystem is CASE-INSENSITIVE: any case-only collision in the payload MERGES two files, destroys one file's content, and rsync reports success. Treat the hazard scan as FATAL." ;;
  sensitive)   st_ok "destination filesystem is case-sensitive (hazard scan is warn-only in this direction)" ;;
  *)           st_skip "destination filesystem case-sensitivity probe" ;;
esac

if [ -e "$ST_DEST_ROOT" ]; then
  N_EXIST=$(find "$ST_DEST_ROOT" -type f 2>/dev/null | wc -l | tr -d ' ')
  if [ "$N_EXIST" -gt 0 ]; then
    st_warn "destination root already holds $N_EXIST files — the transplant will rsync ON TOP of them"
    st_warn "  st-transplant.py refuses to overwrite newer destination files without"
    st_warn "  --overwrite-destination-work, and backs up whatever it does replace"
  else
    st_ok "destination root exists and is empty"
  fi
  if [ -d "$ST_DEST_ROOT/.git" ]; then
    st_bad "the destination root is ALREADY A GIT REPOSITORY. Copying the origin's .git on"
    st_bad "  top of it overwrites refs, index and reflog: destination-only commits become"
    st_bad "  unreachable AND the reflog that would recover them is clobbered in the same pass."
    st_bad "  st-transplant.py excludes .git/ by default; pass --merge-git only if you mean it,"
    st_bad "  and bring the origin's history in as a bundle from st-git-rescue.sh instead."
  fi
  [ -f "$ST_DEST_ROOT/CLAUDE.md" ] && st_warn "destination already has CLAUDE.md — the transplant edits it between per-session markers, it does not clobber it"
else
  st_ok "destination root does not exist yet (will be created)"
fi

DEST_TX_DIR="$ST_CLAUDE_HOME/projects/$DEST_KEY"
DEST_TX="$DEST_TX_DIR/$ST_SESSION_ID.jsonl"
if [ -e "$DEST_TX" ]; then
  st_warn "a transcript already exists at $DEST_TX ($(st_size "$DEST_TX") bytes)."
  st_warn "  st-transplant.py compares its prefix to the checkpoint: a byte-exact extension"
  st_warn "  is a RESUMED session and is left alone; anything else is renamed aside, never deleted."
else
  st_ok "no transcript collision at $DEST_TX"
fi
if [ -d "$DEST_TX_DIR" ]; then
  OTHER=$(ls -1 "$DEST_TX_DIR"/*.jsonl 2>/dev/null | wc -l | tr -d ' ')
  st_info "destination project dir exists with $OTHER transcript(s) — sessions share it, that is normal"
fi
st_info "the transcript lives under $ST_CLAUDE_HOME (plain ~/.claude), NOT the user-data-dir:"
st_info "  every Desktop instance on this host shares transcripts, skills, plugins and memory"

# ---- disk headroom
SESSION_B=$(python3 - "$PROBE_JSON" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
inv = d.get("inventory") or {}
tot = 0
for k in ("transcript", "sidecar_total", "memory", "tasks", "settings_json"):
    v = inv.get(k)
    if v:
        tot += v["bytes"]
for v in (inv.get("sibling_keys") or {}).values():
    tot += v["bytes"]
print(tot)
PY
)
PROJECT_B=$(python3 - "$PROBE_JSON" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
print((d.get("project_tree") or {}).get("bytes", 0))
PY
)
NEED=$(( SESSION_B + PROJECT_B ))
st_info "payload: session $(st_human "$SESSION_B") + project tree $(st_human "$PROJECT_B") = $(st_human "$NEED")"
st_info "  (the project tree figure is UNFILTERED — st-checkpoint.sh's excludes shrink it,"
st_info "   and it prints a per-pattern file/byte count so an over-broad exclude is a NUMBER)"

check_space() {  # check_space LABEL DIR NEEDED
  local label="$1" dir="$2" need="$3" free
  free="$(st_free_bytes "$dir" 2>/dev/null)"
  if [ -z "$free" ]; then st_skip "free space at $label"; return; fi
  if [ "$free" -gt "$need" ]; then
    st_ok "$label has $(st_human "$free") free (need ~$(st_human "$need"))"
  else
    st_bad "$label has only $(st_human "$free") free, needs ~$(st_human "$need")"
  fi
}
if [ -n "$ST_CKPT_ROOT" ]; then
  check_space "checkpoint root" "$ST_CKPT_ROOT" "$NEED"
else
  st_info "no --checkpoint-root given; skipping its headroom check"
fi
check_space "destination"    "$ST_DEST_ROOT"   "$NEED"
check_space "$ST_CLAUDE_HOME" "$ST_CLAUDE_HOME" "$SESSION_B"

# ---- Desktop instance
if [ -n "$ST_USER_DATA_DIR" ]; then
  if [ -d "$ST_USER_DATA_DIR" ]; then
    st_ok "user-data-dir exists: $ST_USER_DATA_DIR"
    if [ -f "$ST_USER_DATA_DIR/config.json" ]; then
      # KEYS ONLY. This file holds oauth:tokenCache — never print or copy its values.
      python3 - "$ST_USER_DATA_DIR/config.json" >&2 <<'PY'
import json, sys
try:
    d = json.load(open(sys.argv[1]))
except Exception as e:
    print("        config.json unreadable: %s" % e); raise SystemExit(0)
keys = sorted(d.keys())
has_tok = any(k.startswith("oauth:tokenCache") for k in keys)
acct = d.get("lastKnownAccountUuid")
print("        config.json: %d keys, oauth tokenCache %s, lastKnownAccountUuid %s"
      % (len(keys), "PRESENT" if has_tok else "ABSENT", acct or "-"))
orgs = sorted({k.split(":")[-1] for k in keys if k.startswith("dxt:allowlist")})
if orgs:
    print("        org uuids recoverable from dxt:allowlist* keys: %s" % ", ".join(orgs))
print("        (values are never printed, never copied — this file is on the NEVER-COPY list)")
PY
    else
      st_warn "no config.json in the user-data-dir"
    fi
    SESS_DIR="$ST_USER_DATA_DIR/claude-code-sessions"
    if [ -d "$SESS_DIR" ]; then
      st_info "existing session store: $(find "$SESS_DIR" -name 'local_*.json' 2>/dev/null | wc -l | tr -d ' ') session file(s)"
    else
      st_info "no claude-code-sessions/ yet — that means 'no session has been created', NOT 'not signed in' (F6)"
    fi
    if [ -n "$ST_ACCOUNT" ] && [ -n "$ST_ORG" ]; then
      TDIR="$SESS_DIR/$ST_ACCOUNT/$ST_ORG"
      [ -d "$TDIR" ] && st_ok "target account/org dir exists: $TDIR" \
                     || st_info "target account/org dir will be created: $TDIR"
      st_info "a session placed under a NON-matching account/org pair is never read, and it"
      st_info "additionally suppresses its transcript from the recovery UI of the right one"
    else
      st_warn "no --account/--org given; the Desktop session cannot be minted without them"
    fi
    RUN="$(st_instance_running "$ST_USER_DATA_DIR")"
    if [ -n "$RUN" ]; then
      st_warn "that Desktop instance appears to be RUNNING:"
      st_log "        $RUN"
      st_warn "there is no file watcher: a session JSON dropped in now will not appear, and"
      st_warn "the debounced writer can destroy it. Stop THIS instance before transplanting."
    else
      st_ok "no Desktop process is using that user-data-dir"
    fi
  else
    st_warn "user-data-dir does not exist: $ST_USER_DATA_DIR"
  fi
else
  st_info "no --user-data-dir given: CLI-ONLY migration. That is a complete path on its own —"
  st_info "  G7 reduces to 'cd <dest root> && claude --resume=<SID>' and no Desktop gate applies."
fi

# ---- destination CLI
if [ -z "$ST_CLI" ]; then
  ST_CLI="$(command -v claude 2>/dev/null)"
  if [ -z "$ST_CLI" ]; then
    for c in "$HOME"/.claude-instances/*/claude-code/*/claude "$HOME"/.local/share/claude-code/*/claude; do
      [ -x "$c" ] && ST_CLI="$c"
    done
  fi
fi
CLIV=""
if [ -n "$ST_CLI" ] && [ -x "$ST_CLI" ]; then
  CLIV="$("$ST_CLI" --version 2>/dev/null | head -1 | awk '{print $1}')"
  st_ok "destination CLI: $ST_CLI  ${CLIV:-<version unknown>}"
  st_info "this is the version that will extend the transcript. Pass it to st-transplant.py"
  st_info "  as --cli-version $CLIV so any appended record is stamped truthfully."
else
  st_warn "no destination claude binary found (pass --cli) — st-verify.sh needs it for the probe"
fi

# --------------------------------------------------------------- verdict
st_banner "PREFLIGHT VERDICT"
st_log "destination key   $DEST_KEY"
st_log "destination file  $DEST_TX"
st_log "filename stem     $ST_SESSION_ID  (MUST NOT CHANGE — sidecars resolve from it)"
st_log "cli version       ${CLIV:-<unknown>}"
st_log "next              st-checkpoint.sh --plan, then --apply; st-git-rescue.sh --scan;"
st_log "                  st-transplant.py --plan, then --apply; st-verify.sh"

if [ -n "$EMIT_PROFILE" ]; then
  OKEY="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("origin_key") or "")' "$PROBE_JSON")"
  OCL="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("claude_home") or "")' "$PROBE_JSON")"
  {
    echo "# claude-session-transporter profile — generated by st-preflight.sh $(st_ts)"
    echo "# Command-line flags override everything here."
    echo "ST_ORIGIN_HOST=${ST_ORIGIN_HOST:-local}"
    echo "ST_ORIGIN_ROOT=$ST_ORIGIN_ROOT"
    echo "ST_ORIGIN_CLAUDE=$OCL"
    echo "ST_ORIGIN_KEY=$OKEY"
    echo "ST_SESSION_ID=$ST_SESSION_ID"
    echo "ST_DEST_ROOT=$ST_DEST_ROOT"
    echo "ST_CLAUDE_HOME=$ST_CLAUDE_HOME"
    [ -n "$ST_USER_DATA_DIR" ] && echo "ST_USER_DATA_DIR=$ST_USER_DATA_DIR"
    [ -n "$ST_ACCOUNT" ] && echo "ST_ACCOUNT=$ST_ACCOUNT"
    [ -n "$ST_ORG" ] && echo "ST_ORG=$ST_ORG"
    [ -n "$ST_CKPT_ROOT" ] && echo "ST_CKPT_ROOT=$ST_CKPT_ROOT"
    [ -n "$ST_CKPT_ROOT" ] && echo "ST_CKPT=\$ST_CKPT_ROOT/latest-$ST_SESSION_ID"
    [ -n "$ST_CLI" ] && echo "ST_CLI=$ST_CLI"
    [ -n "$CLIV" ] && echo "ST_CLI_VERSION=$CLIV"
  } > "$EMIT_PROFILE"
  st_ok "profile written: $EMIT_PROFILE  (pass it to every later script with --profile)"
fi

st_summary "PREFLIGHT"
exit $?
