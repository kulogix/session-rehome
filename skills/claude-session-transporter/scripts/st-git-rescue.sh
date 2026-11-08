#!/usr/bin/env bash
# st-git-rescue.sh — G4. Make a fragile git repo durable BEFORE a migration relies on it.
#
# The failure this exists for, measured on the origin of the run that worked:
#
#   HEAD -> refs/heads/master  (UNBORN)
#   338 staged files, 427 loose objects, 0 packfiles, no commit, no tree
#   `git fsck` reports every one of the 427 objects as DANGLING
#
# The 338 files exist as content-addressed blobs WITH NO NAMES. The only copy of the
# blob -> filename mapping is a 34 KB `.git/index`. Lose or corrupt it and you keep 24 MB
# of anonymous blobs. Any `git gc` / `git prune` — which several porcelain commands
# trigger automatically — deletes dangling objects outright.
#
# Therefore, in this order and no other:
#   1. gc.auto=0 as the literal FIRST git operation
#   2. back up .git/index and record its hash
#   3. prove every index entry's blob is actually present (blob completeness)
#   4. commit the index  -> the blobs acquire names and stop being dangling
#   5. for an UNBORN-HEAD repo only: a second commit for working-tree drift
#   6. bundle + bare mirror, and verify both
#
# WRITING IS OPT-IN AND OPT-IN AGAIN. `--apply` alone is not enough: it also needs either
# `--work DIR` (operate on a copy — the safe default) or `--in-place`, which additionally
# demands a typed confirmation. The header of this file used to say "NEVER run this
# against the origin. It writes." and nothing enforced it; `--repo <origin> --apply` was a
# one-flag path to two commits and a `git add -A` on the user's primary repository.
set -uo pipefail

ST_SELF="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=st-common.sh
. "$ST_SELF/st-common.sh"

usage() {
  cat <<'EOF'
st-git-rescue.sh — rescue a repo whose only filename mapping is .git/index.

  --repo PATH        the repository to inspect / rescue (LOCAL path only)
  --work DIR         copy the repo here first and operate on the copy. THIS IS THE
                     INTENDED MODE, and it is required for --apply unless --in-place.
  --in-place         write to --repo itself. Requires a typed confirmation, and is
                     refused when --repo lies under $ST_ORIGIN_ROOT.
  --out DIR          where to write repo.bundle and repo.git (default: <work>/../st-git-rescue)
  --scan ROOT        inspect every git repo under ROOT and report risk; implies read-only
  --apply            actually write (config, commits, bundle, mirror). Without it,
                     nothing is written and the script only reports.
  --sensitive-list F a file of paths (e.g. <checkpoint>/manifest/SENSITIVE.txt) that must
                     NOT be committed. Any of them still untracked-and-unignored refuses
                     the drift commit. Strongly recommended: `git add -A` commits keys.
  --author "N <e>"   identity for the rescue commits
                     (default: "claude-session-transporter <claude-session-transporter@localhost>")
  --message MSG      subject of the index commit (default: "rescue: staged index snapshot")
  -h | --help

WHAT IT DOES NOT DO. If the repo already has commits, the "working-tree drift" step does
NOT run `git add -A` and commit onto your branch: that silently diverges a branch with an
upstream and destroys a deliberately-curated staging set. It writes `drift.patch` and
`untracked.txt` into --out instead, and says so.

Exit 0 = nothing to do, or the rescue completed and verified.
Exit 1 = a gate failed. Exit 2 = bad usage.
EOF
}

REPO=""; WORK=""; OUT=""; APPLY=0; SCAN=""; INPLACE=0; SENSLIST=""
AUTHOR="claude-session-transporter <claude-session-transporter@localhost>"
MSG="rescue: staged index snapshot"

while [ $# -gt 0 ]; do
  case "$1" in
    --repo)    REPO="$2"; shift 2 ;;
    --work)    WORK="$2"; shift 2 ;;
    --in-place) INPLACE=1; shift ;;
    --out)     OUT="$2"; shift 2 ;;
    --scan)    SCAN="$2"; shift 2 ;;
    --apply)   APPLY=1; shift ;;
    --sensitive-list) SENSLIST="$2"; shift 2 ;;
    --author)  AUTHOR="$2"; shift 2 ;;
    --message) MSG="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done
st_need git python3

# ------------------------------------------------------------------ scan mode
if [ -n "$SCAN" ]; then
  st_banner "ST-GIT-RESCUE  scan  $SCAN"
  [ -d "$SCAN" ] || st_die "not a directory: $SCAN"
  find "$SCAN" -maxdepth 8 -name .git 2>/dev/null | sort | while IFS= read -r g; do
    r="$(dirname "$g")"
    head_ok=$(git --no-optional-locks -C "$r" rev-parse --verify HEAD 2>/dev/null)
    n_idx=$(git --no-optional-locks -C "$r" ls-files 2>/dev/null | wc -l | tr -d ' ')
    n_loose=$(find "$g/objects" -type f -not -path '*/pack/*' 2>/dev/null | wc -l | tr -d ' ')
    n_pack=$(ls -1 "$g/objects/pack"/*.pack 2>/dev/null | wc -l | tr -d ' ')
    if [ -z "$head_ok" ]; then
      st_log "$(printf '  AT RISK  %-56s UNBORN HEAD, %s index entries, %s loose objects, %s packs' "$r" "$n_idx" "$n_loose" "$n_pack")"
    else
      st_log "$(printf '  ok       %-56s HEAD %s, %s index entries' "$r" "$(echo "$head_ok" | cut -c1-8)" "$n_idx")"
    fi
  done
  st_log ""
  st_log "Every 'AT RISK' row has no commit: its filenames live only in .git/index."
  st_log "Run:  st-git-rescue.sh --repo <path> --work <writable dir> --apply"
  exit 0
fi

[ -n "$REPO" ] || { usage >&2; exit 2; }
[ -e "$REPO" ] || st_die "no such path: $REPO"
REPO_REAL="$(st_realpath "$REPO")"

st_banner "ST-GIT-RESCUE  $( [ "$APPLY" -eq 1 ] && echo '[APPLY]' || echo '[REPORT ONLY — pass --apply to write]')"
st_log "repo $REPO"

# ------------------------------------------------------------------ not-a-repo
if [ ! -e "$REPO/.git" ]; then
  if git --no-optional-locks -C "$REPO" rev-parse --git-dir >/dev/null 2>&1; then
    st_warn "$REPO is inside another repository, but has no .git of its own — nothing to rescue here"
  else
    st_ok "not a git repository — nothing to rescue. Its contents are preserved by file copy only."
  fi
  exit 0
fi

# ------------------------------------------------------------------ sealed source?
SEALED=0
d="$REPO"
while [ "$d" != "/" ] && [ -n "$d" ]; do
  [ -f "$d/SEALED" ] && { SEALED=1; break; }
  d="$(dirname "$d")"
done
if [ "$SEALED" -eq 1 ] || [ ! -w "$REPO/.git" ]; then
  st_warn "the repo is inside a sealed/read-only tree — it must be copied before any git write"
  [ -n "$WORK" ] || st_die "pass --work DIR so the rescue happens on a copy (a sealed checkpoint must never be modified: with --link-dest hardlinks, writing through an inode rewrites every earlier generation)"
fi

# ------------------------------------------------------------------ where do we write?
HEAD_SHA_SRC=$(git --no-optional-locks -C "$REPO" rev-parse --verify HEAD 2>/dev/null)
if [ "$APPLY" -eq 1 ] && [ -z "$WORK" ]; then
  if [ "$INPLACE" -eq 0 ]; then
    st_die "--apply without --work would write to $REPO itself. Pass --work DIR to rescue on a copy (the intended mode), or --in-place if you really mean to write to this repository."
  fi
  case "$REPO_REAL/" in
    "$(st_realpath "${ST_ORIGIN_ROOT:-/nonexistent-origin-root}")"/*)
      st_die "--in-place refused: $REPO is inside ST_ORIGIN_ROOT (${ST_ORIGIN_ROOT}). The origin is read-only; creating a commit there is a WRITE and belongs to the user." ;;
  esac
  N_IDX_PRE=$(git --no-optional-locks -C "$REPO" ls-files 2>/dev/null | wc -l | tr -d ' ')
  st_warn "--in-place: this will write commits and config INTO $REPO"
  [ -n "$HEAD_SHA_SRC" ] && st_warn "  and that repository ALREADY HAS COMMITS ($(echo "$HEAD_SHA_SRC" | cut -c1-12))"
  st_confirm_typed "$N_IDX_PRE" \
    "About to write to the live repository $REPO. The confirmation is its INDEX ENTRY COUNT." \
    || st_die "aborted — nothing was written"
fi

TARGET="$REPO"
if [ -n "$WORK" ]; then
  if [ "$APPLY" -eq 1 ]; then
    mkdir -p "$WORK" || st_die "cannot create $WORK"
    st_info "copying repo -> $WORK (chmod u+rwX: a sealed source would otherwise propagate a-w — M6)"
    rsync -a --no-perms --chmod=u+rwX,go-w "$REPO/" "$WORK/" || st_die "copy failed"
    TARGET="$WORK"
  else
    st_info "would copy $REPO -> $WORK before touching it"
    TARGET="$REPO"
  fi
fi
WROTE_IN_PLACE=0
[ "$APPLY" -eq 1 ] && [ "$TARGET" = "$REPO" ] && WROTE_IN_PLACE=1
[ -n "$OUT" ] || OUT="$(dirname "$TARGET")/st-git-rescue"

G() { git --no-optional-locks -C "$TARGET" "$@"; }

# ------------------------------------------------------------------ 1. gc.auto=0 FIRST
if [ "$APPLY" -eq 1 ] && [ -w "$TARGET/.git" ]; then
  git -C "$TARGET" config gc.auto 0            || st_bad "could not set gc.auto=0"
  git -C "$TARGET" config gc.autoDetach false  || true
  git -C "$TARGET" config gc.autoPackLimit 0   || true
  git -C "$TARGET" config maintenance.auto false || true
  st_ok "gc.auto=0 set — this is the literal first write, before any command that could auto-gc"
  # A .git/config copied verbatim off APFS carries core.ignorecase=true, which git honours
  # on every platform: it reintroduces the case-merge hazard inside git on a filesystem
  # that does not have it.
  if [ "$(git -C "$TARGET" config --get core.ignorecase 2>/dev/null)" = "true" ]; then
    if [ "$(python3 -c 'import os,sys,tempfile
fd,p=tempfile.mkstemp(prefix="STcase",dir=sys.argv[1]);os.close(fd)
o=os.path.join(os.path.dirname(p),os.path.basename(p).replace("STcase","stCASE"))
print("insensitive" if os.path.exists(o) else "sensitive");os.unlink(p)' "$TARGET" 2>/dev/null)" = "sensitive" ]; then
      git -C "$TARGET" config core.ignorecase false
      st_ok "core.ignorecase was true (inherited from a case-insensitive origin fs) on a "
      st_ok "  case-SENSITIVE filesystem — corrected to false on this copy"
    fi
  fi
else
  st_info "would set gc.auto=0 as the first operation"
fi

# ------------------------------------------------------------------ 2. census
IDX="$TARGET/.git/index"
if [ -f "$IDX" ]; then
  IDX_SIZE=$(st_size "$IDX"); IDX_SHA=$(st_sha256 "$IDX")
  st_ok "index: $IDX_SIZE bytes  sha256 ${IDX_SHA}"
  if [ "$APPLY" -eq 1 ] && [ -w "$TARGET/.git" ]; then
    cp -p "$IDX" "$IDX.st-bak-$(st_ts)" && st_ok "index backed up beside itself"
  fi
else
  st_bad "no .git/index — there is nothing staged to rescue"
fi

N_IDX=$(G ls-files 2>/dev/null | wc -l | tr -d ' ')
N_LOOSE=$(find "$TARGET/.git/objects" -type f -not -path '*/pack/*' 2>/dev/null | wc -l | tr -d ' ')
N_PACK=$(ls -1 "$TARGET/.git/objects/pack"/*.pack 2>/dev/null | wc -l | tr -d ' ')
HEAD_SHA=$(G rev-parse --verify HEAD 2>/dev/null)
st_ok "index entries: $N_IDX   loose objects: $N_LOOSE   packfiles: $N_PACK"
if [ -n "$HEAD_SHA" ]; then
  st_ok "HEAD exists ($(echo "$HEAD_SHA" | cut -c1-12)) — this repo already has commits"
  N_HEAD=$(G ls-tree -r HEAD --name-only 2>/dev/null | wc -l | tr -d ' ')
  st_info "HEAD tree holds $N_HEAD files"
  st_info "there is nothing fragile here in the unborn-HEAD sense; the drift step will produce"
  st_info "  a patch, not a commit"
else
  st_warn "HEAD is UNBORN — $N_IDX filenames exist ONLY in .git/index"
fi

# untracked / ignored: NOT represented in git at all, must be preserved by file copy
N_UNTRACKED=$(G status --porcelain 2>/dev/null | grep -c '^??' || true)
N_IGNORED=$(G status --porcelain --ignored 2>/dev/null | grep -c '^!!' || true)
st_info "untracked: $N_UNTRACKED   ignored: $N_IGNORED  — neither is in git; file copy is the only thing preserving them"

# ------------------------------------------------------------------ 3. blob completeness
st_log ""
st_log "BLOB COMPLETENESS — is every index entry's object actually present?"
# The gc.log check runs BEFORE fsck: fsck can CREATE a gc.log, and the check then reported
# "something has already attempted a gc here" about its own predecessor.
[ -f "$TARGET/.git/gc.log" ] && st_warn "a .git/gc.log exists (checked before fsck ran) — something has already attempted a gc here"
MISSING=$(G ls-files -s 2>/dev/null | awk '{print $2}' | sort -u | \
          G cat-file --batch-check='%(objectname) %(objecttype)' 2>/dev/null | \
          grep -c 'missing' || true)
TOTAL_BLOBS=$(G ls-files -s 2>/dev/null | awk '{print $2}' | sort -u | wc -l | tr -d ' ')
if [ "$TOTAL_BLOBS" -eq 0 ]; then
  st_skip "blob completeness (no index entries to check)"
elif [ "${MISSING:-0}" -eq 0 ]; then
  st_ok "all $TOTAL_BLOBS distinct staged blobs are present in the object store"
else
  st_bad "$MISSING of $TOTAL_BLOBS staged blobs are MISSING — the index references objects that do not exist"
fi
# `git fsck` alone treats the index as a reachability root on modern git, so staged blobs
# do NOT show as dangling there. --no-index-objects removes that root and shows the real
# exposure: objects whose ONLY reference is the 34 KB index file.
ORPHAN=$(G fsck --no-progress --unreachable --no-index-objects 2>&1 | grep -cE '^(dangling|unreachable)' || true)
if [ "${ORPHAN:-0}" -gt 0 ] && [ -z "$HEAD_SHA" ]; then
  st_warn "$ORPHAN object(s) are referenced ONLY by .git/index — a git gc or git prune, which"
  st_warn "  several porcelain commands trigger automatically, would delete them outright"
else
  st_info "objects referenced only by the index: ${ORPHAN:-0}"
fi

# ------------------------------------------------------------------ 3b. secrets gate
# `.gitignore` before `git add` is an ORDERING RULE, not a suggestion: a commit that
# captures a private key propagates it into the bundle and the bare mirror, both of which
# are then treated as durable artifacts.
SENS_HITS=""
if [ -n "$SENSLIST" ]; then
  if [ ! -r "$SENSLIST" ]; then
    st_bad "--sensitive-list not readable: $SENSLIST"
  else
    UNTRACKED_TMP="$(mktemp "${TMPDIR:-/tmp}/st-untracked.XXXXXX")"
    G ls-files --others --exclude-standard > "$UNTRACKED_TMP" 2>/dev/null
    SENS_HITS="$(python3 - "$SENSLIST" "$UNTRACKED_TMP" <<'PY'
import os, sys
want = set()
for line in open(sys.argv[1]):
    line = line.split('#', 1)[0].strip()
    if not line:
        continue
    # SENSITIVE.txt rows are checkpoint-relative ("project/path/to/x.key")
    want.add(line)
    if line.startswith("project/"):
        want.add(line[len("project/"):])
    want.add(os.path.basename(line))
for line in open(sys.argv[2]):
    p = line.rstrip('\n')
    if not p:
        continue
    if p in want or os.path.basename(p) in want:
        print(p)
PY
)"
    if [ -n "$SENS_HITS" ]; then
      # WARN here, hard FAIL at the point of the `git add -A` drift commit. A repo with
      # real history never reaches that commit, and blocking the whole rescue would deny
      # it the bundle and mirror for a risk it does not run.
      st_warn "these untracked, unignored paths are on the sensitive list:"
      printf '%s\n' "$SENS_HITS" | head -20 | while IFS= read -r l; do st_log "        $l"; done
      st_warn "  Add them to .gitignore FIRST (that is the ordering rule), or quarantine them"
      st_warn "  outside the tree. Any \`git add -A\` commit propagates them into repo.bundle"
      st_warn "  and repo.git, both of which are then treated as durable artifacts."
      st_warn "  The drift commit below is REFUSED while this list is non-empty."
    else
      st_ok "no sensitive-list path is untracked-and-unignored"
    fi
  fi
else
  st_warn "no --sensitive-list given. A drift commit runs \`git add -A\`; pass"
  st_warn "  --sensitive-list <checkpoint>/manifest/SENSITIVE.txt so keys and .env files"
  st_warn "  cannot be swept into a commit, a bundle and a mirror."
fi

if [ "$APPLY" -eq 0 ]; then
  st_log ""
  st_log "REPORT ONLY. Re-run with --apply (and --work, or --in-place) to rescue."
  st_summary "GIT-RESCUE-REPORT"; exit $?
fi
[ "$ST_FAIL" -eq 0 ] || { st_log "refusing to write with failures recorded"; exit 1; }

# ------------------------------------------------------------------ 4. commit the index
st_log ""
AUTHOR_NAME="$(printf '%s' "$AUTHOR" | sed -e 's/[[:space:]]*<.*//')"
AUTHOR_MAIL="$(printf '%s' "$AUTHOR" | sed -n 's/.*<\(.*\)>.*/\1/p')"
git -C "$TARGET" config user.name  "$AUTHOR_NAME" >/dev/null 2>&1
git -C "$TARGET" config user.email "${AUTHOR_MAIL:-session-transporter@localhost}" >/dev/null 2>&1

if [ -z "$HEAD_SHA" ]; then
  st_info 'committing the index as-is (no git-add: the staged set is exactly what we rescue)'
  git -C "$TARGET" commit --no-verify --no-gpg-sign -m "$MSG" >/dev/null 2>&1
  rc=$?
  HEAD_SHA=$(G rev-parse --verify HEAD 2>/dev/null)
  if [ $rc -ne 0 ] || [ -z "$HEAD_SHA" ]; then
    st_bad "index commit failed (rc=$rc) — the blobs are still dangling"
  else
    N_HEAD=$(G ls-tree -r HEAD --name-only | wc -l | tr -d ' ')
    st_ok "commit #1 $(echo "$HEAD_SHA" | cut -c1-12) — $N_HEAD files now have durable names"
    if [ "$N_HEAD" -eq "$N_IDX" ]; then
      st_ok "tree file count == index entry count ($N_IDX): nothing was lost in the conversion"
    else
      st_bad "tree holds $N_HEAD files but the index had $N_IDX — DO NOT DISCARD the index backup"
    fi
  fi
  RESCUED_UNBORN=1
else
  st_ok "HEAD already exists; skipping the index commit"
  RESCUED_UNBORN=0
fi

# ------------------------------------------------------------------ 5. drift
st_log ""
mkdir -p "$OUT" || st_die "cannot create $OUT"
DRIFT=$(G status --porcelain 2>/dev/null | wc -l | tr -d ' ')
if [ "$DRIFT" -eq 0 ]; then
  st_ok "no working-tree drift"
elif [ "$RESCUED_UNBORN" -eq 1 ]; then
  # Only legitimate for a repo whose entire history we just created: "commit everything"
  # IS the rescue there. On a repo with real history it diverges the branch and destroys a
  # curated staging set, so that path writes artifacts instead (below).
  st_info "$DRIFT path(s) differ from the new commit (working-tree drift, incl. untracked)"
  if [ -n "$SENS_HITS" ]; then
    st_bad "refusing the drift commit: sensitive paths are still untracked and unignored"
  else
    git -C "$TARGET" add -A >/dev/null 2>&1
    git -C "$TARGET" commit --no-verify --no-gpg-sign -m "rescue: working-tree drift at migration time" >/dev/null 2>&1
    rc=$?
    if [ $rc -eq 0 ]; then
      D_SHA=$(G rev-parse --verify HEAD)
      N_HEAD2=$(G ls-tree -r HEAD --name-only | wc -l | tr -d ' ')
      st_ok "commit #2 $(echo "$D_SHA" | cut -c1-12) — tree now holds $N_HEAD2 files"
      st_info "  the index was STALE relative to the working tree on the reference run: 26 added"
      st_info "  and 6 modified files, including an entire required crate, that an index-only"
      st_info "  rescue would have lost"
    else
      st_info "nothing to commit for drift (rc=$rc)"
    fi
  fi
else
  st_warn "$DRIFT path(s) differ from HEAD, and this repo HAS REAL HISTORY."
  st_warn "  NOT committing: \`git add -A\` onto a branch with an upstream silently diverges"
  st_warn "  it and destroys a deliberately-curated staging set. Capturing artifacts instead:"
  G diff HEAD > "$OUT/drift.patch" 2>/dev/null
  G ls-files --others --exclude-standard > "$OUT/untracked.txt" 2>/dev/null
  G status --porcelain > "$OUT/status.txt" 2>/dev/null
  st_ok "  $OUT/drift.patch      ($(st_size "$OUT/drift.patch") bytes, tracked-file changes)"
  st_ok "  $OUT/untracked.txt    ($(wc -l < "$OUT/untracked.txt" | tr -d ' ') untracked paths)"
  st_ok "  $OUT/status.txt"
  st_info "  the untracked files themselves are preserved by the FILE COPY, not by git."
  st_info "  Decide deliberately what to commit; do not let a rescue script decide."
fi
N_IGNORED2=$(G status --porcelain --ignored 2>/dev/null | grep -c '^!!' || true)
[ "${N_IGNORED2:-0}" -gt 0 ] && st_warn "$N_IGNORED2 ignored path(s) remain outside git entirely — only the file copy preserves them"

# ------------------------------------------------------------------ 6. bundle + mirror
st_log ""
BUNDLE="$OUT/repo.bundle"
rm -f "$BUNDLE"
git -C "$TARGET" bundle create "$BUNDLE" --all >/dev/null 2>&1
rc=$?
if [ $rc -eq 0 ] && [ -s "$BUNDLE" ]; then
  st_ok "bundle: $BUNDLE ($(st_human "$(st_size "$BUNDLE")"))"
  if git -C "$TARGET" bundle verify "$BUNDLE" >/dev/null 2>&1; then
    st_ok "bundle verifies"
  else
    st_bad "bundle does NOT verify"
  fi
else
  st_bad "bundle creation failed (rc=$rc)"
fi

MIRROR="$OUT/repo.git"
rm -rf "$MIRROR"
git clone --mirror "$TARGET" "$MIRROR" >/dev/null 2>&1
rc=$?
if [ $rc -eq 0 ]; then
  git -C "$MIRROR" config gc.auto 0 >/dev/null 2>&1
  M_HEAD=$(git --no-optional-locks -C "$MIRROR" rev-parse --verify HEAD 2>/dev/null)
  M_FILES=$(git --no-optional-locks -C "$MIRROR" ls-tree -r HEAD --name-only 2>/dev/null | wc -l | tr -d ' ')
  st_ok "bare mirror: $MIRROR"
  if [ "$M_HEAD" = "$(G rev-parse --verify HEAD)" ]; then
    st_ok "mirror HEAD matches the source ($(echo "$M_HEAD" | cut -c1-12))"
  else
    st_bad "mirror HEAD differs from the source"
  fi
  if [ "$M_FILES" = "$(G ls-tree -r HEAD --name-only | wc -l | tr -d ' ')" ]; then
    st_ok "mirror tree holds the same $M_FILES files"
  else
    st_bad "mirror tree file count differs"
  fi
  git --no-optional-locks -C "$MIRROR" fsck --no-progress >/dev/null 2>&1 \
    && st_ok "mirror passes fsck" || st_warn "mirror fsck reported findings (see: git -C $MIRROR fsck)"
else
  st_bad "mirror clone failed (rc=$rc)"
fi

# ------------------------------------------------------------------ 7. postflight
st_log ""
st_log "POSTFLIGHT"
N_IDX2=$(G ls-files | wc -l | tr -d ' ')
[ "$N_IDX2" = "$N_IDX" ] && st_ok "index still holds $N_IDX entries" \
                         || st_warn "index now holds $N_IDX2 entries (was $N_IDX) — expected after the drift commit"
BAK="$(ls -1t "$TARGET/.git"/index.st-bak-* 2>/dev/null | head -1)"
if [ -n "$BAK" ]; then
  if [ "$(st_sha256 "$BAK")" = "$IDX_SHA" ]; then
    st_ok "the pre-rescue index backup is intact ($BAK)"
  else
    st_bad "the index backup does not match the hash recorded before the rescue"
  fi
fi
st_log ""
if [ "$WROTE_IN_PLACE" -eq 1 ]; then
  st_warn "THIS RAN IN PLACE: $REPO was WRITTEN TO (config, index backup, commits)."
  st_warn "  Nothing was copied first. If that repository is the origin's, say so plainly to"
  st_warn "  the user — the migration's read-only claim no longer covers it."
else
  st_log "The source repo at $REPO is UNCHANGED — this ran on the copy at $TARGET."
  st_log "Creating the first commit on the origin itself is a WRITE and must be done by the"
  st_log "user, not by this skill."
fi
st_summary "GIT-RESCUE"
exit $?
