"""install.py: installs, is idempotent, never destroys a folder it did not create, uninstalls only its own."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from _common import ROOT

INSTALL = os.path.join(ROOT, "install.py")


def run(*args):
    r = subprocess.run([sys.executable, "-I", INSTALL, *args], capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    return r.returncode, r.stdout + r.stderr


class Installer(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="csr-install-"))
        self.target = os.path.join(self.tmp, ".claude", "skills")
        self.bin = os.path.join(self.tmp, "bin")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_copy_install_is_complete_and_marked(self):
        rc, out = run("--copy", "--target", self.target)
        self.assertEqual(rc, 0, out)
        for s in ("session-rehome", "session-transporter"):
            d = os.path.join(self.target, s)
            self.assertTrue(os.path.isfile(os.path.join(d, "SKILL.md")))
            self.assertTrue(os.path.isfile(os.path.join(d, ".installed-by-session-rehome.json")))
            self.assertFalse(os.path.islink(d))
        rc, out = run("--copy", "--target", self.target)
        self.assertEqual(rc, 0, "re-running is safe (refresh of our own copy)\n" + out)

    @unittest.skipIf(sys.platform.startswith("win"), "symlinks need special rights on Windows")
    def test_link_install_points_at_the_checkout(self):
        rc, out = run("--link", "--target", self.target)
        self.assertEqual(rc, 0, out)
        d = os.path.join(self.target, "session-rehome")
        self.assertTrue(os.path.islink(d))
        self.assertEqual(os.path.realpath(d), os.path.realpath(os.path.join(ROOT, "skills", "session-rehome")))
        rc, out = run("--link", "--target", self.target)
        self.assertIn("already linked", out)

    def test_foreign_folder_is_refused_then_backed_up_never_deleted(self):
        foreign = os.path.join(self.target, "session-rehome")
        os.makedirs(foreign)
        with open(os.path.join(foreign, "my-notes.txt"), "w") as f:
            f.write("precious")
        rc, out = run("--copy", "--target", self.target)
        self.assertNotEqual(rc, 0)
        self.assertIn("REFUSED", out)
        with open(os.path.join(foreign, "my-notes.txt")) as f:
            self.assertEqual(f.read(), "precious")
        rc, out = run("--copy", "--force", "--target", self.target)
        self.assertEqual(rc, 0, out)
        backups = os.listdir(os.path.join(self.tmp, ".claude", "skill-backups"))
        kept = [b for b in backups if b.startswith("session-rehome-")]
        self.assertEqual(len(kept), 1)
        with open(os.path.join(self.tmp, ".claude", "skill-backups", kept[0], "my-notes.txt")) as f:
            self.assertEqual(f.read(), "precious")

    def test_foreign_legacy_folder_is_refused_then_backed_up(self):
        """A folder under a 0.9.x skill name that this installer did not make: refused, then moved, never deleted."""
        old = os.path.join(self.target, "claude-session-transporter")
        os.makedirs(old)
        with open(os.path.join(old, "notes.txt"), "w") as f:
            f.write("mine")
        rc, out = run("--copy", "--target", self.target)
        self.assertNotEqual(rc, 0)
        self.assertIn("earlier install", out)
        rc, out = run("--copy", "--force", "--target", self.target)
        self.assertEqual(rc, 0, out)
        self.assertFalse(os.path.exists(old))
        kept = [b for b in os.listdir(os.path.join(self.tmp, ".claude", "skill-backups"))
                if b.startswith("claude-session-transporter-")]
        self.assertEqual(len(kept), 1)

    @unittest.skipIf(sys.platform.startswith("win"), "symlinks need special rights on Windows")
    def test_our_legacy_link_is_replaced_without_force(self):
        """A 0.9.x link install (now dangling, the checkout moved) is ours: replaced, no --force needed."""
        os.makedirs(self.target)
        os.symlink(os.path.join(self.tmp, "old-checkout", "skills", "claude-desktop-rehome"),
                   os.path.join(self.target, "claude-desktop-rehome"))
        rc, out = run("--link", "--target", self.target)
        self.assertEqual(rc, 0, out)
        self.assertFalse(os.path.lexists(os.path.join(self.target, "claude-desktop-rehome")))
        self.assertTrue(os.path.isfile(os.path.join(self.target, "session-rehome", "SKILL.md")))

    @unittest.skipIf(sys.platform.startswith("win"), "POSIX launcher check")
    def test_launchers_from_an_earlier_release_are_ours(self):
        os.makedirs(self.bin)
        with open(os.path.join(self.bin, "ccd-rehome"), "w") as f:
            f.write("#!/bin/sh\n# installed by claude-session-rehome install.py\nexec python3 /old/path \"$@\"\n")
        rc, out = run("--copy", "--target", self.target, "--bin", self.bin)
        self.assertEqual(rc, 0, out)
        with open(os.path.join(self.bin, "ccd-rehome")) as f:
            self.assertIn("installed by session-rehome install.py", f.read())

    def test_dry_run_changes_nothing(self):
        rc, out = run("--copy", "--target", self.target, "--bin", self.bin, "--dry-run")
        self.assertEqual(rc, 0, out)
        self.assertFalse(os.path.exists(self.target))
        self.assertFalse(os.path.exists(self.bin))

    @unittest.skipIf(sys.platform.startswith("win"), "POSIX launcher check")
    def test_launchers_run_the_installed_tools(self):
        rc, out = run("--copy", "--target", self.target, "--bin", self.bin)
        self.assertEqual(rc, 0, out)
        for name in ("ccd-rehome", "st-bundle"):
            r = subprocess.run([os.path.join(self.bin, name), "--version"], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertRegex(r.stdout + r.stderr, r"\d+\.\d+\.\d+")
        r = subprocess.run([os.path.join(self.bin, "st-verify"), "--help"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("--origin-proof", r.stdout + r.stderr)

    def test_foreign_launcher_is_never_overwritten(self):
        os.makedirs(self.bin)
        with open(os.path.join(self.bin, "st-bundle" + (".cmd" if sys.platform.startswith("win") else "")), "w") as f:
            f.write("my own script\n")
        rc, out = run("--copy", "--target", self.target, "--bin", self.bin)
        self.assertNotEqual(rc, 0)
        self.assertIn("REFUSED", out)
        with open(os.path.join(self.bin, "st-bundle" + (".cmd" if sys.platform.startswith("win") else ""))) as f:
            self.assertEqual(f.read(), "my own script\n")

    def test_edited_copy_is_backed_up_not_deleted(self):
        rc, out = run("--copy", "--target", self.target)
        self.assertEqual(rc, 0, out)
        note = os.path.join(self.target, "session-rehome", "my-fix.txt")
        with open(note, "w") as f:
            f.write("an edit made after installing")
        rc, out = run("--status", "--target", self.target)
        self.assertIn("ours-copy-edited", out)
        rc, out = run("--uninstall", "--target", self.target)
        self.assertEqual(rc, 0, out)
        self.assertFalse(os.path.exists(os.path.join(self.target, "session-rehome")))
        kept = [b for b in os.listdir(os.path.join(self.tmp, ".claude", "skill-backups"))
                if b.startswith("session-rehome-")]
        self.assertEqual(len(kept), 1, "the edited copy must survive in skill-backups")
        self.assertTrue(os.path.isfile(os.path.join(self.tmp, ".claude", "skill-backups", kept[0], "my-fix.txt")))

    @unittest.skipIf(sys.platform.startswith("win"), "symlinks need special rights on Windows")
    def test_broken_link_is_replaced(self):
        os.makedirs(self.target)
        os.symlink(os.path.join(self.tmp, "gone", "session-rehome"),
                   os.path.join(self.target, "session-rehome"))
        rc, out = run("--link", "--target", self.target)
        self.assertEqual(rc, 0, out)
        self.assertIn("broken link", out)
        self.assertTrue(os.path.isfile(os.path.join(self.target, "session-rehome", "SKILL.md")))

    def test_uninstall_removes_only_ours(self):
        rc, out = run("--copy", "--target", self.target, "--bin", self.bin)
        other = os.path.join(self.target, "some-other-skill")
        os.makedirs(other)
        rc, out = run("--uninstall", "--target", self.target, "--bin", self.bin)
        self.assertEqual(rc, 0, out)
        self.assertFalse(os.path.exists(os.path.join(self.target, "session-rehome")))
        self.assertTrue(os.path.isdir(other))
        self.assertEqual([f for f in os.listdir(self.bin)], [])

    def test_status_reports_versions(self):
        run("--copy", "--target", self.target)
        rc, out = run("--status", "--target", self.target)
        self.assertEqual(rc, 0, out)
        self.assertIn("ours-copy", out)
        self.assertRegex(out, r"ccd-rehome \d+\.\d+\.\d+")


if __name__ == "__main__":
    unittest.main()
