#!/usr/bin/env bash
# st-resync.sh — the WRITE-BACK path: push work done at the destination back to the origin.
#
# This is the only script in the set that can modify the origin, and the origin is the
# user's primary copy. It is therefore built to refuse:
#
#   * DRY RUN BY DEFAULT. --apply is required, and even then a typed confirmation follows.
#   * Three-way classification against the checkpoint the local work started from.
#     BOTH_CHANGED is NEVER auto-resolved. REMOTE_ONLY is never overwritten.
#   * DELETION IS DISABLED BY POLICY. --delete is never passed. Files missing locally are
#     reported, never removed remotely.
#   * The current remote bytes of every file about to be overwritten are pulled into a
#     local backup dir FIRST, so a restore is always possible without trusting the origin.
#   * Writes go through rsync --delay-updates: content lands in temporary names and is
#     renamed into place at the end. --inplace and --append are never used (they would
#     also corrupt any checkpoint generation sharing an inode via --link-dest).
#   * Case-only collisions and NFD names are FATAL here. ext4 is case-sensitive and APFS
#     usually is not: pushing `Foo.md` and `foo.md` to a case-insensitive origin silently
#     destroys one file's content AND RSYNC REPORTS SUCCESS. openrsync has no --iconv;
#     nothing can fix it in flight.
#   * The transcript is never pushed in place. Its histories fork the moment either side
#     appends; the only legal push is to a NEW filename, and only if the remote file is
#     still a byte-exact prefix of the local one.
set -uo pipefail

ST_SELF="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=st-common.sh
. "$ST_SELF/st-common.sh"

usage() {
  cat <<'EOF'
st-resync.sh — review and (optionally) push destination changes back to the origin.

  --profile FILE        shell file presetting ST_* variables
  --origin-host HOST    ssh host of the origin                (required)
  --origin-root PATH    project root on the origin            (required)
  --dest-root PATH      the local working tree                (required)
  --checkpoint DIR      the checkpoint the local work started from = the BASE of the
                        three-way comparison                  (required)
  --exclude-file FILE   same anchored+justified format as st-checkpoint.sh
  --diff                show a unified diff for every text file that would change
  --max-diff-bytes N    per-file cap for --diff (default 262144)
  --backup-dir DIR      local backup of the remote bytes we would overwrite
                        (default: <checkpoint>/../writeback/<ts>/backup)
  --remote-backup       ALSO copy the pre-write remote bytes into a backup dir ON the
                        origin. This is an extra origin write; off by default.
  --skip-conflicts      proceed with the non-conflicting files instead of halting
  --resurrect-deleted   permit re-creating files the ORIGIN deleted after the checkpoint
                        (off by default: a remote delete + a local edit is a conflict)
  --allow-origin-activity
                        proceed even though a claude process references the origin tree
  --apply               actually write, after the typed confirmation
  --confirm-count N     supply the typed confirmation non-interactively. There is no
                        controlling terminal inside an agent harness, so this exists —
                        but it is only legitimate when the USER typed that number.
  -h | --help

Exit 0 = nothing to do, or the push completed and verified.
Exit 1 = refused, or a gate failed.
EOF
}

st_preparse_profile "$@"

ST_ORIGIN_HOST="${ST_ORIGIN_HOST:-}"; ST_ORIGIN_ROOT="${ST_ORIGIN_ROOT:-}"
ST_DEST_ROOT="${ST_DEST_ROOT:-}"; ST_CKPT="${ST_CKPT:-}"
EXCL_FILE=""; SHOW_DIFF=0; MAXDIFF=262144; BACKUP_DIR=""; REMOTE_BACKUP=0
SKIP_CONFLICTS=0; APPLY=0; ALLOW_ACTIVITY=0; RESURRECT=0

while [ $# -gt 0 ]; do
  case "$1" in
    --profile)        shift 2 ;;
    --profile=*)      shift ;;
    --resurrect-deleted) RESURRECT=1; shift ;;
    --confirm-count)  ST_CONFIRM_COUNT="$2"; export ST_CONFIRM_COUNT; shift 2 ;;
    --origin-host)    ST_ORIGIN_HOST="$2"; shift 2 ;;
    --origin-root)    ST_ORIGIN_ROOT="$2"; shift 2 ;;
    --dest-root)      ST_DEST_ROOT="$2"; shift 2 ;;
    --checkpoint)     ST_CKPT="$2"; shift 2 ;;
    --exclude-file)   EXCL_FILE="$2"; shift 2 ;;
    --diff)           SHOW_DIFF=1; shift ;;
    --max-diff-bytes) MAXDIFF="$2"; shift 2 ;;
    --backup-dir)     BACKUP_DIR="$2"; shift 2 ;;
    --remote-backup)  REMOTE_BACKUP=1; shift ;;
    --skip-conflicts) SKIP_CONFLICTS=1; shift ;;
    --allow-origin-activity) ALLOW_ACTIVITY=1; shift ;;
    --apply)          APPLY=1; shift ;;
    -h|--help)        usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done
st_need python3 rsync
st_require_var ST_ORIGIN_HOST --origin-host
st_require_var ST_ORIGIN_ROOT --origin-root
st_require_var ST_DEST_ROOT   --dest-root
st_require_var ST_CKPT        --checkpoint

# "local" means both sides are on this host: a directory-to-directory write-back. Every
# remote operation then runs locally, and no ssh is involved at all.
LOCAL_ORIGIN=0
case "$ST_ORIGIN_HOST" in local|localhost) LOCAL_ORIGIN=1 ;; esac
[ "$LOCAL_ORIGIN" -eq 1 ] || st_need ssh

rwalk() {   # rwalk ARGS...  — st_walk.py on the origin side
  if [ "$LOCAL_ORIGIN" -eq 1 ]; then
    python3 "$ST_SELF/st_walk.py" "$@"
  else
    st_ssh_py "$ST_ORIGIN_HOST" "$ST_SELF/st_walk.py" "$@"
  fi
}
rro() {     # rro CMD  — read-only command on the origin side
  # The chokepoint applies to the local branch too. It used to be `sh -c "$*"` with no
  # check at all, so the advertised guarantee ("enforced by one chokepoint, not by
  # intention") was enforced by neither for --origin-host local.
  if [ "$LOCAL_ORIGIN" -eq 1 ]; then
    st_local_ro "$@"
  else
    st_ssh_ro "$ST_ORIGIN_HOST" "$@"
  fi
}
rspec() {   # rspec PATH -> rsync path spec for the origin side
  if [ "$LOCAL_ORIGIN" -eq 1 ]; then printf '%s' "$1"; else printf '%s:%s' "$ST_ORIGIN_HOST" "$1"; fi
}

TS="$(st_ts)"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/st-resync.XXXXXX")" || st_die "mktemp -d failed"
trap 'rm -rf "$WORK"' EXIT
[ -n "$BACKUP_DIR" ] || BACKUP_DIR="$(dirname "$(st_realpath "$ST_CKPT")")/writeback/$TS/backup"

st_banner "ST-RESYNC  $TS   $( [ "$APPLY" -eq 1 ] && echo '[APPLY REQUESTED]' || echo '[DRY RUN — nothing will be written]')"
st_log "origin      $ST_ORIGIN_HOST:$ST_ORIGIN_ROOT"
st_log "local       $ST_DEST_ROOT"
st_log "base        $ST_CKPT"

# ================================================================ STAGE 1 preconditions
st_banner "STAGE 1  PRECONDITIONS  (no remote writes in stages 1-5)"
[ -f "$ST_CKPT/COMPLETE" ] && st_ok "the base checkpoint carries COMPLETE" \
  || st_bad "the base checkpoint has no COMPLETE sentinel — it was never verified"
[ -d "$ST_DEST_ROOT" ] || st_bad "local tree missing: $ST_DEST_ROOT"

if [ "$LOCAL_ORIGIN" -eq 1 ]; then
  [ -d "$ST_ORIGIN_ROOT" ] && st_ok "origin is a local directory: $ST_ORIGIN_ROOT" \
                           || { st_bad "origin root missing: $ST_ORIGIN_ROOT"; st_summary "RESYNC"; exit 1; }
elif st_ssh_alive "$ST_ORIGIN_HOST"; then
  st_ok "origin reachable"
else
  st_bad "origin unreachable"; st_summary "RESYNC"; exit 1
fi

# is anything running there that could be writing?
# Never `pgrep -f <pattern>`: it self-matches. And when the origin IS this host, the
# operator's own Claude session (and every tool it spawns, which inherit its comm) would
# match a bare name test — so in that case require the process to actually reference the
# origin tree, which is the thing we care about.
if [ "$LOCAL_ORIGIN" -eq 1 ]; then
  PROCS="$(ps -eo pid,comm,args 2>/dev/null | awk -v me="$$" -v par="$PPID" -v root="$ST_ORIGIN_ROOT" \
      'NR>1 && $1 != me && $1 != par && tolower($2) ~ /claude/ && index($0, root) > 0')"
else
  PROCS="$(rro "ps -eo pid,comm,args" 2>/dev/null | awk 'NR>1 && tolower($2) ~ /claude/')"
fi
if [ -z "$PROCS" ]; then
  st_ok "no claude process is touching the origin tree"
elif [ "$ALLOW_ACTIVITY" -eq 1 ]; then
  st_warn "a claude process references the origin tree (--allow-origin-activity given):"
  printf '        %s\n' "$PROCS"
else
  st_bad "a claude process references the origin tree — it may be writing the very files we"
  st_bad "  would overwrite. Stop it, or pass --allow-origin-activity if you are certain."
  printf '        %s\n' "$PROCS"
fi

# hazard scan on the LOCAL tree — FATAL on push
python3 - "$ST_DEST_ROOT" > "$WORK/hazards.txt" 2>&1 <<'PY'
import collections, os, sys, unicodedata
root = sys.argv[1]
nfd = []
case = collections.defaultdict(list)


def fold(n):
    # APFS folds case AND Unicode normalisation. Folding on .lower() alone reports 0
    # collisions for exactly the NFC/NFD pair that merges.
    return unicodedata.normalize('NFC', n).casefold()


for base, dirs, files in os.walk(root):
    for n in dirs + files:
        if unicodedata.normalize('NFC', n) != n:
            nfd.append(os.path.join(base, n))
        case[os.path.join(base, fold(n))].append(n)
coll = {k: v for k, v in case.items() if len(set(v)) > 1}
print("nfd=%d" % len(nfd))
print("case=%d" % len(coll))
for k, v in list(coll.items())[:40]:
    print("  CASE %s %s" % (k, sorted(set(v))))
for p in nfd[:40]:
    print("  NFD  %s" % p)
PY
NFD=$(sed -n 's/^nfd=//p' "$WORK/hazards.txt"); CASE=$(sed -n 's/^case=//p' "$WORK/hazards.txt")
if [ "${NFD:-0}" -eq 0 ] && [ "${CASE:-0}" -eq 0 ]; then
  st_ok "filename hazards: 0 NFD names, 0 case-only collisions"
else
  st_bad "filename hazards on the local tree: $NFD NFD name(s), $CASE case-only collision(s)"
  st_bad "  A case-only collision pushed to a case-insensitive origin destroys one file's"
  st_bad "  content and rsync reports success. Rename locally first; this cannot be fixed in flight."
  grep -E '^  (CASE|NFD)' "$WORK/hazards.txt" | head -20 | while IFS= read -r l; do st_log "      $l"; done
fi

FREE="$(rro "df -k \"$ST_ORIGIN_ROOT\"" 2>/dev/null | awk 'NR==2{print $4*1024}')"
if [ -n "$FREE" ]; then
  st_ok "origin free space: $(st_human "$FREE")"
else
  st_skip "origin free-space check"
fi

# ================================================================ STAGE 2 classification
st_banner "STAGE 2  THREE-WAY CLASSIFICATION  (base = the checkpoint the work started from)"
set -- --root "$ST_CKPT/project" --jobs 8
[ -n "$EXCL_FILE" ] && set -- "$@" --exclude-from "$EXCL_FILE"
python3 "$ST_SELF/st_walk.py" "$@" > "$WORK/base.tsv" 2>/dev/null || st_bad "base manifest failed"

set -- --root "$ST_DEST_ROOT" --jobs 8
[ -n "$EXCL_FILE" ] && set -- "$@" --exclude-from "$EXCL_FILE"
python3 "$ST_SELF/st_walk.py" "$@" > "$WORK/local.tsv" 2>/dev/null || st_bad "local manifest failed"

set -- --root "$ST_ORIGIN_ROOT" --jobs 8
[ -n "$EXCL_FILE" ] && set -- "$@" --exclude-from "$EXCL_FILE"
st_info "hashing the origin tree (read-only)"
rwalk "$@" > "$WORK/remote.tsv" 2>/dev/null || st_bad "remote manifest failed"

for f in base local remote; do
  st_ok "$f manifest: $(grep -v '^#' "$WORK/$f.tsv" 2>/dev/null | wc -l | tr -d ' ') files"
done

python3 - "$WORK" "$RESURRECT" > "$WORK/classify.txt" 2>&1 <<'PY'
import os, sys
w = sys.argv[1]


def rd(p):
    d = {}
    for line in open(p):
        if line.startswith('#') or not line.strip():
            continue
        f = line.rstrip('\n').split('\t')
        if len(f) >= 3:
            d[f[0]] = (f[1], f[2])
    return d


resurrect = len(sys.argv) > 2 and sys.argv[2] == '1'
base, loc, rem = rd(w + '/base.tsv'), rd(w + '/local.tsv'), rd(w + '/remote.tsv')
cls = {k: [] for k in ('UNCHANGED', 'LOCAL_ONLY', 'REMOTE_ONLY', 'BOTH_CHANGED',
                       'NEW_LOCAL', 'DELETED_LOCAL', 'NEW_BOTH',
                       'REMOTE_DELETED', 'REMOTE_DELETED_UNCHANGED')}
for p in sorted(set(base) | set(loc) | set(rem)):
    b, l, r = base.get(p), loc.get(p), rem.get(p)
    if b is None:
        if l is not None and r is None:
            cls['NEW_LOCAL'].append(p)
        elif l is None and r is not None:
            pass                      # appeared on the origin after the checkpoint; leave alone
        elif l is not None and r is not None:
            cls['NEW_BOTH' if l != r else 'UNCHANGED'].append(p)
        continue
    if l is None:
        cls['DELETED_LOCAL'].append(p)
        continue
    if r is None:
        # In the base, present locally, GONE FROM THE ORIGIN: the user deleted it there
        # after the checkpoint. If we also changed it locally that is a delete/modify
        # conflict; if we did not, pushing it RESURRECTS a file the user removed. Both
        # used to be filed as LOCAL_ONLY / REMOTE_ONLY, and the first was queued for write
        # under a heading that read "untouched on the origin".
        cls['REMOTE_DELETED' if l != b else 'REMOTE_DELETED_UNCHANGED'].append(p)
        continue
    lc, rc = (l != b), (r != b)
    if not lc and not rc:
        cls['UNCHANGED'].append(p)
    elif lc and not rc:
        cls['LOCAL_ONLY'].append(p)
    elif rc and not lc:
        cls['REMOTE_ONLY'].append(p)
    else:
        cls['BOTH_CHANGED' if l != r else 'UNCHANGED'].append(p)

push = cls['LOCAL_ONLY'] + cls['NEW_LOCAL']
if resurrect:
    push = push + cls['REMOTE_DELETED']
with open(w + '/push.list', 'w') as f:
    for p in push:
        f.write(p + '\n')
with open(w + '/conflicts.list', 'w') as f:
    for p in cls['BOTH_CHANGED'] + cls['NEW_BOTH'] + ([] if resurrect else cls['REMOTE_DELETED']):
        f.write(p + '\n')

# symlink rows carry size -1; clamp so the byte total stays meaningful
bytes_push = sum(max(0, int(loc[p][0])) for p in push)
print("counts\t%d\t%d\t%d\t%d\t%d\t%d\t%d\t%d" % (
    len(cls['UNCHANGED']), len(cls['LOCAL_ONLY']), len(cls['NEW_LOCAL']),
    len(cls['REMOTE_ONLY']),
    len(cls['BOTH_CHANGED']) + len(cls['NEW_BOTH']) + (0 if resurrect else len(cls['REMOTE_DELETED'])),
    len(cls['DELETED_LOCAL']),
    len(cls['REMOTE_DELETED']), len(cls['REMOTE_DELETED_UNCHANGED'])))
print("bytes\t%d" % bytes_push)
for k in ('LOCAL_ONLY', 'NEW_LOCAL', 'REMOTE_ONLY', 'BOTH_CHANGED', 'NEW_BOTH',
          'DELETED_LOCAL', 'REMOTE_DELETED', 'REMOTE_DELETED_UNCHANGED'):
    for p in cls[k][:200]:
        extra = ""
        if k in ('BOTH_CHANGED', 'NEW_BOTH'):
            extra = "  base=%s local=%s remote=%s" % (
                (base.get(p) or ('-', '-'))[1][:10], (loc.get(p) or ('-', '-'))[1][:10],
                (rem.get(p) or ('-', '-'))[1][:10])
        print("%s\t%s%s" % (k, p, extra))

# case-insensitivity risk against the ORIGIN's existing names
low = {}
for p in rem:
    low.setdefault(p.lower(), set()).add(p)
risky = []
for p in push:
    others = low.get(p.lower(), set()) - {p}
    if others:
        risky.append((p, sorted(others)))
for p, o in risky[:40]:
    print("CASERISK\t%s\t%s" % (p, o))
print("caserisk\t%d" % len(risky))
PY

COUNTS="$(sed -n 's/^counts	//p' "$WORK/classify.txt")"
N_UNCH=$(printf '%s' "$COUNTS" | cut -f1); N_LOCAL=$(printf '%s' "$COUNTS" | cut -f2)
N_NEW=$(printf '%s' "$COUNTS" | cut -f3);  N_REMOTE=$(printf '%s' "$COUNTS" | cut -f4)
N_CONF=$(printf '%s' "$COUNTS" | cut -f5); N_DEL=$(printf '%s' "$COUNTS" | cut -f6)
N_RDEL=$(printf '%s' "$COUNTS" | cut -f7); N_RDELU=$(printf '%s' "$COUNTS" | cut -f8)
B_PUSH=$(sed -n 's/^bytes	//p' "$WORK/classify.txt")
N_CASERISK=$(sed -n 's/^caserisk	//p' "$WORK/classify.txt")
N_PUSH=$(( ${N_LOCAL:-0} + ${N_NEW:-0} ))
[ "$RESURRECT" -eq 1 ] && N_PUSH=$(( N_PUSH + ${N_RDEL:-0} ))

# `\b` is a GNU grep extension: on BSD grep (a macOS destination) these matched NOTHING
# and every preview below printed blank while the counts still printed. Anchor on the
# literal TAB the classifier emits instead.
TAB="$(printf '\t')"
st_log ""
st_log "  UNCHANGED      $N_UNCH"
st_log "  MODIFY         $N_LOCAL   (changed locally, still present and untouched on the origin)"
st_log "  CREATE         $N_NEW     (new locally)"
st_log "  REMOTE_ONLY    $N_REMOTE  (the ORIGIN moved on — these will be LEFT ALONE)"
st_log "  CONFLICT       $N_CONF    (changed on BOTH sides since the base)"
st_log "  DELETED_LOCAL  $N_DEL     (deletion is disabled by policy — reported only)"
st_log "  REMOTE_DELETED $N_RDEL    (the ORIGIN deleted it AND we changed it — a conflict)"
st_log "  ..unchanged    $N_RDELU   (the ORIGIN deleted it and we did not touch it — left alone)"
st_log "  to write       $N_PUSH files, $(st_human "${B_PUSH:-0}")"
st_log ""
grep -E "^(LOCAL_ONLY|NEW_LOCAL)$TAB" "$WORK/classify.txt" | head -40 | \
  while IFS="$TAB" read -r k p; do st_log "    WRITE   $p"; done
grep -E "^REMOTE_ONLY$TAB" "$WORK/classify.txt" | head -20 | \
  while IFS="$TAB" read -r k p; do st_log "    LEAVE   $p   (origin changed it)"; done
if [ "${N_CONF:-0}" -gt 0 ]; then
  st_log ""
  grep -E "^(BOTH_CHANGED|NEW_BOTH)$TAB" "$WORK/classify.txt" | head -40 | \
    while IFS="$TAB" read -r k rest; do st_log "    CONFLICT $rest"; done
fi
if [ "${N_RDEL:-0}" -gt 0 ]; then
  grep -E "^REMOTE_DELETED$TAB" "$WORK/classify.txt" | head -20 | \
    while IFS="$TAB" read -r k p; do
      if [ "$RESURRECT" -eq 1 ]; then st_log "    RESURRECT $p   (--resurrect-deleted)"
      else st_log "    CONFLICT $p   (deleted on the origin, changed here)"; fi
    done
  [ "$RESURRECT" -eq 0 ] && st_warn "$N_RDEL file(s) were DELETED on the origin and changed here. Writing them would re-create files the user removed. They are treated as conflicts; --resurrect-deleted overrides."
fi
if [ "${N_RDELU:-0}" -gt 0 ]; then
  grep -E "^REMOTE_DELETED_UNCHANGED$TAB" "$WORK/classify.txt" | head -10 | \
    while IFS="$TAB" read -r k p; do st_log "    LEAVE   $p   (deleted on the origin; unchanged here)"; done
fi
if [ "${N_DEL:-0}" -gt 0 ]; then
  grep -E "^DELETED_LOCAL$TAB" "$WORK/classify.txt" | head -20 | \
    while IFS="$TAB" read -r k p; do st_log "    KEPT    $p   (missing locally; never deleted remotely)"; done
fi
if [ "${N_CASERISK:-0}" -gt 0 ]; then
  st_bad "$N_CASERISK file(s) would collide case-insensitively with existing origin names:"
  grep '^CASERISK' "$WORK/classify.txt" | head -20 | while IFS= read -r l; do st_log "      $l"; done
fi

# files that already exist on the origin (needed by the diff preview and the backup step)
python3 - "$WORK" <<'PYBK2' > "$WORK/backup.list"
import sys
w = sys.argv[1]
have = set()
for line in open(w + '/remote.tsv'):
    if line.startswith('#') or not line.strip():
        continue
    have.add(line.split('\t')[0])
for line in open(w + '/push.list'):
    q = line.strip()
    if q and q in have:
        print(q)
PYBK2

# transcript never travels in place
if grep -qE '^CLAUDE\.md$' "$WORK/push.list" 2>/dev/null; then
  st_warn "the push set contains CLAUDE.md — that file was written BY the transporter to tell"
  st_warn "  the model this workspace moved. Pushing it back to the origin is almost certainly"
  st_warn "  not what you want. Exclude it unless you have edited it deliberately."
fi
if grep -qE '\.jsonl$' "$WORK/push.list" 2>/dev/null; then
  st_warn "the push set contains .jsonl files. A session transcript is never pushed in place:"
  st_warn "  the histories fork the moment either side appends. Exclude it, or copy it to a"
  st_warn "  NEW filename manually after confirming the remote file is still a byte-exact prefix."
fi

# ================================================================ STAGE 3/4 dry run + diff
st_banner "STAGE 3  RSYNC DRY RUN (independent second opinion: rolling checksums, not SHA-256)"
if [ "$N_PUSH" -gt 0 ]; then
  rsync -n -a -c --itemize-changes --no-perms --no-owner --no-group \
    --files-from="$WORK/push.list" "$ST_DEST_ROOT/" \
    "$(rspec "$ST_ORIGIN_ROOT/")" 2>&1 | head -60 | while IFS= read -r l; do st_log "    $l"; done
else
  st_ok "nothing to write"
fi

if [ "$SHOW_DIFF" -eq 1 ] && [ "$N_PUSH" -gt 0 ]; then
  st_banner "STAGE 4  DIFF PREVIEW"
  mkdir -p "$WORK/remotecopy"
  rsync -a --no-perms --files-from="$WORK/backup.list" \
    "$(rspec "$ST_ORIGIN_ROOT/")" "$WORK/remotecopy/" >/dev/null 2>&1
  while IFS= read -r p; do
    L="$ST_DEST_ROOT/$p"; Rf="$WORK/remotecopy/$p"
    [ -f "$L" ] || continue
    SZ=$(st_size "$L")
    if [ "$SZ" -gt "$MAXDIFF" ]; then
      st_log "    ---- $p  (binary or >$MAXDIFF bytes: $(st_human "$SZ"))"
      continue
    fi
    if [ -f "$Rf" ]; then
      st_log "    ---- $p"
      diff -u "$Rf" "$L" 2>/dev/null | head -60 | while IFS= read -r l; do st_log "      $l"; done
    else
      st_log "    ---- $p  (NEW on the origin, $(st_human "$SZ"))"
    fi
  done < "$WORK/push.list"
fi

# ================================================================ gates before writing
st_log ""
if [ "${N_CONF:-0}" -gt 0 ] && [ "$SKIP_CONFLICTS" -eq 0 ]; then
  st_bad "$N_CONF conflict(s) changed on BOTH sides since the base. These are never"
  st_bad "  auto-resolved. Resolve them by hand, or re-run with --skip-conflicts to push"
  st_bad "  only the non-conflicting files."
fi
if [ "$APPLY" -eq 0 ]; then
  st_log "DRY RUN COMPLETE. Nothing was written. Re-run with --apply to be asked for confirmation."
  st_summary "RESYNC-DRYRUN"; exit $?
fi
if [ "$ST_FAIL" -ne 0 ]; then
  st_log "refusing to write with $ST_FAIL failed gate(s)."
  exit 1
fi
if [ "$N_PUSH" -eq 0 ]; then
  st_log "nothing to write."
  exit 0
fi

# ================================================================ STAGE 5 confirmation
st_banner "STAGE 5  CONFIRMATION"
cat <<EOF
WRITE-BACK TO THE ORIGIN — REVIEW REQUIRED
  Target : $ST_ORIGIN_HOST:$ST_ORIGIN_ROOT
  Base   : $ST_CKPT

    $N_LOCAL file(s) to MODIFY
    $N_NEW file(s) to CREATE
    $( [ "$RESURRECT" -eq 1 ] && echo "$N_RDEL file(s) to RE-CREATE that the origin had deleted" || echo "0 file(s) to re-create (--resurrect-deleted not given)")
    0 file(s) to DELETE   (deletion is disabled by policy)
    $N_REMOTE remote-only change(s) will be LEFT ALONE
    $N_CONF conflict(s) $( [ "$SKIP_CONFLICTS" -eq 1 ] && echo 'SKIPPED' || echo 'blocking')

  Bytes to write : $(st_human "${B_PUSH:-0}")
  Local backup   : $BACKUP_DIR
EOF
st_confirm_typed "$N_PUSH" "The confirmation is the NUMBER OF FILES that will be written, not a y/n." \
  || { st_log "aborted by the operator — nothing was written"; exit 1; }

# ================================================================ STAGE 6 backup + write
st_banner "STAGE 6  BACKUP, THEN STAGED WRITE"
mkdir -p "$BACKUP_DIR" || st_die "cannot create $BACKUP_DIR"
st_info "pulling the current origin bytes of every target file into the local backup"
# backup.list was built during classification: only files that ACTUALLY EXIST on the
# origin. Asking rsync for a missing source is an error on openrsync, which has no
# --ignore-missing-args.
NBK=$(wc -l < "$WORK/backup.list" | tr -d ' ')
if [ "$NBK" -gt 0 ]; then
  rsync -a --no-perms --files-from="$WORK/backup.list" \
    "$(rspec "$ST_ORIGIN_ROOT/")" "$BACKUP_DIR/" >/dev/null 2>&1
  rc=$?
  NB=$(find "$BACKUP_DIR" -type f 2>/dev/null | wc -l | tr -d ' ')
  if [ $rc -eq 0 ] && [ "$NB" -eq "$NBK" ]; then
    st_ok "backup: $NB of $NBK pre-write file(s) saved under $BACKUP_DIR"
  else
    st_bad "backup incomplete ($NB of $NBK, rc=$rc) — refusing to overwrite without a restorable copy"
  fi
else
  st_ok "no existing origin file would be overwritten (all $N_PUSH are new)"
fi
[ "$ST_FAIL" -eq 0 ] || { st_log "aborting before any write"; exit 1; }
cp "$WORK/push.list" "$BACKUP_DIR/../push.list" 2>/dev/null
cp "$WORK/classify.txt" "$BACKUP_DIR/../classification.txt" 2>/dev/null

if [ "$REMOTE_BACKUP" -eq 1 ]; then
  st_warn "--remote-backup: this writes a backup tree ON the origin as well"
  RB="\$HOME/.st-writeback-backup/$TS"
  st_log "  ORIGIN WRITE: mkdir -p $RB  (deliberate, post-confirmation, outside the project root)"
  # deliberately bypasses the read-only chokepoint: an authorised origin write
  ssh $ST_SSH_OPTS "$ST_ORIGIN_HOST" "mkdir -p '$RB'" >/dev/null 2>&1 \
    && st_ok "remote backup dir created" || st_bad "could not create the remote backup dir"
  mkdir -p "$WORK/rb"
  rsync -a --no-perms --files-from="$WORK/backup.list" \
    "$(rspec "$ST_ORIGIN_ROOT/")" "$WORK/rb/" >/dev/null 2>&1
  rsync -a --no-perms "$WORK/rb/" "$(rspec "$RB/")" >/dev/null 2>&1 \
    && st_ok "remote backup populated at $RB" || st_bad "remote backup failed"
fi

# --delay-updates is a RECEIVER-side feature, and the receiver here is the origin — which
# may be macOS/openrsync. Probe rather than assume: an unsupported flag would abort the
# whole push after the confirmation.
DELAY_OK=1
if [ "$LOCAL_ORIGIN" -eq 0 ]; then
  RVER="$(st_ssh_ro "$ST_ORIGIN_HOST" "rsync --version" 2>/dev/null | head -1)"
  case "$RVER" in
    *openrsync*) DELAY_OK=0 ;;
  esac
  if [ "$DELAY_OK" -eq 0 ]; then
    st_warn "the origin runs openrsync ($RVER): --delay-updates is not relied on there."
    st_warn "  Falling back to --partial-dir, which gives the same 'never a half-written file"
    st_warn "  under its real name' property by a different mechanism."
  fi
fi
st_info "writing with $( [ "$DELAY_OK" -eq 1 ] && echo '--delay-updates' || echo '--partial-dir' ) (temp names, renamed into place)"
st_info "  never --inplace, never --append, never --delete"
set -- -a --no-perms --no-owner --no-group --itemize-changes
if [ "$DELAY_OK" -eq 1 ]; then set -- "$@" --delay-updates; else set -- "$@" --partial-dir=.st-partial; fi
rsync "$@" --files-from="$WORK/push.list" "$ST_DEST_ROOT/" "$(rspec "$ST_ORIGIN_ROOT/")" \
  > "$WORK/push.log" 2>&1
rc=$?
if [ $rc -eq 0 ]; then
  st_ok "rsync push completed"
  head -40 "$WORK/push.log" | while IFS= read -r l; do st_log "    $l"; done
else
  st_bad "rsync push rc=$rc"
  tail -20 "$WORK/push.log" | while IFS= read -r l; do st_log "    $l"; done
fi

# ================================================================ STAGE 7 postflight
st_banner "STAGE 7  POSTFLIGHT — re-hash remotely and compare"
set -- --root "$ST_ORIGIN_ROOT" --jobs 8
[ -n "$EXCL_FILE" ] && set -- "$@" --exclude-from "$EXCL_FILE"
rwalk "$@" > "$WORK/remote2.tsv" 2>/dev/null || st_skip "post-write remote manifest"
if [ -s "$WORK/remote2.tsv" ]; then
  while IFS= read -r line; do
    case "$line" in
      "OK "*)   st_ok  "${line#OK }" ;;
      "FAIL "*) st_bad "${line#FAIL }" ;;
      *) st_log "    $line" ;;
    esac
  done < <(python3 - "$WORK" <<'PYPOST'
import sys
w = sys.argv[1]


def rd(p):
    d = {}
    for line in open(p):
        if line.startswith('#') or not line.strip():
            continue
        f = line.rstrip('\n').split('\t')
        if len(f) >= 3:
            d[f[0]] = (f[1], f[2])
    return d


loc, rem = rd(w + '/local.tsv'), rd(w + '/remote2.tsv')
want = [l.strip() for l in open(w + '/push.list') if l.strip()]
bad = [p for p in want if rem.get(p) != loc.get(p)]
print("OK all %d written file(s) now hash identically on the origin" % len(want)
      if not bad else "FAIL %d of %d written file(s) do NOT match after the push" % (len(bad), len(want)))
for p in bad[:20]:
    print("%s  local=%s remote=%s" % (p, (loc.get(p) or ('-', '-'))[1][:12],
                                      (rem.get(p) or ('-', '-'))[1][:12]))
PYPOST
)
fi
RECEIPT="$(dirname "$BACKUP_DIR")/receipt.txt"
{
  echo "write-back receipt $TS"
  echo "origin      $ST_ORIGIN_HOST:$ST_ORIGIN_ROOT"
  echo "local       $ST_DEST_ROOT"
  echo "base        $ST_CKPT"
  echo "files       $N_PUSH  bytes ${B_PUSH:-0}"
  echo "conflicts   ${N_CONF:-0} (skipped: $SKIP_CONFLICTS)"
  echo "backup      $BACKUP_DIR"
} > "$RECEIPT" 2>/dev/null
st_ok "receipt: $RECEIPT"
st_log ""
st_log "If a git repo was touched, re-assert its invariants on the origin: index size and"
st_log "entry count, loose-object count, and that no .git/gc.log appeared."
st_summary "RESYNC"
exit $?
