#!/usr/bin/env python3
"""Run every test in the repository: both skills' self-tests, then the repository tests.

    python3 tests/run_all.py            all of it
    python3 tests/run_all.py --quick    repository tests only (seconds; no self-tests)
    SELFTEST_VERBOSE=1 ...              print tool output under each failing self-test check

Exit 0 only if everything passed. Nothing outside temporary folders is touched.
"""
import os
import subprocess
import sys
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SELFTESTS = [("claude-desktop-rehome", os.path.join(ROOT, "skills", "claude-desktop-rehome", "scripts", "selftest.py")),
             ("claude-session-transporter",
              os.path.join(ROOT, "skills", "claude-session-transporter", "scripts", "selftest.py"))]


def main():
    sys.dont_write_bytecode = True
    quick = "--quick" in sys.argv[1:]
    results = []
    if not quick:
        for name, path in SELFTESTS:
            t0 = time.time()
            env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1",
                       ST_REHOME=os.path.join(ROOT, "skills", "claude-desktop-rehome", "scripts", "ccd-rehome"))
            p = subprocess.run([sys.executable, "-I", path], capture_output=True, text=True, encoding="utf-8",
                               errors="replace", env=env)
            out = p.stdout + p.stderr
            passed = out.count("  PASS ")
            failed = [l.strip() for l in out.splitlines() if l.startswith("  FAIL ")]
            print(f"== {name} self-test: {passed} passed, {len(failed)} failed  ({time.time() - t0:.0f}s)")
            for f in failed:
                print("   " + f)
            if p.returncode and not failed:
                print("\n".join("   | " + l for l in out.splitlines()[-25:]))
            results.append(p.returncode == 0)
    print("== repository tests")
    sys.path.insert(0, HERE)
    suite = unittest.defaultTestLoader.discover(HERE, pattern="test_*.py", top_level_dir=HERE)
    r = unittest.TextTestRunner(verbosity=1).run(suite)
    results.append(r.wasSuccessful())
    ok = all(results)
    print("\nALL TESTS PASSED" if ok else "\nSOME TESTS FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
