#!/usr/bin/env bash
# st-checkpoint.sh — G3. Pull a VERIFIED, SEALED checkpoint of a session + its project
# tree from an origin host. READ-ONLY on the origin: rsync pull only, every other remote
# call goes through the read-only ssh chokepoint.
#
# Generalised from the pull-checkpoint.sh that produced the checkpoint the real migration
# ran from. Every guard below exists because something went wrong without it:
#
#   M1  excludes must be ANCHORED and JUSTIFIED. `--exclude='_research/re/rust/'` was
#       meant to skip a cargo target dir and instead dropped 26 irreplaceable source
#       files; `--exclude='_research/re/target/'` assumed "target == build output" when
#       it was the ground-truth binary drop dir. So: this script refuses an unanchored
#       or unjustified pattern, and PRINTS the file+byte count each pattern removes. An
#       over-broad exclude must show up as a NUMBER, never as silence.
#   M2  verification must diff a REMOTE-side manifest against a LOCAL-side manifest, and
#       COVERAGE (are all files present) is a SEPARATE gate from FIDELITY (do the bytes
#       match). A corpus can be 100% faithful and 60% complete.
#   M3  whitelist, never blacklist, when copying out of a ~/.claude. Enumerate the exact
#       paths belonging to the session; then assert the DENYLIST over the staged bytes,
#       independently.
#   M5  publish (advance `latest`) only after verification passes, and write the COMPLETE
#       sentinel last. A crashed run must never become the next run's --link-dest base.
#
# Default action is --plan (accounting only, no transfer). Pass --apply to transfer.
set -uo pipefail

ST_SELF="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=st-common.sh
. "$ST_SELF/st-common.sh"

usage() {
  cat <<'EOF'
st-checkpoint.sh — pull a verified, sealed checkpoint from an origin host.

  --profile FILE          shell file presetting ST_* variables (FLAGS WIN)
  --plan                  accounting only: exclude attribution + inventory (DEFAULT)
  --apply                 actually transfer          (--run is a deprecated alias)

ORIGIN
  --origin-host HOST      ssh host ("local" for a same-host copy or an offline archive)
  --origin-root PATH      project root on the origin
  --origin-claude PATH    origin ~/.claude (default: ~/.claude there)
  --origin-key KEY        LITERAL project-dir name observed on the origin.
                          Omit to take it from the probe. NEVER derive one by editing
                          another key — the mangler is not injective.
  --all-transcript-keys   when several keys hold this session's transcript (git worktrees),
                          take ALL of them instead of refusing
  --session-id UUID       transcript stem

OUTPUT
  --checkpoint-root DIR   generations live in DIR/<UTC-ts>/, published via
                          DIR/latest and DIR/latest-<SESSION-ID>

WHAT TO TAKE
  --exclude-file FILE     one pattern per line, "PATTERN  # justification"
  --exclude 'PAT#why'     inline pattern + justification (repeatable)
  --no-excludes           take the project tree whole (still prints the accounting)
  --skill NAME            copy this global skill (repeatable). Default: none.
  --skills-all            copy every global skill (audit sizes first: one skill was 321 MB)
  --include-agents        also take ~/.claude/agents/       (custom subagent definitions)
  --include-commands      also take ~/.claude/commands/     (custom slash commands)
  --include-output-styles also take ~/.claude/output-styles/
  --no-memory             do not take the project memory/ (it is project-wide, not per session: on a shared
                          project key it holds notes from OTHER sessions)
  --include-user-memory   also take ~/.claude/CLAUDE.md     (HOST-wide user memory; review it,
                          it usually contains the origin's absolute paths)
  --include-plugins       copy plugins/ too. Default off: absolute installPath +
                          per-arch binaries make plugins REGENERATE-not-copy.
  --project-only          skip the ~/.claude side
  --session-only          skip the project tree (offline archive, session-only move)
  --allow-extra           do not fail when the copy holds paths the origin manifest does
                          not. Off by default: that divergence is the M3 shape.

OTHER
  --probe-json FILE       reuse the JSON that st-preflight.sh --json wrote
  --jobs N                hashing threads per side (default 8)
  -h | --help

An UNANCHORED exclude must be written as `unanchored:PATTERN  # why`. There is no flag
that turns the justification requirement off.
EOF
}

st_preparse_profile "$@"

ST_ORIGIN_HOST="${ST_ORIGIN_HOST:-}"
ST_ORIGIN_ROOT="${ST_ORIGIN_ROOT:-}"
ST_ORIGIN_CLAUDE="${ST_ORIGIN_CLAUDE:-}"
ST_ORIGIN_KEY="${ST_ORIGIN_KEY:-}"
ST_SESSION_ID="${ST_SESSION_ID:-}"
ST_CKPT_ROOT="${ST_CKPT_ROOT:-}"
EXCL_FILE=""; NO_EXCL=0; RUN=0
SKILLS=""; SKILLS_ALL=0; INC_PLUGINS=0; PROJECT_ONLY=0; SESSION_ONLY=0
INC_AGENTS=0; INC_COMMANDS=0; INC_STYLES=0; INC_USER_MEM=0; NO_MEM=0
ALL_TX_KEYS=0; ALLOW_EXTRA=0
PROBE_JSON_IN=""; JOBS=8
INLINE_EXCL_FILE=""

while [ $# -gt 0 ]; do
  case "$1" in
    --profile)          shift 2 ;;
    --profile=*)        shift ;;
    --plan)             RUN=0; shift ;;
    --apply|--run)      RUN=1; shift ;;
    --origin-host)      ST_ORIGIN_HOST="$2"; shift 2 ;;
    --origin-root)      ST_ORIGIN_ROOT="$2"; shift 2 ;;
    --origin-claude)    ST_ORIGIN_CLAUDE="$2"; shift 2 ;;
    --origin-key)       ST_ORIGIN_KEY="$2"; shift 2 ;;
    --all-transcript-keys) ALL_TX_KEYS=1; shift ;;
    --session-id)       ST_SESSION_ID="$2"; shift 2 ;;
    --checkpoint-root)  ST_CKPT_ROOT="$2"; shift 2 ;;
    --exclude-file)     EXCL_FILE="$2"; shift 2 ;;
    --exclude)
        [ -n "$INLINE_EXCL_FILE" ] || INLINE_EXCL_FILE="$(mktemp "${TMPDIR:-/tmp}/st-excl.XXXXXX")"
        printf '%s\n' "$2" | tr '#' '\t' | awk -F'\t' '{p=$1; sub(/[ \t]+$/,"",p); j=$2; print p "\t#" j}' >> "$INLINE_EXCL_FILE"
        shift 2 ;;
    --no-excludes)      NO_EXCL=1; shift ;;
    --skill)            SKILLS="$SKILLS $2"; shift 2 ;;
    --skills-all)       SKILLS_ALL=1; shift ;;
    --include-agents)   INC_AGENTS=1; shift ;;
    --include-commands) INC_COMMANDS=1; shift ;;
    --include-output-styles) INC_STYLES=1; shift ;;
    --include-user-memory)   INC_USER_MEM=1; shift ;;
    --no-memory)             NO_MEM=1; shift ;;
    --include-plugins)  INC_PLUGINS=1; shift ;;
    --project-only)     PROJECT_ONLY=1; shift ;;
    --session-only)     SESSION_ONLY=1; shift ;;
    --allow-extra)      ALLOW_EXTRA=1; shift ;;
    --probe-json)       PROBE_JSON_IN="$2"; shift 2 ;;
    --jobs)             JOBS="$2"; shift 2 ;;
    -h|--help)          usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

st_need python3 rsync
st_require_var ST_SESSION_ID  --session-id
st_require_var ST_CKPT_ROOT   --checkpoint-root
[ "$SESSION_ONLY" -eq 1 ] || st_require_var ST_ORIGIN_ROOT --origin-root

LOCAL_ORIGIN=0
case "${ST_ORIGIN_HOST:-local}" in local|localhost|"") LOCAL_ORIGIN=1 ;; esac
[ "$LOCAL_ORIGIN" -eq 1 ] || st_need ssh
SID="$ST_SESSION_ID"

TS="$(st_ts)"
GEN="$ST_CKPT_ROOT/$TS"
st_banner "ST-CHECKPOINT  $TS   $( [ "$RUN" -eq 1 ] && echo '[APPLY]' || echo '[PLAN — nothing will be transferred]')"
st_log "origin      ${ST_ORIGIN_HOST:-<local>}:${ST_ORIGIN_ROOT:-<session only>}"
st_log "generation  $GEN"

# ------------------------------------------------------------------ remote helpers
remote_walk() {   # remote_walk ARGS...
  if [ "$LOCAL_ORIGIN" -eq 1 ]; then
    python3 "$ST_SELF/st_walk.py" "$@"
  else
    st_ssh_py "$ST_ORIGIN_HOST" "$ST_SELF/st_walk.py" "$@"
  fi
}
remote_probe() {  # remote_probe ARGS...
  if [ "$LOCAL_ORIGIN" -eq 1 ]; then
    python3 "$ST_SELF/st_origin_probe.py" "$@"
  else
    st_ssh_py "$ST_ORIGIN_HOST" "$ST_SELF/st_origin_probe.py" "$@"
  fi
}
rsrc() {          # rsrc PATH -> rsync source spec
  if [ "$LOCAL_ORIGIN" -eq 1 ]; then printf '%s' "$1"; else printf '%s:%s' "$ST_ORIGIN_HOST" "$1"; fi
}

# ------------------------------------------------------------------ probe
PROBE="$(mktemp "${TMPDIR:-/tmp}/st-ckpt-probe.XXXXXX")" || st_die "mktemp failed"
PROBE_ERR="$(mktemp "${TMPDIR:-/tmp}/st-ckpt-perr.XXXXXX")"
TMPS="$PROBE $PROBE_ERR"
cleanup() { for f in $TMPS; do rm -f "$f"; done; }
trap cleanup EXIT

if [ -n "$PROBE_JSON_IN" ] && [ -s "$PROBE_JSON_IN" ]; then
  cp "$PROBE_JSON_IN" "$PROBE"; st_ok "reusing probe JSON $PROBE_JSON_IN"
else
  st_info "probing the origin"
  set -- --session-id "$SID"
  [ -n "$ST_ORIGIN_ROOT" ]   && set -- "$@" --project-root "$ST_ORIGIN_ROOT"
  [ -n "$ST_ORIGIN_CLAUDE" ] && set -- "$@" --claude-home "$ST_ORIGIN_CLAUDE"
  # `--opt=VALUE`, never `--opt VALUE`: EVERY project key begins with '-' (the mangler
  # maps the leading '/' of an absolute path to a dash), and argparse reads a leading-dash
  # value as the next option — "error: argument --origin-key: expected one argument".
  [ -n "$ST_ORIGIN_KEY" ]    && set -- "$@" "--origin-key=$ST_ORIGIN_KEY"
  remote_probe "$@" > "$PROBE" 2>"$PROBE_ERR"
  rc=$?
  if [ $rc -ne 0 ] || [ ! -s "$PROBE" ]; then
    st_log "probe stderr (the reason, which used to be discarded):"
    head -20 "$PROBE_ERR" | while IFS= read -r l; do st_log "    $l"; done
    st_die "origin probe failed rc=$rc"
  fi
  st_ok "origin probed"
fi

RC_HOME="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["claude_home"])' "$PROBE")"
[ -n "$ST_ORIGIN_CLAUDE" ] && RC_HOME="$ST_ORIGIN_CLAUDE"

TX_KEYS="$(python3 -c '
import json,sys
d=json.load(open(sys.argv[1]))
print(" ".join(d.get("keys_with_transcript") or []))' "$PROBE")"
N_TX_KEYS=0
for k in $TX_KEYS; do N_TX_KEYS=$((N_TX_KEYS + 1)); done

KEY_GIVEN=0
if [ -n "$ST_ORIGIN_KEY" ]; then
  KEY_GIVEN=1
else
  ST_ORIGIN_KEY="$(python3 -c 'import json,sys;d=json.load(open(sys.argv[1]));print(d.get("origin_key") or "")' "$PROBE")"
fi
[ -n "$ST_ORIGIN_KEY" ] || st_die "could not determine the origin project key; pass --origin-key"

# A multi-key session is legitimate (git worktrees; the CLI appends in place in the
# sibling's project dir). Taking the first one silently is a coverage bug whose oracle is
# the whitelist itself, so it can never be detected downstream.
EXTRA_TX_KEYS=""
if [ "$N_TX_KEYS" -gt 1 ]; then
  if [ "$KEY_GIVEN" -eq 1 ] && [ "$ALL_TX_KEYS" -eq 0 ]; then
    st_warn "$N_TX_KEYS keys hold $SID.jsonl; --origin-key selected one and the others are"
    st_warn "  NOT in the plan. Pass --all-transcript-keys to stage them too:"
    for k in $TX_KEYS; do [ "$k" = "$ST_ORIGIN_KEY" ] || st_log "        $k"; done
  elif [ "$ALL_TX_KEYS" -eq 1 ]; then
    for k in $TX_KEYS; do [ "$k" = "$ST_ORIGIN_KEY" ] || EXTRA_TX_KEYS="$EXTRA_TX_KEYS $k"; done
    st_warn "$N_TX_KEYS keys hold $SID.jsonl; --all-transcript-keys: taking all of them."
    st_warn "  Only the PRIMARY one is transplanted automatically; the others are staged under"
    st_warn "  claude/projects/<key>/ for you to place deliberately."
  else
    st_bad "$N_TX_KEYS project keys each contain $SID.jsonl:"
    for k in $TX_KEYS; do st_log "        $k"; done
    st_bad "  Pick one with --origin-key, or take them all with --all-transcript-keys."
    st_bad "  Refusing to guess: the alphabetically-first key is not a decision."
  fi
fi
st_ok "origin claude home : $RC_HOME"
st_ok "origin project key : $ST_ORIGIN_KEY  (literal, as observed)"

SIBLINGS="$(python3 -c '
import json,sys
d=json.load(open(sys.argv[1]))
print(" ".join(sorted((d.get("inventory") or {}).get("sibling_keys") or {})))' "$PROBE")"
[ -n "$SIBLINGS" ] && st_info "sibling project keys: $SIBLINGS"

# ------------------------------------------------------------------ excludes
PATFILE="$(mktemp "${TMPDIR:-/tmp}/st-pats.XXXXXX")"; TMPS="$TMPS $PATFILE"
: > "$PATFILE"
JUSTFILE="$(mktemp "${TMPDIR:-/tmp}/st-just.XXXXXX")"; TMPS="$TMPS $JUSTFILE"
: > "$JUSTFILE"

collect_pats() {  # collect_pats FILE
  local line pat just
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in ''|\#*) continue ;; esac
    pat="$(printf '%s' "$line" | sed -e 's/[[:space:]]*#.*$//' -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
    just="$(printf '%s' "$line" | sed -n 's/^[^#]*#[[:space:]]*//p')"
    [ -n "$pat" ] || continue
    # The justification requirement is UNCONDITIONAL. It used to share a flag with the
    # anchoring requirement, so an operator who legitimately wanted `unanchored:*.pyc`
    # switched off justification for every pattern in the file at the same time.
    if [ -z "$just" ]; then
      st_die "exclude pattern '$pat' has no justification. Format: PATTERN  # why. Justify it against an actual listing of that directory, not against what its name suggests."
    fi
    # An unanchored pattern matches by NAME anywhere in the tree. That is sometimes what
    # you want (*.pyc, .DS_Store) and sometimes how you lose a directory that merely
    # shares a name with build output. It must therefore be declared, not assumed:
    # write it as `unanchored:PATTERN  # why`.
    case "$pat" in
      unanchored:*) pat="${pat#unanchored:}" ;;
      /*) : ;;
      *)  st_die "exclude pattern '$pat' is UNANCHORED (no leading '/'): it matches by NAME anywhere in the tree. That is exactly how 26 irreplaceable source files were lost, and how the ground-truth binary drop dir was nearly dropped for being called 'target'. Either anchor it ('/path/to/$pat'), or declare it deliberately as 'unanchored:$pat  # why'." ;;
    esac
    printf '%s\n' "$pat" >> "$PATFILE"
    printf '%s\t%s\n' "$pat" "$just" >> "$JUSTFILE"
  done < "$1"
}

if [ "$NO_EXCL" -eq 0 ] && [ "$SESSION_ONLY" -eq 0 ]; then
  [ -n "$EXCL_FILE" ] && { [ -r "$EXCL_FILE" ] || st_die "--exclude-file not readable: $EXCL_FILE"; collect_pats "$EXCL_FILE"; }
  [ -n "$INLINE_EXCL_FILE" ] && collect_pats "$INLINE_EXCL_FILE"
  if [ ! -s "$PATFILE" ]; then
    st_die "no excludes given. Pass --exclude-file / --exclude, or --no-excludes to take the tree whole. Silence is not a default here. (With --session-only no project tree is transferred and this requirement does not apply.)"
  fi
elif [ "$SESSION_ONLY" -eq 1 ]; then
  st_info "--session-only: no project tree is transferred, so no exclude decision is needed"
fi

NPAT=$(wc -l < "$PATFILE" | tr -d ' ')
if [ "$NPAT" -gt 0 ]; then
  st_log ""
  st_log "EXCLUDES ($NPAT), each with the justification you supplied:"
  while IFS="$(printf '\t')" read -r p j; do
    st_log "  $(printf '%-46s' "$p") $j"
  done < "$JUSTFILE"
fi

# ------------------------------------------------------------------ PLAN: attribution
if [ "$SESSION_ONLY" -eq 0 ]; then
  st_log ""
  st_log "EXCLUDE ATTRIBUTION on the origin project tree (the M1 guard):"
  ACC="$(mktemp "${TMPDIR:-/tmp}/st-acc.XXXXXX")"; TMPS="$TMPS $ACC"
  set -- --root "$ST_ORIGIN_ROOT" --explain-excludes
  while IFS= read -r p; do set -- "$@" --exclude "$p"; done < "$PATFILE"
  if remote_walk "$@" > "$ACC" 2>/dev/null; then
    sed 's/^/  /' "$ACC" | while IFS= read -r l; do st_log "$l"; done
    KEPT_N=$(awk '/^  \(KEPT\)/{print $2}' "$ACC" | tail -1)
    KEPT_B=$(awk '/^  \(KEPT\)/{print $3}' "$ACC" | tail -1)
    st_log "  -> $KEPT_N files / $KEPT_B bytes will be pulled from the project tree"
  else
    st_bad "exclude attribution failed — refusing to transfer blind"
    KEPT_N=""; KEPT_B=""
  fi
fi

# ---- the ~/.claude side: STRICT WHITELIST (M3), filtered by what actually EXISTS ----
# A short or fresh session has no memory/, no tasks/<sid>/ and no sidecar directory. Those
# absences are normal. Transferring them anyway produced four rsync exit-23 failures, which
# the M5 guard then correctly refused to publish — turning a perfectly good checkpoint of a
# perfectly ordinary session into an unrecoverable refusal.
CLAUDE_RELS=""
WANT_RELS=""
if [ "$PROJECT_ONLY" -eq 0 ]; then
  want() { WANT_RELS="$WANT_RELS $1"; }
  want "projects/$ST_ORIGIN_KEY/$SID.jsonl"
  want "projects/$ST_ORIGIN_KEY/$SID"
  [ "$NO_MEM" -eq 1 ] || want "projects/$ST_ORIGIN_KEY/memory"
  for k in $EXTRA_TX_KEYS; do want "projects/$k/$SID.jsonl"; done
  for k in $SIBLINGS; do want "projects/$k/$SID"; [ "$NO_MEM" -eq 1 ] || want "projects/$k/memory"; done
  [ "$NO_MEM" -eq 1 ] && st_log "  --no-memory: project memory/ is NOT taken"
  want "tasks/$SID"
  want "settings.json"
  if [ "$SKILLS_ALL" -eq 1 ]; then
    want "skills"
    st_warn "--skills-all: copying every global skill. On the run that worked this pulled a"
    st_warn "  321 MB skill whose bulk was a bundled .venv with two Node runtimes (O6)."
  else
    for s in $SKILLS; do want "skills/$s"; done
  fi
  [ "$INC_AGENTS" -eq 1 ]   && want "agents"
  [ "$INC_COMMANDS" -eq 1 ] && want "commands"
  [ "$INC_STYLES" -eq 1 ]   && want "output-styles"
  [ "$INC_USER_MEM" -eq 1 ] && { want "CLAUDE.md"; st_warn "--include-user-memory: ~/.claude/CLAUDE.md is HOST-wide and usually names the origin's absolute paths. Review it at the destination before trusting it."; }
  [ "$INC_PLUGINS" -eq 1 ] && { want "plugins"; st_warn "--include-plugins: plugins carry absolute installPath and per-arch binaries; prefer reinstalling at the destination"; }

  st_log ""
  st_log "  ~/.claude whitelist — checking which entries actually exist on the origin:"
  set -- --root "$RC_HOME" --exists
  for r in $WANT_RELS; do set -- "$@" --rel "$r"; done
  EXISTS="$(remote_walk "$@" 2>/dev/null)"
  if [ -z "$EXISTS" ]; then
    st_bad "could not determine which whitelist entries exist on the origin"
  else
    while IFS="$(printf '\t')" read -r r kind; do
      [ -n "$r" ] || continue
      case "$kind" in
        missing) st_log "    -- $(printf '%-58s' "$r") not present on the origin (skipped)" ;;
        *)       st_log "    OK $(printf '%-58s' "$r") $kind"; CLAUDE_RELS="$CLAUDE_RELS $r" ;;
      esac
    done <<EOF
$EXISTS
EOF
  fi
  case " $CLAUDE_RELS " in
    *" projects/$ST_ORIGIN_KEY/$SID.jsonl "*) : ;;
    *) st_bad "the transcript itself (projects/$ST_ORIGIN_KEY/$SID.jsonl) is not present on the origin" ;;
  esac
  st_log "  NOT taken, by policy: .credentials.json, ~/.claude.json, backups/, history.jsonl,"
  st_log "    telemetry/, sessions/, shell-snapshots/, session-env/, cache/, stats-cache.json,"
  st_log "    policy-limits.json, other sessions' tasks/, other sessions' transcripts"
fi

if [ "$RUN" -eq 0 ]; then
  st_log ""
  st_log "PLAN ONLY. Re-run with --apply to transfer."
  st_summary "CHECKPOINT-PLAN"; exit $?
fi
[ "$ST_FAIL" -eq 0 ] || { st_log "refusing to transfer with failures already recorded"; exit 1; }

# ------------------------------------------------------------------ generation setup
mkdir -p "$GEN/project" "$GEN/claude" "$GEN/manifest" "$GEN/logs" || st_die "cannot create $GEN"
ST_LOGFILE="$GEN/logs/run.log"
cp "$PROBE" "$GEN/manifest/origin-probe.json"
cp "$JUSTFILE" "$GEN/manifest/excludes.tsv" 2>/dev/null
[ -n "${ACC:-}" ] && cp "$ACC" "$GEN/manifest/exclude-accounting.txt" 2>/dev/null

# --link-dest must point at the newest generation that carries the COMPLETE sentinel —
# never at `latest` blindly, and never at a crashed run (M5).
PREV=""
for d in "$ST_CKPT_ROOT"/*/; do
  d="${d%/}"
  # NEVER follow `latest`: it is a symlink, it sorts last, and pointing --link-dest at it
  # silently reintroduces exactly the failure the COMPLETE sentinel exists to prevent.
  [ -L "$d" ] && continue
  [ -d "$d" ] || continue
  [ -f "$d/COMPLETE" ] || continue
  [ "$d" = "$GEN" ] && continue
  PREV="$d"
done
# --link-dest is resolved RELATIVE TO THE DESTINATION DIRECTORY, so it must name the
# corresponding subtree of the previous generation, not the generation root. Pointing it
# at the root silently hardlinks nothing: every file is re-transferred and each generation
# costs full size. (Verified by `Number of regular files transferred` in the rsync stats.)
LD=""
if [ -n "$PREV" ]; then
  LD="--link-dest=$PREV/project"
  st_ok "hardlink base: $PREV (has COMPLETE)"
  st_info "NEVER combine --link-dest with --inplace/--append: writing through a hardlink"
  st_info "mutates every earlier generation sharing that inode"
else
  st_info "no COMPLETE generation to hardlink against; this is a full pull"
fi

# ------------------------------------------------------------------ manifests: REMOTE
st_log ""
st_log "REMOTE manifests (the source of truth we verify against — M2)"
if [ "$SESSION_ONLY" -eq 0 ]; then
  set -- --root "$ST_ORIGIN_ROOT" --jobs "$JOBS"
  while IFS= read -r p; do set -- "$@" --exclude "$p"; done < "$PATFILE"
  remote_walk "$@" > "$GEN/manifest/remote-project.tsv" 2>"$GEN/logs/remote-project.err"
  rc=$?
  [ $rc -eq 0 ] || st_bad "remote project manifest failed rc=$rc"
  RN=$(grep -v '^#' "$GEN/manifest/remote-project.tsv" 2>/dev/null | wc -l | tr -d ' ')
  st_ok "remote project manifest: $RN files"
  # oddities went to a .err file nobody read. Surface them: they are the walker's own
  # blind spots, and a blind spot shared by the oracle and the copy is not a gate.
  grep -E '^st_walk: [0-9]+ (symlink|special|unreadable|missing)' "$GEN/logs/remote-project.err" 2>/dev/null \
    | while IFS= read -r l; do st_info "  ${l#st_walk: }"; done
  if [ -n "${KEPT_N:-}" ] && [ "$RN" != "$KEPT_N" ]; then
    st_bad "manifest count $RN != exclude-accounting KEPT count $KEPT_N — the two walks disagree; do not trust these excludes"
  elif [ -n "${KEPT_N:-}" ]; then
    st_ok "manifest count matches the exclude accounting exactly ($KEPT_N)"
  fi

  # FILENAME HAZARDS ARE SCANNED ON THE ORIGIN MANIFEST, BEFORE THE TRANSFER.
  # Scanning the landed copy cannot see the collision it exists to detect: on a
  # case-insensitive destination the two names have already merged by then and the scan
  # reports 0.
  remote_walk --hazards "$GEN/manifest/remote-project.tsv" > "$GEN/manifest/filename-hazards.txt" 2>&1 \
    || python3 "$ST_SELF/st_walk.py" --hazards "$GEN/manifest/remote-project.tsv" \
       > "$GEN/manifest/filename-hazards.txt" 2>&1
  HZ_COLL=$(sed -n 's/^case_or_normalisation_collisions\t//p' "$GEN/manifest/filename-hazards.txt")
  HZ_NFD=$(sed -n 's/^nfd_names\t//p' "$GEN/manifest/filename-hazards.txt")
  DEST_CI="$(python3 - "$GEN" <<'PY'
import os, sys, tempfile
d = sys.argv[1]
try:
    fd, p = tempfile.mkstemp(prefix="STcase", dir=d)
    os.close(fd)
    other = os.path.join(os.path.dirname(p), os.path.basename(p).replace("STcase", "stCASE"))
    print("insensitive" if os.path.exists(other) else "sensitive")
    os.unlink(p)
except Exception:
    print("unknown")
PY
)"
  st_info "filename hazards on the ORIGIN names: ${HZ_COLL:-?} case/normalisation collisions, ${HZ_NFD:-?} NFD names"
  st_info "  checkpoint filesystem is case-$DEST_CI"
  if [ "${HZ_COLL:-0}" -gt 0 ]; then
    if [ "$DEST_CI" = "insensitive" ]; then
      st_bad "$HZ_COLL case/normalisation collision(s) landing on a CASE-INSENSITIVE filesystem:"
      st_bad "  the two names merge, one file's content is destroyed, and rsync reports success."
      st_bad "  Nothing fixes this in flight (openrsync has no --iconv). Rename on the origin first."
      grep '^  COLLIDE' "$GEN/manifest/filename-hazards.txt" | head -10 | while IFS= read -r l; do st_log "      $l"; done
    else
      st_warn "$HZ_COLL case/normalisation collision(s) in the payload. Harmless here (this"
      st_warn "  filesystem is case-sensitive) but FATAL on any later move to a case-insensitive"
      st_warn "  one — including a write-back to a macOS origin."
    fi
  fi
fi

if [ "$PROJECT_ONLY" -eq 0 ] && [ -n "$CLAUDE_RELS" ]; then
  set -- --root "$RC_HOME" --jobs "$JOBS" --exclude '.DS_Store'
  for r in $CLAUDE_RELS; do set -- "$@" --rel "$r"; done
  remote_walk "$@" > "$GEN/manifest/remote-claude.tsv" 2>"$GEN/logs/remote-claude.err"
  rc=$?
  [ $rc -eq 0 ] || st_bad "remote claude manifest failed rc=$rc"
  CN=$(grep -v '^#' "$GEN/manifest/remote-claude.tsv" 2>/dev/null | wc -l | tr -d ' ')
  st_ok "remote claude manifest: $CN files"
  # The floor is ONE: the transcript. A transcript-only session is a legitimate shape.
  [ "$CN" -ge 1 ] || st_bad "remote claude manifest has $CN files — the whitelist matched nothing"
fi

# ------------------------------------------------------------------ transfer
st_log ""
st_log "TRANSFER (pull direction only; --delete is never passed toward the origin)"
if [ "$SESSION_ONLY" -eq 0 ]; then
  set -- -a --stats --no-perms --no-owner --no-group
  [ -n "$LD" ] && set -- "$@" "$LD"      # = $PREV/project, matching this destination
  while IFS= read -r p; do set -- "$@" "--exclude=$p"; done < "$PATFILE"
  rsync "$@" "$(rsrc "$ST_ORIGIN_ROOT")/" "$GEN/project/" >> "$GEN/logs/rsync-project.log" 2>&1
  rc=$?
  [ $rc -eq 0 ] && st_ok "project tree pulled" || st_bad "rsync project rc=$rc (see logs/rsync-project.log)"
fi
if [ "$PROJECT_ONLY" -eq 0 ]; then
  for r in $CLAUDE_RELS; do
    mkdir -p "$GEN/claude/$(dirname "$r")"
    set -- -a --no-perms --no-owner --no-group --exclude='.DS_Store'
    # again: relative to THIS destination, which is $GEN/claude/$(dirname "$r")/
    [ -n "$PREV" ] && [ -d "$PREV/claude/$(dirname "$r")" ] && \
      set -- "$@" "--link-dest=$PREV/claude/$(dirname "$r")"
    rsync "$@" "$(rsrc "$RC_HOME/$r")" "$GEN/claude/$(dirname "$r")/" >> "$GEN/logs/rsync-claude.log" 2>&1
    rc=$?
    [ $rc -eq 0 ] || st_bad "rsync claude '$r' rc=$rc"
  done
  [ -n "$CLAUDE_RELS" ] && st_ok "claude whitelist pulled"
fi

# ------------------------------------------------------------------ verify
st_log ""
st_log "VERIFY — remote manifest vs local manifest, coverage and fidelity as separate gates"
if [ "$SESSION_ONLY" -eq 0 ] && [ -s "$GEN/manifest/remote-project.tsv" ]; then
  python3 "$ST_SELF/st_walk.py" --root "$GEN/project" --jobs "$JOBS" \
    > "$GEN/manifest/local-project.tsv" 2>/dev/null
  set -- --compare "$GEN/manifest/remote-project.tsv" "$GEN/manifest/local-project.tsv" \
         --label ORIGIN LOCAL
  # The remote manifest is produced by st_walk's exclude engine and the transfer by
  # rsync's. If they ever disagree, extra files land in the checkpoint — the M3 shape,
  # passing a green gate. So UNEXPECTED is a gate, not an INFO line, unless waived.
  [ "$ALLOW_EXTRA" -eq 1 ] || set -- "$@" --strict-extra
  python3 "$ST_SELF/st_walk.py" "$@" > "$GEN/manifest/DIFF-project.txt" 2>&1
  rc=$?
  sed 's/^/  /' "$GEN/manifest/DIFF-project.txt" | while IFS= read -r l; do st_log "$l"; done
  [ $rc -eq 0 ] && st_ok "project: coverage complete AND every byte identical" \
                || st_bad "project: verification FAILED (manifest/DIFF-project.txt)"
fi
if [ "$PROJECT_ONLY" -eq 0 ] && [ -s "$GEN/manifest/remote-claude.tsv" ]; then
  python3 "$ST_SELF/st_walk.py" --root "$GEN/claude" --jobs "$JOBS" \
    > "$GEN/manifest/local-claude.tsv" 2>/dev/null
  # The ~/.claude whitelist is EXACT, so --strict-extra is unconditional here: anything
  # in the staged copy that the origin manifest does not name is over-collection.
  python3 "$ST_SELF/st_walk.py" --compare "$GEN/manifest/remote-claude.tsv" \
    "$GEN/manifest/local-claude.tsv" --label ORIGIN LOCAL --strict-extra \
    > "$GEN/manifest/DIFF-claude.txt" 2>&1
  rc=$?
  sed 's/^/  /' "$GEN/manifest/DIFF-claude.txt" | while IFS= read -r l; do st_log "$l"; done
  [ $rc -eq 0 ] && st_ok "claude: coverage complete AND every byte identical" \
                || st_bad "claude: verification FAILED (manifest/DIFF-claude.txt)"
fi

# ---- transcript prefix invariant (tolerates concurrent appends) --------------
LOCAL_TX="$GEN/claude/projects/$ST_ORIGIN_KEY/$SID.jsonl"
if [ "$PROJECT_ONLY" -eq 0 ]; then
  if [ -f "$LOCAL_TX" ]; then
    L=$(st_size "$LOCAL_TX")
    LSHA=$(st_sha256 "$LOCAL_TX")
    REM="$(remote_walk --root "$RC_HOME/projects/$ST_ORIGIN_KEY/$SID.jsonl" --prefix-sha "$L" 2>/dev/null)"
    RSHA=$(printf '%s' "$REM" | cut -f1)
    RSIZE=$(printf '%s' "$REM" | cut -f3)
    if [ -z "$RSHA" ]; then
      st_skip "transcript prefix invariant (remote prefix hash did not execute)"
    elif [ "$RSHA" = "$LSHA" ]; then
      st_ok "transcript prefix invariant holds over all $L bytes"
      st_ok "  sha256 $LSHA"
      [ -n "$RSIZE" ] && [ "$RSIZE" -gt "$L" ] && st_info "the origin has grown to $RSIZE bytes since the copy started; that is expected and legal — JSONL is append-only"
    else
      st_bad "transcript prefix MISMATCH: local $LSHA vs origin-prefix $RSHA"
    fi
    LASTBYTE=$(tail -c 1 "$LOCAL_TX" | od -An -tx1 | tr -d ' \n')
    [ "$LASTBYTE" = "0a" ] && st_ok "transcript ends with LF" || st_bad "transcript does not end with LF — torn copy"
    tail -n 1 "$LOCAL_TX" | python3 -c 'import json,sys; json.loads(sys.stdin.readline())' 2>/dev/null \
      && st_ok "last line parses as JSON" \
      || st_bad "last line does not parse — mid-line tear; re-run rather than repairing in place"
    printf '%s\n' "$L" > "$GEN/manifest/transcript-prefix-len.txt"
    printf '%s\n' "$LSHA" > "$GEN/manifest/transcript-sha256.txt"
  else
    st_bad "transcript not present in the checkpoint: $LOCAL_TX"
  fi
fi

# ---- independent DENYLIST assertion over the staged bytes (M3) ---------------
st_log ""
st_log "DENYLIST assertion over the staged bytes (independent of the whitelist)"
python3 - "$GEN/claude" >&2 <<'PY'
import os, sys
DENY = ('.credentials.json', '.claude.json', 'history.jsonl', 'stats-cache.json',
        'policy-limits.json', 'ant-did', 'ant-device-registry.json', 'Local State',
        'config.json')
DENY_DIRS = ('backups', 'telemetry', 'sessions', 'shell-snapshots', 'session-env',
             'cache', 'file-history', 'paste-cache', 'downloads', 'Local Storage',
             'IndexedDB', 'Cookies')
# Vendored trees deliberately brought along (a skill's bundled .venv, a plugin
# marketplace clone) contain files whose NAMES match the denylist and whose contents are
# nothing of the kind — certifi's cacert.pem, setuptools' `downloads` fixture dir, a
# plugin's own config.json. A gate that cries wolf is a gate reviewers learn to skip,
# which is exactly how an M3-class error survives review. Their bytes were already
# accounted for by the whitelist decision that pulled them.
EXEMPT_TOP = ('skills', 'plugins', 'agents', 'commands', 'output-styles')
root = sys.argv[1]
hits = []
exempted = 0
for base, dirs, files in os.walk(root):
    rel = os.path.relpath(base, root)
    parts = [] if rel == '.' else rel.split(os.sep)
    top = parts[0] if parts else None
    for d in list(dirs):
        if d in DENY_DIRS:
            if top in EXEMPT_TOP:
                exempted += 1
            else:
                hits.append(os.path.join(rel, d))
    for f in files:
        if f in DENY:
            if top in EXEMPT_TOP:
                exempted += 1
            else:
                hits.append(os.path.join(rel, f))
if exempted:
    print("     %d denylist-shaped name(s) inside a deliberately-copied shared asset "
          "(skills/plugins/agents/...) — exempt, they came with a whitelist decision" % exempted)
if hits:
    print("FAIL %d denied path(s) present in the staged checkpoint:" % len(hits))
    for h in hits[:40]:
        print("     %s" % h)
    sys.exit(1)
print("OK   no account-coupled or host-coupled path was collected")
PY
rc=$?
[ $rc -eq 0 ] && st_ok "denylist clean" || st_bad "DENYLIST VIOLATION — see above; delete this generation"

# ---- sensitive-path inventory (locate and flag; never open) ------------------
if [ "$SESSION_ONLY" -eq 0 ]; then
  { echo "# Sensitive paths present in this checkpoint — gitignore them, never commit them."
    echo "# Located by NAME/PATH only. No file below was opened, read, or hashed for content."
    find "$GEN/project" \( -path '*/server_keys/*' -o -path '*/captures/*' -o -name '*.key' \
         -o -name '*.pem' -o -name 'id_*' -o -name '*.p12' -o -name '*.keystore' \
         -o -name '*license*' -o -name '.env' -o -name '*.env' \) -type f 2>/dev/null \
      | sed "s|$GEN/||"
  } > "$GEN/manifest/SENSITIVE.txt" 2>/dev/null
  NSENS=$(( $(wc -l < "$GEN/manifest/SENSITIVE.txt") - 2 ))
  st_info "sensitive paths flagged: $NSENS  (manifest/SENSITIVE.txt)"
  st_info "  st-git-rescue.sh --sensitive-list manifest/SENSITIVE.txt refuses to commit any of them"
fi

# ------------------------------------------------------------------ seal + publish
st_log ""
if [ "$ST_FAIL" -ne 0 ]; then
  touch "$GEN/INCOMPLETE"
  st_log "INCOMPLETE — 'latest' NOT advanced, no COMPLETE sentinel written."
  st_log "Inspect $GEN then re-run. A crashed generation must never become the next --link-dest base."
  st_summary "CHECKPOINT"; exit 1
fi

# Sealing is not cosmetic: with --link-dest hardlink chains, writing through an inode in
# the newest generation silently rewrites every earlier generation that shares it.
chmod -R a-w "$GEN/project" "$GEN/claude" 2>/dev/null
touch "$GEN/SEALED"
{
  echo "session_id=$SID"
  echo "origin_host=${ST_ORIGIN_HOST:-local}"
  echo "origin_root=$ST_ORIGIN_ROOT"
  echo "origin_claude=$RC_HOME"
  echo "origin_key=$ST_ORIGIN_KEY"
  echo "sibling_keys=$SIBLINGS"
  echo "extra_transcript_keys=$EXTRA_TX_KEYS"
  echo "taken_at=$TS"
} > "$GEN/PROVENANCE"
touch "$GEN/COMPLETE"          # written LAST — it is the only publish signal
# relative symlinks: an absolute one silently breaks if the checkpoint root ever moves (O7).
# `latest-<SID>` exists because one checkpoint root shared by several migrated sessions
# leaves `latest` naming only the last of them, and every later --checkpoint <root>/latest
# then transplants that same session again and reports "already-placed" — a green run that
# migrated nothing.
( cd "$ST_CKPT_ROOT" && ln -sfn "$TS" latest && ln -sfn "$TS" "latest-$SID" )
st_ok "SEALED and PUBLISHED -> $GEN"
st_ok "latest -> $TS   and   latest-$SID -> $TS   (both relative)"
st_info "use --checkpoint $ST_CKPT_ROOT/latest-$SID downstream: it is unambiguous when the"
st_info "  same checkpoint root holds more than one migrated session"
st_summary "CHECKPOINT"
exit $?
