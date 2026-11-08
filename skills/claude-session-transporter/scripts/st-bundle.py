#!/usr/bin/env python3
"""st-bundle.py: pack ONE Claude Code session into a single portable, hash-verified file, and install it anywhere.

  st-bundle.py list     [--claude-home DIR] [--limit N] [--json]   every session here: the id to export, its
                        folder, title and opening words, newest first (start here: nobody knows a session id)
  st-bundle.py export   --session-id SID [-o FILE] [--claude-home DIR] [--project-root DIR | --no-project]
                        [--origin-key=KEY] [--no-memory] [--exclude 'PAT  # why' ...] [--exclude-file F]
                        [--include-sensitive] [--desktop-profile P [--record-id ID] | --no-record] [--dry-run]
  st-bundle.py inspect  FILE [--json]                     verify every byte; print what is inside
  st-bundle.py import   FILE --dest-root DIR [--claude-home DIR] [--staging DIR] [--plan | --apply]
                        [--desktop-profile P [--to ACCOUNT] [--to-org ORG]] [--no-memory] [--title T]
                        [--new-session-id UUID] [--trust] [--allow-existing] [--overwrite-destination-work]
                        [--cli-version V]
  st-bundle.py origin-proof FILE [--claude-home DIR] [-o PROOF]   run ON THE ORIGIN: is it still unchanged?

The bundle is a zip (readable by Python's stdlib on every OS) holding exactly what st-checkpoint.sh would take:
the transcript (a byte-exact prefix snapshot), its sidecar dir, tasks/<SID>, the project memory (unless
--no-memory), sibling keys' sidecars, the project tree (minus excludes and secret-looking files), and optionally
the Desktop record as a ccd-record/1 (from claude-desktop-rehome). manifest.json lists every member with its
sha256. `import` verifies all of it, unpacks into the checkpoint layout, and hands over to st-transplant.py,
which does the careful part (mangled key, append-only relocation notice, CLAUDE.md, receipts, record adoption).

Never edits a transcript. Never reads or packs credentials, ~/.claude.json, history, settings, other sessions.
"""
import argparse, datetime, glob, hashlib, io, json, os, platform, re, shutil, subprocess, sys, tempfile, unicodedata
import zipfile

VERSION = "0.9.1"
FORMAT = "claude-session-bundle/1"
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from mangle import mangle  # noqa: E402  (canonical mangler shipped with this skill)

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
# Project files that look like credentials are left out unless --include-sensitive (they would ride inside a file
# that is meant to be copied around). The transcript itself cannot be edited: secrets in it are COUNTED, reported.
SENSITIVE_NAMES = re.compile(r"(^\.env(\..*)?$|\.pem$|\.key$|\.p12$|\.pfx$|\.kdbx$|^id_(rsa|dsa|ecdsa|ed25519)(\.pub)?$|"
                             r"^\.netrc$|^\.credentials\.json$|^credentials.*\.json$|^\.pypirc$|^\.npmrc$)", re.I)
SECRET_PATTERNS = {"anthropic_key": rb"sk-ant-[A-Za-z0-9_-]{20,}", "github_token": rb"gh[opsu]_[A-Za-z0-9]{30,}",
                   "aws_key_id": rb"AKIA[0-9A-Z]{16}", "private_key": rb"-----BEGIN [A-Z ]*PRIVATE KEY-----",
                   "slack_token": rb"xox[baprs]-[A-Za-z0-9-]{10,}"}
WIN_BAD = re.compile(r'[<>:"|?*\x00-\x1f]|[ .]$')
WIN_RESERVED = re.compile(r"^(con|prn|aux|nul|com[1-9]|lpt[1-9])(\..*)?$", re.I)


def say(m=""): print(m, flush=True)


def human_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0


def tilde(path):
    home = os.path.expanduser("~")
    return "~" + path[len(home):] if path and (path == home or path.startswith(home + os.sep)) else path


def list_sessions(a):
    """Every transcript in this machine's Claude home, newest first: what a human needs to say "that one"."""
    import st_origin_probe as probe          # the same lister st-preflight.sh ships over ssh
    ch = os.path.abspath(os.path.expanduser(a.claude_home))
    rows = probe.list_sessions(ch, a.limit)
    if a.json:
        print(json.dumps({"claude_home": ch, "sessions": rows}, indent=2, ensure_ascii=False))
        return
    if not rows:
        say(f"no sessions found under {tilde(os.path.join(ch, 'projects'))}")
        return
    say(f"sessions in {tilde(ch)}, newest first. Pass the id to: st-bundle.py export --session-id ID")
    for r in rows:
        when = datetime.datetime.fromtimestamp(r["mtime"]).strftime("%Y-%m-%d %H:%M")
        where = tilde(r.get("cwd")) if r.get("cwd") else f"(folder unknown; key {r['project_key']})"
        if r.get("cwd") and mangle(r["cwd"]) != r["project_key"]:
            where += f"   [filed under {r['project_key']}: resume it from the folder that key names]"
        say(f"  {r['session_id']}  {when}  {human_size(r['bytes']):>9}  {where}")
        hint = []
        if r.get("title"):
            hint.append(f"title: {r['title']}")
        if r.get("first_user_message"):
            hint.append('"' + r["first_user_message"][:100] + '"')
        if hint:
            say("      " + "   ".join(hint))
def die(m): sys.exit(f"st-bundle: {m}")
def now(): return datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def sha256_file(path, limit=None):
    h, left = hashlib.sha256(), limit
    with open(path, "rb") as f:
        while True:
            b = f.read(1 << 20 if left is None else min(1 << 20, left))
            if not b:
                break
            h.update(b)
            if left is not None:
                left -= len(b)
                if left <= 0:
                    break
    return h.hexdigest()


def safe_arcname(n):
    """Zip-slip guard: relative, forward slashes, no '..', no drive letters."""
    return bool(n) and not n.startswith(("/", "\\")) and "\\" not in n and ":" not in n.split("/")[0] \
        and ".." not in n.split("/")


def profile_path(spec):
    if not spec:
        return None
    if spec == "default":
        if sys.platform == "darwin":
            return os.path.expanduser("~/Library/Application Support/Claude")
        if sys.platform.startswith("win"):
            return os.path.join(os.environ.get("APPDATA", os.path.expanduser("~/AppData/Roaming")), "Claude")
        return os.path.expanduser("~/.config/Claude")
    if os.sep in spec or "/" in spec or spec.startswith(("~", ".")):
        return os.path.abspath(os.path.expanduser(spec))
    return os.path.join(os.path.expanduser("~/.claude-instances"), spec)


def find_rehome():
    for c in (os.environ.get("ST_REHOME", ""),
              os.path.join(os.path.dirname(os.path.dirname(HERE)), "claude-desktop-rehome", "scripts", "ccd-rehome"),
              os.path.expanduser("~/.claude/skills/claude-desktop-rehome/scripts/ccd-rehome"),
              shutil.which("ccd-rehome") or ""):
        if c and os.path.isfile(c):
            return c
    return None


def detect_cli_version():
    """The Claude Code version that will resume the session here: PATH / ~/.local/bin, else the newest CLI a Desktop
    profile bundles (<profile>/claude-code/<version>/). Stamped into the appended notice record."""
    cands = [shutil.which("claude") or "", os.path.expanduser("~/.local/bin/claude")]
    for prof in (profile_path("default"), *glob.glob(os.path.expanduser("~/.claude-instances/*"))):
        vs = sorted(glob.glob(os.path.join(prof, "claude-code", "*", "claude*")),
                    key=lambda x: [int(n) if n.isdigit() else 0 for n in re.split(r"[.-]", os.path.basename(os.path.dirname(x)))])
        cands += vs[-1:]
    for c in cands:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            try:
                out = subprocess.run([c, "--version"], capture_output=True, text=True, timeout=20).stdout
                m = re.search(r"(\d+\.\d+\.\d+)", out)
                if m:
                    return m.group(1)
            except (OSError, subprocess.SubprocessError):
                continue
    return None


# ---------------------------------------------------------------- excludes (same rules as st-checkpoint.sh)
def parse_excludes(items, files):
    out = []
    for f in files or []:
        items = list(items or []) + [l for l in open(f, encoding="utf-8").read().splitlines() if l.strip()
                                     and not l.lstrip().startswith("#")]
    for raw in items or []:
        if "#" not in raw:
            die(f"exclude {raw!r} has no justification: write it as 'PATTERN  # why'")
        pat, why = (x.strip() for x in raw.split("#", 1))
        unanchored = pat.startswith("unanchored:")
        pat = pat[len("unanchored:"):] if unanchored else pat
        if not unanchored and not pat.startswith("/"):
            die(f"exclude {pat!r} is unanchored: anchor it at the project root ('/{pat}') or write "
                f"'unanchored:{pat}  # why' (an unanchored pattern matches by NAME anywhere)")
        out.append({"pattern": pat, "why": why, "unanchored": unanchored, "files": 0, "bytes": 0})
    return out


def excluded(rel, is_dir, ex):
    import fnmatch
    for e in ex:
        p = e["pattern"]
        d = p.endswith("/")
        body = p.strip("/")
        if e["unanchored"]:
            parts = rel.split("/")
            if any(fnmatch.fnmatch(x, body) for x in (parts if is_dir or not d else parts[:-1])):
                return e
        else:
            if fnmatch.fnmatch(rel, body) or (rel + "/").startswith(body + "/"):
                return e
    return None


# ---------------------------------------------------------------- export
def transcript_snapshot(path):
    """(length, sha256) of the largest prefix that ends on a complete line: a live transcript may be mid-append."""
    n = os.path.getsize(path)
    with open(path, "rb") as f:
        f.seek(max(0, n - (1 << 20)))
        tail = f.read(n - f.tell())
    if not tail.endswith(b"\n"):
        cut = tail.rfind(b"\n")
        if cut < 0:
            die(f"{path}: no complete line in the last MiB; cannot take a consistent snapshot")
        n -= len(tail) - cut - 1
    return n, sha256_file(path, n)


def scan_transcript(path, n):
    hits, versions, cwds, title = {}, {}, {}, None
    with open(path, "rb") as f:
        left = n
        for line in f:
            if left <= 0:
                break
            line = line[:left]; left -= len(line)
            for k, rx in SECRET_PATTERNS.items():
                c = len(re.findall(rx, line))
                if c:
                    hits[k] = hits.get(k, 0) + c
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if isinstance(d, dict):
                if d.get("version"):
                    versions[d["version"]] = versions.get(d["version"], 0) + 1
                if d.get("cwd"):
                    cwds[d["cwd"]] = cwds.get(d["cwd"], 0) + 1
                if d.get("type") in ("custom-title", "ai-title") and (d.get("customTitle") or d.get("aiTitle")):
                    title = d.get("customTitle") or d.get("aiTitle")
    return hits, versions, cwds, title


def walk_files(root):
    for base, dirs, files in os.walk(root):
        dirs.sort()
        for f in sorted(files):
            yield os.path.join(base, f)


def export(a):
    ch = os.path.abspath(os.path.expanduser(a.claude_home))
    sid = a.session_id
    if not UUID_RE.match(sid or ""):
        die("--session-id must be the transcript's uuid (find it: st-preflight.sh --list-sessions)")
    keys = [os.path.basename(os.path.dirname(t)) for t in glob.glob(os.path.join(ch, "projects", "*", sid + ".jsonl"))]
    if a.origin_key:
        if a.origin_key not in keys:
            die(f"--origin-key {a.origin_key!r} holds no {sid}.jsonl")
        key = a.origin_key
    elif len(keys) != 1:
        die(f"{len(keys)} project keys hold {sid}.jsonl {keys}; pick one with --origin-key=KEY" if keys else
            f"no transcript {sid}.jsonl under {ch}/projects")
    else:
        key = keys[0]
    pdir = os.path.join(ch, "projects", key)
    tx = os.path.join(pdir, sid + ".jsonl")
    L, tsha = transcript_snapshot(tx)
    hits, versions, cwds, title = scan_transcript(tx, L)
    proj = None if a.no_project else (os.path.abspath(os.path.expanduser(a.project_root)) if a.project_root else
                                      (max(cwds, key=cwds.get) if cwds else None))
    if not a.no_project and (not proj or not os.path.isdir(proj)):
        die(f"project root {proj!r} not found; pass --project-root DIR (or --no-project for the session only)")
    siblings = sorted(os.path.basename(os.path.dirname(d)) for d in glob.glob(os.path.join(ch, "projects", "*", sid))
                      if os.path.isdir(d) and os.path.basename(os.path.dirname(d)) != key)

    members = []                                     # (arcname, source path, limit)
    def add_tree(src, arc):
        for f in walk_files(src):
            if os.path.islink(f):
                continue
            members.append((arc + "/" + os.path.relpath(f, src).replace(os.sep, "/"), f, None))
    members.append((f"payload/claude/projects/{key}/{sid}.jsonl", tx, L))
    if os.path.isdir(os.path.join(pdir, sid)):
        add_tree(os.path.join(pdir, sid), f"payload/claude/projects/{key}/{sid}")
    if not a.no_memory and os.path.isdir(os.path.join(pdir, "memory")):
        add_tree(os.path.join(pdir, "memory"), f"payload/claude/projects/{key}/memory")
    for sk in siblings:
        add_tree(os.path.join(ch, "projects", sk, sid), f"payload/claude/projects/{sk}/{sid}")
        if not a.no_memory and os.path.isdir(os.path.join(ch, "projects", sk, "memory")):
            add_tree(os.path.join(ch, "projects", sk, "memory"), f"payload/claude/projects/{sk}/memory")
    if os.path.isdir(os.path.join(ch, "tasks", sid)):
        add_tree(os.path.join(ch, "tasks", sid), f"payload/claude/tasks/{sid}")

    ex = parse_excludes(a.exclude, a.exclude_file)
    sensitive, symlinks = [], []
    if proj:
        for base, dirs, files in os.walk(proj):
            rb = os.path.relpath(base, proj).replace(os.sep, "/")
            rb = "" if rb == "." else rb + "/"
            keep = []
            for d in sorted(dirs):
                e = excluded(rb + d, True, ex)
                if e:
                    n_ = sum(1 for _ in walk_files(os.path.join(base, d)))
                    e["files"] += n_; e["bytes"] += sum(os.path.getsize(x) for x in walk_files(os.path.join(base, d))
                                                        if not os.path.islink(x))
                else:
                    keep.append(d)
            dirs[:] = keep
            for f in sorted(files):
                full, rel = os.path.join(base, f), rb + f
                if os.path.islink(full):
                    symlinks.append(rel); continue
                e = excluded(rel, False, ex)
                if e:
                    e["files"] += 1; e["bytes"] += os.path.getsize(full); continue
                if SENSITIVE_NAMES.search(f) and not a.include_sensitive:
                    sensitive.append(rel); continue
                members.append(("payload/project/" + rel, full, None))

    record = None
    if a.desktop_profile and not a.no_record:
        rh = find_rehome()                 # read-only calls: always --dry-run, so rehome writes no state either
        if not rh:
            die("--desktop-profile needs claude-desktop-rehome (ccd-rehome): install it next to this skill, or pass "
                "--no-record")
        rid = a.record_id
        if not rid:
            pr = subprocess.run([sys.executable, "-I", rh, "sessions", a.desktop_profile, "--json", "--dry-run"],
                                capture_output=True, text=True, encoding="utf-8")
            try:
                rows = json.loads(pr.stdout)["sessions"]
            except (ValueError, KeyError):
                die(f"ccd-rehome sessions failed: {pr.stderr.strip() or pr.stdout.strip()[:300]}")
            cand = [r["id"] for r in rows if r.get("kind") == "code" and r.get("cli") == sid]
            if len(cand) != 1:
                die(f"{len(cand)} Desktop records in {a.desktop_profile} point at {sid}; pass --record-id ID "
                    f"(or --no-record)")
            rid = cand[0]
        pe = subprocess.run([sys.executable, "-I", rh, "export-record", a.desktop_profile, "--only", rid, "--dry-run"],
                            capture_output=True, text=True, encoding="utf-8")
        if pe.returncode != 0:
            die(f"ccd-rehome export-record refused: {pe.stderr.strip() or pe.stdout.strip()}")
        record = json.loads(pe.stdout)
        if record["record"].get("cliSessionId") != sid:
            die(f"record {rid} belongs to conversation {record['record'].get('cliSessionId')}, not {sid}")
        title = record["record"].get("title") or title

    # filename hazards across the member names: NFC+casefold collisions, Windows-invalid names
    seen, hazards = {}, []
    for arc, _, _ in members:
        fold = unicodedata.normalize("NFC", arc).casefold()
        if fold in seen and seen[fold] != arc:
            hazards.append(f"case/normalisation collision: {seen[fold]} <-> {arc}")
        seen[fold] = arc
        for part in arc.split("/"):
            if WIN_BAD.search(part) or WIN_RESERVED.match(part):
                hazards.append(f"not a valid Windows name: {arc}"); break
        if unicodedata.normalize("NFC", arc) != arc:
            hazards.append(f"NFD (not NFC) name: {arc}")

    total = sum(L if lim is not None else os.path.getsize(src) for _, src, lim in members)
    say(f"st-bundle {VERSION} export: session {sid}  {title or ''}")
    say(f"  transcript  {L} bytes (consistent prefix), sha256 {tsha[:16]}…, writer versions "
        f"{', '.join(f'{v} x{n}' for v, n in sorted(versions.items())) or '?'}")
    say(f"  key         {key}" + (f"   siblings: {', '.join(siblings)}" if siblings else ""))
    say(f"  project     {proj or '(not included)'}")
    for e in ex:
        say(f"  exclude     {e['pattern']:30} {e['files']:5} files {e['bytes']:10} B   # {e['why']}")
    for s_ in sensitive:
        say(f"  SENSITIVE   left out: project/{s_}   (pass --include-sensitive to pack it)")
    for s_ in symlinks:
        say(f"  symlink     not packed: project/{s_}")
    if hits:
        say(f"  WARNING     the transcript contains secret-looking strings: {hits}. A transcript cannot be "
            f"edited; whoever receives this bundle can read them. Consider ROTATING those credentials.")
    for h in hazards:
        say(f"  HAZARD      {h}")
    if a.no_memory:
        say("  memory      not included (--no-memory)")
    say(f"  record      {('ccd-record/1 from ' + a.desktop_profile) if record else '(none: CLI-only, or a minimal record at import)'}")
    say(f"  total       {len(members)} files, {total} bytes")
    if a.dry_run:
        say("dry run: nothing was written"); return

    out = os.path.abspath(a.output or f"session-{sid[:8]}-{now()}.csb.zip")
    tmp = out + ".partial"
    man = {"format": FORMAT, "tool": f"st-bundle {VERSION}", "created_utc": now(),
           "session": {"id": sid, "title": title},
           "origin": {"os": platform.system(), "arch": platform.machine().lower(), "claude_home": ch,
                      "project_root": proj, "key": key, "siblings": siblings,
                      "cli_versions": versions, "desktop": (record or {}).get("desktop")},
           "transcript": {"path": f"payload/claude/projects/{key}/{sid}.jsonl", "prefix_len": L, "sha256": tsha},
           "excludes": ex, "sensitive_left_out": sensitive, "symlinks_left_out": symlinks,
           "transcript_secret_hits": hits, "hazards": hazards, "no_memory": bool(a.no_memory),
           "record": "record/record.json" if record else None, "members": []}
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as z:
        for arc, src, lim in members:
            h = hashlib.sha256(); size = 0
            with open(src, "rb") as f, z.open(zipfile.ZipInfo(arc, datetime.datetime.fromtimestamp(
                    os.path.getmtime(src)).timetuple()[:6]), "w", force_zip64=True) as w:
                left = lim
                while True:
                    b = f.read(1 << 20 if left is None else min(1 << 20, left))
                    if not b:
                        break
                    h.update(b); w.write(b); size += len(b)
                    if left is not None:
                        left -= len(b)
                        if left <= 0:
                            break
            if arc == man["transcript"]["path"] and h.hexdigest() != tsha:
                os.remove(tmp)
                die("the transcript changed while it was being packed (prefix hash moved); nothing was written")
            man["members"].append({"path": arc, "size": size, "sha256": h.hexdigest()})
        if record:
            body = json.dumps(record, indent=2, ensure_ascii=False).encode("utf-8")
            z.writestr("record/record.json", body)
            man["members"].append({"path": "record/record.json", "size": len(body),
                                   "sha256": hashlib.sha256(body).hexdigest()})
        z.writestr("manifest.json", json.dumps(man, indent=2, ensure_ascii=False))
    os.replace(tmp, out)
    os.chmod(out, 0o600)
    say(f"wrote {out}  ({os.path.getsize(out)} bytes)")
    say("next: copy it to the other machine (any way you like), then there:")
    say(f"  python3 st-bundle.py inspect {os.path.basename(out)}")
    say(f"  python3 st-bundle.py import {os.path.basename(out)} --dest-root <DIR> --plan     (then --apply)")
    say(f"later, back HERE, to prove the origin was not touched:  python3 st-bundle.py origin-proof {os.path.basename(out)}")


# ---------------------------------------------------------------- inspect
def verify_bundle(path):
    """(manifest, problems). Every member listed AND present AND hash-identical; nothing extra; no unsafe names."""
    problems = []
    try:
        z = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as e:
        return None, [f"not a readable zip: {e}"]
    with z:
        names = z.namelist()
        bad = [n for n in names if not safe_arcname(n)]
        if bad:
            return None, [f"unsafe member path(s) (zip-slip): {bad[:3]}"]
        if "manifest.json" not in names:
            return None, ["no manifest.json"]
        man = json.loads(z.read("manifest.json"))
        if man.get("format") != FORMAT:
            return man, [f"format {man.get('format')!r} is not {FORMAT}"]
        listed = {m["path"]: m for m in man.get("members", [])}
        extra = set(names) - set(listed) - {"manifest.json"}
        missing = set(listed) - set(names)
        if extra:
            problems.append(f"{len(extra)} member(s) not in the manifest: {sorted(extra)[:3]}")
        if missing:
            problems.append(f"{len(missing)} member(s) missing: {sorted(missing)[:3]}")
        for n, m in listed.items():
            if n in missing:
                continue
            h, size = hashlib.sha256(), 0
            with z.open(n) as f:
                for b in iter(lambda: f.read(1 << 20), b""):
                    h.update(b); size += len(b)
            if h.hexdigest() != m["sha256"] or size != m["size"]:
                problems.append(f"hash/size mismatch: {n}")
        t = man.get("transcript", {})
        if listed.get(t.get("path"), {}).get("sha256") != t.get("sha256"):
            problems.append("transcript hash does not match the manifest's transcript record")
    return man, problems


def inspect(a):
    man, problems = verify_bundle(a.file)
    if a.json:
        print(json.dumps({"ok": not problems, "problems": problems, "manifest": man}, indent=2, ensure_ascii=False))
        sys.exit(0 if not problems else 1)
    if man and man.get("format") == FORMAT:
        o, t = man["origin"], man["transcript"]
        say(f"{os.path.basename(a.file)}: {FORMAT}, made {man['created_utc']} by {man['tool']}")
        say(f"  session    {man['session']['id']}  {man['session'].get('title') or ''}")
        say(f"  origin     {o['os']} {o['arch']}, project {o['project_root']}, key {o['key']}")
        say(f"  transcript {t['prefix_len']} bytes, sha256 {t['sha256'][:16]}…  CLI {', '.join(o.get('cli_versions') or {})}")
        say(f"  members    {len(man['members'])}, {sum(m['size'] for m in man['members'])} bytes"
            + ("; memory NOT included" if man.get("no_memory") else ""))
        say(f"  record     {man.get('record') or '(none)'}")
        for h in man.get("hazards", []):
            say(f"  HAZARD     {h}")
        if man.get("transcript_secret_hits"):
            say(f"  WARNING    secret-looking strings in the transcript: {man['transcript_secret_hits']}")
    for p in problems:
        say(f"  FAIL       {p}")
    say("  VERIFIED: every member present and byte-identical" if not problems else "  NOT VERIFIED: do not import")
    sys.exit(0 if not problems else 1)


# ---------------------------------------------------------------- import
def case_insensitive(path):
    q = path
    while not os.path.isdir(q):
        q = os.path.dirname(q)
    fd, probe = tempfile.mkstemp(prefix=".stCaseProbe", dir=q)
    os.close(fd)
    try:
        return os.path.exists(os.path.join(q, os.path.basename(probe).lower()))
    finally:
        os.remove(probe)


def do_import(a):
    man, problems = verify_bundle(a.file)
    if problems:
        die("the bundle did not verify; nothing was written:\n  " + "\n  ".join(problems))
    sid, key, o = man["session"]["id"], man["origin"]["key"], man["origin"]
    collisions = [h for h in man.get("hazards", []) if h.startswith("case/normalisation")]
    if collisions and a.apply and case_insensitive(os.path.abspath(os.path.expanduser(a.dest_root))):
        die("the destination filesystem is case-insensitive and the bundle has name collisions that would MERGE "
            "files:\n  " + "\n  ".join(collisions))
    if any(h.startswith("not a valid Windows name") for h in man.get("hazards", [])) and sys.platform.startswith("win"):
        die("the bundle has names Windows cannot store: " + "; ".join(man["hazards"][:3]))
    claude_home = os.path.abspath(os.path.expanduser(a.claude_home))
    base = a.staging or os.path.join(os.path.expanduser("~"), ".local", "share", "st-bundles")
    staging = os.path.join(base, f"{sid}-{man['created_utc']}") if a.apply else tempfile.mkdtemp(prefix="st-bundle-plan-")
    if a.apply and os.path.isdir(staging) and os.path.isfile(os.path.join(staging, "COMPLETE")):
        say(f"  staging {staging} already unpacked and verified (re-run)")
    else:
        os.makedirs(staging, mode=0o700, exist_ok=True)
        with zipfile.ZipFile(a.file) as z:
            for m in man["members"]:
                n = m["path"]
                rel = n[len("payload/"):] if n.startswith("payload/") else n
                dst = os.path.join(staging, *rel.split("/"))
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                with z.open(n) as f, open(dst, "wb") as w:
                    shutil.copyfileobj(f, w, 1 << 20)
                if sha256_file(dst) != m["sha256"]:
                    die(f"unpacked {n} does not match its hash; staging left at {staging} for inspection")
        with open(os.path.join(staging, "PROVENANCE"), "w", encoding="utf-8") as f:
            f.write(f"session_id={sid}\norigin_host=bundle\norigin_root={o.get('project_root') or ''}\n"
                    f"origin_claude={o.get('claude_home') or ''}\norigin_key={key}\n"
                    f"sibling_keys={' '.join(o.get('siblings') or [])}\nextra_transcript_keys=\n"
                    f"taken_at={man['created_utc']}\nbundle={os.path.abspath(a.file)}\n")
        os.makedirs(os.path.join(staging, "manifest"), exist_ok=True)
        t = man["transcript"]
        with open(os.path.join(staging, "manifest", "transcript-sha256.txt"), "w") as f:
            f.write(f"{t['sha256']}  claude/projects/{key}/{sid}.jsonl\n")
        with open(os.path.join(staging, "manifest", "transcript-prefix-len.txt"), "w") as f:
            f.write(f"{t['prefix_len']}\n")
        with open(os.path.join(staging, "manifest", "local-project.tsv"), "w", encoding="utf-8") as f:
            f.write("# rel\tsize\tsha256\n")             # what st-verify.sh checks destination coverage against
            for m in sorted(man["members"], key=lambda m: m["path"]):
                if m["path"].startswith("payload/project/"):
                    f.write(f"{m['path'][len('payload/project/'):]}\t{m['size']}\t{m['sha256']}\n")
        with open(os.path.join(staging, "manifest", "bundle-manifest.json"), "w", encoding="utf-8") as f:
            json.dump(man, f, indent=2, ensure_ascii=False)
        open(os.path.join(staging, "COMPLETE"), "w").close()    # verified above, member by member
    cmd = [sys.executable, "-I", os.path.join(HERE, "st-transplant.py"), "--apply" if a.apply else "--plan",
           "--checkpoint", staging, "--session-id", sid, f"--origin-key={key}",
           "--origin-root", o.get("project_root") or "/", "--origin-claude", o.get("claude_home") or "",
           "--origin-desc", f"{o['os']} {o['arch']} (bundle {os.path.basename(a.file)}, made {man['created_utc']})",
           "--dest-root", a.dest_root, "--claude-home", claude_home, "--no-skills", "--no-settings"]
    if a.no_memory or man.get("no_memory"):
        cmd.append("--no-memory")
    if not os.path.isdir(os.path.join(staging, "project")):
        cmd.append("--no-project-tree")
    if a.desktop_profile:
        cmd += ["--user-data-dir", profile_path(a.desktop_profile)]
        if a.to:
            cmd += ["--account", a.to]
        if a.to_org:
            cmd += ["--org", a.to_org]
        if man.get("record") and os.path.isfile(os.path.join(staging, "record", "record.json")):
            cmd += ["--record-file", os.path.join(staging, "record", "record.json")]
    cliv = a.cli_version or detect_cli_version()
    if cliv and not a.cli_version:
        say(f"  destination Claude Code: {cliv} (detected; override with --cli-version)")
    for flag, val in (("--title", a.title), ("--new-session-id", a.new_session_id), ("--cli-version", cliv)):
        if val:
            cmd += [flag, val]
    for flag, on in (("--trust", a.trust), ("--allow-existing", a.allow_existing),
                     ("--overwrite-destination-work", a.overwrite_destination_work)):
        if on:
            cmd.append(flag)
    say(f"st-bundle {VERSION} import: verified {len(man['members'])} members; handing over to st-transplant.py "
        f"({'APPLY' if a.apply else 'plan'})")
    rc = subprocess.run(cmd).returncode
    if not a.apply:
        shutil.rmtree(staging, ignore_errors=True)
        say("plan only: the temporary unpack was removed; nothing else was written")
    else:
        say(f"\nstaging (= the checkpoint this install came from): {staging}")
        say("verify:  st-verify.sh --checkpoint " + staging + f" --dest-root {a.dest_root} --session-id {sid}"
            + f" --claude-home {claude_home}   [--origin-proof PROOF made on the origin]")
    sys.exit(rc)


# ---------------------------------------------------------------- origin-proof
def origin_proof(a):
    man, problems = verify_bundle(a.file)
    if man is None or man.get("format") != FORMAT:
        die("not a session bundle: " + "; ".join(problems))
    sid, key, t = man["session"]["id"], man["origin"]["key"], man["transcript"]
    ch = os.path.abspath(os.path.expanduser(a.claude_home or man["origin"].get("claude_home") or "~/.claude"))
    tx = os.path.join(ch, "projects", key, sid + ".jsonl")
    found = os.path.isfile(tx)
    size = os.path.getsize(tx) if found else None
    psha = sha256_file(tx, t["prefix_len"]) if found and size >= t["prefix_len"] else None
    proof = {"format": "st-origin-proof/1", "session_id": sid, "prefix_len": t["prefix_len"],
             "prefix_sha256": psha, "size_now": size, "found": found, "created_utc": now(),
             "bundle_created_utc": man["created_utc"]}
    verdict = ("UNCHANGED" if psha == t["sha256"] and size == t["prefix_len"] else
               "UNCHANGED PREFIX, GROWN (resumed here: the histories fork)" if psha == t["sha256"] else
               "NOT FOUND" if not found else "CHANGED")
    out = a.output or f"origin-proof-{sid[:8]}-{proof['created_utc']}.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(proof, f, indent=2)
    say(f"origin {verdict}: {tx}\nproof written: {out}  (give it to st-verify.sh --origin-proof on the destination)")
    sys.exit(0 if psha == t["sha256"] else 1)


def main():
    ap = argparse.ArgumentParser(prog="st-bundle.py", description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=f"st-bundle {VERSION}")
    sub = ap.add_subparsers(dest="cmd", required=True)
    ls = sub.add_parser("list", help="every session on this machine (the id to export), newest first")
    ls.add_argument("--claude-home", default=os.environ.get("CLAUDE_CONFIG_DIR") or "~/.claude")
    ls.add_argument("--limit", type=int, default=30, help="how many (0 = all; default 30)")
    ls.add_argument("--json", action="store_true")
    e = sub.add_parser("export")
    e.add_argument("--session-id", required=True); e.add_argument("-o", "--output")
    e.add_argument("--claude-home", default=os.environ.get("CLAUDE_CONFIG_DIR") or "~/.claude")
    e.add_argument("--origin-key", default=""); e.add_argument("--project-root"); e.add_argument("--no-project", action="store_true")
    e.add_argument("--no-memory", action="store_true"); e.add_argument("--exclude", action="append", default=[])
    e.add_argument("--exclude-file", action="append", default=[]); e.add_argument("--include-sensitive", action="store_true")
    e.add_argument("--desktop-profile"); e.add_argument("--record-id"); e.add_argument("--no-record", action="store_true")
    e.add_argument("--dry-run", action="store_true")
    i = sub.add_parser("inspect"); i.add_argument("file"); i.add_argument("--json", action="store_true")
    m = sub.add_parser("import"); m.add_argument("file"); m.add_argument("--dest-root", required=True)
    m.add_argument("--claude-home", default=os.environ.get("CLAUDE_CONFIG_DIR") or "~/.claude")
    m.add_argument("--staging"); g = m.add_mutually_exclusive_group(required=True)
    g.add_argument("--plan", action="store_true"); g.add_argument("--apply", action="store_true")
    m.add_argument("--desktop-profile"); m.add_argument("--to"); m.add_argument("--to-org")
    m.add_argument("--no-memory", action="store_true"); m.add_argument("--title"); m.add_argument("--new-session-id")
    m.add_argument("--trust", action="store_true"); m.add_argument("--allow-existing", action="store_true")
    m.add_argument("--overwrite-destination-work", action="store_true"); m.add_argument("--cli-version")
    p = sub.add_parser("origin-proof"); p.add_argument("file"); p.add_argument("--claude-home"); p.add_argument("-o", "--output")
    a = ap.parse_args()
    {"list": list_sessions, "export": export, "inspect": inspect, "import": do_import,
     "origin-proof": origin_proof}[a.cmd](a)


if __name__ == "__main__":
    main()
