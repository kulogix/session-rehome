#!/usr/bin/env python3
"""MANUAL end-to-end test: a session moved between two CLI homes by `ccd-rehome move` is found by the REAL Claude Code
CLI in the target home, and no longer in the source home; after `ccd-rehome rollback`, the reverse.

It is not run by tests/run_all.py (its name does not start with `test_`), and it skips, printing why, unless both:
  - the environment variable SESSION_REHOME_E2E=1 is set, and
  - a `claude` executable is on PATH.

    SESSION_REHOME_E2E=1 python3 tests/e2e_real_cli.py

What it does, all inside one new temporary folder (removed at the end; nothing else is read or written):
  1. builds two synthetic CLI homes, A (`<tmp>/.claude-e2ea`) and B (`<tmp>/.claude-e2eb`), and a small synthetic
     transcript in A at projects/<mangle(cwd)>/<id>.jsonl: a user record and an assistant record (uuid,
     parentUuid, sessionId, cwd, type, message) and a custom-title record; it creates the folder cwd;
  2. runs `ccd-rehome move A --only <id> --to-profile B` with CCD_REHOME_HOME=<tmp> and CCD_REHOME_SANDBOX=1;
  3. runs the real `claude -p --resume <id> ping` from cwd, once with CLAUDE_CONFIG_DIR=B and once with
     CLAUDE_CONFIG_DIR=A. The API is pointed at a closed port (ANTHROPIC_BASE_URL=http://127.0.0.1:1, a dummy
     ANTHROPIC_API_KEY), so no account is used and no turn is spent; HOME is a folder inside <tmp>, stdin is
     /dev/null, each run has 90 s;
  4. PASS when B's run ends in a connection error (the CLI found and loaded the session, then could not reach the
     API) and A's run says "No conversation found". The two runs are each other's control: A's shows that the CLI
     looks the session up before it tries the network, so B's connection error comes after a successful lookup;
  5. runs `ccd-rehome rollback B <archive>` and checks the reverse: A finds it, B does not.

It prints the CLI's version and, for any step that fails, what the CLI printed. Exit 0: passed or skipped; 1: failed.
Record a pass in skills/session-rehome/references/mechanics.md section 4b (date, CLI version, OS).
"""
import importlib.machinery
import importlib.util
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(os.path.dirname(HERE), "skills", "session-rehome", "scripts", "ccd-rehome")
SID = "e2e2e2e2-0000-4000-8000-000000000001"           # synthetic ids (tests/test_privacy.py)
U1, U2 = "e2e2e2e2-0000-4000-8000-0000000000a1", "e2e2e2e2-0000-4000-8000-0000000000a2"
NOT_FOUND = re.compile(r"No conversation found")
# What the CLI prints when it cannot reach the API (a closed port refuses at once; a firewall that drops the packets
# makes it time out after API_TIMEOUT_MS).
CONNECTION = re.compile(r"(?i)connection error|ECONNREFUSED|unable to connect|fetch failed|connection refused|"
                        r"ConnectionRefused|could not connect|ETIMEDOUT|request timed out")
TIMEOUT = 90


def skip(why):
    print(f"SKIPPED: {why}")
    print("This is a manual test with the real Claude Code CLI. Run it with: "
          "SESSION_REHOME_E2E=1 python3 tests/e2e_real_cli.py")
    sys.exit(0)


def mangle(path):
    """ccd-rehome's own mangle() (Claude Code's project-dir name for a folder)."""
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_loader("ccd_rehome_e2e", importlib.machinery.SourceFileLoader("ccd_rehome_e2e",
                                                                                                    TOOL))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.mangle(path)


def clean_env(extra):
    """The caller's PATH and locale only: no CLAUDE_*, ANTHROPIC_*, CCD_REHOME_* or HOME of the caller."""
    keep = ("PATH", "LANG", "LC_ALL", "SYSTEMROOT", "TMPDIR", "TEMP", "TMP")
    env = {k: v for k, v in os.environ.items() if k in keep}
    env.update(extra)
    return env


def write_transcript(home, cwd):
    d = os.path.join(home, "projects", mangle(cwd))
    os.makedirs(d, mode=0o700)
    common = {"isSidechain": False, "userType": "external", "cwd": cwd, "sessionId": SID, "gitBranch": ""}
    rows = [dict(common, parentUuid=None, type="user", uuid=U1, timestamp="2026-11-08T10:00:00.000Z",
                 message={"role": "user", "content": "hello"}),
            dict(common, parentUuid=U1, type="assistant", uuid=U2, timestamp="2026-11-08T10:00:01.000Z",
                 message={"id": "msg_e2e", "type": "message", "role": "assistant", "model": "claude-sonnet-4-5",
                          "content": [{"type": "text", "text": "hello"}], "stop_reason": "end_turn",
                          "stop_sequence": None, "usage": {"input_tokens": 1, "output_tokens": 1}}),
            {"type": "custom-title", "customTitle": "session-rehome e2e", "sessionId": SID}]
    path = os.path.join(d, SID + ".jsonl")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("".join(json.dumps(r) + "\n" for r in rows))
    return path


def tool(tmp, *args):
    env = clean_env({"CCD_REHOME_HOME": tmp, "CCD_REHOME_SANDBOX": "1", "PYTHONIOENCODING": "utf-8"})
    r = subprocess.run([sys.executable, "-I", TOOL, *args], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=env, stdin=subprocess.DEVNULL, timeout=120)
    return r.returncode, r.stdout + r.stderr


def claude(exe, tmp, config_dir, cwd, *args):
    env = clean_env({"HOME": os.path.join(tmp, "home"), "USERPROFILE": os.path.join(tmp, "home"),
                     "CLAUDE_CONFIG_DIR": config_dir, "ANTHROPIC_BASE_URL": "http://127.0.0.1:1",
                     "ANTHROPIC_API_KEY": "x", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
                     "API_TIMEOUT_MS": "8000", "CLAUDE_CODE_MAX_RETRIES": "0", "DISABLE_AUTOUPDATER": "1"})
    try:
        r = subprocess.run([exe, *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", env=env, stdin=subprocess.DEVNULL, timeout=TIMEOUT)
    except subprocess.TimeoutExpired as e:          # its partial output: bytes on POSIX, text on Windows, or None
        return None, "".join(x.decode("utf-8", "replace") if isinstance(x, bytes) else (x or "")
                             for x in (e.stdout, e.stderr))
    return r.returncode, r.stdout + r.stderr


def main():
    if os.environ.get("SESSION_REHOME_E2E") != "1":
        skip("SESSION_REHOME_E2E=1 is not set")
    exe = shutil.which("claude")
    if not exe:
        skip("no `claude` executable on PATH")
    results = []

    def check(ok, what, out=None, evidence=False):
        print(("PASS " if ok else "FAIL ") + what)
        if not ok and out is not None:
            print("    | " + (out.strip() or "(no output)").replace("\n", "\n    | ")[-3000:])
        elif evidence and out is not None:          # what the CLI said, for the record in mechanics.md
            print("".join("    > " + l + "\n" for l in [x for x in out.splitlines() if x.strip()][-3:]), end="")
        results.append(ok)
        return ok

    tmp = os.path.realpath(tempfile.mkdtemp(prefix="sr-e2e-"))
    try:
        os.makedirs(os.path.join(tmp, "home"), mode=0o700)
        rc, out = claude(exe, tmp, os.path.join(tmp, "version-home"), tmp, "--version")
        print(f"claude: {exe}")
        print(f"claude --version: {out.strip() or '(nothing)'} (rc {rc})")
        print(f"on: {platform.system()} {platform.release()} {platform.machine()}, Python {platform.python_version()}")
        homes = {k: os.path.join(tmp, ".claude-e2e" + k.lower()) for k in ("A", "B")}
        for h in homes.values():
            os.makedirs(os.path.join(h, "projects"), mode=0o700)
        cwd = os.path.join(tmp, "proj")
        os.makedirs(cwd)
        src = write_transcript(homes["A"], cwd)
        dst = os.path.join(homes["B"], os.path.relpath(src, homes["A"]))

        def found_only_in(have, lack):
            rc, out = claude(exe, tmp, homes[have], cwd, "-p", "--resume", SID, "ping")
            check(rc is not None and not NOT_FOUND.search(out) and CONNECTION.search(out) is not None,
                  f"claude -p --resume ID with CLAUDE_CONFIG_DIR={have}: found and loaded the session (it then hit "
                  f"the closed API port: a connection error, no turn spent)"
                  + ("" if rc is not None else f"; killed after {TIMEOUT}s"), out, evidence=True)
            rc, out = claude(exe, tmp, homes[lack], cwd, "-p", "--resume", SID, "ping")
            check(rc is not None and NOT_FOUND.search(out) is not None,
                  f"claude -p --resume ID with CLAUDE_CONFIG_DIR={lack}: \"No conversation found\""
                  + ("" if rc is not None else f"; killed after {TIMEOUT}s"), out, evidence=True)

        rc, out = tool(tmp, "move", homes["A"], "--only", SID, "--to-profile", homes["B"])
        arch = next((w for w in out.split() if w.endswith("-cli-move")), None)
        if check(bool(rc == 0 and os.path.isfile(dst) and not os.path.exists(src) and arch),
                 "ccd-rehome move A --only ID --to-profile B moved the transcript (and printed its archive)", out):
            found_only_in("B", "A")
            rc, out = tool(tmp, "rollback", homes["B"], arch)
            if check(rc == 0 and os.path.isfile(src) and not os.path.exists(dst),
                     "ccd-rehome rollback B ARCHIVE moved the transcript back to A", out):
                found_only_in("A", "B")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    ok = all(results)
    print("\nE2E PASSED" if ok else "\nE2E FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
