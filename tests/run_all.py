#!/usr/bin/env python3
"""Run every test in the repository: both skills' self-tests, then the repository tests.

    python3 tests/run_all.py            all of it
    python3 tests/run_all.py --quick    repository tests only (seconds; no self-tests)
    SELFTEST_VERBOSE=1 ...              print tool output under each failing self-test check

Exit 0 only if everything passed. Nothing outside temporary folders is touched. On Linux, a full run also compares
the self-test counts that the newest CHANGELOG entry states with the counts of this run (see count_claims_differ).
"""
import os
import subprocess
import sys
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SELFTESTS = [("session-rehome", os.path.join(ROOT, "skills", "session-rehome", "scripts", "selftest.py")),
             ("session-transporter",
              os.path.join(ROOT, "skills", "session-transporter", "scripts", "selftest.py"))]


def count_claims_differ(outputs):
    """How the self-test counts the newest CHANGELOG entry states differ from this run's (an empty list: they agree),
    or None when this run cannot tell: the counts are stated for Linux, where nothing is skipped, run as a normal
    user (some checks need a user that file modes apply to), with no emulated platform."""
    sys.path.insert(0, HERE)
    from _common import changelog_newest, check_count_claims, selftest_sections
    if not sys.platform.startswith("linux") or os.geteuid() == 0 or os.environ.get("CCD_REHOME_PLATFORM") \
            or any("(skipped" in out for out in outputs.values()):
        return None
    with open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8") as f:
        version, body = changelog_newest(f.read())
    claims, diffs = check_count_claims(body), []
    sections = selftest_sections(outputs.get("session-rehome", ""))
    for name, out in outputs.items():
        if name in claims and claims[name] != out.count("  PASS "):
            diffs.append(f"{name}: CHANGELOG {version} says {claims[name]} checks, this run has {out.count('  PASS ')}")
    for title, n in claims["sections"].items():
        if sections.get(title) != n:
            diffs.append(f"session-rehome section {title!r}: CHANGELOG {version} says {n} checks, this run has "
                         f"{sections.get(title, 'no such section')}")
    return diffs


def main():
    sys.dont_write_bytecode = True
    quick = "--quick" in sys.argv[1:]
    results, outputs = [], {}
    if not quick:
        for name, path in SELFTESTS:
            t0 = time.time()
            env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1",
                       ST_REHOME=os.path.join(ROOT, "skills", "session-rehome", "scripts", "ccd-rehome"))
            p = subprocess.run([sys.executable, "-I", path], capture_output=True, text=True, encoding="utf-8",
                               errors="replace", env=env)
            out = p.stdout + p.stderr
            outputs[name] = out
            passed = out.count("  PASS ")
            failed = [l.strip() for l in out.splitlines() if l.startswith("  FAIL ")]
            print(f"== {name} self-test: {passed} passed, {len(failed)} failed  ({time.time() - t0:.0f}s)")
            detail = False
            for line in out.splitlines():           # each FAIL, with the tool output SELFTEST_VERBOSE adds under it
                if line.startswith("  FAIL "):
                    print("   " + line.strip())
                    detail = True
                elif detail and line.startswith("    ") and not line.startswith("  PASS "):
                    print("   " + line)
                else:
                    detail = False
            if p.returncode and "Traceback" in out:  # a crash ends the self-test early: show where
                print("\n".join("   | " + l for l in out[out.rindex("Traceback"):].splitlines()[-15:]))
            if p.returncode and not failed:
                print("\n".join("   | " + l for l in out.splitlines()[-25:]))
            results.append(p.returncode == 0)
        diffs = count_claims_differ(outputs)
        if diffs is None:
            print("== CHANGELOG check counts: not compared (they are stated for a Linux run with nothing skipped)")
        else:
            print(f"== CHANGELOG check counts: {'they match this run' if not diffs else 'WRONG'}")
            for d in diffs:
                print("   " + d)
            results.append(not diffs)
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
