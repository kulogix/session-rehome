# AGENTS.md

Instructions for AI agents working in this repository. People should start with [README.md](README.md).

There are two different jobs. Decide which one you were given before doing anything.

## Job 1: you were asked to USE the tools (move or inspect a user's sessions)

Read the skill that fits the request, all of it, and follow it. Each one starts with the same routing table.

| The user wants… | Read |
|---|---|
| sessions back after a sign-in change; to move sessions to another account; to move a session to another Desktop window; terminal (CLI) ↔ Desktop | [skills/session-rehome/SKILL.md](skills/session-rehome/SKILL.md) |
| to move a session to another computer or operating system; to pull one from a machine reachable over ssh; to restore one from a backup; to fork one | [skills/session-transporter/SKILL.md](skills/session-transporter/SKILL.md) |

When you read a SKILL.md as a plain file (not loaded as a skill), `${CLAUDE_SKILL_DIR}` means the folder that
contains that SKILL.md.

The rules that matter most (each SKILL.md has the full list and the reasons):
- **Never sign in or out** for the user, and never read password, token or cookie values. Relay sign-in
  blockers to the user.
- **Never use Desktop's "Recover CLI sessions"** button or a `claude://resume` link on a real conversation. It
  rewrites the transcript in place. Use `ccd-rehome register` instead.
- **Never edit, trim or re-sign a transcript.** Copy it byte for byte; the tools append a note instead.
- **Dry run first** (`--dry-run`, `--plan`) and show the user the plan, unless they asked for exactly that move.
- **A refusal is a stop.** Exit code `1` means refused or failed, and the message says why; `2` means a bad
  command line; `0` means done or nothing to do. Do not work around a refusal by hand: relay it, or fix the tool
  (job 2).
- **Never quit a Desktop window** without the user's OK: it may hold their live work. The tools refuse to quit
  the window they are running inside.
- **Parse `--json`**, not the text, where a command offers it.
- **Ask before touching a second machine.** A move between machines has consent questions (D1–D6 in the
  transporter's SKILL.md); ask them in chat before the first write.
- **Start a terminal leg in a clean environment.** A `claude` started from a shell inside a Claude Desktop
  session inherits Desktop's environment and is recorded as Desktop. Use
  `env -i HOME="$HOME" USER="$USER" PATH="$PATH" TERM="$TERM" claude ...` on macOS and Linux; on Windows, ask the
  user to run it in a new terminal window. `ccd-rehome resume-cli` prints the right form when it detects the
  problem.

## Job 2: you are CHANGING this repository

### Layout

| Path | What it is |
|---|---|
| `skills/session-rehome/` | skill: `SKILL.md` (agent manual), `scripts/ccd-rehome` (the tool), `scripts/selftest.py`, `references/mechanics.md` (evidence), `tested.json` |
| `skills/session-transporter/` | skill: `SKILL.md`, `scripts/st-bundle.py` and the `st-*` scripts, `scripts/selftest.py`, `references/` (evidence, formats, the gated procedure), `tested.json` |
| `docs/` | the human guides |
| `tests/` | repository tests: privacy, skill structure, every documented command against the tools' `--help`, links, manifests, versions, installer. `tests/run_all.py` runs them and both self-tests |
| `install.py` | installs the skills into `~/.claude/skills` (link or copy) and the command launchers |
| `.claude-plugin/` | the plugin (`session-rehome`) and its marketplace (`kulogix`) |
| `tools/scrub_terms.py` | maintainers' check against a private list of terms that must never be published |

### Rules

1. **One canonical copy.** Fix the tools here. Never copy a script elsewhere to patch it, and never add a
   variant ("v2", a one-off script). A link install (`install.py`) means the user's installed skill *is* this
   folder.
2. **Test first.** Write the check that fails: in the skill's `scripts/selftest.py` for tool behaviour, in
   `tests/` for repository rules. Run it and watch it fail. Then fix. Then **break your fix on purpose** and
   confirm the check catches it (a check that cannot fail is not a check). Finish with
   `python3 tests/run_all.py`: it must print `ALL TESTS PASSED`.
3. **Standard library only, Python 3.9+.** No new dependencies. Each skill folder must work on its own, because
   a copied or plugin-installed skill gets only its own folder: nothing in `skills/<name>/` may refer to files in
   the repository root (`tests/test_skills.py` checks `../` references).
4. **Docs in the same commit as the change:** the SKILL.md (what agents do), `docs/` (what people do),
   `references/` (the evidence), and `CHANGELOG.md` (what changed, what was tested, what was not).
5. **Versions move in lockstep.** One version for the whole project: `VERSION` in
   `skills/session-rehome/scripts/ccd-rehome` and in `skills/session-transporter/scripts/st-bundle.py`,
   `version` in `.claude-plugin/plugin.json`, and the newest `## X.Y.Z` heading in `CHANGELOG.md`.
   `tests/test_repo.py` fails if they disagree. Plugin users only receive an update when the version changes.
6. **Every documented command must exist.** `tests/test_docs_commands.py` reads every command line in the docs
   and the SKILL.md files and asks the tool itself (its `--help`) whether each subcommand and flag is real. When
   you rename a flag, the docs fail until they are fixed too.
7. **Nothing personal, ever.** No real names, e-mail addresses, host names, home paths, IP addresses, or
   account, org or session ids, in code, tests, docs or commit messages. Use the placeholders already in use:
   users `dana` / `jamiedoe`, `example.com` addresses, `192.0.2.x` addresses, synthetic ids such as
   `aaaaaaaa-1111-4111-8111-111111111111`. `tests/test_privacy.py` scans every file. Maintainers also run it with
   `PRIVACY_TERMS_FILE` set to their private list of terms.
8. **Claims need evidence.** A statement about how Claude Desktop or Claude Code behaves needs a measurement, an
   excerpt of code, or a clear "inferred". In `references/`, tag claims `[M]` measured, `[C]` from code, `[D]`
   derived, `[I]` inferred. Add a `tested.json` entry only for what actually ran, with the versions it ran on.
9. **Prefer refusing over guessing.** When the right behaviour is unclear, make the tool refuse that case with a
   clear message, and record the open question in the skill's `references/`.
10. **Never experiment on the user's real data** without their OK. Self-tests build synthetic machines in a
    temporary folder; do the same.

### Running the tests

```bash
python3 tests/run_all.py
```

```bash
python3 tests/run_all.py --quick
```

The first runs everything (under a minute); `--quick` runs only the repository tests (seconds). Set
`SELFTEST_VERBOSE=1` to see the tool's output under a failing self-test check. CI runs the full set on Linux,
macOS and Windows with Python 3.9 and 3.13, and validates the plugin with `claude plugin validate`.

### Submitting

See [CONTRIBUTING.md](CONTRIBUTING.md). In short: a branch, a failing test, the fix, the docs, the CHANGELOG
entry, `python3 tests/run_all.py`, then a pull request. Push or open a pull request only when the user has said
so.
