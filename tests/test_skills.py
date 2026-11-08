"""Each skill is well-formed, routable, and self-contained."""
import os
import sys
import re
import unittest

from _common import SKILLS, frontmatter, read_text

NAMES = sorted(d for d in os.listdir(SKILLS) if os.path.isfile(os.path.join(SKILLS, d, "SKILL.md")))


class Skills(unittest.TestCase):
    def test_both_skills_present(self):
        self.assertEqual(NAMES, ["claude-desktop-rehome", "claude-session-transporter"])

    def test_frontmatter(self):
        for n in NAMES:
            fm, body = frontmatter(os.path.join(SKILLS, n, "SKILL.md"))
            self.assertIsNotNone(fm, f"{n}: SKILL.md must start with --- frontmatter ---")
            self.assertEqual(fm.get("name"), n, f"{n}: frontmatter name must equal the directory name")
            self.assertRegex(n, r"^[a-z0-9]+(-[a-z0-9]+)*$")
            d = fm.get("description", "")
            self.assertTrue(d, f"{n}: description missing")
            self.assertLessEqual(len(d), 1024, f"{n}: description is {len(d)} chars (limit 1024)")
            self.assertGreater(len(body.strip()), 500, f"{n}: SKILL.md body looks empty")

    def test_routing_is_mutual_and_early(self):
        """Each skill names the other near the top, so an agent that loaded the wrong one is redirected."""
        for n in NAMES:
            other = [x for x in NAMES if x != n][0]
            fm, body = frontmatter(os.path.join(SKILLS, n, "SKILL.md"))
            self.assertIn(other, fm["description"] + body[:2500], f"{n}: must route to {other} in its first screen")

    def test_no_hardcoded_install_paths(self):
        """A skill may be installed as a personal skill, a plugin, or run from a checkout: no fixed path."""
        for n in NAMES:
            s = read_text(os.path.join(SKILLS, n, "SKILL.md"))
            self.assertNotRegex(s, r"~/\.claude/skills/[a-z-]+/scripts",
                                f"{n}: refer to scripts relative to the skill's base directory, not a fixed path")

    def test_referenced_files_exist(self):
        for n in NAMES:
            base = os.path.join(SKILLS, n)
            s = read_text(os.path.join(base, "SKILL.md"))
            for ref in sorted(set(re.findall(r"`((?:scripts|references)/[A-Za-z0-9_.\-/]+)`", s))):
                self.assertTrue(os.path.exists(os.path.join(base, ref)), f"{n}: SKILL.md references missing {ref}")

    def test_scripts_are_executable_or_python(self):
        for n in NAMES:
            sd = os.path.join(SKILLS, n, "scripts")
            for f in os.listdir(sd):
                p = os.path.join(sd, f)
                if not os.path.isfile(p) or f.endswith((".md", ".example", ".pyc")):
                    continue
                with open(p, "rb") as fh:
                    head = fh.read(400)
                if head.startswith(b"#!") and b"do not execute it" not in head:   # sourced libraries are exempt
                    if os.name != "nt":
                        self.assertTrue(os.access(p, os.X_OK), f"{n}/scripts/{f} has a shebang but is not executable")

    def test_scripts_use_only_the_stdlib(self):
        """Python tools must run on a bare Python 3.9+ (no pip install step anywhere)."""
        stdlib = set(getattr(sys, "stdlib_module_names", ())) or {
            "argparse", "base64", "binascii", "codecs", "collections", "concurrent", "contextlib", "copy", "csv",
            "datetime", "difflib", "errno", "fnmatch", "functools", "glob", "hashlib", "http", "importlib", "io",
            "itertools", "json", "locale", "math", "os", "pathlib", "platform", "queue", "random", "re", "select",
            "shlex", "shutil", "signal", "socket", "sqlite3", "stat", "string", "struct", "subprocess", "sys",
            "tempfile", "textwrap", "threading", "time", "traceback", "unicodedata", "unittest", "urllib", "uuid",
            "zipfile", "zlib", "__future__"}
        local = {"mangle", "_common", "st_walk", "st_origin_probe", "st_mock_api"}
        bad = []
        for n in NAMES:
            sd = os.path.join(SKILLS, n, "scripts")
            for f in sorted(os.listdir(sd)):
                p = os.path.join(sd, f)
                if not os.path.isfile(p):
                    continue
                src = read_text(p) or ""
                if not (f.endswith(".py") or src.startswith("#!/usr/bin/env python3")):
                    continue
                for m in re.finditer(r"^\s*(?:import\s+([\w., ]+)|from\s+([\w.]+)\s+import)", src, re.M):
                    for mod in (m.group(1) or m.group(2)).split(","):
                        top = mod.strip().split(" as ")[0].strip().split(".")[0]
                        if top and top not in stdlib and top not in local:
                            bad.append(f"{n}/scripts/{f} imports {top}")
        self.assertEqual(sorted(set(bad)), [])

    def test_relative_references_stay_inside_the_skill(self):
        """`../FILE` named in a script must exist inside that skill's own folder: a copied or plugin-installed
        skill gets only its folder, so a pointer to the repository root (README, docs/, CONTRIBUTING) breaks."""
        bad = []
        for n in NAMES:
            sd = os.path.join(SKILLS, n, "scripts")
            for f in sorted(os.listdir(sd)):
                p = os.path.join(sd, f)
                if not os.path.isfile(p):
                    continue
                for ref in re.findall(r"(?<![\w./])((?:\.\./)+[\w./-]+\.(?:md|json|py|sh))", read_text(p) or ""):
                    full = os.path.normpath(os.path.join(sd, ref))
                    inside = full.startswith(os.path.join(SKILLS, n) + os.sep)
                    if not inside or not os.path.exists(full):
                        bad.append(f"{n}/scripts/{f}: {ref}" + ("" if inside else " (outside the skill)"))
        self.assertEqual(bad, [])

if __name__ == "__main__":
    unittest.main()
