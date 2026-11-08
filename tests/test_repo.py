"""Repository invariants: links resolve, manifests are well-formed, one version everywhere, required files exist."""
import json
import os
import re
import unittest
from urllib.parse import urlparse

from _common import BUNDLE, REHOME, ROOT, SKILLS, doc_files, read_text, run_tool

LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
SKILL_NAMES = ("claude-desktop-rehome", "claude-session-transporter")


def anchors(md):
    """GitHub-style heading anchors of a markdown file."""
    out = set()
    fence = False
    for line in md.split("\n"):
        if line.strip().startswith("```"):
            fence = not fence
            continue
        m = None if fence else re.match(r"^#{1,6}\s+(.*?)\s*#*\s*$", line)
        if m:
            text = re.sub(r"`([^`]*)`", r"\1", m.group(1))
            text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
            out.add(re.sub(r"[^\w\- ]", "", text.strip().lower()).replace(" ", "-"))
    return out


def load_json(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return json.load(f)


class Links(unittest.TestCase):
    def test_relative_links_resolve(self):
        bad = []
        for p in doc_files():
            s = read_text(p) or ""
            for target in LINK.findall(s):
                if re.match(r"^[a-z][a-z0-9+.-]*:", target):
                    continue
                path, _, frag = target.partition("#")
                full = os.path.normpath(os.path.join(os.path.dirname(p), path)) if path else p
                if not os.path.exists(full):
                    bad.append(f"{os.path.relpath(p, ROOT)} -> {target} (missing file)")
                elif frag and full.endswith(".md") and frag not in anchors(read_text(full) or ""):
                    bad.append(f"{os.path.relpath(p, ROOT)} -> {target} (missing anchor)")
        self.assertEqual(bad, [])


class Manifests(unittest.TestCase):
    def check_entries(self, rel, extra_keys, extra):
        d = load_json(rel)
        self.assertIsInstance(d.get("about"), str, f"{rel}: needs an `about` text")
        self.assertIsInstance(d.get("tested"), list)
        self.assertTrue(d["tested"], f"{rel}: no entries")
        for e in d["tested"]:
            for k in ("tool", "os_family", "os", "date", "verified") + extra_keys:
                self.assertIn(k, e, f"{rel}: entry missing `{k}`: {e}")
            self.assertRegex(e["tool"], r"^\d+\.\d+\.\d+$", f"{rel}: tool is a bare version")
            self.assertRegex(e["date"], r"^\d{4}-\d\d-\d\d$")
            self.assertIn(e["os_family"], ("Linux", "macOS", "Windows"))
            self.assertIsInstance(e["verified"], list)
            self.assertTrue(e["verified"], f"{rel}: `verified` must name what ran")
            extra(e)

    def test_rehome_tested_json(self):
        self.check_entries("skills/claude-desktop-rehome/tested.json", ("desktop",), lambda e: None)

    def test_transporter_tested_json(self):
        self.check_entries("skills/claude-session-transporter/tested.json", ("role",),
                           lambda e: self.assertIn(e["role"], ("export", "import")))

    def test_plugin_manifest(self):
        p = load_json(".claude-plugin/plugin.json")
        self.assertRegex(p["name"], r"^[a-z0-9]+(-[a-z0-9]+)*$")
        self.assertFalse(re.match(r"^(claude|anthropic|anthropics|cc-plugin)-", p["name"]),
                         "reserved plugin-name prefix (the docs make it an error)")
        for k in ("version", "description", "author", "license", "homepage", "repository"):
            self.assertIn(k, p)
        self.assertEqual(p["license"], "MIT")
        u = urlparse(p["homepage"])
        self.assertTrue(u.scheme == "https" and u.netloc, "homepage must parse as a URL or the plugin fails to load")

    def test_marketplace_manifest(self):
        m = load_json(".claude-plugin/marketplace.json")
        p = load_json(".claude-plugin/plugin.json")
        self.assertRegex(m["name"], r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
        self.assertNotIn("..", m["name"])
        self.assertIn("name", m["owner"])
        entry = [e for e in m["plugins"] if e["name"] == p["name"]]
        self.assertEqual(len(entry), 1, "the marketplace lists this plugin exactly once, under the manifest's name")
        self.assertEqual(entry[0]["source"], "./")
        self.assertNotIn("version", entry[0], "keep the version in plugin.json only (it wins anyway)")
        self.assertTrue(os.path.isdir(os.path.join(ROOT, "skills")), "the plugin's skills load from skills/")


class Versions(unittest.TestCase):
    def test_one_version_everywhere(self):
        """Lockstep: both tools, the plugin manifest and the newest CHANGELOG entry carry the same version."""
        versions = {}
        for name, tool in (("ccd-rehome", REHOME), ("st-bundle", BUNDLE)):
            rc, out = run_tool(tool, "--version")
            self.assertEqual(rc, 0, out)
            versions[name] = re.search(r"(\d+\.\d+\.\d+)", out).group(1)
        versions["plugin.json"] = load_json(".claude-plugin/plugin.json")["version"]
        changelog = read_text(os.path.join(ROOT, "CHANGELOG.md")) or ""
        top = re.search(r"^## \[?(\d+\.\d+\.\d+)\]?", changelog, re.M)
        self.assertIsNotNone(top, "CHANGELOG.md needs '## <version>' headings, newest first")
        versions["CHANGELOG.md"] = top.group(1)
        self.assertEqual(len(set(versions.values())), 1, f"versions disagree: {versions}")


class Layout(unittest.TestCase):
    def test_required_files(self):
        need = ["README.md", "AGENTS.md", "CLAUDE.md", "LICENSE", "CHANGELOG.md", "CONTRIBUTING.md", "SECURITY.md",
                "install.py", ".github/workflows/ci.yml", ".github/pull_request_template.md",
                ".claude-plugin/plugin.json", ".claude-plugin/marketplace.json"]
        for s in SKILL_NAMES:
            need += [f"skills/{s}/SKILL.md", f"skills/{s}/tested.json", f"skills/{s}/scripts/selftest.py"]
        missing = [f for f in need if not os.path.exists(os.path.join(ROOT, f))]
        self.assertEqual(missing, [])

    def test_license_is_mit(self):
        self.assertIn("MIT License", read_text(os.path.join(ROOT, "LICENSE")) or "")

    def test_no_stray_root_manifest(self):
        """tested.json lives in each skill folder (it must ship with a copied or plugin-installed skill)."""
        self.assertFalse(os.path.exists(os.path.join(ROOT, "tested.json")))

if __name__ == "__main__":
    unittest.main()
