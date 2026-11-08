#!/usr/bin/env python3
"""st_walk.py — dependency-free manifest walker and manifest comparator.

ONE implementation, run on BOTH sides of a migration, so the remote manifest and the
local manifest are produced by identical semantics. On the origin it is executed over
ssh stdin (`ssh HOST "python3 - ARGS" < st_walk.py`) and therefore NEVER written to the
origin filesystem.

Stdlib only. Runs on Python 3.6+ (macOS 12+ ships 3.9).

MODES
  (default)          walk --root and emit a manifest:  relpath \\t size \\t sha256
  --stat-only        emit a fingerprint instead:        relpath \\t size \\t mtime \\t mode \\t inode
                     (no hashing; used for the origin-unchanged proof. atime is
                      deliberately absent — reading changes it. ctime is emitted only
                      with --ctime, as a SECOND advisory fingerprint.)
  --explain-excludes walk with NO exclusions and report, per pattern, how many files and
                     bytes it would remove.  This is the M1 guard: an over-broad exclude
                     must show up as a NUMBER, never as silence.
  --compare A B      compare two manifests. COVERAGE and FIDELITY are separate gates.
  --hazards          filename-hazard scan over a MANIFEST (not over a copy): case-only
                     collisions folded with Unicode normalisation, NFD names, control
                     characters. Run this on the ORIGIN manifest, before the transfer.

SYMLINKS are emitted as manifest rows `rel \\t -1 \\t symlink:<target>`. They used to be
counted in `oddities` and dropped, which meant BOTH walkers were blind in the same way:
a symlinked directory holding real content was copied by neither side, reported missing
by neither manifest, and the comparison printed "coverage complete AND every byte
identical". A blind spot shared by the oracle and the copy is not a gate.

EXCLUDE SEMANTICS — a documented subset of rsync's, so the same pattern string can be
handed to rsync verbatim and the two agree:
    /a/b/     anchored, directory:  rel == 'a/b' or rel startswith 'a/b/'
    /a/b      anchored, any type
    name/     any path COMPONENT that is a directory equal to (or globbing) 'name'
    *.pyc     glob against any single path component
`*` and `?` do NOT cross '/', exactly as in rsync. (They did when this used fnmatch,
where `*` matches '/' — so `/logs/*.txt` was reported as removing 2 files while rsync
removed 1. The M1 guard rests on that number being true.)
Patterns with '**' are rejected: rsync's meaning for them is not reproduced here, and a
pattern whose two implementations disagree is exactly the M1 failure mode.
"""
import argparse
import errno
import hashlib
import os
import re
import stat as statmod
import sys
import unicodedata

CHUNK = 1 << 20
SYMLINK_SIZE = -1


# --------------------------------------------------------------------------- patterns
def glob_re(p):
    """Translate an rsync-ish glob to a regex where '*' and '?' do not cross '/'."""
    out = ["(?s)"]
    i = 0
    n = len(p)
    while i < n:
        c = p[i]
        if c == "*":
            out.append("[^/]*")
        elif c == "?":
            out.append("[^/]")
        elif c == "[":
            j = i + 1
            if j < n and p[j] in "!^":
                j += 1
            if j < n and p[j] == "]":
                j += 1
            while j < n and p[j] != "]":
                j += 1
            if j >= n:
                out.append(re.escape(c))
            else:
                body = p[i + 1:j]
                if body.startswith(("!", "^")):
                    body = "^" + body[1:]
                out.append("[" + body.replace("\\", "\\\\") + "]")
                i = j + 1
                continue
        else:
            out.append(re.escape(c))
        i += 1
    return re.compile("".join(out) + r"\Z")


_RE_CACHE = {}


def gmatch(pat, s):
    r = _RE_CACHE.get(pat)
    if r is None:
        r = glob_re(pat)
        _RE_CACHE[pat] = r
    return r.match(s) is not None


def load_patterns(items, files):
    pats = []
    for it in items or []:
        it = it.strip()
        if it and not it.startswith("#"):
            pats.append(it)
    for fn in files or []:
        with open(fn, "r") as fh:
            for line in fh:
                line = line.split("#", 1)[0].strip()
                if line:
                    pats.append(line)
    for p in pats:
        if "**" in p:
            sys.stderr.write("st_walk: refusing '**' pattern (ambiguous vs rsync): %s\n" % p)
            sys.exit(2)
    return pats


def pat_match(pat, rel, is_dir):
    """True if `pat` excludes `rel`. `rel` is a POSIX relative path, no leading slash."""
    dironly = pat.endswith("/")
    p = pat[:-1] if dironly else pat
    anchored = p.startswith("/")
    if anchored:
        p = p.lstrip("/")
        if dironly:
            return rel == p or rel.startswith(p + "/") or gmatch(p + "/*", rel)
        return rel == p or rel.startswith(p + "/") or gmatch(p, rel)
    if "/" in p:
        padded = "/" + rel + "/"
        if ("/" + p + "/") in padded:
            return True
        return gmatch(p, rel) or gmatch("*/" + p, rel) or gmatch(p + "/*", rel) \
            or gmatch("*/" + p + "/*", rel)
    parts = rel.split("/")
    if dironly and not is_dir:
        parts = parts[:-1]          # a dir-only pattern can only match a directory component
    return any(gmatch(p, c) for c in parts)


def excluded(pats, rel, is_dir):
    for p in pats:
        if pat_match(p, rel, is_dir):
            return p
    return None


# --------------------------------------------------------------------------- walking
class Entry(object):
    __slots__ = ("rel", "size", "mtime", "mode", "ino", "link")

    def __init__(self, rel, st, link=None):
        self.rel = rel
        self.size = SYMLINK_SIZE if link is not None else st.st_size
        self.mtime = int(st.st_mtime)
        self.mode = statmod.S_IMODE(st.st_mode)
        self.ino = st.st_ino
        self.link = link


def _symlink_entry(root, abs_path, rel):
    try:
        st = os.lstat(abs_path)
        return Entry(rel, st, link=os.readlink(abs_path))
    except OSError:
        return None


def walk(root, rels, pats, oddities, keep_symlinks=True):
    """Yield Entry for every REGULAR file, and (by default) for every SYMLINK.
    Fifos/sockets/devices are counted in `oddities`, never followed, never hashed."""
    roots = []
    if rels:
        for r in rels:
            roots.append((os.path.join(root, r), r.strip("/")))
    else:
        roots.append((root, ""))

    for abs_start, rel_start in roots:
        if os.path.islink(abs_start):
            oddities.setdefault("symlink", []).append(rel_start)
            if keep_symlinks and excluded(pats, rel_start, False) is None:
                e = _symlink_entry(root, abs_start, rel_start)
                if e is not None:
                    yield e
            continue
        if os.path.isfile(abs_start):
            try:
                st = os.lstat(abs_start)
            except OSError:
                oddities.setdefault("unreadable", []).append(rel_start)
                continue
            if excluded(pats, rel_start, False) is None:
                yield Entry(rel_start, st)
            continue
        if not os.path.isdir(abs_start):
            oddities.setdefault("missing", []).append(rel_start)
            continue
        for base, dirs, files in os.walk(abs_start, topdown=True, followlinks=False):
            brel = os.path.relpath(base, root).replace(os.sep, "/")
            if brel == ".":
                brel = ""
            keep = []
            for d in dirs:
                drel = (brel + "/" + d) if brel else d
                if os.path.islink(os.path.join(base, d)):
                    oddities.setdefault("symlink", []).append(drel)
                    if keep_symlinks and excluded(pats, drel, True) is None:
                        e = _symlink_entry(root, os.path.join(base, d), drel)
                        if e is not None:
                            yield e
                    continue
                if excluded(pats, drel, True) is not None:
                    continue
                keep.append(d)
            dirs[:] = sorted(keep)
            for f in sorted(files):
                frel = (brel + "/" + f) if brel else f
                full = os.path.join(base, f)
                try:
                    st = os.lstat(full)
                except OSError:
                    oddities.setdefault("unreadable", []).append(frel)
                    continue
                if statmod.S_ISLNK(st.st_mode):
                    oddities.setdefault("symlink", []).append(frel)
                    if keep_symlinks and excluded(pats, frel, False) is None:
                        e = _symlink_entry(root, full, frel)
                        if e is not None:
                            yield e
                    continue
                if not statmod.S_ISREG(st.st_mode):
                    oddities.setdefault("special", []).append(frel)
                    continue
                if excluded(pats, frel, False) is not None:
                    continue
                yield Entry(frel, st)


def sha256_file(path, limit=None):
    h = hashlib.sha256()
    n = 0
    with open(path, "rb") as fh:
        while True:
            want = CHUNK if limit is None else min(CHUNK, limit - n)
            if want <= 0:
                break
            b = fh.read(want)
            if not b:
                break
            h.update(b)
            n += len(b)
    if limit is not None and n < limit:
        raise IOError("file shorter than requested prefix: %d < %d" % (n, limit))
    return h.hexdigest()


# --------------------------------------------------------------------------- compare
def read_manifest(path):
    out = {}
    with open(path, "r") as fh:
        for line in fh:
            if not line.strip() or line.startswith("#"):
                continue
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 3:
                continue
            out[parts[0]] = (parts[1], parts[2])
    return out


def compare(a_path, b_path, label_a, label_b, examples, strict_extra):
    a = read_manifest(a_path)
    b = read_manifest(b_path)
    missing = sorted(set(a) - set(b))
    extra = sorted(set(b) - set(a))
    bad = []
    for k in sorted(set(a) & set(b)):
        if a[k] != b[k]:
            bad.append((k, a[k], b[k]))

    print("MANIFEST COMPARISON")
    print("  %-8s %s  (%d files)" % (label_a, a_path, len(a)))
    print("  %-8s %s  (%d files)" % (label_b, b_path, len(b)))
    print("")
    print("  GATE 1  COVERAGE  : %d present in %s but absent in %s" % (len(missing), label_a, label_b))
    for k in missing[:examples]:
        print("      MISSING  %s" % k)
    if len(missing) > examples:
        print("      ... and %d more" % (len(missing) - examples))
    print("  GATE 2  FIDELITY  : %d files differ in size or sha256" % len(bad))
    for k, va, vb in bad[:examples]:
        print("      DIFFER   %s   %s/%s -> %s/%s" % (k, va[0], va[1][:12], vb[0], vb[1][:12]))
    if len(bad) > examples:
        print("      ... and %d more" % (len(bad) - examples))
    print("  GATE 3  UNEXPECTED: %d present in %s only%s"
          % (len(extra), label_b, "" if strict_extra else "   (informational: pass --strict-extra to gate on it)"))
    for k in extra[:examples]:
        print("      EXTRA    %s" % k)
    if len(extra) > examples:
        print("      ... and %d more" % (len(extra) - examples))
    print("")
    rc = 0
    if missing:
        print("  RESULT: COVERAGE FAILED")
        rc = 1
    if bad:
        print("  RESULT: FIDELITY FAILED")
        rc = 1
    if extra and strict_extra:
        print("  RESULT: UNEXPECTED FILES (strict) — the copy holds paths the origin manifest")
        print("          does not. The two exclude engines disagree, or something was swept in.")
        rc = 1
    if rc == 0:
        print("  RESULT: PASS — coverage complete AND every byte identical")
    return rc


# --------------------------------------------------------------------------- hazards
def fold(name):
    """The key two names must share to collide on a case-insensitive, normalising fs.
    APFS folds case AND Unicode normalisation; folding on `.lower()` alone reports 0
    collisions for the NFC/NFD pair that actually merges."""
    return unicodedata.normalize("NFC", name).casefold()


def hazard_scan(paths, label):
    """`paths` is an iterable of relative POSIX paths — from a MANIFEST, so the scan sees
    the ORIGIN's names rather than whatever survived landing on the destination fs."""
    by_dir = {}
    nfd = []
    nonascii = []
    ctrl = []
    for p in paths:
        d, _, n = p.rpartition("/")
        by_dir.setdefault(d, {}).setdefault(fold(n), []).append(n)
        if unicodedata.normalize("NFC", n) != n:
            nfd.append(p)
        try:
            n.encode("ascii")
        except UnicodeEncodeError:
            nonascii.append(p)
        if any(ord(c) < 32 for c in n) or n != n.strip() or n.endswith("."):
            ctrl.append(p)
    coll = []
    for d, m in by_dir.items():
        for k, names in m.items():
            if len(set(names)) > 1:
                coll.append((d, sorted(set(names))))
    print("# filename hazard scan over %s" % label)
    print("case_or_normalisation_collisions\t%d" % len(coll))
    print("nfd_names\t%d" % len(nfd))
    print("non_ascii_names\t%d" % len(nonascii))
    print("control_or_trailing\t%d" % len(ctrl))
    for d, names in coll[:80]:
        print("  COLLIDE\t%s\t%s" % (d or ".", names))
    for p in nfd[:40]:
        print("  NFD\t%s" % p)
    for p in ctrl[:40]:
        print("  CTRL\t%s" % p)
    return 1 if coll else 0


# --------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description="manifest walker / comparator (stdlib only)")
    ap.add_argument("--root")
    ap.add_argument("--rel", action="append", default=[],
                    help="restrict the walk to this path under --root (repeatable)")
    ap.add_argument("--exclude", action="append", default=[])
    ap.add_argument("--exclude-from", action="append", default=[])
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--stat-only", action="store_true", help="fingerprint mode, no hashing")
    ap.add_argument("--ctime", action="store_true", help="advisory second fingerprint column")
    ap.add_argument("--no-hash", action="store_true", help="manifest with '-' in the hash column")
    ap.add_argument("--no-symlinks", action="store_true",
                    help="omit symlink rows (they are included by default so that a symlinked "
                         "subtree cannot go missing from BOTH manifests at once)")
    ap.add_argument("--explain-excludes", action="store_true")
    ap.add_argument("--summary", action="store_true", help="print only the totals, to stdout")
    ap.add_argument("--prefix-sha", metavar="N", type=int,
                    help="with --root pointing at a FILE: sha256 of its first N bytes")
    ap.add_argument("--compare", nargs=2, metavar=("A", "B"))
    ap.add_argument("--label", nargs=2, default=["A", "B"])
    ap.add_argument("--examples", type=int, default=20)
    ap.add_argument("--strict-extra", action="store_true")
    ap.add_argument("--hazards", metavar="MANIFEST",
                    help="filename-hazard scan over a manifest file (use '-' for --root walk)")
    ap.add_argument("--exists", action="store_true",
                    help="with --rel: print 'rel<TAB>dir|file|missing' for each, one round trip. "
                         "A whitelist entry that is simply absent (a short session has no "
                         "memory/, no tasks/, no sidecars) must be SKIPPED, not transferred "
                         "and then failed.")
    a = ap.parse_args()

    if a.compare:
        return compare(a.compare[0], a.compare[1], a.label[0], a.label[1],
                       a.examples, a.strict_extra)

    if a.hazards and a.hazards != "-":
        return hazard_scan(sorted(read_manifest(a.hazards)), a.hazards)

    if not a.root:
        ap.error("--root is required unless --compare/--hazards is used")

    if a.exists:
        for r in a.rel:
            p = os.path.join(a.root, r)
            kind = "dir" if os.path.isdir(p) else ("file" if os.path.isfile(p) else "missing")
            print("%s\t%s" % (r, kind))
        return 0

    if a.prefix_sha is not None:
        try:
            size = os.path.getsize(a.root)
            print("%s\t%d\t%d" % (sha256_file(a.root, a.prefix_sha), a.prefix_sha, size))
            return 0
        except Exception as e:                                  # noqa: BLE001
            sys.stderr.write("prefix-sha failed: %s\n" % e)
            return 3

    root = os.path.realpath(a.root)
    pats = load_patterns(a.exclude, a.exclude_from)
    oddities = {}
    keep_links = not a.no_symlinks

    if a.explain_excludes:
        # Walk with NO exclusions, then attribute every file to the FIRST pattern that
        # would drop it. The point is the per-pattern count.
        entries = list(walk(root, a.rel, [], oddities, keep_links))
        counts = {}
        for p in pats:
            counts[p] = [0, 0]
        kept_n = kept_b = 0
        for e in entries:
            hit = excluded(pats, e.rel, False)
            sz = max(0, e.size)
            if hit is None:
                kept_n += 1
                kept_b += sz
            else:
                counts[hit][0] += 1
                counts[hit][1] += sz
        print("EXCLUDE ACCOUNTING for %s" % root)
        print("  %-52s %8s %16s" % ("pattern", "files", "bytes"))
        for p in pats:
            anchored = "  " if p.startswith("/") else "!!"
            print("  %s%-50s %8d %16d" % (anchored, p, counts[p][0], counts[p][1]))
        print("  %-52s %8d %16d" % ("(KEPT)", kept_n, kept_b))
        print("")
        print("  '!!' marks an UNANCHORED pattern: it matches by NAME anywhere in the tree.")
        print("  Justify every non-zero row against a listing before trusting this run.")
        return 0

    entries = list(walk(root, a.rel, pats, oddities, keep_links))
    total_bytes = sum(max(0, e.size) for e in entries)

    if a.hazards == "-":
        return hazard_scan([e.rel for e in entries], root)

    if a.summary:
        print("files\t%d" % len(entries))
        print("bytes\t%d" % total_bytes)
        for k in sorted(oddities):
            print("%s\t%d" % (k, len(oddities[k])))
        return 0

    sys.stderr.write("st_walk: %d files, %d bytes under %s\n" % (len(entries), total_bytes, root))
    for k in sorted(oddities):
        sys.stderr.write("st_walk: %d %s entries%s\n"
                         % (len(oddities[k]), k,
                            " (emitted as manifest rows)" if k == "symlink" and keep_links
                            else " SKIPPED"))

    if a.stat_only:
        print("# rel\tsize\tmtime\tmode\tinode" + ("\tctime" if a.ctime else ""))
        for e in sorted(entries, key=lambda x: x.rel):
            row = "%s\t%d\t%d\t%o\t%d" % (e.rel, e.size, e.mtime, e.mode, e.ino)
            if a.ctime:
                try:
                    row += "\t%d" % int(os.lstat(os.path.join(root, e.rel)).st_ctime)
                except OSError:
                    row += "\t-"
            print(row)
        return 0

    print("# rel\tsize\tsha256")
    if a.no_hash:
        for e in sorted(entries, key=lambda x: x.rel):
            print("%s\t%d\t%s" % (e.rel, e.size,
                                  ("symlink:" + e.link) if e.link is not None else "-"))
        return 0

    def job(e):
        if e.link is not None:
            return (e.rel, e.size, "symlink:" + e.link)
        try:
            return (e.rel, e.size, sha256_file(os.path.join(root, e.rel)))
        except (IOError, OSError) as exc:
            if getattr(exc, "errno", None) in (errno.EACCES, errno.ENOENT):
                return (e.rel, e.size, "UNREADABLE")
            raise

    rc = 0
    try:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=max(1, a.jobs)) as ex:
            rows = list(ex.map(job, entries))
    except ImportError:
        rows = [job(e) for e in entries]
    for rel, size, digest in sorted(rows):
        if digest == "UNREADABLE":
            sys.stderr.write("st_walk: UNREADABLE %s\n" % rel)
            rc = 4
        print("%s\t%d\t%s" % (rel, size, digest))
    return rc


if __name__ == "__main__":
    sys.exit(main())
