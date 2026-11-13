#!/usr/bin/env python3
"""Self-test for ccd-rehome. Builds synthetic Desktop profiles in a temp HOME (no real data is read or written)
and checks every rule the tool promises. Run:  python3 -I selftest.py      exit 0 = all pass."""
import datetime, glob, hashlib, json, os, re, shutil, sqlite3, stat, subprocess, sys, tempfile, time
sys.dont_write_bytecode = True       # importing ccd-rehome for unit tests must not litter the skill folder

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, "ccd-rehome")
A, B, C = ("aaaaaaaa-1111-4111-8111-111111111111", "bbbbbbbb-2222-4222-8222-222222222222",
           "cccccccc-3333-4333-8333-333333333333")                     # three accounts
OA, OB, OC = ("0a0a0a0a-1111-4111-8111-111111111111", "0b0b0b0b-2222-4222-8222-222222222222",
              "0c0c0c0c-3333-4333-8333-333333333333")                  # their orgs
EMAIL = {A: "a@example.com", B: "b@example.com", C: "c@example.com"}
fails = []
LAST = [""]


def check(cond, msg):
    print(("  PASS " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)
        if os.environ.get("SELFTEST_VERBOSE"):
            print("    | " + LAST[0].strip().replace("\n", "\n    | ")[-1500:])


def caller_env():
    """The caller's environment minus everything that would point the tool at real data or change what it
    simulates: CLAUDE_CONFIG_DIR (a shell or session started for another account), CCD_REHOME_CLI_HOMES,
    CCD_REHOME_PROFILES, CCD_REHOME_LIVE_PIDS, ... and XDG_STATE_HOME (the Linux state folder; the tool's sandbox
    also ignores one outside its home). Only CCD_REHOME_PLATFORM is kept: it runs the whole self-test with the
    macOS or Windows layouts on any OS (the tool honours it only in its sandbox mode)."""
    return {k: v for k, v in os.environ.items()
            if k.upper() not in ("CLAUDE_CONFIG_DIR", "XDG_STATE_HOME") and
            not (k.upper().startswith("CCD_REHOME_") and k.upper() != "CCD_REHOME_PLATFORM")}


def run(home, *args, env=None, pre=None, timeout=None, argv=None):
    """`pre`: POSIX only, a function the child runs before the tool starts (e.g. a real file-size limit).
    `timeout`: seconds; a run that takes longer (say, one that waits on a FIFO) is killed and returns rc None.
    `argv`: what runs instead of the tool itself (the arguments follow it)."""
    e = dict(caller_env(), CCD_REHOME_HOME=home, CCD_REHOME_SANDBOX="1", **(env or {}))
    e["PYTHONIOENCODING"] = "utf-8"
    try:
        r = subprocess.run([sys.executable, "-I", *(argv or [TOOL]), *args], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", env=e, timeout=timeout,
                           **({"preexec_fn": pre} if pre else {}))
    except subprocess.TimeoutExpired:
        LAST[0] = f"$ {' '.join(args)}  (killed: still running after {timeout}s)\n"
        return None, LAST[0]
    LAST[0] = f"$ {' '.join(args)}  (rc {r.returncode})\n" + r.stdout + r.stderr
    return r.returncode, r.stdout + r.stderr


def cookies(path, present=True):
    con = sqlite3.connect(path)
    con.execute("create table cookies (host_key text, name text, expires_utc integer, encrypted_value blob)")
    if present:
        exp = datetime.datetime.now() + datetime.timedelta(days=20) - datetime.datetime(1601, 1, 1)
        con.execute("insert into cookies values ('.claude.ai','sessionKey',?,x'00')", (int(exp.total_seconds() * 1e6),))
    con.commit(); con.close()


def rec(d, sid, title, activity=1000, **extra):
    os.makedirs(d, exist_ok=True)
    r = {"sessionId": f"local_{sid}", "cliSessionId": f"cli-{sid}", "title": title, "lastActivityAt": activity,
         "createdAt": 1000, "model": "claude-opus-5-5", "effort": "xhigh", "sessionSettings": {"ultracode": True},
         "remoteMcpServersConfig": [{"x": 1}], "steeredByRemoteClient": True, "bridgeSessionIds": ["session_x"],
         "error": "stale", **extra}
    json.dump(r, open(os.path.join(d, f"local_{sid}.json"), "w", encoding="utf-8"))
    return r


def init(t, acct, org):
    return f"2026-11-07 {t} [info] [LocalSessionManager] Initialization succeeded — accountId={acct}, orgId={org}, existingSessions=0"


def profile(home, where, signed_in=B, logs=(), cookie=True):
    p = where if os.path.isabs(where) else os.path.join(home, ".claude-instances", where)
    os.makedirs(os.path.join(p, "logs"), exist_ok=True)
    json.dump({"lastKnownAccountUuid": signed_in} if signed_in else {}, open(os.path.join(p, "config.json"), "w", encoding="utf-8"))
    cookies(os.path.join(p, "Cookies"), cookie)
    open(os.path.join(p, "logs", "main.log"), "w", encoding="utf-8").write("".join(l + "\n" for l in logs))
    if signed_in:
        os.makedirs(os.path.join(p, "IndexedDB", "x.blob"), exist_ok=True)
        open(os.path.join(p, "IndexedDB", "x.blob", "1"), "wb").write(
            f'\x00{signed_in}"\x0demail_address"\x10{EMAIL[signed_in]}\x00'.encode())
    return p


def tree_hash(d, skip=None):
    """Every entry under d, hidden ones included: its relative path, type and mode, a file's bytes, a symlink's
    target (never followed). os.walk, because glob skips dot-names and `include_hidden` needs Python 3.11; every
    CLI home is a dot-dir. `skip`: a path (or a tuple of paths) under d left out, e.g. the tool's own state."""
    skip = (skip,) if isinstance(skip, str) else tuple(skip or ())
    entries = []
    for dp, dn, fn in os.walk(d):
        dn[:] = [n for n in dn if os.path.join(dp, n) not in skip]
        entries += [os.path.join(dp, n) for n in dn + fn if os.path.join(dp, n) not in skip]
    h = hashlib.sha256()
    for p in sorted(entries):
        st = os.lstat(p)
        h.update(os.path.relpath(p, d).encode("utf-8", "surrogateescape") + b"\0")
        h.update(("%o" % st.st_mode).encode() + b"\0")
        if stat.S_ISLNK(st.st_mode):
            h.update(os.readlink(p).encode("utf-8", "surrogateescape"))
        elif stat.S_ISREG(st.st_mode):
            with open(p, "rb") as f:
                h.update(hashlib.sha256(f.read()).digest())
        h.update(b"\0")
    return h.hexdigest()


def refusal_hash(home):
    """The whole home, the tool's state dir included, minus the account registry: every real run refreshes that
    (its last_seen stamps), by design. A refusal must leave everything else as it was, archives included."""
    return tree_hash(home, skip=os.path.join(sdir(home), "accounts.json"))


def sdir(h, plat=None):
    """Where the tool keeps its state for the test home h when nothing else decides (no CCD_REHOME_STATE, no
    ~/.claude-instances/_rehome left by an earlier version): the platform's own per-user state folder, for the
    layout this self-test runs with, or for `plat` (a CCD_REHOME_PLATFORM value)."""
    plat = plat or os.environ.get("CCD_REHOME_PLATFORM") or sys.platform
    if plat == "darwin":
        return os.path.join(h, "Library", "Application Support", "session-rehome")
    if plat.startswith("win"):
        return os.path.join(h, "AppData", "Local", "session-rehome")
    return os.path.join(h, ".local", "state", "session-rehome")


def disp(*parts):
    """How the tool prints a path under HOME on this OS: ~ + native separators."""
    return "~" + os.sep + os.path.join(*parts)


def newest(home, prof, kind="move"):
    d = os.path.join(sdir(home), "archive", prof)
    return sorted(x for x in os.listdir(d) if x.endswith("-" + kind))[-1]


def j(home, *args):
    rc, out = run(home, *args, "--json")
    return json.loads(out)


home = os.path.realpath(tempfile.mkdtemp(prefix="ccd-rehome-test-"))   # macOS: /var -> /private/var
try:
    print("the self-test's own hash sees hidden paths, modes and symlink targets")
    hz = os.path.join(home, "hash-probe")
    os.makedirs(os.path.join(hz, ".hidden-dir", "sub")); os.makedirs(os.path.join(hz, "visible"))
    open(os.path.join(hz, ".hidden-dir", "sub", "f"), "w", encoding="utf-8").write("one")
    open(os.path.join(hz, ".dotfile"), "w", encoding="utf-8").write("one")
    open(os.path.join(hz, "visible", "f"), "w", encoding="utf-8").write("one")
    h0 = tree_hash(hz)
    open(os.path.join(hz, ".hidden-dir", "sub", "f"), "w", encoding="utf-8").write("two")
    check(tree_hash(hz) != h0, "a changed file inside a dot-dir changes the hash")
    h0 = tree_hash(hz)
    open(os.path.join(hz, ".dotfile"), "w", encoding="utf-8").write("two")
    check(tree_hash(hz) != h0, "a changed dot-file changes the hash")
    h0 = tree_hash(hz)
    os.makedirs(os.path.join(hz, ".hidden-dir", "empty"))
    check(tree_hash(hz) != h0, "a new empty folder inside a dot-dir changes the hash")
    if os.name != "nt":
        h0, mode0 = tree_hash(hz), stat.S_IMODE(os.stat(os.path.join(hz, "visible", "f")).st_mode)
        os.chmod(os.path.join(hz, "visible", "f"), mode0 ^ 0o040)          # toggle group-read only
        h1 = tree_hash(hz)
        os.chmod(os.path.join(hz, "visible", "f"), mode0)
        check(h1 != h0 and tree_hash(hz) == h0, "a file's mode is part of the hash")
    shutil.copytree(os.path.join(hz, "visible"), os.path.join(hz, "visible2"))     # same content, other name
    try:
        os.symlink("visible", os.path.join(hz, "link")); linked = True
    except (OSError, NotImplementedError):
        linked = False
    if linked:
        h0 = tree_hash(hz)
        os.remove(os.path.join(hz, "link")); os.symlink("visible2", os.path.join(hz, "link"))
        check(tree_hash(hz) != h0, "a symlink's target is part of the hash (the link is not followed)")
    else:
        print("  (skipped symlink-target check: this OS/user cannot create symlinks)")
    shutil.rmtree(hz)

    print("Any layout: profiles and homes outside ~/.claude-instances")
    # A machine that never had ~/.claude-instances: Desktop profiles and CLI homes in folders of the user's own
    # choosing, found by every route the tool offers (profiles --add / --add-root, CCD_REHOME_INSTANCES, a shell
    # alias with --user-data-dir, Desktop's shared macOS log), named by their folder names, and the tool's state in
    # the platform's own state folder. lx stands for a folder outside HOME (/elsewhere).
    lh = os.path.join(home, "any-layout"); os.makedirs(lh)
    lx = os.path.join(home, "any-layout-elsewhere"); os.makedirs(lx)
    linst = os.path.join(lh, ".claude-instances")
    lplat = os.environ.get("CCD_REHOME_PLATFORM") or sys.platform

    def lrun(*args, env=None):
        return run(lh, *args, env=env)

    def ljson(*args, env=None):
        rc, out = lrun(*args, "--json", env=env)
        try:
            return json.loads(out)
        except ValueError:
            return None

    def lrows(env=None):
        rows = ljson("profiles", env=env)
        return {r.get("path"): r for r in rows if isinstance(r, dict)} if isinstance(rows, list) else {}

    def lfound(rows, path):
        r = rows.get(os.path.realpath(path)) or {}
        return r.get("found_by"), r.get("found_in")

    def lstate_hash():
        return tree_hash(sdir(lh), skip=os.path.join(sdir(lh), "accounts.json"))

    def lsigned(where):
        p = profile(lh, where, logs=[init("09:00:00", B, OB)])
        return os.path.realpath(p)

    def lcli(where):
        os.makedirs(os.path.join(where, "projects"))
        return os.path.realpath(where)

    lcli(os.path.join(lh, ".claude"))
    json.dump({"oauthAccount": {"accountUuid": A, "emailAddress": EMAIL[A], "organizationUuid": OA}},
              open(os.path.join(lh, ".claude.json"), "w", encoding="utf-8"))
    lwork = lsigned(os.path.join(lh, "data", "claude", "work"))
    lplay = lsigned(os.path.join(lh, "data", "claude", "play"))
    lterm = lcli(os.path.join(lh, "data", "claude", "term"))             # a CLI home among the profiles
    lhid = lcli(os.path.join(lh, "data", "claude", ".claude-hid"))       # and a hidden one
    lacct = lsigned(os.path.join(lx, "acct"))
    lcliacct = lcli(os.path.join(lx, "cli-acct"))
    lplain = os.path.join(lx, "plain"); os.makedirs(lplain)
    lenv = lsigned(os.path.join(lh, "inst2", "env-acct"))
    ldesk, lspaced, lopen, lcomment, lchrom, lglued = (lsigned(os.path.join(lh, "aliased", n)) for n in (
        "desk", "spaced", "mac-open", "commented", "chromium", "glued"))
    rec(os.path.join(lwork, "claude-code-sessions", A, OA), "w1", "work one")
    open(os.path.join(lh, ".bashrc"), "w", encoding="utf-8").write(
        "alias cw='claude-desktop --user-data-dir=\"$HOME/aliased/desk\"'\n"
        "alias cs=\"claude-desktop-unofficial --user-data-dir ~/aliased/spaced\"\n"
        "# alias cc='claude-desktop --user-data-dir=$HOME/aliased/commented'\n"
        "alias ch='chromium --user-data-dir=$HOME/aliased/chromium'\n"
        "alias cg='claude-desktop x--user-data-dir=$HOME/aliased/glued'\n")
    open(os.path.join(lh, ".zshrc"), "w", encoding="utf-8").write(
        "alias cm='open -n -a Claude --args --user-data-dir=\"$HOME/aliased/mac-open\"'\n")

    rc, out = lrun("profiles")
    check(rc == 0 and not os.path.exists(linst) and os.path.isfile(os.path.join(sdir(lh), "accounts.json")),
          "a real run on a machine without ~/.claude-instances never creates it: the state folder is the "
          "platform's own (" + os.path.relpath(sdir(lh), lh) + ")")
    lq = os.path.join(home, "any-layout-xdg"); os.makedirs(lq)
    rc, out = run(lq, "profiles", env={"XDG_STATE_HOME": os.path.join(lq, "xdg")})
    xdg_used = os.path.isfile(os.path.join(lq, "xdg", "session-rehome", "accounts.json"))
    check(rc == 0 and xdg_used == lplat.startswith("linux") and not os.path.exists(os.path.join(lq, ".claude-instances"))
          and (xdg_used or os.path.isfile(os.path.join(sdir(lq), "accounts.json"))),
          "$XDG_STATE_HOME/session-rehome is the state folder on Linux (and ignored on macOS and Windows)")
    lg = os.path.join(home, "any-layout-legacy"); os.makedirs(lg)
    lgstate = os.path.join(lg, ".claude-instances", "_rehome"); os.makedirs(lgstate)
    lgp = profile(lg, "acct-l", logs=[init("09:00:00", B, OB)])
    rec(os.path.join(lgp, "claude-code-sessions", A, OA), "l1", "legacy one")
    rc, out = run(lg, "rehome", "acct-l")
    lgarch = sorted(os.listdir(os.path.join(lgstate, "archive", "acct-l"))) \
        if os.path.isdir(os.path.join(lgstate, "archive", "acct-l")) else []
    rows = j(lg, "status", "acct-l")
    rc2, out2 = run(lg, "rollback", "acct-l", lgarch[-1] if lgarch else "none")
    check(rc == 0 and lgarch and isinstance(rows, list) and rows[0].get("archives") == lgarch and rc2 == 0
          and os.path.isfile(os.path.join(lgp, "claude-code-sessions", A, OA, "local_l1.json"))
          and not os.path.exists(sdir(lg)),
          "an existing ~/.claude-instances/_rehome keeps being the state folder: its archives are listed and roll "
          "back, and no new state folder is made")
    lgpre = tree_hash(lgstate)
    rc, out = run(lg, "profiles", env={"CCD_REHOME_STATE": os.path.join(lg, "mine")})
    check(rc == 0 and os.path.isfile(os.path.join(lg, "mine", "accounts.json")) and tree_hash(lgstate) == lgpre
          and not os.path.exists(sdir(lg)),
          "CCD_REHOME_STATE still decides, even over an existing ~/.claude-instances/_rehome")

    rows = lrows()
    check(lfound(rows, os.path.join(lh, ".claude")) == ("default", None) and lfound(rows, lwork) == (None, None)
          and lfound(rows, lacct) == (None, None) and lfound(rows, lenv) == (None, None),
          "profiles --json says where each one was found (found_by, found_in); profiles in folders nobody named "
          "are not invented")
    check(lfound(rows, ldesk) == ("shell-file", disp(".bashrc")) and lfound(rows, lspaced)[0] == "shell-file"
          and lfound(rows, lopen) == ("shell-file", disp(".zshrc"))
          and all(lfound(rows, x) == (None, None) for x in (lcomment, lchrom, lglued)),
          "a --user-data-dir= / --user-data-dir PATH used with claude-desktop, claude-desktop-unofficial or Claude "
          "in a shell startup file is found; not in a comment, not with another program, not glued to a word")

    rc, out = lrun("profiles", "--add", lacct)
    rc2, out2 = lrun("profiles", "--add", lcliacct)
    rows = lrows()
    check(rc == 0 and "added the Desktop profile" in out and rc2 == 0 and "added the CLI home" in out2
          and lfound(rows, lacct) == ("added", None) and rows.get(lacct, {}).get("kind") == "desktop"
          and lfound(rows, lcliacct) == ("added", None) and rows.get(lcliacct, {}).get("kind") == "cli",
          "profiles --add PATH registers a Desktop profile or a CLI home anywhere (it tells which), found on every "
          "run")
    lpre = lstate_hash()
    bad = []
    for path, want in ((lplain, "neither a Desktop profile (no config.json) nor a CLI home"),
                       (os.path.join(lx, "missing"), "does not exist"), (lh, "is your home folder"),
                       (sdir(lh), "the tool's state folder")):
        rc, out = lrun("profiles", "--add", path)
        if rc != 1 or want not in " ".join(out.split()) or "Nothing was changed" not in out:
            bad.append(path)
    check(not bad and lstate_hash() == lpre,
          "profiles --add refuses, with the reason, a folder that is neither, a missing path, HOME and the state "
          "folder; nothing is written")

    rc, out = lrun("profiles", "--add-root", os.path.join(lh, "data", "claude"))
    rows = lrows()
    check(rc == 0 and "added the profile root" in out
          and lfound(rows, lwork) == ("root", disp("data", "claude")) and lfound(rows, lplay)[0] == "root"
          and lfound(rows, lterm) == ("root", disp("data", "claude")) and rows.get(lterm, {}).get("kind") == "cli"
          and lfound(rows, lhid)[0] == "root",
          "profiles --add-root DIR: every Desktop profile and CLI home in its subfolders is found, on every run "
          "(a hidden .claude-NAME too)")
    lpre, bad = lstate_hash(), []
    for path, want in ((lh, "is your home folder"), (os.path.join(lx, "missing"), "does not exist"),
                       (lwork, "--add")):
        rc, out = lrun("profiles", "--add-root", path)
        if rc != 1 or want not in out or "Nothing was changed" not in out:
            bad.append(path)
    check(not bad and lstate_hash() == lpre and lfound(lrows(), lwork)[0] == "root",
          "profiles --add-root refuses HOME, a missing folder and a profile itself (that is --add), with the "
          "reason; nothing is written")
    rows = lrows(env={"CCD_REHOME_INSTANCES": os.path.join(lh, "inst2")})
    check(lfound(rows, lenv) == ("env", "CCD_REHOME_INSTANCES") and lfound(lrows(), lenv) == (None, None),
          "CCD_REHOME_INSTANCES names folders whose subfolders are profiles (found_by env)")
    rc, out = lrun("profiles")
    wline = next((l for l in out.splitlines() if l.rstrip().endswith("found: root " + disp("data", "claude"))
                  and " work " in l), "")
    check(rc == 0 and wline and any(lacct in l and l.rstrip().endswith("found: added") for l in out.splitlines())
          and any(l.rstrip().endswith("found: shell file " + disp(".bashrc")) for l in out.splitlines())
          and "state folder: " + "~" + os.sep + os.path.relpath(sdir(lh), lh) in out,
          "profiles (text) prints where each one was found, and the state folder in use")

    rows = ljson("status", "work")
    rows2 = ljson("status", "acct")
    rows3 = ljson("status", "env-acct", env={"CCD_REHOME_INSTANCES": os.path.join(lh, "inst2")})
    check(isinstance(rows, list) and rows[0].get("path") == lwork and rows[0].get("profile") == "work"
          and isinstance(rows2, list) and rows2[0].get("path") == lacct
          and isinstance(rows3, list) and rows3[0].get("path") == lenv,
          "a bare NAME is the folder NAME under a profile root (an added root, CCD_REHOME_INSTANCES), else a known "
          "profile whose folder is called NAME")
    rows = lrows()
    check(rows.get(lwork, {}).get("profile") == "work" and rows.get(lacct, {}).get("profile") == lacct,
          "a profile in a root is printed by its folder name, one found anywhere else by its path")
    rc, out = lrun("rehome", "work")
    keys = os.listdir(os.path.join(sdir(lh), "archive")) if os.path.isdir(os.path.join(sdir(lh), "archive")) else []
    wkey = [k for k in keys if k.startswith("path-data_claude_work-")]
    warch = sorted(os.listdir(os.path.join(sdir(lh), "archive", wkey[0]))) if wkey else []
    rc2, out2 = lrun("rollback", "work", warch[-1] if warch else "none")
    check(rc == 0 and wkey and "work" not in keys and warch and rc2 == 0
          and os.path.isfile(os.path.join(lwork, "claude-code-sessions", A, OA, "local_w1.json")),
          "a move of a root's profile by its bare name is archived under the key its path always had (not under "
          "the folder name), and rolls back by that name")
    lmore = lsigned(os.path.join(lh, "more", "work"))
    lrun("profiles", "--add-root", os.path.join(lh, "more"))
    lpre = lstate_hash()
    rc, out = lrun("status", "work")
    rows = lrows()
    flat_ = " ".join(out.split())
    check(rc == 1 and "ambiguous" in flat_ and disp("data", "claude", "work") in flat_ and disp("more", "work") in flat_
          and rows.get(lwork, {}).get("profile") == disp("data", "claude", "work")
          and rows.get(lmore, {}).get("profile") == disp("more", "work") and lstate_hash() == lpre,
          "a bare NAME that two roots hold is refused, with both paths, and both are printed by their paths")
    s1, s2 = lsigned(os.path.join(lx, "x", "same")), lsigned(os.path.join(lx, "y", "same"))
    lrun("profiles", "--add", s1); lrun("profiles", "--add", s2)
    rc, out = lrun("status", "same")
    check(rc == 1 and "ambiguous" in out and s1 in out and s2 in out,
          "two known profiles with the same folder name: the bare name is refused, with both paths")

    lbackup = lcli(os.path.join(lx, "homes", "backup"))
    lold = lcli(os.path.join(lx, "mnt", ".claude-old"))
    lt1, lt2 = lcli(os.path.join(lx, "t1", "twin")), lcli(os.path.join(lx, "t2", "twin"))
    lpref, lpref2 = lcli(os.path.join(lh, ".claude-pref")), lcli(os.path.join(lx, "p", "pref"))
    lrun("profiles", "--add", lold)
    cenv = {"CCD_REHOME_CLI_HOMES": os.pathsep.join([lbackup, lt1, lt2, lpref2])}
    r1, r2, r3 = ljson("status", "cli:backup", env=cenv), ljson("status", "cli:old"), ljson("status", "cli:pref", env=cenv)
    rc, out = lrun("status", "cli:twin", env=cenv)
    check(isinstance(r1, list) and r1[0].get("path") == lbackup and isinstance(r2, list) and r2[0].get("path") == lold
          and isinstance(r3, list) and r3[0].get("path") == lpref
          and rc == 1 and "ambiguous" in out and lt1 in out and lt2 in out,
          "cli:NAME is ~/.claude-NAME, else the known CLI home whose folder is NAME or .claude-NAME; two such homes "
          "are refused, with both paths")

    rc, out = lrun("profiles", "--forget", lacct)
    rc2, out2 = lrun("profiles", "--forget", os.path.join(lh, "data", "claude"))
    rows = lrows()
    rc3, out3 = lrun("status", "acct")
    check(rc == 0 and rc2 == 0 and lacct not in rows and lwork not in rows and lplay not in rows
          and lterm not in rows and lhid not in rows and lmore in rows and rc3 == 1 and "does not exist" in out3,
          "profiles --forget removes an added profile, and a root with every profile in it")
    lpre = lstate_hash()
    rc, out = lrun("profiles", "--forget", lplain)
    rc2, out2 = lrun("profiles", "--forget", os.path.join(lh, ".claude"))
    check(rc == 1 and "is not registered" in out and rc2 == 1 and "is not registered" in out2
          and "found: default" in out2 and lstate_hash() == lpre,
          "--forget of a path never added is refused (and says how it is found instead); nothing is written")
    rc, out = lrun("status", "--add", lacct)
    check(rc == 2 and "--add, --add-root and --forget go with `profiles`" in out,
          "--add, --add-root and --forget go with `profiles` only (exit 2)")

    zstate = os.path.join(lh, "data", "claude", "zz-state"); os.makedirs(zstate)
    zenv = {"CCD_REHOME_STATE": zstate, "CCD_REHOME_INSTANCES": os.path.join(lh, "data", "claude")}
    seen = []
    for marker in ("config.json", "settings.json"):
        open(os.path.join(zstate, marker), "w", encoding="utf-8").write("{}")
        rows = lrows(env=zenv)
        seen.append(lwork in rows and os.path.realpath(zstate) not in rows)
        os.remove(os.path.join(zstate, marker))
    rc, out = lrun("profiles", "--add", zstate, env=zenv)
    check(all(seen) and len(seen) == 2 and rc == 1 and "the tool's state folder" in out,
          "the state folder is never a Desktop profile or a CLI home, even inside a profile root")

    lml = os.path.join(lh, "Library", "Logs", "Claude"); os.makedirs(lml)
    lmac, lmplain = lsigned(os.path.join(lh, "mac", "place")), os.path.join(lh, "mac", "plain")
    os.makedirs(os.path.join(lmplain, "claude-code-sessions", B, OB))
    open(os.path.join(lml, "main.log"), "w", encoding="utf-8").write("".join(
        f"2026-11-07 09:00:0{i} [info] [LocalSessionManager] Loaded {i} persisted sessions from "
        f"{os.path.join(p, 'claude-code-sessions', B, OB)}\n"
        for i, p in enumerate((lmac, os.path.join(lh, "mac", "gone"), lmplain))))
    mrows, prows = lrows(env={"CCD_REHOME_PLATFORM": "darwin"}), lrows()
    check(lfound(mrows, lmac) == ("log", disp("Library", "Logs", "Claude", "main.log"))
          and os.path.realpath(lmplain) not in mrows and len([p for p in mrows if "/mac/" in p.replace(os.sep, "/")]) == 1
          and (lplat == "darwin" or lmac not in prows),
          "macOS: a profile that Desktop's shared log names in a 'Loaded N persisted sessions from' line is found "
          "(only one that exists and is a Desktop profile)")
    check(not os.path.exists(linst) and not os.path.exists(os.path.join(lx, ".claude-instances"))
          and not os.path.exists(os.path.join(lq, ".claude-instances")),
          "no run of this section created a ~/.claude-instances")

    os.makedirs(os.path.join(home, ".claude", "projects", "-x"))
    open(os.path.join(home, ".claude", "projects", "-x", "cli-s1.jsonl"), "w", encoding="utf-8").write("{}\n")
    json.dump({"oauthAccount": {"accountUuid": A, "emailAddress": EMAIL[A], "organizationUuid": OA,
               "organizationName": "Org A"}}, open(os.path.join(home, ".claude.json"), "w", encoding="utf-8"))

    # ---- P1: signed in as B; sessions under A and C; Desktop's transitional line (old acct + new org) present
    logs = [init("08:00:00", C, OC), init("09:00:00", A, OA),
            "2026-11-07 10:00:00 [info] [account] Login-state transition (loggedOut: false → true, uuid: " + A + " → <none>), clearing oauth cache",
            "2026-11-07 10:01:00 [info] [account] Login-state transition (loggedOut: true → false, uuid: <none> → " + B + "), clearing oauth cache",
            init("10:01:00", A, OB), init("10:01:02", B, OB)]
    p1 = profile(home, "acct-p1", logs=logs)
    s = os.path.join(p1, "claude-code-sessions")
    sa, sc, dst = os.path.join(s, A, OA), os.path.join(s, C, OC), os.path.join(s, B, OB)
    rec(sa, "s1", "one", armedWorkAtQuit={"backgroundTaskCount": 3})
    rec(sa, "s2", "two", model="claude-local-example[1m]")
    rec(sa, "s3", "three-older", activity=5); rec(dst, "s3", "three-newer", activity=99)
    rec(sc, "c1", "from-c")
    rec(sa, "u1", "Café · 漢字 · 🚀 naïve")                                 # non-ASCII title: must survive byte-exact
    os.makedirs(os.path.join(s, A, OB))                                 # stray empty dir, as Desktop leaves
    open(os.path.join(sa, "deleted_zz"), "w", encoding="utf-8").write("1787193830575")            # Desktop's format: a ms timestamp
    os.makedirs(os.path.join(sa, "backlog"))
    json.dump({"version": 1, "items": [{"id": "t1", "originSessionId": "local_s1"},
                                       {"id": "t2", "originSessionId": "local_s2"}]},
              open(os.path.join(sa, "backlog", "tasks.json"), "w", encoding="utf-8"))
    json.dump({"scheduledTasks": [{"id": "k1"}]}, open(os.path.join(sa, "scheduled-tasks.json"), "w", encoding="utf-8"))
    json.dump({"scheduledTasks": []}, open(os.path.join(dst, "scheduled-tasks.json"), "w", encoding="utf-8"))
    cw = os.path.join(p1, "local-agent-mode-sessions")
    os.makedirs(os.path.join(cw, A, OA, "local_cw1")); open(os.path.join(cw, A, OA, "local_cw1", "f"), "w", encoding="utf-8").write("x")
    os.makedirs(os.path.join(cw, A, OA, "rpm", "plugin_x"))
    before = tree_hash(p1)

    print("discovery / accounts / status / sessions")
    rc, out = run(home, "accounts")
    check(all(EMAIL[x] in out for x in (A, B)), "emails from IndexedDB (B) and ~/.claude.json (A)")
    reg = json.load(open(os.path.join(sdir(home), "accounts.json"), encoding="utf-8"))["accounts"]
    check(list(reg[A]["orgs"]) == [OA], "registry ignores the transitional line (A is not linked to B's org)")
    st = j(home, "status", "acct-p1")[0]
    check(st["email"] == EMAIL[B] and st["active_dir"] == dst, "signed-in account and its real org found")
    check(sum(st["stranded"].values()) == 5 and st["cowork_stranded"] == 1, "5 stranded code sessions + 1 cowork item")
    ss = j(home, "sessions", "acct-p1")["sessions"]
    vis = {x["id"]: x["visible"] for x in ss if x["kind"] == "code"}
    check(vis == {"s3": True, "s1": False, "s2": False, "s3": False, "c1": False} or
          (sorted(x["id"] for x in ss if x["visible"]) == ["s3"] and len(ss) == 7),
          "sessions lists every record, its account, and whether Desktop shows it")
    check({x["email"] for x in ss if x["id"] == "c1"} == {"cccccccc… (email unknown)"},
          "an account with no known email is still listed (by uuid)")

    print("dry run")
    h_home = tree_hash(home)
    rc, out = run(home, "rehome", "acct-p1", "--dry-run")
    check(rc == 0 and tree_hash(home) == h_home, "a TRUE dry run: the whole home (state dir included) is byte-identical")
    check("nothing was written" in out and "would" in out, "dry run says what the real run would do")

    print("--from: only one source account")
    rc, out = run(home, "move", "acct-p1", "--from", "cccc")
    check(rc == 0 and os.path.exists(os.path.join(dst, "local_c1.json")) and os.path.exists(os.path.join(sa, "local_s1.json")),
          "--from C moves C's session and leaves A's")
    arch_from = newest(home, "acct-p1")
    rc, out = run(home, "rollback", "acct-p1", arch_from)
    check(rc == 0 and tree_hash(p1) == before, "rollback of the --from move is exact")

    print("rehome everything (3 accounts -> signed-in B), with cowork")
    rc, out = run(home, "rehome", "acct-p1", "--include-cowork")
    check(rc == 0, "rehome exits 0")
    check(sorted(os.listdir(sa)) == ["backlog", "deleted_zz", "local_s3.json", "scheduled-tasks.json"] and
          not os.listdir(sc), "records from both other accounts moved; the newer-copy skip stays put")
    r1 = json.load(open(os.path.join(dst, "local_s1.json"), encoding="utf-8"))
    check(not {"remoteMcpServersConfig", "steeredByRemoteClient", "bridgeSessionIds", "error"} & set(r1),
          "account-bound (incl. bridgeSessionIds) and transient fields dropped")
    check(r1["armedWorkAtQuit"] == {"backgroundTaskCount": 3} and "3 queued background task(s) kept" in out,
          "queued background work (armedWorkAtQuit) kept and reported")
    check(r1["effort"] == "xhigh" and r1["sessionSettings"] == {"ultracode": True}, "effort / ultracode kept")
    check(json.load(open(os.path.join(dst, "local_u1.json"), encoding="utf-8"))["title"] == "Café · 漢字 · 🚀 naïve",
          "a non-ASCII title survives the move unchanged (UTF-8 on every OS)")
    check(json.load(open(os.path.join(dst, "local_s2.json"), encoding="utf-8"))["model"] == "claude-opus-5-5", "local-only model replaced")
    check(json.load(open(os.path.join(dst, "local_s3.json"), encoding="utf-8"))["title"] == "three-newer", "newer copy in target wins")
    check(os.path.exists(os.path.join(dst, "deleted_zz")), "tombstone copied")
    check([i["id"] for i in json.load(open(os.path.join(dst, "backlog", "tasks.json"), encoding="utf-8"))["items"]] == ["t1", "t2"],
          "all task suggestions merged on a full move")
    check([i["id"] for i in json.load(open(os.path.join(dst, "scheduled-tasks.json"), encoding="utf-8"))["scheduledTasks"]] == ["k1"],
          "scheduled tasks merged")
    check(os.path.exists(os.path.join(cw, B, OB, "local_cw1", "f")) and os.path.isdir(os.path.join(cw, A, OA, "rpm")),
          "cowork item moved; its rpm/ plugin cache left alone")
    check(open(os.path.join(home, ".claude", "projects", "-x", "cli-s1.jsonl"), encoding="utf-8").read() == "{}\n",
          "transcript untouched")
    rc, out = run(home, "rehome", "acct-p1")
    check(rc == 0 and "moved" not in out.replace("moved,", ""), "second run moves nothing")
    arch = newest(home, "acct-p1")
    rc, out = run(home, "rollback", "acct-p1", arch)
    check(rc == 0 and tree_hash(p1) == before, "rollback restores everything, cowork dirs included, byte-identical")

    print("validation: drift and format errors")
    rec(sa, "dr1", "has-new-field", newDesktopField={"x": 1})
    os.makedirs(os.path.join(sa, "new-per-account-store"))
    h_home = refusal_hash(home)
    rc, out = run(home, "rehome", "acct-p1")
    check(rc != 0 and "DRIFT" in out and "newDesktopField" in out and "new-per-account-store" in out
          and "nothing was changed" in out and refusal_hash(home) == h_home,
          "real run refuses on DRIFT (unknown field + unknown entry), names both, writes nothing")
    rc, out = run(home, "rehome", "acct-p1", "--dry-run")
    check(rc == 0 and "DRIFT" in out and "--accept-drift" not in out.split("DRIFT")[0], "dry run reports DRIFT and still shows the plan")
    rc, out = run(home, "move", "acct-p1", "--only", "dr1", "--accept-drift")
    check(rc == 0 and json.load(open(os.path.join(dst, "local_dr1.json"), encoding="utf-8"))["newDesktopField"] == {"x": 1},
          "--accept-drift proceeds (unknown field carried as-is)")
    rc, out = run(home, "rollback", "acct-p1", newest(home, "acct-p1"))
    os.remove(os.path.join(sa, "local_dr1.json")); os.rmdir(os.path.join(sa, "new-per-account-store"))
    json.dump({"version": 1, "items": [{"no_id": 1}]}, open(os.path.join(sa, "backlog", "tasks.json"), "w", encoding="utf-8"))
    h_home = refusal_hash(home)
    rc, out = run(home, "rehome", "acct-p1", "--accept-drift")
    check(rc != 0 and "ERROR" in out and "tasks.json" in out and refusal_hash(home) == h_home,
          "a changed format (task items without id) is an ERROR: refused even with --accept-drift")
    json.dump({"version": 1, "items": [{"id": "t1", "originSessionId": "local_s1"},
                                       {"id": "t2", "originSessionId": "local_s2"}]},
              open(os.path.join(sa, "backlog", "tasks.json"), "w", encoding="utf-8"))
    check(tree_hash(p1) == before, "fixture restored")

    print("Desktop 4.x layout (fields and folders first seen on Desktop 4.23118.0, macOS)")
    v4 = profile(home, "acct-v4", logs=[init("09:00:00", A, OA), init("10:00:00", B, OB),
                                        "2026-11-07 10:00:00 [info] Starting app {", "  appVersion: '4.23118.0',",
                                        "  isPackaged: true,", "}"])
    s4 = os.path.join(v4, "claude-code-sessions")
    rec(os.path.join(s4, A, OA), "n1", "new-fields", chromeAllowedDomains=["localhost:9090"], chromeTabGroupId=1,
        contextExceededCount=3, cuAllowedApps=[{"bundleId": "x"}], cuGrantFlags={"clipboardRead": False},
        cuLastScreenshotDims={"width": 1}, cuSelectedDisplayId=1, interruptedAwaitingPerson=None,
        lastAssistantCliSessionId="cli-n1", lastTurnEdgeAt=1, planPath="/p/plan.md", previousTitles=["t"],
        queryCrashes=[], shellFolders=["/p"], spawnedFrom={"sessionId": "local_x"}, startedFromEnvironmentId="env_01x", turnBoxDeclared=True,
        turnBoxMounted=True, turnWrapUp={"description": "d"})
    os.makedirs(os.path.join(s4, A, OA, "waiting-input")); os.makedirs(os.path.join(s4, B, OB, "waiting-input"))
    cw4 = os.path.join(v4, "local-agent-mode-sessions", A, OA)
    for d in ("cowork_plugins/marketplaces", "debug", "backups", ".claude.json.lock"):
        os.makedirs(os.path.join(cw4, d))
    for f, body in ((".claude.json", "{}"), ("cowork-gb-cache.json", "{}"), ("cowork_settings.json", "{}")):
        open(os.path.join(cw4, f), "w", encoding="utf-8").write(body)
    rc, out = run(home, "doctor")
    check("0 unknown field(s)" in out and "session-dir entries: 0 unknown" in out,
          "Desktop 4.x record fields, waiting-input and Cowork caches are known: no drift")
    rc, out = run(home, "report", "selftest")
    check('"desktop": "4.23118.0"' in out, "Desktop version read from the log's appVersion")
    rc, out = run(home, "rehome", "acct-v4")
    check(rc == 0 and os.path.exists(os.path.join(s4, B, OB, "local_n1.json")) and
          json.load(open(os.path.join(s4, B, OB, "local_n1.json"), encoding="utf-8"))["turnWrapUp"] == {"description": "d"},
          "a 4.x record moves with its new session-state fields kept")
    open(os.path.join(s4, A, OA, "waiting-input", "snap1"), "w", encoding="utf-8").write("{}")
    rec(os.path.join(s4, A, OA), "n2", "second")
    rc, out = run(home, "rehome", "acct-v4")
    check(rc != 0 and "waiting-input" in out and "DRIFT" in out,
          "a NON-empty waiting-input (pending input snapshots) is DRIFT: it would be left behind")
    os.remove(os.path.join(s4, A, OA, "waiting-input", "snap1"))
    os.makedirs(os.path.join(cw4, "local_cw9"))
    json.dump({"spaces": [{"id": "sp1"}]}, open(os.path.join(cw4, "spaces.json"), "w", encoding="utf-8"))
    rc, out = run(home, "rehome", "acct-v4", "--include-cowork")
    check(rc != 0 and "spaces" in out and "Cowork" in out, "Cowork move refused while spaces/agent data exist (not supported yet)")
    rc, out = run(home, "rehome", "acct-v4")
    check(rc == 0 and os.path.exists(os.path.join(s4, B, OB, "local_n2.json")),
          "...while a Code-only move of the same profile still works")

    print("--only: a subset, with only its own task suggestions")
    rc, out = run(home, "move", "acct-p1", "--only", "s1")
    items = json.load(open(os.path.join(dst, "backlog", "tasks.json"), encoding="utf-8"))["items"]
    check(rc == 0 and os.path.exists(os.path.join(dst, "local_s1.json")) and os.path.exists(os.path.join(sa, "local_s2.json"))
          and [i["id"] for i in items] == ["t1"], "--only s1 moves s1 and only the suggestion that came from s1")
    rc, out = run(home, "move", "acct-p1", "--only", "nope")
    check(rc != 0 and "matched no" in out, "--only with an unknown id refuses")

    print("--to an account that is NOT signed in (pre-stage)")
    rc, out = run(home, "move", "acct-p1", "--to", EMAIL[A], "--only", "s1")
    check(rc == 0 and os.path.exists(os.path.join(sa, "local_s1.json")) and "not the signed-in account" in out,
          "--to EMAIL moves into that account's real org and warns it is not signed in")
    rc, out = run(home, "move", "acct-p1", "--to", "nobody@example.com")
    check(rc != 0 and "matches 0 known accounts" in out, "--to an unknown email refuses and lists known accounts")
    D = "dddddddd-4444-4444-8444-444444444444"; OD = "0d0d0d0d-4444-4444-8444-444444444444"
    rc, out = run(home, "move", "acct-p1", "--to", D, "--only", "s2")
    check(rc != 0, "--to an account never seen anywhere refuses")
    os.makedirs(os.path.join(s, D))
    rc, out = run(home, "move", "acct-p1", "--to", "dddd", "--only", "s2")
    check(rc != 0 and "--to-org" in out, "--to an account with no known org asks for --to-org")
    rc, out = run(home, "move", "acct-p1", "--to", "dddd", "--to-org", OD, "--only", "s2")
    check(rc == 0 and os.path.exists(os.path.join(s, D, OD, "local_s2.json")), "--to-org creates the target and moves")

    print("blockers")
    p2 = profile(home, "acct-p2", signed_in=None, cookie=False, logs=[init("09:00:00", A, OA)])
    rec(os.path.join(p2, "claude-code-sessions", A, OA), "x1", "x")
    rc, out = run(home, "rehome", "acct-p2")
    check(rc != 0 and "not signed in" in out, "signed-out profile refuses a plain rehome")
    p3 = profile(home, "acct-p3", logs=[init("09:00:00", A, OA)])
    rec(os.path.join(p3, "claude-code-sessions", A, OA), "y1", "y")
    rc, out = run(home, "rehome", "acct-p3", "--dry-run")
    check(rc == 0 and "inferred" in out, "Code tab never opened here: org inferred from the account's only known org")
    reg_f = os.path.join(sdir(home), "accounts.json")
    rg = json.load(open(reg_f, encoding="utf-8")); rg["accounts"][B]["orgs"][OC] = None; json.dump(rg, open(reg_f, "w", encoding="utf-8"))
    rc, out = run(home, "rehome", "acct-p3")
    check(rc != 0 and "ambiguous" in out and "Code tab once" in out,
          "...but an account with several known orgs refuses and says to open the Code tab")
    rg["accounts"][B]["orgs"].pop(OC); json.dump(rg, open(reg_f, "w", encoding="utf-8"))
    try:
        ok = j(home, "status", "acct-p3")[0]["email"] == EMAIL[B] and "sessions" in j(home, "sessions", "acct-p3")
    except ValueError:
        ok = False
    check(ok, "--json stays valid JSON when the target org is inferred (notes never leak into it)")
    p4 = profile(home, "acct-p4", logs=[init("09:00:00", A, OA), init("10:00:00", B, OB)])
    rec(os.path.join(p4, "claude-code-sessions", A, OA), "z1", "z"); os.makedirs(os.path.join(p4, "claude-code-sessions", B, OB))
    bad = os.path.join(p4, "claude-code-sessions", A, OA, "local_z2.json"); open(bad, "w", encoding="utf-8").write("{not json")
    h4 = tree_hash(p4)
    rc, out = run(home, "rehome", "acct-p4")
    check(rc != 0 and "nothing was changed" in out and tree_hash(p4) == h4, "unreadable record refuses before any write")
    os.remove(bad)

    print("any user-data-dir, anywhere")
    elsewhere = os.path.join(home, "work", "desktop profiles", "acct-p1")      # same basename as p1, a space in it
    p5 = profile(home, elsewhere, logs=[init("09:00:00", A, OA), init("10:00:00", B, OB)])
    rec(os.path.join(p5, "claude-code-sessions", A, OA), "e1", "elsewhere")
    os.makedirs(os.path.join(p5, "claude-code-sessions", B, OB))
    rc, out = run(home, "profiles")
    check(elsewhere not in out and "~/work" not in out, "an unknown outside path is not invented")
    rc, out = run(home, "profiles", env={"CCD_REHOME_PROFILES": elsewhere})
    check(disp("work", "desktop profiles", "acct-p1") in out, "found via $CCD_REHOME_PROFILES")
    rc, out = run(home, "rehome", elsewhere)
    check(rc == 0 and os.path.exists(os.path.join(p5, "claude-code-sessions", B, OB, "local_e1.json")),
          "rehome works on a path outside ~/.claude-instances")
    rc, out = run(home, "profiles")
    check(disp("work", "desktop profiles", "acct-p1") in out, "and is remembered afterwards (no env needed)")
    keys = os.listdir(os.path.join(sdir(home), "archive"))
    check("acct-p1" in keys and any(k.startswith("path-work_desktop_profiles_acct-p1-") for k in keys),
          "two profiles with the same folder name get separate archive keys")
    arch5 = os.listdir(os.path.join(sdir(home), "archive",
                                    [k for k in keys if k.startswith("path-")][0]))[0]
    rc, out = run(home, "rollback", "~/" + os.path.relpath(elsewhere, home), arch5)
    check(rc == 0 and os.path.exists(os.path.join(p5, "claude-code-sessions", A, OA, "local_e1.json")),
          "rollback by ~-path works")
    rc, out = run(home, "status", os.path.join(home, "work"))
    check(rc != 0 and "not a Desktop profile" in out, "a folder that is not a profile is refused clearly")

    print("verify")
    with open(os.path.join(p1, "logs", "main.log"), "a", encoding="utf-8") as f:
        n = len(glob.glob(os.path.join(dst, "local_*.json")))
        f.write(f"2099-01-01 00:00:00 [info] Loaded {n - 1} persisted sessions from {dst}\n")
    rc, out = run(home, "verify", "acct-p1")
    check(rc != 0 and "MISMATCH" in out, f"verify flags Desktop loading fewer records than exist ({n - 1} of {n})")
    with open(os.path.join(p1, "logs", "main.log"), "a", encoding="utf-8") as f:
        f.write(f"2099-01-02 00:00:00 [info] Loaded {n} persisted sessions from {dst}\n")
    rc, out = run(home, "verify", "acct-p1")
    check(rc == 0 and "OK" in out, "verify passes when Desktop loaded every record")

    print("switching BACK to an account used before")
    p6 = profile(home, "acct-p6", logs=[init("08:00:00", B, OB), init("09:00:00", B, OA), init("09:00:01", A, OA)])
    os.makedirs(os.path.join(p6, "claude-code-sessions", B, OB)); os.makedirs(os.path.join(p6, "claude-code-sessions", B, OA))
    rec(os.path.join(p6, "claude-code-sessions", A, OA), "w1", "w")
    check(j(home, "status", "acct-p6")[0]["active_dir"] == os.path.join(p6, "claude-code-sessions", B, OB),
          "transitional line for the signed-in account is ignored (target = its real org)")

    print("--all")
    rc, out = run(home, "rehome", "--all")
    check(rc != 0 and "acct-p2: SKIPPED" in out and "acct-p3: 1 session(s)" in out and "acct-p4: 1 session(s)" in out,
          "--all does the safe ones, explains the blocked ones, exits non-zero")

    print("command-line parsing and Desktop detection (macOS / Windows formats)")
    import importlib.machinery, importlib.util
    spec = importlib.util.spec_from_loader("cr", importlib.machinery.SourceFileLoader("cr", TOOL))
    cr = importlib.util.module_from_spec(spec); spec.loader.exec_module(cr)
    a = cr._split("/Applications/Claude.app/Contents/MacOS/Claude --user-data-dir=/Users/x/Library/Application Support/Claude --foo")
    check(a[0] == "/Applications/Claude.app/Contents/MacOS/Claude" and
          "--user-data-dir=/Users/x/Library/Application Support/Claude" in a, "macOS ps line: path with spaces kept whole")
    a = cr._split('"C:\\Users\\x\\AppData\\Local\\AnthropicClaude\\app-1\\claude.exe" "--user-data-dir=C:\\P D\\acct-e" --type=renderer')
    check(a[0].endswith("claude.exe") and "--user-data-dir=C:\\P D\\acct-e" in a and "--type=renderer" in a,
          "Windows command line: quoted exe and quoted user-data-dir")
    app = ("/Applications/Claude.app/Contents/MacOS/Claude" if cr.MAC else
           "C:/Users/u/AppData/Local/AnthropicClaude/app-1/claude.exe" if cr.WIN else "/usr/lib/claude-desktop/claude-desktop")
    check(not cr._is_desktop(["/home/u/.claude-instances/acct-d/claude-code/2.1/x/claude", "--output-format"]) and
          cr._is_desktop([app]), "the Claude Code CLI (`claude`) is never mistaken for the Desktop app (this OS)")

    root_ = "/home/u/.claude-instances/acct-x/claude-code/"
    wrapper = ["/usr/lib/claude-desktop/resources/disclaimer", "--pgroup", "--", root_ + "2.1.295/abc/claude",
               "--output-format", "stream-json", "--resume", "11111111-2222-4333-8444-555555555555"]
    check(cr._owned_by(wrapper, root_, None, "/home/u/.claude-instances/acct-x"),
          "Desktop's `disclaimer` wrapper around a session CLI counts as that instance's process")
    check(not cr._owned_by(["/usr/bin/vim", "/home/u/notes.txt"], root_, None, "/home/u/.claude-instances/acct-x"),
          "an unrelated process does not")

    print("macOS layout (simulated): default under 'Application Support', shared ~/Library/Logs/Claude")
    mh = os.path.join(home, "mac"); os.makedirs(os.path.join(mh, ".claude", "projects"))
    mdef = os.path.join(mh, "Library", "Application Support", "Claude")
    macc = os.path.join(mh, ".claude-instances", "acct-m")
    for pp in (mdef, macc):
        profile(home, pp); shutil.rmtree(os.path.join(pp, "logs"))          # macOS: no per-profile logs
    for pp in (mdef, macc):
        rec(os.path.join(pp, "claude-code-sessions", A, OA), "m-" + os.path.basename(pp)[-1], "mac")
    os.makedirs(os.path.join(mh, "Library", "Logs", "Claude"))
    with open(os.path.join(mh, "Library", "Logs", "Claude", "main.log"), "w", encoding="utf-8") as f:   # ONE log for both instances
        f.write(init("09:00:00", B, OB) + "\n")                                         # no path: unattributable
        f.write(f"2026-11-07 09:00:00 [info] Loaded 0 persisted sessions from {mdef}/claude-code-sessions/{B}/{OB}\n")
        f.write(f"2026-11-07 09:00:05 [info] Loaded 0 persisted sessions from {macc}/claude-code-sessions/{B}/{OC}\n")
    menv = {"CCD_REHOME_PLATFORM": "darwin"}
    rc, out = run(mh, "status", "--json", env=menv)
    try:
        rows = {r["profile"]: r for r in json.loads(out)}
    except ValueError:
        rows = {}
    check(rows.get("default", {}).get("active_dir") == os.path.join(mdef, "claude-code-sessions", B, OB),
          "macOS default profile found; its org comes from ITS path-bearing line in the shared log")
    check(rows.get("acct-m", {}).get("active_dir") == os.path.join(macc, "claude-code-sessions", B, OC),
          "a second instance sharing that log gets its own org, not the other instance's")
    rc, out = run(mh, "rehome", "default", env=menv)
    check(rc == 0 and os.path.exists(os.path.join(mdef, "claude-code-sessions", B, OB, "local_m-e.json")),
          "rehome on the macOS layout (path with a space)")
    with open(os.path.join(mh, "Library", "Logs", "Claude", "main.log"), "a", encoding="utf-8") as f:
        f.write(f"2099-01-01 00:00:00 [info] Loaded 1 persisted sessions from {mdef}/claude-code-sessions/{B}/{OB}\n")
    rc, out = run(mh, "verify", "default", env=menv)
    check(rc == 0 and "OK" in out, "verify reads a 'Loaded … from' path containing spaces")

    print("Windows layout (simulated)")
    wh = os.path.join(home, "win"); os.makedirs(os.path.join(wh, ".claude", "projects"))
    wdef = os.path.join(wh, "AppData", "Roaming", "Claude")
    profile(home, wdef, logs=[init("09:00:00", A, OA), init("10:00:00", B, OB)])
    rec(os.path.join(wdef, "claude-code-sessions", A, OA), "w9", "win")
    wenv = {"CCD_REHOME_PLATFORM": "win32", "APPDATA": os.path.join(wh, "AppData", "Roaming")}
    rc, out = run(wh, "rehome", "default", env=wenv)
    check(rc == 0 and os.path.exists(os.path.join(wdef, "claude-code-sessions", B, OB, "local_w9.json")),
          "default profile resolves to %APPDATA%\\Claude and rehomes")
    rc, out = run(wh, "quit", "default", env=wenv)
    check("not supported on Windows" in out or "not running" in out, "quit never signals on Windows")

    print("doctor")
    rc, out = run(home, "doctor")
    check(rc == 0 and "ready" in out and "profile(s) found" in out, "doctor runs and reports readiness")
    check("0 unknown field(s)" in out, "doctor: no drift on known record fields")
    rec(dst, "drift1", "drift", someNewDesktopField=1)
    os.makedirs(os.path.join(dst, "brand-new-store"))
    rc, out = run(home, "doctor")
    check("someNewDesktopField" in out and "brand-new-store" in out and "DRIFT" in out,
          "doctor flags a new record field and a new per-account entry as DRIFT, with what to do")
    os.remove(os.path.join(dst, "local_drift1.json")); os.rmdir(os.path.join(dst, "brand-new-store"))

    print("export-record / adopt (the interface session-transporter uses)")
    src = profile(home, "acct-x1", logs=[init("09:00:00", A, OA)], signed_in=A)
    rx = rec(os.path.join(src, "claude-code-sessions", A, OA), "e1e1e1e1-0000-4000-8000-000000000001", "Café export",
             cwd="/old/host/proj", originCwd="/old/host/proj", gitAnchorsFolderRealpath="/old/host/proj",
             planPath="/old/.claude/plans/p.md", shellFolders=["/old/host/proj/x"], cuAllowedApps=[{"bundleId": "a"}], startedFromEnvironmentId="env_01x",
             chromeTabGroupId=7)
    out_f = os.path.join(home, "exported.json")
    rc, out = run(home, "export-record", "acct-x1", "--only", "e1e1e1e1", "--out", out_f)
    ex = json.load(open(out_f, encoding="utf-8")) if os.path.exists(out_f) else {}
    r = ex.get("record", {})
    check(rc == 0 and ex.get("format") == "ccd-record/1" and r.get("cliSessionId") == "cli-e1e1e1e1-0000-4000-8000-000000000001",
          "export-record writes a portable ccd-record/1 file")
    check(not {"remoteMcpServersConfig", "steeredByRemoteClient", "bridgeSessionIds", "error"} & set(r)
          and r.get("title") == "Café export", "exported record has account-bound and transient fields stripped, title intact")
    check(not any(x in json.dumps(ex) for x in (A, OA)), "exported record carries no account or org id")
    dst_p = profile(home, "acct-x2", logs=[init("09:00:00", B, OB)])
    dd = os.path.join(dst_p, "claude-code-sessions", B, OB); os.makedirs(dd)
    h_dst = tree_hash(dst_p)
    rc, out = run(home, "adopt", "acct-x2", "--record", out_f, "--cwd", "/new/host/proj", "--dry-run")
    check(rc == 0 and tree_hash(dst_p) == h_dst and "would" in out.lower(), "adopt --dry-run writes nothing")
    rc, out = run(home, "adopt", "acct-x2", "--record", out_f, "--cwd", "/new/host/proj")
    placed = glob.glob(os.path.join(dd, "local_*.json"))
    pr = json.load(open(placed[0], encoding="utf-8")) if placed else {}
    check(rc == 0 and len(placed) == 1 and pr.get("cwd") == "/new/host/proj" and pr.get("originCwd") == "/new/host/proj",
          "adopt files the record under the signed-in account with the new cwd")
    check(not {"gitAnchorsFolderRealpath", "planPath", "shellFolders", "cuAllowedApps", "chromeTabGroupId", "startedFromEnvironmentId"} & set(pr)
          and pr.get("effort") == "xhigh" and pr.get("sessionSettings") == {"ultracode": True},
          "cross-host adopt drops fields bound to the old machine, keeps session settings")
    check(os.path.basename(placed[0])[:-5] == pr.get("sessionId") if placed else False, "file name == sessionId")
    rc, out = run(home, "adopt", "acct-x2", "--record", out_f, "--cwd", "/new/host/proj")
    check(rc == 0 and len(glob.glob(os.path.join(dd, "local_*.json"))) == 1 and "already" in out,
          "adopt is idempotent: the same conversation is never registered twice")
    other = os.path.join(dst_p, "claude-code-sessions", A, OA); os.makedirs(other)
    shutil.move(placed[0], os.path.join(other, os.path.basename(placed[0])))
    rc, out = run(home, "adopt", "acct-x2", "--record", out_f, "--cwd", "/new/host/proj")
    check(rc != 0 and "already in this profile" in out, "adopt refuses a conversation already filed under another account (use move)")
    shutil.move(os.path.join(other, os.path.basename(placed[0])), placed[0])
    a_arch = sorted(x for x in os.listdir(os.path.join(sdir(home), "archive", "acct-x2"))
                    if x.endswith("-adopt"))
    rc, out = run(home, "rollback", "acct-x2", a_arch[0]) if a_arch else (1, "")
    check(rc == 0 and not glob.glob(os.path.join(dd, "local_*.json")), "an adopt is undone exactly by rollback")
    ex2 = dict(ex); ex2["record"] = dict(r, brandNewField=1)
    json.dump(ex2, open(out_f, "w", encoding="utf-8"))
    rc, out = run(home, "adopt", "acct-x2", "--record", out_f, "--cwd", "/new/host/proj")
    check(rc != 0 and "DRIFT" in out, "adopt refuses a record with unknown fields unless --accept-drift")
    json.dump({"format": "nope"}, open(out_f, "w", encoding="utf-8"))
    rc, out = run(home, "adopt", "acct-x2", "--record", out_f)
    check(rc != 0 and "ccd-record/1" in out, "adopt refuses a file that is not a ccd-record/1")

    print("older Desktop builds (first seen 1.9255.2, Linux arm64): no lastKnownAccountUuid, no Login-state lines")
    o1 = profile(home, "acct-old", signed_in=None, logs=[
        "2026-11-07 20:08:19 [info] claude.ai account active and logged in",
        "2026-11-07 20:08:20 [info] [account] User logged out during IPC wait, stopping early",
        "2026-11-07 20:51:33 [info] [account] User is logged out, skipping account ID wait",
        "2026-11-07 20:58:08 [info] claude.ai account active and logged in",
        init("20:58:08", A, OA)])
    rec(os.path.join(o1, "claude-code-sessions", A, OA), "old1", "older build session")
    st = j(home, "status", "acct-old")[0]
    check(st["verdict"] == "signed-in" and st["account"] == A and len(st["visible"]) == 1,
          "signed in judged from the NEWEST login event; account taken from Desktop's own init line")
    o2 = profile(home, "acct-old2", signed_in=None, cookie=True, logs=[
        "2026-11-07 20:08:19 [info] claude.ai account active and logged in", init("20:08:19", A, OA),
        "2026-11-07 20:08:20 [info] [account] User is logged out, skipping account ID wait"])
    check(j(home, "status", "acct-old2")[0]["verdict"] == "signed-out",
          "a logged-out event AFTER the last login means signed out (the Pi's 20:08 sequence)")

    print("CLI <-> Desktop: cli-sessions / register / resume-cli / unregister")
    import importlib.machinery, importlib.util
    spec = importlib.util.spec_from_loader("cr2", importlib.machinery.SourceFileLoader("cr2", TOOL))
    cr2 = importlib.util.module_from_spec(spec); spec.loader.exec_module(cr2)
    tm = os.path.join(os.path.dirname(os.path.dirname(HERE)), "session-transporter", "scripts", "mangle.py")
    if os.path.isfile(tm):
        sys.path.insert(0, os.path.dirname(tm)); import mangle as canon
        cases = ["/home/u/Projects/a b", "/a/b.c_d", "/Users/x/Café/漢字", "/p/" + "x" * 230, "C:\\Users\\x\\proj"]
        check(all(cr2.mangle(c) == canon.mangle(c) for c in cases),
              "rehome's mangle matches session-transporter's canonical mangle.py (incl. >200 chars, non-ASCII)")
    else:
        print("  (skipped mangle cross-check: session-transporter not installed next to this skill)")
    work = os.path.join(home, "Projects", "cli proj"); os.makedirs(work)
    key = cr2.mangle(os.path.realpath(work))
    pdir = os.path.join(home, ".claude", "projects", key); os.makedirs(pdir, exist_ok=True)
    CLI1 = "c1c1c1c1-0000-4000-8000-000000000001"
    lines = [{"type": "user", "uuid": "u1", "cwd": os.path.realpath(work), "entrypoint": "cli", "sessionId": CLI1,
              "timestamp": "2026-11-01T10:00:00.000Z", "message": {"role": "user", "content": "write a parser"}},
             {"type": "assistant", "uuid": "a1", "cwd": os.path.realpath(work), "entrypoint": "cli",
              "timestamp": "2026-11-02T11:00:00.000Z", "message": {"role": "assistant", "content": "ok"}},
             {"type": "custom-title", "customTitle": "Parser work", "sessionId": CLI1}]
    tx = os.path.join(pdir, CLI1 + ".jsonl")
    open(tx, "w", encoding="utf-8").write("".join(json.dumps(l) + "\n" for l in lines))
    tx_hash = hashlib.sha256(open(tx, "rb").read()).hexdigest()
    reg = profile(home, "acct-reg", logs=[init("09:00:00", B, OB)])
    rd = os.path.join(reg, "claude-code-sessions", B, OB); os.makedirs(rd)
    rc, out = run(home, "cli-sessions", "--json")
    rows = json.loads(out) if rc == 0 else []
    mine = [r for r in rows if r.get("cli") == CLI1]
    check(len(mine) == 1 and mine[0]["started_in"] == "cli" and mine[0]["cwd"] == os.path.realpath(work)
          and mine[0]["title"] == "Parser work", "cli-sessions lists a transcript no Desktop profile knows, with its folder")
    h = tree_hash(reg)
    rc, out = run(home, "register", "acct-reg", "--cli-session-id", "c1c1c1c1", "--dry-run")
    check(rc == 0 and tree_hash(reg) == h, "register --dry-run writes nothing")
    rc, out = run(home, "register", "acct-reg", "--cli-session-id", "c1c1c1c1")
    got = glob.glob(os.path.join(rd, "local_*.json"))
    gr = json.load(open(got[0], encoding="utf-8")) if got else {}
    check(rc == 0 and len(got) == 1 and gr.get("cliSessionId") == CLI1 and gr.get("cwd") == os.path.realpath(work)
          and gr.get("title") == "Parser work", "register files a Desktop record for the CLI session (folder, title)")
    check(gr.get("createdAt", 0) < gr.get("lastActivityAt", 0) and gr.get("lastActivityAt", 0) > 1.7e12,
          "created / last-activity times come from the transcript")
    check(hashlib.sha256(open(tx, "rb").read()).hexdigest() == tx_hash, "the transcript is not touched (no import)")
    rc, out = run(home, "register", "acct-reg", "--cli-session-id", "c1c1c1c1")
    check(rc == 0 and len(glob.glob(os.path.join(rd, "local_*.json"))) == 1 and "already" in out,
          "register is idempotent")
    rc, out = run(home, "resume-cli", "acct-reg", "--only", os.path.basename(got[0])[6:14] if got else "x")
    check(rc == 0 and "--resume " + CLI1 in out and os.path.realpath(work) in out,
          "resume-cli prints the exact command (folder + conversation id) to continue it in the terminal")
    rc, out = run(home, "unregister", "acct-reg", "--only", os.path.basename(got[0])[6:14] if got else "x")
    check(rc == 0 and not glob.glob(os.path.join(rd, "local_*.json")) and "claude --resume" in out,
          "unregister archives and removes the Desktop record, and prints how to resume in the CLI")
    ua = sorted(x for x in os.listdir(os.path.join(sdir(home), "archive", "acct-reg"))
                if x.endswith("-unregister"))
    rc, out = run(home, "rollback", "acct-reg", ua[-1]) if ua else (1, "")
    check(rc == 0 and len(glob.glob(os.path.join(rd, "local_*.json"))) == 1, "an unregister is undone by rollback")
    gpath = glob.glob(os.path.join(rd, "local_*.json"))[0]
    g2 = json.load(open(gpath, encoding="utf-8")); g2.update(effort="max", permissionMode="auto",
                                                             sessionSettings={"ultracode": True}, title="Renamed in Desktop")
    json.dump(g2, open(gpath, "w", encoding="utf-8"))
    rc, out = run(home, "unregister", "acct-reg", "--only", os.path.basename(gpath)[6:14])
    rc, out = run(home, "register", "acct-reg", "--cli-session-id", "c1c1c1c1")
    g3 = json.load(open(glob.glob(os.path.join(rd, "local_*.json"))[0], encoding="utf-8"))
    check(rc == 0 and g3.get("effort") == "max" and g3.get("sessionSettings") == {"ultracode": True}
          and g3.get("title") == "Renamed in Desktop" and "restored" in out,
          "register after unregister restores the session's Desktop settings from the archive (nothing lost)")
    fake = os.path.join(home, "fakebin"); os.makedirs(fake)
    if sys.platform.startswith("win"):                  # Windows finds commands by extension (PATHEXT)
        with open(os.path.join(fake, "claude.cmd"), "w", encoding="utf-8") as f:
            f.write("@echo 2.1.100 (Claude Code)\r\n")
    else:
        with open(os.path.join(fake, "claude"), "w", encoding="utf-8") as f:
            f.write("#!/bin/sh\necho '2.1.100 (Claude Code)'\n")
        os.chmod(os.path.join(fake, "claude"), 0o755)
    open(tx, "a", encoding="utf-8").write(json.dumps({"type": "assistant", "uuid": "a2", "version": "2.1.295",
                                                      "entrypoint": "claude-desktop"}) + "\n")
    rc, out = run(home, "resume-cli", "acct-reg", "--only", os.path.basename(glob.glob(os.path.join(rd, "local_*.json"))[0])[6:14],
                  env={"PATH": fake + os.pathsep + os.environ.get("PATH", "")})
    check(rc == 0 and "different account" in out and "a@example.com" in out and "b@example.com" in out,
          "resume-cli warns when the terminal CLI is signed in to a different account than the Desktop session")
    check("2.1.100" in out and "2.1.295" in out and "older" in out,
          "resume-cli warns when the terminal CLI is older than the one that last wrote the conversation")
    rid = os.path.basename(glob.glob(os.path.join(rd, "local_*.json"))[0])[6:14]
    rc, out = run(home, "resume-cli", "acct-reg", "--only", rid, env={"CLAUDE_CODE_ENTRYPOINT": "claude-desktop",
                                                                     "CCD_REHOME_PLATFORM": "linux"})
    check(rc == 0 and "inside a Desktop session" in out and "env -i" in out,
          "resume-cli warns when run from inside a Desktop session (the child would be stamped as Desktop) and shows a clean-env command")
    rc, out = run(home, "resume-cli", "acct-reg", "--only", rid, env={"CLAUDE_CODE_ENTRYPOINT": "claude-desktop",
                                                                     "CCD_REHOME_PLATFORM": "win32"})
    check(rc == 0 and "inside a Desktop session" in out and "new terminal" in out and "env -i" not in out,
          "on Windows too, it warns inside a Desktop session, with a remedy that works there (a new terminal, no env -i)")
    CLI2 = "c2c2c2c2-0000-4000-8000-000000000002"
    gone = os.path.join(home, "Projects", "moved-away")
    p2 = os.path.join(home, ".claude", "projects", cr2.mangle(gone)); os.makedirs(p2)
    open(os.path.join(p2, CLI2 + ".jsonl"), "w", encoding="utf-8").write(json.dumps(
        {"type": "user", "uuid": "x", "cwd": gone, "entrypoint": "cli", "sessionId": CLI2}) + "\n")
    rc, out = run(home, "register", "acct-reg", "--cli-session-id", "c2c2c2c2")
    check(rc != 0 and "does not exist" in out, "register refuses when the session's folder no longer exists")
    os.makedirs(os.path.join(home, "Projects", "elsewhere"))
    rc, out = run(home, "register", "acct-reg", "--cli-session-id", "c2c2c2c2", "--cwd", os.path.join(home, "Projects", "elsewhere"))
    check(rc != 0 and "would not find" in out, "register refuses a --cwd the CLI would not resume from (key mismatch)")

    print("move --to-profile (between user-data-dirs on one host)")
    ps_ = profile(home, "acct-ps", logs=[init("09:00:00", A, OA)], signed_in=A)
    pd_ = profile(home, "acct-pd", logs=[init("09:00:00", B, OB)])
    sd_ = os.path.join(ps_, "claude-code-sessions", A, OA); dd_ = os.path.join(pd_, "claude-code-sessions", B, OB)
    os.makedirs(dd_)
    rec(sd_, "f1f1f1f1-0000-4000-8000-000000000001", "cross-profile", effort="max")
    os.makedirs(os.path.join(sd_, "backlog"))
    json.dump({"version": 1, "items": [{"id": "x1", "originSessionId": "local_f1f1f1f1-0000-4000-8000-000000000001"},
                                       {"id": "x2", "originSessionId": "local_other"}]},
              open(os.path.join(sd_, "backlog", "tasks.json"), "w", encoding="utf-8"))
    h_src, h_dst = tree_hash(ps_), tree_hash(pd_)
    rc, out = run(home, "move", "acct-ps", "--only", "f1f1f1f1", "--to-profile", "acct-pd", "--dry-run")
    check(rc == 0 and tree_hash(ps_) == h_src and tree_hash(pd_) == h_dst, "move --to-profile --dry-run writes nothing in either profile")
    rc, out = run(home, "move", "acct-ps", "--only", "f1f1f1f1", "--to-profile", "acct-pd")
    moved_ = glob.glob(os.path.join(dd_, "local_*.json"))
    mr = json.load(open(moved_[0], encoding="utf-8")) if moved_ else {}
    check(rc == 0 and not glob.glob(os.path.join(sd_, "local_*.json")) and len(moved_) == 1
          and mr.get("effort") == "max" and "remoteMcpServersConfig" not in mr,
          "move --to-profile: filed in the other profile's signed-in account, removed from the source, settings kept")
    bl = os.path.join(dd_, "backlog", "tasks.json")
    check(os.path.isfile(bl) and [i["id"] for i in json.load(open(bl, encoding="utf-8"))["items"]] == ["x1"],
          "its own task suggestions go with it (and only those)")
    rc, out = run(home, "move", "acct-ps", "--only", "f1f1f1f1", "--to-profile", "acct-pd")
    check(rc != 0 and "matches 0" in out, "a second run finds nothing to move (no duplicate)")

    print("report (shareable compatibility entry)")
    rc, out = run(home, "report", "selftest")
    body = out.split("\n#")[0]
    try:
        entry = json.loads(body)
    except ValueError:
        entry = {}
    import re as _re
    check(entry.get("tool") and entry.get("os_family") and entry.get("arch") and entry.get("verified") == ["selftest"],
          "report is valid JSON with versions and CPU architecture")
    check(not _re.search(r"@|[0-9a-f]{8}-[0-9a-f]{4}-|" + _re.escape(home) + "|" + _re.escape(os.path.basename(home)), body),
          "report contains no emails, uuids or paths")
    rc, out = run(home, "--version")
    check(rc == 0 and out.startswith("ccd-rehome "), "--version")

    print("registry survives sign-out")
    shutil.rmtree(os.path.join(p1, "IndexedDB")); os.remove(os.path.join(home, ".claude.json"))
    rc, out = run(home, "accounts")
    check(EMAIL[A] in out and EMAIL[B] in out, "emails stay known after every source forgets them")

    print("CLI homes (CLAUDE_CONFIG_DIR)")
    # A home of its own, so the transcript counts here do not move with the sections above.
    ch = os.path.join(home, "cli-homes"); os.makedirs(ch)
    cstate = sdir(ch)

    def cli_hash(state=False):
        """Every entry under the CLI test home (.claude, .claude-work, .claude.json, ... included). The tool's own
        state/archive dir is left out; with state=True it is kept, minus the account registry every real run
        refreshes: what a refusal must leave as it was (no archive either)."""
        return tree_hash(ch, skip=os.path.join(cstate, "accounts.json") if state else cstate)

    outputs = []

    def crun(*args, env=None, pre=None):
        rc, out = run(ch, *args, env=env, pre=pre)
        outputs.append(out)
        return rc, out

    def cj(*args, env=None):
        rc, out = crun(*args, "--json", env=env)
        return json.loads(out)

    cdef = os.path.join(ch, ".claude")
    work = os.path.join(ch, ".claude-work")
    xhome = os.path.join(ch, "elsewhere", "xhome")
    for d in (cdef, work, xhome):
        os.makedirs(os.path.join(d, "projects"), exist_ok=True)
    json.dump({"oauthAccount": {"accountUuid": A, "emailAddress": EMAIL[A], "organizationUuid": OA,
                                "organizationName": "Org A"}},
              open(os.path.join(ch, ".claude.json"), "w", encoding="utf-8"))
    for d, acct, org, orgname in ((work, B, OB, "Org B"), (xhome, C, OC, "Org C")):
        json.dump({"oauthAccount": {"accountUuid": acct, "emailAddress": EMAIL[acct], "organizationUuid": org,
                                    "organizationName": orgname}},
                  open(os.path.join(d, ".claude.json"), "w", encoding="utf-8"))
    open(os.path.join(cdef, ".credentials.json"), "w", encoding="utf-8").write("DECOY-CREDENTIAL-xyz")
    # Two different, non-default retention periods (the default is 30), so check 8 shows WHICH home's is read.
    open(os.path.join(work, "settings.json"), "w", encoding="utf-8").write('{"cleanupPeriodDays": 45}')
    open(os.path.join(cdef, "settings.json"), "w", encoding="utf-8").write('{"cleanupPeriodDays": 50}')
    open(os.path.join(ch, ".bashrc"), "w", encoding="utf-8").write(
        "alias claude-x='CLAUDE_CONFIG_DIR=~/elsewhere/xhome claude'\n")

    proj = os.path.join(ch, "Projects", "alpha"); os.makedirs(proj)
    proj2 = os.path.join(ch, "Projects", "beta"); os.makedirs(proj2)
    k1 = cr2.mangle(os.path.realpath(proj))
    k2 = cr2.mangle(os.path.realpath(proj2))
    CS1 = "e1e1e1e1-0000-4000-8000-000000000101"
    CS2 = "e2e2e2e2-0000-4000-8000-000000000102"
    CS4 = "e4e4e4e4-0000-4000-8000-000000000104"

    def cli_transcript(base, key, sid, cwd, title=None, summary=None):
        d = os.path.join(base, "projects", key); os.makedirs(d, exist_ok=True)
        rows = [{"type": "user", "uuid": "u1", "cwd": cwd, "entrypoint": "cli", "sessionId": sid,
                 "timestamp": "2026-10-01T10:00:00.000Z", "message": {"role": "user", "content": "hello"}},
                {"type": "assistant", "uuid": "a1", "cwd": cwd, "entrypoint": "cli", "sessionId": sid,
                 "timestamp": "2026-10-01T10:01:00.000Z", "message": {"role": "assistant", "content": "ok"}}]
        if title is not None:
            rows.append({"type": "custom-title", "customTitle": title, "sessionId": sid})
        if summary is not None:
            rows.append({"type": "summary", "summary": summary, "sessionId": sid})
        p = os.path.join(d, sid + ".jsonl")
        open(p, "w", encoding="utf-8").write("".join(json.dumps(r) + "\n" for r in rows))
        return p

    tx1 = cli_transcript(cdef, k1, CS1, os.path.realpath(proj), title="CLI title one")
    tx2 = cli_transcript(cdef, k1, CS2, os.path.realpath(proj), summary="CLI summary two")
    side = os.path.join(cdef, "projects", k1, CS1, "subagents"); os.makedirs(side)
    open(os.path.join(side, "agent.jsonl"), "w", encoding="utf-8").write("{}\n")
    os.makedirs(os.path.join(cdef, "tasks", CS1)); open(os.path.join(cdef, "tasks", CS1, "task"), "w", encoding="utf-8").write("t")
    os.makedirs(os.path.join(cdef, "todos"))
    open(os.path.join(cdef, "todos", CS1 + "-agent-" + CS1 + ".json"), "w", encoding="utf-8").write("[]")
    os.makedirs(os.path.join(cdef, "file-history", CS1))
    open(os.path.join(cdef, "file-history", CS1, "v1"), "w", encoding="utf-8").write("v1")
    mem = os.path.join(cdef, "projects", k1, "memory"); os.makedirs(mem)
    open(os.path.join(mem, "MEM.md"), "w", encoding="utf-8").write("alpha memory")
    open(os.path.join(mem, "EXTRA.md"), "w", encoding="utf-8").write("only alpha")
    wmem = os.path.join(work, "projects", k1, "memory"); os.makedirs(wmem)
    open(os.path.join(wmem, "MEM.md"), "w", encoding="utf-8").write("work memory differs")
    open(os.path.join(cdef, "history.jsonl"), "w", encoding="utf-8").write('{"display": "a prompt"}\n')
    sreg = os.path.join(cdef, "sessions"); os.makedirs(sreg)
    json.dump({"pid": 11111, "sessionId": CS1, "cwd": os.path.realpath(proj), "status": "active"},
              open(os.path.join(sreg, "11111.json"), "w", encoding="utf-8"))
    json.dump({"pid": 22222, "sessionId": CS2, "cwd": os.path.realpath(proj), "status": "idle"},
              open(os.path.join(sreg, "22222.json"), "w", encoding="utf-8"))
    open(os.path.join(sreg, "11111.abc.key"), "w", encoding="utf-8").write("KEY-SECRET-xyz")

    cli_rows = {r["profile"]: r for r in cj("profiles") if r.get("kind") == "cli"}
    alias_name = disp("elsewhere", "xhome")
    check(set(cli_rows) == {"cli", "cli:work", alias_name},
          "profiles lists exactly cli, cli:work and the alias-fed home as kind cli")
    check(cli_rows.get("cli", {}).get("email") == EMAIL[A] and cli_rows["cli"].get("sessions") == 2,
          "cli: account A's email and its two sessions")
    check(cli_rows.get("cli:work", {}).get("email") == EMAIL[B] and cli_rows.get("cli:work", {}).get("sessions") == 0,
          "cli:work: account B's email and no sessions")
    check(cli_rows.get(alias_name, {}).get("email") == EMAIL[C], "the home named only by .bashrc has account C's email")

    # A caller started with CLAUDE_CONFIG_DIR (the multi-account setup this section is about) must not lead the
    # tool to a home, or a Desktop profile, outside the test HOME: run() hands the tool none of these variables.
    caller_cli = os.path.join(home, "caller-cli-home"); caller_cli2 = os.path.join(home, "caller-cli-home2")
    for d in (caller_cli, caller_cli2):
        cli_transcript(d, "-caller", "cacacaca-0000-4000-8000-000000000001", "/caller")
    caller_desk = profile(home, os.path.join(home, "caller-desktop"))
    caller_vars = {"CLAUDE_CONFIG_DIR": caller_cli, "CCD_REHOME_CLI_HOMES": caller_cli2,
                   "CCD_REHOME_PROFILES": caller_desk, "CCD_REHOME_LIVE_PIDS": "11111"}
    saved_env = {k: os.environ.get(k) for k in caller_vars}
    os.environ.update(caller_vars)
    try:
        rc, out = crun("profiles", "--json")
        live_c = {r["id"]: r for r in cj("sessions", "cli")["sessions"]}
    finally:
        for k, v in saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    known = os.path.join(cstate, "profiles.json")
    check(rc == 0 and "caller-" not in out and
          not (os.path.exists(known) and "caller-" in open(known, encoding="utf-8").read()),
          "the caller's CLAUDE_CONFIG_DIR / CCD_REHOME_CLI_HOMES / CCD_REHOME_PROFILES never reach the tool")
    check(live_c.get(CS1, {}).get("open") is False, "the caller's CCD_REHOME_LIVE_PIDS never reaches the tool")
    shutil.rmtree(caller_cli); shutil.rmtree(caller_cli2); shutil.rmtree(caller_desk)

    # The verdict depends on the OS (macOS keeps the login in the Keychain), so each OS is pinned, not the host's.
    for plat, want_work in (("linux", "signed-out"), ("win32", "signed-out"), ("darwin", "unknown")):
        penv = {"CCD_REHOME_PLATFORM": plat}
        st = {r["profile"]: r for r in cj("status", "cli:work", env=penv) if r.get("kind") == "cli"}
        check(st.get("cli:work", {}).get("verdict") == want_work,
              f"status cli:work on {plat}: {want_work} (no credentials file"
              + ("; the login may be in the Keychain)" if plat == "darwin" else ")"))
        st = {r["profile"]: r for r in cj("status", "cli", env=penv) if r.get("kind") == "cli"}
        check(st.get("cli", {}).get("verdict") == "signed-in", f"status cli on {plat}: signed-in (credentials file present)")
    if os.name != "nt":
        cred = os.path.join(cdef, ".credentials.json")
        os.chmod(cred, 0)
        try:
            st = {r["profile"]: r for r in cj("status", "cli") if r.get("kind") == "cli"}
            check(st.get("cli", {}).get("verdict") == "signed-in",
                  "a mode-000 .credentials.json still says signed-in: the file is never opened")
        finally:
            os.chmod(cred, 0o600)

    ss = {r["id"]: r for r in cj("sessions", "cli")["sessions"]}
    check(CS1 in ss and CS2 in ss, "sessions cli lists both transcripts")
    check(ss.get(CS1, {}).get("cwd") == os.path.realpath(proj) and ss.get(CS1, {}).get("title") == "CLI title one",
          "a session's folder (from its transcript) and custom title")
    check(ss.get(CS2, {}).get("title") == "CLI summary two", "without a custom title, the last summary is used")
    rc, out = crun("sessions", "cli")
    check(os.path.realpath(proj) in out and "CLI title one" in out, "sessions cli shows the folder and title")
    live = {r["id"]: r for r in cj("sessions", "cli", env={"CCD_REHOME_LIVE_PIDS": "11111"})["sessions"]}
    check(live.get(CS1, {}).get("open") is True and live.get(CS2, {}).get("open") is False,
          "a live sessions/<pid>.json entry makes its session OPEN")
    rc, out = crun("sessions", "cli", env={"CCD_REHOME_LIVE_PIDS": "11111"})
    check("OPEN" in out, "sessions cli prints OPEN for it")

    CS3 = "e3e3e3e3-0000-4000-8000-000000000103"
    tx3 = cli_transcript(cdef, k1, CS3, os.path.realpath(proj), title="Symlinked sidecar")
    inside = os.path.join(cdef, "inside-target"); os.makedirs(inside)
    open(os.path.join(inside, "f"), "w", encoding="utf-8").write("target")
    try:
        os.symlink(inside, os.path.join(cdef, "projects", k1, CS3)); linked = True
    except (OSError, NotImplementedError):
        linked = False
    if linked:
        pre = cli_hash(True)
        rc, out = crun("move", "cli", "--only", CS3[:8], "--to-profile", "cli:work")
        check(rc != 0 and cli_hash(True) == pre and "symlink" in out.lower(),
              "a symlinked sidecar folder is refused and nothing is written")
        os.remove(os.path.join(cdef, "projects", k1, CS3)); os.remove(tx3)
    else:
        os.remove(tx3)
        print("  (skipped symlink check: this OS/user cannot create symlinks)")

    state_pre = tree_hash(cstate)
    pre = cli_hash()
    rc, out = crun("move", "cli", "--only", CS1[:8], "--to-profile", "cli:work", "--dry-run")
    check(rc == 0 and cli_hash() == pre and tree_hash(cstate) == state_pre,
          "move --to-profile --dry-run leaves every CLI home and the tool's state byte-identical")
    check("would" in out.lower() or "dry run" in out.lower(), "the dry run shows the plan")
    check(CS1[:8] in out and "memory" in out.lower(), "the dry run names the session and the memory copies")

    saved = open(tx1, "rb").read()
    rc, out = crun("move", "cli", "--only", CS1[:8], "--to-profile", "cli:work")
    wtx1 = os.path.join(work, "projects", k1, CS1 + ".jsonl")
    check(rc == 0 and os.path.exists(wtx1) and open(wtx1, "rb").read() == saved and not os.path.exists(tx1),
          "move: transcript moved byte-for-byte into cli:work and gone from cli")
    check(os.path.isdir(os.path.join(work, "projects", k1, CS1, "subagents")) and
          not os.path.exists(os.path.join(cdef, "projects", k1, CS1)), "the sidecar folder moved too")
    check(os.path.isdir(os.path.join(work, "tasks", CS1)) and not os.path.exists(os.path.join(cdef, "tasks", CS1)) and
          os.path.exists(os.path.join(work, "todos", CS1 + "-agent-" + CS1 + ".json")) and
          os.path.isdir(os.path.join(work, "file-history", CS1)),
          "tasks/, todos/<id>*.json and file-history/ moved")
    check(os.path.exists(os.path.join(cdef, "history.jsonl")) and
          not os.path.exists(os.path.join(work, "history.jsonl")),
          "history.jsonl is never moved")
    wmem_mem = os.path.join(work, "projects", k1, "memory", "MEM.md")
    check(os.path.exists(os.path.join(mem, "MEM.md")) and os.path.exists(os.path.join(mem, "EXTRA.md")),
          "the project memory stays in cli (other sessions still use it)")
    check(open(wmem_mem, encoding="utf-8").read() == "work memory differs" and
          os.path.exists(os.path.join(work, "projects", k1, "memory", "EXTRA.md")),
          "memory copied file by file; a different existing file is kept")
    check("conflict" in out.lower(), "the memory conflict is reported")
    check("organization" in out.lower() and "unverified" in out, "a different org is warned about (unverified)")
    check("CLAUDE_CONFIG_DIR" in out and "--resume " + CS1 in out, "the resume command names CLAUDE_CONFIG_DIR and the id")
    ma = re.search(r"Archive:\s+(\S+)", out)
    arch = ma.group(1) if ma else ""
    check(bool(arch) and arch.endswith("-cli-move"), "the move prints its archive name")

    rc, out = crun("rollback", "cli:work", arch)
    check(rc == 0 and cli_hash() == pre, "rollback from the destination restores every CLI home exactly")
    check(os.path.exists(tx1) and not os.path.exists(wtx1), "rollback moves the transcript back")

    pre = cli_hash(True)
    rc, out = crun("move", "cli", "--only", CS1[:8], "--to-profile", "cli:work", env={"CCD_REHOME_LIVE_PIDS": "11111"})
    check(rc != 0 and cli_hash(True) == pre and "open" in out.lower(), "an OPEN session refuses and nothing is written")

    desk = profile(ch, "acct-cli-desk", logs=[init("09:00:00", A, OA)])
    rec(os.path.join(desk, "claude-code-sessions", A, OA), "cs1desk", "desk", cliSessionId=CS1)
    pre_rb = cli_hash()
    pre = cli_hash(True)
    rc, out = crun("move", "cli", "--only", CS1[:8], "--to-profile", "cli:work")
    check(rc != 0 and cli_hash(True) == pre and "unregister" in out and "--copy" in out,
          "a Desktop record for the session refuses; the message says unregister or --copy")
    rc, out = crun("move", "cli", "--only", CS1[:8], "--to-profile", "cli:work", "--copy")
    check(rc == 0 and os.path.exists(tx1) and os.path.exists(wtx1) and "diverge" in out,
          "--copy is allowed and warns the copies diverge")
    archc = re.search(r"Archive:\s+(\S+)", out)
    rc, out = crun("rollback", "cli:work", archc.group(1) if archc else "")
    check(rc == 0 and cli_hash() == pre_rb, "rollback of a --copy move removes the unchanged copies")

    # Without the Desktop record, so the refusal below can only come from the DIFFERENT transcript (the record's
    # own refusal, and the cross-org warning's "different", would otherwise mask it).
    desk_rec = os.path.join(desk, "claude-code-sessions", A, OA, "local_cs1desk.json")
    os.remove(desk_rec)
    dupdir = os.path.join(work, "projects", k2); os.makedirs(dupdir)
    open(os.path.join(dupdir, CS1 + ".jsonl"), "w", encoding="utf-8").write('{"type": "user", "cwd": "/x"}\n')
    pre = cli_hash(True)
    rc, out = crun("move", "cli", "--only", CS1[:8], "--to-profile", "cli:work")
    check(rc != 0 and cli_hash(True) == pre and "DIFFERENT transcript" in out and "is shown by Desktop" not in out,
          "a different transcript with the same id in the target refuses on its own (no duplicate id in one home)")
    open(os.path.join(dupdir, CS1 + ".jsonl"), "wb").write(saved)
    pre = cli_hash(True)
    rc, out = crun("move", "cli", "--only", CS1[:8], "--to-profile", "cli:work")
    check(rc == 0 and "already there" in out and cli_hash(True) == pre,
          "an identical transcript is 'already there': skipped, not an error")
    shutil.rmtree(dupdir)
    rec(os.path.join(desk, "claude-code-sessions", A, OA), "cs1desk", "desk", cliSessionId=CS1)

    old = time.time() - 60 * 86400
    os.utime(tx2, (old, old))
    rc, out = crun("move", "cli", "--only", CS2[:8], "--to-profile", "cli:work")
    wtx2 = os.path.join(work, "projects", k1, CS2 + ".jsonl")
    check(rc == 0 and "older than 45 days (cleanupPeriodDays in cli:work)" in out
          and abs(os.path.getmtime(wtx2) - time.time()) < 120,
          "an old transcript warns with the DESTINATION's cleanupPeriodDays (45, not cli's 50 or the default 30) "
          "and is re-dated")
    os.utime(wtx2, (old, old))
    # (a move with --keep-dates of an old transcript is refused, since the target would delete the only copy at its
    # next start: the fifth review's section checks that; a --copy with --keep-dates goes ahead)
    rc, out = crun("move", "cli:work", "--only", CS2[:8], "--to-profile", "cli", "--keep-dates", "--copy")
    check(rc == 0 and os.path.exists(tx2) and abs(os.path.getmtime(tx2) - old) < 2
          and "older than 50 days (cleanupPeriodDays in cli)" in out,
          "--keep-dates leaves the old mtime (a --copy here; the warning uses cli's own 50 days)")
    if rc == 0 and os.path.exists(tx2):
        os.remove(wtx2)                  # as a move would have left it: CS2 in cli only

    tx4 = cli_transcript(cdef, k2, CS4, os.path.realpath(proj2), title="Beta session")
    rc, out = crun("move", "cli", "--project", proj2, "--to-profile", "cli:work")
    check(rc == 0 and not os.path.exists(tx4) and os.path.exists(os.path.join(work, "projects", k2, CS4 + ".jsonl"))
          and os.path.exists(tx1) and os.path.exists(tx2), "--project moves only that folder's sessions")

    pre = cli_hash(True)
    rc, out = crun("rehome", "cli")
    check(rc == 0 and cli_hash(True) == pre and "lists every session" in out and "move cli" in out,
          "rehome cli explains the CLI's model and changes nothing")

    rc, out = crun("register", "acct-cli-desk", "--cli-session-id", CS4[:8])
    check(rc != 0 and "move cli:work --to-profile cli" in out,
          "register refuses a conversation in another home and prints the move that brings it there")

    desk2 = profile(ch, "acct-cli-desk2", logs=[init("09:00:00", B, OB)])
    rec(os.path.join(desk2, "claude-code-sessions", B, OB), "cs4desk", "desk", cliSessionId=CS4)
    rc, out = crun("sessions", "acct-cli-desk2")
    check(rc == 0 and "in cli:work" in out and "transcript MISSING" not in out,
          "a record whose transcript lives in cli:work shows 'in cli:work', not 'transcript MISSING'")

    print("CLI moves that fail part-way, partial states, and rollback")
    # Failures are real where a test can make them (a read-only folder, a file-size limit) and otherwise come from
    # CCD_REHOME_FAULT, a test-only switch the tool honours only in its sandbox: exdev, short-copy:N, fail-after:N,
    # kill-after:N, kill-in-copy:N, appear:N (see the tool's _faults()).
    proj3 = os.path.join(ch, "Projects", "gamma"); os.makedirs(proj3)
    rp3 = os.path.realpath(proj3)
    k3 = cr2.mangle(rp3)
    CS5 = "e5e5e5e5-0000-4000-8000-000000000105"
    CS6 = "e6e6e6e6-0000-4000-8000-000000000106"
    CS7 = "e7e7e7e7-0000-4000-8000-000000000107"
    ARCH_NAME = re.compile(r"\d{8}T\d{6}Z-cli-move")

    def put(path, data):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data.encode("utf-8") if isinstance(data, str) else data)
        return path

    def items_of(base, key, sid):
        """The five per-session paths a move carries, in the tool's order."""
        return [os.path.join(base, "projects", key, sid + ".jsonl"), os.path.join(base, "projects", key, sid),
                os.path.join(base, "tasks", sid), os.path.join(base, "file-history", sid),
                os.path.join(base, "todos", sid + "-agent-" + sid + ".json")]

    def tmp_left(*bases):
        return [os.path.join(dp, n) for b in bases for dp, dn, fn in os.walk(b) for n in dn + fn
                if ".rehome-tmp-" in n]

    def arch_in(out):
        m = ARCH_NAME.search(out)
        return m.group(0) if m else "none"

    def discard(*paths):
        for p in paths:
            if os.path.isdir(p) and not os.path.islink(p):
                shutil.rmtree(p)
            elif os.path.lexists(p):
                os.remove(p)

    def rmdirs_if_empty(*dirs):
        for d in dirs:
            if os.path.isdir(d) and not os.listdir(d):
                os.rmdir(d)

    def mtime_ns(p):
        return os.stat(p).st_mtime_ns if os.path.exists(p) else None

    def readb(p):
        return open(p, "rb").read() if os.path.isfile(p) else None

    def append_turn(p, sid, text):
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps({"type": "user", "uuid": "u-" + text[:4], "cwd": rp3, "sessionId": sid,
                                "message": {"role": "user", "content": text}}) + "\n")

    def mtime_age(p):
        return abs(os.path.getmtime(p) - time.time()) if os.path.exists(p) else 1e9

    tx5 = cli_transcript(cdef, k3, CS5, rp3, title="Gamma one")
    put(os.path.join(cdef, "projects", k3, CS5, "subagents", "agent.jsonl"), "{}\n")
    put(os.path.join(cdef, "tasks", CS5, "1.json"), "{}")
    put(os.path.join(cdef, "file-history", CS5, "v1"), "v1")
    put(os.path.join(cdef, "file-history", CS5, "big"), b"x" * (200 * 1024))   # over the file-size limit below
    put(os.path.join(cdef, "todos", CS5 + "-agent-" + CS5 + ".json"), "[]")
    tx6 = cli_transcript(cdef, k3, CS6, rp3, title="Gamma two")
    put(os.path.join(cdef, "projects", k3, "memory", "MEMORY.md"), "gamma memory")
    old5 = time.time() - 60 * 86400                     # older than cli:work's 45 days: the move re-dates it
    os.utime(tx5, (old5, old5))
    mt5 = os.stat(tx5).st_mtime_ns
    saved5 = open(tx5, "rb").read()
    i5, w5 = items_of(cdef, k3, CS5), items_of(work, k3, CS5)
    i6, w6 = items_of(cdef, k3, CS6), items_of(work, k3, CS6)
    wmem3 = os.path.join(work, "projects", k3, "memory", "MEMORY.md")
    work_parents = [os.path.join(work, d) for d in ("tasks", "file-history", "todos")]
    work_parents_new = [d for d in work_parents if not os.path.isdir(d)]
    base0 = cli_hash()

    def mv5(*extra, env=None, pre=None):
        return crun("move", "cli", "--only", CS5[:8], "--to-profile", "cli:work", *extra, env=env, pre=pre)

    pre = cli_hash(True)
    rc, out = mv5(env={"CCD_REHOME_FAULT": "fail-after:2"})
    check(rc == 1 and cli_hash(True) == pre and "undone" in out and "nothing was changed" in out.lower()
          and "Traceback" not in out,
          "a move that fails at its 3rd of 5 items is undone: the moved items go back, its archive is removed, and the "
          "message says so (no traceback)")
    rc, out = mv5(env={"CCD_REHOME_FAULT": "fail-after:5"})
    check(rc == 1 and cli_hash(True) == pre and mtime_ns(tx5) == mt5 and "undone" in out,
          "a move that fails at its memory copy, after every item moved and the old transcript was re-dated, is undone "
          "with the original mtime")

    rc, out = mv5(env={"CCD_REHOME_FAULT": "kill-after:0"})
    karch = arch_in(out)
    check(rc != 0 and karch != "none" and cli_hash() == base0,
          "the archive name is printed before the first change (a run killed just before it already names it)")
    rc, out = crun("rollback", "cli", karch)
    check(rc == 0 and cli_hash() == base0, "rollback of a move that was killed before its first change changes nothing")

    rc, out = mv5(env={"CCD_REHOME_FAULT": "kill-after:2"})
    karch = arch_in(out)
    split = all(os.path.lexists(p) for p in w5[:2] + i5[2:]) and not any(os.path.lexists(p) for p in i5[:2] + w5[2:])
    check(rc != 0 and karch != "none" and split,
          "(fixture) a move killed after 2 of 5 items leaves the session split between the two homes")
    shutil.copytree(w5[1], i5[1])                       # the sidecar folder is now in both homes
    pre = cli_hash(True)
    rc, out = crun("rollback", "cli", karch)
    check(rc == 1 and cli_hash(True) == pre and "both" in out,
          "rollback refuses when an item is in both homes, and changes nothing")
    shutil.rmtree(i5[1])
    rc, out = crun("rollback", "cli", karch)
    check(rc == 0 and cli_hash() == base0,
          "rollback of a cut-off move moves back what reached cli:work, skips what never left cli: exactly as before")

    rc, out = mv5(env={"CCD_REHOME_FAULT": "exdev"})
    xarch = arch_in(out)
    check(rc == 0 and all(os.path.lexists(p) for p in w5) and not any(os.path.lexists(p) for p in i5)
          and readb(w5[0]) == saved5 and "EXDEV" in out and not tmp_left(work, cdef),
          "a rename that fails with EXDEV (two mounts of one filesystem) falls back to copy, verify, remove, and says so")
    check(mtime_age(w5[0]) < 120, "(fixture) the old transcript was re-dated in cli:work")
    rc, out = crun("rollback", "cli:work", xarch, env={"CCD_REHOME_FAULT": "exdev"})
    check(rc == 0 and cli_hash() == base0 and not tmp_left(work, cdef),
          "its rollback, across the same EXDEV, restores every home exactly")
    check(mtime_ns(tx5) == mt5, "rollback gives a re-dated transcript its original mtime back")

    rc, out = mv5(env={"CCD_REHOME_FAULT": "exdev,kill-in-copy:0"})
    karch = arch_in(out)
    rc2, out2 = crun("sessions", "cli:work")
    check(rc != 0 and not os.path.lexists(w5[0]) and tmp_left(work) and rc2 == 0 and CS5[:8] not in out2,
          "a run killed in the middle of copying a transcript across devices leaves it only under a temporary name: "
          "cli:work does not list a half-copied session")
    rc, out = crun("rollback", "cli", karch)
    check(rc == 0 and cli_hash() == base0 and not tmp_left(work, cdef) and "partial copy" in out,
          "its rollback removes the partial copy: exactly as before")
    rc, out = mv5(env={"CCD_REHOME_FAULT": "exdev,kill-in-copy:3"})
    karch = arch_in(out)
    check(rc != 0 and not os.path.lexists(w5[3]) and os.path.lexists(w5[2]) and tmp_left(work),
          "(fixture) killed while copying the 4th item: 3 items are in cli:work, the 4th only under a temporary name")
    rc, out = crun("rollback", "cli", karch)
    check(rc == 0 and cli_hash() == base0 and not tmp_left(work, cdef) and "partial copy" in out,
          "its rollback moves back the 3 items and removes the partial copy: exactly as before")
    rc, out = mv5(env={"CCD_REHOME_FAULT": "exdev,kill-in-copy:5"})
    karch = arch_in(out)
    check(rc != 0 and not os.path.exists(wmem3) and tmp_left(work),
          "(fixture) killed while copying the memory file: it is only under a temporary name")
    rc, out = crun("rollback", "cli", karch)
    check(rc == 0 and cli_hash() == base0 and not tmp_left(work, cdef),
          "its rollback moves the 5 items back and removes the partial memory copy too: exactly as before")

    pre = cli_hash(True)
    rc, out = mv5(env={"CCD_REHOME_FAULT": "exdev,short-copy:2"})
    check(rc == 1 and cli_hash(True) == pre and "verif" in out.lower() and "undone" in out and not tmp_left(work, cdef),
          "a cross-device copy that does not match its source never gets its real name: the partial copy is removed, "
          "the two items copied before it go back, nothing is changed")

    rc, out = mv5(env={"CCD_REHOME_FAULT": "exdev,appear:2"})
    foreign = os.path.isdir(w5[2]) and not os.listdir(w5[2])
    check(rc == 1 and foreign and all(os.path.lexists(p) for p in i5) and readb(tx5) == saved5
          and "appeared" in out and not tmp_left(work, cdef),
          "a destination another process creates during the copy is not ours: the move stops, the undo leaves it "
          "alone and the source is intact")
    discard(w5[2]); rmdirs_if_empty(*work_parents_new)
    check(cli_hash(True) == pre, "(fixture) and apart from that folder, nothing was changed")

    if os.name != "nt":
        import resource, signal

        def fsize_limit():
            signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
            resource.setrlimit(resource.RLIMIT_FSIZE, (64 * 1024, 64 * 1024))
        pre = cli_hash(True)
        rc, out = mv5(env={"CCD_REHOME_FAULT": "exdev"}, pre=fsize_limit)
        check(rc == 1 and cli_hash(True) == pre and "undone" in out and not tmp_left(work, cdef)
              and "Traceback" not in out,
              "a cross-device copy cut short by a real write error (a file-size limit, like a full disk) is removed, "
              "the items before it go back, nothing is changed")
    if os.name != "nt" and os.geteuid() != 0:
        ro = os.path.join(work, "file-history")
        made = not os.path.isdir(ro)
        os.makedirs(ro, exist_ok=True)
        mode0 = os.stat(ro).st_mode & 0o7777
        os.chmod(ro, 0o500)
        try:
            pre = cli_hash(True)
            rc, out = mv5()
            ok = rc == 1 and cli_hash(True) == pre and "undone" in out and "Traceback" not in out
        finally:
            os.chmod(ro, mode0)
            if made:
                os.rmdir(ro)
        check(ok, "a rename the target refuses (a read-only cli:work/file-history) is undone: no split session, "
                  "nothing changed")

    rc, out = crun("move", "cli", "--only", CS6[:8], "--to-profile", "cli:work",
                   env={"CCD_REHOME_OPEN_FILES": tx6})
    check(rc == 1 and "open in another process" in out and os.path.exists(tx6),
          "move refuses a transcript another process holds open (the sandbox's simulated process check)")

    rc, out = mv5()
    arch5 = arch_in(out)
    check(rc == 0 and all(os.path.lexists(p) for p in w5), "(fixture) the move of the five-item session completes")
    deskw = profile(ch, "acct-cli-deskw", logs=[init("09:00:00", B, OB)])
    rec(os.path.join(deskw, "claude-code-sessions", B, OB), "cs5desk", "desk", cliSessionId=CS5)
    pre = cli_hash(True)
    rc, out = crun("rollback", "cli:work", arch5, "--dry-run")
    check(rc == 0 and cli_hash(True) == pre and "acct-cli-deskw" in out and "REFUSE" not in out
          and "dry run" in out,
          "a rollback back INTO ~/.claude is not refused while a Desktop profile whose records' transcripts are all in "
          "cli:work shows the session (dry run: a note names the profile, nothing written)")
    shutil.rmtree(deskw)
    wreg = put(os.path.join(work, "sessions", "33333.json"),
               json.dumps({"pid": 33333, "sessionId": CS5, "cwd": rp3, "status": "active"}))
    pre = cli_hash(True)
    rc, out = crun("rollback", "cli:work", arch5, env={"CCD_REHOME_LIVE_PIDS": "33333"})
    check(rc == 1 and cli_hash(True) == pre and "OPEN in cli:work" in out,
          "rollback refuses while the session is OPEN in cli:work (a live sessions/<pid>.json)")
    os.remove(wreg); rmdirs_if_empty(os.path.dirname(wreg))
    pre = cli_hash(True)
    rc, out = crun("rollback", "cli:work", arch5, env={"CCD_REHOME_OPEN_FILES": w5[0]})
    check(rc == 1 and cli_hash(True) == pre and "open in another process" in out,
          "rollback refuses while another process holds the transcript open in cli:work (not only a registry entry)")
    rc, out = crun("rollback", "cli:work", arch5, env={"CCD_REHOME_FAULT": "fail-after:2"})
    check(rc == 1 and "again" in out and "Traceback" not in out and os.path.exists(tx5) and os.path.lexists(w5[2]),
          "a rollback that fails part-way says what to do (run it again)")
    pre = cli_hash(True)
    rc, out = crun("rollback", "cli:work", arch5, "--dry-run")
    check(rc == 0 and cli_hash(True) == pre and "[dry-run] move back" in out and "still in cli" in out
          and "remove copied memory" in out,
          "rollback --dry-run of that half-done rollback shows what it would move back, skip and remove, and writes "
          "nothing")
    rc, out = crun("rollback", "cli:work", arch5)
    check(rc == 0 and cli_hash() == base0 and mtime_ns(tx5) == mt5,
          "running the same rollback again finishes it: every home exactly as before, the transcript's mtime included")

    saved6 = readb(tx6)
    rc, out = crun("move", "cli", "--only", CS6[:8], "--to-profile", "cli:work")
    arch6 = arch_in(out)
    check(rc == 0 and os.path.exists(w6[0]) and not any(os.path.lexists(p) for p in w6[1:]),
          "(fixture) a transcript-only session moves")
    append_turn(w6[0], CS6, "continued in cli:work")
    put(os.path.join(w6[1], "tool-results", "toolu_1.txt"), "result")
    put(os.path.join(w6[2], "1.json"), "{}")
    put(os.path.join(w6[3], "f@v1"), "v1")
    put(w6[4], "[]")
    grown = readb(w6[0])
    rc, out = crun("rollback", "cli:work", arch6)
    check(rc == 0 and all(os.path.lexists(p) for p in i6) and not any(os.path.lexists(p) for p in w6)
          and readb(tx6) == grown,
          "rollback also brings back what the session gained in cli:work after the move (sidecar, tasks, file history, "
          "todos), and the grown transcript as it is now")
    discard(*i6[1:]); put(tx6, saved6 or b""); rmdirs_if_empty(*work_parents_new)
    check(cli_hash() == base0, "(fixture) back to the state before these checks")

    rc, out = mv5("--copy")
    archc5 = arch_in(out)
    append_turn(w5[0], CS5, "the copy goes on")
    rc, out = crun("rollback", "cli:work", archc5)
    check(rc == 0 and all(os.path.lexists(p) for p in w5) and os.path.exists(wmem3) and "kept" in out
          and all(os.path.lexists(p) for p in i5),
          "rollback of a --copy move keeps the whole session copy (sidecar, tasks, file history, todos, memory) when "
          "any part of it changed")
    discard(*w5); discard(wmem3)
    rmdirs_if_empty(os.path.dirname(wmem3), os.path.dirname(w5[0]), *work_parents_new)
    check(cli_hash() == base0, "(fixture) back to the state before these checks")

    rc, out = mv5()
    r1 = arch_in(out)
    rc2, out2 = crun("move", "cli", "--only", CS6[:8], "--to-profile", "cli:work")
    r2 = arch_in(out2)
    check(rc == 0 and rc2 == 0 and "same projects" in out2, "(fixture) a second move of the project finds the memory there")
    rc, out = crun("rollback", "cli", r1)
    check(rc == 0 and os.path.exists(wmem3) and os.path.exists(w6[0]) and "kept copied memory" in out and CS6[:8] in out,
          "rolling back the first move keeps the project memory that a later-moved session (still in cli:work) uses, "
          "and says so")
    rc, out = crun("rollback", "cli", r2)
    discard(wmem3); rmdirs_if_empty(os.path.dirname(wmem3), os.path.dirname(w5[0]))
    rc, out = mv5()
    r1 = arch_in(out)
    rc2, out2 = crun("move", "cli", "--only", CS6[:8], "--to-profile", "cli:work")
    r2 = arch_in(out2)
    rc3, _ = crun("rollback", "cli", r2)
    rc4, _ = crun("rollback", "cli", r1)
    check(rc == rc2 == rc3 == rc4 == 0 and cli_hash() == base0,
          "undone newest first, the two moves leave every home exactly as before (the copied memory removed)")

    put(os.path.join(cdef, "projects", k2, "memory", "B.md"), "beta memory")
    cli_transcript(cdef, k2, CS7, os.path.realpath(proj2), title="Beta two")
    w7fh = put(os.path.join(work, "file-history", CS7, "pre"), "what cli:work had of it before")
    pre = cli_hash()
    rc, out = crun("move", "cli", "--only", CS7[:8], "--to-profile", "cli:work")
    a7 = arch_in(out)
    check(rc == 0 and os.path.exists(os.path.join(work, "projects", k2, "memory", "B.md")),
          "(fixture) the memory is copied next to a session that was already in cli:work")
    rc, out = crun("rollback", "cli", a7)
    check(rc == 0 and not os.path.exists(os.path.join(work, "projects", k2, "memory", "B.md")),
          "a session that was in cli:work BEFORE the move does not keep the copied memory")
    check(rc == 0 and os.path.exists(w7fh) and not os.path.exists(os.path.join(cdef, "file-history", CS7))
          and cli_hash() == pre,
          "what cli:work had of the session before the move stays there: the undo stays exact")

    print("CLI moves: which sessions, symlinks, glob characters and refusals")
    proj4 = os.path.join(ch, "Projects", "delta"); os.makedirs(proj4)
    rp4 = os.path.realpath(proj4)
    k4 = cr2.mangle(rp4)
    S8 = "e8e8e8e8-0000-4000-8000-000000000108"
    S9 = "e9e9e9e9-0000-4000-8000-000000000109"
    S10 = "eaeaeaea-0000-4000-8000-000000000110"
    S11 = "ebebebeb-0000-4000-8000-000000000111"
    S12 = "ecececec-0000-4000-8000-000000000112"
    S13 = "edededed-0000-4000-8000-000000000113"
    S14 = "eeeeeeee-0000-4000-8000-000000000114"
    S15 = "efefefef-0000-4000-8000-000000000115"
    S16 = "f0f0f0f0-0000-4000-8000-000000000116"
    S17 = "f1f1f1f1-0000-4000-8000-000000000117"

    def can_link(target, link, is_dir=True):
        try:
            os.symlink(target, link, target_is_directory=is_dir); return True
        except (OSError, NotImplementedError):
            return False

    def files_under(*bases):
        return [os.path.join(dp, f) for b in bases for dp, _, fn in os.walk(b) for f in fn]

    def moves_listed(out):
        return re.findall(r"^    (?:move|copy) (\S+)", out, re.M)

    def undo(rc, out, where="cli"):
        """A move that should have refused but went ahead (a broken tool) is rolled back, so that each check below
        still tests what it says instead of failing because of the one before it."""
        if rc == 0 and arch_in(out) != "none":
            crun("rollback", where, arch_in(out))

    # A symlinked project folder (the usual workaround after renaming a repo) reaches one transcript under two keys.
    cli_transcript(cdef, k4, S8, rp4, title="Delta, reached twice")
    put(os.path.join(cdef, "projects", k4, S8, "subagents", "agent.jsonl"), "{}\n")
    put(os.path.join(cdef, "tasks", S8, "1.json"), "{}")
    put(os.path.join(cdef, "file-history", S8, "v1"), "v1")
    put(os.path.join(cdef, "todos", S8 + "-agent-" + S8 + ".json"), "[]")
    i8, w8 = items_of(cdef, k4, S8), items_of(work, k4, S8)
    alias = os.path.join(cdef, "projects", k4 + "-renamed")
    if can_link(k4, alias):
        rows = [r for r in cj("sessions", "cli")["sessions"] if r["id"] == S8]
        check(len(rows) == 1 and rows[0]["cwd"] == rp4,
              "a transcript reached through a symlinked project folder (a renamed repo's alias) is one session, "
              "not two")
        pre = tree_hash(ch)
        rc, out = crun("move", "cli", "--only", S8[:8], "--to-profile", "cli:work", "--dry-run")
        listed = moves_listed(out)
        check(rc == 0 and tree_hash(ch) == pre and len(listed) == 5 and len(set(listed)) == 5
              and not any("-renamed" in x for x in listed),
              "--only selects it, and its dry run lists each of its 5 items once, none under the alias")
        pre = cli_hash()
        rc, out = crun("move", "cli", "--project", proj4, "--to-profile", "cli:work")
        a8 = arch_in(out)
        check(rc == 0 and "1 session(s)" in out and all(os.path.lexists(p) for p in w8)
              and not any(os.path.lexists(p) for p in i8)
              and not os.path.lexists(os.path.join(work, "projects", k4 + "-renamed")) and "Traceback" not in out,
              "--project moves it once: every item lands in cli:work under the real folder name, none under the alias")
        rc, out = crun("rollback", "cli:work", a8)
        check(rc == 0 and cli_hash() == pre and os.path.islink(alias),
              "its rollback restores every home exactly (the alias link untouched)")
        os.remove(alias)
        # A project folder that is a symlink to a folder that is not itself a project folder: nothing to dedupe it
        # with, so the move refuses rather than move the files out from under the link.
        real9 = os.path.join(cdef, "kept-elsewhere", "delta"); os.makedirs(real9)
        tmp9 = cli_transcript(os.path.join(ch, "tmp9"), "k", S9, rp4, title="Behind a link")
        os.rename(tmp9, os.path.join(real9, S9 + ".jsonl")); shutil.rmtree(os.path.join(ch, "tmp9"))
        link9 = os.path.join(cdef, "projects", k4 + "-linked")
        os.symlink(real9, link9, target_is_directory=True)
        pre = cli_hash(True)
        rc, out = crun("move", "cli", "--only", S9[:8], "--to-profile", "cli:work")
        check(rc == 1 and cli_hash(True) == pre and "symlink" in out and "undone" not in out
              and "Traceback" not in out,
              "a transcript whose project folder is a symlink (to a folder inside the home) is refused up front: "
              "nothing is written")
        undo(rc, out)
        os.remove(link9); shutil.rmtree(os.path.join(cdef, "kept-elsewhere"))
    else:
        print("  (skipped symlinked-project-folder checks: this OS/user cannot create symlinks)")
    discard(*i8); rmdirs_if_empty(os.path.join(cdef, "projects", k4))

    # The same id under two REAL project folders (Claude Code itself cannot resume it by id there).
    t10a = cli_transcript(cdef, k4, S10, rp4, title="Pinned twice")
    t10b = cli_transcript(cdef, k4 + "-pinned", S10, rp4, title="Pinned twice, other copy")
    put(os.path.join(cdef, "tasks", S10, "1.json"), "{}")
    pre = tree_hash(ch)
    rc, out = crun("move", "cli", "--project", proj4, "--to-profile", "cli:work", "--dry-run")
    check(rc == 1 and tree_hash(ch) == pre and "2 project folders" in out and k4 + "-pinned" in out
          and out.count("tasks" + os.sep + S10) == 0,
          "dry run: an id with a transcript in two project folders of the source is refused (both named), and its "
          "shared tasks/ are not planned twice")
    pre = cli_hash(True)
    rc, out = crun("move", "cli", "--project", proj4, "--to-profile", "cli:work")
    check(rc == 1 and cli_hash(True) == pre and "2 project folders" in out and "undone" not in out
          and "Traceback" not in out
          and not glob.glob(os.path.join(glob.escape(work), "projects", "*", S10 + ".jsonl")),
          "the real move refuses it up front (no archive, no half move, no duplicate id in cli:work)")
    rc, out = crun("move", "cli", "--only", S10[:8], "--to-profile", "cli:work")
    check(rc == 1 and cli_hash(True) == pre and "2 project folders" in out and "matches 2" not in out,
          "--only with that id gives the same refusal (not 'matches 2 sessions')")
    rc, out = crun("move", "cli", "--to-profile", "cli:work", "--dry-run")
    check(rc == 1 and out.count("REFUSE " + S10[:8]) == 1, "a move of every session names that refusal once")
    discard(t10a, t10b, os.path.join(cdef, "tasks", S10))
    rmdirs_if_empty(os.path.join(cdef, "projects", k4), os.path.join(cdef, "projects", k4 + "-pinned"))

    # Home paths with glob characters ([ ] * ?) are paths, not patterns.
    gw = os.path.join(ch, "homes", "work[1]")
    os.makedirs(os.path.join(gw, "projects"))
    cli_transcript(gw, k4 + "-other", S11, rp4, title="Glob target's own copy")
    t11 = cli_transcript(cdef, k4, S11, rp4, title="Glob source")
    rows = cj("sessions", gw)["sessions"]
    check([r["id"] for r in rows] == [S11], "sessions of a home whose path has [ and ] lists its transcript")
    pre = cli_hash(True)
    rc, out = crun("move", "cli", "--only", S11[:8], "--to-profile", gw)
    check(rc == 1 and cli_hash(True) == pre and "DIFFERENT transcript" in out,
          "a target whose path has [ and ] still refuses a different transcript with the same id (no duplicate id)")
    undo(rc, out)
    check(any(r.get("cli") == S11 and r.get("home_path") == os.path.realpath(gw) for r in cj("cli-sessions")),
          "cli-sessions lists the conversation of that home")
    discard(t11)
    t16 = cli_transcript(cdef, k4, S16, rp4, title="Glob memory one")
    t17 = cli_transcript(cdef, k4, S17, rp4, title="Glob memory two")
    m4 = put(os.path.join(cdef, "projects", k4, "memory", "M.md"), "delta memory")
    gm4 = os.path.join(gw, "projects", k4, "memory", "M.md")
    rc, out = crun("move", "cli", "--only", S16[:8], "--to-profile", gw)
    a16 = arch_in(out)
    rc2, out2 = crun("move", "cli", "--only", S17[:8], "--to-profile", gw)
    a17 = arch_in(out2)
    rc3, out3 = crun("rollback", "cli", a16)
    check(rc == rc2 == rc3 == 0 and os.path.exists(gm4) and "kept copied memory" in out3 and S17[:8] in out3,
          "rolling back the first of two moves into such a home keeps the memory the later-moved session uses there")
    crun("rollback", "cli", a17)
    discard(t16, t17, os.path.dirname(m4), gw); rmdirs_if_empty(os.path.join(cdef, "projects", k4))
    gs = os.path.join(ch, "homes", "src[1]" if os.name == "nt" else "src[1]?")   # no '?' in a Windows file name
    t12 = cli_transcript(gs, k4, S12, rp4, title="Glob source home")
    side12 = put(os.path.join(gs, "projects", k4 + "-wt", S12, "subagents", "a.jsonl"), "{}\n")
    todo12 = put(os.path.join(gs, "todos", S12 + "-agent-" + S12 + ".json"), "[]")
    reg12 = put(os.path.join(gs, "sessions", "77777.json"),
                json.dumps({"pid": 77777, "sessionId": S12, "cwd": rp4, "status": "active"}))
    rc, out = crun("sessions", gs)
    check(rc == 0 and S12[:8] in out, "(fixture) a source home whose path has glob characters lists its session")
    pre = cli_hash(True)
    rc, out = crun("move", gs, "--only", S12[:8], "--to-profile", "cli:work", env={"CCD_REHOME_LIVE_PIDS": "77777"})
    check(rc == 1 and cli_hash(True) == pre and "OPEN" in out,
          "a session OPEN in such a home is refused (its sessions/<pid>.json is found)")
    os.remove(reg12)
    pre = cli_hash(True)
    rc, out = crun("move", gs, "--only", S12[:8], "--to-profile", "cli:work", env={"CCD_REHOME_OPEN_FILES": t12})
    check(rc == 1 and cli_hash(True) == pre and "open in another process" in out,
          "a transcript another process holds open in such a home is refused (the transcript is found)")
    pre = cli_hash()
    rc, out = crun("move", gs, "--only", S12[:8], "--to-profile", "cli:work")
    a12 = arch_in(out)
    check(rc == 0 and os.path.exists(os.path.join(work, "projects", k4, S12 + ".jsonl"))
          and os.path.isdir(os.path.join(work, "projects", k4 + "-wt", S12))
          and os.path.exists(os.path.join(work, "todos", S12 + "-agent-" + S12 + ".json"))
          and not any(os.path.lexists(p) for p in (t12, os.path.dirname(os.path.dirname(side12)), todo12)),
          "a move from such a home carries its sibling-key sidecar and its todos too")
    rc, out = crun("rollback", gs, a12)
    check(rc == 0 and cli_hash() == pre, "and its rollback restores both homes exactly")
    discard(gs)
    odd = profile(ch, os.path.join(ch, "odd[1]", "Claude"), logs=[init("09:00:00", A, OA)])
    rec(os.path.join(odd, "claude-code-sessions", A, OA), "odd1", "A record in an odd[1] window")
    rc, out = crun("sessions", odd)
    check(rc == 0 and "A record in an odd[1] window" in out,
          "a Desktop profile whose path has [ and ] lists its records too")
    discard(os.path.dirname(odd))

    # Project memory: a symlinked memory folder is refused, never followed, never read.
    proj5 = os.path.join(ch, "Projects", "epsilon"); os.makedirs(proj5)
    rp5 = os.path.realpath(proj5)
    k5 = cr2.mangle(rp5)
    t13 = cli_transcript(cdef, k5, S13, rp5, title="Memory behind a link")
    outside = os.path.join(ch, "outside-memory")
    secret = put(os.path.join(outside, "SECRET-OUTSIDE.md"), "OUTSIDE-DECOY-ddd")
    m5 = os.path.join(cdef, "projects", k5, "memory")
    w13 = os.path.join(work, "projects", k5)
    if can_link(outside, m5):
        pre = tree_hash(ch)
        rc, out = crun("move", "cli", "--only", S13[:8], "--to-profile", "cli:work", "--dry-run")
        check(rc == 1 and tree_hash(ch) == pre and "symlink" in out and "SECRET-OUTSIDE" not in out,
              "dry run: a project memory folder that is a symlink (to a folder outside every home) is refused; "
              "nothing in it is listed")
        pre = cli_hash(True)
        rc, out = crun("move", "cli", "--only", S13[:8], "--to-profile", "cli:work")
        check(rc == 1 and cli_hash(True) == pre and "--no-memory" in out
              and not any("OUTSIDE-DECOY" in open(f, encoding="utf-8", errors="replace").read()
                          for f in files_under(work)),
              "the real move refuses it, copies nothing, and says --no-memory moves the session without it")
        undo(rc, out)
        if os.name != "nt" and os.geteuid() != 0:
            os.chmod(secret, 0)
            try:
                rc, out = crun("move", "cli", "--only", S13[:8], "--to-profile", "cli:work", "--dry-run")
            finally:
                os.chmod(secret, 0o600)
            check(rc == 1 and "symlink" in out and "Traceback" not in out and "ermission" not in out,
                  "the linked folder is never read: an unreadable file in it does not reach the tool")
        pre = cli_hash()
        rc, out = crun("move", "cli", "--only", S13[:8], "--to-profile", "cli:work", "--no-memory")
        a13 = arch_in(out)
        check(rc == 0 and os.path.exists(os.path.join(w13, S13 + ".jsonl"))
              and not os.path.lexists(os.path.join(w13, "memory")),
              "--no-memory moves the session and leaves the linked memory alone")
        rc, out = crun("rollback", "cli", a13)
        check(rc == 0 and cli_hash() == pre, "(fixture) rolled back exactly")
        os.remove(m5); os.symlink(cdef, m5, target_is_directory=True)
        pre = cli_hash(True)
        rc, out = crun("move", "cli", "--only", S13[:8], "--to-profile", "cli:work", "--copy")
        check(rc == 1 and cli_hash(True) == pre and ".credentials.json" not in out and "history.jsonl" not in out
              and ".key" not in out,
              "a memory folder linked to the home itself (inside it) is refused too: .credentials.json, "
              "sessions/*.key and history.jsonl are never listed or copied")
        undo(rc, out)
        os.remove(m5); os.makedirs(m5)
        put(os.path.join(m5, "MEMORY.md"), "epsilon memory")
        os.symlink(outside, os.path.join(m5, "sub"), target_is_directory=True)
        pre = cli_hash(True)
        rc, out = crun("move", "cli", "--only", S13[:8], "--to-profile", "cli:work")
        check(rc == 1 and cli_hash(True) == pre and "symlink" in out
              and disp(".claude", "projects", k5, "memory", "sub") in out,
              "a symlinked folder inside the project memory is refused, not skipped silently")
        undo(rc, out)
        os.remove(os.path.join(m5, "sub"))
        os.symlink(secret, os.path.join(m5, "LINK.md"))
        pre = cli_hash(True)
        rc, out = crun("move", "cli", "--only", S13[:8], "--to-profile", "cli:work")
        check(rc == 1 and cli_hash(True) == pre and "LINK.md is a symlink" in out,
              "a symlinked file in the project memory is refused (as before)")
        undo(rc, out)
        os.remove(os.path.join(m5, "LINK.md"))
    else:
        print("  (skipped memory symlink checks: this OS/user cannot create symlinks)")
    discard(m5, t13, outside); rmdirs_if_empty(os.path.join(cdef, "projects", k5))

    # A sessions/<pid>.json that is not a JSON object (a truncated or foreign write) is skipped, never a crash.
    junk = [put(os.path.join(cdef, "sessions", n + ".json"), body)
            for n, body in (("123", "null"), ("124", "[]"), ("125", '"x"'), ("126", "7"))]
    for cmd in (("status",), ("profiles",), ("sessions", "cli")):
        rc, out = crun(*cmd)
        check(rc == 0 and "Traceback" not in out and (cmd[0] == "sessions" or "acct-cli-desk" in out),
              f"{' '.join(cmd)}: a sessions/<pid>.json holding null, [], a string or a number is skipped, and "
              f"every row still shows")
    discard(*junk)

    # A dry run that finds a refusal must say the real run would REFUSE, and exit 1 as the real run does.
    proj6 = os.path.join(ch, "Projects", "zeta"); os.makedirs(proj6)
    rp6 = os.path.realpath(proj6)
    k6 = cr2.mangle(rp6)
    t14 = cli_transcript(cdef, k6, S14, rp6, title="Zeta free")
    t15 = cli_transcript(cdef, k6, S15, rp6, title="Zeta open")
    reg15 = put(os.path.join(cdef, "sessions", "88888.json"),
                json.dumps({"pid": 88888, "sessionId": S15, "cwd": rp6, "status": "active"}))
    live15 = {"CCD_REHOME_LIVE_PIDS": "88888"}
    pre = tree_hash(ch)
    rc, out = crun("move", "cli", "--project", proj6, "--to-profile", "cli:work", "--dry-run", env=live15)
    check(rc == 1 and tree_hash(ch) == pre and S14[:8] in out and "REFUSE " + S15[:8] in out
          and "would REFUSE" in out and "would do the above" not in out,
          "a dry run that finds a refusal shows the plan and the REFUSE line, says the real run would REFUSE, and "
          "exits 1 (as the real run does)")
    rc, out = crun("move", "cli", "--only", S15[:8], "--to-profile", "cli:work", "--dry-run", env=live15)
    check(rc == 1 and tree_hash(ch) == pre and "would REFUSE" in out and "nothing to move" not in out,
          "a dry run whose only session is refused exits 1 too (not 'nothing to move')")
    pre = cli_hash(True)
    rc, out = crun("move", "cli", "--project", proj6, "--to-profile", "cli:work", env=live15)
    check(rc == 1 and cli_hash(True) == pre and "refusing" in out and os.path.exists(t14),
          "the real run refuses the same move (nothing moved)")
    pre = tree_hash(ch)
    rc, out = crun("move", "cli", "--project", proj6, "--to-profile", "cli:work", "--dry-run")
    check(rc == 0 and tree_hash(ch) == pre and "would do the above" in out and "REFUSE" not in out,
          "without the refusal the same dry run exits 0 and says the real run would do the above")
    discard(t14, t15, reg15); rmdirs_if_empty(os.path.join(cdef, "projects", k6))

    check(not any("DECOY-CREDENTIAL-xyz" in o or "KEY-SECRET-xyz" in o or "OUTSIDE-DECOY" in o for o in outputs),
          "no output of these sections ever contains the credentials, session-key or outside-memory contents")

    print("Desktop windows and CLI homes: every window taken to read ~/.claude, records that keep a session there, "
          "shadowed names")
    # Desktop reads CLAUDE_CONFIG_DIR ?? ~/.claude, and nothing on disk says which one a window was started with, so
    # the tool takes every window to read ~/.claude. A home of its own: ~/.claude, ~/.claude-work, and
    # ~/.claude-backup, a copy of old transcripts that retention has since deleted from ~/.claude (found as
    # cli:backup, because it has projects/).
    dh = os.path.join(home, "desk-homes"); os.makedirs(dh)
    dstate = sdir(dh)

    def dhash(state=True):
        """The whole test home; with state=True the tool's state too (minus the account registry every real run
        refreshes): what a refusal must leave as it was. state=False: the homes and profiles only."""
        return tree_hash(dh, skip=os.path.join(dstate, "accounts.json") if state else dstate)

    def drun(*args, env=None):
        return run(dh, *args, env=dict({"PATH": fake + os.pathsep + os.environ.get("PATH", "")}, **(env or {})))

    def dundo(rc, out, where):
        """A move or rollback that should have refused but went ahead (a broken tool) is undone, so each check
        below still tests what it says."""
        if rc == 0 and arch_in(out) != "none" and "rolled back" not in out:
            drun("rollback", where, arch_in(out))

    ddef, dwork, dbak = (os.path.join(dh, n) for n in (".claude", ".claude-work", ".claude-backup"))
    for d in (ddef, dwork, dbak):
        os.makedirs(os.path.join(d, "projects"))
    for f in (os.path.join(dh, ".claude.json"), os.path.join(dwork, ".claude.json")):
        json.dump({"oauthAccount": {"accountUuid": A, "emailAddress": EMAIL[A], "organizationUuid": OA,
                                    "organizationName": "Org A"}}, open(f, "w", encoding="utf-8"))
    dproj = os.path.join(dh, "Projects", "delta"); os.makedirs(dproj)
    rpd = os.path.realpath(dproj)
    kd = cr2.mangle(rpd)
    O1, O2, O3 = ("d%dd%dd%dd%d-0000-4000-8000-00000000040%d" % ((n,) * 5) for n in (1, 2, 3))  # only in the backup
    S7, N8, S9 = ("d%dd%dd%dd%d-0000-4000-8000-00000000040%d" % ((n,) * 5) for n in (7, 8, 9))  # in ~/.claude
    W1, W2, W3, W4, W5, W6, W7 = ("9%d9%d9%d9%d-0000-4000-8000-00000000050%d" % ((n,) * 5)
                                  for n in range(1, 8))                     # in cli:work
    for sid in (O1, O2, O3):
        cli_transcript(dbak, kd, sid, rpd, title="old " + sid[:8])
    for sid in (S7, N8, S9):
        cli_transcript(ddef, kd, sid, rpd, title="default " + sid[:8])
    for sid in (W1, W2, W3, W4, W5, W6, W7):
        cli_transcript(dwork, kd, sid, rpd, title="work " + sid[:8])

    def desk(name, recs):
        p = profile(dh, name, signed_in=A, logs=[init("09:00:00", A, OA)])
        for rid, sid in recs:
            rec(os.path.join(p, "claude-code-sessions", A, OA), rid, "rec " + rid, cliSessionId=sid, cwd=rpd)
        return p
    # acct-d: three records whose transcripts are only in the backup, one in ~/.claude, one in cli:work.
    acct_d = desk("acct-d", [("do1", O1), ("do2", O2), ("do3", O3), ("ds9", S9), ("dw4", W4)])
    desk("acct-b", [("bo1", O1), ("bo2", O2)])                     # none in ~/.claude, two in the backup
    desk("acct-w", [("ww1", W1), ("ww2", W2), ("ww7", W7)])        # none in ~/.claude, three in cli:work
    desk("acct-m", [("ms7", S7), ("mw5", W5), ("mw6", W6)])        # one in ~/.claude, two in cli:work

    def desk_flags(spec):
        rc, out = drun("sessions", spec, "--json")
        try:
            return {r["id"]: r["desktop"] for r in json.loads(out)["sessions"]}
        except (ValueError, KeyError, TypeError):
            return {}

    fw, fb, fd = desk_flags("cli:work"), desk_flags("cli:backup"), desk_flags("cli")
    check(fw.get(W1) == ["acct-w"],
          "a profile whose records' transcripts are in cli:work and none in ~/.claude reads cli:work "
          "(sessions cli:work shows it on that session)")
    check(fw.get(W5) == [] and fd.get(S7) == ["acct-m"],
          "one record whose transcript is in ~/.claude outweighs two in cli:work: that profile reads ~/.claude")
    check(fb.get(O1) == ["acct-b"] and fd.get(S9) == ["acct-d"],
          "a backup home holding more of a profile's old transcripts never outvotes its record in ~/.claude; a profile "
          "with none in ~/.claude reads the backup")
    # Round 3: that inference is a display hint only (the `desktop:` flag above, and notes). Nothing on disk says
    # whether a window was started with CLAUDE_CONFIG_DIR, and a backup home fools the inference, so every rule below
    # takes each Desktop profile to read ~/.claude, Desktop's default.
    rc, out = drun("sessions", "acct-b")
    rc2, out2 = drun("sessions", "acct-d")
    check(rc == 0 and "cli:backup" in out and "CLAUDE_CONFIG_DIR=" + disp(".claude-backup") in out
          and "assumes" in out and rc2 == 0 and "assumes" not in out2,
          "sessions PROFILE says when none of a profile's records' transcripts is in ~/.claude and most are in another "
          "home (cli:backup), and that the tool still assumes ~/.claude; not for a profile with one in ~/.claude")

    pre = dhash()
    rc, out = drun("register", "acct-d", "--cli-session-id", N8[:8], "--dry-run")
    check(rc == 0 and dhash() == pre and "Bring it there" not in out and "cli:backup" not in out,
          "register accepts a ~/.claude conversation for a profile that reads ~/.claude, whatever a backup home holds "
          "(dry run, nothing written)")
    rc, out = drun("register", "acct-b", "--cli-session-id", N8[:8], "--dry-run")
    check(rc == 0 and dhash() == pre and "--to-profile cli:backup" not in out and "CLAUDE_CONFIG_DIR" in out,
          "register always accepts a conversation in ~/.claude, even for a profile whose other transcripts are only in "
          "a backup home (and says what that would mean)")
    rc, out = drun("register", "acct-d", "--cli-session-id", W3[:8], "--dry-run")
    check(rc == 1 and dhash() == pre and "move cli:work --to-profile cli --only " + W3[:8] in out
          and "--to-profile cli:backup" not in out,
          "register of a cli:work conversation prints the move into ~/.claude, never into a backup home that holds "
          "more of the profile's old transcripts")
    rc, out = drun("register", "acct-b", "--cli-session-id", W3[:8], "--dry-run")
    check(rc == 1 and dhash() == pre and "move cli:work --to-profile cli --only " + W3[:8] in out
          and "--to-profile cli:backup" not in out and "then run this register again" in out,
          "the same for a profile whose transcripts are only in the backup: no move into the backup is printed")
    rc, out = drun("register", "acct-b", "--cli-session-id", O3[:8], "--dry-run")
    check(rc == 1 and dhash() == pre and "move cli:backup --to-profile cli --only " + O3[:8] in out
          and "then run this register again" in out,
          "a cli:backup conversation is refused even for the profile whose records' transcripts are all in "
          "cli:backup, with the move INTO ~/.claude (where a profile's transcripts are decides nothing)")
    rc, out = drun("register", "acct-w", "--cli-session-id", W3[:8], "--dry-run")
    check(rc == 1 and dhash() == pre and "move cli:work --to-profile cli --only " + W3[:8] in out,
          "a cli:work conversation is refused for the profile whose records' transcripts are all in cli:work, with "
          "the move INTO ~/.claude")
    # Review finding #14 again (second critic, item 1): a profile whose old records' transcripts survive only in a
    # backup home (retention removed them from ~/.claude), and a new terminal conversation in ~/.claude. Registered
    # for real: no advice to move the live conversation out of ~/.claude, and afterwards no move takes it out.
    K1 = "d0d0d0d0-0000-4000-8000-00000000040a"
    k1t = cli_transcript(ddef, kd, K1, rpd, title="live in default")
    rc, out = drun("register", "acct-b", "--cli-session-id", K1[:8])
    k1rec = [f for f in glob.glob(os.path.join(dh, ".claude-instances", "acct-b", "claude-code-sessions", A, OA,
                                               "local_*.json"))
             if json.load(open(f, encoding="utf-8")).get("cliSessionId") == K1]
    k1row = [r for r in j(dh, "sessions", "acct-b").get("sessions", []) if r.get("cli") == K1]
    check(rc == 0 and len(k1rec) == 1 and os.path.exists(k1t) and "ccd-rehome move cli " not in out
          and "--to-profile cli:backup" not in out and len(k1row) == 1
          and k1row[0].get("transcript_home", "x") is None and k1row[0].get("transcript_mb") is not None,
          "#14: register files the new ~/.claude conversation for the profile whose old transcripts are only in a "
          "backup home, prints no move out of ~/.claude, and sessions shows the record with its transcript found")
    pre = dhash()
    rc, out = drun("move", "cli", "--only", K1[:8], "--to-profile", "cli:backup")
    check(rc == 1 and dhash() == pre and os.path.exists(k1t) and "is shown by Desktop profile acct-b" in out,
          "#14: and the move of that live conversation into the backup home is refused while acct-b lists it "
          "(Desktop looks for it in ~/.claude); nothing written")
    dundo(rc, out, "cli")
    for f in k1rec:
        os.remove(f)
    os.remove(k1t)

    def resume_line(prof, rid):
        rc, out = drun("resume-cli", prof, "--only", rid)
        return rc, next((l for l in out.splitlines() if "--resume" in l), "")

    rc, line = resume_line("acct-m", "ms7")
    check(rc == 0 and "claude --resume " + S7 in line and "CLAUDE_CONFIG_DIR" not in line,
          "resume-cli of a record whose transcript is in ~/.claude: no CLAUDE_CONFIG_DIR (though most of that "
          "profile's transcripts are in cli:work)")
    rc, line = resume_line("acct-m", "mw5")
    check(rc == 0 and "CLAUDE_CONFIG_DIR=" in line and os.path.realpath(dwork) in line
          and "claude --resume " + W5 in line,
          "resume-cli of a record whose transcript is in cli:work names CLAUDE_CONFIG_DIR=<cli:work> (though the "
          "profile reads ~/.claude)")
    rc, line = resume_line("acct-d", "dw4")
    check(rc == 0 and "CLAUDE_CONFIG_DIR=" in line and os.path.realpath(dwork) in line
          and os.path.realpath(dbak) not in line and "claude --resume " + W4 in line,
          "resume-cli names the home that holds THIS transcript, not the home most of the profile's records are in")
    rc, out = drun("resume-cli", "acct-m", "--only", "mw5")
    rc2, out2 = drun("resume-cli", "acct-w", "--only", "ww1")
    check(rc == 0 and "is in cli:work, not in " + disp(".claude") + ", where Desktop looks for its conversations;"
          in out and "mostly there" not in out
          and rc2 == 0 and "acct-w's records' transcripts are mostly there" in out2,
          "resume-cli's note says the conversation is not in ~/.claude, where Desktop looks, and adds the hint only "
          "for a profile whose records' transcripts are mostly in that home")
    bw7 = os.path.join(dbak, "projects", kd, W7 + ".jsonl")
    shutil.copy2(os.path.join(dwork, "projects", kd, W7 + ".jsonl"), bw7)      # a second copy, in a home found first
    rc, line = resume_line("acct-w", "ww7")
    check(rc == 0 and os.path.realpath(dwork) in line and os.path.realpath(dbak) not in line,
          "a transcript in two homes: resume-cli names the copy in the home the profile reads (cli:work), not the "
          "first home it is found in")
    os.remove(bw7)

    pre = dhash()
    rc, out = drun("move", "cli", "--only", S9[:8], "--to-profile", "cli:work", "--dry-run")
    check(rc == 1 and dhash() == pre and "REFUSE " + S9[:8] + " is shown by Desktop profile acct-d" in out,
          "dry run: a session a Desktop profile shows is refused, though a backup home holds more of that profile's "
          "transcripts")
    rc, out = drun("move", "cli", "--only", S9[:8], "--to-profile", "cli:work")
    check(rc == 1 and dhash() == pre and "shown by Desktop profile acct-d" in out
          and "unregister acct-d --only ds9" in out and "--copy" in out,
          "the real move refuses it too and nothing is written (unregister it first, or --copy)")
    dundo(rc, out, "cli")
    # Round 3: a record keeps its conversation from leaving ~/.claude, the home every Desktop profile is taken to
    # read, and never from moving INTO it (that gives the window its conversation back), whatever home the profile's
    # other transcripts are in. A move between two other homes goes ahead, with a note.
    rc, out = drun("move", "cli:work", "--only", W1[:8], "--to-profile", "cli", "--dry-run")
    check(rc == 0 and dhash() == pre and "REFUSE" not in out and "would do the above" in out
          and "acct-w" in out and "conversation back" in out,
          "a move INTO ~/.claude goes ahead though acct-w, whose records' transcripts are all in cli:work, shows the "
          "session: it gives that window its conversation back (dry run; the plan names acct-w)")
    dw1 = os.path.join(acct_d, "claude-code-sessions", A, OA, "local_dw1.json")
    rec(os.path.dirname(dw1), "dw1", "rec dw1", cliSessionId=W1, cwd=rpd)
    pre = dhash()
    rc, out = drun("move", "cli:work", "--only", W1[:8], "--to-profile", "cli", "--dry-run")
    check(rc == 0 and dhash() == pre and "REFUSE" not in out and "acct-d, acct-w" in out,
          "a session two profiles show (acct-d, and acct-w whose transcripts are all in cli:work): the move into "
          "~/.claude goes ahead and its note names both")
    os.remove(dw1)
    pre = dhash()
    rc, out = drun("move", "cli:work", "--only", W4[:8], "--to-profile", "cli:backup", "--dry-run")
    check(rc == 0 and dhash() == pre and "REFUSE" not in out and "would do the above" in out
          and "Desktop looks for its conversations in " + disp(".claude") in out and "CLAUDE_CONFIG_DIR" in out,
          "a move between two homes other than ~/.claude goes ahead for a session acct-d shows, with a note: Desktop "
          "looks for its conversations in ~/.claude (or in the folder its own CLAUDE_CONFIG_DIR names)")
    rc, out = drun("move", "cli:work", "--only", W4[:8], "--to-profile", "cli", "--dry-run")
    check(rc == 0 and dhash() == pre and "REFUSE" not in out and "would do the above" in out
          and "acct-d" in out,
          "dry run: a session acct-d shows as [in cli:work] may move INTO ~/.claude, the home acct-d reads (it gives "
          "the window its conversation back); the plan names acct-d")
    rc, out = drun("move", "cli:work", "--only", W4[:8], "--to-profile", "cli")
    undo4 = re.search(r"^undo:\s+ccd-rehome (rollback \S+ \S+)", out, re.M)
    w4d, w4w = (os.path.join(d, "projects", kd, W4 + ".jsonl") for d in (ddef, dwork))
    dw4 = {r.get("id"): r for r in j(dh, "sessions", "acct-d").get("sessions", [])}.get("dw4", {})
    check(rc == 0 and os.path.exists(w4d) and not os.path.exists(w4w) and dw4.get("transcript_home", "x") is None
          and dw4.get("transcript_mb") is not None,
          "the real move brings it there: sessions acct-d no longer shows dw4 [in cli:work]")
    rc, out = drun(*undo4.group(1).split()) if undo4 else (None, "")
    check(rc == 0 and os.path.exists(w4w) and not os.path.exists(w4d) and "warning: " + W4[:8] in out
          and "acct-d" in out and "ccd-rehome move cli:work --only " + W4 + " --to-profile cli" in out,
          "the undo that move printed works: its rollback takes the session back out of ~/.claude although acct-d "
          "shows it, with a warning that names acct-d and the move that brings it back")
    pre0 = dhash(False)
    rc, out = drun("move", "cli", "--only", S9[:8], "--to-profile", "cli:work", "--copy")
    s9w = os.path.join(dwork, "projects", kd, S9 + ".jsonl")
    check(rc == 0 and os.path.exists(os.path.join(ddef, "projects", kd, S9 + ".jsonl")) and os.path.exists(s9w),
          "--copy still goes ahead (the window keeps its copy)")
    rc, out = drun("rollback", "cli:work", arch_in(out))
    check(rc == 0 and dhash(False) == pre0, "(fixture) and rolling the copy back removes it")
    rc, out = drun("move", "cli:work", "--only", W2[:8], "--to-profile", "cli", "--copy")
    w2d = os.path.join(ddef, "projects", kd, W2 + ".jsonl")
    check(rc == 0 and os.path.exists(w2d) and "acct-w" in out,
          "(fixture) a --copy into ~/.claude of a session acct-w shows")
    rc, out = drun("rollback", "cli", arch_in(out))
    check(rc == 0 and not os.path.exists(w2d) and dhash(False) == pre0 and "warning: " + W2[:8] in out
          and "acct-w" in out,
          "the rollback of that --copy removes the copy from ~/.claude although acct-w shows the session, with a "
          "warning (the original stays in cli:work)")
    rc, out = drun("move", "cli", "--only", N8[:8], "--to-profile", "cli:work")
    a8 = arch_in(out)
    check(rc == 0 and os.path.exists(os.path.join(dwork, "projects", kd, N8 + ".jsonl")),
          "(fixture) a session no Desktop profile shows moves")
    acct_w = os.path.join(dh, ".claude-instances", "acct-w")
    n8w = os.path.join(acct_w, "claude-code-sessions", A, OA, "local_wn8.json")
    rec(os.path.dirname(n8w), "wn8", "rec wn8", cliSessionId=N8, cwd=rpd)
    rc, out = drun("rollback", "cli:work", a8)
    check(rc == 0 and os.path.exists(os.path.join(ddef, "projects", kd, N8 + ".jsonl"))
          and not os.path.exists(os.path.join(dwork, "projects", kd, N8 + ".jsonl")) and "acct-w" in out
          and "warning: " + N8[:8] not in out,
          "a rollback that brings the session back INTO ~/.claude goes ahead while acct-w, whose other transcripts "
          "are all in cli:work, shows it (a note, no warning)")
    os.remove(n8w)
    check(rc == 0 and dhash(False) == pre0, "(fixture) that rollback restores both homes exactly")

    # A Desktop instance named `cli` (or `cli-NAME`) under ~/.claude-instances. Only the bare `cli` fits both it and
    # ~/.claude; `cli:NAME` and `cli-NAME` are different names (R7).
    eh = os.path.join(home, "shadow-names"); os.makedirs(eh)
    estate = sdir(eh)

    def erun(*args, env=None):
        return run(eh, *args, env=env)

    edef, ework = os.path.join(eh, ".claude"), os.path.join(eh, ".claude-work")
    for d in (edef, ework):
        os.makedirs(os.path.join(d, "projects"))
    # two accounts, so that status advises a copy between the two homes (it advises none between homes of one account)
    for f, acct, org in ((os.path.join(eh, ".claude.json"), A, OA), (os.path.join(ework, ".claude.json"), B, OB)):
        json.dump({"oauthAccount": {"accountUuid": acct, "emailAddress": EMAIL[acct], "organizationUuid": org,
                                    "organizationName": "Org " + EMAIL[acct][0].upper()}},
                  open(f, "w", encoding="utf-8"))
    eproj = os.path.join(eh, "Projects", "eps"); os.makedirs(eproj)
    rpe = os.path.realpath(eproj)
    E1 = "e9e9e9e9-0000-4000-8000-000000000601"
    te1 = cli_transcript(edef, cr2.mangle(rpe), E1, rpe, title="shadowed names")
    we1 = os.path.join(ework, "projects", cr2.mangle(rpe), E1 + ".jsonl")
    icli = profile(eh, "cli", signed_in=B, logs=[init("09:00:00", B, OB)])
    rec(os.path.join(icli, "claude-code-sessions", A, OA), "stranded1", "stranded under A")
    profile(eh, "cli-work", signed_in=B, logs=[init("09:00:00", B, OB)])
    i_cli, h_def, h_work = disp(".claude-instances", "cli"), disp(".claude"), disp(".claude-work")
    rc, out = erun("status", "cli")
    check(rc == 1 and "ambiguous" in out, "status cli is refused as ambiguous (not a report on one of the two)")
    epre, epre0 = tree_hash(eh), tree_hash(eh, skip=estate)
    rc, out = erun("rehome", "cli", "--dry-run")
    check(rc == 1 and tree_hash(eh) == epre and "ambiguous" in out
          and "the CLI home " + h_def + "," in out and i_cli in out,
          "`cli` is refused as ambiguous when ~/.claude-instances/cli is a Desktop profile; both paths are named")
    rc, out = erun("move", h_def, "--only", E1[:8], "--to-profile", "cli:work", "--dry-run")
    check(rc == 0 and tree_hash(eh) == epre and "ambiguous" not in out and "would do the above" in out,
          "`cli:work` is NOT refused as ambiguous though ~/.claude-instances/cli-work is a Desktop profile: that one "
          "is `cli-work`, another name (only the bare `cli` fits both)")
    rc, out = erun("rehome", i_cli, "--dry-run")
    check(rc == 0 and tree_hash(eh) == epre and "1 session(s)" in out,
          "that Desktop profile is still reached by its path (its stranded session is planned)")
    rc, out = erun("status", "cli:work", "cli-work", "--json")
    try:
        rows = json.loads(out)
    except ValueError:
        rows = None
    check(isinstance(rows, list) and [(r.get("kind"), os.path.realpath(r.get("path") or "")) for r in rows]
          == [("cli", os.path.realpath(ework)), ("desktop", os.path.realpath(os.path.join(eh, ".claude-instances",
                                                                                         "cli-work")))]
          and rows[0].get("profile") == "cli:work",
          "status cli:work reports the CLI home ~/.claude-work (named cli:work), status cli-work the Desktop profile")
    rc, out = erun("profiles", "--json")
    try:
        names = [r["profile"] for r in json.loads(out)]
    except (ValueError, KeyError, TypeError):
        names = []
    check(len(names) == len(set(names)) and {h_def, "cli:work", i_cli, "cli-work"} <= set(names)
          and h_work not in names,
          "profiles gives every row a name that can be typed back: no two rows share one; only `cli`, which a Desktop "
          "profile named cli shadows, is shown by its path (cli:work keeps its name)")
    rc, out = erun("status", h_def)
    check(rc == 0 and "ccd-rehome move " + h_def + " --to-profile cli:work" in out,
          "the move command status prints names ~/.claude by its path (`cli` is ambiguous here) and cli:work by its "
          "name, so it runs as printed")
    rc, out = erun("move", h_def, "--only", E1[:8], "--to-profile", h_work)
    ea1 = arch_in(out)
    wl = next((l for l in out.splitlines() if "--resume" in l), "")
    check(rc == 0 and os.path.exists(we1) and not os.path.exists(te1) and "CLAUDE_CONFIG_DIR=" in wl,
          "(fixture) a move between homes named by path")
    # Archive names of this second and the next two, taken in the OTHER home's archive folder: the move back must
    # not reuse one (rollback finds an archive by its name, from either home).
    t0 = datetime.datetime.now(datetime.timezone.utc)
    decoys = [(t0 + datetime.timedelta(seconds=n)).strftime("%Y%m%dT%H%M%SZ") + "-cli-move" for n in range(3)]
    decoys = [n for n in decoys if n != ea1]
    for n in decoys:
        os.makedirs(os.path.join(estate, "cli-archive", "cli", n))
    rc, out = erun("move", h_work, "--only", E1[:8], "--to-profile", h_def)
    ea2 = arch_in(out)
    dl = next((l for l in out.splitlines() if "--resume" in l), "")
    check(rc == 0 and os.path.exists(te1) and "claude --resume " + E1 in dl and "CLAUDE_CONFIG_DIR" not in dl,
          "moved back into ~/.claude named by its path: the continue command has no CLAUDE_CONFIG_DIR (the default "
          "home is told by its path, not by its name)")
    check(ea2 not in decoys + [ea1, "none"], "a CLI-move archive name is unique across every home's archives")
    for n in decoys:
        os.rmdir(os.path.join(estate, "cli-archive", "cli", n))
    old_arch = os.path.join(estate, "archive", "cli", "20260101T000000Z-rehome")   # left by an earlier version
    os.makedirs(old_arch)
    rc, out = erun("status", i_cli, "cli-work", "--json")
    try:
        arcs = [a for r in json.loads(out) for a in r.get("archives", [])]
    except (ValueError, TypeError, AttributeError):
        arcs = ["unreadable"]
    check(ea1 != "none" and ea2 != "none" and rc == 0 and not any(a.endswith("-cli-move") for a in arcs)
          and arcs != ["unreadable"],
          "CLI-home archives never land in the archive folder of a Desktop profile named cli or cli-work")
    check(os.path.basename(old_arch) in arcs,
          "the Desktop profile named cli keeps its archive folder (archive/cli): its earlier archives are still listed")
    os.rmdir(old_arch)
    rc, out = erun("rollback", h_def, ea2)
    rc2, out2 = erun("rollback", h_work, ea1)
    check(rc == 0 and rc2 == 0 and tree_hash(eh, skip=estate) == epre0,
          "(fixture) both moves roll back, from where their archives now live, to the exact state before")
    iwork = os.path.join(eh, ".claude-instances", "cli-work")
    rec(os.path.join(iwork, "claude-code-sessions", B, OB), "e1rec", "shadowed names", cliSessionId=E1, cwd=rpe)
    rc, out = erun("resume-cli", "cli-work", "--only", "e1rec",
                   env={"PATH": fake + os.pathsep + os.environ.get("PATH", "")})
    rl = next((l for l in out.splitlines() if "--resume" in l), "")
    check(rc == 0 and "claude --resume " + E1 in rl and "CLAUDE_CONFIG_DIR" not in rl,
          "resume-cli of a conversation in ~/.claude (shown by its path) prints no CLAUDE_CONFIG_DIR")
    ses = j(eh, "sessions", "cli-work").get("sessions", [])
    check([r.get("transcript_home") for r in ses] == [None],
          "sessions of a Desktop profile does not flag a transcript in ~/.claude as 'in' another home")
    rc, out = erun("cli-sessions")
    check(rc == 0 and "Desktop reads " + h_def + " only when" not in out
          and "Desktop reads cli:work only when" in out,
          "cli-sessions notes CLAUDE_CONFIG_DIR for the other home only, not for ~/.claude shown by its path")

    print("Reports and discovery: CLI-home archives in status, the status --json shape, shell-file discovery, the "
          "move hint, sign-in warnings, Windows commands")
    # A home of its own: ~/.claude (two sessions, signed in), ~/.claude-work (signed out), ~/.claude-third (signed
    # in), all one account and org, and a Desktop profile acct-r.
    rh = os.path.join(home, "report-homes"); os.makedirs(rh)
    # This section emulates three OSes in one home, and each OS has its own state folder: a state folder that an
    # earlier version left in ~/.claude-instances/_rehome is the one place they all share (and keep using).
    rstate = os.path.join(rh, ".claude-instances", "_rehome"); os.makedirs(rstate)
    lin, win, mac = ({"CCD_REHOME_PLATFORM": p} for p in ("linux", "win32", "darwin"))

    def rrun(*args, env=None):
        return run(rh, *args, env=env)

    def rjson(*args, env=None):
        rc, out = run(rh, *args, "--json", env=env)
        try:
            return json.loads(out)
        except ValueError:
            return None

    rdef, rwork, rthird = (os.path.join(rh, n) for n in (".claude", ".claude-work", ".claude-third"))
    for d in (rdef, rwork, rthird):
        os.makedirs(os.path.join(d, "projects"))
    for f in (os.path.join(rh, ".claude.json"), os.path.join(rwork, ".claude.json"),
              os.path.join(rthird, ".claude.json")):
        json.dump({"oauthAccount": {"accountUuid": A, "emailAddress": EMAIL[A], "organizationUuid": OA,
                                    "organizationName": "Org A"}}, open(f, "w", encoding="utf-8"))
    for d in (rdef, rthird):
        open(os.path.join(d, ".credentials.json"), "w", encoding="utf-8").write("x")
    rproj = os.path.realpath(os.path.join(rh, "Projects", "rho")); os.makedirs(rproj)
    rk = cr2.mangle(rproj)
    R1, R2 = ("7%d7%d7%d7%d-0000-4000-8000-00000000060%d" % ((n,) * 5) for n in (1, 2))
    for sid in (R1, R2):
        cli_transcript(rdef, rk, sid, rproj, title="report " + sid[:8])
    racct = profile(rh, "acct-r", signed_in=A, logs=[init("09:00:00", A, OA)])
    ridb = os.path.join(racct, "IndexedDB", "x.blob", "1")
    rwork_rp = os.path.realpath(rwork)
    rpre = tree_hash(rh, skip=rstate)

    # ---- status of a CLI home lists its cli-move archives (#10, #46)
    rc, out = rrun("move", "cli", "--only", R1[:8], "--to-profile", "cli:work", env=lin)
    ra1 = arch_in(out)
    check(rc == 0 and f"cd '{rproj}' && CLAUDE_CONFIG_DIR='{rwork_rp}' claude --resume {R1}" in out,
          "(fixture) a move into cli:work; elsewhere than Windows the continue command is one POSIX line")
    rc2, out2 = rrun("move", "cli", "--only", R2[:8], "--to-profile", "cli:third", env=lin)
    ra2 = arch_in(out2)
    check(rc2 == 0 and "none" not in (ra1, ra2) and ra1 != ra2, "(fixture) and one into cli:third")

    def arcs_of(spec):
        rows = rjson("status", spec)
        return rows[0].get("archives") if isinstance(rows, list) and rows and isinstance(rows[0], dict) else None

    check(arcs_of("cli") == sorted([ra1, ra2]),
          "status cli --json lists the archives of both moves out of cli (oldest first)")
    check(arcs_of("cli:work") == [ra1] and arcs_of("cli:third") == [ra2],
          "status of each target lists only the archive of the move into it")
    rc, out = rrun("status", "cli:work")
    check(rc == 0 and "archives" in out and ra1 in out and ra2 not in out,
          "status cli:work (text) prints the name of its archive")
    junk = os.path.join(rstate, "cli-archive", "cli", "20200101T000000Z-cli-move"); os.makedirs(junk)
    check(arcs_of("cli") == sorted([ra1, ra2]),
          "a folder there without a readable manifest is not listed (rollback could not use it)")
    os.rmdir(junk)
    rc, out = rrun("rollback", "cli", "20990101T000000Z-cli-move")
    hint = re.search(r"list them: ccd-rehome (status \S+)", out)
    rc2, out2 = rrun(*hint.group(1).split()) if hint else (1, "")
    check(rc == 1 and hint is not None and rc2 == 0 and ra1 in out2 and ra2 in out2,
          "rollback with a wrong archive name says to list them with status, and that status lists them")

    # ---- status --json rows of CLI homes carry the Desktop keys, with neutral values (#18)
    rows = rjson("status") or []
    drow = next((r for r in rows if isinstance(r, dict) and r.get("kind") == "desktop"), None)
    crows = [r for r in rows if isinstance(r, dict) and r.get("kind") == "cli"]
    dkeys = {"kind", "profile", "path", "running", "verdict", "account", "email", "last_account_email",
             "cookie_expires", "active_dir", "blocker", "visible", "stranded", "cowork_stranded", "archives"}
    check(drow is not None and dkeys <= set(drow) and len(crows) == 3 and all(set(drow) <= set(r) for r in crows),
          "status --json (no arguments): every CLI row has every key a Desktop row has (the shape only grows)")
    neutral = {"stranded": {}, "cowork_stranded": 0, "visible": [], "active_dir": None, "blocker": None,
               "cookie_expires": None, "last_account_email": None}
    check(bool(crows) and all(all(r.get(k, "absent") == v for k, v in neutral.items())
                              and isinstance(r.get("archives"), list) for r in crows),
          "a CLI row's Desktop keys are neutral: nothing stranded or visible, no folder, blocker, cookie or last "
          "account; archives is a list")
    try:
        sum(sum(r["stranded"].values()) + r["cowork_stranded"] for r in rows)
        summed = bool(rows)
    except (KeyError, TypeError, AttributeError):
        summed = False
    check(summed, "a 0.10 consumer of status --json (stranded + cowork_stranded summed over every row) still works")
    rc, out = rrun("rollback", "cli", ra2)
    rc2, out2 = rrun("rollback", "cli", ra1)
    check(rc == 0 and rc2 == 0 and tree_hash(rh, skip=rstate) == rpre, "(fixture) both moves rolled back exactly")

    # ---- the registry reads each profile once (#42)
    count_opens = (
        "import builtins, os, runpy, sys\n"
        "tool, watch = sys.argv[1], os.path.realpath(sys.argv[2])\n"
        "n, real = [0], builtins.open\n"
        "def counting(f, *a, **k):\n"
        "    if isinstance(f, str) and os.path.realpath(f) == watch:\n"
        "        n[0] += 1\n"
        "    return real(f, *a, **k)\n"
        "builtins.open = counting\n"
        "sys.argv = [tool] + sys.argv[3:]\n"
        "try:\n"
        "    runpy.run_path(tool, run_name='__main__')\n"
        "finally:\n"
        "    sys.stdout.flush(); print('OPENS=%d' % n[0])\n")

    def opens(watch, *args):
        e = dict(caller_env(), CCD_REHOME_HOME=rh, CCD_REHOME_SANDBOX="1", PYTHONIOENCODING="utf-8")
        r = subprocess.run([sys.executable, "-I", "-c", count_opens, TOOL, watch, *args], capture_output=True,
                           text=True, encoding="utf-8", errors="replace", env=e)
        LAST[0] = f"$ {' '.join(args)}  (rc {r.returncode})\n" + r.stdout + r.stderr
        m = re.search(r"OPENS=(\d+)", r.stdout)
        return r.returncode, int(m.group(1)) if m else -1

    for args in (("status", "acct-r"), ("sessions", "acct-r"), ("status", "acct-r", "acct-r")):
        rc, n = opens(ridb, *args)
        check(rc == 0 and n == 1, f"`{' '.join(args)}` reads the profile's IndexedDB once (opened {n} times): each "
                                  f"path reaches the account registry once")

    # ---- a target that is not signed in: warn only when it is signed out (#40)
    rc, out = rrun("move", "cli", "--only", R1[:8], "--to-profile", "cli:work", "--dry-run", env=lin)
    check(rc == 0 and "cli:work is signed" in out and "sign in there" in out and "Keychain" not in out,
          "Linux: a target without a login file is signed out: sign in there before resuming")
    rc, out = rrun("move", "cli", "--only", R1[:8], "--to-profile", "cli:work", "--dry-run", env=mac)
    check(rc == 0 and "sign in there" not in out and "is unknown" not in out and "Keychain" in out,
          "macOS: the same target is unknown, not signed out: no 'sign in there', it says the login is in the Keychain")
    for plat, penv in (("Linux", lin), ("macOS", mac)):
        rc, out = rrun("move", "cli", "--only", R1[:8], "--to-profile", "cli:third", "--dry-run", env=penv)
        check(rc == 0 and "sign in" not in out and "Keychain" not in out,
              f"{plat}: a target with a login file gets no sign-in warning or note")

    # ---- Windows: the continue command in cmd and PowerShell syntax (#38)
    posix_prefix = re.compile(r"(?<![:\w])CLAUDE_CONFIG_DIR=\S+ claude")
    rc, out = rrun("move", "cli", "--only", R1[:8], "--to-profile", "cli:work", env=win)
    wa1 = arch_in(out)
    lines = [l for l in out.splitlines() if "claude --resume " + R1 in l]
    check(rc == 0 and any(f'cd /d "{rproj}" && set "CLAUDE_CONFIG_DIR={rwork_rp}" && claude --resume {R1}' in l
                          and "(cmd)" in l for l in lines),
          "Windows: the continue command in cmd syntax (cd /d, set \"CLAUDE_CONFIG_DIR=...\" &&)")
    check(any(f"Set-Location -LiteralPath '{rproj}'; $env:CLAUDE_CONFIG_DIR='{rwork_rp}'; claude --resume {R1}" in l
              and "(PowerShell)" in l for l in lines),
          "Windows: and in PowerShell syntax ($env:CLAUDE_CONFIG_DIR='...';)")
    check(bool(lines) and not any(posix_prefix.search(l) for l in lines),
          "Windows: no continue line uses the POSIX `CLAUDE_CONFIG_DIR=... claude` prefix")
    rec(os.path.join(racct, "claude-code-sessions", A, OA), "r1desk", "report desk", cliSessionId=R1, cwd=rproj)
    rc, out = rrun("resume-cli", "acct-r", "--only", "r1desk", env=win)
    lines = [l for l in out.splitlines() if "claude --resume " + R1 in l]
    check(rc == 0 and any(f'set "CLAUDE_CONFIG_DIR={rwork_rp}" && claude --resume {R1}' in l for l in lines)
          and any(f"$env:CLAUDE_CONFIG_DIR='{rwork_rp}'; claude --resume {R1}" in l for l in lines)
          and not any(posix_prefix.search(l) for l in lines),
          "Windows: resume-cli prints the cmd and the PowerShell line, no POSIX prefix")
    rc, out = rrun("resume-cli", "acct-r", "--only", "r1desk", env=lin)
    check(rc == 0 and f"cd '{rproj}' && CLAUDE_CONFIG_DIR='{rwork_rp}' claude --resume {R1}" in out,
          "elsewhere resume-cli prints the one POSIX line, as before")
    shutil.rmtree(os.path.join(racct, "claude-code-sessions"))
    rc, out = rrun("move", "cli:work", "--only", R1[:8], "--to-profile", "cli", env=win)
    wa2 = arch_in(out)
    lines = [l for l in out.splitlines() if "claude --resume " + R1 in l]
    check(rc == 0 and any(f'cd /d "{rproj}" && claude --resume {R1}' in l for l in lines)
          and any(f"Set-Location -LiteralPath '{rproj}'; claude --resume {R1}" in l for l in lines)
          and not any("CLAUDE_CONFIG_DIR" in l for l in lines),
          "Windows, moved into ~/.claude: both lines, with no variable to set")
    rc, out = rrun("rollback", "cli", wa2, env=win)
    rc2, out2 = rrun("rollback", "cli", wa1, env=win)
    check(rc == 0 and rc2 == 0 and tree_hash(rh, skip=rstate) == rpre, "(fixture) the Windows moves rolled back")

    # ---- only ~/.claude: no move command into a home that does not exist; how to create one (#36, #41)
    oh = os.path.join(home, "one-home"); os.makedirs(os.path.join(oh, ".claude", "projects"))
    json.dump({"oauthAccount": {"accountUuid": A, "emailAddress": EMAIL[A], "organizationUuid": OA}},
              open(os.path.join(oh, ".claude.json"), "w", encoding="utf-8"))
    open(os.path.join(oh, ".claude", ".credentials.json"), "w", encoding="utf-8").write("x")
    oproj = os.path.realpath(os.path.join(oh, "Projects", "omicron")); os.makedirs(oproj)
    OS1 = "6e6e6e6e-0000-4000-8000-000000000701"
    cli_transcript(os.path.join(oh, ".claude"), cr2.mangle(oproj), OS1, oproj, title="only home")
    for cmd in (("status", "cli"), ("rehome", "cli"), ("status",)):
        rc, out = run(oh, *cmd, env=lin)
        check(rc == 0 and "--to-profile cli:work" not in out and "no other CLI home" in out
              and "CLAUDE_CONFIG_DIR=~/.claude-NAME claude" in out and "sign in" in out,
              f"`{' '.join(cmd)}` with only ~/.claude: no move into a home that does not exist; it says how to create "
              f"one (start CLAUDE_CONFIG_DIR=~/.claude-NAME claude once, sign in)")
    rows = j(oh, "status", "cli")
    check(isinstance(rows, list) and rows and rows[0].get("move", "absent") is None,
          "status cli --json: \"move\" is null when there is no other CLI home")
    rc, out = run(oh, "status", "cli", env=win)
    check(rc == 0 and f'set "CLAUDE_CONFIG_DIR={os.path.join(oh, ".claude-NAME")}" && claude' in out
          and f"$env:CLAUDE_CONFIG_DIR='{os.path.join(oh, '.claude-NAME')}'; claude" in out
          and "CLAUDE_CONFIG_DIR=~/.claude-NAME claude" not in out,
          "Windows: that setup step in cmd and PowerShell syntax")
    os.makedirs(os.path.join(oh, ".claude-work"))
    open(os.path.join(oh, ".claude-work", "settings.json"), "w", encoding="utf-8").write("{}")
    rc, out = run(oh, "status", "cli", env=lin)
    mv = re.search(r"ccd-rehome (move cli --to-profile \S+)", out)
    rc2, out2 = run(oh, *mv.group(1).split(), "--only", OS1[:8], "--dry-run", env=lin) if mv else (1, "")
    check(rc == 0 and mv is not None and mv.group(1).endswith(" cli:work") and rc2 == 0 and
          "no other CLI home" not in out,
          "once ~/.claude-work exists, status prints the move into it, and that command runs (dry run)")

    # ---- shell-file discovery: real assignments only, never HOME or a folder above a home or a profile (#20)
    rr = os.path.join(home, "rc-root"); hh = os.path.join(rr, "h")
    hstate = sdir(hh)
    hdef = os.path.join(hh, ".claude"); os.makedirs(os.path.join(hdef, "projects"))
    open(os.path.join(rr, "settings.json"), "w", encoding="utf-8").write("{}")    # above HOME, looks like a home
    json.dump({"oauthAccount": {"accountUuid": A, "emailAddress": EMAIL[A], "organizationUuid": OA}},
              open(os.path.join(hh, ".claude.json"), "w", encoding="utf-8"))
    hproj = os.path.realpath(os.path.join(hh, "Projects", "eta")); os.makedirs(hproj)
    HS1 = "5e5e5e5e-0000-4000-8000-000000000801"
    cli_transcript(hdef, cr2.mangle(hproj), HS1, hproj, title="rc")
    other = os.path.join(hh, "other")
    goods = ("good1", "good2", "good3", "good4")
    for n in goods + ("ohome", "chome", "shome", "thome", "rel", "named"):
        os.makedirs(os.path.join(other, n, "projects"))
    deskroot = os.path.join(hh, "desk-root"); os.makedirs(deskroot)
    open(os.path.join(deskroot, "settings.json"), "w", encoding="utf-8").write("{}")
    hdesk = profile(hh, os.path.join(deskroot, "prof"), signed_in=A, logs=[init("09:00:00", A, OA)])
    hinst = os.path.join(hh, ".claude-instances"); os.makedirs(hinst, exist_ok=True)
    open(os.path.join(hinst, "settings.json"), "w", encoding="utf-8").write("{}")
    rc_lines = [
        "alias c='CLAUDE_CONFIG_DIR=~ claude'",
        "export CLAUDE_CONFIG_DIR=$HOME",
        "CLAUDE_CONFIG_DIR=.",
        "CLAUDE_CONFIG_DIR=~/..",
        'export OLD_CLAUDE_CONFIG_DIR="${HOME}/other/ohome"',
        "  # alias cx='CLAUDE_CONFIG_DIR=~/other/chome claude'",
        "CLAUDE_CONFIG_DIR = ~/other/shome",
        "echo hi  # CLAUDE_CONFIG_DIR=~/other/thome",
        "CLAUDE_CONFIG_DIR=other/rel",
        "CLAUDE_CONFIG_DIR=~/desk-root",
        "CLAUDE_CONFIG_DIR=~/.claude-instances",
        'alias g1="CLAUDE_CONFIG_DIR=~/other/good1 claude"',
        'export CLAUDE_CONFIG_DIR="$HOME/other/good2"',
        "alias g3='env CLAUDE_CONFIG_DIR=~/other/good3 claude'",
        "cd /tmp;CLAUDE_CONFIG_DIR=${HOME}/other/good4 claude",
    ]
    open(os.path.join(hh, ".bashrc"), "w", encoding="utf-8").write("\n".join(rc_lines) + "\n")
    henv = {"CCD_REHOME_PROFILES": hdesk}

    def hrun(*args, env=None):
        return run(hh, *args, env=dict(henv, **(env or {})))

    def hpaths():
        rc, out = hrun("profiles", "--json")
        try:
            return {r["path"] for r in json.loads(out) if r.get("kind") == "cli"}
        except (ValueError, TypeError, KeyError, AttributeError):
            return {"unreadable"}

    def rp_(*parts):
        return os.path.realpath(os.path.join(hh, *parts))

    hp = hpaths()
    check(rp_() not in hp, "HOME is never a CLI home (CLAUDE_CONFIG_DIR=~, =$HOME, =.), though ~/.claude.json is in it")
    check(os.path.realpath(rr) not in hp, "nor a folder above HOME (CLAUDE_CONFIG_DIR=~/..)")
    check(rp_("other", "ohome") not in hp, "OLD_CLAUDE_CONFIG_DIR= is another variable: not an assignment of it")
    check(rp_("other", "chome") not in hp, "a commented-out line is skipped")
    check(rp_("other", "thome") not in hp, "a comment after a command is skipped")
    check(rp_("other", "shome") not in hp, "`CLAUDE_CONFIG_DIR = path` (spaces around =) is not an assignment")
    check(rp_("other", "rel") not in hp, "a relative path (relative to wherever the shell runs) is not guessed")
    check(rp_("desk-root") not in hp, "a folder that holds a Desktop profile is not a CLI home")
    check(rp_(".claude-instances") not in hp, "~/.claude-instances is not a CLI home")
    check(all(rp_("other", g) in hp for g in goods) and hp == {rp_(".claude")} | {rp_("other", g) for g in goods},
          "real assignments are found (in an alias with either quotes, after env, after ;, export with quotes), "
          "and nothing else")
    hknown = os.path.join(hstate, "profiles.json")

    def hremembered():
        try:
            return [os.path.realpath(x) for x in json.load(open(hknown, encoding="utf-8"))]
        except (OSError, ValueError, TypeError):
            return []

    check(not any(rp_("other", g) in hremembered() for g in goods),
          "homes found in shell files are not remembered (they go away with their line)")
    open(os.path.join(hh, ".bashrc"), "w", encoding="utf-8").write(
        "\n".join(l for l in rc_lines if "good1" not in l) + "\n")
    check(rp_("other", "good1") not in hpaths(), "after its line is removed, that home is no longer listed")
    rc, out = hrun("status", os.path.join(other, "named"))
    check(rc == 0 and rp_("other", "named") in hremembered() and rp_("other", "named") in hpaths(),
          "a home named on the command line is remembered and listed later")
    json.dump(hremembered() + [rp_()], open(hknown, "w", encoding="utf-8"))     # left by an earlier build
    check(rp_() not in hpaths(), "HOME remembered by an earlier build is not listed")
    hrun("sessions", "cli")                 # a run that names cli (remembered as named) before the hash is taken
    hpre = tree_hash(hh, skip=os.path.join(hstate, "accounts.json"))
    for label, spec in (("~", "~"), ("HOME's path", hh), ("a folder above HOME", os.path.join(hh, "..")),
                        ("~/.claude-instances", hinst), ("a folder holding a Desktop profile", deskroot)):
        rc, out = hrun("move", "cli", "--only", HS1[:8], "--to-profile", spec)
        check(rc == 1 and "not a Claude Code config dir" in out
              and tree_hash(hh, skip=os.path.join(hstate, "accounts.json")) == hpre,
              f"move --to-profile {label} is refused and nothing is written")
        if rc == 0 and arch_in(out) != "none":          # a broken tool went ahead: undo, so the next check is fair
            hrun("rollback", "cli", arch_in(out))
    # A fresh machine: no ~/.claude-instances and no Desktop profile, and only dry runs (they create no state
    # folder), so HOME and the folder above it can be refused only for being what they are.
    fr = os.path.join(home, "fresh-root"); fh = os.path.join(fr, "h"); fdef = os.path.join(fh, ".claude")
    os.makedirs(os.path.join(fdef, "projects"))
    open(os.path.join(fr, "settings.json"), "w", encoding="utf-8").write("{}")
    json.dump({"oauthAccount": {"accountUuid": A, "emailAddress": EMAIL[A], "organizationUuid": OA}},
              open(os.path.join(fh, ".claude.json"), "w", encoding="utf-8"))
    fproj = os.path.realpath(os.path.join(fh, "Projects", "phi")); os.makedirs(fproj)
    FS1 = "4f4f4f4f-0000-4000-8000-000000000901"
    cli_transcript(fdef, cr2.mangle(fproj), FS1, fproj, title="fresh")
    open(os.path.join(fh, ".bashrc"), "w", encoding="utf-8").write("export CLAUDE_CONFIG_DIR=~\nCLAUDE_CONFIG_DIR=~/..\n")
    fpre = tree_hash(fr)
    rc, out = run(fh, "profiles", "--json", "--dry-run")
    try:
        fpaths = {r["path"] for r in json.loads(out) if r.get("kind") == "cli"}
    except (ValueError, TypeError, KeyError, AttributeError):
        fpaths = {"unreadable"}
    check(fpaths == {os.path.realpath(fdef)} and tree_hash(fr) == fpre,
          "a fresh machine (no ~/.claude-instances, no Desktop): CLAUDE_CONFIG_DIR=~ and =~/.. find neither HOME nor "
          "the folder above it")
    rc, out = run(fh, "move", "cli", "--only", FS1[:8], "--to-profile", "~", "--dry-run")
    check(rc == 1 and "is your home folder" in out and tree_hash(fr) == fpre,
          "there, move --to-profile ~ (dry run) is refused: it is your home folder")
    rc, out = run(fh, "move", "cli", "--only", FS1[:8], "--to-profile", fr, "--dry-run")
    check(rc == 1 and "is a folder above" in out and tree_hash(fr) == fpre,
          "and --to-profile <the folder above HOME> as a folder above ~/.claude")
    inner = profile(hh, os.path.join(hdef, "desk-inside"), signed_in=A, logs=[init("09:00:00", A, OA)])
    rc, out = hrun("status", "cli", "--json", env={"CCD_REHOME_PROFILES": os.pathsep.join([hdesk, inner])})
    try:
        inner_ok = rc == 0 and json.loads(out)[0].get("path") == rp_(".claude")
    except (ValueError, IndexError, AttributeError):
        inner_ok = False
    check(inner_ok, "~/.claude is always a CLI home, even with a Desktop profile kept inside it")
    shutil.rmtree(inner)

    print("What the tool says about itself, the target of a CLI move, and rules that had no check")
    # A home of its own: ~/.claude (signed in) with four sessions, ~/.claude-work, and a Desktop profile acct-x.
    dh = os.path.join(home, "docs-root")
    dstate = sdir(dh)
    ddef, dwork = os.path.join(dh, ".claude"), os.path.join(dh, ".claude-work")
    for d in (ddef, dwork):
        os.makedirs(os.path.join(d, "projects"))
    for gc in (os.path.join(dh, ".claude.json"), os.path.join(dwork, ".claude.json")):
        json.dump({"oauthAccount": {"accountUuid": A, "emailAddress": EMAIL[A], "organizationUuid": OA}},
                  open(gc, "w", encoding="utf-8"))
    open(os.path.join(ddef, ".credentials.json"), "w", encoding="utf-8").write("DECOY")
    dx = profile(dh, "acct-x", logs=[init("09:00:00", B, OB)])
    DX = "d6d6d6d6-0000-4000-8000-000000000601"
    rec(os.path.join(dx, "claude-code-sessions", B, OB), DX, "a Desktop session")
    dproj = os.path.realpath(os.path.join(dh, "Projects", "delta")); os.makedirs(dproj)
    dk = cr2.mangle(dproj)
    DS = ["d1d1d1d1-0000-4000-8000-000000000611", "d2d2d2d2-0000-4000-8000-000000000612",
          "d3d3d3d3-0000-4000-8000-000000000613", "d4d4d4d4-0000-4000-8000-000000000614"]
    for i, sid in enumerate(DS):
        cli_transcript(ddef, dk, sid, dproj, title=f"docs {i + 1}")
    old = time.time() - 100 * 86400                       # older than the default cleanupPeriodDays (30)
    os.utime(os.path.join(ddef, "projects", dk, DS[1] + ".jsonl"), (old, old))

    def dhash():
        return tree_hash(dh, skip=os.path.join(dstate, "accounts.json"))

    def drun(*args, env=None):
        return run(dh, *args, env=env)

    rc, out = drun("--help")
    flat = " ".join(out.split())
    check(rc == 0 and "`move cli` moves" in flat and "with --copy" in flat and "byte for byte" in flat
          and "never copies or edits transcripts" not in flat and "never touches another profile" not in flat,
          "--help says `move cli` moves (with --copy, copies) a session's files byte for byte between CLI homes, and "
          "no longer that the tool never copies a transcript or touches another profile")
    check("every Desktop profile and CLI home" in flat, "--help: `profiles` lists the CLI homes too")

    # The first real run creates the state folder, and a home or profile named on the command line is remembered
    # (by design): name each one once before the hash is taken.
    drun("status", "cli", "cli:work", "acct-x", dx)
    dpre = dhash()
    for label, spec in (("a Desktop profile's name", "acct-x"), ("a Desktop profile's path", dx)):
        rc, out = drun("move", "cli", "--only", DS[0][:8], "--to-profile", spec)
        check(rc == 1 and "is not a CLI home (use cli, cli:NAME, or a path to one)" in out and dhash() == dpre,
              f"move cli --to-profile <{label}> is refused with 'is not a CLI home', and nothing is written")
    rc, out = drun("move", "cli", "--only", DS[0][:8], "--to-profile", "cli:nope")
    check(rc == 1 and "is not a Claude Code config dir" in out and dhash() == dpre,
          "move cli --to-profile cli:NAME with no such folder is refused with 'is not a Claude Code config dir'")
    rc, out = drun("move", "cli", "--only", DS[0][:8], "--to-profile", "cli")
    check(rc == 1 and "names the same CLI home" in out and dhash() == dpre,
          "move cli --to-profile cli (the same home) is refused, and nothing is written")
    rc, out = drun("move", "acct-x", "--only", DX[:8], "--to-profile", "cli:work")
    check(rc == 1 and "--to-profile is a CLI home" in out and dhash() == dpre,
          "a Desktop profile's move --to-profile <a CLI home> is refused (records go to Desktop profiles only)")
    rc, out = drun("rehome", "--all", "--dry-run")
    check(rc == 0 and "nothing to rehome" not in out and "cli" not in out.split(),
          "rehome --all skips the CLI homes silently")

    sreg_ = os.path.join(ddef, "sessions"); os.makedirs(sreg_)
    json.dump({"pid": 33333, "sessionId": DS[0], "cwd": dproj, "status": "idle"},
              open(os.path.join(sreg_, "33333.json"), "w", encoding="utf-8"))
    rows_ = {}
    for live in ("33333", ""):
        rc, out = drun("profiles", "--json", env={"CCD_REHOME_LIVE_PIDS": live})
        try:
            rows_[live] = next(r for r in json.loads(out) if r.get("kind") == "cli" and r.get("profile") == "cli")
        except (ValueError, StopIteration, AttributeError):
            rows_[live] = {}
    check(rows_["33333"].get("running") is True and rows_[""].get("running") is False,
          "profiles: a CLI home is RUNNING while a live sessions/<pid>.json names a process that is alive, not otherwise")
    os.remove(os.path.join(sreg_, "33333.json"))
    rc, out = drun("sessions", "cli")
    line2 = next((l for l in out.splitlines() if DS[1][:8] in l), "")
    line1 = next((l for l in out.splitlines() if DS[0][:8] in l), "")
    check(rc == 0 and "[older than 30 days]" in line2 and "older than" not in line1,
          "sessions cli flags a transcript older than the home's cleanupPeriodDays (default 30), and only that one")

    # The symlink rule on its own: a sidecar folder that is a symlink to a folder INSIDE the home (so the escape
    # rule cannot be what refuses it).
    target_ = os.path.join(ddef, "kept-sidecar"); os.makedirs(target_)
    open(os.path.join(target_, "x.txt"), "w", encoding="utf-8").write("x")
    try:
        os.symlink(target_, os.path.join(ddef, "projects", dk, DS[2]), target_is_directory=True)
        linked = True
    except (OSError, NotImplementedError):
        linked = False
    if linked:
        dpre = dhash()
        rc, out = drun("move", "cli", "--only", DS[2][:8], "--to-profile", "cli:work")
        check(rc == 1 and "is a symlink" in out and out.lower().count("nothing was changed") == 1
              and dhash() == dpre,
              "a sidecar folder that is a symlink to a folder inside the home is refused as a symlink; nothing is "
              "written")
        os.remove(os.path.join(ddef, "projects", dk, DS[2]))
    else:
        print("  (skipped in-home symlink check: this OS/user cannot create symlinks)")

    # Rollback keeps a copied memory file that was changed in the target since the move.
    dmem = os.path.join(ddef, "projects", dk, "memory"); os.makedirs(dmem)
    open(os.path.join(dmem, "NOTES.md"), "w", encoding="utf-8").write("delta memory")
    rc, out = drun("move", "cli", "--only", DS[3][:8], "--to-profile", "cli:work")
    darch = next((w for w in out.split() if w.endswith("-cli-move")), "none")
    wnotes = os.path.join(dwork, "projects", dk, "memory", "NOTES.md")
    check(rc == 0 and os.path.isfile(wnotes), "(fixture) the move copies the project memory into cli:work")
    if os.path.isfile(wnotes):
        open(wnotes, "a", encoding="utf-8").write(" + a note written in cli:work")
    rc, out = drun("rollback", "cli:work", darch)
    try:
        kept_ = open(wnotes, encoding="utf-8").read()
    except OSError:
        kept_ = ""
    check(rc == 0 and kept_.endswith("written in cli:work") and "kept changed memory file" in out
          and os.path.isfile(os.path.join(ddef, "projects", dk, DS[3] + ".jsonl")),
          "rollback moves the session back but keeps a copied memory file changed in the target since, and says so")

    print("Second review of CLI moves: links in the target, rules that had no check, special files, interruptions, "
          "the only copy left")
    # A home of its own: ~/.claude (signed in) and ~/.claude-work, one account and one org, so no warning is in the
    # way. Each session id has its own first 8 characters, so `--only <8>` picks exactly one.
    bh = os.path.join(home, "b1-root")
    bstate = sdir(bh)
    bdef, bwork = os.path.join(bh, ".claude"), os.path.join(bh, ".claude-work")
    for d in (bdef, bwork):
        os.makedirs(os.path.join(d, "projects"))
    for gc in (os.path.join(bh, ".claude.json"), os.path.join(bwork, ".claude.json")):
        json.dump({"oauthAccount": {"accountUuid": A, "emailAddress": EMAIL[A], "organizationUuid": OA}},
                  open(gc, "w", encoding="utf-8"))
    put(os.path.join(bdef, ".credentials.json"), "DECOY-B1-CREDENTIAL")
    put(os.path.join(bwork, ".credentials.json"), "DECOY-B1-WORK")
    put(os.path.join(bwork, "settings.json"), '{"cleanupPeriodDays": 45}')
    bproj = os.path.realpath(os.path.join(bh, "Projects", "one")); os.makedirs(bproj)
    bk = cr2.mangle(bproj)
    bmem = put(os.path.join(bdef, "projects", bk, "memory", "MEMORY.md"), "project one memory")
    wbmem = os.path.join(bwork, "projects", bk, "memory", "MEMORY.md")

    def bhash():
        """Both homes and the tool's state (archives included), minus the account registry every run refreshes."""
        return tree_hash(bh, skip=os.path.join(bstate, "accounts.json"))

    bouts = []

    def brun(*args, env=None, timeout=120, argv=None):
        rc, out = run(bh, *args, env=env, timeout=timeout, argv=argv)
        bouts.append(out)
        return rc, out

    def bid(n):
        """A synthetic session id whose first 8 characters differ for each n (and hold only two kinds of character, as
        a placeholder id must for tests/test_privacy.py)."""
        return format(n % 256, "08b").replace("0", "b") + "-0000-4000-8000-%012d" % n

    def bsession(n, title):
        """A session of five items in ~/.claude: transcript, sidecar folder, tasks, file history, a todo."""
        sid = bid(n)
        cli_transcript(bdef, bk, sid, bproj, title=title)
        put(os.path.join(bdef, "projects", bk, sid, "subagents", "agent.jsonl"), "{}\n")
        put(os.path.join(bdef, "tasks", sid, "1.json"), "{}")
        put(os.path.join(bdef, "file-history", sid, "v1"), "v1")
        put(os.path.join(bdef, "todos", sid + "-agent-" + sid + ".json"), "[]")
        return sid, items_of(bdef, bk, sid), items_of(bwork, bk, sid)

    def bmove(sid, *extra, env=None, timeout=120):
        return brun("move", "cli", "--only", sid[:8], "--to-profile", "cli:work", *extra, env=env, timeout=timeout)

    def bundo(rc, out):
        """A move that should have refused but went ahead (a broken tool) is rolled back, so that the next check
        still tests what it says."""
        if rc == 0 and arch_in(out) != "none":
            brun("rollback", "cli", arch_in(out))

    def regular_text(base):
        """The text of every regular file under base (a FIFO is never opened)."""
        out = []
        for dp, _, fn in os.walk(base):
            for f in fn:
                p = os.path.join(dp, f)
                if stat.S_ISREG(os.lstat(p).st_mode):
                    out.append(open(p, encoding="utf-8", errors="replace").read())
        return "\n".join(out)

    def kept_archives():
        return [os.path.basename(d) for d in
                glob.glob(os.path.join(glob.escape(bstate), "cli-archive", "*", "*-cli-move"))]

    # The first real run creates the state folder and remembers the homes named (by design): name both once before
    # any hash is taken.
    brun("status", "cli", "cli:work")

    # Links in the target: a folder of cli:work that leads elsewhere must never receive a session.
    sH, iH, wH = bsession(208, "into a linked folder of cli:work")
    elsewhere = os.path.join(bh, "elsewhere-tasks"); os.makedirs(elsewhere)
    wtasks = os.path.join(bwork, "tasks")
    if can_link(elsewhere, wtasks):
        pre = bhash()
        rc, out = bmove(sH, "--dry-run")
        rc2, out2 = bmove(sH)
        check(rc == 1 and rc2 == 1 and bhash() == pre and not os.listdir(elsewhere) and "outside cli:work" in out2
              and "undone" not in out2,
              "a folder of cli:work that leads outside it (tasks -> another folder) is refused, in the dry run too, "
              "before any write: nothing lands there")
        bundo(rc2, out2)
        os.remove(wtasks)
        other = os.path.join(bwork, "projects", "-other-project"); os.makedirs(other)
        wkey = os.path.join(bwork, "projects", bk)
        os.symlink(other, wkey, target_is_directory=True)
        pre = bhash()
        rc, out = bmove(sH)
        check(rc == 1 and bhash() == pre and "is a symlink" in out and not os.listdir(other) and "undone" not in out,
              "a symlinked folder inside cli:work (projects/<key> -> another project folder of it) is refused too")
        bundo(rc, out)
        os.remove(wkey); discard(other)
        os.makedirs(wkey)
        outm = os.path.join(bh, "outside-memory")
        outf = put(os.path.join(outm, "MEMORY.md"), "OUTSIDE-B1-xyz")
        os.symlink(outm, os.path.join(wkey, "memory"), target_is_directory=True)
        mode0 = os.stat(outf).st_mode & 0o7777
        pre = bhash()
        if os.name != "nt" and os.geteuid() != 0:
            os.chmod(outf, 0)
        try:
            rc, out = bmove(sH)
        finally:
            os.chmod(outf, mode0)
        check(rc == 1 and bhash() == pre and "outside cli:work" in out and "Traceback" not in out
              and os.listdir(outm) == ["MEMORY.md"],
              "a project memory folder in cli:work that leads outside it is refused before any file in it is read or "
              "written")
        bundo(rc, out)
        os.remove(os.path.join(wkey, "memory")); discard(wkey, outm)
    else:
        print("  (skipped target-link checks: this OS/user cannot create symlinks)")
    discard(elsewhere)

    # Rules that had no check (each was shown to matter by removing it from a copy of the tool).
    sJ, iJ, wJ = bsession(210, "a link inside its sidecar")
    lnk = os.path.join(iJ[1], "tool-results", "x.txt"); os.makedirs(os.path.dirname(lnk))
    if can_link(os.path.join(bdef, ".credentials.json"), lnk, is_dir=False):
        pre = bhash()
        rc, out = bmove(sJ, "--copy")
        check(rc == 1 and bhash() == pre and "x.txt is a symlink" in out and "undone" not in out
              and out.lower().count("nothing was changed") == 1
              and "DECOY-B1-CREDENTIAL" not in regular_text(bwork),
              "a symlink INSIDE a session folder (tool-results/x.txt -> the home's .credentials.json) is refused "
              "up front: --copy never follows it, and the credentials never reach cli:work")
        bundo(rc, out)
        os.remove(lnk)
    else:
        print("  (skipped inner-symlink check: this OS/user cannot create symlinks)")
    sK, iK, wK = bsession(211, "the target has its own todo")
    theirs = put(wK[4], '["the target\'s own todo"]')
    pre = bhash()
    rc, out = bmove(sK)
    check(rc == 1 and bhash() == pre and readb(theirs) == b'["the target\'s own todo"]' and "already has" in out
          and "todos" in out,
          "an item cli:work already has (its own todos/<id>-agent-*.json) is refused: never overwritten, nothing "
          "written")
    bundo(rc, out)
    discard(theirs)
    sL, iL, wL = bsession(212, "old, then grown in cli:work")
    oldL = time.time() - 60 * 86400
    os.utime(iL[0], (oldL, oldL))
    rc, out = bmove(sL)
    la = arch_in(out)
    check(rc == 0 and mtime_age(wL[0]) < 120, "(fixture) the 60-day-old transcript was re-dated in cli:work")
    append_turn(wL[0], sL, "it went on in cli:work")
    grown = readb(wL[0])
    rc, out = brun("rollback", "cli:work", la)
    check(rc == 0 and readb(iL[0]) == grown and mtime_age(iL[0]) < 120,
          "rollback restores the original mtime only when the content is unchanged: "
          "a transcript that grew in cli:work keeps its current mtime (not 60 days ago, which retention would delete)")

    # Special files: a FIFO is never opened (it would wait for a writer for ever), a socket or device never copied.
    if hasattr(os, "mkfifo"):
        sE, iE, wE = bsession(205, "a FIFO in its sidecar")
        fifo = os.path.join(iE[1], "subagents", "pipe")
        os.mkfifo(fifo)
        pre = bhash()
        rc, out = bmove(sE, "--dry-run", timeout=30)
        check(rc == 1 and bhash() == pre and "is a FIFO" in out,
              "dry run: a FIFO inside a session's sidecar folder is refused (exit 1), without waiting on it")
        rc, out = bmove(sE, timeout=30)
        check(rc == 1 and bhash() == pre and "is a FIFO" in out and "undone" not in out,
              "the real move refuses it before anything is written or hashed: no hang, no archive, nothing changed")
        bundo(rc, out)
        discard(fifo, os.path.join(wE[1], "subagents", "pipe"))
        mfifo = os.path.join(bdef, "projects", bk, "memory", "pipe.md")
        os.mkfifo(mfifo)
        pre = bhash()
        rc, out = bmove(sE, "--dry-run", timeout=30)
        check(rc == 1 and bhash() == pre and "is a FIFO" in out and "--no-memory" in out,
              "dry run: a FIFO in the project memory is refused before any memory file is read (no hang); the "
              "message names --no-memory")
        discard(mfifo)
        sock = os.path.join(iE[2], "agent.sock")
        here = os.getcwd()
        try:
            import socket
            os.chdir(os.path.dirname(sock))           # a short relative name: AF_UNIX paths are limited to ~100 bytes
            sk = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); sk.bind(os.path.basename(sock)); sk.close()
            made_sock = True
        except (OSError, AttributeError, ImportError):
            made_sock = False
        finally:
            os.chdir(here)
        if made_sock:
            pre = bhash()
            rc, out = bmove(sE, timeout=30)
            check(rc == 1 and bhash() == pre and "is a socket" in out and "Traceback" not in out,
                  "a socket in tasks/<id>/ is refused the same way, and nothing is written")
            bundo(rc, out)
            discard(sock, os.path.join(wE[2], "agent.sock"))
        sG = bid(207)
        tG = os.path.join(bdef, "projects", bk, sG + ".jsonl")
        os.mkfifo(tG)
        pre = bhash()
        rc, out = brun("sessions", "cli", timeout=30)
        rc2, out2 = brun("move", "cli", "--only", sG[:8], "--to-profile", "cli:work", timeout=30)
        check(rc == 0 and rc2 == 1 and bhash() == pre and "is a FIFO" in out2,
              "a transcript that is itself a FIFO: sessions does not wait on it, and the move refuses it")
        bundo(rc2, out2)
        discard(tG, os.path.join(bwork, "projects", bk, sG + ".jsonl"))
        # In the receiving home, and in what a rollback hashes there: a second project with an empty memory file (a
        # FIFO has size 0 too, so only its content could tell them apart).
        bproj2 = os.path.realpath(os.path.join(bh, "Projects", "two")); os.makedirs(bproj2)
        bk2 = cr2.mangle(bproj2)
        sQ = bid(215)
        tQ = cli_transcript(bdef, bk2, sQ, bproj2, title="empty memory")
        emp = put(os.path.join(bdef, "projects", bk2, "memory", "EMPTY.md"), "")
        wemp = os.path.join(bwork, "projects", bk2, "memory", "EMPTY.md")
        os.makedirs(os.path.dirname(wemp)); os.mkfifo(wemp)
        pre = bhash()
        rc, out = brun("move", "cli", "--only", sQ[:8], "--to-profile", "cli:work", timeout=30)
        check(rc == 1 and bhash() == pre and "is a FIFO" in out and "Traceback" not in out,
              "a FIFO where cli:work keeps a project memory file is refused before it is opened (no hang)")
        bundo(rc, out)
        os.remove(wemp)
        rc, out = brun("move", "cli", "--only", sQ[:8], "--to-profile", "cli:work")
        qa = arch_in(out)
        ok = rc == 0 and os.path.isfile(wemp)
        if ok:
            os.remove(wemp); os.mkfifo(wemp)             # what cli:work has there now is a FIFO, not the copy
        rc, out = brun("rollback", "cli", qa, timeout=30)
        check(ok and rc == 0 and "kept changed memory file" in out and os.path.exists(tQ),
              "rollback: a copied memory file that is a FIFO in cli:work now is kept as changed, never opened "
              "(no hang)")
        discard(wemp, os.path.join(bdef, "projects", bk2), os.path.join(bwork, "projects", bk2))
        sR, iR, wR = bsession(216, "copied; a FIFO appears in the copy")
        rc, out = bmove(sR, "--copy")
        ra = arch_in(out)
        rfifo = os.path.join(wR[1], "subagents", "pipe")
        if rc == 0:
            os.mkfifo(rfifo)
        rc, out = brun("rollback", "cli:work", ra, timeout=30)
        check(rc == 0 and "kept the copy" in out and os.path.lexists(rfifo) and os.path.exists(wR[0]),
              "rollback of a --copy move whose copy now holds a FIFO keeps that copy as changed, without opening the "
              "FIFO (no hang)")
        discard(*wR, wbmem)
    else:
        print("  (skipped special-file checks: this OS has no FIFOs)")

    # Interruptions: Ctrl-C between a rename and the move's own note of it; SIGTERM, SIGHUP; an undo that cannot
    # bring everything back.
    for n, fault, what in (
            (201, "int-after-place:2",
             "Ctrl-C right after an item got its name in cli:work, before the move noted it: still undone, "
             "every home exactly as before, the archive removed"),
            (202, "exdev,int-after-place:1",
             "the same for a cross-device copy that got its name in cli:work: the copy is removed, the source stays"),
            (203, "int-after-place:5", "the same for a project memory file copied into cli:work")):
        sA, iA, wA = bsession(n, "interrupted")
        pre = bhash()
        rc, out = bmove(sA, env={"CCD_REHOME_FAULT": fault})
        check(rc == 1 and bhash() == pre and "undone" in out and "Traceback" not in out and not tmp_left(bh)
              and not os.path.exists(wbmem), what)
    if os.name != "nt":
        import signal
        for fault, name, what in (
                ("term-after:2", "SIGTERM",
                 "a SIGTERM during the move (an agent's timeout, a kill) undoes it as Ctrl-C does"),
                ("hup-after:3", "SIGHUP",
                 "a SIGHUP during the move (the terminal closed) undoes it as Ctrl-C does")):
            pre = bhash()
            rc, out = bmove(sA, env={"CCD_REHOME_FAULT": fault})
            check(rc == 1 and bhash() == pre and "undone" in out and name in out, what)
        sN, iN, wN = bsession(214, "moved under nohup")
        rc, out = run(bh, "move", "cli", "--only", sN[:8], "--to-profile", "cli:work",
                      env={"CCD_REHOME_FAULT": "hup-after:3"}, pre=lambda: signal.signal(signal.SIGHUP, signal.SIG_IGN))
        bouts.append(out)
        check(rc == 0 and all(os.path.lexists(p) for p in wN) and not any(os.path.lexists(p) for p in iN),
              "a SIGHUP the caller ignores (nohup) stays ignored: that move goes on and completes")
        if rc == 0:
            brun("rollback", "cli", arch_in(out))
        drv = os.path.join(home, "b1-signals.py")
        open(drv, "w", encoding="utf-8").write(
            "import importlib.machinery, importlib.util, signal, sys\n"
            "sys.dont_write_bytecode = True\n"
            "def mine(signum, frame):\n    pass\n"
            "for s in (signal.SIGTERM, signal.SIGHUP):\n    signal.signal(s, mine)\n"
            "before = {s: signal.getsignal(s) for s in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}\n"
            "spec = importlib.util.spec_from_loader('ccd_rehome', importlib.machinery.SourceFileLoader('ccd_rehome', "
            "sys.argv[1]))\n"
            "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
            "sys.argv = ['ccd-rehome'] + sys.argv[2:]\n"
            "try:\n    m.main()\nexcept SystemExit as e:\n    print(e.code)\n"
            "after = {s: signal.getsignal(s) for s in before}\n"
            "print('SIGNALS ' + ('RESTORED' if after == before else 'CHANGED %r' % (after,)))\n")
        rc, out = brun("move", "cli", "--only", sA[:8], "--to-profile", "cli:work", argv=[drv, TOOL])
        bundo(0 if "done:" in out else 1, out)
        rc2, out2 = brun("move", "cli", "--only", sA[:8], "--to-profile", "cli:work", argv=[drv, TOOL],
                         env={"CCD_REHOME_FAULT": "fail-after:1"})
        check("done:" in out and "SIGNALS RESTORED" in out and "undone" in out2 and "SIGNALS RESTORED" in out2,
              "after a move, and after one that failed and was undone, "
              "the caller's SIGINT, SIGTERM and SIGHUP handlers are back")
    sB, iB, wB = bsession(204, "an item vanishes from cli:work")
    rc, out = bmove(sB, env={"CCD_REHOME_FAULT": "vanish:2,fail-after:3"})
    va = arch_in(out)
    check(rc == 1 and va in kept_archives() and "rollback" in out and "nothing was changed" not in out.lower()
          and not os.path.lexists(iB[2]) and not os.path.lexists(wB[2]),
          "when its undo cannot bring every item back (another process removed one from cli:work), "
          "the move keeps its archive, names the rollback, and never says that nothing was changed")
    put(os.path.join(iB[2], "1.json"), "{}")
    rc, out = brun("rollback", "cli", va)
    check(rc == 0 and all(os.path.lexists(p) for p in iB) and not any(os.path.lexists(p) for p in wB),
          "(fixture) with the lost folder back by hand, the kept archive's rollback finds nothing left to move")

    # The only copy left: a rollback never removes a copy whose original is gone.
    sC, iC, wC = bsession(206, "copied, then the original deleted")
    rc, out = bmove(sC, "--copy")
    ca = arch_in(out)
    check(rc == 0 and all(os.path.lexists(p) for p in wC + iC), "(fixture) --copy puts a copy in cli:work")
    savedC = readb(iC[0])
    discard(*iC)
    rc, out = brun("rollback", "cli:work", ca)
    check(rc == 0 and all(os.path.lexists(p) for p in wC) and readb(wC[0]) == savedC and "only" in out,
          "rollback of a --copy move keeps the copy when the original was deleted from cli since: it may be the only "
          "one left, and the rollback says so")
    discard(*wC, wbmem)
    sD, iD, wD = bsession(209, "moved; its project memory then deleted from cli")
    rc, out = bmove(sD)
    da = arch_in(out)
    check(rc == 0 and "    copy " + os.path.join("projects", bk, "memory", "MEMORY.md") in out
          and os.path.exists(wbmem),
          "(fixture) the move copies the project memory into cli:work")
    savedm = readb(bmem)
    os.remove(bmem)
    rc, out = brun("rollback", "cli", da)
    check(rc == 0 and readb(wbmem) == savedm and os.path.exists(iD[0]) and "only" in out,
          "rollback keeps a copied memory file whose original was deleted from cli since (the only one left), and "
          "says so")
    put(bmem, savedm or b""); discard(wbmem)

    # Rollback writes into cli: the same containment as a move's target.
    sI, iI, wI = bsession(213, "rolled back into a linked folder")
    rc, out = bmove(sI)
    ia = arch_in(out)
    fh, fh_real = os.path.join(bdef, "file-history"), os.path.join(bdef, "file-history.real")
    efh = os.path.join(bh, "elsewhere-fh"); os.makedirs(efh)
    os.rename(fh, fh_real)
    if rc == 0 and can_link(efh, fh):
        pre = bhash()
        rc, out = brun("rollback", "cli:work", ia)
        check(rc == 1 and bhash() == pre and not os.listdir(efh) and "outside cli" in out and "Traceback" not in out,
              "rollback refuses to move a session back through a folder of cli that now leads outside it, and changes "
              "nothing")
        for n_ in os.listdir(efh):
            os.rename(os.path.join(efh, n_), os.path.join(fh_real, n_))
        os.remove(fh)
    os.rename(fh_real, fh); discard(efh)
    rc, out = brun("rollback", "cli:work", ia)
    check(rc == 0 and all(os.path.lexists(p) for p in iI) and not any(os.path.lexists(p) for p in wI),
          "(fixture) with the real folder back, that rollback finishes")
    check(not any(x in o for o in bouts for x in ("DECOY-B1-CREDENTIAL", "OUTSIDE-B1-xyz")),
          "no output of this section shows the decoy credentials or the outside memory's contents")

    print("Second review of messages: an empty login file, a refusal said once, unregister on Windows, how many "
          "archives status shows")
    # A home of its own: ~/.claude (signed in), ~/.claude-work (no login file), ~/.claude-empty (an EMPTY login file),
    # one account and org, and a Desktop profile acct-u.
    mh = os.path.join(home, "msg-homes"); os.makedirs(mh)
    mouts = []

    def mrun(*args, env=None):
        rc, out = run(mh, *args, env=env)
        mouts.append(out)
        return rc, out

    def once(out):
        return out.lower().count("nothing was changed") == 1

    mdef, mwork, mempty = (os.path.join(mh, n) for n in (".claude", ".claude-work", ".claude-empty"))
    for d in (mdef, mwork, mempty):
        os.makedirs(os.path.join(d, "projects"))
    for gc in (os.path.join(mh, ".claude.json"), os.path.join(mwork, ".claude.json"),
               os.path.join(mempty, ".claude.json")):
        json.dump({"oauthAccount": {"accountUuid": A, "emailAddress": EMAIL[A], "organizationUuid": OA,
                                    "organizationName": "Org A"}}, open(gc, "w", encoding="utf-8"))
    open(os.path.join(mdef, ".credentials.json"), "w", encoding="utf-8").write("DECOY-MSG-CREDENTIAL")
    open(os.path.join(mempty, ".credentials.json"), "w", encoding="utf-8").close()      # empty: no login in it
    mproj = os.path.realpath(os.path.join(mh, "Projects", "mu")); os.makedirs(mproj)
    mk = cr2.mangle(mproj)
    M = ["5%d5%d5%d5%d-0000-4000-8000-00000000080%d" % ((n,) * 5) for n in range(1, 10)]
    for sid in M:
        cli_transcript(mdef, mk, sid, mproj, title="msg " + sid[:8])
    MW1 = "6a6a6a6a-0000-4000-8000-000000000901"                 # only in cli:work
    cli_transcript(mwork, mk, MW1, mproj, title="msg in work")
    mwork_rp = os.path.realpath(mwork)

    # ---- an empty .credentials.json (R9)
    for plat, penv in (("Linux", lin), ("Windows", win)):
        rc, out = mrun("status", "cli:empty", env=penv)
        check(rc == 0 and "SIGNED-OUT" in out and "is empty" in out and "no login file" not in out,
              f"{plat}: an empty .credentials.json is reported as empty (signed out), not as 'no login file'")
    rc, out = mrun("status", "cli:empty", env=mac)
    check(rc == 0 and "SIGNED-IN" not in out and "UNKNOWN" in out and "is empty" in out,
          "macOS: an empty .credentials.json holds no login either: unknown (the Keychain may hold one), not signed "
          "in, and it says the file is empty")
    rc, out = mrun("move", "cli", "--only", M[0][:8], "--to-profile", "cli:empty", "--dry-run", env=lin)
    check(rc == 0 and "cli:empty is signed out" in out and "is empty" in out and "no login file" not in out
          and "sign in there" in out,
          "a move into it warns that it is signed out because its login file is empty")
    rc, out = mrun("status", "cli:work", env=lin)
    check(rc == 0 and "SIGNED-OUT" in out and "no login file" in out and "is empty" not in out,
          "a home with no .credentials.json at all still says 'no login file'")

    # ---- a refusal says "nothing was changed" once (R9)
    mrun("status", "cli", "cli:work")      # (both homes named once: the tool remembers a home it is given)
    wt = os.path.join(mwork, "projects", mk, M[1] + ".jsonl")
    open(wt, "w", encoding="utf-8").write('{"type": "user", "cwd": "elsewhere"}\n')
    for d in (mdef, mwork):
        os.makedirs(os.path.join(d, "todos"), exist_ok=True)
        open(os.path.join(d, "todos", M[2] + "-agent-" + M[2] + ".json"), "w", encoding="utf-8").write("[]")
    mpre = refusal_hash(mh)
    rc, out = mrun("move", "cli", "--only", M[1][:8], "--to-profile", "cli:work")
    check(rc == 1 and refusal_hash(mh) == mpre and "DIFFERENT transcript" in out and once(out),
          "a refusal (cli:work has a DIFFERENT transcript) says 'nothing was changed' once, not twice")
    rc, out = mrun("move", "cli", "--only", M[2][:8], "--to-profile", "cli:work")
    check(rc == 1 and refusal_hash(mh) == mpre and "already has" in out and once(out),
          "the same for an item cli:work already has (its own todos file)")
    rc, out = mrun("move", "cli", "--only", M[1][:8], M[2][:8], "--to-profile", "cli:work")
    check(rc == 1 and refusal_hash(mh) == mpre and out.count("REFUSE") == 2 and "and more above" in out and once(out),
          "two refusals: both REFUSE lines, then 'nothing was changed' once")
    rc, out = mrun("move", "cli", "--only", M[1][:8], "--to-profile", "cli:work", "--dry-run")
    check(rc == 1 and refusal_hash(mh) == mpre and "nothing was written" in out
          and "nothing was changed" not in out.lower(),
          "the dry run of it says 'nothing was written', and never 'nothing was changed'")
    os.remove(wt); os.remove(os.path.join(mwork, "todos", M[2] + "-agent-" + M[2] + ".json"))
    msd = os.path.join(mdef, "projects", mk, M[3], "tool-results"); os.makedirs(msd)
    mout_f = os.path.join(mh, "outside.txt"); open(mout_f, "w", encoding="utf-8").write("outside")
    if can_link(mout_f, os.path.join(msd, "x.txt"), is_dir=False):
        mpre = refusal_hash(mh)
        rc, out = mrun("move", "cli", "--only", M[3][:8], "--to-profile", "cli:work")
        check(rc == 1 and refusal_hash(mh) == mpre and "x.txt is a symlink" in out and once(out),
              "the same for a symlink inside a session folder")
    else:
        print("  (skipped the symlink message check: this OS/user cannot create symlinks)")
    shutil.rmtree(os.path.join(mdef, "projects", mk, M[3]))
    os.makedirs(os.path.join(mdef, "tasks", M[4]))
    open(os.path.join(mdef, "tasks", M[4], "t"), "w", encoding="utf-8").write("t")
    rc, out = mrun("move", "cli", "--only", M[4][:8], "--to-profile", "cli:work")
    ma4 = arch_in(out)
    check(rc == 0 and os.path.isdir(os.path.join(mwork, "tasks", M[4])), "(fixture) a move with a tasks folder")
    mtasks, mtasks_real, mels = os.path.join(mdef, "tasks"), os.path.join(mdef, "tasks.real"), os.path.join(mh, "els")
    os.makedirs(mels); os.rename(mtasks, mtasks_real)
    if can_link(mels, mtasks):
        mpre = refusal_hash(mh)
        rc, out = mrun("rollback", "cli:work", ma4)
        check(rc == 1 and refusal_hash(mh) == mpre and "outside cli" in out and once(out),
              "a rollback refusal (a folder of cli now leads outside it) says 'nothing was changed' once too")
        os.remove(mtasks)
    else:
        print("  (skipped the rollback message check: this OS/user cannot create symlinks)")
    os.rename(mtasks_real, mtasks)
    rc, out = mrun("rollback", "cli:work", ma4)
    check(rc == 0 and os.path.isdir(os.path.join(mdef, "tasks", M[4])), "(fixture) and that rollback then finishes")

    # ---- unregister's hint in the syntax of the shell it is for (R9)
    macct = profile(mh, "acct-u", signed_in=A, logs=[init("09:00:00", A, OA)])
    udir = os.path.join(macct, "claude-code-sessions", A, OA)
    rec(udir, "u5", "unreg default", cliSessionId=M[5], cwd=mproj)
    rec(udir, "u6", "unreg work", cliSessionId=MW1, cwd=mproj)
    rc, out = mrun("unregister", "acct-u", "--only", "u5", "--dry-run", env=win)
    lines = [l for l in out.splitlines() if "claude --resume " + M[5] in l]
    check(rc == 0 and any(f'cd /d "{mproj}" && claude --resume {M[5]}' in l and "(cmd)" in l for l in lines)
          and any(f"Set-Location -LiteralPath '{mproj}'; claude --resume {M[5]}" in l and "(PowerShell)" in l
                  for l in lines)
          and not any(f"cd '{mproj}'" in l for l in lines),
          "Windows: unregister's hint is in cmd and PowerShell syntax (cd /d, Set-Location), not POSIX `cd '...' &&`")
    rc, out = mrun("unregister", "acct-u", "--only", "u5", "--dry-run", env=lin)
    check(rc == 0 and f"cd '{mproj}' && claude --resume {M[5]}" in out,
          "elsewhere unregister's hint is the one POSIX line, as before")
    rc, out = mrun("unregister", "acct-u", "--only", "u6", "--dry-run", env=win)
    lines = [l for l in out.splitlines() if "claude --resume " + MW1 in l]
    check(rc == 0 and any(f'set "CLAUDE_CONFIG_DIR={mwork_rp}" && claude --resume {MW1}' in l for l in lines)
          and any(f"$env:CLAUDE_CONFIG_DIR='{mwork_rp}'; claude --resume {MW1}" in l for l in lines),
          "Windows: for a conversation in cli:work the hint sets CLAUDE_CONFIG_DIR the cmd and the PowerShell way")
    rc, out = mrun("unregister", "acct-u", "--only", "u6", "--dry-run", env=lin)
    check(rc == 0 and f"cd '{mproj}' && CLAUDE_CONFIG_DIR='{mwork_rp}' claude --resume {MW1}" in out,
          "elsewhere it names CLAUDE_CONFIG_DIR=<cli:work> on the POSIX line: the home that holds the transcript")

    # ---- status says how many archives there are when it shows only the newest (R9)
    made = []          # into cli:empty, which has no other archive
    for sid in (M[0], M[6], M[7]):
        rc, out = mrun("move", "cli", "--only", sid[:8], "--to-profile", "cli:empty")
        made.append(arch_in(out))
    rc, out = mrun("status", "cli:empty")
    aline = next((l for l in out.splitlines() if "archives" in l), "")
    check(rc == 0 and "none" not in made and all(a in aline for a in made) and "in all" not in aline
          and "--json" not in aline,
          "with 3 archives, status (text) shows all three and no count")
    rc, out = mrun("move", "cli", "--only", M[8][:8], "--to-profile", "cli:empty")
    made.append(arch_in(out))
    rc, out = mrun("status", "cli:empty")
    aline = next((l for l in out.splitlines() if "archives" in l), "")
    check(rc == 0 and "none" not in made and made[0] not in out and all(a in aline for a in made[1:])
          and "4 in all" in aline and "ccd-rehome status cli:empty --json" in aline,
          "with 4 archives, status (text) shows the newest 3, says there are 4 in all, and that "
          "`status cli:empty --json` lists them all")
    rows = j(mh, "status", "cli:empty")
    check(isinstance(rows, list) and rows and rows[0].get("archives") == sorted(made),
          "and status cli:empty --json lists all 4")
    uarch = os.path.join(sdir(mh), "archive", "acct-u")
    for n in range(4):
        os.makedirs(os.path.join(uarch, "2026010%dT000000Z-move" % (n + 1)))
    rc, out = mrun("status", "acct-u")
    aline = next((l for l in out.splitlines() if "archives" in l), "")
    check(rc == 0 and "20260101T000000Z-move" not in aline and "20260104T000000Z-move" in aline
          and "4 in all" in aline and "ccd-rehome status acct-u --json" in aline,
          "the same for a Desktop profile with 4 archives")
    check(not any("DECOY-MSG-CREDENTIAL" in o for o in mouts),
          "no output of this section shows the decoy credentials")

    print("Second review of the docs: where a Desktop move leaves the conversation, and which refusal a name that "
          "is no home prints")
    # The troubleshooting rows say which message each kind of name prints; these checks pin that. A home of its own:
    # ~/.claude (one session), ~/.claude-work, ~/.claude-desk (a Desktop window folder: it has a config.json), and a
    # plain folder that is neither.
    nh = os.path.join(home, "names-root"); os.makedirs(nh)
    ndef, nwork = os.path.join(nh, ".claude"), os.path.join(nh, ".claude-work")
    for d in (ndef, nwork):
        os.makedirs(os.path.join(d, "projects"))
    json.dump({"oauthAccount": {"accountUuid": A, "emailAddress": EMAIL[A], "organizationUuid": OA}},
              open(os.path.join(nh, ".claude.json"), "w", encoding="utf-8"))
    os.makedirs(os.path.join(nh, ".claude-desk"))
    json.dump({}, open(os.path.join(nh, ".claude-desk", "config.json"), "w", encoding="utf-8"))
    nplain = os.path.join(nh, "plain-folder"); os.makedirs(nplain)
    nmiss = os.path.join(nh, "no-such-folder")
    nproj = os.path.realpath(os.path.join(nh, "Projects", "nu")); os.makedirs(nproj)
    cli_transcript(ndef, cr2.mangle(nproj), "7e7e7e7e-0000-4000-8000-000000000a01", nproj, title="names")

    def nhash():
        return tree_hash(nh, skip=os.path.join(sdir(nh), "accounts.json"))

    rc, out = run(nh, "--help")
    hflat = " ".join(out.split())
    check(rc == 0 and "the conversation is shared" not in hflat and "the conversation stays in its CLI home" in hflat,
          "--help: a Desktop move --to-profile moves the record only, and the conversation stays in its CLI home (it "
          "no longer says the conversation is shared: each CLAUDE_CONFIG_DIR home has its own)")

    run(nh, "status", "cli", "cli:work")             # the state folder and the remembered names, before the hash
    npre = nhash()
    config_dir = ("is not a Claude Code config dir (no projects/, .claude.json, .credentials.json or settings.json), "
                  "or it is a Desktop profile")
    for label, args, want in (
            ("a path that does not exist, as what `move` works on", ("move", nmiss, "--to-profile", "cli:work"),
             f"{nmiss} does not exist"),
            ("the same, for `status`", ("status", nmiss), f"{nmiss} does not exist"),
            ("a Desktop profile name that names no folder", ("status", "acct-none"), "acct-none does not exist"),
            ("a folder that is neither a Desktop profile nor a CLI home, as what `move` works on",
             ("move", nplain, "--to-profile", "cli:work"), f"{nplain} is not a Desktop profile (no config.json)"),
            ("a path that does not exist, as a CLI move's --to-profile", ("move", "cli", "--to-profile", nmiss),
             f"--to-profile {nmiss!r} is not a CLI home"),
            ("a folder that is no CLI home, as a CLI move's --to-profile", ("move", "cli", "--to-profile", nplain),
             f"--to-profile {nplain!r} is not a CLI home"),
            ("cli:NAME naming no folder", ("move", "cli", "--to-profile", "cli:nope"), config_dir),
            ("cli:NAME naming a Desktop window folder (~/.claude-desk has a config.json)", ("sessions", "cli:desk"),
             config_dir),
            ("the home folder itself, as a CLI move's --to-profile", ("move", "cli", "--to-profile", nh),
             "is your home folder (it holds ~/.claude and ~/.claude.json): it is not a Claude Code config dir")):
        rc, out = run(nh, *args)
        nflat = " ".join(out.split())
        by_path = nmiss in args or nplain in args
        check(rc == 1 and want in nflat and nhash() == npre and not (by_path and "Claude Code config dir" in nflat),
              f"{label}: refused with '{want.replace(nh, '~')}', as its troubleshooting row says, and nothing is "
              f"written")
    print("Third review: Windows directory junctions inside a session, its project memory and the target")
    # os.path.islink is False for a Windows directory junction, Python before 3.12 has no os.path.isjunction, and
    # os.walk walks into one, so on Windows the tool also takes a reparse point (FILE_ATTRIBUTE_REPARSE_POINT in
    # st_file_attributes) for a link. POSIX cannot make a junction: a unit check of the helper, then the test-only
    # switch CCD_REHOME_FAULT=reparse:PATH (honoured only in the sandbox, on the emulated Windows layout) makes the
    # folder at PATH one.
    import types
    reparse = getattr(cr2, "_reparse_point", lambda st: None)
    check(reparse(types.SimpleNamespace(st_file_attributes=0x400 | 0x10)) is True
          and reparse(types.SimpleNamespace(st_file_attributes=0x10)) is False and reparse(os.lstat(home)) is False,
          "the reparse-point helper: FILE_ATTRIBUTE_REPARSE_POINT (0x400) is a link; a plain folder (0x10) is not, and "
          "neither is a stat result without st_file_attributes (POSIX)")
    jh = os.path.join(home, "junctions"); os.makedirs(jh)
    jdef, jwork = os.path.join(jh, ".claude"), os.path.join(jh, ".claude-work")
    for d in (jdef, jwork):
        os.makedirs(os.path.join(d, "projects"))
    json.dump({"oauthAccount": {"accountUuid": A, "emailAddress": EMAIL[A], "organizationUuid": OA}},
              open(os.path.join(jh, ".claude.json"), "w", encoding="utf-8"))
    jproj = os.path.realpath(os.path.join(jh, "Projects", "jay")); os.makedirs(jproj)
    jk = cr2.mangle(jproj)
    J1 = "f1f1f1f1-0000-4000-8000-000000000b01"
    cli_transcript(jdef, jk, J1, jproj, title="junctions")
    jinner = os.path.join(jdef, "projects", jk, J1, "tool-results", "linked")   # stands in for a junction
    put(os.path.join(jinner, "out.txt"), "what a junction would lead to")
    jmem = os.path.join(jdef, "projects", jk, "memory", "linked")
    put(os.path.join(jmem, "notes.md"), "memory below a junction")
    put(os.path.join(jdef, "tasks", J1, "1.json"), "{}")
    jtasks = os.path.join(jwork, "tasks"); os.makedirs(jtasks)

    def jrun(*args, at=None):
        env = {"CCD_REHOME_PLATFORM": "win32"}
        if at:
            env["CCD_REHOME_FAULT"] = "reparse:" + at
        return run(jh, *args, env=env)

    def jhash():
        return tree_hash(jh, skip=os.path.join(sdir(jh, "win32"), "accounts.json"))

    jmove = ("move", "cli", "--only", J1[:8], "--to-profile", "cli:work")
    rc, out = jrun(*jmove, "--dry-run")
    check(rc == 0 and "would do the above" in out and "REFUSE" not in out,
          "(fixture) on the Windows layout, with no folder taken for a junction, the move's dry run goes ahead")
    jrun("status", "cli", "cli:work")                    # the state folder and the remembered names, before the hash
    for label, at, extra, want in (
            ("a junction inside the session's sidecar folder", jinner, (), jinner),
            ("a junction inside the sidecar folder, with --copy (a copy would follow it)", jinner, ("--copy",),
             jinner),
            ("a junction inside the project memory", jmem, (), jmem),
            ("a junction in the target (cli:work's tasks/)", jtasks, (), jtasks)):
        jpre = jhash()
        rc, out = jrun(*jmove, *extra, at=at)
        check(rc == 1 and jhash() == jpre and "REFUSE" in out and "symlink" in out
              and "~" + want[len(jh):] in out,
              f"Windows: {label} is refused like a symlink, and nothing is written")
        if rc == 0 and arch_in(out) != "none":          # a broken tool went ahead: undo it for the next check
            jrun("rollback", "cli", arch_in(out))

    print("Fourth review: copies for a conversation in another home, ~/.claude by a second name, CLI ids in the "
          "advice, a record's earlier conversations, walks that stop at a junction")
    # A home of its own: ~/.claude, ~/.claude-work, and ~/.claude-backup, which holds old transcripts that retention
    # has deleted from ~/.claude (the backup is never started, so it keeps them). A move re-dates such a transcript,
    # which only postpones ~/.claude's retention, so advice for a conversation in another home is a --copy (the
    # other home keeps its own). Desktop names its records local_<uuid4>: no record id here shares its first 8
    # characters with the CLI id it points at, so advice that names one where the other belongs cannot pass.
    fh = os.path.join(home, "fourth"); os.makedirs(fh)
    fstate = sdir(fh)
    fdef, fwork, fbak = (os.path.join(fh, n) for n in (".claude", ".claude-work", ".claude-backup"))
    for d in (fdef, fwork, fbak):
        os.makedirs(os.path.join(d, "projects"))
    for f in (os.path.join(fh, ".claude.json"), os.path.join(fwork, ".claude.json")):
        json.dump({"oauthAccount": {"accountUuid": A, "emailAddress": EMAIL[A], "organizationUuid": OA,
                                    "organizationName": "Org A"}}, open(f, "w", encoding="utf-8"))
    fproj = os.path.realpath(os.path.join(fh, "Projects", "phi")); os.makedirs(fproj)
    fk = cr2.mangle(fproj)
    FB1, FB2, FD1, FW1, FW2, FP0, FP1 = ("4%d4%d4%d4%d-0000-4000-8000-000000000c0%d" % ((n,) * 5) for n in range(1, 8))
    frid = lambda n: "0d0d0d%02d-dddd-4ddd-8ddd-%012d" % (n, n)       # Desktop record ids
    fold = time.time() - 60 * 86400                     # older than ~/.claude's cleanupPeriodDays (the default 30)
    for sid in (FB1, FB2):
        t = cli_transcript(fbak, fk, sid, fproj, title="old " + sid[:8])
        os.utime(t, (fold, fold))
    for sid in (FD1, FP0, FP1):
        cli_transcript(fdef, fk, sid, fproj, title="default " + sid[:8])
    for sid in (FW1, FW2):
        cli_transcript(fwork, fk, sid, fproj, title="work " + sid[:8])

    def fdesk(name, recs):
        p = profile(fh, name, signed_in=A, logs=[init("09:00:00", A, OA)])
        for n, sid, extra in recs:
            rec(os.path.join(p, "claude-code-sessions", A, OA), frid(n), "rec " + frid(n)[:8], cliSessionId=sid,
                cwd=fproj, **extra)
        return p
    fdesk("acct-k", [(1, FB1, {}), (2, FB2, {})])                  # every record's conversation is only in the backup
    fdesk("acct-m", [(3, FD1, {}), (4, FW1, {})])                  # one in ~/.claude, one in cli:work
    fdesk("acct-p", [(5, FP1, {"priorCliSessionIds": [FP0]})])     # FP0: that record's earlier conversation

    def frun(*args, env=None):
        return run(fh, *args, env=env)

    def fhash(state=True):
        return tree_hash(fh, skip=os.path.join(fstate, "accounts.json") if state else fstate)

    def fundo(rc, out, where, env=None):
        """A move that should have refused but went ahead (a broken tool) is undone for the next check."""
        if rc == 0 and arch_in(out) != "none" and "rolled back" not in out:
            frun("rollback", where, arch_in(out), env=env)

    fw1d, fw1w = (os.path.join(d, "projects", fk, FW1 + ".jsonl") for d in (fdef, fwork))
    rc, out = frun("sessions", "acct-k")
    adv = [l for l in out.splitlines() if "--to-profile cli" in l]
    check(rc == 0 and adv and all("--to-profile cli --copy" in l for l in adv)
          and any("ccd-rehome move cli:backup --only " in l and FB1 in l and FB2 in l for l in adv)
          and not any(frid(n)[:8] in l for l in adv for n in (1, 2)),
          "sessions PROFILE advises a COPY of conversations that live only in another home (a backup keeps its own): "
          "`move cli:backup --only <both CLI ids> --to-profile cli --copy`, never a move")
    rc, out = frun("sessions", "acct-m")
    row = next((l for l in out.splitlines() if l.strip().startswith(frid(4)[:8])), "")
    cmd = next((l for l in out.splitlines() if "--to-profile cli" in l), "")
    check(rc == 0 and "[in cli:work" in row and FW1[:8] in row and FW1 in cmd and "--copy" in cmd
          and frid(4)[:8] not in cmd and "assumes" not in out,
          "sessions PROFILE shows the CLI id of a record whose conversation is in another home, and the copy it prints "
          "names that CLI id in full, never the Desktop record id (for a profile with a record in ~/.claude too)")
    m = re.search(r"ccd-rehome (move cli:work --only \S+ --to-profile cli --copy)", cmd)
    pre = fhash()
    rc, out = frun(*m.group(1).split(), "--dry-run") if m else (None, "")
    check(rc == 0 and fhash() == pre and "would do the above" in out and "1 session(s)  [copy]" in out,
          "and that line runs as printed (its dry run plans the copy of that conversation into ~/.claude)")

    rc, out = frun("move", "cli:backup", "--only", FB1[:8], "--to-profile", "cli")
    warn = next((l for l in out.splitlines() if "older than 30 days" in l), "")
    fb1d, fb1b = (os.path.join(d, "projects", fk, FB1 + ".jsonl") for d in (fdef, fbak))
    check(rc == 0 and os.path.exists(fb1d) and "cli:backup no longer has it" in warn and "postpones" in warn
          and "--copy" in warn,
          "a real move (not --copy) of an old transcript warns that the source no longer has it, and that re-dating "
          "only postpones the target's retention; it names --copy")
    undo = re.search(r"^undo:\s+ccd-rehome (rollback \S+ \S+)", out, re.M)
    rc, out = frun(*undo.group(1).split()) if undo else (None, "")
    check(rc == 0 and os.path.exists(fb1b) and not os.path.exists(fb1d) and os.path.getmtime(fb1b) < time.time() - 86400,
          "(fixture) its undo puts it back in the backup with its old mtime")
    rc, out = frun("move", "cli:backup", "--only", FB1[:8], "--to-profile", "cli", "--copy", "--dry-run")
    warn = next((l for l in out.splitlines() if "older than 30 days" in l), "")
    check(rc == 0 and warn and "no longer has it" not in warn and "postpones" in warn,
          "with --copy the warning still says re-dating only postpones it, and not that the source loses it")
    pre = fhash()
    rc, out = frun("register", "acct-k", "--cli-session-id", FW2[:8], "--dry-run")
    check(rc == 1 and fhash() == pre and "ccd-rehome move cli:work --to-profile cli --only " + FW2 + " --copy" in out,
          "register of a conversation in another home prints the COPY into ~/.claude (its home keeps it)")
    rc, out = frun("move", "cli:work", "--only", FW1[:8], "--to-profile", "cli")
    undo = re.search(r"^undo:\s+ccd-rehome (rollback \S+ \S+)", out, re.M)
    rc2, out2 = frun(*undo.group(1).split()) if undo else (None, "")
    check(rc == 0 and rc2 == 0 and os.path.exists(fw1w) and not os.path.exists(fw1d) and "warning: " + FW1[:8] in out2
          and "ccd-rehome move cli:work --only " + FW1 + " --to-profile cli --copy" in out2,
          "a rollback that takes a listed conversation back out of ~/.claude prints the COPY that gives the window "
          "its conversation back")

    pre = fhash()
    rc, out = frun("move", "cli", "--only", FP0[:8], "--to-profile", "cli:work")
    check(rc == 1 and fhash() == pre and "REFUSE " + FP0[:8] in out and "acct-p" in out,
          "a conversation a record names among its earlier ones (priorCliSessionIds) stays in ~/.claude like its "
          "current one: the move out is refused, and nothing is written")
    fundo(rc, out, "cli")
    pre = fhash()
    rc, out = frun("move", "cli", "--only", FP0[:8], "--to-profile", "cli:work", "--copy", "--dry-run")
    check(rc == 0 and fhash() == pre and "would do the above" in out,
          "(guard) --copy of that earlier conversation still goes ahead (dry run)")

    # ~/.claude by a second name that realpath does not resolve: a bind mount, a macOS firmlink, ~/.Claude on a
    # case-insensitive disk. POSIX realpath resolves a symlink, so the test-only CCD_REHOME_FAULT=alias:PATH makes the
    # tool's realpath leave this one as it is (os.stat still sees through it, as it does a bind mount).
    falias = os.path.join(fh, "claude-by-another-name")
    if can_link(fdef, falias):
        aenv = {"CCD_REHOME_FAULT": "alias:" + falias}
        pre = fhash()
        rc, out = frun("move", falias, "--only", FD1[:8], "--to-profile", "cli:work", env=aenv)
        check(rc == 1 and fhash() == pre and "is shown by Desktop profile acct-m" in out,
              "~/.claude named by a second path that realpath does not resolve is still ~/.claude: the move out of a "
              "conversation a Desktop profile lists is refused, and nothing is written")
        fundo(rc, out, "cli:work")
        rc, out = frun("profiles", "--json", env=dict(aenv, CCD_REHOME_CLI_HOMES=falias))
        try:
            paths = [r.get("path") for r in json.loads(out) if r.get("kind") == "cli"]
        except (ValueError, TypeError, AttributeError):
            paths = None
        check(rc == 0 and paths is not None and falias not in paths and paths.count(os.path.realpath(fdef)) == 1,
              "that second name is never remembered or listed as a home of its own, even when $CCD_REHOME_CLI_HOMES "
              "names it (discovery)")
        rc, out = frun("move", "cli:work", "--only", FW1[:8], "--to-profile", "cli")
        fa = arch_in(out)
        rdef = os.path.realpath(fdef)

        def swap(x):
            """The manifest a move into ~/.claude named by its second path wrote (that name in every path)."""
            if isinstance(x, str):
                return falias + x[len(rdef):] if x == rdef or x.startswith(rdef + os.sep) else x
            if isinstance(x, list):
                return [swap(y) for y in x]
            return {k: swap(v) for k, v in x.items()} if isinstance(x, dict) else x
        mf = glob.glob(os.path.join(fstate, "cli-archive", "*", fa, "manifest.json"))
        if rc == 0 and mf:
            json.dump(swap(json.load(open(mf[0], encoding="utf-8"))), open(mf[0], "w", encoding="utf-8"))
        rc, out = frun("rollback", "cli", fa, env=aenv)
        check(rc == 0 and os.path.exists(fw1w) and not os.path.exists(fw1d) and "warning: " + FW1[:8] in out
              and "so that window cannot open it" in out,
              "rollback from `cli` finds an archive that names ~/.claude by that second path, and knows it takes a "
              "listed conversation back out of ~/.claude (a warning with the copy that gives it back)")
        if rc != 0 and os.path.exists(fw1d):
            frun("rollback", "cli:work", fa)
        os.remove(falias)
    else:
        print("  (skipped the second-name checks: this OS/user cannot create symlinks)")

    # Windows: a walk inside an item, the project memory or a copy in the target leaves a junction out BEFORE it
    # descends (os.walk before Python 3.12 walks into one). The junction fixture of the section above;
    # CCD_REHOME_FAULT=reparse:PATH also reports any listing of what is inside it.
    walked = "TEST-ONLY: listed inside the simulated junction"
    rc, out = jrun(*jmove, at=jinner)
    check(rc == 1 and "symlink" in out and walked not in out,
          "Windows: the walk inside a session's sidecar folder stops at a junction: nothing inside it is listed "
          "before the move is refused")
    if rc == 0 and arch_in(out) != "none":
        jrun("rollback", "cli", arch_in(out))
    rc, out = jrun(*jmove, at=jmem)
    check(rc == 1 and "symlink" in out and walked not in out,
          "(guard) Windows: the same for a junction in the project memory")
    if rc == 0 and arch_in(out) != "none":
        jrun("rollback", "cli", arch_in(out))
    rc, out = jrun(*jmove, "--copy")
    ja = arch_in(out)
    jcopy = os.path.join(jwork, "projects", jk, J1, "tool-results", "linked")    # the copy of jinner
    check(rc == 0 and os.path.isdir(jcopy), "(fixture) on the Windows layout, a --copy with no junction goes ahead")
    rc, out = jrun("rollback", "cli:work", ja, at=jcopy)
    check(rc == 0 and os.path.isdir(jcopy) and "kept the copy of " + J1[:8] in out and walked not in out,
          "Windows: the rollback of a --copy whose copy now holds a junction keeps that copy as changed, and never "
          "lists what is inside the junction")

    pairs = []
    for dp, dn, fn in os.walk(home):
        for n in fn:
            if n.startswith("local_") and n.endswith(".json"):
                try:
                    r = json.load(open(os.path.join(dp, n), encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                if isinstance(r, dict) and isinstance(r.get("cliSessionId"), str):
                    pairs.append((n[len("local_"):-len(".json")], r["cliSessionId"]))
    check(len(pairs) >= 10 and all(a[:8] != b[:8] for a, b in pairs),
          "(fixtures) no Desktop record id in this self-test shares its first 8 characters with the CLI id it points "
          "at")

    print("Fifth review: the status and rehome advice is a copy into the home of another account, --keep-dates "
          "refused where it loses the only copy, a record's earlier conversation, transcripts last continued in "
          "Desktop kept at any age")
    # ~/.claude and ~/.claude-backup are signed in to one account (a@example.com), ~/.claude-work to another
    # (b@example.com). The backup holds old conversations, 60 days old: G1 written in the terminal, G2 started in the
    # terminal and last continued in Claude Desktop, G3 the other way round. Claude Code keeps the transcript of a
    # session most recently continued in Desktop at any age unless desktopSessionCleanupPeriodDays is set
    # (https://code.claude.com/docs/en/claude-directory, "Cleaned up automatically"): of the three, only G1 and G3
    # are past ~/.claude's 30 days. ~/.claude holds Q1, a Desktop record's conversation, and Q0, its earlier one.
    vh = os.path.join(home, "fifth"); os.makedirs(vh)
    vstate = sdir(vh)
    vdef, vbak, vwork = (os.path.join(vh, n) for n in (".claude", ".claude-backup", ".claude-work"))
    for d, gc, acct, org in ((vdef, os.path.join(vh, ".claude.json"), A, OA),
                             (vbak, os.path.join(vbak, ".claude.json"), A, OA),
                             (vwork, os.path.join(vwork, ".claude.json"), B, OB)):
        os.makedirs(os.path.join(d, "projects"))
        json.dump({"oauthAccount": {"accountUuid": acct, "emailAddress": EMAIL[acct], "organizationUuid": org,
                                    "organizationName": "Org " + EMAIL[acct][0].upper()}},
                  open(gc, "w", encoding="utf-8"))
        open(os.path.join(d, ".credentials.json"), "w", encoding="utf-8").write("x")
    vproj = os.path.realpath(os.path.join(vh, "Projects", "psi")); os.makedirs(vproj)
    vk = cr2.mangle(vproj)
    G1, G2, G3, Q0, Q1, VW, Q2, Q3, G4 = ("8%d8%d8%d8%d-0000-4000-8000-000000000d0%d" % ((n,) * 5)
                                          for n in range(1, 10))
    vold = time.time() - 60 * 86400

    def vtranscript(base, sid, entrypoints, age=None):
        """A transcript with a user and an assistant record per entrypoint, in order, then a title record (no
        entrypoint), so its most recent records carry the last entrypoint."""
        d = os.path.join(base, "projects", vk); os.makedirs(d, exist_ok=True)
        rows = []
        for n, ep in enumerate(entrypoints):
            for role in ("user", "assistant"):
                rows.append({"type": role, "uuid": role[0] + str(n), "cwd": vproj, "entrypoint": ep, "sessionId": sid,
                             "timestamp": "2026-09-01T10:%02d:00.000Z" % n,
                             "message": {"role": role, "content": "turn %d" % n}})
        rows.append({"type": "custom-title", "customTitle": "fifth " + sid[:8], "sessionId": sid})
        p = os.path.join(d, sid + ".jsonl")
        open(p, "w", encoding="utf-8").write("".join(json.dumps(r) + "\n" for r in rows))
        if age:
            os.utime(p, (age, age))
        return p

    vb = {sid: vtranscript(vbak, sid, eps, vold) for sid, eps in
          ((G1, ("cli", "cli")), (G2, ("cli", "claude-desktop")), (G3, ("claude-desktop", "cli")))}
    vd = {sid: os.path.join(vdef, "projects", vk, sid + ".jsonl") for sid in (G1, G2, G3)}
    for sid in (Q0, Q1, Q2):
        vtranscript(vdef, sid, ("cli",))
    vtranscript(vwork, VW, ("cli",))
    # G4: its first lines are Desktop turns, and its last 256 KB (all the tool reads after the first 400 lines) hold
    # no record with an entrypoint, so its most recent turn is not known: it gets cleanupPeriodDays, which warns
    g4 = vtranscript(vbak, G4, ("claude-desktop",) * 220)
    open(g4, "a", encoding="utf-8").write("".join(json.dumps({"type": "summary", "summary": "x" * 900,
                                                               "leafUuid": "l%d" % n}) + "\n" for n in range(400)))
    os.utime(g4, (vold, vold))
    vrid, vrid2, vrid3 = ("0e0e0e0e-eeee-4eee-8eee-00000000000%d" % n for n in (1, 2, 3))
    vacct = profile(vh, "acct-v", signed_in=A, logs=[init("09:00:00", A, OA)])
    vrecs = os.path.join(vacct, "claude-code-sessions", A, OA)
    rec(vrecs, vrid, "rec with an earlier conversation", cliSessionId=Q1, priorCliSessionIds=[Q0], cwd=vproj)
    rec(vrecs, vrid2, "rec of Q2", cliSessionId=Q2, cwd=vproj)       # Q2: one record's current conversation,
    rec(vrecs, vrid3, "rec that had Q2", cliSessionId=Q3, priorCliSessionIds=[Q2], cwd=vproj)  # another's earlier
    vouts = []

    def fake_claude(name, text):
        """A PATH whose first `claude` prints `text` for --version: the Claude Code version a check needs, whatever is
        installed here (or none: text None gives a PATH with no `claude` on it)."""
        d = os.path.join(home, "fake-claude-" + name); os.makedirs(d)
        if text is None:
            extra = [os.path.join(os.environ.get("SystemRoot", "C:\\Windows"), "System32")] \
                if sys.platform.startswith("win") else []
            return {"PATH": os.pathsep.join([d] + extra)}
        if sys.platform.startswith("win"):
            with open(os.path.join(d, "claude.cmd"), "w", encoding="utf-8") as f:
                f.write("@echo " + text + "\r\n")
        else:
            with open(os.path.join(d, "claude"), "w", encoding="utf-8") as f:
                f.write("#!/bin/sh\necho '" + text + "'\n")
            os.chmod(os.path.join(d, "claude"), 0o755)
        return {"PATH": d + os.pathsep + os.environ.get("PATH", "")}

    VNEW, VOLD = fake_claude("new", "2.1.300 (Claude Code)"), fake_claude("old", "2.1.100 (Claude Code)")
    VUNK, VNONE = fake_claude("unknown", "Claude Code"), fake_claude("none", None)

    def vrun(*args, env=None):
        rc, out = run(vh, *args, env=env)
        vouts.append(out)
        return rc, out

    def vhash():
        return tree_hash(vh, skip=os.path.join(vstate, "accounts.json"))

    def vundo(rc, out):
        u = re.search(r"^undo:\s+ccd-rehome (rollback \S+ \S+)", out, re.M)
        return vrun(*u.group(1).split()) if rc == 0 and u else (None, "")

    def vline(out, sid):
        return next((l for l in out.splitlines() if l.strip().startswith(sid[:8])), "")

    vrun("status", "cli", "cli:backup", "cli:work")      # (every home named once: the tool remembers a home it is given)
    vpre0 = tree_hash(vh, skip=vstate)

    # ---- the status and rehome advice for a CLI home's sessions
    rc, out = vrun("status", "cli:work")
    check(rc == 0 and "ccd-rehome move cli:work --to-profile cli --copy" in out
          and "the home where that account is signed in" in out and EMAIL[A] in out,
          "status cli:work (signed in as b@example.com) advises a COPY of its sessions into ~/.claude, the home where "
          "the other account is signed in, never a move")
    rows = j(vh, "status", "cli:work")
    row = rows[0] if isinstance(rows, list) and rows and isinstance(rows[0], dict) else {}
    check(row.get("move") == "ccd-rehome move cli:work --to-profile cli --copy"
          and row.get("move_why") == "another-account",
          "status cli:work --json: \"move\" is that copy, and \"move_why\" says it is another account's home")
    rc, out = vrun("rehome", "cli:work")
    m = re.search(r"ccd-rehome (move cli:work --to-profile cli --copy)$", out, re.M)
    pre = vhash()
    rc2, out2 = vrun(*m.group(1).split(), "--dry-run") if m else (None, "")
    check(rc == 0 and m is not None and "the home where that account is signed in" in out and rc2 == 0
          and vhash() == pre and "1 session(s)  [copy]" in out2,
          "rehome cli:work prints the same copy, and it runs as printed (its dry run plans a copy)")
    rc, out = vrun("status", "cli:backup")
    check(rc == 0 and "ccd-rehome move cli:backup --to-profile cli:work --copy" in out and EMAIL[B] in out
          and not re.search(r"--to-profile cli(?![:\w])", out),
          "status cli:backup (the same account as ~/.claude) advises the copy into cli:work, the home of another "
          "account, and never offers ~/.claude as another account")

    # two homes of one account, and nothing else: no move or copy between them is an account switch
    sh = os.path.join(home, "fifth-same"); os.makedirs(sh)
    sdef, sbak = os.path.join(sh, ".claude"), os.path.join(sh, ".claude-backup")
    for d, gc in ((sdef, os.path.join(sh, ".claude.json")), (sbak, os.path.join(sbak, ".claude.json"))):
        os.makedirs(os.path.join(d, "projects"))
        json.dump({"oauthAccount": {"accountUuid": A, "emailAddress": EMAIL[A], "organizationUuid": OA,
                                    "organizationName": "Org A"}}, open(gc, "w", encoding="utf-8"))
        open(os.path.join(d, ".credentials.json"), "w", encoding="utf-8").write("x")
    for n in (1, 2):
        sp = cli_transcript(sbak, vk, "8e8e8e8e-0000-4000-8000-00000000000%d" % n, vproj, title="same %d" % n)
        os.utime(sp, (vold, vold))
    souts = []
    for cmd in (("status", "cli:backup"), ("rehome", "cli:backup"), ("status", "cli")):
        rc, out = run(sh, *cmd)
        souts.append(out)
        check(rc == 0 and "the same account as" in out and EMAIL[A] in out
              and "the home where that account is signed in" not in out and "another account, move" not in out
              and not re.search(r"--to-profile cli(?::backup)?(?![:\w])", out),
              f"`{' '.join(cmd)}` with two homes of one account says they have the same account, and prints no move "
              f"or copy between them as an account switch")
    rows = j(sh, "status", "cli:backup", "cli")
    check(isinstance(rows, list) and len(rows) == 2 and all(isinstance(r, dict) and r.get("move", "absent") is None
                                                            and r.get("move_why") == "same-account" for r in rows),
          "status --json of both: \"move\" is null and \"move_why\" is same-account")
    os.makedirs(os.path.join(sh, ".claude-new"))
    open(os.path.join(sh, ".claude-new", "settings.json"), "w", encoding="utf-8").write("{}")
    rc, out = run(sh, "status", "cli:backup")
    souts.append(out)
    rows = j(sh, "status", "cli:backup")
    check(rc == 0 and "ccd-rehome move cli:backup --to-profile cli:new --copy" in out and "not known" in out
          and "the home where that account is signed in" not in out and isinstance(rows, list) and rows
          and rows[0].get("move_why") == "account-unknown",
          "a home whose account is not known gets the copy, and is not called the home where that account is signed "
          "in (\"move_why\": account-unknown)")
    for cmd in (("sessions", "cli"), ("sessions", "cli:backup"), ("sessions", "cli:work"), ("status",)):
        vrun(*cmd)
    printed = [c for out in vouts + souts for c in re.findall(r"ccd-rehome move [^\n]*--to-profile[^\n]*", out)]
    check(len(printed) >= 8 and all("--copy" in c.split() for c in printed),
          "every move command that status, rehome and sessions print for a CLI home is a --copy (the source keeps "
          "its own; %d printed)" % len(printed))

    # ---- --keep-dates where the target's cleanup would delete the only copy
    pre = vhash()
    rc, out = vrun("move", "cli:backup", "--only", G1[:8], "--to-profile", "cli", "--keep-dates")
    ref = next((l for l in out.splitlines() if "REFUSE " + G1[:8] in l), "")
    check(rc == 1 and vhash() == pre and "--keep-dates" in ref and "next start" in ref and "use --copy" in ref,
          "a move (not --copy) with --keep-dates of a transcript the target's cleanup would delete is refused: the "
          "target would delete it at its next start and the source would no longer have it; it says to use --copy, "
          "and nothing is written")
    vundo(rc, out)
    rc, out = vrun("move", "cli:backup", "--only", G1[:8], "--to-profile", "cli", "--dry-run")
    warn = next((l for l in out.splitlines() if "warning: " + G1[:8] in l), "")
    check(rc == 0 and "older than 30 days" in warn and "use --copy" in warn and "--keep-dates" not in warn,
          "the warning on a move (not --copy) of an old transcript names --copy and never suggests --keep-dates")
    rc, out = vrun("move", "cli:backup", "--only", G1[:8], "--to-profile", "cli", "--copy", "--keep-dates")
    check(rc == 0 and os.path.exists(vb[G1]) and os.path.exists(vd[G1]) and abs(os.path.getmtime(vd[G1]) - vold) < 2,
          "(guard) --keep-dates with --copy goes ahead: the copy keeps the old date, and the source keeps its own")
    vundo(rc, out)

    # ---- a record's earlier conversation
    pre = vhash()
    rc, out = vrun("move", "cli", "--only", Q0[:8], "--to-profile", "cli:work")
    ref = next((l for l in out.splitlines() if "REFUSE " + Q0[:8] in l), "")
    check(rc == 1 and vhash() == pre and "earlier conversations" in ref and "use --copy" in ref
          and "ccd-rehome unregister" not in ref,
          "the refusal for a record's earlier conversation (priorCliSessionIds) advises --copy only, never "
          "unregistering that record (it would take the record's current conversation out of the window too)")
    vundo(rc, out)
    rc, out = vrun("move", "cli", "--only", Q1[:8], "--to-profile", "cli:work", "--dry-run")
    check(rc == 1 and "ccd-rehome unregister acct-v --only " + vrid in out,
          "(guard) for a record's current conversation the refusal still names the unregister")
    rc, out = vrun("move", "cli", "--only", Q2[:8], "--to-profile", "cli:work", "--dry-run")
    ref = next((l for l in out.splitlines() if "REFUSE " + Q2[:8] in l), "")
    check(rc == 1 and "record " + vrid3[:8] + " names it among its earlier conversations" in ref
          and "use --copy" in ref and "ccd-rehome unregister" not in ref,
          "a conversation that is one record's current one and another's earlier one: the refusal names the record "
          "that had it earlier and advises --copy only (unregistering the first would not free it)")

    # ---- which retention applies, read from the transcript's most recent records
    # (a plain move of such a transcript is the sixth review's: it depends on the Claude Code version here)
    rc, out = vrun("move", "cli:backup", "--only", G2[:8], "--to-profile", "cli", "--copy", env=VNEW)
    note = next((l for l in out.splitlines() if "note: " + G2[:8] in l), "")
    check(rc == 0 and os.path.exists(vd[G2]) and abs(os.path.getmtime(vd[G2]) - vold) < 2 and "older than" not in out
          and "2.1.248" in note and "cleanupPeriodDays" in note,
          "a transcript last continued in Claude Desktop, older than cleanupPeriodDays, is copied with no retention "
          "warning and is not re-dated (kept at any age unless desktopSessionCleanupPeriodDays is set); a note says "
          "that Claude Code before 2.1.248 deleted it after cleanupPeriodDays (Claude Code 2.1.300 here)")
    vundo(rc, out)
    vset = os.path.join(vdef, "settings.json")
    open(vset, "w", encoding="utf-8").write('{"desktopSessionCleanupPeriodDays": 20}')
    rc, out = vrun("move", "cli:backup", "--only", G2[:8], "--to-profile", "cli")
    warn = next((l for l in out.splitlines() if "warning: " + G2[:8] in l), "")
    check(rc == 0 and "older than 20 days (desktopSessionCleanupPeriodDays in cli)" in warn
          and os.path.exists(vd[G2]) and abs(os.path.getmtime(vd[G2]) - time.time()) < 120,
          "with desktopSessionCleanupPeriodDays set (20) in the target's settings.json, the same transcript warns "
          "with that limit and is re-dated")
    vundo(rc, out)
    os.remove(vset)
    rc, out = vrun("move", "cli:backup", "--only", G1[:8], "--to-profile", "cli")
    warn = next((l for l in out.splitlines() if "warning: " + G1[:8] in l), "")
    check(rc == 0 and "older than 30 days (cleanupPeriodDays in cli)" in warn and os.path.exists(vd[G1])
          and abs(os.path.getmtime(vd[G1]) - time.time()) < 120,
          "a transcript written in the terminal, older than cleanupPeriodDays, still warns with cleanupPeriodDays "
          "and is re-dated")
    vundo(rc, out)
    rc, out = vrun("move", "cli:backup", "--only", G2[:8], G3[:8], "--to-profile", "cli", "--copy", "--dry-run",
                   env=VNEW)
    check(rc == 0 and "warning: " + G3[:8] in out and "warning: " + G2[:8] not in out,
          "the most recent records decide: started in Desktop and last continued in the terminal warns, the other "
          "way round does not")
    rc, out = vrun("move", "cli:backup", "--only", G2[:8], "--to-profile", "cli", "--keep-dates", "--dry-run",
                   env=VNEW)
    check(rc == 0 and "REFUSE" not in out,
          "(guard) --keep-dates on a move of a transcript the target keeps at any age is not refused (Claude Code "
          "2.1.248 or later here)")
    rc, out = vrun("move", "cli:backup", "--only", G4[:8], "--to-profile", "cli", "--dry-run")
    check(rc == 0 and "older than 30 days (cleanupPeriodDays in cli)" in out and "note: " + G4[:8] not in out,
          "a transcript whose last 256 KB hold no entrypoint (its first lines are Desktop turns) gets "
          "cleanupPeriodDays: its most recent turn is not known, and the first lines do not decide")
    rc, out = vrun("sessions", "cli:backup")
    srows = {r.get("id"): r for r in (j(vh, "sessions", "cli:backup") or {}).get("sessions", [])}
    check(rc == 0 and "[older than 30 days]" in vline(out, G1) and "[older than 30 days]" in vline(out, G3)
          and "older than" not in vline(out, G2) and srows.get(G2, {}).get("older_than_days", 0) is None
          and srows.get(G2, {}).get("last_entrypoint") == "claude-desktop",
          "sessions cli:backup flags the terminal transcripts older than 30 days, and not the one last continued in "
          "Desktop (JSON: older_than_days null, last_entrypoint claude-desktop)")
    vbset = os.path.join(vbak, "settings.json")
    open(vbset, "w", encoding="utf-8").write('{"desktopSessionCleanupPeriodDays": 20}')
    rc, out = vrun("sessions", "cli:backup")
    check(rc == 0 and "[older than 20 days]" in vline(out, G2) and "[older than 30 days]" in vline(out, G1),
          "with desktopSessionCleanupPeriodDays (20) in that home's settings.json, it is flagged by that limit")
    os.remove(vbset)
    check(tree_hash(vh, skip=vstate) == vpre0, "(fixture) every move of this section was undone exactly")

    print("Sixth review: a plain move of an old transcript last continued in Desktop, managed settings, the sidecar "
          "files of a re-dated transcript, and the conversations of a Desktop window that are only in another home")
    # The fifth section's layout, every move of it undone: ~/.claude-backup holds G1 (terminal), G2 (last continued
    # in Desktop), G3 and G4, 60 days old. Claude Code before 2.1.248 deletes a Desktop transcript after
    # cleanupPeriodDays like any other, and the terminal `claude` (VNEW, VOLD, VUNK, VNONE: 2.1.300, 2.1.100, a
    # version it does not print, no `claude` at all) is what the tool can read of the version here.
    G5, T20 = "8a8a8a8a-0000-4000-8000-000000000d0a", "8b8b8b8b-0000-4000-8000-000000000d0b"
    g5 = vtranscript(vbak, G5, ("cli",), vold)
    g5side = os.path.join(vbak, "projects", vk, G5)
    g5files = {}
    for sub, name in (("subagents", "agent-a.jsonl"), ("tool-results", "toolu_1.txt"), ("mcp-tasks", "task.json"),
                      ("workflows", "run-1.json")):
        os.makedirs(os.path.join(g5side, sub))
        f = os.path.join(g5side, sub, name)
        open(f, "w", encoding="utf-8").write(sub * 10)
        os.utime(f, (vold, vold))
        g5files[os.path.join(sub, name)] = os.stat(f).st_mtime_ns
    t20 = vtranscript(vbak, T20, ("cli",), time.time() - 20 * 86400)
    vd[G5], vd[T20] = (os.path.join(vdef, "projects", vk, x + ".jsonl") for x in (G5, T20))
    six0 = tree_hash(vh, skip=vstate)

    def vwarn(out, sid, kind="warning"):
        return next((l for l in out.splitlines() if (kind + ": " + sid[:8]) in l), "")

    def fresh(p):
        return os.path.exists(p) and abs(os.path.getmtime(p) - time.time()) < 120

    def old(p):
        return os.path.exists(p) and abs(os.path.getmtime(p) - vold) < 2

    # ---- V1: a plain move (not --copy) of a transcript last continued in Desktop, older than cleanupPeriodDays
    rc, out = vrun("move", "cli:backup", "--only", G2[:8], "--to-profile", "cli", env=VNEW)
    w = vwarn(out, G2)
    check(rc == 0 and old(vd[G2]) and "`claude --version` here is 2.1.300" in w and "not re-dated" in w
          and "After this move cli:backup no longer has it (the archive holds no copy): use --copy to keep it in "
              "cli:backup too" in w,
          "a plain move of a transcript last continued in Desktop, older than cleanupPeriodDays, with Claude Code "
          "2.1.248 or later here: not re-dated, and a warning says so, that the source no longer has it and to use "
          "--copy")
    vundo(rc, out)
    rc, out = vrun("move", "cli:backup", "--only", G2[:8], "--to-profile", "cli", env=VOLD)
    w = vwarn(out, G2)
    check(rc == 0 and fresh(vd[G2]) and "older than 30 days (cleanupPeriodDays in cli)" in w
          and "`claude --version` here is 2.1.100" in w and "its mtime is set to now" in w
          and "no longer has it (the archive holds no copy): use --copy" in w,
          "the same move with Claude Code 2.1.100 here: re-dated (an earlier version deletes it after "
          "cleanupPeriodDays), and the warning names the version, the re-dating and --copy")
    vundo(rc, out)
    check(old(vb[G2]), "(fixture) its undo gives the backup's transcript back its old mtime")
    rc, out = vrun("move", "cli:backup", "--only", G2[:8], "--to-profile", "cli", env=VUNK)
    w = vwarn(out, G2)
    check(rc == 0 and fresh(vd[G2]) and "the version of Claude Code here is not known" in w
          and "its mtime is set to now" in w and "use --copy" in w,
          "the same move when `claude --version` prints no version: re-dated, and the warning says the version is "
          "not known")
    vundo(rc, out)
    rc, out = vrun("move", "cli:backup", "--only", G2[:8], "--to-profile", "cli", "--dry-run", env=VNONE)
    w = vwarn(out, G2)
    check(rc == 0 and "not known (no `claude` on PATH)" in w and "its mtime is set to now" in w,
          "with no `claude` on PATH the version is not known either, and the move would re-date it")
    for env, why in ((VOLD, "Claude Code 2.1.100 here"), (VUNK, "a version that is not known")):
        pre = vhash()
        rc, out = vrun("move", "cli:backup", "--only", G2[:8], "--to-profile", "cli", "--keep-dates", env=env)
        ref = next((l for l in out.splitlines() if "REFUSE " + G2[:8] in l), "")
        check(rc == 1 and vhash() == pre and "--keep-dates keeps that date" in ref and "next start" in ref
              and "last continued in Claude Desktop" in ref and "use --copy to keep it in cli:backup too" in ref,
              f"--keep-dates on that plain move with {why} is refused like a terminal transcript's, and nothing is "
              f"written")
        vundo(rc, out)
    vset = os.path.join(vdef, "settings.json")
    open(vset, "w", encoding="utf-8").write('{"desktopSessionCleanupPeriodDays": 90}')
    rc, out = vrun("move", "cli:backup", "--only", G2[:8], "--to-profile", "cli", "--dry-run", env=VOLD)
    w = vwarn(out, G2)
    rc2, out2 = vrun("move", "cli:backup", "--only", G2[:8], "--to-profile", "cli", "--dry-run", env=VNEW)
    w2 = vwarn(out2, G2)
    check(rc == 0 and "its mtime is set to now" in w and rc2 == 0 and "not re-dated" in w2
          and "until it is 90 days old (desktopSessionCleanupPeriodDays in cli)" in w2,
          "with desktopSessionCleanupPeriodDays 90 in the target, a 60-day-old Desktop transcript is still re-dated "
          "under Claude Code 2.1.100 (which ignores that setting), and under 2.1.300 the warning names the limit")
    os.remove(vset)
    rc, out = vrun("move", "cli:backup", "--only", G4[:8], "--to-profile", "cli", "--dry-run")
    check(rc == 0 and "no longer has it (the archive holds no copy): use --copy" in vwarn(out, G4),
          "(guard) a plain move of a transcript whose most recent entrypoint is not known says the source no longer "
          "has it, too")

    # ---- V2: managed settings rank above the home's settings.json
    if not cr2.SANDBOX:          # this process is not sandboxed: the tool's real paths, as the documentation gives them
        want = ("/Library/Application Support/ClaudeCode/managed-settings.json" if sys.platform == "darwin" else
                "C:\\Program Files\\ClaudeCode\\managed-settings.json" if sys.platform.startswith("win") else
                "/etc/claude-code/managed-settings.json")
        check(getattr(cr2, "managed_settings_path", lambda: None)() == want,
              "outside the sandbox the tool reads managed-settings.json where the documentation puts it (" + want + ")")
    plat = os.environ.get("CCD_REHOME_PLATFORM") or sys.platform
    mdir = os.path.join(vh, *(("Library", "Application Support", "ClaudeCode") if plat == "darwin" else
                              ("Program Files", "ClaudeCode") if plat.startswith("win") else ("etc", "claude-code")))
    mfile, rfile = os.path.join(mdir, "managed-settings.json"), os.path.join(vdef, "remote-settings.json")
    mtop, d = None, mdir                      # the topmost folder this section makes for it (removed at the end)
    while not os.path.exists(d):
        mtop, d = d, os.path.dirname(d)
    os.makedirs(mdir)
    open(vset, "w", encoding="utf-8").write('{"cleanupPeriodDays": 90}')
    open(mfile, "w", encoding="utf-8").write('{"cleanupPeriodDays": 7}')
    pre = vhash()
    rc, out = vrun("move", "cli:backup", "--only", T20[:8], "--to-profile", "cli", "--keep-dates")
    ref = next((l for l in out.splitlines() if "REFUSE " + T20[:8] in l), "")
    vundo(rc, out)
    rc2, out2 = vrun("move", "cli:backup", "--only", T20[:8], "--to-profile", "cli", "--dry-run")
    check(rc == 1 and vhash() == pre and "older than 7 days (cleanupPeriodDays in the managed settings" in ref
          and "managed-settings.json" in ref and "older than 7 days (cleanupPeriodDays in the managed settings"
          in vwarn(out2, T20),
          "managed-settings.json's cleanupPeriodDays (7) wins over the target's settings.json (90): a 20-day-old "
          "transcript warns with it, and --keep-dates on a plain move of it is refused")
    rc, out = vrun("sessions", "cli:backup")
    check(rc == 0 and "[older than 7 days]" in vline(out, T20),
          "sessions flags a transcript by the managed cleanupPeriodDays")
    open(mfile, "w", encoding="utf-8").write('{"cleanupPeriodDays": 30}')
    rc, out = vrun("move", "cli:backup", "--only", G2[:8], "--to-profile", "cli", env=VNEW)
    w = vwarn(out, G2)
    check(rc == 0 and fresh(vd[G2]) and "older than 30 days (cleanupPeriodDays in the managed settings" in w,
          "a managed cleanupPeriodDays applies to a transcript last continued in Desktop too, whatever the version: "
          "warned and re-dated")
    vundo(rc, out)
    os.remove(mfile)
    open(rfile, "w", encoding="utf-8").write('{"cleanupPeriodDays": 7}')
    rc, out = vrun("move", "cli:backup", "--only", T20[:8], "--to-profile", "cli", "--dry-run")
    check(rc == 0 and "older than 7 days (cleanupPeriodDays in the server-managed settings" in vwarn(out, T20)
          and "remote-settings.json" in vwarn(out, T20),
          "the server-managed settings cached in the target's remote-settings.json win over its settings.json")
    open(rfile, "w", encoding="utf-8").write('{"cleanupPeriodDays": 40}')
    open(mfile, "w", encoding="utf-8").write('{"cleanupPeriodDays": 7}')
    rc, out = vrun("move", "cli:backup", "--only", T20[:8], "--to-profile", "cli", "--dry-run")
    check(rc == 0 and "older than 7 days (cleanupPeriodDays in the managed settings" in vwarn(out, T20),
          "with remote settings 40 and managed-settings.json 7 the shorter applies (since the seventh review): a "
          "20-day-old transcript is warned by the file's 7")
    os.remove(rfile)
    if hasattr(os, "mkfifo"):                 # POSIX: a named pipe where the cache would be
        os.mkfifo(rfile)
        rc, out = run(vh, "move", "cli:backup", "--only", T20[:8], "--to-profile", "cli", "--dry-run", timeout=60)
        os.remove(rfile)
        check(rc == 0 and "older than 7 days (cleanupPeriodDays in the managed settings" in vwarn(out, T20),
              "a FIFO named remote-settings.json is never opened (the dry run does not wait on it), and the managed "
              "file is still read")
    open(mfile, "w", encoding="utf-8").write('{"desktopSessionCleanupPeriodDays": 20}')
    open(vset, "w", encoding="utf-8").write('{"desktopSessionCleanupPeriodDays": 90}')
    rc, out = vrun("move", "cli:backup", "--only", G2[:8], "--to-profile", "cli", "--dry-run", env=VNEW)
    check(rc == 0 and "older than 20 days (desktopSessionCleanupPeriodDays in the managed settings"
          in vwarn(out, G2),
          "a managed desktopSessionCleanupPeriodDays (20) wins over the target's (90)")
    os.remove(mfile); os.remove(vset)
    rc, out = vrun("move", "cli:backup", "--only", G2[:8], "--to-profile", "cli", "--copy", "--dry-run", env=VNEW)
    note = vwarn(out, G2, "note")
    check(rc == 0 and "2.1.248" in note and "visible" not in note and "HIPAA" in note,
          "the note on a copy no longer says that managed settings are not visible (they are read)")

    # ---- V3: a re-dated transcript's sidecar files are re-dated with it, and get their mtimes back
    rc, out = vrun("move", "cli:backup", "--only", G5[:8], "--to-profile", "cli")
    moved = os.path.join(vdef, "projects", vk, G5)
    check(rc == 0 and fresh(vd[G5]) and all(fresh(os.path.join(moved, r)) for r in g5files),
          "a move that re-dates a transcript re-dates every file of its sidecar folder (subagents/, tool-results/, "
          "mcp-tasks/, workflows/) too")
    vundo(rc, out)
    check(all(os.stat(os.path.join(g5side, r)).st_mtime_ns == ns for r, ns in g5files.items()) and old(g5),
          "its rollback gives the transcript and each sidecar file back the mtime it had before the move")
    rc, out = vrun("move", "cli:backup", "--only", G5[:8], "--to-profile", "cli", "--copy")
    check(rc == 0 and all(fresh(os.path.join(moved, r)) for r in g5files)
          and all(os.stat(os.path.join(g5side, r)).st_mtime_ns == ns for r, ns in g5files.items()),
          "a re-dating --copy re-dates the copy's sidecar files and leaves the source's as they were")
    vundo(rc, out)
    rc, out = vrun("move", "cli:backup", "--only", G5[:8], G1[:8], "--to-profile", "cli",
                   env={"CCD_REHOME_FAULT": "fail-after:2"})
    check(rc == 1 and "undone: re-dating" in out and os.path.exists(g5) and old(g5)
          and all(os.stat(os.path.join(g5side, r)).st_mtime_ns == ns for r, ns in g5files.items()),
          "a move that fails after re-dating undoes it: the transcript and each sidecar file are back with their old "
          "mtimes")

    # ---- V4: status counts a Desktop window's conversations that are only in another CLI home
    xacct = profile(vh, "acct-x", signed_in=A, logs=[init("09:00:00", A, OA)])
    xrecs = os.path.join(xacct, "claude-code-sessions", A, OA)
    for n, sid in enumerate((G1, G2, G3, Q1)):
        rec(xrecs, "0e0e0e0e-eeee-4eee-8eee-0000000000a%d" % n, "x %d" % n, cliSessionId=sid, cwd=vproj)
    rc, out = vrun("status", "acct-x")
    rows = j(vh, "status", "acct-x", "acct-v", "cli:backup")
    row = rows[0] if isinstance(rows, list) and rows and isinstance(rows[0], dict) else {}
    check(rc == 0 and "3 of these records' conversations are only in cli:backup" in out
          and "ccd-rehome sessions acct-x" in out and row.get("elsewhere") == {"cli:backup": 3},
          "status of a Desktop profile counts the records whose conversation is only in another CLI home (JSON "
          "\"elsewhere\": {\"cli:backup\": 3}) and points to `ccd-rehome sessions PROFILE` for the --copy")
    check(isinstance(rows, list) and len(rows) == 3 and rows[1].get("elsewhere") == {}
          and rows[2].get("elsewhere") == {},
          "a profile whose conversations are in ~/.claude (or missing) has \"elsewhere\" {}, and a CLI row has it, "
          "empty, like the other Desktop keys")
    shutil.rmtree(xacct)
    if mtop:
        shutil.rmtree(mtop)
    check(tree_hash(vh, skip=vstate) == six0, "(fixture) every move of this section was undone exactly")
    for x in (g5, t20):
        os.remove(x)
    shutil.rmtree(g5side)

    print("Seventh review: the shortest retention any settings source sets (managed-settings.d too), and a --copy "
          "re-dated where the destination would delete it")
    # The fifth section's homes again, every move undone. Claude Code combines its managed sources by rules the tool
    # does not model (https://code.claude.com/docs/en/managed-settings: "first-wins" by default, drop-ins in
    # managed-settings.d/ merged after managed-settings.json): the tool takes, for each setting, the SHORTEST value
    # that the target's settings.json, its remote-settings.json, managed-settings.json or a drop-in sets, so it may
    # warn where Claude Code would keep a transcript, never the other way round. T7 is a terminal transcript 20 days
    # old; G7 was last continued in Desktop, 60 days old, with sidecar files; a window's record points at G7.
    T7, G7 = "8c8c8c8c-0000-4000-8000-000000000d0c", "8d8d8d8d-0000-4000-8000-000000000d0d"
    t7 = vtranscript(vbak, T7, ("cli",), time.time() - 20 * 86400)
    g7 = vtranscript(vbak, G7, ("cli", "claude-desktop"), vold)
    g7side, g7files = os.path.join(vbak, "projects", vk, G7), {}
    for sub, name in (("subagents", "agent-a.jsonl"), ("tool-results", "toolu_1.txt")):
        os.makedirs(os.path.join(g7side, sub))
        f = os.path.join(g7side, sub, name)
        open(f, "w", encoding="utf-8").write(sub * 10)
        os.utime(f, (vold, vold))
        g7files[os.path.join(sub, name)] = os.stat(f).st_mtime_ns
    vd[T7], vd[G7] = (os.path.join(vdef, "projects", vk, x + ".jsonl") for x in (T7, G7))
    g7copy = os.path.join(vdef, "projects", vk, G7)
    g7ns = os.stat(g7).st_mtime_ns
    sacct = profile(vh, "acct-s", signed_in=A, logs=[init("09:00:00", A, OA)])
    rec(os.path.join(sacct, "claude-code-sessions", A, OA), "0e0e0e0e-eeee-4eee-8eee-0000000000b1", "rec of G7",
        cliSessionId=G7, cwd=vproj)
    seven0 = tree_hash(vh, skip=vstate)
    mtop, d = None, mdir
    while not os.path.exists(d):
        mtop, d = d, os.path.dirname(d)
    mdrop = os.path.join(mdir, "managed-settings.d")
    os.makedirs(mdrop)

    def settings7(home=None, remote=None, managed=None, drops=None):
        """The target's settings.json, its remote-settings.json, managed-settings.json and the drop-ins in
        managed-settings.d/ ({name: dict}); None: absent."""
        for p, v in ((vset, home), (rfile, remote), (mfile, managed)):
            if v is not None:
                open(p, "w", encoding="utf-8").write(json.dumps(v))
            elif os.path.lexists(p):
                os.remove(p)
        for n in os.listdir(mdrop):
            os.remove(os.path.join(mdrop, n))
        for n, v in (drops or {}).items():
            open(os.path.join(mdrop, n), "w", encoding="utf-8").write(json.dumps(v))

    def unchanged7():
        return os.stat(g7).st_mtime_ns == g7ns and \
            all(os.stat(os.path.join(g7side, r)).st_mtime_ns == ns for r, ns in g7files.items())

    POLICY = {"permissions": {"deny": ["Bash(curl:*)"]}}         # a policy key, and no retention setting

    # ---- W1: the shortest value any source sets
    settings7(home={"cleanupPeriodDays": 7}, remote=POLICY, managed={"cleanupPeriodDays": 90})
    rc, out = vrun("move", "cli:backup", "--only", T7[:8], "--to-profile", "cli")
    w = vwarn(out, T7)
    check(rc == 0 and fresh(vd[T7]) and "older than 7 days (cleanupPeriodDays in cli)" in w
          and "no longer has it (the archive holds no copy): use --copy" in w,
          "a cache with other policy keys and no cleanupPeriodDays, managed-settings.json 90 and the target's "
          "settings.json 7: the shortest (7) applies, so a 20-day-old transcript is warned and re-dated")
    vundo(rc, out)
    pre = vhash()
    rc, out = vrun("move", "cli:backup", "--only", T7[:8], "--to-profile", "cli", "--keep-dates")
    ref = next((l for l in out.splitlines() if "REFUSE " + T7[:8] in l), "")
    check(rc == 1 and vhash() == pre and "older than 7 days (cleanupPeriodDays in cli)" in ref
          and "--keep-dates keeps that date" in ref,
          "the same layout with --keep-dates on a plain move is refused, and nothing is written")
    vundo(rc, out)
    settings7(home={"cleanupPeriodDays": 7}, managed={"cleanupPeriodDays": 90},
              drops={"20-retention.json": {"cleanupPeriodDays": 7}})
    rc, out = vrun("move", "cli:backup", "--only", T7[:8], "--to-profile", "cli")
    check(rc == 0 and fresh(vd[T7]) and "older than 7 days (cleanupPeriodDays in the managed settings" in vwarn(out, T7)
          and "20-retention.json" in vwarn(out, T7),
          "a drop-in managed-settings.d/20-retention.json 7 over managed-settings.json 90 (the target's settings.json "
          "7): warned and re-dated, and on that tie the managed source is the one named")
    vundo(rc, out)
    settings7(home={"cleanupPeriodDays": 90}, managed={"cleanupPeriodDays": 90},
              drops={"20-retention.json": {"cleanupPeriodDays": 7}, "30-other.json": {"cleanupPeriodDays": 60}})
    rc, out = vrun("move", "cli:backup", "--only", T7[:8], "--to-profile", "cli", "--dry-run")
    w = vwarn(out, T7)
    check(rc == 0 and "older than 7 days (cleanupPeriodDays in the managed settings" in w
          and "managed-settings.d" in w and "20-retention.json" in w,
          "a drop-in's value is read, and the warning names that drop-in")
    settings7(home={"cleanupPeriodDays": 90},
              drops={".10-hidden.json": {"cleanupPeriodDays": 1}, "10-notes.txt": {"cleanupPeriodDays": 1}})
    rc, out = vrun("move", "cli:backup", "--only", T7[:8], "--to-profile", "cli", "--dry-run")
    check(rc == 0 and "older than" not in vwarn(out, T7),
          "a hidden drop-in and one that does not end in .json are not read (Claude Code ignores them)")
    if hasattr(os, "mkfifo"):
        settings7(home={"cleanupPeriodDays": 90}, drops={"20-retention.json": {"cleanupPeriodDays": 7}})
        os.mkfifo(os.path.join(mdrop, "10-pipe.json"))
        rc, out = run(vh, "move", "cli:backup", "--only", T7[:8], "--to-profile", "cli", "--dry-run", timeout=60)
        check(rc == 0 and "older than 7 days (cleanupPeriodDays in the managed settings" in vwarn(out, T7),
              "a FIFO among the drop-ins is never opened (the dry run does not wait on it), and the other drop-in is "
              "still read")
    settings7(home={"cleanupPeriodDays": 90}, remote={"cleanupPeriodDays": 7}, managed={"cleanupPeriodDays": 40})
    rc, out = vrun("move", "cli:backup", "--only", T7[:8], "--to-profile", "cli", "--dry-run")
    w = vwarn(out, T7)
    settings7(home={"cleanupPeriodDays": 90}, remote={"cleanupPeriodDays": 40}, managed={"cleanupPeriodDays": 7})
    rc2, out2 = vrun("move", "cli:backup", "--only", T7[:8], "--to-profile", "cli", "--dry-run")
    w2 = vwarn(out2, T7)
    check(rc == 0 and "older than 7 days (cleanupPeriodDays in the server-managed settings" in w and rc2 == 0
          and "older than 7 days (cleanupPeriodDays in the managed settings" in w2
          and "managed-settings.json" in w2,
          "the shortest value wins whichever source ranks first: remote 7 over file 40, and file 7 under remote 40, "
          "each named")
    settings7(managed={"cleanupPeriodDays": 90})
    rc, out = vrun("move", "cli:backup", "--only", G1[:8], "--to-profile", "cli", "--dry-run")
    check(rc == 0 and "older than 30 days (cleanupPeriodDays in cli)" in vwarn(out, G1),
          "a managed value never lengthens the target's: managed-settings.json 90 and a target that sets none (30, "
          "the default) warn a 60-day-old transcript by the 30 days")
    rc, out = vrun("sessions", "cli:backup")
    settings7(drops={"20-retention.json": {"cleanupPeriodDays": 7}})
    rc2, out2 = vrun("sessions", "cli:backup")
    check(rc == 0 and "older than" not in vline(out, T7) and rc2 == 0 and "[older than 7 days]" in vline(out2, T7),
          "sessions flags a transcript by the shortest value too (a drop-in's 7)")

    # Desktop transcripts: a managed cleanupPeriodDays applies to them too; the home's own does not
    settings7(drops={"20-retention.json": {"cleanupPeriodDays": 30}})
    rc, out = vrun("move", "cli:backup", "--only", G2[:8], "--to-profile", "cli", "--dry-run", env=VNEW)
    w = vwarn(out, G2)
    check(rc == 0 and "older than 30 days (cleanupPeriodDays in the managed settings" in w
          and "managed-settings.d" in w and "its mtime is set to now" in w,
          "a drop-in's cleanupPeriodDays applies to a transcript last continued in Desktop too (Claude Code 2.1.300 "
          "here): it would be re-dated")
    settings7(home={"cleanupPeriodDays": 7}, managed={"cleanupPeriodDays": 90})
    rc, out = vrun("move", "cli:backup", "--only", G2[:8], "--to-profile", "cli", "--dry-run", env=VNEW)
    w = vwarn(out, G2)
    check(rc == 0 and "not re-dated" in w and "older than 7 days (cleanupPeriodDays in cli)" in w
          and "until it is 90 days old (cleanupPeriodDays in the managed settings" in w,
          "(guard) the target's own cleanupPeriodDays (7) does not apply to a Desktop transcript, and the managed 90 "
          "is not reached: under 2.1.300 it is not re-dated, and the warning names the managed limit it keeps")
    settings7(home={"desktopSessionCleanupPeriodDays": 90},
              drops={"20-retention.json": {"desktopSessionCleanupPeriodDays": 20}})
    rc, out = vrun("move", "cli:backup", "--only", G2[:8], "--to-profile", "cli", "--dry-run", env=VNEW)
    w = vwarn(out, G2)
    check(rc == 0 and "older than 20 days (desktopSessionCleanupPeriodDays in the managed settings" in w
          and "20-retention.json" in w,
          "the shortest desktopSessionCleanupPeriodDays (a drop-in's 20 under the target's 90) applies, named")
    settings7()

    # ---- W2: a --copy the destination would delete is re-dated (the copy, never the source)
    rc, out = vrun("sessions", "acct-s", env=VOLD)
    m = re.search(r"ccd-rehome (move cli:backup --only \S+ --to-profile cli --copy)", out)
    pre = tree_hash(vh, skip=vstate)
    rc2, out2 = vrun(*m.group(1).split(), env=VOLD) if m else (None, "")
    w = vwarn(out2, G7)
    check(rc == 0 and m is not None and G7[:8] in m.group(1) and rc2 == 0 and fresh(vd[G7])
          and all(fresh(os.path.join(g7copy, r)) for r in g7files) and unchanged7()
          and "`claude --version` here is 2.1.100" in w and "would delete the copy at its next start" in w
          and "the copy's mtime is set to now, and so are those of the 2 file(s) in its sidecar folder" in w
          and "cli:backup keeps its own" in w,
          "the --copy that sessions PROFILE prints for a window, with Claude Code 2.1.100 here: the copy of a "
          "Desktop transcript older than cleanupPeriodDays is re-dated with its sidecar files, the source keeps its "
          "dates, and the warning says so")
    vundo(rc2, out2)
    check(not os.path.exists(vd[G7]) and not os.path.exists(g7copy) and tree_hash(vh, skip=vstate) == pre
          and unchanged7(),
          "its rollback removes the re-dated copy (a re-dated copy is still the tool's: content decides, not mtime) "
          "and leaves the source as it was")
    rc, out = vrun("move", "cli:backup", "--only", G7[:8], "--to-profile", "cli", "--copy", "--dry-run", env=VUNK)
    rc2, out2 = vrun("move", "cli:backup", "--only", G7[:8], "--to-profile", "cli", "--copy", "--dry-run",
                     env=VNONE)
    check(rc == 0 and "the version of Claude Code here is not known" in vwarn(out, G7)
          and "the copy's mtime is set to now" in vwarn(out, G7) and rc2 == 0
          and "not known (no `claude` on PATH)" in vwarn(out2, G7) and "the copy's mtime is set to now" in vwarn(out2, G7),
          "with no version known (none printed, no `claude` on PATH) the copy would be re-dated too")
    rc, out = vrun("move", "cli:backup", "--only", G7[:8], "--to-profile", "cli", "--copy", env=VNEW)
    n = next((l for l in out.splitlines() if "note: " + G7[:8] in l and "2.1.248" in l), "")
    check(rc == 0 and old(vd[G7]) and "warning: " + G7[:8] not in out and "`claude --version` here is 2.1.300" in n
          and "so this copy is not re-dated" in n,
          "(guard) with Claude Code 2.1.300 here the copy keeps its date, and the note names the version")
    vundo(rc, out)
    rc, out = vrun("move", "cli:backup", "--only", G7[:8], "--to-profile", "cli", "--copy", "--keep-dates", env=VOLD)
    w = vwarn(out, G7)
    check(rc == 0 and old(vd[G7]) and all(old(os.path.join(g7copy, r)) for r in g7files) and unchanged7()
          and "--keep-dates keeps the copy's date" in w and "would delete the copy at its next start" in w
          and "cli:backup keeps its own" in w,
          "--copy --keep-dates with Claude Code 2.1.100 here keeps the old dates and warns that the destination "
          "will delete the copy (the source keeps its own)")
    vundo(rc, out)
    rc, out = vrun("move", "cli:backup", "--only", G1[:8], "--to-profile", "cli", "--copy", "--keep-dates",
                   "--dry-run")
    rc2, out2 = vrun("move", "cli:backup", "--only", G1[:8], "--to-profile", "cli", "--copy", "--dry-run")
    check(rc == 0 and "would delete the copy at its next start" in vwarn(out, G1)
          and "--keep-dates keeps the copy's date" in vwarn(out, G1) and "cli:backup keeps its own" in vwarn(out, G1)
          and rc2 == 0 and "the copy's mtime is set to now" in vwarn(out2, G1),
          "a terminal transcript's --copy says the same: re-dated, or with --keep-dates deleted at the next start")
    settings7(managed={"cleanupPeriodDays": 30})
    rc, out = vrun("move", "cli:backup", "--only", G7[:8], "--to-profile", "cli", "--copy", env=VNEW)
    check(rc == 0 and fresh(vd[G7]) and unchanged7()
          and "older than 30 days (cleanupPeriodDays in the managed settings" in vwarn(out, G7),
          "a managed cleanupPeriodDays re-dates the copy of a Desktop transcript whatever the version")
    vundo(rc, out)
    settings7()
    rc, out = vrun("move", "cli:backup", "--only", G7[:8], "--to-profile", "cli", "--copy", env=VOLD)
    with open(vd[G7], "a", encoding="utf-8") as f:
        f.write(json.dumps({"type": "user", "uuid": "u9", "sessionId": G7, "message": {"content": "new"}}) + "\n")
    rc2, out2 = vundo(rc, out)
    check(rc == 0 and fresh(vd[G7]) and "kept the copy of " + G7[:8] in out2 and os.path.exists(vd[G7])
          and unchanged7(),
          "(guard) a re-dated copy that gained a turn after the copy is kept by the rollback")
    os.remove(vd[G7]); shutil.rmtree(g7copy)
    if mtop:
        shutil.rmtree(mtop)
    check(tree_hash(vh, skip=vstate) == seven0, "(fixture) every move of this section was undone exactly")
    shutil.rmtree(sacct)
    for x in (t7, g7):
        os.remove(x)
    shutil.rmtree(g7side)

    print("Desktop conversations an older terminal Claude Code deletes for their age (doctor, status)")
    # Seen on a real Mac: the terminal `claude` was 2.1.119 with no cleanupPeriodDays, and two Desktop records had
    # lost their conversations. Before 2.1.248 Claude Code deletes EVERY transcript older than cleanupPeriodDays.
    rh = os.path.join(home, "retention-home"); os.makedirs(rh)
    rp = profile(rh, "acct-r", signed_in=A, logs=[init("09:00:00", A, OA)])
    rkey = os.path.join(rh, ".claude", "projects", "-r-proj"); os.makedirs(rkey)
    R1, R2 = ("7e7e7e7e-0000-4000-8000-00000000000%d" % n for n in (1, 2))
    for sid, age in ((R1, time.time() - 60 * 86400), (R2, None)):
        t = os.path.join(rkey, sid + ".jsonl")
        open(t, "w", encoding="utf-8").write(json.dumps({"type": "user", "uuid": "u1", "cwd": "/r/proj", "sessionId": sid,
                                                         "entrypoint": "claude-desktop",
                                                         "message": {"content": "hi"}}) + "\n")
        if age:
            os.utime(t, (age, age))
        rec(os.path.join(rp, "claude-code-sessions", A, OA), sid, "retention " + sid[-1], cliSessionId=sid,
            cwd="/r/proj")
    rset = os.path.join(rh, ".claude", "settings.json")
    r0 = tree_hash(rkey), tree_hash(os.path.join(rp, "claude-code-sessions"))
    rc, out = run(rh, "doctor", env=VOLD)
    w = next((l for l in out.splitlines() if "acct-r: 1 of 2 Desktop conversation" in l), "")
    check("[WARN]" in w and "older than 30 days" in w and "2.1.100" in out and "2.1.248" in out
          and "cleanupPeriodDays" in out and "settings.json" in out,
          "doctor: with Claude Code 2.1.100 here, the Desktop conversation older than cleanupPeriodDays (30 by "
          "default) is named as one it deletes at its next start, with the fix")
    rc, out = run(rh, "status", "acct-r", env=VOLD)
    rc2, out2 = run(rh, "status", "acct-r", "--json", env=VOLD)
    try:
        risk = json.loads(out2)[0]["retention_risk"]
    except (ValueError, LookupError, TypeError):
        risk = None
    check(rc == 0 and "WARNING: 1 of these sessions' conversations" in out and "older than 30 days" in out
          and risk and risk[0]["n"] == 1 and risk[0]["of"] == 2 and risk[0]["days"] == 30,
          "status says the same in text and in --json (retention_risk)")
    rc, out = run(rh, "status", "--json", env=VOLD)
    try:
        rows = json.loads(out)
    except ValueError:
        rows = []
    check(rows and all("retention_risk" in r for r in rows),
          "every status --json row, a CLI home's too, has retention_risk")
    rc, out = run(rh, "doctor", env=VNEW)
    rc2, out2 = run(rh, "doctor", env=VNONE)
    check("acct-r: no Desktop conversation" in out and "[WARN] acct-r: 1 of" not in out
          and "acct-r: no Desktop conversation" in out2,
          "(guard) with Claude Code 2.1.300, or with Desktop's own (no `claude` on PATH), a conversation last "
          "continued in Desktop is kept at any age: no warning")
    json.dump({"cleanupPeriodDays": 3650}, open(rset, "w", encoding="utf-8"))
    rc, out = run(rh, "doctor", env=VOLD)
    check("acct-r: no Desktop conversation" in out, "(guard) cleanupPeriodDays 3650 removes the warning")
    json.dump({"desktopSessionCleanupPeriodDays": 45}, open(rset, "w", encoding="utf-8"))
    rc, out = run(rh, "doctor", env=VNEW)
    check("acct-r: 1 of 2 Desktop conversation" in out and "desktopSessionCleanupPeriodDays" in out,
          "with Claude Code 2.1.300, a desktopSessionCleanupPeriodDays shorter than the conversation's age warns")
    os.remove(rset)
    check((tree_hash(rkey), tree_hash(os.path.join(rp, "claude-code-sessions"))) == r0,
          "(fixture) doctor and status changed no conversation and no record")
    shutil.rmtree(rh)

    print("Desktop 5 (5.11492.0, macOS): log lines, per-account files, imported and scratch sessions")
    d5h = os.path.join(home, "desktop5-home"); os.makedirs(d5h)

    def d5store(prof, acct, org):
        return os.path.join(d5h, ".claude-instances", prof, "claude-code-sessions", acct, org)
    # Per-account files Desktop 5 keeps beside the records: an archived-ids cache, Remote Control delete markers
    # (64-hex name), the staging folder of imported sessions. Known, and none of them is moved.
    pe = profile(d5h, "acct-d5e", signed_in=B, logs=[init("09:00:00", B, OB)])
    se, te = d5store("acct-d5e", A, OA), d5store("acct-d5e", B, OB)
    rec(se, "e5e5e5e5-0000-4000-8000-000000000001", "plain")
    rec(te, "e5e5e5e5-0000-4000-8000-000000000009", "already there")
    json.dump({"v": 1, "archived": ["local_x"]}, open(os.path.join(se, "archived-sessions.idx"), "w", encoding="utf-8"))
    open(os.path.join(se, "archived-sessions.idx.tmp"), "w", encoding="utf-8").write("{}")
    owed = os.path.join(se, "owed-bridge-delete_" + "ab" * 32)
    json.dump({"version": 3, "remoteId": "cse_1", "sessionId": "local_other", "transcriptIds": [], "nonce": "n",
               "state": "owed", "action": "delete"}, open(owed, "w", encoding="utf-8"))
    os.makedirs(os.path.join(se, "imported-staging"))
    rc, out = run(d5h, "doctor")
    check("session-dir entries: 0 unknown" in out,
          "doctor: archived-sessions.idx(.tmp), owed-bridge-delete_<hash> and imported-staging/ are known entries")
    rc, out = run(d5h, "rehome", "acct-d5e")
    check(rc == 0 and os.path.exists(os.path.join(te, "local_e5e5e5e5-0000-4000-8000-000000000001.json"))
          and os.path.exists(owed) and not os.path.exists(os.path.join(te, os.path.basename(owed)))
          and not os.path.exists(os.path.join(te, "archived-sessions.idx")),
          "a move leaves the Remote Control markers (the old account's) and the archived-ids cache where they are")
    # A Remote Control delete still in progress ("intent") names a record: moving that record would strand it.
    rec(se, "e5e5e5e5-0000-4000-8000-000000000002", "being deleted")
    intent = os.path.join(se, "owed-bridge-delete_" + "cd" * 32)
    json.dump({"version": 3, "remoteId": "cse_2", "sessionId": "local_e5e5e5e5-0000-4000-8000-000000000002",
               "transcriptIds": [], "nonce": "n", "state": "intent", "action": "delete"},
              open(intent, "w", encoding="utf-8"))
    h_e = tree_hash(os.path.join(pe, "claude-code-sessions"))
    rc, out = run(d5h, "rehome", "acct-d5e")
    check(rc != 0 and "DRIFT" in out and "Remote Control" in out and "e5e5e5e5" in out
          and tree_hash(os.path.join(pe, "claude-code-sessions")) == h_e,
          "a record named by a Remote Control delete in progress (state intent) is DRIFT: nothing moves")
    os.remove(intent); os.remove(os.path.join(se, "local_e5e5e5e5-0000-4000-8000-000000000002.json"))
    # An imported session Desktop has not resumed yet keeps its conversation INSIDE the account folder.
    cli_i = "e5e5e5e5-0000-4000-8000-0000000000c1"
    staged = os.path.join(se, "imported-staging", cli_i + ".jsonl")
    open(staged, "w", encoding="utf-8").write('{"type":"user"}\n')
    rec(se, "e5e5e5e5-0000-4000-8000-000000000003", "imported", cliSessionId=cli_i,
        importedFrom="previous-profile-code", stagedTranscriptPath=staged)
    out_i = os.path.join(d5h, "imported.json")
    rc, out = run(d5h, "export-record", "acct-d5e", "--only", "e5e5e5e5-0000-4000-8000-000000000003", "--out", out_i)
    check(rc != 0 and "not resumed yet" in out and "imported-staging" in out and not os.path.exists(out_i),
          "export-record refuses an imported session not resumed yet: its conversation is in no CLI home")
    rc, out = run(d5h, "rehome", "acct-d5e")
    r3t = os.path.join(te, "local_e5e5e5e5-0000-4000-8000-000000000003.json")
    check(rc == 0 and os.path.exists(r3t) and os.path.exists(staged)
          and json.load(open(r3t, encoding="utf-8")).get("stagedTranscriptPath") == staged,
          "within its window it moves to the signed-in account: Desktop keeps reading the staged conversation there")
    # An unfinished write: Desktop 5 turns local_X.json.tmp into a record at its next start in that folder.
    rec(se, "e5e5e5e5-0000-4000-8000-000000000004", "half-written")
    open(os.path.join(se, "local_e5e5e5e5-0000-4000-8000-000000000004.json.tmp"), "w", encoding="utf-8").write("{}")
    rc, out = run(d5h, "rehome", "acct-d5e")
    check(rc != 0 and "DRIFT" in out and ".json.tmp" in out and "unfinished write" in out,
          "a local_*.json.tmp beside the records is DRIFT: Desktop would bring the session back in the old account")
    os.remove(os.path.join(se, "local_e5e5e5e5-0000-4000-8000-000000000004.json.tmp"))
    # A session working in a scratch workspace: the folder stays under the old account, whose sweep deletes it.
    scr = os.path.join(pe, "scratch-workspaces", A, OA, "scratch-2026-11-01-abcdef"); os.makedirs(scr)
    rec(se, "e5e5e5e5-0000-4000-8000-000000000005", "scratch", cwd=scr)
    rc, out = run(d5h, "rehome", "acct-d5e")
    check(rc == 0 and "scratch" in out and "7 days" in out and "delete" in out,
          "moving a session whose folder is the old account's scratch workspace warns that Desktop deletes it")
    # Desktop 5 adds a suffix to the line when archived sessions are deferred, and logs those separately.
    p5 = profile(d5h, "acct-d5", signed_in=C, logs=[])     # C: no other profile here knows its org
    s5 = os.path.join(p5, "claude-code-sessions")
    for n, arch in ((1, False), (2, False), (3, True)):
        rec(os.path.join(s5, C, OC), "d5d5d5d5-0000-4000-8000-00000000000%d" % n, "d5 %d" % n, isArchived=arch)
    os.makedirs(os.path.join(s5, C, OB))                       # a second org folder: the log must decide
    rec(os.path.join(s5, A, OA), "d5d5d5d5-0000-4000-8000-000000000009", "to move")
    open(os.path.join(p5, "logs", "main.log"), "w", encoding="utf-8").write(
        f"2026-11-12 15:17:13 [info] Loaded 2 persisted sessions from {os.path.join(s5, C, OC)} "
        f"(1 archived deferred, 1 of them unopened; hint on)\n"
        f"2026-11-12 15:17:13 [info] Loaded 1 deferred archived sessions from {os.path.join(s5, C, OC)} "
        f"(after_active, 12 ms)\n")
    rc, out = run(d5h, "verify", "acct-d5")
    check(rc == 0 and "OK" in out and "loaded 3 session(s)" in out,
          "verify reads Desktop 5's line with its archived-deferred suffix, and adds the deferred line's count")
    rc, out = run(d5h, "rehome", "acct-d5")
    check(rc == 0 and os.path.exists(os.path.join(s5, C, OC, "local_d5d5d5d5-0000-4000-8000-000000000009.json")),
          "the target org comes from that line (the path before the suffix), with two org folders to choose from")
    po = profile(d5h, "acct-d5out", signed_in=B, logs=[
        "2026-11-12 15:00:00 [info] claude.ai account active and logged in",
        "2026-11-12 15:16:01 [info] [account] User logged out during account ID wait, stopping early"])
    rc, out = run(d5h, "status", "acct-d5out", "--json")
    try:
        verdict = json.loads(out)[0]["verdict"]
    except (ValueError, LookupError, TypeError):
        verdict = None
    check(verdict == "signed-out", "Desktop 5's 'User logged out during account ID wait' line means signed out")
    # The 138 record fields Desktop 5.11492.0 can write that 0.11.1 did not know, classified from its code
    # (references/mechanics.md §5). A record with all of them: none is DRIFT, and each class is handled.
    AB5 = ["artifactsMcpVouchedCalls", "backgroundTaskSuggestions", "cloudSessionId", "cloudSpawnedTasks",
           "connectorWireNames", "emailAddress", "enabledMcpTools", "interruptedByQuitAt", "interruptedByQuitFor",
           "interruptedUnseenResume", "movedToCloud", "remoteControlFollowsStarter", "remoteControlKeptServerCopyId",
           "remoteControlLiveAtUpdateQuit", "remoteControlSpawn", "remoteControlUserEnabled", "servedConnectorCalls",
           "spaceId", "sshReattach", "cutTurn"]
    TR5 = ["coveredError", "errorCategory", "errorCode", "peerInbound", "restartErrorMark", "tccFolderKind"]
    HB5 = ["btwSharedTree", "cuFlagsGrantedAt", "folderPlace", "folderWorktrees", "keepCoversOwnTree", "keptDirtyAt",
           "keptDirtyWorktree", "keptWorktreeLeftover", "knownStartedByHostLauncher", "launcherAtSpawn",
           "launcherUsedAppSignIn", "pendingSystemReminder", "requestedAdditionalFolders", "scratchCarried",
           "scratchFilesLeftIn", "sharedTreeGone", "sshAddressNeverEdited", "sshConfig", "sshForeignDaemonLossAt",
           "sshHostChangedAt", "sshKillRecoveryGrantedAt", "sshProcessLossStoodDownAt", "sshRemoteProcessId",
           "sshRemoteTranscriptPath", "stagedTranscriptPath", "tasksStoppedAt", "tasksStoppedEnded", "worktreeLazy",
           "worktreeName", "worktreePath", "writtenRepositories", "wslConfig"]
    KP5 = ["_startedThroughHostCliLauncher", "adoptedFromOtherSurface", "agent", "asides", "autoArchiveExempt",
           "autoArchiveOnPrClose", "autoFixDelivered", "autoFixNoticeSent", "autoSendsPausedAfterDelete", "branch",
           "btwLoweredFrom", "bypassChosenInApp", "cliMcpAppServerNames", "color", "connectionTriesSincePerson",
           "contextRecovery", "conversationPluginLoaded", "cutTurnChain", "cutTurnStoppedAt",
           "dispatchParentId", "dispatchParentOrigin", "durableCronMade", "effortInherited", "endedIdleAsOf",
           "forkedAtMessageUuid", "forkedFromSessionId", "fromCliTranscript", "givenUpCliSessionIds",
           "historyOnlyCliSessionId", "importedFrom", "importedRunOf", "indexedAt", "isStarred", "lanyardOfferPrompt",
           "lastTurnReport", "lastTurnStopped", "launcherMarked", "lineageDetached", "lineageDetachedBy",
           "midTaskReplyTool", "overflowCliSessionIds", "overflowRemoteCliSessionIds", "peerMessaged", "peerReceipts",
           "pendingFirstStart", "permissionModePicked", "priorCliSessionLeftAt", "priorRemoteCliSessionIds", "prs",
           "queuedSideSessionNotes", "recap", "recapAt", "remoteControlDescendant", "resumeConfirmed",
           "scheduledRunContinued", "scheduledTaskId", "seenCommentIds", "setupTools", "sideSessionNotes",
           "sideSessionOffersMuted", "sideSessionReportOwed", "sideSessionStartsSinceUserMessage",
           "sideSessionWakesSinceUserMessage", "simulatorToolsUsed", "sourceBranch", "spawnedFromEndNotified",
           "startChain", "stoppedUntilPersonSends", "subagentsTruncatedFor", "surfaceNoticeUuid", "titleCheck",
           "titleFromPr", "titleOffers", "titleSuggestionsOff", "transcriptCuts", "violinBow", "violinBowHomeSettings",
           "violinBowPromptKinds", "violinBowPrompts"]       # + remoteClientLimits (KEEP), absent here on purpose
    check(len(set(AB5 + TR5 + HB5 + KP5)) == 137, "(fixture) 137 distinct new fields, plus remoteClientLimits")
    pf = profile(d5h, "acct-d5f", signed_in=B, logs=[init("09:00:00", B, OB)])
    sf = os.path.join(pf, "claude-code-sessions")
    vals = {k: True for k in AB5 + TR5 + HB5 + KP5}
    vals.update(remoteControlSpawn={"ccrSessionId": "cse_x", "folder": "/p"}, emailAddress="old@example.com",
                subagentsTruncatedFor="cli-f5f5f5f5-0000-4000-8000-000000000001", interruptedAwaitingPerson=True,
                importedFrom="previous-profile-code", resumeConfirmed=True, stagedTranscriptPath="/gone/x.jsonl")
    rec(os.path.join(sf, A, OA), "f5f5f5f5-0000-4000-8000-000000000001", "every Desktop 5 field", **vals)
    rc, out = run(d5h, "doctor")
    check("0 unknown field(s)" in out, "doctor: none of the 138 Desktop 5 fields is unknown")
    rc, out = run(d5h, "rehome", "acct-d5f")
    mf = os.path.join(sf, B, OB, "local_f5f5f5f5-0000-4000-8000-000000000001.json")
    mr = json.load(open(mf, encoding="utf-8")) if os.path.exists(mf) else {}
    check(rc == 0 and mr and not set(AB5 + TR5 + ["interruptedAwaitingPerson"]) & set(mr),
          "an account move drops the 20 account-bound fields (old email, cloud, Remote Control, connector ids, an "
          "owed SSH turn) and the 6 transient ones, and interruptedAwaitingPerson with its quit mark")
    check(set(HB5 + KP5) <= set(mr) and mr.get("subagentsTruncatedFor") == vals["subagentsTruncatedFor"],
          "it keeps the 32 machine-bound and the 80 session-state fields (subagentsTruncatedFor among them)")
    check(mr.get("remoteClientLimits") is True,
          "dropping remoteControlSpawn keeps Desktop's clamp: remoteClientLimits is set (never bypass permissions)")
    out_f5 = os.path.join(d5h, "exported5.json")
    rc, out = run(d5h, "export-record", "acct-d5f", "--only", "f5f5f5f5", "--out", out_f5)
    ex5 = (json.load(open(out_f5, encoding="utf-8")) if os.path.exists(out_f5) else {}).get("record", {})
    profile(d5h, "acct-d5g", signed_in=C, logs=[init("09:00:00", C, OC)])
    rc, out = run(d5h, "adopt", "acct-d5g", "--record", out_f5, "--cwd", "/new/host/proj")
    ad = glob.glob(os.path.join(d5h, ".claude-instances", "acct-d5g", "claude-code-sessions", C, OC, "local_*.json"))
    ar = json.load(open(ad[0], encoding="utf-8")) if ad else {}
    check(ex5.get("remoteClientLimits") is True and ar and not set(AB5 + TR5 + HB5) & set(ar)
          and set(KP5) <= set(ar) and ar.get("remoteClientLimits") is True,
          "export-record + adopt --cwd (another machine) also drop the 32 machine-bound fields, keep the clamp")
    shutil.rmtree(d5h)

    print("0.11.2 review: the Desktop 5 guards per session, --to-profile, rollback, adopt and the Remote Control clamps")
    rvh = os.path.join(home, "review-home"); os.makedirs(rvh)

    def rvstore(prof, acct, org):
        return os.path.join(rvh, ".claude-instances", prof, "claude-code-sessions", acct, org)
    X, Y, Z = ("9a9a9a9a-0000-4000-8000-00000000000%d" % n for n in (1, 2, 3))
    pw = profile(rvh, "acct-w", signed_in=B, logs=[init("09:00:00", B, OB)])
    sw, tw = rvstore("acct-w", A, OA), rvstore("acct-w", B, OB)
    profile(rvh, "acct-v", signed_in=C, logs=[init("09:00:00", C, OC)])
    tv = rvstore("acct-v", C, OC)
    rec(sw, X, "X"); rec(sw, Y, "Y"); os.makedirs(tw)
    # Guards for OTHER sessions, or in the target, do not block a move of X
    json.dump({"version": 3, "remoteId": "cse_y", "sessionId": "local_" + Y, "transcriptIds": [], "nonce": "n",
               "state": "intent", "action": "delete"}, open(os.path.join(sw, "owed-bridge-delete_" + "1f" * 32), "w", encoding="utf-8"))
    open(os.path.join(sw, "local_%s.json.tmp" % Y), "w", encoding="utf-8").write("{}")
    json.dump({"version": 3, "remoteId": "cse_z", "sessionId": "local_zz", "transcriptIds": [], "nonce": "n",
               "state": "intent", "action": "delete"}, open(os.path.join(tw, "owed-bridge-delete_" + "2e" * 32), "w", encoding="utf-8"))
    open(os.path.join(tw, "local_zz.json.tmp"), "w", encoding="utf-8").write("{}")
    os.makedirs(os.path.join(tw, "imported-staging"))
    zst = os.path.join(tw, "imported-staging", "cli-z.jsonl"); open(zst, "w", encoding="utf-8").write("{}\n")
    rec(tw, Z, "Z imported", cliSessionId="cli-z", importedFrom="previous-profile-code", stagedTranscriptPath=zst)
    rc, out = run(rvh, "move", "acct-w", "--only", X)
    check(rc == 0 and os.path.exists(os.path.join(tw, "local_%s.json" % X)),
          "Desktop 5 guards are per session: another session's Remote Control delete or unfinished write, and "
          "anything in the target folder, do not block moving X")
    # ... but X's own fresh unfinished write does, with a message that names the hazard
    if os.path.exists(os.path.join(tw, "local_%s.json" % X)):
        run(rvh, "rollback", "acct-w", newest(rvh, "acct-w"))
    open(os.path.join(sw, "local_%s.json.tmp" % X), "w", encoding="utf-8").write("{}")
    rc, out = run(rvh, "move", "acct-w", "--only", X)
    check(rc != 0 and "unfinished write" in out and "not safe to move yet" in out and "does not know" not in out
          and os.path.exists(os.path.join(sw, "local_%s.json" % X)),
          "X's own unfinished write (under 30 days) refuses, saying what is unsafe, not 'unknown'")
    old = time.time() - 40 * 86400
    os.utime(os.path.join(sw, "local_%s.json.tmp" % X), (old, old))
    rc, out = run(rvh, "move", "acct-w", "--only", X, "--dry-run")
    check(rc == 0 and "unfinished write" not in out,
          "(guard) a .tmp older than 30 days is not a hazard: Desktop no longer restores a record from it")
    os.utime(os.path.join(sw, "local_%s.json.tmp" % X), None)
    # --to-profile applies the same guards to the source (it validated only a copy of the record before)
    h_w = tree_hash(os.path.join(pw, "claude-code-sessions"))
    rc, out = run(rvh, "move", "acct-w", "--only", X, "--to-profile", "acct-v")
    check(rc != 0 and "unfinished write" in out and tree_hash(os.path.join(pw, "claude-code-sessions")) == h_w
          and not glob.glob(os.path.join(tv, "local_*.json")),
          "move --to-profile refuses X's unfinished write too, before anything is written")
    os.remove(os.path.join(sw, "local_%s.json.tmp" % X))
    mx = os.path.join(sw, "owed-bridge-delete_" + "3d" * 32)
    json.dump({"version": 3, "remoteId": "cse_x", "sessionId": "local_" + X, "transcriptIds": [], "nonce": "n",
               "state": "intent", "action": "delete"}, open(mx, "w", encoding="utf-8"))
    rc, out = run(rvh, "move", "acct-w", "--only", X, "--to-profile", "acct-v")
    check(rc != 0 and "Remote Control" in out and not glob.glob(os.path.join(tv, "local_*.json")),
          "move --to-profile refuses a session with a Remote Control delete in progress")
    os.remove(mx)
    # An imported session not resumed yet: fine within the window (the absolute path keeps working), refused
    # to another window, by export-record and by unregister (its conversation is in no CLI home)
    xst_dir = os.path.join(sw, "imported-staging"); os.makedirs(xst_dir)
    xst = os.path.join(xst_dir, "cli-x.jsonl"); open(xst, "w", encoding="utf-8").write('{"turn": 1}\n')
    rx = json.load(open(os.path.join(sw, "local_%s.json" % X), encoding="utf-8"))
    rx.update(cliSessionId="cli-x", importedFrom="previous-profile-code", stagedTranscriptPath=xst)
    json.dump(rx, open(os.path.join(sw, "local_%s.json" % X), "w", encoding="utf-8"))
    for args_, what in ((("move", "acct-w", "--only", X, "--to-profile", "acct-v"), "move --to-profile"),
                        (("export-record", "acct-w", "--only", X, "--out", os.path.join(rvh, "x.json")),
                         "export-record"),
                        (("unregister", "acct-w", "--only", X), "unregister")):
        rc, out = run(rvh, *args_)
        check(rc != 0 and "not resumed yet" in out and os.path.exists(os.path.join(sw, "local_%s.json" % X)),
              f"{what} refuses an imported session not resumed yet (its conversation is only in imported-staging/)")
    rc, out = run(rvh, "move", "acct-w", "--only", X)
    mxr = os.path.join(tw, "local_%s.json" % X)
    check(rc == 0 and os.path.exists(mxr) and json.load(open(mxr, encoding="utf-8")).get("stagedTranscriptPath") == xst
          and os.path.exists(xst) and "imported-staging" in out,
          "a move within the window takes it, keeps the path to its staged conversation, and says where it stays")
    # Desktop resumes it under the new account: the staged copy goes to the CLI home and the record is confirmed.
    # A rollback would restore the old staged copy, which Desktop would later write over the newer conversation.
    arch_x = newest(rvh, "acct-w") if os.path.exists(mxr) else "19700101T000000Z-move"
    if os.path.exists(xst):
        os.remove(xst)
    rx = json.load(open(mxr, encoding="utf-8")) if os.path.exists(mxr) else dict(rx)
    rx.pop("stagedTranscriptPath", None); rx["resumeConfirmed"] = True
    json.dump(rx, open(mxr, "w", encoding="utf-8"))
    h_w = tree_hash(os.path.join(pw, "claude-code-sessions"))
    rc, out = run(rvh, "rollback", "acct-w", arch_x)
    check(rc != 0 and "resumed" in out and tree_hash(os.path.join(pw, "claude-code-sessions")) == h_w,
          "rollback refuses when an imported session was resumed since: its old staged copy would come back")
    os.remove(mxr)
    # A special file where Desktop keeps a known entry: refused cleanly, before an archive is started
    if hasattr(os, "mkfifo"):
        adir = os.path.join(sdir(rvh), "archive", "acct-w")
        n_arch = len(os.listdir(adir)) if os.path.isdir(adir) else 0
        os.mkfifo(os.path.join(sw, "archived-sessions.idx"))
        rc, out = run(rvh, "move", "acct-w", "--only", Y, "--accept-drift", timeout=60)
        n_arch2 = len(os.listdir(adir)) if os.path.isdir(adir) else 0
        check(rc not in (0, None) and "ERROR" in out and "Traceback" not in out and n_arch2 == n_arch,
              "a FIFO named archived-sessions.idx is an ERROR: no crash, no half-made archive")
        os.remove(os.path.join(sw, "archived-sessions.idx"))
    # adopt strips what export-record would have: a 0.11.1 or hand-made record keeps none of the old account's state
    raw = {"format": "ccd-record/1", "record": {
        "sessionId": "local_9a9a9a9a-0000-4000-8000-000000000007", "cliSessionId": "cli-adopted", "title": "raw",
        "cwd": "/p", "emailAddress": "old@example.com", "remoteControlUserEnabled": True,
        "remoteControlSpawn": {"ccrSessionId": "cse_1", "folder": "/p"}, "movedToCloud": {"cloudSessionId": "s"},
        "interruptedByQuitAt": 1, "peerInbound": {"u": {}}, "error": "x"}}
    json.dump(raw, open(os.path.join(rvh, "raw.json"), "w", encoding="utf-8"))
    rc, out = run(rvh, "adopt", "acct-v", "--record", os.path.join(rvh, "raw.json"))
    ad = [json.load(open(f, encoding="utf-8")) for f in glob.glob(os.path.join(tv, "local_*.json"))]
    ad = next((r for r in ad if r.get("cliSessionId") == "cli-adopted"), {})
    check(rc == 0 and ad and not {"emailAddress", "remoteControlUserEnabled", "remoteControlSpawn", "movedToCloud",
                                  "interruptedByQuitAt", "peerInbound", "error"} & set(ad)
          and ad.get("remoteClientLimits") is True and ad.get("remoteControlDescendant") is True,
          "adopt drops account-bound and transient fields itself, and keeps both Remote Control clamps")
    # The Remote Control lineage and request, an owed SSH turn, a cut first SSH turn, computer-use grants
    rec(sw, "9a9a9a9a-0000-4000-8000-000000000004", "root started from Remote Control",
        remoteControlSpawn={"ccrSessionId": "cse_r", "folder": "/p"}, remoteControlUserEnabled=False,
        pendingFirstStart={"since": 1, "options": {"remoteControlAtStart": True, "useWorktree": True}},
        sshConfig={"sshHost": "h"}, cutTurn={"state": "owed", "at": 1}, cuGrantFlags={"clipboardRead": True})
    rec(sw, "9a9a9a9a-0000-4000-8000-000000000005", "first SSH turn cut", cliSessionId=None, sshConfig={"sshHost": "h"},
        sshRemoteProcessId=77, sshReattach={"processId": 77, "namedCliSessionId": "abcd-named"})
    rc, out = run(rvh, "move", "acct-w", "--only", "9a9a9a9a-0000-4000-8000-000000000004",
                  "9a9a9a9a-0000-4000-8000-000000000005")
    m4 = json.load(open(os.path.join(tw, "local_9a9a9a9a-0000-4000-8000-000000000004.json"), encoding="utf-8")) \
        if os.path.exists(os.path.join(tw, "local_9a9a9a9a-0000-4000-8000-000000000004.json")) else {}
    m5 = json.load(open(os.path.join(tw, "local_9a9a9a9a-0000-4000-8000-000000000005.json"), encoding="utf-8")) \
        if os.path.exists(os.path.join(tw, "local_9a9a9a9a-0000-4000-8000-000000000005.json")) else {}
    check(rc == 0 and m4.get("remoteControlDescendant") is True and m4.get("remoteClientLimits") is True,
          "a root session started from Remote Control keeps its lineage (remoteControlDescendant) when its spawn "
          "id is dropped")
    check(m4.get("pendingFirstStart") == {"since": 1, "options": {"useWorktree": True}},
          "a held first start loses remoteControlAtStart (Desktop would otherwise derive a Remote Control request "
          "under the new account), and keeps its other options")
    check("cutTurn" not in m4 and m4.get("cuGrantFlags") == {"clipboardRead": True},
          "an owed SSH turn (cutTurn) is dropped like the quit-resume marks; computer-use grants stay on this machine")
    check(m5.get("cliSessionId") == "abcd-named",
          "a cut first SSH turn keeps its conversation: its id moves from sshReattach into cliSessionId")
    out_g = os.path.join(rvh, "g.json")
    run(rvh, "export-record", "acct-w", "--only", "9a9a9a9a-0000-4000-8000-000000000004", "--out", out_g)
    rc, out = run(rvh, "adopt", "acct-v", "--record", out_g, "--cwd", "/new/p")
    g = next((json.load(open(f, encoding="utf-8")) for f in glob.glob(os.path.join(tv, "local_*.json"))
              if json.load(open(f, encoding="utf-8")).get("title") == "root started from Remote Control"), {})
    check(rc == 0 and g and "cuGrantFlags" not in g, "adopt --cwd drops computer-use grant flags with their app list")
    # Cowork records carry the account's email and name into the session's environment: a move drops them
    cw = os.path.join(pw, "local-agent-mode-sessions", A, OA); os.makedirs(cw)
    json.dump({"sessionId": "local_cw1", "emailAddress": "old@example.com", "accountName": "Old", "title": "cw"},
              open(os.path.join(cw, "local_cw1.json"), "w", encoding="utf-8"))
    rc, out = run(rvh, "move", "acct-w", "--include-cowork", "--only", "cw1")
    cwm = os.path.join(pw, "local-agent-mode-sessions", B, OB, "local_cw1.json")
    cj = json.load(open(cwm, encoding="utf-8")) if os.path.exists(cwm) else {}
    check(rc == 0 and cj.get("title") == "cw" and not {"emailAddress", "accountName"} & set(cj),
          "a Cowork move drops the old account's emailAddress and accountName (Desktop refills them)")
    shutil.rmtree(rvh)

    print("0.11.2 review: reading Desktop's log (shared macOS log, same-second order, transitional lines, verify)")
    lh = os.path.join(home, "log-home"); os.makedirs(os.path.join(lh, ".claude", "projects"))
    menv = {"CCD_REHOME_PLATFORM": "darwin"}
    ldef = os.path.join(lh, "Library", "Application Support", "Claude")
    lacc = os.path.join(lh, ".claude-instances", "acct-l")
    for pp in (ldef, lacc):
        profile(home, pp); shutil.rmtree(os.path.join(pp, "logs"))
    os.makedirs(os.path.join(lh, "Library", "Logs", "Claude"))
    llog = os.path.join(lh, "Library", "Logs", "Claude", "main.log")
    with open(llog, "w", encoding="utf-8") as f:
        f.write(f"2026-11-12 09:00:00 [info] Loaded 0 persisted sessions from {ldef}/claude-code-sessions/{B}/{OB}\n")
        f.write("2026-11-12 09:30:00 [info] [account] User is logged out, skipping account ID wait\n")
        f.write("2026-11-12 09:30:00 [info] [account] User logged out during account ID wait, stopping early\n")
    rc, out = run(lh, "status", "default", "--json", env=menv)
    try:
        v = json.loads(out)[0]["verdict"]
    except (ValueError, LookupError, TypeError):
        v = None
    check(v == "signed-in", "macOS, two windows on one log: another window's signed-out launch lines (no path) do not "
                            "sign this one out; its cookie and lastKnownAccountUuid decide")
    shutil.rmtree(lacc)
    with open(llog, "w", encoding="utf-8") as f:
        f.write(f"2026-11-12 09:00:00 [info] Loaded 0 persisted sessions from {ldef}/claude-code-sessions/{B}/{OB}\n")
        f.write(f"2026-11-12 09:30:00 [info] [account] Login-state transition (loggedOut: false \u2192 true, uuid: {B} "
                f"\u2192 <none>), clearing oauth cache\n")
    rc, out = run(lh, "status", "default", "--json", env=menv)
    try:
        v = json.loads(out)[0]["verdict"]
    except (ValueError, LookupError, TypeError):
        v = None
    check(v == "signed-out", "(guard) macOS, the default window alone on its log: its sign-out line still counts")
    pl = profile(lh, "acct-same", signed_in=B, logs=[
        "2026-11-12 15:16:02 [info] [account] User logged out during account ID wait, stopping early",
        f"2026-11-12 15:16:02 [info] [account] Login-state transition (loggedOut: true \u2192 false, uuid: <none> "
        f"\u2192 {B}), clearing oauth cache",
        "2026-11-12 15:16:02 [info] claude.ai account active and logged in"])
    rc, out = run(lh, "status", "acct-same", "--json")
    try:
        v = json.loads(out)[0]["verdict"]
    except (ValueError, LookupError, TypeError):
        v = None
    check(v == "signed-in", "a sign-out and a sign-in in the same second: the log's order decides (signed in)")
    pt = profile(lh, "acct-trans", signed_in=A, logs=[])
    st_ = os.path.join(pt, "claude-code-sessions")
    open(os.path.join(pt, "logs", "main.log"), "w", encoding="utf-8").write(
        init("08:00:00", A, OA).replace("2026-11-07", "2026-11-12") + "\n" +
        init("09:00:00", A, OB).replace("2026-11-07", "2026-11-12") + "\n" +
        f"2026-11-12 09:00:01 [info] Loaded 0 persisted sessions from {st_}/{A}/{OB} (1 archived deferred, 1 of them "
        f"unopened; hint used)\n" + init("09:00:02", B, OB).replace("2026-11-07", "2026-11-12") + "\n")
    rc, out = run(lh, "status", "acct-trans", "--json")
    try:
        ad_ = json.loads(out)[0]["active_dir"]
    except (ValueError, LookupError, TypeError):
        ad_ = None
    check(ad_ == os.path.join(st_, A, OA), "a transitional (old account, new org) init is skipped even when its "
                                          "Loaded line is a second later: the account's own org is found")
    pv = profile(lh, "acct-ver", signed_in=B, logs=[])
    dv = os.path.join(pv, "claude-code-sessions", B, OB)
    for n, arch in ((1, False), (2, True), (3, True)):
        rec(dv, "7c7c7c7c-0000-4000-8000-00000000000%d" % n, "v%d" % n, isArchived=arch)
    open(os.path.join(pv, "logs", "main.log"), "w", encoding="utf-8").write(
        "2026-11-12 15:17:12 [info] Starting app {\n"
        f"2026-11-12 15:17:13 [info] Loaded 1 persisted sessions from {dv} (2 archived deferred, 2 of them unopened; "
        f"hint used)\n")
    rc, out = run(lh, "verify", "acct-ver")
    check(rc != 0 and "MISMATCH" not in out and "archived" in out and "re-run" in out,
          "verify while Desktop 5's deferred pass is still loading 2 archived sessions: 'wait and re-run', not "
          "MISMATCH")
    open(os.path.join(pv, "logs", "main.log"), "w", encoding="utf-8").write(
        "2026-11-12 15:17:12 [info] Starting app {\n"
        f"2026-11-12 15:17:13 [info] Loaded 3 persisted sessions from {dv}\n"
        f"2026-11-12 15:40:00 [info] Loaded 0 persisted sessions from {dv}\n")
    rc, out = run(lh, "verify", "acct-ver")
    check(rc == 0 and "OK" in out, "verify after the same account signed out and in again in one launch (Desktop "
                                   "reloads 0, keeping the 3 it has): OK from the launch's full load")
    shutil.rmtree(lh)

    print("0.11.2 review: the retention warning (crashes, cost, earlier conversations, rows, Desktop entrypoints)")
    th = os.path.join(home, "ret2-home"); os.makedirs(th)
    tp = profile(th, "acct-t", signed_in=A, logs=[init("09:00:00", A, OA)])
    tdir = os.path.join(tp, "claude-code-sessions", A, OA)
    tkey = os.path.join(th, ".claude", "projects", "-t-proj"); os.makedirs(tkey)
    old60 = time.time() - 60 * 86400

    def tconv(sid, eps, age=None):
        t = os.path.join(tkey, sid + ".jsonl")
        with open(t, "w", encoding="utf-8") as f:
            for n, ep in enumerate(eps):
                f.write(json.dumps({"type": "user", "uuid": "u%d" % n, "cwd": "/t", "sessionId": sid, "entrypoint": ep,
                                    "message": {"content": "x"}}) + "\n")
        if age:
            os.utime(t, (age, age))
        return t
    T0, T1, T2, T3, T4 = ("5e5e5e5e-0000-4000-8000-00000000000%d" % n for n in range(5))
    tconv(T0, ["claude-desktop"], old60); tconv(T1, ["claude-desktop"])
    rec(tdir, T1, "current fresh, earlier one old", cliSessionId=T1, priorCliSessionIds=[T0])
    rc, out = run(th, "doctor", env=VOLD)
    check("acct-t: 1 of 2 Desktop conversation" in out,
          "an earlier conversation of a record (priorCliSessionIds) is checked too: Claude Code 2.1.100 deletes it")
    rec(tdir, "5e5e5e5e-0000-4000-8000-0000000000aa", "same conversation again", cliSessionId=T1,
        priorCliSessionIds=[T0])
    rc, out = run(th, "doctor", env=VOLD)
    check("acct-t: 1 of 2 Desktop conversation" in out, "a conversation two records name is counted once")
    os.remove(os.path.join(tdir, "local_5e5e5e5e-0000-4000-8000-0000000000aa.json"))
    open(os.path.join(tdir, "local_5e5e5e5e-0000-4000-8000-0000000000bb.json"), "w", encoding="utf-8").write('"x"')
    rec(tdir, "5e5e5e5e-0000-4000-8000-0000000000cc", "bad id", cliSessionId=12345)
    rc, out = run(th, "doctor", env=VOLD)
    rc2, out2 = run(th, "status", env=VOLD)
    check("Traceback" not in out + out2 and "acct-t:" in out and rc2 == 0,
          "doctor and status survive a record that is not an object and a cliSessionId that is not a string")
    os.remove(os.path.join(tdir, "local_5e5e5e5e-0000-4000-8000-0000000000bb.json"))
    os.remove(os.path.join(tdir, "local_5e5e5e5e-0000-4000-8000-0000000000cc.json"))
    odd = os.path.join(home, "fake-claude-odd"); os.makedirs(odd)
    if not sys.platform.startswith("win"):
        with open(os.path.join(odd, "claude"), "wb") as f:
            f.write(b"#!/bin/sh\nprintf '\\351 2.1.100 (Claude Code)\\n'\nprintf '\\377' >&2\n")
        os.chmod(os.path.join(odd, "claude"), 0o755)
        rc, out = run(th, "status", env={"PATH": odd + os.pathsep + os.environ.get("PATH", "")})
        check(rc == 0 and "Traceback" not in out, "a `claude --version` that prints bytes that are not UTF-8 crashes nothing")
        marker = os.path.join(home, "claude-ran")
        with open(os.path.join(odd, "claude"), "w", encoding="utf-8") as f:
            f.write("#!/bin/sh\ntouch '" + marker + "'\necho '2.1.100 (Claude Code)'\n")
        tempty = profile(th, "acct-empty", signed_in=A, logs=[init("09:00:00", A, OA)])
        rc, out = run(th, "status", "acct-empty", env={"PATH": odd + os.pathsep + os.environ.get("PATH", "")})
        check(rc == 0 and not os.path.exists(marker),
              "status runs `claude --version` only when a conversation is old enough for the answer to matter")
    tset = os.path.join(th, ".claude", "settings.json")
    for val, why in (("1e999", "a value too large for a number"), ("0", "0 (a settings error: Claude Code pauses")):
        open(tset, "w", encoding="utf-8").write('{"cleanupPeriodDays": %s}' % val)
        rc, out = run(th, "doctor", env=VOLD)
        check("Traceback" not in out and "acct-t: no Desktop conversation" in out,
              f"cleanupPeriodDays {why}{' its cleanup)' if val == '0' else ''}: no crash, no warning")
    os.remove(tset)
    tconv(T2, ["claude-desktop-3p"], old60); tconv(T3, ["local-agent"], old60)
    tconv(T4, ["cli", "cli"], time.time() - 40 * 86400)
    for sid in (T2, T3, T4):
        rec(tdir, sid, "conv " + sid[-1], cliSessionId=sid)
    open(tset, "w", encoding="utf-8").write('{"desktopSessionCleanupPeriodDays": 45}')
    rc, out = run(th, "status", "acct-t", "--json", env=VNEW)
    try:
        rr = json.loads(out)[0]["retention_risk"]
    except (ValueError, LookupError, TypeError):
        rr = []
    by = {r.get("setting"): r for r in rr}
    check(by.get("desktopSessionCleanupPeriodDays", {}).get("n") == 3 and by.get("cleanupPeriodDays", {}).get("n") == 1,
          "Claude Code 2.1.300: one row per setting: the three Desktop conversations (claude-desktop, "
          "claude-desktop-3p, Cowork's local-agent) under desktopSessionCleanupPeriodDays 45, the terminal one under "
          "cleanupPeriodDays 30")
    rc, out = run(th, "status", "acct-t", env=VNEW)
    check("may delete" in out, "with Claude Code 2.1.248 or later the warning says 'may delete' (settings this tool "
                               "models from the documentation), not that it will")
    os.remove(tset)
    shutil.rmtree(th)

finally:
    shutil.rmtree(home)
print(f"\n{'ALL PASS' if not fails else str(len(fails)) + ' FAILED'}")
sys.exit(1 if fails else 0)
