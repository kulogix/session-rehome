#!/usr/bin/env python3
"""Self-test for session-transporter's bundle path and the st-transplant.py / st-verify.sh fixes.

Builds two synthetic machines in a temp dir (an ORIGIN home with a session, sidecars, memory, tasks, a sibling
key, decoy credentials and secret-looking project files; a DESTINATION home with a Desktop profile) and checks
every promise. Touches nothing outside the temp dir. Needs session-rehome next to this skill (or
$ST_REHOME) for the Desktop-record checks.      python3 -I selftest.py      exit 0 = all pass
"""
import datetime, glob, hashlib, json, os, shutil, sqlite3, subprocess, sys, tempfile, zipfile

sys.dont_write_bytecode = True
for _s in (sys.stdout, sys.stderr):          # -I ignores PYTHONIOENCODING; a Windows pipe would be cp1252
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from mangle import mangle  # noqa: E402

BUNDLE = os.path.join(HERE, "st-bundle.py")
TRANSPLANT = os.path.join(HERE, "st-transplant.py")
VERIFY = os.path.join(HERE, "st-verify.sh")
REHOME = os.environ.get("ST_REHOME") or os.path.join(os.path.dirname(os.path.dirname(HERE)),
                                                     "session-rehome", "scripts", "ccd-rehome")
SID = "11111111-2222-4333-8444-555555555555"
A, OA = "aaaaaaaa-1111-4111-8111-111111111111", "0a0a0a0a-1111-4111-8111-111111111111"
B, OB = "bbbbbbbb-2222-4222-8222-222222222222", "0b0b0b0b-2222-4222-8222-222222222222"
fails, LAST = [], [""]


def check(cond, msg):
    print(("  PASS " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)
        if os.environ.get("SELFTEST_VERBOSE"):
            print("\n".join("    | " + l for l in LAST[0].strip().splitlines()[-40:]))


def run(cmd, home, env=None, inp=None):
    e = dict(os.environ, HOME=home, USERPROFILE=home, CCD_REHOME_HOME=home, CCD_REHOME_SANDBOX="1",
             ST_REHOME=REHOME, PYTHONIOENCODING="utf-8", **(env or {}))
    e.pop("CLAUDE_CONFIG_DIR", None); e.pop("CCD_REHOME_STATE", None)
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", env=e, input=inp)
    LAST[0] = f"$ {' '.join(cmd[2:] if cmd[0] == sys.executable else cmd)}  (rc {r.returncode})\n" + r.stdout + r.stderr
    return r.returncode, r.stdout + r.stderr


def py(script, *args, home, env=None):
    return run([sys.executable, "-I", script, *args], home, env)


def tree_hash(d):
    h = hashlib.sha256()
    for base, dirs, files in os.walk(d):
        dirs.sort()
        for f in sorted(files):
            p = os.path.join(base, f)
            h.update(os.path.relpath(p, d).encode())
            if os.path.isfile(p):
                h.update(open(p, "rb").read())
    return h.hexdigest()


def bash_works():
    """True only if `bash` really runs here. On Windows, PATH can find the WSL launcher, which runs nothing without
    a WSL distribution installed."""
    if not shutil.which("bash"):
        return False
    try:
        r = subprocess.run(["bash", "-c", "echo ok"], capture_output=True, text=True, timeout=60)
        return r.stdout.strip() == "ok"
    except (OSError, subprocess.SubprocessError):
        return False


BASH_OK = bash_works()
WIN = sys.platform.startswith("win")


def no_bash(what):
    """Bash is part of the POSIX path (a missing bash there is a failure); on Windows the .sh tools run under WSL
    or Git Bash, so say plainly that their checks did not run."""
    if WIN:
        print(f"  (skipped {what}: bash cannot run here; on Windows the .sh tools run under WSL or Git Bash)")
    else:
        check(False, f"bash is needed for {what}")


def sha(p, n=None):
    b = open(p, "rb").read()
    return hashlib.sha256(b if n is None else b[:n]).hexdigest()


def jl(path, recs):
    with open(path, "w", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r) + "\n")


def desktop_profile(home, name, acct, org):
    p = os.path.join(home, ".claude-instances", name)
    os.makedirs(os.path.join(p, "logs"), exist_ok=True)
    json.dump({"lastKnownAccountUuid": acct}, open(os.path.join(p, "config.json"), "w", encoding="utf-8"))
    con = sqlite3.connect(os.path.join(p, "Cookies"))
    con.execute("create table cookies (host_key text, name text, expires_utc integer, encrypted_value blob)")
    exp = datetime.datetime.now() + datetime.timedelta(days=20) - datetime.datetime(1601, 1, 1)
    con.execute("insert into cookies values ('.claude.ai','sessionKey',?,x'00')", (int(exp.total_seconds() * 1e6),))
    con.commit(); con.close()
    open(os.path.join(p, "logs", "main.log"), "w", encoding="utf-8").write(
        f"2026-11-07 10:00:00 [info] [LocalSessionManager] Initialization succeeded — accountId={acct}, orgId={org}, "
        f"existingSessions=0\n")
    os.makedirs(os.path.join(p, "claude-code-sessions", acct, org), exist_ok=True)
    return p


root = os.path.realpath(tempfile.mkdtemp(prefix="st-selftest-"))
try:
    if not os.path.isfile(REHOME):
        print(f"  FAIL session-rehome not found at {REHOME} (install both skills from the "
              f"session-rehome project, or set ST_REHOME)")
        sys.exit(1)
    # ------------------------------------------------------------------ the ORIGIN machine
    HA = os.path.join(root, "origin-home"); proj = os.path.join(HA, "work", "fib project")
    ch = os.path.join(HA, ".claude"); key = mangle(proj)
    pdir = os.path.join(ch, "projects", key)
    os.makedirs(os.path.join(pdir, SID, "subagents")); os.makedirs(os.path.join(pdir, SID, "tool-results"))
    recs = [{"type": "user", "uuid": "u1", "parentUuid": None, "cwd": proj, "version": "2.1.295", "sessionId": SID,
             "message": {"role": "user", "content": "make a fibonacci cli"}},
            {"type": "assistant", "uuid": "a1", "parentUuid": "u1", "cwd": proj, "version": "2.1.295",
             "sessionId": SID, "message": {"role": "assistant", "content": "Café 漢字 🚀 key sk-ant-api03-" + "x" * 30}},
            {"type": "custom-title", "customTitle": "Fibonacci CLI", "sessionId": SID}]
    tx = os.path.join(pdir, SID + ".jsonl"); jl(tx, recs)
    jl(os.path.join(pdir, SID, "subagents", "agent-1.jsonl"), [{"type": "user", "uuid": "s1"}])
    open(os.path.join(pdir, SID, "tool-results", "abc.txt"), "w", encoding="utf-8").write("0 1 1 2 3 5\n")
    os.makedirs(os.path.join(pdir, "memory")); open(os.path.join(pdir, "memory", "note.md"), "w", encoding="utf-8").write("project note\n")
    os.makedirs(os.path.join(ch, "tasks", SID)); open(os.path.join(ch, "tasks", SID, "1.json"), "w", encoding="utf-8").write("{}")
    sib = os.path.join(ch, "projects", key + "-worktree", SID, "workflows"); os.makedirs(sib)
    open(os.path.join(sib, "wf.json"), "w", encoding="utf-8").write("{}")
    other = os.path.join(pdir, "99999999-2222-4333-8444-555555555555.jsonl"); jl(other, [{"type": "user", "uuid": "z"}])
    for decoy in (".credentials.json", "history.jsonl", "settings.json"):
        open(os.path.join(ch, decoy), "w", encoding="utf-8").write('{"decoy": true}')
    open(os.path.join(HA, ".claude.json"), "w", encoding="utf-8").write('{"oauthAccount": {"accountUuid": "%s"}}' % A)
    os.makedirs(os.path.join(proj, "src")); os.makedirs(os.path.join(proj, "build"))
    open(os.path.join(proj, "src", "fib.py"), "w", encoding="utf-8").write("def fib(n):\n    return n\n")
    open(os.path.join(proj, "build", "out.bin"), "w", encoding="utf-8").write("x" * 100)
    open(os.path.join(proj, ".env"), "w", encoding="utf-8").write("TOKEN=secret\n")
    open(os.path.join(proj, "id_rsa"), "w", encoding="utf-8").write("-----BEGIN OPENSSH PRIVATE KEY-----\n")
    pa = desktop_profile(HA, "acct-o", A, OA)
    json.dump({"sessionId": "local_e0e0e0e0-0000-4000-8000-000000000001", "cliSessionId": SID, "cwd": proj,
               "originCwd": proj, "title": "Fibonacci CLI", "effort": "max", "permissionMode": "auto",
               "model": "claude-opus-5-5", "sessionSettings": {"ultracode": True}, "lastActivityAt": 5,
               "createdAt": 1, "remoteMcpServersConfig": [{"x": 1}], "planPath": "/old/plan.md",
               "shellFolders": [proj]},
              open(os.path.join(pa, "claude-code-sessions", A, OA, "local_e0e0e0e0-0000-4000-8000-000000000001.json"),
                   "w", encoding="utf-8"))
    out = os.path.join(root, "fib.csb.zip")
    EX = ["--exclude", "/build/  # build output, regenerated"]

    print("list (finding the session id)")
    h0 = tree_hash(HA)
    rc, o = py(BUNDLE, "list", "--claude-home", ch, home=HA)
    check(rc == 0 and SID in o and "fib project" in o and "Fibonacci CLI" in o and "make a fibonacci cli" in o,
          "list shows each session's full id, folder, title and opening words")
    rc, o = py(BUNDLE, "list", "--claude-home", ch, "--json", home=HA)
    rows = json.loads(o).get("sessions", []) if rc == 0 else []
    mine = [r for r in rows if r.get("session_id") == SID]
    check({r.get("session_id") for r in rows} == {SID, "99999999-2222-4333-8444-555555555555"} and mine
          and mine[0].get("cwd") == proj and mine[0].get("title") == "Fibonacci CLI" and tree_hash(HA) == h0,
          "list --json: every transcript, with cwd and title; it writes nothing")

    print("export")
    rc, o = py(BUNDLE, "export", "--session-id", SID, "--claude-home", ch, *EX, "--desktop-profile", "acct-o",
               "-o", out, "--dry-run", home=HA)
    check(rc == 0 and tree_hash(HA) == h0 and not os.path.exists(out), "export --dry-run writes nothing")
    rc, o = py(BUNDLE, "export", "--session-id", SID, "--claude-home", ch, "--exclude", "build/  # x", "-o", out, home=HA)
    check(rc != 0 and "unanchored" in o, "an unanchored exclude is refused")
    rc, o = py(BUNDLE, "export", "--session-id", SID, "--claude-home", ch, "--exclude", "/build/", "-o", out, home=HA)
    check(rc != 0 and "justification" in o, "an exclude without a justification is refused")
    rc, o = py(BUNDLE, "export", "--session-id", SID, "--claude-home", ch, *EX, "--desktop-profile", "acct-o",
               "-o", out, home=HA)
    check(rc == 0 and os.path.isfile(out), "export writes the bundle")
    z = zipfile.ZipFile(out); names = set(z.namelist()); man = json.loads(z.read("manifest.json"))
    must = {f"payload/claude/projects/{key}/{SID}.jsonl", f"payload/claude/projects/{key}/{SID}/subagents/agent-1.jsonl",
            f"payload/claude/projects/{key}/{SID}/tool-results/abc.txt", f"payload/claude/projects/{key}/memory/note.md",
            f"payload/claude/tasks/{SID}/1.json", f"payload/claude/projects/{key}-worktree/{SID}/workflows/wf.json",
            "payload/project/src/fib.py", "record/record.json", "manifest.json"}
    check(must <= names, "bundle holds transcript, sidecars, memory, tasks, sibling key, project, record")
    check(not any(x in n for n in names for x in (".credentials.json", "history.jsonl", "settings.json", ".claude.json",
                                                  "99999999", "/build/", ".env", "id_rsa")),
          "no credentials, history, settings, other sessions, excluded or secret-looking files")
    check(sorted(man["sensitive_left_out"]) == [".env", "id_rsa"] and man["excludes"][0]["files"] == 1,
          "secret-looking project files listed as left out; exclude accounted with a count")
    check(man["transcript_secret_hits"].get("anthropic_key") == 1, "a key inside the transcript is counted and reported")
    rr = json.loads(z.read("record/record.json"))["record"]
    check(rr["cliSessionId"] == SID and "remoteMcpServersConfig" not in rr and rr["effort"] == "max",
          "the Desktop record travels as a ccd-record/1 (account-bound fields stripped, settings kept)")
    check(not any(x in json.dumps(json.loads(z.read("record/record.json"))) for x in (A, OA)), "the record carries no account ids")
    z.close()
    out_nm = os.path.join(root, "fib-nomem.csb.zip")
    py(BUNDLE, "export", "--session-id", SID, "--claude-home", ch, *EX, "--no-memory", "--no-record", "-o", out_nm, home=HA)
    nn = zipfile.ZipFile(out_nm).namelist()
    check(not any("/memory/" in n for n in nn) and json.loads(zipfile.ZipFile(out_nm).read("manifest.json"))["no_memory"],
          "--no-memory leaves every memory/ out")
    torn = os.path.join(root, "torn"); shutil.copytree(HA, torn, symlinks=True)
    ttx = os.path.join(torn, ".claude", "projects", key, SID + ".jsonl")
    with open(ttx, "a", encoding="utf-8") as f:
        f.write('{"type": "user", "partial')                                   # a write in progress
    full = os.path.getsize(tx)
    rc, o = py(BUNDLE, "export", "--session-id", SID, "--claude-home", os.path.join(torn, ".claude"), "--no-project",
               "--no-record", "-o", os.path.join(root, "torn.zip"), home=torn)
    tm = json.loads(zipfile.ZipFile(os.path.join(root, "torn.zip")).read("manifest.json"))
    check(rc == 0 and tm["transcript"]["prefix_len"] == full, "a half-written last line is not packed (consistent prefix)")

    print("inspect")
    rc, o = py(BUNDLE, "inspect", out, home=HA)
    check(rc == 0 and "VERIFIED" in o, "inspect verifies every member")
    def rewrite(src, dst, fn):
        with zipfile.ZipFile(src) as zi, zipfile.ZipFile(dst, "w") as zo:
            for i in zi.infolist():
                b = fn(i.filename, zi.read(i.filename))
                if b is not None:
                    zo.writestr(i.filename, b)
    bad = os.path.join(root, "bad.zip")
    rewrite(out, bad, lambda n, b: b.replace(b"return n", b"return 0") if n.endswith("fib.py") else b)
    rc, o = py(BUNDLE, "inspect", bad, home=HA)
    check(rc != 0 and "mismatch" in o, "a modified member is caught")
    rewrite(out, bad, lambda n, b: b)
    with zipfile.ZipFile(bad, "a") as zz:
        zz.writestr("../../evil.txt", "x")
    rc, o = py(BUNDLE, "inspect", bad, home=HA)
    check(rc != 0 and "zip-slip" in o, "a path-escaping member (zip-slip) is refused")
    rewrite(out, bad, lambda n, b: b)
    with zipfile.ZipFile(bad, "a") as zz:
        zz.writestr("payload/project/sneaky.sh", "x")
    rc, o = py(BUNDLE, "inspect", bad, home=HA)
    check(rc != 0 and "not in the manifest" in o, "a member the manifest does not list is caught")

    # ------------------------------------------------------------------ the DESTINATION machine
    HB = os.path.join(root, "dest-home"); chb = os.path.join(HB, ".claude"); os.makedirs(chb)
    pb = desktop_profile(HB, "acct-d", B, OB)
    dest = os.path.join(HB, "Projects", "fibonacci")
    print("import")
    h0 = tree_hash(HB)
    rc, o = py(BUNDLE, "import", out, "--dest-root", dest, "--claude-home", chb, "--desktop-profile", pb,
               "--staging", os.path.join(HB, "staging"), "--plan", home=HB)
    check(rc == 0 and tree_hash(HB) == h0, "import --plan writes nothing at the destination")
    rc, o = py(BUNDLE, "import", out, "--dest-root", dest, "--claude-home", chb, "--desktop-profile", pb,
               "--staging", os.path.join(HB, "staging"), "--apply", home=HB)
    check(rc == 0 and "TRANSPLANT OK" in o, "import --apply runs st-transplant.py to completion")
    dk = mangle(dest); dtx = os.path.join(chb, "projects", dk, SID + ".jsonl")
    check(os.path.isfile(dtx) and sha(dtx, man["transcript"]["prefix_len"]) == man["transcript"]["sha256"],
          "transcript under mangle(destination) with the origin bytes as an exact prefix")
    check(os.path.isfile(dtx) and os.path.getsize(dtx) > man["transcript"]["prefix_len"],
          "relocation notice appended (append-only)")
    check(all(os.path.isfile(p) for p in (os.path.join(chb, "projects", dk, SID, "subagents", "agent-1.jsonl"),
                                         os.path.join(chb, "projects", dk, SID, "tool-results", "abc.txt"),
                                         os.path.join(chb, "projects", dk, "memory", "note.md"),
                                         os.path.join(chb, "tasks", SID, "1.json"),
                                         os.path.join(dest, "src", "fib.py"), os.path.join(dest, "CLAUDE.md"))),
          "sidecars, memory, tasks, project files and CLAUDE.md installed")
    check(not os.path.exists(os.path.join(dest, ".env")) and not os.path.exists(os.path.join(chb, "settings.json")),
          "no secret-looking file and no settings.json at the destination")
    placed = glob.glob(os.path.join(pb, "claude-code-sessions", B, OB, "local_*.json"))
    pr = json.load(open(placed[0], encoding="utf-8")) if placed else {}
    check(len(placed) == 1 and pr.get("cliSessionId") == SID and pr.get("cwd") == dest and pr.get("effort") == "max"
          and pr.get("sessionSettings") == {"ultracode": True} and "planPath" not in pr,
          "Desktop record adopted via session-rehome: signed-in account, new cwd, settings kept, host fields dropped")
    rc, o = py(BUNDLE, "import", out, "--dest-root", dest, "--claude-home", chb, "--desktop-profile", pb,
               "--staging", os.path.join(HB, "staging"), "--apply", home=HB)
    check(rc == 0 and len(glob.glob(os.path.join(pb, "claude-code-sessions", B, OB, "local_*.json"))) == 1,
          "re-import is idempotent (no second record)")
    HC = os.path.join(root, "dest2"); chc = os.path.join(HC, ".claude"); os.makedirs(chc)
    dest2 = os.path.join(HC, "fib")
    rc, o = py(BUNDLE, "import", out, "--dest-root", dest2, "--claude-home", chc, "--no-memory",
               "--staging", os.path.join(HC, "staging"), "--apply", home=HC, env={"ST_NO_RSYNC": "1"})
    d2 = os.path.join(chc, "projects", mangle(dest2))
    check(rc == 0 and os.path.isfile(os.path.join(d2, SID, "subagents", "agent-1.jsonl"))
          and os.path.isfile(os.path.join(dest2, "src", "fib.py")) and not os.path.exists(os.path.join(d2, "memory")),
          "without rsync (Windows path, ST_NO_RSYNC=1) the pure-Python copy installs the same; --no-memory honoured")
    check(oct(os.stat(os.path.join(dest2, "src", "fib.py")).st_mode & 0o777) in ("0o644", "0o600", "0o640")
          or sys.platform.startswith("win"), "copied files are writable and not group/world-writable")

    print("legacy CLAUDE.md marker (projects migrated before the rename)")
    HL = os.path.join(root, "dest-legacy"); chl = os.path.join(HL, ".claude"); os.makedirs(chl)
    destl = os.path.join(HL, "fib"); os.makedirs(destl)
    open(os.path.join(destl, "CLAUDE.md"), "w", encoding="utf-8").write(
        f"<!-- BEGIN claude-session-transporter relocation notice: {SID} -->\nold table\n"
        f"<!-- END claude-session-transporter relocation notice: {SID} -->\n\n# user notes\nkeep me\n")
    rc, o = py(BUNDLE, "import", out, "--dest-root", destl, "--claude-home", chl, "--staging",
               os.path.join(HL, "staging"), "--apply", home=HL)
    cm = open(os.path.join(destl, "CLAUDE.md"), encoding="utf-8").read()
    check(rc == 0 and cm.count("relocation notice: " + SID) == 2 and "<!-- BEGIN session-transporter" in cm
          and "claude-session-transporter" not in cm and "old table" not in cm and "keep me" in cm,
          "a block written under the 0.9.x skill name is REPLACED (upgraded), not duplicated; user text kept")
    if not BASH_OK:
        no_bash("the st-verify.sh legacy-marker check")
    else:
        open(os.path.join(destl, "CLAUDE.md"), "w", encoding="utf-8").write(
            f"<!-- BEGIN claude-session-transporter relocation notice: {SID} -->\nold\n"
            f"<!-- END claude-session-transporter relocation notice: {SID} -->\n")
        stl = os.path.join(HL, "staging"); stl = os.path.join(stl, os.listdir(stl)[0])
        rc, o = run(["bash", VERIFY, "--checkpoint", stl, "--dest-root", destl, "--session-id", SID, "--claude-home", chl,
                     "--no-probe", "--no-tree-check"], HL)
        check("CLAUDE.md carries this session's" in o, "st-verify.sh recognises a block written under the 0.9.x skill name")

    print("st-transplant.py settings fix")
    stg = os.path.join(HB, "staging"); stg = os.path.join(stg, os.listdir(stg)[0])
    os.chmod(os.path.join(stg, "claude"), 0o755)
    json.dump({"theme": "dark", "enabledPlugins": {"p": True}, "permissions": {"allow": ["x"]}},
              open(os.path.join(stg, "claude", "settings.json"), "w", encoding="utf-8"))
    HD = os.path.join(root, "dest3"); chd = os.path.join(HD, ".claude"); os.makedirs(chd)
    base = ["--checkpoint", stg, "--claude-home", chd, "--no-skills", "--allow-existing"]
    rc, o = py(TRANSPLANT, "--apply", *base, "--dest-root", os.path.join(HD, "p1"), "--settings-key", "theme", home=HD)
    sd = json.load(open(os.path.join(chd, "settings.json"), encoding="utf-8")) if os.path.isfile(os.path.join(chd, "settings.json")) else {}
    check(rc == 0 and sd == {"theme": "dark"}, "--settings-key REPLACES the defaults (was: always appended to them)")
    os.remove(os.path.join(chd, "settings.json"))
    rc, o = py(TRANSPLANT, "--apply", *base, "--dest-root", os.path.join(HD, "p2"), "--no-settings", home=HD)
    check(rc == 0 and not os.path.exists(os.path.join(chd, "settings.json")), "--no-settings merges nothing")

    print("origin-proof + st-verify.sh --origin-proof")
    proof = os.path.join(root, "proof.json")
    rc, o = py(BUNDLE, "origin-proof", out, "--claude-home", ch, "-o", proof, home=HA)
    check(rc == 0 and "UNCHANGED" in o and json.load(open(proof, encoding="utf-8"))["prefix_sha256"] == man["transcript"]["sha256"],
          "origin-proof on an untouched origin: UNCHANGED")
    staged = os.path.join(HB, "staging")
    vargs = [VERIFY, "--checkpoint", os.path.join(staged, os.listdir(staged)[0]) if os.path.isdir(staged) else staged,
             "--dest-root", dest, "--session-id", SID, "--claude-home", chb, "--no-probe", "--origin-proof", proof]
    if BASH_OK:
        rc, o = run(["bash", *vargs], HB)
        check("origin proof" in o and "identical to the checkpoint" in o and "NOTRUN origin" not in o,
              "st-verify.sh accepts a proof made on the origin (no more NOTRUN when it cannot reach back)")
        check("coverage: every checkpoint file is present at the destination" in o and "NOTRUN destination" not in o,
              "an imported bundle carries the project manifest st-verify.sh checks coverage against")
    with open(tx, "a", encoding="utf-8") as f:
        f.write(json.dumps({"type": "user", "uuid": "later"}) + "\n")
    rc, o = py(BUNDLE, "origin-proof", out, "--claude-home", ch, "-o", proof, home=HA)
    check(rc == 0 and "GROWN" in o, "origin resumed after export: prefix unchanged, reported as a fork")
    b = open(tx, "rb").read(); open(tx, "wb").write(b.replace(b"fibonacci", b"FIBONACCI", 1))
    rc, o = py(BUNDLE, "origin-proof", out, "--claude-home", ch, "-o", proof, home=HA)
    check(rc != 0 and "CHANGED" in o, "history edited on the origin: CHANGED")
    if BASH_OK:
        rc, o = run(["bash", *vargs], HB)
        check("CHANGED" in o and "something wrote to the origin" in o, "st-verify.sh fails on a CHANGED proof")
    else:
        no_bash("the st-verify.sh checks (origin proof, coverage)")

    print("st-checkpoint.sh --no-memory")
    if BASH_OK and shutil.which("rsync"):
        conf = os.path.join(root, "mig.conf")
        open(conf, "w", encoding="utf-8").write(f"ST_ORIGIN_HOST=local\nST_ORIGIN_ROOT='{proj}'\nST_ORIGIN_CLAUDE='{ch}'\n"
                              f"ST_ORIGIN_KEY='{key}'\nST_SESSION_ID={SID}\nST_DEST_ROOT='{dest}'\n"
                              f"ST_CLAUDE_HOME='{chb}'\nST_CKPT_ROOT='{root}/ckpt'\nST_CKPT=$ST_CKPT_ROOT/latest-$ST_SESSION_ID\n")
        rc, o = run(["bash", os.path.join(HERE, "st-checkpoint.sh"), "--profile", conf, "--no-excludes", "--no-memory",
                     "--plan"], HA)
        check("--no-memory: project memory/ is NOT taken" in o and f"projects/{key}/memory" not in o,
              "st-checkpoint.sh --no-memory drops memory/ from the whitelist")
    else:
        print("  (skipped st-checkpoint.sh: needs bash + rsync; not part of the Windows path)")
finally:
    shutil.rmtree(root, ignore_errors=True)
print(f"\n{'ALL PASS' if not fails else str(len(fails)) + ' FAILED'}")
sys.exit(1 if fails else 0)
