"""Nothing personal may be published: no real emails, private IPs, home paths, account/session ids.

Generic patterns run everywhere (CI included). Maintainers can additionally point $PRIVACY_TERMS_FILE at a
PRIVATE tab-separated map (real<TAB>placeholder, the format tools/scrub_terms.py uses) kept outside the repo;
every real term in it must then be absent too.
"""
import os
import re
import unittest

from _common import ROOT, read_text, repo_files

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@((?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,})")
OK_EMAIL_DOMAINS = re.compile(r"(^|\.)(example\.(com|org|net)|users\.noreply\.github\.com|anthropic\.com|localhost)$")
OK_EMAIL_LOCAL = {"noreply"}
PRIVATE_IP = re.compile(r"(?<![\d.])(10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|"
                        r"172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})(?![\d.])")
HOME = re.compile(r"(?<![\w$])(/home/|/Users/|C:\\\\Users\\\\|C:\\Users\\)([A-Za-z0-9._-]+)")
# Placeholder user names used in examples. Anything else in a home path is treated as a real name.
OK_USERS = {"dana", "jamiedoe", "you", "YOU", "me", "u", "x", "runner", "USER", "alice", "bob", "name",
            "jdoe", "username", "<user>", "%USERNAME%"}
UUID = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
# Placeholder UUIDs: a repeated-digit first group (aaaaaaaa-, 0a0a0a0a-, 11111111-...), all zeros, or these.
OK_UUID_PREFIXES = {"5e55105e", "f0f0f0f0", "e1e1e1e1", "c1c1c1c1", "c2c2c2c2", "f1f1f1f1", "e0e0e0e0"}


def placeholder_uuid(u):
    first = u.split("-")[0].lower()
    return len(set(first)) <= 2 or first in OK_UUID_PREFIXES or set(u.replace("-", "")) <= {"0"}


class Privacy(unittest.TestCase):
    def files(self):
        out = []
        for f in repo_files():
            s = read_text(f)
            if s is not None:
                out.append((os.path.relpath(f, ROOT), s))
        return out

    def test_no_real_email_addresses(self):
        bad = [(p, m.group(0)) for p, s in self.files() for m in EMAIL.finditer(s)
               if not OK_EMAIL_DOMAINS.search(m.group(1).lower()) and m.group(0).split("@")[0] not in OK_EMAIL_LOCAL]
        self.assertEqual(bad, [], "real-looking email addresses (use example.com)")

    def test_no_private_ip_addresses(self):
        bad = [(p, m.group(0)) for p, s in self.files() for m in PRIVATE_IP.finditer(s)]
        self.assertEqual(bad, [], "private-range IPs (use 192.0.2.x / 198.51.100.x / 203.0.113.x)")

    def test_no_real_home_paths(self):
        bad = [(p, m.group(0)) for p, s in self.files() for m in HOME.finditer(s)
               if m.group(2) not in OK_USERS and not m.group(2).startswith(".")]
        self.assertEqual(bad, [], "home paths with a real-looking user name (use /home/you, /Users/you, ~)")

    def test_no_real_uuids(self):
        bad = [(p, m.group(0)) for p, s in self.files() for m in UUID.finditer(s) if not placeholder_uuid(m.group(0))]
        self.assertEqual(bad, [], "real-looking account/org/session ids (use synthetic ones like aaaaaaaa-1111-...)")

    def test_private_terms_absent(self):
        path = os.environ.get("PRIVACY_TERMS_FILE")
        if not path:
            self.skipTest("set PRIVACY_TERMS_FILE to a private real<TAB>placeholder map to also check literal terms")
        terms = []
        for line in open(os.path.expanduser(path), encoding="utf-8"):
            line = line.rstrip("\n")
            if line and not line.startswith("#") and "\t" in line:
                terms.append(line.split("\t", 1)[0])
        bad = [(p, len(t)) for p, s in self.files() for t in terms if t in s]
        self.assertEqual(bad, [], "private terms found (lengths shown, not the terms)")

    def test_the_detectors_detect(self):
        """The patterns themselves must catch what they claim to (a guard that never fires is no guard)."""
        self.assertTrue(EMAIL.search("mail jane" + "@" + "corp.io now"))
        self.assertFalse(OK_EMAIL_DOMAINS.search("corp.io"))
        self.assertTrue(PRIVATE_IP.search("host " + ".".join(["10", "1", "2", "3"]) + " up"))
        self.assertTrue(PRIVATE_IP.search("at " + ".".join(["192", "168", "0", "9"])))
        self.assertFalse(PRIVATE_IP.search("doc 192.0.2.5"))
        self.assertEqual(HOME.search("/home/" + "jane/x").group(2), "jane")
        self.assertFalse(placeholder_uuid("3f2c9a71-0b1d-4e4a-9c3e-" + "2a7b8c9d0e1f"))
        self.assertTrue(placeholder_uuid("aaaaaaaa-1111-4111-8111-111111111111"))


if __name__ == "__main__":
    unittest.main()
