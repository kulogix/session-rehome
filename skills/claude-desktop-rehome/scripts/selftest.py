#!/usr/bin/env python3
"""Self-test for ccd-rehome. Builds synthetic Desktop profiles in a temp HOME (no real data is read or written)
and checks every rule the tool promises. Run:  python3 -I selftest.py      exit 0 = all pass."""
import datetime, glob, hashlib, json, os, shutil, sqlite3, subprocess, sys, tempfile
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


def run(home, *args, env=None):
    e = dict(os.environ, CCD_REHOME_HOME=home, CCD_REHOME_SANDBOX="1", **(env or {}))
    e.pop("CCD_REHOME_STATE", None)
    e["PYTHONIOENCODING"] = "utf-8"
    r = subprocess.run([sys.executable, "-I", TOOL, *args], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=e)
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


def tree_hash(d):
    h = hashlib.sha256()
    for f in sorted(glob.glob(os.path.join(d, "**", "*"), recursive=True)):
        h.update(os.path.relpath(f, d).encode())
        if os.path.isfile(f):
            h.update(open(f, "rb").read())
    return h.hexdigest()


def disp(*parts):
    """How the tool prints a path under HOME on this OS: ~ + native separators."""
    return "~" + os.sep + os.path.join(*parts)


def newest(home, prof, kind="move"):
    d = os.path.join(home, ".claude-instances", "_rehome", "archive", prof)
    return sorted(x for x in os.listdir(d) if x.endswith("-" + kind))[-1]


def j(home, *args):
    rc, out = run(home, *args, "--json")
    return json.loads(out)


home = os.path.realpath(tempfile.mkdtemp(prefix="ccd-rehome-test-"))   # macOS: /var -> /private/var
try:
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
    reg = json.load(open(os.path.join(home, ".claude-instances", "_rehome", "accounts.json"), encoding="utf-8"))["accounts"]
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
    h_home = tree_hash(home)
    rc, out = run(home, "rehome", "acct-p1")
    check(rc != 0 and "DRIFT" in out and "newDesktopField" in out and "new-per-account-store" in out
          and "nothing was changed" in out and tree_hash(home) == h_home,
          "real run refuses on DRIFT (unknown field + unknown entry), names both, writes nothing")
    rc, out = run(home, "rehome", "acct-p1", "--dry-run")
    check(rc == 0 and "DRIFT" in out and "--accept-drift" not in out.split("DRIFT")[0], "dry run reports DRIFT and still shows the plan")
    rc, out = run(home, "move", "acct-p1", "--only", "dr1", "--accept-drift")
    check(rc == 0 and json.load(open(os.path.join(dst, "local_dr1.json"), encoding="utf-8"))["newDesktopField"] == {"x": 1},
          "--accept-drift proceeds (unknown field carried as-is)")
    rc, out = run(home, "rollback", "acct-p1", newest(home, "acct-p1"))
    os.remove(os.path.join(sa, "local_dr1.json")); os.rmdir(os.path.join(sa, "new-per-account-store"))
    json.dump({"version": 1, "items": [{"no_id": 1}]}, open(os.path.join(sa, "backlog", "tasks.json"), "w", encoding="utf-8"))
    h_home = tree_hash(home)
    rc, out = run(home, "rehome", "acct-p1", "--accept-drift")
    check(rc != 0 and "ERROR" in out and "tasks.json" in out and tree_hash(home) == h_home,
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
        queryCrashes=[], shellFolders=["/p"], spawnedFrom={"sessionId": "local_x"}, turnBoxDeclared=True,
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
    reg_f = os.path.join(home, ".claude-instances", "_rehome", "accounts.json")
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
    keys = os.listdir(os.path.join(home, ".claude-instances", "_rehome", "archive"))
    check("acct-p1" in keys and any(k.startswith("path-work_desktop_profiles_acct-p1-") for k in keys),
          "two profiles with the same folder name get separate archive keys")
    arch5 = os.listdir(os.path.join(home, ".claude-instances", "_rehome", "archive",
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

    print("export-record / adopt (the interface claude-session-transporter uses)")
    src = profile(home, "acct-x1", logs=[init("09:00:00", A, OA)], signed_in=A)
    rx = rec(os.path.join(src, "claude-code-sessions", A, OA), "e1e1e1e1-0000-4000-8000-000000000001", "Café export",
             cwd="/old/host/proj", originCwd="/old/host/proj", gitAnchorsFolderRealpath="/old/host/proj",
             planPath="/old/.claude/plans/p.md", shellFolders=["/old/host/proj/x"], cuAllowedApps=[{"bundleId": "a"}],
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
    check(not {"gitAnchorsFolderRealpath", "planPath", "shellFolders", "cuAllowedApps", "chromeTabGroupId"} & set(pr)
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
    a_arch = sorted(x for x in os.listdir(os.path.join(home, ".claude-instances", "_rehome", "archive", "acct-x2"))
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
    tm = os.path.join(os.path.dirname(os.path.dirname(HERE)), "claude-session-transporter", "scripts", "mangle.py")
    if os.path.isfile(tm):
        sys.path.insert(0, os.path.dirname(tm)); import mangle as canon
        cases = ["/home/u/Projects/a b", "/a/b.c_d", "/Users/x/Café/漢字", "/p/" + "x" * 230, "C:\\Users\\x\\proj"]
        check(all(cr2.mangle(c) == canon.mangle(c) for c in cases),
              "rehome's mangle matches claude-session-transporter's canonical mangle.py (incl. >200 chars, non-ASCII)")
    else:
        print("  (skipped mangle cross-check: claude-session-transporter not installed next to this skill)")
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
    ua = sorted(x for x in os.listdir(os.path.join(home, ".claude-instances", "_rehome", "archive", "acct-reg"))
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
        with open(os.path.join(fake, "claude.cmd"), "w") as f:
            f.write("@echo 2.1.100 (Claude Code)\r\n")
    else:
        with open(os.path.join(fake, "claude"), "w") as f:
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
finally:
    shutil.rmtree(home)
print(f"\n{'ALL PASS' if not fails else str(len(fails)) + ' FAILED'}")
sys.exit(1 if fails else 0)
