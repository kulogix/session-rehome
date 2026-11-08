"""Shared helpers for the repository tests (stdlib only)."""
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILLS = os.path.join(ROOT, "skills")
REHOME = os.path.join(SKILLS, "claude-desktop-rehome", "scripts", "ccd-rehome")
BUNDLE = os.path.join(SKILLS, "claude-session-transporter", "scripts", "st-bundle.py")
TRANSPLANT = os.path.join(SKILLS, "claude-session-transporter", "scripts", "st-transplant.py")
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", "build", "dist"}
# Records of past runs: their commands are quoted as executed then, not instructions for today's tools.
HISTORICAL = {"evidence-base.md", "lessons.md"}


def repo_files(exts=None):
    """Tracked files when git is available (what would be published), else every file in the tree."""
    try:
        out = subprocess.run(["git", "-C", ROOT, "ls-files", "-co", "--exclude-standard"], capture_output=True,
                             text=True, check=True).stdout.split("\n")
        files = [os.path.join(ROOT, f) for f in out if f]
    except (OSError, subprocess.CalledProcessError):
        files = []
        for base, dirs, names in os.walk(ROOT):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            files += [os.path.join(base, n) for n in names]
    files = [f for f in files if os.path.isfile(f)]
    return [f for f in files if exts is None or f.endswith(tuple(exts))]


def read_text(path):
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError:
        return None
    if b"\0" in raw[:4096]:
        return None
    try:
        return raw.decode("utf-8").replace("\r\n", "\n")      # a CRLF checkout must not change what tests see
    except UnicodeDecodeError:
        return None


def run_tool(script, *args, env=None, timeout=120):
    e = dict(os.environ, PYTHONIOENCODING="utf-8", **(env or {}))
    r = subprocess.run([sys.executable, "-I", script, *args], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=e, timeout=timeout)
    return r.returncode, r.stdout + r.stderr


def doc_files():
    """Every human/agent-facing document whose commands must match the tools."""
    out = [os.path.join(ROOT, n) for n in ("README.md", "AGENTS.md", "CLAUDE.md", "CONTRIBUTING.md")]
    out += [os.path.join(ROOT, "docs", n) for n in sorted(os.listdir(os.path.join(ROOT, "docs")))
            if n.endswith(".md")] if os.path.isdir(os.path.join(ROOT, "docs")) else []
    for s in sorted(os.listdir(SKILLS)):
        for n in ("SKILL.md", "README.md"):
            out.append(os.path.join(SKILLS, s, n))
        out.append(os.path.join(SKILLS, s, "scripts", "README.md"))
        refs = os.path.join(SKILLS, s, "references")
        if os.path.isdir(refs):
            out += [os.path.join(refs, n) for n in sorted(os.listdir(refs)) if n.endswith(".md") and n not in HISTORICAL]
    return [p for p in out if os.path.isfile(p)]


def frontmatter(path):
    s = read_text(path) or ""
    m = re.match(r"^---\n(.*?)\n---\n", s, re.S)
    if not m:
        return None, s
    fm, key = {}, None
    for line in m.group(1).split("\n"):
        k = re.match(r"^([a-zA-Z_-]+):\s?(.*)$", line)
        if k:
            key = k.group(1)
            v = k.group(2).strip()
            fm[key] = "" if v in (">-", ">", "|", "|-") else v
        elif key and line.startswith((" ", "\t")):
            fm[key] = (fm[key] + " " + line.strip()).strip()
    return fm, s[m.end():]
