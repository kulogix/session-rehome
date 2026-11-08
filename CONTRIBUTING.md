# Contributing

Claude Desktop changes often. This tool stays correct only if what people learn on their machines comes back here.
Please send it back. One shared, tested copy beats many private patches.

## The quickest contribution: "it works on my setup"

1. Run what you normally run (always `--dry-run` first), then:

```bash
ccd-rehome report doctor selftest dry-run rehome verify
```

   List only what you actually ran.

2. Paste the JSON into a **"Works on my setup"** issue, or add it to the `tested` list in `tested.json` in a pull
   request. The report contains versions only: no emails, ids, paths or host names.

## Something is different or broken

- **Report it:** if `doctor` prints `DRIFT`, a move refuses unexpectedly, or a result is wrong, open a **"Drift or
  bug"** issue with the `report` and `doctor` output. Replace emails and account ids with placeholders if you quote
  other output.
- **Fix it:** a pull request is very welcome, and agents are welcome to prepare one for their user. The rules are
  in SKILL.md, "Maintaining this skill". In short:
  1. **Evidence first.** What exactly changed (field, file, log line), on which Desktop version and OS.
  2. **A failing test first.** Add a synthetic fixture to `scripts/selftest.py`; never real user data.
  3. **The fix** in `scripts/ccd-rehome`: one file, Python 3.9+ stdlib only. Classify new record fields
     (`KNOWN_KEYS` / `ACCOUNT_BOUND` / `TRANSIENT`) and new per-account entries (`KNOWN_ENTRIES` plus `move()`).
  4. **Prove the test bites.** It passes with the fix and fails without it.
  5. **Docs in the same pull request:** `references/mechanics.md` (evidence, plus the contract row), `SKILL.md` /
     `README.md` if behaviour changed, `CHANGELOG.md`, and `VERSION` bumped.
  6. **Unsure of the right behaviour?** Make the tool refuse that case with a clear message. That is a fine pull
     request on its own.

## How to open a pull request

```bash
gh repo fork kulogix/claude-desktop-rehome --clone
```

```bash
cd claude-desktop-rehome && git checkout -b fix-desktop-2.40-new-field
```

Make the change, then:

```bash
python3 -I scripts/selftest.py
```

```bash
git commit -am "Handle <what> (Desktop <version>, <OS>)" && gh pr create --fill
```

A GitHub fork is just the vehicle for a pull request. Please don't publish long-lived variants: an improvement
that lands here reaches everyone, and a separate copy drifts and breaks on its own.

If you use the skill from `~/.claude/skills/claude-desktop-rehome` as a clone of this repo, you can work right
there:

```bash
gh repo fork --remote
```

That adds your fork as a remote, so you can push a branch to it and open the pull request.

## CI

Every push and pull request runs the self-test on Linux, macOS and Windows, with Python 3.9 and 3.13.
- **Linux** must pass.
- **macOS and Windows** are experimental: they are reported but don't block, until someone confirms them on real
  hardware with a `tested.json` entry.

## Ground rules

- **Never weaken a safety check** to make a case work. Instead, add the case to the contract.
- **No telemetry, no network calls, no new dependencies.**
- **Never read or copy credential values** (cookies, tokens). Names and expiry dates are as far as it goes.
