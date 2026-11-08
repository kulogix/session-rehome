# Contributing

Claude Desktop and Claude Code change often. These tools stay correct only when what people learn on their
machines comes back here, so please send it back. One shared, tested copy beats many private patches, and agents
are welcome to prepare a contribution for their user.

## The quickest contribution: "it worked on my setup"

**For `ccd-rehome`** (one machine): run what you normally run (always `--dry-run` first), then

```bash
ccd-rehome report doctor selftest dry-run rehome verify
```

List only what you actually ran. Paste the JSON into a **"Works on my setup"** issue, or add it to the `tested`
list in [`skills/session-rehome/tested.json`](skills/session-rehome/tested.json) in a pull request.
The report contains versions only: no e-mail addresses, ids, paths or host names.

**For the transporter** (between machines): add one entry per side to
[`skills/session-transporter/tested.json`](skills/session-transporter/tested.json), in the format of
the entries already there: `tool` (the `st-bundle --version` number), `role` (`export` or `import`), `os_family`,
`os`, `arch`, `python`, `date`, and `verified` (what ran: `list`, `export`, `inspect`, `import`, `verify`,
`origin-proof`, `desktop-load`). Never include paths, host names or session ids.

That is how macOS and Windows become "verified".

## Something is different or broken

1. **Update first:** `git pull` in your clone (or update the plugin). It may already be fixed.
2. **Report it:** if `doctor` prints `DRIFT`, a command refuses unexpectedly, or a result is wrong, open a **"Drift
   or bug"** issue. Include `ccd-rehome report doctor` and the `doctor` output. Replace e-mail addresses, account
   ids and paths with placeholders if you quote other output.

## Fixing it

A pull request is very welcome. The rules are in [AGENTS.md](AGENTS.md) ("Job 2"); in short:

1. **Evidence first.** What exactly changed (a record field, a file, a log line), on which Desktop or CLI version
   and OS.
2. **A failing test first.** Tool behaviour goes in the skill's `scripts/selftest.py` (synthetic fixtures only,
   never real user data); repository rules go in `tests/`.
3. **The fix.** Python 3.9+, standard library only, no new dependencies. In `ccd-rehome`, classify new record
   fields (`KNOWN_KEYS` / `ACCOUNT_BOUND` / `TRANSIENT`) and new per-account entries (`KNOWN_ENTRIES` plus
   `move()`).
4. **Prove the test bites:** it passes with the fix and fails when you break the fix on purpose.
5. **Docs in the same pull request:** the skill's `references/` (the evidence), its `SKILL.md` and `docs/` if
   behaviour changed, a `CHANGELOG.md` entry, and the version bumped in all places (AGENTS.md, rule 5).
6. **Unsure of the right behaviour?** Make the tool refuse that case with a clear message. That is a fine pull
   request on its own.

Then run everything:

```bash
python3 tests/run_all.py
```

## How to open a pull request

```bash
gh repo fork kulogix/session-rehome --clone
```

```bash
cd session-rehome && git checkout -b handle-desktop-4-30-new-field
```

Make the change, run the tests, then:

```bash
git commit -am "Handle <what> (Desktop <version>, <OS>)" && gh pr create --fill
```

If your installed skills are links into an existing clone (the default of `install.py` on macOS and Linux), you
can work right there and add your fork as a remote:

```bash
gh repo fork --remote
```

A fork is only the vehicle for a pull request. Please don't publish long-lived variants: an improvement that lands
here reaches everyone, and a separate copy drifts and breaks on its own.

## CI

Every push and pull request runs `tests/run_all.py` (both self-tests and the repository tests) on Linux, macOS
and Windows, with Python 3.9 and 3.13, and validates the plugin with `claude plugin validate`.
- **Linux** must pass.
- **macOS and Windows** are reported but do not block yet, until someone confirms them on real machines with a
  `tested.json` entry.

## Ground rules

- **Never weaken a safety check** to make a case work. Add the case to the documented contract instead.
- **No telemetry, no network calls, no new dependencies.**
- **Never read or copy credential values** (cookies, tokens, passwords). Names and expiry dates are as far as the
  tools go.
- **Never edit a transcript.** The transporter copies transcripts byte for byte and appends; keep it that way.
- **No personal data** in code, fixtures, docs or commit messages (AGENTS.md, rule 7).
