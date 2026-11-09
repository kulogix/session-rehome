# session-rehome

[![CI](https://github.com/kulogix/session-rehome/actions/workflows/ci.yml/badge.svg)](https://github.com/kulogix/session-rehome/actions/workflows/ci.yml)

Move your Claude Code and Claude Desktop sessions **without losing anything**:
- to another **account** ("I signed in to my work account and my sessions are gone");
- to another **Desktop window** (each `--user-data-dir` is a separate window with its own sign-in);
- to another **terminal account** (each `CLAUDE_CONFIG_DIR` home is a separate login and session history);
- between the **terminal (CLI) and Desktop**, in both directions;
- to **another computer or operating system**: Linux, macOS, Raspberry Pi; Windows is untested.

It is two [Claude Code skills](https://code.claude.com/docs/en/skills) with reference scripts, so an agent can do
it for you, and you can run every step yourself. The scripts need Python 3.9 or newer and nothing else. They
collect no telemetry and contact no online service: the only network use is ssh to a machine you name, in the
transporter's ssh-based procedure. MIT licensed.

## Which tool for which move

| You want to move a session… | Tool | Commands |
|---|---|---|
| to the account a Desktop window is signed in to now | `ccd-rehome` | `status`, then `rehome WINDOW` |
| to a particular account | `ccd-rehome` | `move WINDOW --to EMAIL --only ID` |
| to another Desktop window on the same machine | `ccd-rehome` | `move WINDOW --only ID --to-profile OTHER` |
| to another terminal account (`CLAUDE_CONFIG_DIR` home) on the same machine | `ccd-rehome` | `profiles`, then `move cli --only ID --to-profile cli:work` |
| from the terminal into Desktop | `ccd-rehome` | `cli-sessions`, then `register WINDOW --cli-session-id ID` |
| from Desktop to the terminal | `ccd-rehome` | `resume-cli WINDOW --only ID` prints the command |
| to another computer or OS | `st-bundle` | `export` there → copy one file → `import` here |
| from a computer you can ssh to, or from a backup | the transporter's gated procedure | see [other machines](docs/other-machines.md) |

`ccd-rehome` belongs to the skill [session-rehome](skills/session-rehome/SKILL.md) and works on one
machine. `st-bundle` belongs to [session-transporter](skills/session-transporter/SKILL.md) and moves
between machines.

A conversation is a file in a CLI home's `projects/` folder. Each `CLAUDE_CONFIG_DIR` home has its own `projects/`
(`~/.claude/projects/` for the default home), and every Desktop window reads the default home unless it was started
with `CLAUDE_CONFIG_DIR`. So the moves between accounts and between Desktop windows never copy a conversation: they
only change which window and account *lists* it. A move to another terminal account is different: `move cli` moves
the conversation byte for byte into the other home's `projects/` (with `--copy`, it copies it and keeps the
original). A move to another machine copies it. A conversation is never edited.

## Status

| | Linux | macOS | Windows |
|---|---|---|---|
| `ccd-rehome` (one machine) | verified: x86_64 and Raspberry Pi | partly verified: self-test and read-only commands on a real Mac | experimental: CI self-test only |
| `st-bundle` (between machines) | verified: export, and import on a Raspberry Pi | verified: import | untested (pure Python, so expected to work) |

Every combination that passed is recorded in [`skills/session-rehome/tested.json`](skills/session-rehome/tested.json)
and [`skills/session-transporter/tested.json`](skills/session-transporter/tested.json). Reports from
macOS and Windows are very welcome; see [CONTRIBUTING.md](CONTRIBUTING.md).

Moves between terminal accounts (`move cli`, new in 0.11.0) are checked by the self-test on synthetic homes, and the
real Claude Code CLI (2.1.319) found and loaded a transcript moved between two synthetic homes (one run so far, on
2026-11-08; `tests/e2e_real_cli.py` repeats it). They have not yet run on a real signed-in CLI home: do the dry
run first ([switch-accounts.md](docs/switch-accounts.md#terminal-cli-accounts)).

## Install

You need [Claude Code](https://code.claude.com/docs/en/setup) for the skills, and Python 3.9+ for the scripts.
Claude Desktop itself is optional: see [docs/get-claude-desktop.md](docs/get-claude-desktop.md).

**For your agent only:** install the plugin. In Claude Code:

```
/plugin marketplace add kulogix/session-rehome
/plugin install session-rehome@kulogix
```

**For your agent, and to type the commands yourself:** clone the project and run its installer. It links both
skills into `~/.claude/skills` (copies them on Windows) and puts `ccd-rehome`, `st-bundle` and `st-verify` on your
PATH:

```bash
git clone https://github.com/kulogix/session-rehome ~/Projects/session-rehome
```

```bash
python3 ~/Projects/session-rehome/install.py --bin ~/.local/bin
```

Then check the machine. `doctor` writes nothing:

```bash
ccd-rehome doctor
```

Use one install method, not both. Updating, Windows, uninstalling, and moving from earlier versions (0.9.x was
called `claude-session-rehome`): [docs/install.md](docs/install.md).

## Quick start

**"I signed in to another account and my Desktop sessions are gone."** Quit that Desktop window, then:

```bash
ccd-rehome status
```

```bash
ccd-rehome rehome work --dry-run
```

```bash
ccd-rehome rehome work
```

```bash
ccd-rehome launch work
```

```bash
ccd-rehome verify work
```

`status` names your windows (`default`, or a folder name such as `work`) and prints the exact fix command. The
whole procedure, and how to move single sessions: [docs/switch-accounts.md](docs/switch-accounts.md).

**Your windows and CLI homes can live in any folder.** The guides use `~/.claude-instances/work` only as an example.
`ccd-rehome profiles` lists every one it finds and where it found it; register your own folders once:

```bash
ccd-rehome profiles --add-root ~/data/claude
```

(`--add PATH` registers a single window or CLI home, `--forget` undoes either; `CCD_REHOME_INSTANCES` works too.)
The tool keeps its archives and account registry in its own state folder, `~/.local/state/session-rehome` on Linux
(`~/Library/Application Support/session-rehome` on macOS, `%LOCALAPPDATA%\session-rehome` on Windows), or in
`~/.claude-instances/_rehome` if an earlier version made it there. Details:
[docs/multiple-instances.md](docs/multiple-instances.md#your-own-folders).

**"Continue this session on my other computer."** On the computer that has the session:

```bash
st-bundle list
```

```bash
st-bundle export --session-id ID --project-root ~/Projects/myproject -o myproject.csb.zip --dry-run
```

```bash
st-bundle export --session-id ID --project-root ~/Projects/myproject -o myproject.csb.zip
```

Copy `myproject.csb.zip` to the other computer any way you like. Then, there:

```bash
st-bundle import myproject.csb.zip --dest-root ~/Projects/myproject --plan
```

```bash
st-bundle import myproject.csb.zip --dest-root ~/Projects/myproject --apply
```

The import prints the command that verifies the result. Step by step, with Desktop windows and the proof that the
original was not touched: [docs/other-machines.md](docs/other-machines.md).

**"Show my terminal session in Desktop" (or the reverse).**

```bash
ccd-rehome cli-sessions
```

```bash
ccd-rehome register default --cli-session-id ID
```

```bash
ccd-rehome resume-cli default --only ID
```

What carries over in each direction: [docs/cli-and-desktop.md](docs/cli-and-desktop.md).

## What it never does

- **Sign you in or out.** It never reads passwords, tokens or cookies; it only notes whether a login exists.
- **Edit a conversation.** Transcripts are only ever moved or copied, byte for byte, with a note appended at the end
  when a session moves to another machine.
- **Lose the original.** Every change is archived first and can be undone exactly (`ccd-rehome rollback`). A
  bundle never changes the machine it came from, and a proof file shows that.
- **Guess.** Before changing anything it checks every file against the formats it knows. A file it does not
  understand stops the move. A dry run writes nothing at all.
- **Use Desktop's "Recover CLI sessions" button.** That import rewrites the conversation file in place and strips
  its reasoning. `ccd-rehome register` does the same job safely.

## Documentation

| Guide | Contents |
|---|---|
| [docs/install.md](docs/install.md) | plugin or clone, updating, Windows, uninstalling, moving from the older repositories |
| [docs/get-claude-desktop.md](docs/get-claude-desktop.md) | getting Claude Desktop on macOS, Windows, Linux and Raspberry Pi |
| [docs/multiple-instances.md](docs/multiple-instances.md) | running several Desktop windows, each signed in to its own account |
| [docs/switch-accounts.md](docs/switch-accounts.md) | changing a window's account; moving, inspecting and undoing |
| [docs/cli-and-desktop.md](docs/cli-and-desktop.md) | terminal ↔ Desktop, and what carries over |
| [docs/other-machines.md](docs/other-machines.md) | moving a session to another computer or OS |
| [docs/troubleshooting.md](docs/troubleshooting.md) | every message, what it means, and what to do |
| [docs/how-it-works.md](docs/how-it-works.md) | where sessions live, and why they seem to vanish |

**For agents:** each skill's `SKILL.md` is its operating manual
([session-rehome](skills/session-rehome/SKILL.md),
[session-transporter](skills/session-transporter/SKILL.md)). [AGENTS.md](AGENTS.md) covers working on
this repository.

## Contributing, security, license

Claude Desktop changes often, and this project is maintained by the people (and agents) who use it. A report that
it worked on your setup takes one command; a fix starts with a failing test. See [CONTRIBUTING.md](CONTRIBUTING.md).
To report a vulnerability, see [SECURITY.md](SECURITY.md). Released under the [MIT License](LICENSE).

This is an independent project, not made by or affiliated with Anthropic. It relies on how Claude Desktop and
Claude Code store sessions today, which can change with any release; `ccd-rehome doctor` says when it has.
