#!/usr/bin/env python3
"""st_origin_probe.py — one-shot READ-ONLY recon of a Claude Code session on the origin.

Executed over ssh stdin so that nothing is ever written to the origin:

    ssh HOST "python3 - --session-id SID --project-root R --claude-home C" < st_origin_probe.py

Emits a single JSON object on stdout. Diagnostics go to stderr. Stdlib only, 3.6+.

DISCOVERY MODE — you almost never know the session id up front:

    ssh HOST "python3 - --list-sessions" < st_origin_probe.py

lists every transcript under `<claude-home>/projects/*/`, newest first, with its project
key, session id, size, mtime and the opening words of the first user message, so a human
can recognise the conversation they mean. `--session-id` is not required in that mode.

It NEVER opens .credentials.json, ~/.claude.json, or anything else on the NEVER-COPY list
— it reports existence and size only, so the operator can see what is being left behind.
"""
import argparse
import io
import json
import os
import platform
import re
import shutil
import stat as statmod
import subprocess
import sys
import unicodedata

NEVER_COPY = [
    ".credentials.json", "history.jsonl", "backups", "telemetry", "sessions",
    "shell-snapshots", "session-env", "cache", "stats-cache.json",
    "policy-limits.json", ".last-cleanup", "file-history", "paste-cache", "downloads",
]

# Startup-enumerated asset classes that live beside skills/ and are just as shared. They
# are neither copied by default nor on the NEVER-COPY list, so they must at least be
# VISIBLE — an unclassified directory is how "backed up is not installed" happens one
# step earlier: never inventoried at all.
SHARED_ASSET_DIRS = ["skills", "agents", "commands", "output-styles", "plugins", "hooks"]

VERSION_RE = re.compile(r'"version"\s*:\s*"([^"]{1,32})"')


def dir_size(path, cap_files=None):
    files = 0
    total = 0
    for base, dirs, names in os.walk(path, followlinks=False):
        dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(base, d))]
        for n in names:
            p = os.path.join(base, n)
            try:
                st = os.lstat(p)
            except OSError:
                continue
            if not statmod.S_ISREG(st.st_mode):
                continue
            files += 1
            total += st.st_size
            if cap_files and files >= cap_files:
                return files, total, True
    return files, total, False


def which(cmd):
    try:
        return shutil.which(cmd)
    except Exception:                                            # noqa: BLE001
        return None


def run(argv):
    try:
        p = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        out, _ = p.communicate()
        return out.decode("utf-8", "replace").strip()
    except Exception as e:                                       # noqa: BLE001
        return "ERR: %s" % e


def free_space(path):
    """os.statvfs does not exist on Windows, and AttributeError is not OSError — the
    unguarded call crashed the whole probe there rather than degrading."""
    if not hasattr(os, "statvfs"):
        return None
    try:
        st = os.statvfs(path)
    except OSError:
        return None
    return {"free_bytes": st.f_bavail * st.f_frsize,
            "total_bytes": st.f_blocks * st.f_frsize}


# Opening words the CLI writes itself; they say nothing about which conversation this is.
BOILERPLATE = ("This session is being continued from a previous conversation",)


def first_user_text(path, limit=160):
    """Opening words of the first real user message — the only thing that lets a human
    recognise which conversation a uuid belongs to."""
    try:
        with io.open(path, "r", encoding="utf-8", errors="replace") as fh:
            for _ in range(400):
                line = fh.readline()
                if not line:
                    break
                try:
                    d = json.loads(line)
                except Exception:                                # noqa: BLE001
                    continue
                if d.get("type") != "user":
                    continue
                msg = d.get("message") or {}
                c = msg.get("content")
                txt = ""
                if isinstance(c, str):
                    txt = c
                elif isinstance(c, list):
                    for blk in c:
                        if isinstance(blk, dict) and blk.get("type") == "text":
                            txt = blk.get("text") or ""
                            break
                txt = " ".join((txt or "").split())
                if txt and not txt.startswith("<") and not txt.startswith(BOILERPLATE):
                    return txt[:limit]
    except (IOError, OSError):
        pass
    return ""


def transcript_hints(path, head_lines=400, tail_bytes=262144):
    """The working folder and the title of a transcript, from its first lines and its last 256 KiB only (never the
    whole file). The folder is the NEWEST record's `cwd`: a transplanted transcript's first records still name the
    origin machine's folder. The title is the last `custom-title`, else the last `summary`."""
    cwd, last_cwd, titles, summaries = None, [None], [], []

    def take(d):
        if isinstance(d.get("cwd"), str):
            last_cwd[0] = d["cwd"]
        if d.get("type") == "custom-title" and d.get("customTitle"):
            titles.append(str(d["customTitle"]))
        elif d.get("type") == "summary" and d.get("summary"):
            summaries.append(str(d["summary"]))
    try:
        with io.open(path, "r", encoding="utf-8", errors="replace") as fh:
            for _ in range(head_lines):
                line = fh.readline()
                if not line:
                    break
                try:
                    d = json.loads(line)
                except Exception:                                # noqa: BLE001
                    continue
                if not isinstance(d, dict):
                    continue
                if cwd is None and isinstance(d.get("cwd"), str):
                    cwd = d["cwd"]
                take(d)
        size = os.path.getsize(path)
        if size > tail_bytes:
            with io.open(path, "rb") as fh:
                fh.seek(size - tail_bytes)
                tail = fh.read().split(b"\n")[1:]               # the first piece is a partial line
            for raw in tail:
                if b'"custom-title"' in raw or b'"summary"' in raw or b'"cwd"' in raw:
                    try:
                        d = json.loads(raw.decode("utf-8", "replace"))
                    except Exception:                            # noqa: BLE001
                        continue
                    if isinstance(d, dict):
                        take(d)
    except (IOError, OSError):
        pass
    title = (titles or summaries or [None])[-1]
    return {"cwd": last_cwd[0] or cwd, "title": " ".join(title.split())[:120] if title else None}


def scan_transcript(path, deep, sample_lines):
    """Stream the transcript. Never load it whole (tripwire 10)."""
    info = {"path": path, "exists": os.path.exists(path)}
    if not info["exists"]:
        return info
    info["size"] = os.path.getsize(path)
    st = os.lstat(path)
    info["mtime"] = int(st.st_mtime)
    info["mode"] = "%o" % statmod.S_IMODE(st.st_mode)
    versions = {}
    lines = 0
    last_byte = None
    last_line = b""
    session_ids = {}
    with io.open(path, "rb") as fh:
        if deep:
            for raw in fh:
                lines += 1
                last_line = raw
                s = raw.decode("utf-8", "replace")
                m = VERSION_RE.search(s)
                if m:
                    versions[m.group(1)] = versions.get(m.group(1), 0) + 1
                if lines <= sample_lines:
                    j = s.find('"sessionId":"')
                    if j >= 0:
                        sid = s[j + 13:s.find('"', j + 13)]
                        session_ids[sid] = session_ids.get(sid, 0) + 1
        else:
            for raw in fh:
                lines += 1
                last_line = raw
                if lines <= sample_lines:
                    s = raw.decode("utf-8", "replace")
                    m = VERSION_RE.search(s)
                    if m:
                        versions[m.group(1)] = versions.get(m.group(1), 0) + 1
                    j = s.find('"sessionId":"')
                    if j >= 0:
                        sid = s[j + 13:s.find('"', j + 13)]
                        session_ids[sid] = session_ids.get(sid, 0) + 1
        if info["size"]:
            fh.seek(-1, os.SEEK_END)
            last_byte = fh.read(1)
    info["lines"] = lines
    info["deep_scan"] = bool(deep)
    info["writer_versions"] = versions
    info["in_record_session_ids"] = session_ids
    info["ends_with_lf"] = (last_byte == b"\n")
    try:
        json.loads(last_line.decode("utf-8", "replace"))
        info["last_line_parses"] = True
    except Exception:                                            # noqa: BLE001
        info["last_line_parses"] = False
    return info


def fold(name):
    """APFS folds case AND Unicode normalisation. Folding on .lower() alone reports 0
    collisions for exactly the NFC/NFD pair that merges."""
    return unicodedata.normalize("NFC", name).casefold()


def hazards(root, limit=200):
    nfd = []
    nonascii = []
    by_dir = {}
    collisions = []
    big = []
    special = []
    for base, dirs, names in os.walk(root, followlinks=False):
        m = by_dir.setdefault(base, {})
        for n in list(dirs) + list(names):
            if unicodedata.normalize("NFC", n) != n and len(nfd) < limit:
                nfd.append(os.path.join(base, n))
            try:
                n.encode("ascii")
            except UnicodeEncodeError:
                if len(nonascii) < limit:
                    nonascii.append(os.path.join(base, n))
            m.setdefault(fold(n), []).append(n)
        for n in names:
            p = os.path.join(base, n)
            try:
                st = os.lstat(p)
            except OSError:
                continue
            if statmod.S_ISREG(st.st_mode):
                if st.st_size > (4 << 30) and len(big) < limit:
                    big.append([p, st.st_size])
            elif not statmod.S_ISLNK(st.st_mode) and len(special) < limit:
                special.append(p)
    for base, m in by_dir.items():
        for _, names in m.items():
            if len(set(names)) > 1 and len(collisions) < limit:
                collisions.append([os.path.join(base, x) for x in sorted(set(names))])
    return {"nfd": nfd, "non_ascii": nonascii, "case_collisions": collisions,
            "over_4gib": big, "special_files": special}


def list_sessions(claude_home, limit):
    """Every transcript under projects/*/ — the discovery path. Without it the operator
    has to guess a uuid out of a directory whose name the mangler makes unguessable."""
    pdir = os.path.join(claude_home, "projects")
    rows = []
    if not os.path.isdir(pdir):
        return rows
    for key in sorted(os.listdir(pdir)):
        kdir = os.path.join(pdir, key)
        if not os.path.isdir(kdir):
            continue
        try:
            names = sorted(os.listdir(kdir))
        except OSError:
            continue
        for n in names:
            if not n.endswith(".jsonl"):
                continue
            p = os.path.join(kdir, n)
            try:
                st = os.lstat(p)
            except OSError:
                continue
            if not statmod.S_ISREG(st.st_mode):
                continue
            sid = n[:-6]
            side = os.path.join(kdir, sid)
            rows.append({
                "project_key": key,
                "session_id": sid,
                "bytes": st.st_size,
                "mtime": int(st.st_mtime),
                "has_sidecar_dir": os.path.isdir(side),
                "sidecar_files": dir_size(side)[0] if os.path.isdir(side) else 0,
                "has_tasks": os.path.isdir(os.path.join(claude_home, "tasks", sid)),
                "first_user_message": first_user_text(p),
            })
            rows[-1].update(transcript_hints(p))
    rows.sort(key=lambda r: -r["mtime"])
    return rows[:limit] if limit else rows


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


def main():
    sys.argv[1:] = dashsafe(sys.argv[1:], ("--origin-key",))
    ap = argparse.ArgumentParser()
    ap.add_argument("--session-id", default="")
    ap.add_argument("--project-root", default="")
    ap.add_argument("--claude-home", default="")
    ap.add_argument("--origin-key", default="",
                    help="use THIS literal project key rather than the alphabetically first")
    ap.add_argument("--list-sessions", action="store_true",
                    help="discovery mode: enumerate every transcript, newest first")
    ap.add_argument("--list-limit", type=int, default=40)
    ap.add_argument("--deep", action="store_true",
                    help="full streaming scan of the transcript (slower, exact version census)")
    ap.add_argument("--sample-lines", type=int, default=5000)
    ap.add_argument("--hazard-scan", action="store_true")
    a = ap.parse_args()

    home = os.path.expanduser("~")
    claude = a.claude_home or os.path.join(home, ".claude")

    if a.list_sessions:
        out = {
            "schema": "st_origin_probe/2",
            "mode": "list-sessions",
            "host": platform.node(),
            "home": home,
            "claude_home": claude,
            "claude_home_exists": os.path.isdir(claude),
            "sessions": list_sessions(claude, a.list_limit),
        }
        json.dump(out, sys.stdout, indent=1, sort_keys=True)
        sys.stdout.write("\n")
        return 0

    if not a.session_id:
        sys.stderr.write("st_origin_probe: --session-id is required "
                         "(or use --list-sessions to find one)\n")
        return 2

    sid = a.session_id
    proot = a.project_root
    out = {
        "schema": "st_origin_probe/2",
        "mode": "session",
        "host": platform.node(),
        "uname": " ".join(platform.uname()),
        "python": platform.python_version(),
        "home": home,
        "claude_home": claude,
        "project_root": proot,
        "project_root_given": bool(proot),
        "project_root_real": os.path.realpath(proot) if proot and os.path.exists(proot) else None,
        "session_id": sid,
    }

    # ---- tools -----------------------------------------------------------------
    out["tools"] = {}
    for t in ("rsync", "shasum", "sha256sum", "openssl", "timeout", "zstd", "git",
              "python3", "perl"):
        out["tools"][t] = which(t)
    if out["tools"].get("rsync"):
        out["rsync_version"] = run(["rsync", "--version"]).splitlines()[:1]

    # ---- free space ------------------------------------------------------------
    out["disk"] = {}
    for label, path in (("project_root", proot), ("claude_home", claude), ("home", home)):
        out["disk"][label] = free_space(path) if path else None

    # ---- is anything running that could append? --------------------------------
    ps = run(["ps", "-eo", "pid,comm,args"])
    running = []
    for line in ps.splitlines()[1:]:
        f = line.split(None, 2)
        if len(f) >= 3 and "claude" in f[1].lower():
            running.append(line.strip()[:200])
    out["claude_processes"] = running

    # ---- project dirs: the LITERAL observed keys (never derived — F24) ---------
    pdir = os.path.join(claude, "projects")
    keys_with_transcript = []
    keys_with_sidecar = []
    all_keys = []
    if os.path.isdir(pdir):
        for name in sorted(os.listdir(pdir)):
            full = os.path.join(pdir, name)
            if not os.path.isdir(full):
                continue
            all_keys.append(name)
            if os.path.isfile(os.path.join(full, sid + ".jsonl")):
                keys_with_transcript.append(name)
            if os.path.isdir(os.path.join(full, sid)):
                keys_with_sidecar.append(name)
    out["project_keys_total"] = len(all_keys)
    out["keys_with_transcript"] = keys_with_transcript
    out["keys_with_sidecar"] = keys_with_sidecar

    # Per-candidate detail so a >1-key situation can be RESOLVED rather than guessed at.
    # A session that ran under git worktrees legitimately has transcript content under
    # more than one key; picking the alphabetically first one silently drops the rest.
    cand = {}
    for k in keys_with_transcript:
        p = os.path.join(pdir, k, sid + ".jsonl")
        try:
            st = os.lstat(p)
        except OSError:
            continue
        cand[k] = {"path": p, "bytes": st.st_size, "mtime": int(st.st_mtime),
                   "first_user_message": first_user_text(p),
                   "has_sidecar_dir": os.path.isdir(os.path.join(pdir, k, sid))}
    out["transcript_candidates"] = cand

    # ---- the transcript --------------------------------------------------------
    primary = None
    if a.origin_key:
        if a.origin_key in keys_with_transcript:
            primary = a.origin_key
        else:
            out["origin_key_error"] = ("--origin-key %s holds no %s.jsonl"
                                       % (a.origin_key, sid))
    if primary is None and keys_with_transcript:
        primary = max(keys_with_transcript, key=lambda k: cand.get(k, {}).get("bytes", 0))
    out["origin_key"] = primary
    out["origin_key_was_chosen_automatically"] = bool(primary and not a.origin_key
                                                      and len(keys_with_transcript) > 1)
    out["transcript"] = None
    if primary:
        out["transcript"] = scan_transcript(
            os.path.join(pdir, primary, sid + ".jsonl"), a.deep, a.sample_lines)

    # ---- inventory by category -------------------------------------------------
    inv = {}

    def add(cat, path):
        if os.path.isdir(path):
            f, b, _ = dir_size(path)
            inv[cat] = {"path": path, "files": f, "bytes": b}
        elif os.path.isfile(path):
            inv[cat] = {"path": path, "files": 1, "bytes": os.path.getsize(path)}
        else:
            inv[cat] = {"path": path, "files": 0, "bytes": 0, "missing": True}

    if primary:
        base = os.path.join(pdir, primary)
        if out["transcript"] and out["transcript"].get("exists"):
            inv["transcript"] = {"path": out["transcript"]["path"], "files": 1,
                                 "bytes": out["transcript"]["size"]}
        side = os.path.join(base, sid)
        add("sidecar_total", side)
        add("sidecar_subagents", os.path.join(side, "subagents"))
        add("sidecar_subagents_workflows", os.path.join(side, "subagents", "workflows"))
        add("sidecar_tool_results", os.path.join(side, "tool-results"))
        add("sidecar_workflows", os.path.join(side, "workflows"))
        add("sidecar_workflow_scripts", os.path.join(side, "workflows", "scripts"))
        add("memory", os.path.join(base, "memory"))
    add("tasks", os.path.join(claude, "tasks", sid))
    add("settings_json", os.path.join(claude, "settings.json"))
    add("user_memory", os.path.join(claude, "CLAUDE.md"))
    sib = {}
    for k in keys_with_sidecar:
        if k == primary:
            continue
        p = os.path.join(pdir, k, sid)
        f, b, _ = dir_size(p)
        sib[k] = {"path": p, "files": f, "bytes": b,
                  "has_memory": os.path.isdir(os.path.join(pdir, k, "memory")),
                  "has_transcript": os.path.isfile(os.path.join(pdir, k, sid + ".jsonl"))}
    inv["sibling_keys"] = sib

    # shared assets, per NAME, so the operator can whitelist individually (guard O6)
    assets = {}
    for adir in SHARED_ASSET_DIRS:
        root = os.path.join(claude, adir)
        entry = {}
        if os.path.isdir(root):
            for name in sorted(os.listdir(root)):
                p = os.path.join(root, name)
                if os.path.isdir(p):
                    f, b, _ = dir_size(p)
                    entry[name] = {"files": f, "bytes": b}
                elif os.path.isfile(p):
                    entry[name] = {"files": 1, "bytes": os.path.getsize(p)}
        assets[adir] = entry
    inv["shared_assets"] = assets
    inv["skills"] = assets.get("skills", {})           # kept for backwards compatibility
    add("plugins", os.path.join(claude, "plugins"))
    out["inventory"] = inv

    # ---- project tree ----------------------------------------------------------
    if proot and os.path.isdir(proot):
        f, b, capped = dir_size(proot, cap_files=400000)
        out["project_tree"] = {"files": f, "bytes": b, "capped": capped}
        gits = []
        for base, dirs, _ in os.walk(proot, followlinks=False):
            if ".git" in dirs:
                gits.append(os.path.relpath(base, proot))
                # do not descend into .git
            dirs[:] = [d for d in dirs if d != ".git"]
        out["git_repos"] = gits
    else:
        out["project_tree"] = None
        out["git_repos"] = []

    # ---- NEVER-COPY inventory: existence and size ONLY, contents never read ----
    left = {}
    for n in NEVER_COPY:
        p = os.path.join(claude, n)
        if os.path.exists(p):
            if os.path.isdir(p):
                f, b, _ = dir_size(p)
                left[n] = {"kind": "dir", "files": f, "bytes": b}
            else:
                left[n] = {"kind": "file", "bytes": os.path.getsize(p)}
    p = os.path.join(home, ".claude.json")
    if os.path.exists(p):
        left["~/.claude.json"] = {"kind": "file", "bytes": os.path.getsize(p)}
    out["never_copy_present"] = left

    if a.hazard_scan and proot and os.path.isdir(proot):
        out["hazards"] = hazards(proot)

    json.dump(out, sys.stdout, indent=1, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
