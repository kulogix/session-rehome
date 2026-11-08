#!/usr/bin/env python3
"""Install the session-rehome skills for Claude Code (macOS, Linux, Windows; Python 3.9+, stdlib only).

    python3 install.py                 install both skills into ~/.claude/skills
                                       (linked to this checkout on macOS/Linux, copied on Windows)
    python3 install.py --status        what is installed, from where, and which versions
    python3 install.py --link | --copy choose the mode (a link keeps ONE copy: `git pull` here updates it)
    python3 install.py --bin ~/.local/bin
                                       also put `ccd-rehome`, `st-bundle` and `st-verify` launchers there
    python3 install.py --uninstall     remove what this installer installed, and nothing else
    python3 install.py --dry-run ...   print what would happen; change nothing

Other options: --target DIR (default ~/.claude/skills), --skill NAME (repeatable; default: both skills),
--force (replace a folder this installer did not create; it is MOVED to ~/.claude/skill-backups/, never deleted).

Nothing is ever deleted that this installer did not create unchanged: a copy you edited after installing is
moved to the backup folder too. Exit status: 0 done, 1 something was refused (the output says what and why).

Alternatively, install as a Claude Code plugin (no checkout needed; do not install both ways):
    /plugin marketplace add kulogix/session-rehome
    /plugin install session-rehome@kulogix
"""
import argparse
import datetime
import hashlib
import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
SKILLS = ("session-rehome", "session-transporter")
MAIN_SCRIPT = {"session-rehome": "ccd-rehome", "session-transporter": "st-bundle.py"}
# Folder names of earlier releases (0.9.x): a second copy under an old name would load too.
LEGACY = {"claude-desktop-rehome": "session-rehome", "claude-session-transporter": "session-transporter"}
MARKER = ".installed-by-session-rehome.json"
MARKERS = (MARKER, ".installed-by-claude-session-rehome.json")       # read both: 0.9.x copies carry the old one
# launcher name -> (skill, script, interpreter). st-verify needs bash, so it has no Windows launcher.
LAUNCHERS = {"ccd-rehome": ("session-rehome", "ccd-rehome", "python"),
             "st-bundle": ("session-transporter", "st-bundle.py", "python"),
             "st-verify": ("session-transporter", "st-verify.sh", "bash")}
LAUNCHER_TAG = "installed by session-rehome install.py"
LAUNCHER_TAGS = (LAUNCHER_TAG, "installed by claude-session-rehome install.py")   # 0.9.x launchers are ours too
WIN = sys.platform.startswith("win")
DRY = False


def say(m=""):
    print(m, flush=True)


def stamp():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def commit():
    try:
        r = subprocess.run(["git", "-C", ROOT, "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                           timeout=10)
        return r.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def tool_version(skill_dir, skill):
    p = os.path.join(skill_dir, "scripts", MAIN_SCRIPT[skill])
    if not os.path.isfile(p):
        return "-"
    try:
        r = subprocess.run([sys.executable, "-I", p, "--version"], capture_output=True, text=True, timeout=60)
        return (r.stdout or r.stderr).strip() or "?"
    except (OSError, subprocess.SubprocessError):
        return "?"


def digest(top):
    """Content hash of a skill folder (paths + bytes), ignoring caches and the install marker."""
    h = hashlib.sha256()
    rows = []
    for d, dirs, files in os.walk(top):
        dirs[:] = sorted(x for x in dirs if x != "__pycache__")
        for f in files:
            if f in MARKERS or f.endswith(".pyc"):
                continue
            p = os.path.join(d, f)
            with open(p, "rb") as fh:
                rows.append((os.path.relpath(p, top).replace(os.sep, "/"), hashlib.sha256(fh.read()).hexdigest()))
    for rel, hx in sorted(rows):
        h.update(f"{rel}\0{hx}\n".encode())
    return h.hexdigest()


def read_marker(dest):
    for name in MARKERS:
        try:
            with open(os.path.join(dest, name), encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            continue
    return None


def classify(dest, src):
    """missing | ours-link | ours-copy | ours-copy-edited | dangling-link | foreign-link | foreign-dir | file"""
    if os.path.islink(dest):
        if os.path.realpath(dest) == os.path.realpath(src):
            return "ours-link"
        return "foreign-link" if os.path.exists(dest) else "dangling-link"
    if not os.path.exists(dest):
        return "missing"
    if os.path.isdir(dest):
        m = read_marker(dest)
        if m is None:
            return "foreign-dir"
        return "ours-copy" if m.get("digest") == digest(dest) else "ours-copy-edited"
    return "file"


def backup(path, target):
    bdir = os.path.join(os.path.dirname(os.path.abspath(target)), "skill-backups")
    dst = os.path.join(bdir, f"{os.path.basename(path)}-{stamp()}")
    n = 1
    while os.path.lexists(dst):
        n += 1
        dst = os.path.join(bdir, f"{os.path.basename(path)}-{stamp()}-{n}")
    say(f"  moving {path} -> {dst} (a backup: nothing is deleted)")
    if not DRY:
        os.makedirs(bdir, exist_ok=True)
        shutil.move(path, dst)


def remove(path):
    if DRY:
        return
    if os.path.islink(path) or os.path.isfile(path):
        os.remove(path)
    else:
        shutil.rmtree(path)


def clear_for_install(skill, dest, state, target, force):
    """Make room at dest. Returns False (refused) when that would lose something without --force."""
    if state == "missing":
        return True
    if state in ("ours-link", "ours-copy", "dangling-link"):
        if state == "dangling-link":
            say(f"  replacing a broken link {dest} (it pointed to {os.readlink(dest)})")
        remove(dest)                       # recreatable: a link, or an unchanged copy of a checkout
        return True
    if state == "ours-copy-edited":
        say(f"  {skill}: the installed copy was edited after installing; keeping your edits in a backup")
        backup(dest, target)
        return True
    if not force:
        where = f" -> {os.path.realpath(dest)}" if state == "foreign-link" else ""
        say(f"  {skill}: REFUSED: {dest} exists and was not installed by this installer ({state}{where}).")
        say(f"  {' ' * len(skill)}  Re-run with --force to move it to ~/.claude/skill-backups/ and install.")
        return False
    if state == "foreign-link":
        say(f"  removing the link {dest} (it pointed to {os.path.realpath(dest)}, which is left untouched)")
        remove(dest)
    else:
        backup(dest, target)
    return True


def install_one(skill, target, mode, force):
    src = os.path.join(ROOT, "skills", skill)
    dest = os.path.join(target, skill)
    state = classify(dest, src)
    if state == "ours-link" and mode == "link":
        say(f"  {skill}: already linked to this checkout")
        return True
    if not clear_for_install(skill, dest, state, target, force):
        return False
    if not DRY:
        os.makedirs(target, exist_ok=True)
    if mode == "link":
        say(f"  {skill}: link {dest} -> {src}")
        if not DRY:
            try:
                os.symlink(src, dest, target_is_directory=True)
            except OSError as e:
                say(f"  {skill}: could not create a symlink ({e}). On Windows that needs Developer Mode; "
                    f"use --copy instead.")
                return False
    else:
        say(f"  {skill}: copy {src} -> {dest}")
        if not DRY:
            shutil.copytree(src, dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", *MARKERS))
            with open(os.path.join(dest, MARKER), "w", encoding="utf-8") as f:
                json.dump({"source": ROOT, "commit": commit(), "installed_utc": stamp(), "digest": digest(dest)},
                          f, indent=2)
    return True


def legacy_check(target, force):
    """An install under an earlier release's folder name would load as a second copy. Our own (a link, or a copy
    this installer made and nobody edited) is removed, since nothing is lost; anything else needs --force, and is
    then moved to the backup folder, never deleted."""
    ok = True
    for old, new in LEGACY.items():
        p = os.path.join(target, old)
        if not os.path.lexists(p):
            continue
        if os.path.islink(p):
            say(f"  removing {p}, a link from an earlier release (it pointed to {os.readlink(p)}); {new} replaces it")
            remove(p)
            continue
        m = read_marker(p) if os.path.isdir(p) else None
        if m is not None and m.get("digest") == digest(p):
            say(f"  removing {p}, an unchanged copy from an earlier release; {new} replaces it")
            remove(p)
        elif m is not None or force:
            say(f"  {p} is an earlier install of {new}{' (edited after installing)' if m else ''}; "
                f"moving it aside so only one copy loads")
            backup(p, target)
        else:
            say(f"  REFUSED: {p} looks like an earlier install of {new}, and both would load.")
            say("  Re-run with --force to move it to ~/.claude/skill-backups/.")
            ok = False
    return ok


def launcher_path(bindir, name):
    return os.path.join(bindir, name + (".cmd" if WIN else ""))


def launcher_body(script, interpreter):
    if interpreter == "bash":
        return f'#!/bin/sh\n# {LAUNCHER_TAG}\nexec bash "{script}" "$@"\n'
    if WIN:
        return ("@echo off\r\n"
                f"rem {LAUNCHER_TAG}\r\n"
                "where py >nul 2>nul || goto nopy\r\n"
                f'py -3 "{script}" %*\r\n'
                "exit /b %errorlevel%\r\n"
                ":nopy\r\n"
                f'python "{script}" %*\r\n'
                "exit /b %errorlevel%\r\n")
    return f'#!/bin/sh\n# {LAUNCHER_TAG}\nexec python3 "{script}" "$@"\n'


def ours(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
        return any(tag in text for tag in LAUNCHER_TAGS)
    except OSError:
        return False


def write_launchers(bindir, target):
    ok = True
    if not DRY:
        os.makedirs(bindir, exist_ok=True)
    for name, (skill, script_name, interpreter) in LAUNCHERS.items():
        script = os.path.join(target, skill, "scripts", script_name)
        lp = launcher_path(bindir, name)
        if WIN and interpreter == "bash":
            say(f"  launcher {name}: skipped on Windows (it needs bash: run it under WSL or Git-Bash)")
            continue
        if os.path.lexists(lp) and not ours(lp):
            say(f"  launcher {lp}: REFUSED, a file with that name exists and is not ours")
            ok = False
            continue
        say(f"  launcher {lp} -> {script}")
        if not DRY:
            with open(lp, "w", encoding="utf-8", newline="") as f:
                f.write(launcher_body(script, interpreter))
            if not WIN:
                os.chmod(lp, 0o755)
    on_path = [os.path.realpath(p) for p in os.environ.get("PATH", "").split(os.pathsep) if p]
    if os.path.realpath(bindir) not in on_path:
        say(f"  note: {bindir} is not on your PATH")
    return ok


def status(target, bindir):
    say(f"this checkout: {ROOT} (commit {commit() or 'unknown'})")
    say(f"skills folder: {target}")
    say(f"  {'skill':28} {'state':18} {'installed':24} checkout")
    for s in SKILLS:
        src = os.path.join(ROOT, "skills", s)
        dest = os.path.join(target, s)
        st = classify(dest, src)
        installed = tool_version(dest, s) if os.path.isdir(dest) else "-"
        say(f"  {s:28} {st:18} {installed:24} {tool_version(src, s)}")
        if st == "foreign-link":
            say(f"  {'':28} -> {os.path.realpath(dest)}")
        if st in ("ours-copy", "ours-copy-edited"):
            m = read_marker(dest) or {}
            say(f"  {'':28} copied from {m.get('source')} at commit {m.get('commit') or '?'}, {m.get('installed_utc')}")
    for old in LEGACY:
        if os.path.lexists(os.path.join(target, old)):
            say(f"  {old:28} an OLDER install is still present: both would load (fix: install.py --force)")
    if bindir:
        for name in LAUNCHERS:
            lp = launcher_path(bindir, name)
            say(f"  launcher {lp}: {'ours' if ours(lp) else 'NOT ours' if os.path.lexists(lp) else 'absent'}")
    return True


def uninstall(target, bindir):
    for s in SKILLS:
        dest = os.path.join(target, s)
        st = classify(dest, os.path.join(ROOT, "skills", s))
        if st in ("ours-link", "ours-copy", "dangling-link"):
            say(f"  removing {dest} ({st})")
            remove(dest)
        elif st == "ours-copy-edited":
            say(f"  {dest} was edited after installing; moving it to a backup instead of deleting it")
            backup(dest, target)
        elif st != "missing":
            say(f"  leaving {dest} alone: not installed by this installer ({st})")
    if bindir:
        for name in LAUNCHERS:
            lp = launcher_path(bindir, name)
            if ours(lp):
                say(f"  removing launcher {lp}")
                remove(lp)
    return True


def main():
    global DRY
    if sys.version_info < (3, 9):
        sys.exit("install.py: Python 3.9 or newer is required (found %d.%d)" % sys.version_info[:2])
    ap = argparse.ArgumentParser(prog="install.py", description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog="\n\n".join(__doc__.split("\n\n")[1:]))
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--link", action="store_true", help="symlink each skill to this checkout (default: macOS/Linux)")
    g.add_argument("--copy", action="store_true", help="copy each skill (default: Windows)")
    ap.add_argument("--target", default=os.path.join(os.path.expanduser("~"), ".claude", "skills"),
                    help="skills folder (default: ~/.claude/skills)")
    ap.add_argument("--skill", action="append", choices=SKILLS, help="install only this skill (repeatable)")
    ap.add_argument("--bin", metavar="DIR", help="also write ccd-rehome / st-bundle / st-verify launchers into DIR")
    ap.add_argument("--force", action="store_true", help="move a folder this installer did not create to a backup")
    ap.add_argument("--uninstall", action="store_true", help="remove what this installer installed")
    ap.add_argument("--status", action="store_true", help="show what is installed and the versions")
    ap.add_argument("--dry-run", action="store_true", help="print what would happen; change nothing")
    a = ap.parse_args()
    DRY = a.dry_run
    target = os.path.abspath(os.path.expanduser(a.target))
    bindir = os.path.abspath(os.path.expanduser(a.bin)) if a.bin else None
    if a.status:
        sys.exit(0 if status(target, bindir) else 1)
    if a.uninstall:
        uninstall(target, bindir)
        say("dry run: nothing was changed" if DRY else "uninstalled")
        sys.exit(0)
    mode = "link" if a.link else "copy" if a.copy else ("copy" if WIN else "link")
    say(f"installing into {target} ({mode}{'; DRY RUN, nothing will change' if DRY else ''})")
    ok = legacy_check(target, a.force)
    for s in a.skill or SKILLS:
        ok = install_one(s, target, mode, a.force) and ok
    if bindir:
        ok = write_launchers(bindir, target) and ok
    say("")
    if DRY:
        say("dry run: nothing was changed")
    elif ok:
        say("done. Start a NEW Claude Code session (skills are read at startup). Check the tools with:")
        if bindir and ok:
            say("  ccd-rehome doctor")
        else:
            say(f'  python3 "{os.path.join(target, "session-rehome", "scripts", "ccd-rehome")}" doctor')
    else:
        say("finished with refusals; see the REFUSED lines above.")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
