"""Every command a document tells someone to run must exist: subcommand AND every flag on that command line.

Documentation rots silently: a renamed flag keeps working in the docs forever. This test reads every command
line in README.md, AGENTS.md, CLAUDE.md, CONTRIBUTING.md, docs/*.md and each skill's SKILL.md / README.md that
invokes one of the reference tools, and asks the tool itself (its --help / its argparse error) whether the
subcommand and each `--flag` are real.
"""
import os
import re
import subprocess
import sys
import unittest

from _common import BUNDLE, REHOME, ROOT, SKILLS, TRANSPLANT, doc_files, read_text, run_tool

ST_SCRIPTS = os.path.join(SKILLS, "claude-session-transporter", "scripts")
SHELL_TOOLS = ("st-preflight.sh", "st-checkpoint.sh", "st-git-rescue.sh", "st-resync.sh", "st-verify.sh")
SEPARATORS = re.compile(r"\s(?:\||&&|;|\|\||>|2>)\s|`|\)|$")


def code_lines(text):
    """Lines inside fenced code blocks, plus inline `code` spans and table cells, from markdown."""
    out, fence = [], False
    for line in text.split("\n"):
        if line.strip().startswith("```"):
            fence = not fence
            continue
        if fence:
            out.append(line)
        else:
            out += re.findall(r"`([^`]+)`", line)
    return out


def segments(lines, tool_rx):
    """The part of each line from the tool name to the next shell separator."""
    for line in lines:
        for m in tool_rx.finditer(line):
            rest = line[m.end():]
            cut = SEPARATORS.search(rest)
            yield m.group(0), rest[:cut.start()] if cut else rest


class DocsMatchTools(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rc, out = run_tool(REHOME, "--help")
        cls.rehome_help = out
        rc, out = run_tool(REHOME, "no-such-command")
        cls.rehome_cmds = set(re.findall(r"'([a-z-]+)'", out.split("choose from", 1)[-1]))
        subs = re.search(r"\{([a-z,-]+)\}", run_tool(BUNDLE, "--help")[1])
        cls.bundle_help = {sub: run_tool(BUNDLE, sub, "--help")[1] for sub in (subs.group(1).split(",") if subs else [])}
        cls.transplant_help = run_tool(TRANSPLANT, "--help")[1]
        cls.shell_help = {}
        for t in SHELL_TOOLS:
            try:
                r = subprocess.run(["bash", os.path.join(ST_SCRIPTS, t), "--help"], capture_output=True, text=True,
                                   timeout=60)
                cls.shell_help[t] = r.stdout + r.stderr
            except (OSError, subprocess.SubprocessError):
                cls.shell_help[t] = None          # no bash here (plain Windows): CI's POSIX runners check these
        cls.docs = {os.path.relpath(p, ROOT): code_lines(read_text(p) or "") for p in doc_files()}

    def test_rehome_usage_and_parser_agree(self):
        """Every command the usage text advertises is one the parser accepts, and the reverse."""
        advertised = set(re.findall(r"^\s*ccd-rehome (?:usage: )?([a-z][a-z-]+)", self.rehome_help, re.M))
        advertised |= set(re.findall(r"^usage:\s+ccd-rehome ([a-z][a-z-]+)", self.rehome_help, re.M))
        self.assertEqual(sorted(advertised - self.rehome_cmds), [], "advertised in --help, rejected by the parser")
        self.assertEqual(sorted(self.rehome_cmds - advertised), [], "accepted by the parser, missing from --help")

    def test_found_some_commands(self):
        n = sum(1 for lines in self.docs.values() for l in lines if "ccd-rehome" in l or "st-bundle" in l)
        self.assertGreater(n, 20, "the docs should show the tools in use; did the parser break?")
        self.assertGreater(len(self.rehome_cmds), 10, "could not read ccd-rehome's command list")
        self.assertGreaterEqual(len(self.bundle_help), 5, "could not read st-bundle.py's command list")

    def test_rehome_commands_and_flags(self):
        rx = re.compile(r"(?:\bccd-rehome\"?|\$R|(?<![\w-])R(?= [a-z]))(?=\s)")   # not the -R of chmod -R
        bad = []
        for doc, lines in self.docs.items():
            for _, seg in segments(lines, rx):
                words = seg.split()
                if not words or not re.match(r"^[a-z][a-z-]+$", words[0]):
                    continue
                if words[0] not in self.rehome_cmds:
                    bad.append(f"{doc}: ccd-rehome {words[0]} (no such command)")
                for flag in re.findall(r"(?<![\w-])(--[a-z][a-z-]*)", seg):
                    if flag not in self.rehome_help:
                        bad.append(f"{doc}: ccd-rehome {words[0]} … {flag} (no such flag)")
        self.assertEqual(bad, [])

    def test_bundle_commands_and_flags(self):
        rx = re.compile(r"st-bundle\.py\"?(?=\s)")
        bad = []
        for doc, lines in self.docs.items():
            for _, seg in segments(lines, rx):
                words = seg.split()
                if not words:
                    continue
                sub = words[0]
                if sub.startswith("-"):
                    continue
                if sub not in self.bundle_help:
                    bad.append(f"{doc}: st-bundle.py {sub} (no such command)")
                    continue
                for flag in re.findall(r"(?<![\w-])(--[a-z][a-z-]*)", seg):
                    if flag not in self.bundle_help[sub]:
                        bad.append(f"{doc}: st-bundle.py {sub} … {flag} (no such flag)")
        self.assertEqual(bad, [])

    def test_transporter_script_flags(self):
        """Every --flag shown after st-transplant.py or an st-*.sh script is in that script's --help."""
        tools = [("st-transplant.py", self.transplant_help)] + [(t, h) for t, h in self.shell_help.items() if h]
        bad = []
        for doc, lines in self.docs.items():
            for name, help_text in tools:
                for _, seg in segments(lines, re.compile(re.escape(name) + r"\"?(?=\s)")):
                    for flag in re.findall(r"(?<![\w-])(--[a-z][a-z-]*)", seg):
                        if flag not in help_text:
                            bad.append(f"{doc}: {name} … {flag}")
        self.assertEqual(sorted(set(bad)), [])

    def test_parser_sees_flags(self):
        """Guard the guard: a made-up flag in a synthetic doc line must be reported."""
        seg = list(segments(["ccd-rehome move work --only 1a2b --no-such-flag"],
                            re.compile(r"\bccd-rehome(?=\s)")))[0][1]
        self.assertIn("--no-such-flag", re.findall(r"(?<![\w-])(--[a-z][a-z-]*)", seg))
        self.assertNotIn("--no-such-flag", self.rehome_help)


if __name__ == "__main__":
    unittest.main()
