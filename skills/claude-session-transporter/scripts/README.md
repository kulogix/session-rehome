# session-transporter / scripts

Six drivers plus four helpers. They move a Claude Code session — transcript, sidecars,
memory, task store, project tree — from one host/account to another, and prove afterwards
that the history was not modified and the origin was not touched.

Nothing here needs a third-party package. POSIX-ish bash (written for bash 3.2, the macOS
system bash, as well as bash 5) and `python3` stdlib only, so the same files run on the
origin (over ssh stdin) and on the destination.

**All human output goes to stderr.** That is deliberate: refusal messages from the ssh
chokepoint used to land on stdout, which is where callers collect the origin probe's JSON —
a refused command wrote its reason *into* the probe JSON and the temp-file cleanup then
destroyed it. Capture a run with `--report FILE` or `2>&1 | tee`.

## The bundle path (no ssh, any OS): `st-bundle.py`

`export` (origin) → copy the file → `inspect` / `import --plan` / `import --apply` (destination) →
`origin-proof` (origin) → `st-verify.sh --origin-proof` (destination). The import unpacks into the
checkpoint layout and runs `st-transplant.py`, so the refusals below apply unchanged. Pure Python stdlib.
`selftest.py` covers it end to end on two synthetic machines.

**New in st-transplant.py:**
- `--no-memory`.
- `--no-settings`; `--settings-key` now REPLACES the defaults (it used to append to them, so they
  could never be turned off).
- `--record-file` (a ccd-record/1, adopted through claude-desktop-rehome).
- A Python copy fallback when rsync is absent.

**New in st-checkpoint.sh:** `--no-memory`.

**New in st-verify.sh:** `--origin-proof FILE`.

## Order of operations

```
st-preflight.sh  --list-sessions            step 0: find the session id. Writes nothing.
st-preflight.sh  <the real run>       G0/G1  inspect both ends. Writes nothing.
st-checkpoint.sh --plan then --apply  G3     pull a verified, sealed checkpoint.
st-git-rescue.sh --scan; --work+--apply G4   make fragile repos durable, ON A COPY.
st-transplant.py --plan then --apply  G5-G7  install the session at the destination.
st-verify.sh                          G8     prove it loads and the origin is unchanged.
st-resync.sh                          --     write-back, much later, if ever. Dry run by default.
```

Every `st-*.sh` takes `--profile FILE` (see `profile.example`); **flags always win over the
profile**, because the profile is sourced before the argument loop rather than at the point
`--profile` appears in argv. `st-transplant.py` has no `--profile`: it reads the same `ST_*`
names from the environment (`set -a; . ./mig.conf; set +a`). Every script has `--help`.
Every script refuses to do anything destructive without an explicit flag.

Two flag conventions worth knowing before you type anything:

- The "go" verb is **`--apply`** everywhere (`st-checkpoint.sh` still accepts `--run` as a
  deprecated alias). `--plan` / no flag is the dry side.
- Pass a project key as **`--origin-key=<KEY>`**, never `--origin-key <KEY>`. Every key
  begins with `-` and argparse reads a leading-dash value as the next option.

## The helpers

| file | role |
|---|---|
| `mangle.py` | The CLI's project-dir name function `Pw`, lifted from the binary and confirmed against 22/22 observations. Feed it `realpath(cwd)`. **Losing this file means re-deriving the mangler from the ELF before any transplant can be preflighted.** |
| `st_walk.py` | One manifest walker, run on BOTH sides, so the remote and local manifests cannot differ by implementation. Also does the exclude accounting, the manifest comparison (coverage / fidelity / unexpected as three separate gates), the filename-hazard scan over a manifest, the existence probe and the prefix hash. Its globs match rsync's: `*` and `?` do not cross `/`. |
| `st_origin_probe.py` | One-shot read-only recon of the origin, emitted as JSON. `--list-sessions` is the discovery mode. Shipped over ssh stdin so it is never written to the origin. |
| `st-common.sh` | Logging, portability shims, the read-only chokepoint, the typed-confirmation prompt, the profile pre-parser, the placeholder guard. |
| `st_mock_api.py` | A local stand-in for the API that records the exact request body the CLI puts on the wire and answers with a well-formed SSE stream. Zero tokens, no credentials. Use it to read the assembled system prompt — the only way to see it. |
| `excludes.example`, `profile.example` | Templates. Every value in `profile.example` is a deliberate placeholder, and the scripts refuse to run while one survives. |

## What each script will refuse to do

- **st-preflight.sh** — writes nothing at all except files you name with `--report` /
  `--json` / `--emit-profile`. Fails rather than guessing when several project keys hold
  the same session. Needs `ssh` only for a remote origin.
- **st-checkpoint.sh** — refuses an exclude pattern with no justification (unconditionally —
  there is no flag that turns it off); refuses an unanchored pattern unless you write it as
  `unanchored:PATTERN`; refuses to run with no exclude decision at all *unless*
  `--session-only`, where no project tree is transferred; refuses to publish `latest` or
  write `COMPLETE` unless every gate passed; refuses to keep a generation whose staged bytes
  trip the denylist; treats unexpected files as a gate, not an INFO line. Whitelist entries
  that simply do not exist on the origin are **skipped, not failed** — a short session has
  no `memory/`, no `tasks/` and no sidecars.
- **st-git-rescue.sh** — `--apply` requires `--work DIR` (rescue on a copy) or an explicit
  `--in-place` with a typed confirmation, and `--in-place` is refused when the repo lies
  under `ST_ORIGIN_ROOT`; writes nothing without `--apply`; sets `gc.auto=0` as the literal
  first operation; refuses the `git add -A` drift commit while any `--sensitive-list` path
  is untracked-and-unignored; and never makes that commit at all on a repo with real
  history — it writes `drift.patch` + `untracked.txt` instead.
- **st-transplant.py** — refuses a checkpoint with no `COMPLETE`; refuses to replace
  destination files whose content differs from the checkpoint (`--overwrite-destination-work`
  backs them up first); refuses to overwrite the destination's `.git` (`--merge-git`);
  refuses to replace an already-installed skill (`--overwrite-skill`); renames rather than
  deletes an existing destination transcript, and recognises a byte-exact extension of the
  checkpoint as a *resumed session* to be left alone; refuses to mint a Desktop session
  while that instance is running **even with `--force`**; aborts if the prefix hash changes.
  `--trust` is off by default and refuses while any claude process runs.
- **st-verify.sh** — counts a check that did not execute as a FAILURE, never as a pass, and
  reports an auth/onboarding stop during the load probe as INCONCLUSIVE rather than as
  either outcome. Never claims the destination key is correct unless the probe actually
  loaded.
- **st-resync.sh** — dry run unless `--apply`; then a typed file-count confirmation, not a
  y/n; halts on any file changed on both sides; treats a file the origin **deleted** and you
  then edited as a conflict, not a "modify"; never passes `--delete`, `--inplace` or
  `--append`; backs up the pre-write remote bytes locally before overwriting anything;
  treats case-only and NFC/NFD filename collisions as fatal.

## The read-only guarantee

"We never wrote to the origin" is enforced by one chokepoint, `st_ssh_check_cmd` in
`st-common.sh`, not by intention — and it is applied on the `--origin-host local` path too
(`st_local_ro`), so the guarantee does not depend on which branch you took:

- the leading token of every pipeline segment must be on a short allowlist;
- mutating tokens (`rm`, `mv`, `cp`, `chmod`, `mkdir`, `ln`, `dd`, `curl`, `sh`, …) are
  matched as **whole words**, so `find ... -exec rm` is refused while an origin path that
  merely contains the letters is not;
- `git` is on the allowlist only for read-only subcommands — the check skips `-C`, `-c`,
  `--git-dir` and friends, so `git -C /path commit` is refused, not just `git commit`;
- any redirection, and `--delete` / `--inplace` / `--append` / `sed -i`, refuses the whole
  command;
- python helpers are shipped over **stdin**, never written to the origin;
- ssh calls are multiplexed and serialised (a burst of parallel calls produces
  `mux_client_request_session: session request failed`, which reads like a remote failure
  and is not one).

`st-resync.sh --apply` is the single exception, and it bypasses the chokepoint only after
the typed confirmation, logging each origin write as it goes.

## Conventions

- `set -uo pipefail` **without `-e`**, plus an explicit `ST_FAIL` counter: a partial
  failure is recorded and reported rather than aborting mid-tree.
- Output lines are prefixed `OK` / `..` / `WARN` / `FAIL` / `NOTRUN`. `NOTRUN` increments
  the failure count on purpose.
- Exit 0 = every gate passed. Exit 1 = at least one did not. Exit 2 = bad usage.
- Timestamps and directory names are UTC `%Y%m%dT%H%M%SZ`.
- `latest` and `latest-<SESSION-ID>` are **relative** symlinks. Use the per-session one:
  a checkpoint root shared by several migrated sessions leaves bare `latest` naming only
  the last of them.
- A count assertion passes when the destination has **at least** what the checkpoint had.
  More is a session that has been used; fewer is the failure.
