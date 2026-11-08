#!/usr/bin/env bash
# st-common.sh — shared helpers for the claude-session-transporter scripts.
# SOURCE this file; do not execute it.
#
# Written for bash 3.2 (the macOS system bash) as well as bash 5: no associative
# arrays, no `mapfile`/`readarray`, no `${var^^}`, no `local -n`, no `readlink -f`,
# no `stat -c`, no GNU-only `date`.
#
# Every caller does `set -uo pipefail` WITHOUT `-e`, and accumulates failures in
# ST_FAIL, so a partial failure is REPORTED rather than aborting mid-tree (this is
# how pull-checkpoint.sh behaved on the run that worked).
#
# ALL HUMAN OUTPUT GOES TO STDERR. That is deliberate and load-bearing: the refusal
# messages from the ssh chokepoint used to land on stdout, which is where callers
# were collecting the origin probe's JSON — a refused command wrote "REFUSED
# (mutating token): ..." INTO the probe JSON, the caller reported `rc=90` and the
# temp-file cleanup then destroyed the only copy of the reason. Capture a run with
# `--report FILE`, or with `2>&1 | tee`.

ST_FAIL=0
ST_WARN_N=0
ST_LOGFILE="${ST_LOGFILE:-}"

st_ts()   { date -u +%Y%m%dT%H%M%SZ; }
st_now()  { date -u +%H:%M:%S; }

st_log()  {
  printf '[%s] %s\n' "$(st_now)" "$*" >&2
  [ -n "$ST_LOGFILE" ] && printf '[%s] %s\n' "$(st_now)" "$*" >> "$ST_LOGFILE"
  return 0
}
st_ok()   { st_log "  OK    $*"; }
st_info() { st_log "  ..    $*"; }
st_warn() { ST_WARN_N=$((ST_WARN_N + 1)); st_log "  WARN  $*"; }
st_bad()  { ST_FAIL=$((ST_FAIL + 1));     st_log "  FAIL  $*"; }
st_die()  { st_log "FATAL: $*"; exit 1; }

# A check that could not run is NOT a pass (guard M7/F11).
st_skip() { ST_FAIL=$((ST_FAIL + 1)); st_log "  NOTRUN $* — a check that did not execute counts as a FAILURE"; }

st_hr()   { printf '%s\n' "----------------------------------------------------------------------" >&2; }

st_banner() {
  st_hr
  printf '%s\n' "$1" >&2
  [ -n "$ST_LOGFILE" ] && printf '%s\n' "$1" >> "$ST_LOGFILE"
  st_hr
  return 0
}

# ---------------------------------------------------------------- portability
ST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"

st_realpath() {  # st_realpath PATH -> physical absolute path (may not exist)
  # For a path that does not exist yet, realpath() on some platforms still resolves
  # symlinked ANCESTORS and on others does not. We resolve the deepest existing
  # ancestor and re-join the remainder, which is well-defined everywhere and is
  # exactly what the CLI ends up computing once the directory has been created.
  python3 - "$1" <<'PY'
import os, sys
p = os.path.abspath(sys.argv[1])
tail = []
while not os.path.exists(p):
    p, t = os.path.split(p)
    if not t:
        break
    tail.insert(0, t)
print(os.path.join(os.path.realpath(p), *tail) if tail else os.path.realpath(p))
PY
}

st_size() {      # st_size FILE -> bytes, or empty
  [ -f "$1" ] || return 1
  wc -c < "$1" | tr -d ' '
}

st_sha256() {    # st_sha256 FILE [LIMIT_BYTES]
  python3 - "$1" "${2:-}" <<'PY'
import hashlib, sys
p = sys.argv[1]
lim = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2] else None
h = hashlib.sha256(); n = 0
with open(p, 'rb') as f:
    while True:
        want = 1 << 20 if lim is None else min(1 << 20, lim - n)
        if want <= 0:
            break
        b = f.read(want)
        if not b:
            break
        h.update(b); n += len(b)
if lim is not None and n < lim:
    sys.stderr.write("short file: %d < %d\n" % (n, lim)); sys.exit(2)
print(h.hexdigest())
PY
}

st_mangle() {    # st_mangle PATH -> the CLI project-dir key for realpath(PATH)
  local real
  real="$(st_realpath "$1")" || return 1
  python3 "$ST_DIR/mangle.py" "$real"
}

st_free_bytes() {  # st_free_bytes DIR
  python3 - "$1" <<'PY'
import os, sys
if not hasattr(os, 'statvfs'):        # Windows: no statvfs, and AttributeError is not OSError
    raise SystemExit(0)
p = sys.argv[1]
while p and not os.path.isdir(p):
    q = os.path.dirname(p)
    if q == p:
        break
    p = q
try:
    st = os.statvfs(p or '/')
except OSError:
    raise SystemExit(0)
print(st.f_bavail * st.f_frsize)
PY
}

st_human() {     # st_human BYTES
  python3 - "$1" <<'PY'
import sys
n = float(sys.argv[1] or 0)
for u in ('B', 'KiB', 'MiB', 'GiB', 'TiB'):
    if n < 1024 or u == 'TiB':
        print("%.1f %s" % (n, u)); break
    n /= 1024
PY
}

st_need() {      # st_need CMD...
  local c
  for c in "$@"; do
    command -v "$c" >/dev/null 2>&1 || st_die "required command not found: $c"
  done
}

# ---------------------------------------------------------------- ssh chokepoint
# Tripwire 2: "never write to the origin" is enforced by a single chokepoint, not by
# intention. Every remote command goes through st_ssh_ro, which:
#   * allowlists the leading token of every pipeline segment (whitelist, not blacklist)
#   * denies redirections, and every mutating git subcommand
#   * uses connection multiplexing, and SERIALISES calls (a burst of parallel ssh calls
#     produced spurious `mux_client_request_session: session request failed`)
#
# st_ssh_check_cmd is ALSO applied on the `--origin-host local` path (see st-resync.sh's
# `rro`), so the guarantee is a property of the code and not of which branch you took.
ST_SSH_OPTS="${ST_SSH_OPTS:--o BatchMode=yes -o ControlMaster=auto -o ControlPath=${TMPDIR:-/tmp}/st-ssh-%r@%h:%p -o ControlPersist=10m}"

ST_SSH_ALLOW=" cd python3 python find ls df du uname sw_vers wc head tail stat cat sed awk grep sort uniq tr cut printf echo test true command git shasum sha256sum openssl md5 xargs basename dirname readlink hostname date id sysctl ps "

# Mutating TOKENS, matched as whole words rather than as substrings. The substring form
# refused any command whose arguments merely CONTAINED "cp " or "rm " — an origin path
# such as `/Users/x/rm notes/` produced a refusal that read like an ssh failure.
ST_SSH_DENY_TOK=" rm mv cp tee truncate chmod chown chgrp mkdir rmdir touch ln dd unlink shred install kill pkill killall tar unzip curl wget nc sh bash zsh eval exec "

st_ssh_check_cmd() {
  local cmd="$1" scrubbed seg first sub denied
  # Strip the two benign redirections we do allow.
  scrubbed="$(printf '%s' "$cmd" | sed -e 's/2>&1//g' -e 's|2>/dev/null||g')"
  case "$scrubbed" in
    *">"*)  st_log "REFUSED (redirection to the origin): $cmd"; return 1 ;;
    *"sed -i"*|*"--delete"*|*"--inplace"*|*"--append"*)
      st_log "REFUSED (mutating flag): $cmd"; return 1 ;;
  esac
  # Allowlist the first word of every segment; deny mutating tokens anywhere, as WORDS.
  # (`sed s/&&/|/` first, then tr — BSD sed does not understand \n in a replacement, so
  # never emit newlines from sed.)
  # `|| [ -n "$seg" ]` is load-bearing: printf emits no trailing newline, so a command with
  # a single segment leaves `read` returning false with the segment still in $seg. Without
  # it the loop body never ran for one-segment commands and everything was allowed.
  # NOTE the command substitution rather than `... | grep -q`: with `set -o pipefail`
  # (which every caller sets) a pipeline's status is polluted by every stage, so the
  # grep's verdict was being thrown away and everything came back ALLOW.
  denied="$(printf '%s' "$scrubbed" | sed -e 's/&&/|/g' | tr '|;' '\n\n' | while IFS= read -r seg || [ -n "$seg" ]; do
    seg="$(printf '%s' "$seg" | sed -e 's/^[[:space:]]*//')"
    [ -z "$seg" ] && continue
    first="$(printf '%s' "$seg" | awk '{print $1}')"
    case "$ST_SSH_ALLOW" in
      *" $first "*) : ;;
      *) printf 'DENY %s\n' "$first"; continue ;;
    esac
    # whole-word mutating tokens anywhere in the segment (catches `find ... -exec rm`)
    printf '%s' "$seg" | tr ' \t' '\n\n' | while IFS= read -r w || [ -n "$w" ]; do
      [ -z "$w" ] && continue
      case "$ST_SSH_DENY_TOK" in
        *" $w "*) printf 'DENY tok:%s\n' "$w" ;;
      esac
    done
    # `git` is on the allowlist, but only for read-only porcelain. Matching on the literal
    # string "git commit" is not enough: `git -C /path commit` slips straight past it. So
    # skip the global options and allowlist the SUBCOMMAND.
    if [ "$first" = "git" ]; then
      sub="$(printf '%s' "$seg" | awk '{
        skip = 0
        for (i = 2; i <= NF; i++) {
          t = $i
          if (skip) { skip = 0; continue }
          if (substr(t, 1, 1) == "-") {
            if (t == "-C" || t == "-c" || t == "--git-dir" || t == "--work-tree" || t == "--exec-path") skip = 1
            continue
          }
          print t; exit
        }}')"
      case " ls-files ls-tree rev-parse rev-list cat-file fsck status log show diff count-objects for-each-ref describe var version " in
        *" $sub "*) : ;;
        *) printf 'DENY git-%s\n' "${sub:-<none>}" ;;
      esac
    fi
  done)"
  case "$denied" in
    *DENY*)
      st_log "REFUSED (not on the read-only allowlist): $cmd"
      st_log "  offending token(s): $(printf '%s' "$denied" | tr '\n' ' ')"
      return 1 ;;
  esac
  return 0
}

st_ssh_ro() {    # st_ssh_ro HOST CMD    — read-only remote command, stdout passed through
  local host="$1"; shift
  local cmd="$*"
  st_ssh_check_cmd "$cmd" || return 90
  # shellcheck disable=SC2086
  ssh $ST_SSH_OPTS "$host" "$cmd"
}

st_local_ro() {  # st_local_ro CMD  — the SAME gate, applied to a same-host "origin"
  local cmd="$*"
  st_ssh_check_cmd "$cmd" || return 90
  sh -c "$cmd"
}

st_ssh_py() {    # st_ssh_py HOST SCRIPT_PATH [ARGS...] — ship a python helper over STDIN
  local host="$1" script="$2"; shift 2
  local args=""
  local a
  for a in "$@"; do args="$args '$(printf '%s' "$a" | sed "s/'/'\\\\''/g")'"; done
  st_ssh_check_cmd "python3 - $args" || return 90
  # shellcheck disable=SC2086
  ssh $ST_SSH_OPTS "$host" "python3 - $args" < "$script"
}

st_ssh_alive() { # st_ssh_alive HOST
  st_ssh_ro "$1" "uname -sr" >/dev/null 2>&1
}

# ---------------------------------------------------------------- process checks
# F21: `pgrep -af 'user-data-dir=.*<instance>'` SELF-MATCHES and reports false positives.
# Never `pkill -f` in these scripts either — it self-matched and killed a run.
st_instance_running() {   # st_instance_running USER_DATA_DIR -> prints matching lines
  ps -eo pid,comm,args 2>/dev/null | awk -v pat="$1" -v me="$$" -v par="$PPID" '
    NR > 1 && $1 != me && $1 != par && tolower($2) ~ /claude|electron/ && index($0, pat) > 0 { print }'
}

st_any_claude_running() { # any claude/electron process on this host at all
  ps -eo pid,comm,args 2>/dev/null | awk -v me="$$" -v par="$PPID" '
    NR > 1 && $1 != me && $1 != par && tolower($2) ~ /claude|electron/ { print }'
}

# ---------------------------------------------------------------- confirmation
# The final confirmation is a TYPED VALUE, never a y/n — it forces the operator to have
# read the summary and defeats reflexive assent.
#
# There is no controlling terminal inside an agent harness. Rather than making the whole
# write-back path unreachable there, the agent may pass the SAME number it would have
# typed via --confirm-count / ST_CONFIRM_COUNT — but only after obtaining that number
# from the user in chat. It is still a typed value; the human just types it one layer up.
st_confirm_typed() {      # st_confirm_typed EXPECTED PROMPT
  local expected="$1" prompt="$2" answer=""
  printf '%s\n' "$prompt" >&2
  if [ -n "${ST_CONFIRM_COUNT:-}" ]; then
    if [ "$ST_CONFIRM_COUNT" = "$expected" ]; then
      st_log "confirmation supplied non-interactively: --confirm-count $expected"
      st_log "  (this is only legitimate if the user typed that number themselves)"
      return 0
    fi
    st_log "REFUSED: --confirm-count '$ST_CONFIRM_COUNT' != the actual count '$expected'"
    return 1
  fi
  if [ ! -t 0 ]; then
    st_log "REFUSED: stdin is not a terminal and no --confirm-count was given."
    st_log "  Re-run this step from a real terminal, or pass --confirm-count $expected"
    st_log "  after the user has confirmed that number."
    return 1
  fi
  printf 'Type exactly "%s" to proceed (anything else aborts): ' "$expected" >&2
  IFS= read -r answer
  [ "$answer" = "$expected" ] || { st_log "aborted (typed: $answer)"; return 1; }
  return 0
}

# ---------------------------------------------------------------- profile
# A profile is a plain shell file setting ST_* variables, so a migration can be re-run
# and audited.
#
# CLI FLAGS MUST WIN. They did not: `st_load_profile` used to be called from inside the
# argument loop, so it sourced the file at the point `--profile` appeared in argv and
# clobbered every ST_* already set by an earlier flag. Callers now run
# `st_preparse_profile "$@"` BEFORE their argument loop, and treat `--profile` as a no-op
# inside it.
st_preparse_profile() {
  local prev=""
  local a
  for a in "$@"; do
    if [ "$prev" = "--profile" ]; then
      st_load_profile "$a"
      prev=""
      continue
    fi
    case "$a" in
      --profile) prev="--profile" ;;
      --profile=*) st_load_profile "${a#--profile=}" ;;
      *) prev="" ;;
    esac
  done
  return 0
}

st_load_profile() {
  [ -n "${1:-}" ] || return 0
  [ -r "$1" ] || st_die "profile not readable: $1"
  # shellcheck disable=SC1090
  . "$1"
  st_log "profile loaded: $1  (command-line flags override everything in it)"
  st_placeholder_guard
}

# profile.example ships deliberately-bogus values. Catch a template that was copied and
# only half filled in, before it points --apply at something real.
st_placeholder_guard() {
  local v n
  for n in ST_ORIGIN_HOST ST_ORIGIN_ROOT ST_ORIGIN_CLAUDE ST_ORIGIN_KEY ST_SESSION_ID \
           ST_DEST_ROOT ST_USER_DATA_DIR ST_ACCOUNT ST_ORG ST_CKPT_ROOT; do
    eval "v=\${$n:-}"
    case "$v" in
      *"REPLACE-ME"*|*"<"*">"*|*"/path/to/"*|*"EXAMPLE"*)
        st_die "$n still holds a template placeholder ('$v'). Fill the profile in from st-preflight.sh's output." ;;
    esac
  done
  return 0
}

st_require_var() {        # st_require_var NAME FLAGNAME
  eval "local v=\${$1:-}"
  [ -n "$v" ] || st_die "missing $2 (or $1 in the profile)"
}

st_summary() {            # st_summary LABEL
  st_hr
  if [ "$ST_FAIL" -eq 0 ]; then
    st_log "$1: PASS   (warnings: $ST_WARN_N)"
  else
    st_log "$1: FAIL   ($ST_FAIL failed checks, $ST_WARN_N warnings)"
  fi
  st_hr
  [ "$ST_FAIL" -eq 0 ]
}
