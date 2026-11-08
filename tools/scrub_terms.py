#!/usr/bin/env python3
"""Replace private identifiers with public placeholders, from a map you keep OUTSIDE the repository.

    python3 tools/scrub_terms.py --terms ~/private/scrub-terms.tsv --check  [PATH ...]
    python3 tools/scrub_terms.py --terms ~/private/scrub-terms.tsv --apply  [PATH ...]

The terms file is tab-separated, one `real<TAB>placeholder` per line, `#` comments allowed. Replacements are
applied IN FILE ORDER, so put specific terms before general ones (`acme_sim` before `acme`). With no PATH, the
whole repository is processed. Only text files are touched; .git is skipped.

--check prints every hit and exits 1 if any real term is present (use it before every push). --apply rewrites
the files and prints per-file counts. Never commit the terms file: it is the list of things to hide.
"""
import argparse, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache"}


def load_terms(path):
    terms = []
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            line = line.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            if "\t" not in line:
                sys.exit(f"{path}:{n}: expected 'real<TAB>placeholder'")
            real, fake = line.split("\t", 1)
            if not real:
                sys.exit(f"{path}:{n}: empty term")
            terms.append((real, fake))
    return terms


def text_files(paths):
    for p in paths:
        if os.path.isfile(p):
            yield p
            continue
        for base, dirs, files in os.walk(p):
            dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
            for f in sorted(files):
                full = os.path.join(base, f)
                try:
                    with open(full, "rb") as fh:
                        if b"\0" in fh.read(4096):
                            continue          # binary
                except OSError:
                    continue
                yield full


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--terms", required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true")
    g.add_argument("--apply", action="store_true")
    ap.add_argument("paths", nargs="*")
    a = ap.parse_args()
    terms = load_terms(os.path.expanduser(a.terms))
    hits_total = 0
    for f in text_files(a.paths or [ROOT]):
        if os.path.abspath(f) == os.path.abspath(os.path.expanduser(a.terms)):
            continue
        try:
            s = open(f, encoding="utf-8").read()
        except (UnicodeDecodeError, OSError):
            continue
        counts, out = {}, s
        for real, fake in terms:
            c = out.count(real)
            if c:
                counts[real] = c
                out = out.replace(real, fake)
        if not counts:
            continue
        n = sum(counts.values())
        hits_total += n
        rel = os.path.relpath(f, ROOT)
        if a.check:
            for line_no, line in enumerate(s.splitlines(), 1):
                for real, _ in terms:
                    if real in line:
                        print(f"{rel}:{line_no}: contains a private term ({len(real)} chars)")
                        break
        else:
            with open(f, "w", encoding="utf-8") as fh:
                fh.write(out)
            print(f"{rel}: {n} replacement(s) ({len(counts)} distinct term(s))")
    if a.check:
        print(f"{hits_total} private term occurrence(s)" + (" -- NOT clean" if hits_total else " -- clean"))
        sys.exit(1 if hits_total else 0)
    print(f"done: {hits_total} replacement(s)")


if __name__ == "__main__":
    main()
