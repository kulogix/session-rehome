@AGENTS.md

## Claude Code specifics

- **A link install makes this folder the live skill.** After `python3 install.py`, `~/.claude/skills/<name>` points
  here, so an edit under `skills/` changes the installed skill at once. Skills are read when a session starts:
  start a new session to see a SKILL.md change.
- **Test the tools in a sandbox, never on the user's real profiles.** Both self-tests build synthetic homes in a
  temporary folder. For a manual check, set `HOME` to a temporary folder and `CCD_REHOME_SANDBOX=1`, as the
  self-tests do.
- **You may be running inside Claude Desktop.** Then `ccd-rehome quit` refuses to quit your own window, and a
  `claude` you start from your shell inherits Desktop's environment. For a terminal-leg test, use the clean
  environment shown in AGENTS.md.
- **Check the plugin manifests** with `claude plugin validate .` after editing `.claude-plugin/`, with a clean
  environment as above.
