#!/usr/bin/env python3
"""st-transplant.py — G5/G6/G7. Install a checkpointed Claude Code session at a new
location, on a new host, under a new account.  "Tier 0": the transcript's historical
bytes are NEVER modified.

Why that is safe, and why nothing else is needed (all measured, do not re-litigate):

  * Per-record `$.cwd` is INERT on the resume path. A control run rewrote EVERY record's
    cwd to a different path; the session still ran from the launch directory. Relocating
    a session therefore requires NO transcript rewriting at all.
  * The effective cwd comes from the LAUNCH DIRECTORY.
  * Resume is cwd-scoped: the resolver only searches project dirs derived from
    realpath(launch dir). There is NO global fallback. A wrong directory name gives
    "No conversation found with session ID".
  * Resume is a pure APPEND. The first N bytes stay byte-identical.
  * The FILENAME STEM is load-bearing: sidecars resolve as
    `<transcript path minus .jsonl>/{subagents,tool-results,workflows}`. Renaming the
    file orphans them silently — which is why --new-session-id renames the .jsonl and
    its sidecar directory in the SAME operation, and is the only supported way to fork.
  * `relocated` records are NOT honoured on `--resume=<id>` (only on the in-REPL
    /resume). One is still appended — it is free and it fixes that one path — but the
    relocation is communicated to the MODEL twice instead: an appended notice, and a
    durable CLAUDE.md that survives compaction.

What is therefore installed:
  1. the project tree                      (from the checkpoint, permissions repaired)
  2. the transcript, byte-verbatim         (stem unchanged, mode 0600)
  3. an appended relocation notice + a `relocated` record   (never a rewrite)
  4. sidecars, memory, tasks, and the SIBLING project keys' workflow scripts
  5. a durable CLAUDE.md between per-session markers
  6. shared assets INSTALLED at the destination (the M4 guard), before any launch
  7. a Desktop session JSON under <user-data-dir>/claude-code-sessions/<acct>/<org>/

Every step is idempotent and re-runnable; every copy out of a sealed checkpoint is
followed by an explicit chmod (a sealed source propagates a-w and breaks the next run).
Nothing that already exists at the destination is deleted: files that would be replaced
are backed up first, and a destination transcript that is a byte-exact EXTENSION of the
checkpoint is recognised as a resumed session and left alone.

Stdlib only. --plan writes nothing.
"""
import argparse
import errno
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    from mangle import mangle                      # noqa: E402  (canonical, 22/22)
except ImportError:                                                # pragma: no cover
    sys.stderr.write("st-transplant: mangle.py must sit beside this script\n")
    raise

NOTICE_TAG = "[WORKSPACE RELOCATION NOTICE"
TAIL_WINDOW = 65536          # the `relocated` reverse scan only reads the last 64 KiB
RECEIPT = ".st-receipt.json"


def mark_begin(sid):
    # Session-scoped markers: two sessions migrated into ONE destination root must both
    # keep their path table. A single global marker pair meant the second run's re.sub
    # replaced the first run's block, and the durable half of the relocation message is
    # the only half that survives compaction.
    return "<!-- BEGIN session-transporter relocation notice: %s -->" % sid


def mark_end(sid):
    return "<!-- END session-transporter relocation notice: %s -->" % sid


# ------------------------------------------------------------------ small helpers
class Report(object):
    def __init__(self):
        self.fail = 0
        self.warn = 0

    def ok(self, msg):
        print("  OK     %s" % msg)

    def info(self, msg):
        print("  ..     %s" % msg)

    def warn_(self, msg):
        self.warn += 1
        print("  WARN   %s" % msg)

    def bad(self, msg):
        self.fail += 1
        print("  FAIL   %s" % msg)

    def notrun(self, msg):
        self.fail += 1
        print("  NOTRUN %s  — a check that did not execute counts as a failure" % msg)


R = Report()


def stamp():
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())


def sha256(path, limit=None):
    h = hashlib.sha256()
    n = 0
    with open(path, "rb") as f:
        while True:
            want = 1 << 20 if limit is None else min(1 << 20, limit - n)
            if want <= 0:
                break
            b = f.read(want)
            if not b:
                break
            h.update(b)
            n += len(b)
    if limit is not None and n < limit:
        raise IOError("file shorter than the requested prefix")
    return h.hexdigest()


def count_files(path):
    if not os.path.isdir(path):
        return 0
    return sum(len(f) for _, _, f in os.walk(path))


def dir_bytes(path):
    tot = 0
    for base, _, files in os.walk(path):
        for f in files:
            try:
                tot += os.path.getsize(os.path.join(base, f))
            except OSError:
                pass
    return tot


def human(n):
    n = float(n or 0)
    for u in ("B", "KiB", "MiB", "GiB", "TiB"):
        if n < 1024 or u == "TiB":
            return "%.1f %s" % (n, u)
        n /= 1024


def resolve_dest(p):
    """realpath of the DEEPEST EXISTING ANCESTOR, with the remainder re-joined.

    `os.path.realpath(p) if os.path.exists(p) else os.path.abspath(p)` was wrong in the
    single most common case: a destination that does not exist yet, behind a symlinked
    parent (/home -> /export/home, /Users -> /System/Volumes/Data/Users). The first run
    computed the key from the NON-realpath, wrote the transcript there, and the CLI —
    which resolves realpath itself — then reported "No conversation found with session
    ID". The re-run, with the directory now created, computed a DIFFERENT key.
    """
    p = os.path.abspath(p)
    tail = []
    q = p
    while not os.path.exists(q):
        q, t = os.path.split(q)
        if not t:
            break
        tail.insert(0, t)
    return os.path.join(os.path.realpath(q), *tail) if tail else os.path.realpath(q)


def _pycopy(src, dst, extra):
    """rsync -a --no-perms --chmod=u+rwX,go-w SRC/ DST/ for machines without rsync (Windows). Supports exactly the
    extra arguments this script passes (--exclude=.git/, --backup --backup-dir=DIR) and refuses anything else, so it
    can never silently diverge from rsync's behaviour."""
    excl_git, backup_dir = False, None
    for x in extra or []:
        if x == "--exclude=.git/":
            excl_git = True
        elif x == "--backup":
            pass
        elif x.startswith("--backup-dir="):
            backup_dir = x.split("=", 1)[1]
        else:
            R.bad("internal: the Python copy fallback does not support rsync option %r" % x)
            return False
    src, dst = src.rstrip("/\\"), dst.rstrip("/\\")
    for base, dirs, files in os.walk(src):
        if excl_git:
            dirs[:] = [d for d in dirs if d != ".git"]
        rel = os.path.relpath(base, src)
        tdir = dst if rel == "." else os.path.join(dst, rel)
        os.makedirs(tdir, exist_ok=True)
        os.chmod(tdir, (os.stat(tdir).st_mode | 0o700) & ~0o022)
        for f in files:
            s_, d_ = os.path.join(base, f), os.path.join(tdir, f)
            if os.path.islink(s_):
                if os.path.lexists(d_):
                    os.remove(d_)
                os.symlink(os.readlink(s_), d_)
                continue
            if os.path.isfile(d_) and backup_dir and not (os.path.getsize(s_) == os.path.getsize(d_)
                                                           and sha256(s_) == sha256(d_)):
                b = os.path.join(backup_dir, os.path.relpath(d_, dst))
                os.makedirs(os.path.dirname(b), exist_ok=True)
                shutil.copy2(d_, b)
            if os.path.isfile(d_):
                os.chmod(d_, 0o600)
            shutil.copy2(s_, d_)
            m = os.stat(s_).st_mode
            os.chmod(d_, ((m | 0o600) | (0o100 if m & 0o111 else 0)) & ~0o022)
    return True


def rsync(src, dst, extra=None):
    """Copy out of a possibly-sealed checkpoint. --no-perms --chmod is MANDATORY:
    plain -a propagates the checkpoint's a-w mode into the live tree (mistake M6).
    Without rsync (Windows) or with ST_NO_RSYNC=1, a pure-Python copy with the same contract is used."""
    if os.environ.get("ST_NO_RSYNC") == "1" or not shutil.which("rsync"):
        try:
            return _pycopy(src, dst, extra)
        except OSError as e:
            R.bad("copy failed: %s" % e)
            return False
    cmd = ["rsync", "-a", "--no-perms", "--chmod=u+rwX,go-w"]
    if extra:
        cmd += extra
    cmd += [src, dst]
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if p.returncode != 0:
        R.bad("rsync failed rc=%d: %s" % (p.returncode, p.stdout.decode("utf-8", "replace")[-400:]))
        return False
    return True


def would_overwrite(src_root, dst_root):
    """Files in the checkpoint that exist at the destination with DIFFERENT content.
    rsync's quick check is size+mtime, and the checkpoint is always older, so every
    re-run silently reverted destination edits and printed OK."""
    out = []
    for base, _, files in os.walk(src_root):
        for f in files:
            s = os.path.join(base, f)
            rel = os.path.relpath(s, src_root)
            d = os.path.join(dst_root, rel)
            if not os.path.isfile(d):
                continue
            try:
                if os.path.getsize(s) == os.path.getsize(d) and sha256(s) == sha256(d):
                    continue
            except (IOError, OSError):
                pass
            out.append(rel)
    return sorted(out)


def last_uuid(path):
    """The last record that HAS a uuid. The file ends with mode/ai-title/custom-title
    records, none of which carry one — a naive 'last line' read returns nothing."""
    try:
        with open(path, "rb") as f:                # last ~400 lines without `tail` (absent on Windows)
            f.seek(0, 2)
            n = f.tell()
            f.seek(max(0, n - (4 << 20)))
            out = b"\n".join(f.read().split(b"\n")[-401:])
    except Exception:                                              # noqa: BLE001
        return None
    u = None
    for line in out.decode("utf-8", "replace").splitlines():
        try:
            d = json.loads(line)
        except Exception:                                          # noqa: BLE001
            continue
        if d.get("uuid"):
            u = d["uuid"]
    return u


def in_record_session_id(path):
    """The `relocated` record must carry the IN-RECORD session id, not the filename uuid:
    two of its three consumers key off it."""
    try:
        with open(path, "r", errors="replace") as f:
            for _ in range(200):
                line = f.readline()
                if not line:
                    break
                try:
                    d = json.loads(line)
                except Exception:                                  # noqa: BLE001
                    continue
                if d.get("sessionId"):
                    return d["sessionId"]
    except IOError:
        pass
    return None


def tail_contains(path, needle, window=TAIL_WINDOW):
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            f.seek(max(0, size - window))
            return needle.encode("utf-8") in f.read()
    except IOError:
        return False


def contains_after(path, needle, start):
    """Scan from byte `start` to EOF. The notice guard used a fixed 1 MiB tail window, so
    once the destination session had appended more than that — routine — a re-run
    appended a SECOND relocation notice into the middle of a live conversation."""
    nb = needle.encode("utf-8")
    try:
        with open(path, "rb") as f:
            f.seek(max(0, start))
            prev = b""
            while True:
                chunk = f.read(1 << 20)
                if not chunk:
                    return False
                if nb in prev + chunk:
                    return True
                prev = chunk[-len(nb):] if len(nb) > 1 else b""
    except IOError:
        return False


def instance_running(user_data_dir=None):
    """`pgrep -af <pattern>` SELF-MATCHES (two measured false positives). Use ps+filter,
    and never `pkill -f` — it self-matched and killed a run mid-experiment.

    With user_data_dir=None this reports EVERY claude/electron process on the host, which
    is what matters before touching a host-wide file such as ~/.claude.json."""
    try:
        out = subprocess.run(["ps", "-eo", "pid,comm,args"],
                             stdout=subprocess.PIPE).stdout.decode("utf-8", "replace")
    except Exception:                                              # noqa: BLE001
        return None
    me = str(os.getpid())
    par = str(os.getppid())
    hits = []
    for line in out.splitlines()[1:]:
        f = line.split(None, 2)
        if len(f) < 3:
            continue
        if f[0] in (me, par):
            continue
        if "claude" not in f[1].lower() and "electron" not in f[1].lower():
            continue
        if user_data_dir and user_data_dir not in line:
            continue
        hits.append(line.strip()[:200])
    return hits


def atomic_write(path, text, mode=0o600):
    tmp = path + ".st-tmp"
    with open(tmp, "w") as f:
        f.write(text)
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def makedirs_mode(path, mode):
    """os.makedirs(p, mode) applies the mode to the LEAF only; every intermediate gets
    the umask default. For claude-code-sessions/<account>/<org> that left two of the
    three directories group/world-readable while the leaf check reported 0700."""
    parts = []
    p = path
    while p and not os.path.isdir(p):
        parts.insert(0, p)
        n = os.path.dirname(p)
        if n == p:
            break
        p = n
    for q in parts:
        try:
            os.mkdir(q, mode)
        except OSError as e:
            if e.errno != errno.EEXIST:
                raise
        try:
            os.chmod(q, mode)
        except OSError:
            pass


# ------------------------------------------------------------------ notice text
def build_moves(origin_root, dest_root, origin_home, dest_home, origin_claude, dest_claude):
    moves = []
    if origin_root:
        moves.append((origin_root, dest_root))
    if origin_claude and dest_claude:
        moves.append((origin_claude, dest_claude))
    if origin_home and dest_home and origin_home != dest_home:
        moves.append((origin_home, "%s  (only where it means the home directory)" % dest_home))
    return moves or [("<origin>", dest_root)]


def notice_text(moves, origin_desc, dest_desc, extra):
    table = "\n".join("  %s\n    -> %s" % (a, b) for a, b in moves)
    return """%s — inserted by the session transporter, not by the user]

This session has been migrated to a different machine and/or a different account. The
conversation above is intact and unmodified, but **the filesystem it describes no longer
exists as written**. Read this before acting on any path from earlier in the history.

  origin    %s
  current   %s

Path mapping — every earlier reference to the left-hand path now means the right-hand one:

%s

Consequences you must account for:

* Many lines of the history above reference the origin paths. Those paths are historical
  record, not live locations. Translate them through the table above; do not assume any
  of them exists.
* Scripts, configs and notes written earlier may contain hardcoded origin paths and will
  need updating before they run here. Treat a path failure as expected, not surprising.
* Tooling may differ on this host: architecture-specific binaries from the origin cannot
  necessarily execute here. Do not install anything into the host system to compensate
  without asking.
* The origin may be reachable read-only. It is the archived source. Do not write to it
  without explicit user authorization.
%s
The work itself is unchanged. Continue from where the history leaves off.
""" % (NOTICE_TAG, origin_desc, dest_desc, table,
       ("\n" + extra.rstrip() + "\n") if extra else "")


def claude_md_block(sid, moves, origin_desc, dest_desc, ckpt, counts, extra):
    table = "\n".join("| `%s` | `%s` |" % (a, b) for a, b in moves)
    return """%s
# Relocated workspace — session %s

This tree was migrated by `session-transporter`.

  origin   %s
  current  %s

The session history in this project predates the move and refers throughout to the origin
paths. It was deliberately **not rewritten** — the conversation is preserved byte-for-byte
and the historical `cwd` fields are inert. Translate paths through this table:

| was | is now |
|---|---|
%s

## Things that changed with the move

- Paths from before the move do not exist here. Use the table above.
- Old scripts may hold hardcoded origin paths and will need updating before they run.
- Architecture-specific binaries from the origin may not execute on this host.
- The origin, if reachable, is **read-only** unless the user says otherwise.
%s
## Provenance

Verified byte-exact checkpoint: `%s`
%s
The origin was not modified by the migration.
%s""" % (mark_begin(sid), sid, origin_desc, dest_desc, table,
         ("\n" + extra.rstrip() + "\n") if extra else "",
         ckpt, counts, mark_end(sid))


def dashsafe(argv, opts):
    """EVERY project key begins with '-' (the mangler maps the leading '/' of an absolute
    path to a dash). argparse reads a leading-dash value as the next option and dies with
    "expected one argument". Rewrite `--opt VALUE` to `--opt=VALUE` for the affected
    options so both spellings work."""
    out = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in opts and i + 1 < len(argv):
            out.append("%s=%s" % (a, argv[i + 1]))
            i += 2
            continue
        out.append(a)
        i += 1
    return out


# ------------------------------------------------------------------ main
def find_rehome():
    """claude-desktop-rehome's ccd-rehome: $ST_REHOME, a sibling skill, ~/.claude/skills, or PATH."""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for c in (os.environ.get("ST_REHOME", ""),
              os.path.join(os.path.dirname(here), "claude-desktop-rehome", "scripts", "ccd-rehome"),
              os.path.expanduser("~/.claude/skills/claude-desktop-rehome/scripts/ccd-rehome"),
              shutil.which("ccd-rehome") or ""):
        if c and os.path.isfile(c):
            return c
    return None


def main():
    sys.argv[1:] = dashsafe(sys.argv[1:], ("--origin-key",))
    ap = argparse.ArgumentParser(
        description="install a checkpointed Claude Code session at a new location")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--plan", action="store_true", help="show what would happen; write nothing")
    g.add_argument("--apply", action="store_true", help="do it (idempotent, re-runnable)")

    ap.add_argument("--checkpoint", default=os.environ.get("ST_CKPT", ""),
                    help="a sealed checkpoint generation (or its `latest-<SID>` symlink)")
    ap.add_argument("--session-id", default=os.environ.get("ST_SESSION_ID", ""))
    ap.add_argument("--origin-key", default=os.environ.get("ST_ORIGIN_KEY", ""),
                    help="LITERAL origin project-dir name (never derived by editing another)")
    ap.add_argument("--origin-root", default=os.environ.get("ST_ORIGIN_ROOT", ""))
    ap.add_argument("--origin-claude", default=os.environ.get("ST_ORIGIN_CLAUDE", ""))
    ap.add_argument("--origin-desc", default="", help="human description of the origin host/account")

    ap.add_argument("--dest-root", default=os.environ.get("ST_DEST_ROOT", ""))
    ap.add_argument("--claude-home", default=os.environ.get("ST_CLAUDE_HOME",
                                                            os.path.expanduser("~/.claude")))
    ap.add_argument("--dest-desc", default="", help="human description of this host/account")
    ap.add_argument("--cli-version", default=os.environ.get("ST_CLI_VERSION", ""),
                    help="destination CLI version, stamped into the appended record "
                         "(st-preflight.sh prints it; --emit-profile records it)")

    ap.add_argument("--user-data-dir", default=os.environ.get("ST_USER_DATA_DIR", ""))
    ap.add_argument("--account", default=os.environ.get("ST_ACCOUNT", ""))
    ap.add_argument("--org", default=os.environ.get("ST_ORG", ""))
    ap.add_argument("--title", default="")
    ap.add_argument("--model", default="",
                    help="model id for the minted Desktop session. Default: omit the key "
                         "and let the app choose — model availability is account-scoped.")
    ap.add_argument("--effort", default="high")
    ap.add_argument("--permission-mode", default="default")

    ap.add_argument("--skill", action="append", default=[],
                    help="install this skill at the destination (repeatable); default: all "
                         "skills present in the checkpoint")
    ap.add_argument("--no-skills", action="store_true")
    ap.add_argument("--overwrite-skill", action="append", default=[],
                    help="permit replacing this already-installed destination skill "
                         "(repeatable; 'ALL' permits every collision)")
    # default=None, not a list: with action=append a list default is APPENDED TO, so the defaults could never be
    # turned off (found on a live run: it would have created a settings.json enabling an absent plugin)
    ap.add_argument("--settings-key", action="append", default=None,
                    help="merge only these keys out of the origin settings.json (repeatable; REPLACES the default "
                         "skipWorkflowUsageWarning + enabledPlugins)")
    ap.add_argument("--no-settings", action="store_true", help="merge nothing into the destination settings.json")
    ap.add_argument("--no-memory", action="store_true",
                    help="do not install the project memory/ (it is project-wide, not per session)")
    ap.add_argument("--record-file", default="",
                    help="a ccd-record/1 file (from `ccd-rehome export-record`, or inside a session bundle): the "
                         "Desktop record to adopt, with all its settings, instead of a minimal one")
    ap.add_argument("--no-project-tree", action="store_true")
    ap.add_argument("--merge-git", action="store_true",
                    help="allow the checkpoint's .git to be copied over an existing "
                         "destination .git. Off by default: it clobbers refs, index AND "
                         "the reflog that would recover them.")
    ap.add_argument("--overwrite-destination-work", action="store_true",
                    help="permit replacing destination files whose content differs from "
                         "the checkpoint (they are backed up under .st-overwritten/<ts>/)")
    ap.add_argument("--no-relocated-record", action="store_true")
    ap.add_argument("--trust", action="store_true",
                    help="add projects[<dest root>].hasTrustDialogAccepted to the CLI's "
                         "global config. OFF by default: that file is host-wide and shared "
                         "with every running process.")
    ap.add_argument("--new-session-id", default="",
                    help="FORK: install under this session id instead. Renames the .jsonl "
                         "AND its sidecar directory in the same operation — the only "
                         "supported way to rename, because sidecars resolve from the stem.")
    ap.add_argument("--notice-extra-file", default="",
                    help="extra prose appended to the notice and to CLAUDE.md")
    ap.add_argument("--allow-existing", action="store_true",
                    help="proceed when a DIFFERENT transcript already sits at the "
                         "destination path (it is renamed aside, never deleted)")
    ap.add_argument("--force", action="store_true",
                    help="proceed with steps 1-6 even if the target Desktop instance "
                         "appears to be running. It never permits step 7.")
    a = ap.parse_args()

    if not a.checkpoint:
        ap.error("--checkpoint is required")
    ckpt = os.path.realpath(a.checkpoint)

    # ---- provenance recorded by st-checkpoint.sh ---------------------------------
    prov = {}
    pfile = os.path.join(ckpt, "PROVENANCE")
    if os.path.isfile(pfile):
        for line in open(pfile):
            if "=" in line:
                k, v = line.rstrip("\n").split("=", 1)
                prov[k] = v
    sid = a.session_id or prov.get("session_id", "")
    okey = a.origin_key or prov.get("origin_key", "")
    oroot = a.origin_root or prov.get("origin_root", "")
    oclaude = a.origin_claude or prov.get("origin_claude", "")
    siblings = [s for s in (prov.get("sibling_keys", "") or "").split() if s]
    if not sid or not okey:
        ap.error("--session-id and --origin-key are required (no PROVENANCE in the checkpoint)")
    if not a.dest_root:
        ap.error("--dest-root is required")

    dest_sid = a.new_session_id or sid
    if a.new_session_id and a.new_session_id == sid:
        ap.error("--new-session-id equals the existing session id")

    typed = os.path.abspath(a.dest_root)
    dest_root = resolve_dest(a.dest_root)
    if dest_root != typed:
        R.warn_("destination realpath differs from the string given:")
        R.warn_("    given %s" % typed)
        R.warn_("    real  %s" % dest_root)
        R.warn_("  the mangler is fed the REALPATH; symlinked roots resolve through (K11)")
    claude_home = os.path.expanduser(a.claude_home)
    dest_key = mangle(dest_root)
    dest_dir = os.path.join(claude_home, "projects", dest_key)
    dest_tx = os.path.join(dest_dir, dest_sid + ".jsonl")

    src_tx = os.path.join(ckpt, "claude", "projects", okey, sid + ".jsonl")
    src_side = os.path.join(ckpt, "claude", "projects", okey, sid)
    src_mem = os.path.join(ckpt, "claude", "projects", okey, "memory")
    src_tasks = os.path.join(ckpt, "claude", "tasks", sid)
    src_skills = os.path.join(ckpt, "claude", "skills")
    src_settings = os.path.join(ckpt, "claude", "settings.json")
    src_plugins = os.path.join(ckpt, "claude", "plugins")
    src_project = os.path.join(ckpt, "project")

    origin_desc = a.origin_desc or ("%s : %s" % (prov.get("origin_host", "origin"), oroot or okey))
    dest_desc = a.dest_desc or ("%s : %s" % (platform.node(), dest_root))
    extra = ""
    if a.notice_extra_file:
        extra = open(a.notice_extra_file).read()

    print("=" * 74)
    print("ST-TRANSPLANT   %s" % ("[PLAN — nothing will be written]" if a.plan else "[APPLY]"))
    print("=" * 74)
    print("  checkpoint        %s" % ckpt)
    print("  session id        %s" % sid)
    if a.new_session_id:
        print("  FORK -> new id    %s   (.jsonl AND sidecar dir renamed together)" % dest_sid)
    print("  origin key        %s" % okey)
    if siblings:
        print("  sibling keys      %s" % ", ".join(siblings))
    print("  destination root  %s" % dest_root)
    print("  mangled key       %s   (%d chars)" % (dest_key, len(dest_key)))
    print("  transcript ->     %s" % dest_tx)
    print("  filename stem     %s  (sidecars resolve from it)" % dest_sid)
    if a.user_data_dir:
        print("  desktop session   %s/claude-code-sessions/%s/%s/"
              % (a.user_data_dir, a.account or "<account>", a.org or "<org>"))
    print("")
    print("  historical bytes  NOT modified — append only")
    print("  relocation        appended notice + `relocated` record + durable CLAUDE.md")
    print("")

    # ---- gates -------------------------------------------------------------------
    print("GATES")
    if os.path.isfile(os.path.join(ckpt, "COMPLETE")):
        R.ok("checkpoint carries the COMPLETE sentinel")
    else:
        R.bad("checkpoint has no COMPLETE sentinel — it was never verified; refusing")
    src_size = 0
    if not os.path.isfile(src_tx):
        R.bad("transcript missing from the checkpoint: %s" % src_tx)
    else:
        src_size = os.path.getsize(src_tx)
        R.ok("checkpoint transcript %s (%s)" % (src_size, human(src_size)))

    # The prefix comparison runs ALWAYS, --allow-existing or not. It used to sit inside
    # `if not a.allow_existing:`, so the flag skipped the one check that distinguishes a
    # partial run from a RESUMED session, then unlinked the file. Both "zero-loss proofs"
    # still printed OK afterwards, because after the unlink the prefix check compares a
    # fresh copy against its own source.
    resume_state = "fresh"
    displace_to = None
    if os.path.exists(dest_tx) and src_size:
        dsz = os.path.getsize(dest_tx)
        same_prefix = False
        if dsz >= src_size:
            try:
                same_prefix = sha256(dest_tx, limit=src_size) == sha256(src_tx)
            except IOError:
                same_prefix = False
        if same_prefix:
            resume_state = "already-placed"
            grown = dsz - src_size
            R.ok("a transcript is already at the destination and its first %d bytes are "
                 "byte-identical to the checkpoint" % src_size)
            if grown:
                R.ok("  it has grown by %d bytes — that is a RESUMED session, not a partial "
                     "run. It will not be touched." % grown)
        elif dsz < src_size:
            R.bad("a SHORTER transcript sits at %s (%d < %d). A byte-count DECREASE is the "
                  "signature of a stripping import path having run. Investigate before "
                  "overwriting anything." % (dest_tx, dsz, src_size))
            if a.allow_existing:
                displace_to = dest_tx + ".st-displaced-" + stamp()
                R.warn_("--allow-existing: it will be RENAMED to %s, never deleted"
                        % os.path.basename(displace_to))
                resume_state = "displace"
        else:
            if a.allow_existing:
                displace_to = dest_tx + ".st-displaced-" + stamp()
                resume_state = "displace"
                R.warn_("a DIFFERENT transcript sits at %s; --allow-existing given, so it "
                        "will be RENAMED to %s (never deleted)."
                        % (dest_tx, os.path.basename(displace_to)))
                R.warn_("  renaming also orphans its sidecar directory: decide what happens "
                        "to %s before relying on either." % os.path.join(dest_dir, dest_sid))
            else:
                R.bad("a DIFFERENT transcript already sits at %s — refusing. Move it aside, "
                      "or pass --allow-existing (which renames rather than deletes)." % dest_tx)

    desktop_blocked = False
    if a.user_data_dir:
        hits = instance_running(a.user_data_dir)
        rh = find_rehome() if hits is None else None
        if hits is None and rh:          # no `ps` (Windows): claude-desktop-rehome knows how to tell, on every OS
            pr = subprocess.run([sys.executable, "-I", rh, "status", a.user_data_dir, "--json", "--dry-run"],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                hits = ["running (per claude-desktop-rehome)"] if json.loads(pr.stdout)[0]["running"] else []
            except (ValueError, KeyError, IndexError):
                hits = None
        if hits is None:
            R.notrun("desktop-instance running check")
            desktop_blocked = True
        elif hits:
            msg = ("the Desktop instance using %s appears to be RUNNING. There is no file "
                   "watcher: a session JSON dropped in now will not appear, and the debounced "
                   "writer can destroy it." % a.user_data_dir)
            desktop_blocked = True
            if a.force:
                R.warn_(msg + "  (--force: steps 1-6 proceed; the session mint is still refused)")
            else:
                R.bad(msg + "  Stop that instance, then re-run.")
            for h in hits:
                print("         %s" % h)
        else:
            R.ok("no Desktop process is using %s" % a.user_data_dir)

    # ---- destination git repo ----------------------------------------------------
    dest_has_git = os.path.isdir(os.path.join(dest_root, ".git"))
    ckpt_has_git = os.path.isdir(os.path.join(src_project, ".git"))
    git_exclude = []
    if dest_has_git and ckpt_has_git and not a.no_project_tree:
        if a.merge_git:
            R.warn_("--merge-git: the checkpoint's .git will be copied over the destination's. "
                    "Refs, index and reflog are replaced; destination-only commits become "
                    "unreachable AND the reflog that would recover them goes in the same pass.")
        else:
            git_exclude = ["--exclude=.git/"]
            R.warn_("the destination root is already a git repository. Its .git is left ALONE "
                    "(--exclude=.git/); the origin's history should arrive as the bundle "
                    "st-git-rescue.sh produces, not by overwriting refs. Pass --merge-git to "
                    "override.")

    if R.fail and not a.plan:
        print("\nrefusing to apply with %d failed gate(s)." % R.fail)
        return 1

    # ---- inventory ---------------------------------------------------------------
    print("")
    print("WOULD INSTALL" if a.plan else "INSTALLING")
    inv = [
        ("project tree", src_project, count_files(src_project), dir_bytes(src_project)),
        ("sidecars", src_side, count_files(src_side), dir_bytes(src_side)),
        ("memory", src_mem, count_files(src_mem), dir_bytes(src_mem)),
        ("tasks", src_tasks, count_files(src_tasks), dir_bytes(src_tasks)),
        ("skills", src_skills, count_files(src_skills), dir_bytes(src_skills)),
    ]
    for name, path, n, b in inv:
        print("  %-14s %6d files %14s   %s" % (name, n, human(b),
                                               path if os.path.exists(path) else "(absent)"))

    # what the project-tree step would replace
    clobber = []
    if not a.no_project_tree and os.path.isdir(src_project) and os.path.isdir(dest_root):
        clobber = would_overwrite(src_project, dest_root)
        if clobber:
            print("")
            print("  %d destination file(s) hold DIFFERENT content from the checkpoint:"
                  % len(clobber))
            for rel in clobber[:15]:
                print("       %s" % rel)
            if len(clobber) > 15:
                print("       ... and %d more" % (len(clobber) - 15))
            print("  They are newer work, a partial run, or an edited copy. rsync's quick "
                  "check\n  is size+mtime and the checkpoint is always older, so without a gate "
                  "every\n  re-run silently reverts them and reports OK.")

    # skills that already exist at the destination
    skill_collisions = []
    if not a.no_skills and os.path.isdir(src_skills):
        names = a.skill or sorted(n for n in os.listdir(src_skills)
                                  if os.path.isdir(os.path.join(src_skills, n)))
        for n in names:
            d = os.path.join(claude_home, "skills", n)
            if os.path.isdir(d):
                skill_collisions.append(n)
        if skill_collisions:
            print("")
            print("  %d skill(s) already installed at the destination and would be replaced:"
                  % len(skill_collisions))
            for n in skill_collisions:
                print("       %s" % n)
            print("  Pass --overwrite-skill NAME (or --overwrite-skill ALL) to permit it.")

    if a.plan:
        print("\n  (plan only — re-run with --apply)")
        print("\n  NOTE: install shared assets BEFORE launching the destination. Skills are")
        print("  enumerated at CLI process startup and cached for the process lifetime; a")
        print("  skill added mid-session does not appear until a fresh process starts.")
        return 0 if R.fail == 0 else 1

    if clobber and not a.overwrite_destination_work:
        R.bad("%d destination file(s) would be replaced with OLDER checkpoint content. "
              "Refusing. Re-run with --overwrite-destination-work (they are backed up "
              "under .st-overwritten/) once you have looked at the list above."
              % len(clobber))
        print("\nrefusing to apply with %d failed gate(s)." % R.fail)
        return 1
    bad_skills = [n for n in skill_collisions
                  if n not in a.overwrite_skill and "ALL" not in a.overwrite_skill]
    if bad_skills:
        R.bad("%d skill(s) already exist at the destination: %s. Refusing to replace them. "
              "Pass --overwrite-skill NAME for each, --overwrite-skill ALL, or --skill to "
              "install only the ones you want." % (len(bad_skills), ", ".join(bad_skills)))
        print("\nrefusing to apply with %d failed gate(s)." % R.fail)
        return 1

    receipt = {"schema": "st-transplant/1", "at": stamp(), "checkpoint": ckpt,
               "session_id": sid, "dest_session_id": dest_sid, "origin_key": okey,
               "dest_root": dest_root, "dest_key": dest_key, "skills": [],
               "claude_home": claude_home}

    # =================================================================== 1. project
    print("")
    print("[1/8] project tree")
    if a.no_project_tree:
        R.info("skipped (--no-project-tree)")
    elif not os.path.isdir(src_project):
        R.warn_("no project/ in the checkpoint; skipping")
    else:
        try:
            os.makedirs(dest_root)
        except OSError as e:
            if e.errno != errno.EEXIST:
                R.bad("cannot create %s: %s" % (dest_root, e))
        # The key must be recomputed once the directory exists: resolve_dest() gave the
        # right answer for a not-yet-existing path, and this asserts it.
        after = resolve_dest(dest_root)
        if mangle(after) != dest_key:
            R.bad("the project key CHANGED once the destination existed: %s -> %s. The CLI "
                  "computes realpath itself and would look under the second one. Halting "
                  "before the transcript is placed." % (dest_key, mangle(after)))
            return 1
        R.ok("project key re-asserted after mkdir: %s" % dest_key)
        extra_rs = list(git_exclude)
        if clobber:
            bdir = os.path.join(dest_root, ".st-overwritten", stamp())
            extra_rs += ["--backup", "--backup-dir=" + bdir]
            R.warn_("%d differing file(s) will be replaced; their current bytes are backed "
                    "up under %s" % (len(clobber), bdir))
        if rsync(src_project + "/", dest_root + "/", extra_rs):
            n = count_files(dest_root)
            R.ok("%d files under %s" % (n, dest_root))
            if git_exclude:
                R.ok("the destination's .git was not touched")

    # =============================================================== 2. transcript
    print("")
    print("[2/8] transcript (byte-verbatim)")
    src_sha = sha256(src_tx)
    if resume_state == "already-placed":
        R.ok("already placed; prefix verified above; not re-copied")
        prefix_len = src_size
    else:
        try:
            os.makedirs(dest_dir)
        except OSError as e:
            if e.errno != errno.EEXIST:
                R.bad("cannot create %s: %s" % (dest_dir, e))
        if displace_to:
            os.chmod(dest_tx, 0o600)
            os.rename(dest_tx, displace_to)
            R.ok("displaced the previous file to %s (kept, not deleted)"
                 % os.path.basename(displace_to))
        shutil.copy2(src_tx, dest_tx)
        os.chmod(dest_tx, 0o600)             # copy2 carries the sealed a-w mode over — M6
        if sha256(dest_tx) == src_sha:
            R.ok("byte-identical: %s" % src_sha)
        else:
            R.bad("copy is NOT byte-identical — aborting before any append")
            return 1
        prefix_len = src_size

    # ========================================================== 3. append, never edit
    print("")
    print("[3/8] relocation notice (APPEND ONLY)")
    moves = build_moves(oroot, dest_root,
                        os.path.dirname(oclaude) if oclaude else "",
                        os.path.expanduser("~"),
                        oclaude, claude_home)
    if contains_after(dest_tx, NOTICE_TAG, prefix_len):
        R.ok("a relocation notice is already present after the original bytes — not "
             "appending a second (scanned from byte %d to EOF, not a fixed tail window)"
             % prefix_len)
    else:
        parent = last_uuid(dest_tx)
        if not parent:
            R.warn_("no uuid found in the last 400 records; the notice will be a new root")
        rec = {
            "parentUuid": parent,
            "isSidechain": False,
            "type": "user",
            "message": {"role": "user",
                        "content": [{"type": "text",
                                     "text": notice_text(moves, origin_desc, dest_desc, extra)}]},
            "uuid": str(uuid.uuid4()),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
            "origin": {"kind": "system"},
            "userType": "external",
            "cwd": dest_root,
            "sessionId": dest_sid,
            "version": a.cli_version or "0.0.0",
            "gitBranch": "",
        }
        if not a.cli_version:
            R.warn_("no --cli-version given; the appended record is stamped version 0.0.0. "
                    "st-preflight.sh prints the destination CLI's real version.")
        with open(dest_tx, "a") as f:
            # JSON.stringify-equivalent: compact separators, non-ASCII kept verbatim
            f.write(json.dumps(rec, separators=(",", ":"), ensure_ascii=False) + "\n")
        R.ok("notice appended as one `user` record")

    if not a.no_relocated_record:
        if tail_contains(dest_tx, '"type":"relocated"'):
            R.ok("a `relocated` record is already inside the 64 KiB tail window")
        else:
            in_sid = in_record_session_id(dest_tx) or dest_sid
            if in_sid != dest_sid:
                R.info("in-record sessionId (%s) differs from the filename (%s); the "
                       "`relocated` record must carry the IN-RECORD one" % (in_sid, dest_sid))
            with open(dest_tx, "a") as f:
                f.write(json.dumps({"type": "relocated", "sessionId": in_sid,
                                    "relocatedCwd": dest_root},
                                   separators=(",", ":")) + "\n")
            R.ok("`relocated` record appended (honoured only by the in-REPL /resume — free insurance)")
        size_now = os.path.getsize(dest_tx)
        off = size_now - TAIL_WINDOW
        if not tail_contains(dest_tx, '"type":"relocated"'):
            R.bad("the `relocated` record is not inside the last 64 KiB — its reverse scan will miss it")
        else:
            R.ok("`relocated` record lies within the last 64 KiB (scan window starts at byte %d)"
                 % max(0, off))

    if sha256(dest_tx, limit=prefix_len) == src_sha:
        R.ok("prefix still byte-identical over all %d original bytes" % prefix_len)
    else:
        R.bad("PREFIX CHANGED — history was modified. Halt and restore from the checkpoint.")

    # ================================================== 4. sidecars, memory, tasks
    print("")
    print("[4/8] sidecars, memory, tasks, sibling workflow scripts")

    def cmp_count(label, s, d):
        """`nd < ns` is the failure. `nd > ns` is a session that has been USED — new
        subagents, new tasks. Asserting equality made every post-launch run red, and a
        gate that fails on the normal case is a gate operators learn to ignore."""
        ns, nd = count_files(s), count_files(d)
        if nd == ns:
            R.ok("%-13s %d files" % (label, nd))
        elif nd > ns:
            R.ok("%-13s %d files (checkpoint %d; +%d created since — expected on a used session)"
                 % (label, nd, ns, nd - ns))
        else:
            R.bad("%-13s destination %d < checkpoint %d — something from the checkpoint is missing"
                  % (label, nd, ns))

    if os.path.isdir(src_side):
        if rsync(src_side + "/", os.path.join(dest_dir, dest_sid) + "/"):
            for sub in ("subagents", "tool-results", "workflows"):
                s = os.path.join(src_side, sub)
                d = os.path.join(dest_dir, dest_sid, sub)
                if os.path.isdir(s):
                    cmp_count(sub, s, d)
            if a.new_session_id:
                R.ok("sidecar directory installed under the NEW stem %s — the .jsonl and its "
                     "sidecar root were renamed in the same operation" % dest_sid)
    else:
        R.info("no sidecar directory in the checkpoint (normal for a short session)")
    if a.no_memory:
        R.info("memory/: not installed (--no-memory)")
    elif os.path.isdir(src_mem):
        if rsync(src_mem + "/", os.path.join(dest_dir, "memory") + "/"):
            cmp_count("memory", src_mem, os.path.join(dest_dir, "memory"))
    else:
        R.info("no memory/ in the checkpoint (normal for a short session; when present it is "
               "the highest-value-per-byte artifact)")
    if os.path.isdir(src_tasks):
        dst_tasks = os.path.join(claude_home, "tasks", dest_sid)
        try:
            os.makedirs(os.path.dirname(dst_tasks))
        except OSError as e:
            if e.errno != errno.EEXIST:
                R.bad(str(e))
        if rsync(src_tasks + "/", dst_tasks + "/"):
            cmp_count("tasks", src_tasks, dst_tasks)
    else:
        R.info("no tasks/<sid> in the checkpoint")

    # Sibling keys hold ONLY <sid>/workflows/scripts, created when the session's cwd moved.
    # They were backed up but never installed on the run that worked (open issue O1).
    for skey in siblings:
        s = os.path.join(ckpt, "claude", "projects", skey, sid)
        if not os.path.isdir(s):
            continue
        rel = None
        if oroot:
            # find the subdirectory whose ORIGIN path mangles to this sibling key
            for base, dirs, _ in os.walk(dest_root):
                cand = os.path.relpath(base, dest_root)
                cand = "" if cand == "." else cand
                depth = 0 if not cand else cand.count(os.sep) + 1
                # sibling keys come from cwd changes inside the project; 6 levels is ample
                dirs[:] = [] if depth >= 6 else [d for d in dirs if not d.startswith(".")]
                if mangle(os.path.join(oroot, cand) if cand else oroot) == skey:
                    rel = cand
                    break
        if rel is None:
            R.warn_("sibling key %s: could not locate the matching destination "
                    "subdirectory; its %d workflow script(s) are NOT installed"
                    % (skey, count_files(s)))
            continue
        target_cwd = resolve_dest(os.path.join(dest_root, rel)) if rel else dest_root
        tkey = mangle(target_cwd)
        tdir = os.path.join(claude_home, "projects", tkey, dest_sid)
        try:
            os.makedirs(tdir)
        except OSError as e:
            if e.errno != errno.EEXIST:
                R.bad(str(e))
        if rsync(s + "/", tdir + "/"):
            R.ok("sibling %s -> %s (%d files, cwd %s)" % (skey, tkey, count_files(tdir), target_cwd))
        smem = os.path.join(ckpt, "claude", "projects", skey, "memory")
        if os.path.isdir(smem) and not a.no_memory:
            if rsync(smem + "/", os.path.join(claude_home, "projects", tkey, "memory") + "/"):
                R.ok("sibling %s memory/ installed (%d files)"
                     % (skey, count_files(os.path.join(claude_home, "projects", tkey, "memory"))))

    # ========================================================= 5. durable CLAUDE.md
    print("")
    print("[5/8] durable CLAUDE.md (the half of the message that survives compaction)")
    counts = "(%d project files, %d sidecar files, %d memory files)" % (
        count_files(dest_root), count_files(os.path.join(dest_dir, dest_sid)),
        count_files(os.path.join(dest_dir, "memory")))
    block = claude_md_block(dest_sid, moves, origin_desc, dest_desc, ckpt, counts, extra)
    cmd_path = os.path.join(dest_root, "CLAUDE.md")
    mb, me = mark_begin(dest_sid), mark_end(dest_sid)
    if os.path.isfile(cmd_path):
        cur = open(cmd_path).read()
        if mb in cur and me in cur:
            new = re.sub(re.escape(mb) + r".*?" + re.escape(me), lambda _m: block, cur, flags=re.S)
            R.ok("replaced this session's block in CLAUDE.md (other sessions' blocks kept)")
        else:
            new = block + "\n\n" + cur
            R.ok("prepended this session's block to the existing CLAUDE.md (kept intact)")
    else:
        new = block + "\n"
        R.ok("created %s" % cmd_path)
    atomic_write(cmd_path, new, 0o644)

    # ====================================================== 6. shared assets (M4)
    print("")
    print("[6/8] shared assets — INSTALLED at the destination, not merely backed up (M4)")
    if a.no_skills:
        R.info("skills skipped (--no-skills)")
    elif os.path.isdir(src_skills):
        names = a.skill or sorted(n for n in os.listdir(src_skills)
                                  if os.path.isdir(os.path.join(src_skills, n)))
        for n in names:
            s = os.path.join(src_skills, n)
            d = os.path.join(claude_home, "skills", n)
            if not os.path.isdir(s):
                R.warn_("skill %s is not in the checkpoint" % n)
                continue
            try:
                os.makedirs(os.path.dirname(d))
            except OSError as e:
                if e.errno != errno.EEXIST:
                    R.bad(str(e))
            if os.path.isdir(d):
                bak = d + ".st-bak-" + stamp()
                shutil.copytree(d, bak)
                R.warn_("existing skill %s backed up to %s before replacement"
                        % (n, os.path.basename(bak)))
            if rsync(s + "/", d + "/"):
                ns, nd = count_files(s), count_files(d)
                if nd >= ns:
                    receipt["skills"].append(n)
                    R.ok("skill %-34s installed: %d files at %s" % (n, nd, d))
                else:
                    R.bad("skill %s: checkpoint %d files, destination %d" % (n, ns, nd))
    else:
        R.info("no skills/ in the checkpoint")

    for adir in ("agents", "commands", "output-styles"):
        s = os.path.join(ckpt, "claude", adir)
        if not os.path.isdir(s):
            continue
        d = os.path.join(claude_home, adir)
        if rsync(s + "/", d + "/"):
            R.ok("%-13s installed: %d files at %s" % (adir, count_files(d), d))
    ucm = os.path.join(ckpt, "claude", "CLAUDE.md")
    if os.path.isfile(ucm):
        R.warn_("the checkpoint carries the origin's HOST-WIDE ~/.claude/CLAUDE.md. It is NOT "
                "installed automatically: it applies to every project on this host and it "
                "usually names the origin's absolute paths. Review and merge it by hand: %s"
                % ucm)

    if a.settings_key is None:
        a.settings_key = ["skipWorkflowUsageWarning", "enabledPlugins"]
    if a.no_settings:
        if os.path.isfile(src_settings):
            R.info("settings.json: nothing merged (--no-settings)")
    elif os.path.isfile(src_settings):
        try:
            osettings = json.load(open(src_settings))
        except Exception as e:                                     # noqa: BLE001
            osettings = {}
            R.warn_("origin settings.json unreadable: %s" % e)
        dpath = os.path.join(claude_home, "settings.json")
        try:
            dsettings = json.load(open(dpath)) if os.path.isfile(dpath) else {}
        except Exception:                                          # noqa: BLE001
            dsettings = {}
            R.warn_("destination settings.json unreadable — not overwriting it")
        merged = 0
        for k in a.settings_key:
            if k in osettings and dsettings.get(k) != osettings[k]:
                dsettings[k] = osettings[k]
                merged += 1
        skipped = [k for k in osettings if k not in a.settings_key]
        if merged:
            atomic_write(dpath, json.dumps(dsettings, indent=2) + "\n", 0o600)
            R.ok("settings.json: merged %d key(s) %s (nothing else was touched)"
                 % (merged, a.settings_key))
        else:
            R.ok("settings.json: nothing to merge")
        if skipped:
            R.warn_("origin settings.json keys NOT merged: %s. If the session depended on "
                    "any of them (hooks, permissions, env), copy it deliberately."
                    % ", ".join(sorted(skipped)[:12]))

    if os.path.isdir(src_plugins):
        pl = sorted(os.listdir(src_plugins))
        R.warn_("plugins are NOT installed by copy: they carry absolute installPath and "
                "per-architecture binaries. Reinstall from the marketplace. Present in the "
                "checkpoint: %s" % ", ".join(pl[:8]))
    R.info("skills are enumerated at CLI process STARTUP and cached for the process "
           "lifetime — install them before launching, not after")

    try:
        atomic_write(os.path.join(dest_root, RECEIPT),
                     json.dumps(receipt, indent=2, sort_keys=True) + "\n", 0o644)
        R.ok("receipt written: %s (st-verify.sh reads it so a deliberately partial install "
             "is not reported as a failure)" % os.path.join(dest_root, RECEIPT))
    except OSError as e:
        R.warn_("could not write the receipt: %s" % e)

    # ================================================== 7. Desktop session JSON
    print("")
    print("[7/8] Desktop session")
    rehome = find_rehome()
    if not a.user_data_dir or (not rehome and not (a.account and a.org)):
        R.info("skipped: " + ("--user-data-dir not given." if not a.user_data_dir else
                              "without claude-desktop-rehome, --account and --org are both required."))
        R.info("CLI-direct resume is complete on its own:  cd %s && claude --resume=%s"
               % (dest_root, dest_sid))
    elif desktop_blocked:
        # --force permits steps 1-6. It must NEVER permit this one: dropping a session
        # JSON into a running instance's store is precisely what the debounced writer
        # overwrites or deletes.
        R.bad("REFUSING to mint the Desktop session while that instance is running. "
              "--force does not cover this step. Stop the instance and re-run: everything "
              "else is already in place and this script is idempotent.")
    elif rehome:
        # claude-desktop-rehome owns Desktop-record knowledge: account/org resolution (incl. Desktop's transitional
        # log lines), validation and drift, archive + rollback, idempotency. One implementation, not two.
        if a.record_file:
            rec_path = a.record_file
        else:
            now = int(time.time() * 1000)
            body = {"sessionId": "local_%s" % uuid.uuid4(), "cliSessionId": dest_sid, "cwd": dest_root,
                    "originCwd": dest_root, "createdAt": now, "lastActivityAt": now, "lastFocusedAt": now,
                    "effort": a.effort, "isArchived": False,
                    "title": a.title or ("migrated session %s" % dest_sid[:8]), "titleSource": "custom",
                    "permissionMode": a.permission_mode}
            if a.model:
                body["model"] = a.model
            fd, rec_path = tempfile.mkstemp(prefix="st-record-", suffix=".json")   # never litter the project
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"format": "ccd-record/1", "tool": "st-transplant", "record": body}, f)
        cmd = [sys.executable, "-I", rehome, "adopt", a.user_data_dir, "--record", rec_path, "--cwd", dest_root,
               "--cli-session-id", dest_sid]
        cmd += (["--to", a.account] if a.account else []) + (["--to-org", a.org] if a.org else [])
        cmd += (["--title", a.title] if a.title else [])
        pr = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if not a.record_file:
            os.remove(rec_path)
        for line in pr.stdout.decode("utf-8", "replace").splitlines():
            print("         " + line)
        if pr.returncode == 0:
            R.ok("Desktop record adopted by claude-desktop-rehome (%s)" % rehome)
        else:
            R.bad("claude-desktop-rehome refused to adopt the record (see above); nothing was written there")
    else:
        R.warn_("claude-desktop-rehome not found: writing a MINIMAL Desktop record (settings such as permissions "
                "and grants are lost, no archive/undo). Install it next to this skill for full records.")
        sess_dir = os.path.join(a.user_data_dir, "claude-code-sessions", a.account, a.org)
        try:
            makedirs_mode(sess_dir, 0o700)
        except OSError as e:
            R.bad("cannot create %s: %s" % (sess_dir, e))
        existing = None
        for fn in sorted(os.listdir(sess_dir)):
            if not (fn.startswith("local_") and fn.endswith(".json")):
                continue
            try:
                d = json.load(open(os.path.join(sess_dir, fn)))
            except Exception:                                      # noqa: BLE001
                continue
            if d.get("cliSessionId") == dest_sid:
                existing = fn
                break
        if existing:
            R.ok("a Desktop session for this transcript already exists: %s (not minting a "
                 "second — a duplicate sessionId is silently dropped on load)" % existing)
        else:
            local_id = "local_%s" % uuid.uuid4()
            now = int(time.time() * 1000)
            # Writer key order, and only keys the reader actually consumes. Unknown keys
            # are ignored on read and erased on the next save, so extras are pointless.
            meta = [
                ("sessionId", local_id),
                ("cliSessionId", dest_sid),
                ("cwd", dest_root),
                ("originCwd", dest_root),
                ("createdAt", now),
                ("lastActivityAt", now),
                ("lastFocusedAt", now),
            ]
            # Model availability is account- and plan-scoped. Hardcoding one produced a
            # session the destination account could not start, and the failure looked like
            # a transplant failure. Omit the key unless the operator names one.
            if a.model:
                meta.append(("model", a.model))
            meta += [
                ("effort", a.effort),
                ("isArchived", False),
                ("title", a.title or ("migrated session %s" % dest_sid[:8])),
                ("titleSource", "custom"),
                ("permissionMode", a.permission_mode),
                ("remoteMcpServersConfig", []),
                ("alwaysAllowedReasons", []),
                ("sessionPermissionUpdates", []),
                ("classifierSummaryEnabled", True),
                ("spawnSeed", {}),
            ]
            obj = {}
            for k, v in meta:
                obj[k] = v
            # the filename MUST equal the sessionId field: a mismatch loads under the field
            # value and then rewrites, leaving a permanent ghost file that reloads forever
            path = os.path.join(sess_dir, local_id + ".json")
            body = json.dumps(obj)
            if len(body) > (10 << 20):
                R.bad("session JSON exceeds the 10 MiB load limit")
            else:
                atomic_write(path, body, 0o600)
                R.ok("minted %s" % path)
                R.ok("  sessionId == filename stem, mode 0600, dirs 0700, %d bytes" % len(body))
                if not a.model:
                    R.info("  no `model` key written — the app picks one the destination "
                           "account actually has")
        R.info("there is no file watcher: the Desktop only loads this directory at startup / "
               "account or org change. Start that instance AFTER this script, never during.")
        R.info("never use claude://resume or the Recover-CLI-sessions UI on this session: "
               "both strip thinking blocks IN PLACE on the live transcript.")

    # =========================================================== 8. workspace trust
    print("")
    print("[8/8] workspace trust")
    if not a.trust:
        R.info("not touching the CLI's global config (default). The Desktop/CLI will show "
               "its trust dialog once for %s; accepting it there is the safe path." % dest_root)
        R.info("  --trust writes projects['<dest root>'].hasTrustDialogAccepted = true.")
    else:
        # The global config lives BESIDE the claude home, not necessarily at ~/.claude.json:
        # CLAUDE_CONFIG_DIR relocates it (measured — an isolated rig grows its own
        # cfg/.claude.json and the real one keeps its mtime). Writing the hardcoded path in
        # a non-default layout put the key in a file nothing reads.
        cj = os.path.join(os.path.dirname(os.path.normpath(claude_home)), ".claude.json")
        if os.path.normpath(claude_home) == os.path.normpath(os.path.expanduser("~/.claude")):
            cj = os.path.expanduser("~/.claude.json")
        others = instance_running(None)
        if others:
            R.bad("%d claude/electron process(es) are running on this host. %s is host-wide "
                  "and every one of them can flush its own full-file copy over ours. "
                  "Refusing --trust; accept the dialog in the app instead."
                  % (len(others), cj))
            for h in others[:4]:
                print("         %s" % h)
        elif not os.path.isfile(cj):
            R.warn_("no %s — the app will show its trust dialog on first open" % cj)
        else:
            try:
                d = json.load(open(cj))
                projects = d.setdefault("projects", {})
                entry = projects.setdefault(dest_root, {})
                if entry.get("hasTrustDialogAccepted") is True:
                    R.ok("trust already recorded for %s" % dest_root)
                else:
                    bak = cj + ".st-bak-" + stamp()
                    shutil.copy2(cj, bak)
                    entry["hasTrustDialogAccepted"] = True
                    # indent=2: json.dumps(d) collapsed a 40 KB config to one line and
                    # normalised key order, reformatting the user's file wholesale.
                    atomic_write(cj, json.dumps(d, indent=2) + "\n", 0o600)
                    R.ok("added projects['%s'].hasTrustDialogAccepted = true (backup: %s)"
                         % (dest_root, os.path.basename(bak)))
                    R.info("that is the ONLY key this script writes there; the file itself is "
                           "never copied between hosts — it carries machineID and account identity")
            except Exception as e:                                 # noqa: BLE001
                R.bad("could not update %s: %s" % (cj, e))

    # ---- summary -----------------------------------------------------------------
    print("")
    print("=" * 74)
    if R.fail:
        print("TRANSPLANT INCOMPLETE — %d failed check(s), %d warning(s)" % (R.fail, R.warn))
    else:
        print("TRANSPLANT OK — 0 failed checks, %d warning(s)" % R.warn)
    print("=" * 74)
    print("  verify:  st-verify.sh --dest-root %s --session-id %s --checkpoint %s"
          % (dest_root, dest_sid, ckpt))
    print("  CLI:     cd %s && claude --resume=%s" % (dest_root, dest_sid))
    if a.user_data_dir:
        print("  Desktop: start the instance that uses --user-data-dir=%s the way you"
              % a.user_data_dir)
        print("           normally start it (the launcher's name is platform- and")
        print("           install-specific and is NOT something this skill can assume).")
    return 1 if R.fail else 0


if __name__ == "__main__":
    sys.exit(main())
