"""What the documents say about CLI homes matches the code and the evidence.

Each test here comes from a review finding of 0.11.0: a guide that contradicted the code, a coverage claim the
self-test did not back, an evidence tag with no measurement behind it, a count that did not add up, a refusal
with no troubleshooting row.
"""
import ast
import json
import os
import re
import unittest

from _common import REHOME, ROOT, SKILLS, changelog_newest, check_count_claims, read_text

SKILL = os.path.join(SKILLS, "session-rehome", "SKILL.md")
# SKILL.md keeps the Desktop rows of its Troubleshooting table; the CLI-home rows, and the CLI-home rules in full,
# are in this reference, which SKILL.md tells agents to read. A check of "the agents' table" reads both.
CLI_HOMES = os.path.join(SKILLS, "session-rehome", "references", "cli-homes.md")
AGENT_TABLES = (SKILL, CLI_HOMES)
MECHANICS = os.path.join(SKILLS, "session-rehome", "references", "mechanics.md")
SELFTEST = os.path.join(SKILLS, "session-rehome", "scripts", "selftest.py")
TESTED = os.path.join(SKILLS, "session-rehome", "tested.json")
WILD = None                                  # a {placeholder} of a message template


def flat(s):
    return " ".join((s or "").split())


def section(text, heading):
    """The markdown section that starts with the line `heading` (up to the next heading of the same or a higher
    level)."""
    level = len(heading) - len(heading.lstrip("#"))
    lines, out, on = (text or "").split("\n"), [], False
    for line in lines:
        if line.startswith(heading):
            on = True
        elif on and re.match(r"^#{1,%d} " % level, line):
            break
        if on:
            out.append(line)
    return "\n".join(out)


# ---- refusal messages of the CLI-home code, as templates ({placeholder} -> WILD)
def _template(node, consts=None):
    """The text of a message expression: its constant parts, WILD for each value filled in (a local variable
    that holds one constant string, such as _memory_problem's `why`, is filled in with that string)."""
    consts = consts or {}
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.JoinedStr):
        out = []
        for v in node.values:
            if isinstance(v, ast.Constant):
                out.append(v.value)
            elif isinstance(v, ast.FormattedValue) and isinstance(v.value, ast.Name) and v.value.id in consts \
                    and v.conversion == -1 and v.format_spec is None:
                out.append(consts[v.value.id])
            else:
                out.append(WILD)
        return out
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        a, b = _template(node.left, consts), _template(node.right, consts)
        return None if a is None or b is None else a + b
    return None


def cli_refusal_templates(src):
    """Every refusal ccd-rehome can print about CLI homes: die() messages, `refusals` entries, `bad = ...` reasons
    and the reasons _memory_problem / _target_problem / not_a_cli_home return, in the two CLI-home sections of the
    script, plus any
    message elsewhere that names a CLI home or CLAUDE_CONFIG_DIR. The wrapper `refusing: {}. Nothing was changed.`
    only carries one of the others, so it is left out."""
    lines = src.split("\n")

    def region(title):
        s = next(i for i, l in enumerate(lines) if l.startswith("# ----") and title in l)
        e = next(i for i, l in enumerate(lines[s + 1:], s + 1) if l.startswith("# ----"))
        return s + 1, e + 1

    regions = [region("CLI homes (Claude Code config dirs)"), region("moving between CLI homes")]
    out = []
    for fn in [n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef)]:
        inside = any(a <= fn.lineno < b for a, b in regions)
        assigned = {}
        for n in ast.walk(fn):
            if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
                assigned.setdefault(n.targets[0].id, []).append(n.value)
        consts = {k: v[0].value for k, v in assigned.items()
                  if len(v) == 1 and isinstance(v[0], ast.Constant) and isinstance(v[0].value, str)}
        for n in ast.walk(fn):
            cands = []
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "die" and n.args:
                cands = [n.args[0]]
            elif isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "append" \
                    and isinstance(n.func.value, ast.Name) and n.func.value.id == "refusals" and n.args:
                cands = [n.args[0]]
            elif isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id in ("bad", "refusals")
                                                   for t in n.targets):
                cands = [n.value.elt if isinstance(n.value, ast.ListComp) else n.value]
            elif isinstance(n, ast.Return) and fn.name in ("_memory_problem", "_target_problem", "not_a_cli_home") \
                    and n.value is not None:
                cands = [n.value]
            for c in cands:
                if isinstance(c, ast.IfExp):
                    more = [c.body, c.orelse]
                elif isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id == "next" and c.args \
                        and isinstance(c.args[0], ast.GeneratorExp):
                    more = [c.args[0].elt]
                else:
                    more = [c]
                for m in more:
                    t = _template(m, consts)
                    if not t:
                        continue
                    text = "".join(x if x is not None else "{}" for x in t)
                    if text.startswith("refusing: {}") and text.endswith("Nothing was changed."):
                        continue
                    if inside or "CLI home" in text or "CLAUDE_CONFIG_DIR" in text:
                        out.append((n.lineno, t))
    return out


def _tokens(parts):
    toks = []
    for p in parts:
        if p is None:
            if not toks or toks[-1] is not WILD:
                toks.append(WILD)
        else:
            toks += re.findall(r"[A-Za-z0-9]+", p)       # case kept: `is OPEN in` is not `is open in`
    return toks


def _align(p, t, i, j, lit):
    """Literal words matched when p[i:] is read along t[j:] (a WILD in t stands for one or more words), or 0."""
    if i == len(p):
        return lit
    if j == len(t):
        return 0
    if t[j] is WILD:
        for k in range(i + 1, len(p) + 1):
            r = _align(p, t, k, j + 1, lit)
            if r:
                return r
        return 0
    return _align(p, t, i + 1, j + 1, lit + 1) if p[i] == t[j] else 0


def quoted_matches(span, template):
    """Does the message quoted in a table row (`…` for the parts that vary) fit this template? Every piece between
    the `…` must line up with the template, at least half of it word for word, and at least three words in all."""
    t, total = _tokens(template), 0
    for piece in span.split("…"):
        p = _tokens([piece])
        if not p:
            continue
        best = max((_align(p, t, 0, j, 0) for j in range(len(t))), default=0)
        if not best or best * 2 < len(p):
            return False
        total += best
    return total >= 3


def agent_text(path):
    """The text an agent reads for `path`: SKILL.md together with references/cli-homes.md, anything else alone."""
    return "\n".join(read_text(p) or "" for p in (AGENT_TABLES if path == SKILL else (path,)))


def table_section(path, heading):
    """The section `heading` of `path`; for SKILL.md, that section of SKILL.md and of references/cli-homes.md."""
    return "\n".join(section(read_text(p), heading) for p in (AGENT_TABLES if path == SKILL else (path,)))


def retention_row(path):
    """The `older than N days` row of the troubleshooting table of `path` (for SKILL.md: of SKILL.md or of
    references/cli-homes.md)."""
    return next((l for l in agent_text(path).splitlines() if l.startswith("| `older than N days")), "")


def row_quotes(md, heading):
    """The messages quoted (in backticks) in the first column of the table(s) under `heading`."""
    out = []
    for line in section(md, heading).split("\n"):
        if not line.startswith("|") or line.startswith("|---"):
            continue
        cell = line.split("|")[1]
        out += [a or b for a, b in re.findall(r"``\s?(.+?)\s?``|`([^`]+)`", cell)]
    return out


# ---- the other direction: every message a troubleshooting row quotes is printed by the code, word for word
ELL = object()                               # the `…` of a quoted message: the text that varies


def _str_alts(node):
    """The strings a constant expression can be (a string, or a conditional between two), else None."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.IfExp):
        a, b = _str_alts(node.body), _str_alts(node.orelse)
        return None if a is None or b is None else a + b
    return None


def _forms(node, env, funcs, seen=()):
    """Every form a message expression can take: a list of part lists (a string, or WILD for a value filled in).
    A conditional gives both of its forms; a local variable assigned once (`env`: name -> its expression, such as
    register's `why`) gives the forms of that expression; a call to a function that only ever returns constant
    strings (`funcs`, such as login_note) gives those strings; anything else is a value (WILD)."""
    def sub(x):
        if isinstance(x, ast.Name) and x.id in env and x.id not in seen:
            return _forms(env[x.id], env, funcs, seen + (x.id,))
        if isinstance(x, ast.Call) and isinstance(x.func, ast.Name) and x.func.id in funcs:
            return [[s] for s in funcs[x.func.id]]
        if isinstance(x, (ast.Constant, ast.JoinedStr, ast.BinOp, ast.IfExp)):
            return _forms(x, env, funcs, seen)
        return [[WILD]]

    def product(a, b):
        return [x + y for x in a for y in b][:64]

    if isinstance(node, ast.Constant):
        return [[node.value]] if isinstance(node.value, str) else [[WILD]]
    if isinstance(node, ast.JoinedStr):
        res = [[]]
        for v in node.values:
            if isinstance(v, ast.Constant):
                res = product(res, [[v.value]])
            elif v.conversion == -1 and v.format_spec is None:
                res = product(res, sub(v.value))
            else:
                res = product(res, [[WILD]])
        return res
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return product(sub(node.left), sub(node.right))
    if isinstance(node, ast.IfExp):
        return sub(node.body) + sub(node.orelse)
    return sub(node) if isinstance(node, (ast.Name, ast.Call)) else [[WILD]]


def _split_format(s, rx):
    out = []
    for i, piece in enumerate(re.split(rx, s)):
        out += ([WILD] if i else []) + [piece]
    return out


def _word_tokens(parts):
    """Words and punctuation, case kept: `is OPEN in` is not `is open in`, `'…'` is not `…`."""
    toks = []
    for p in parts:
        if p is WILD:
            if not toks or toks[-1] is not WILD:
                toks.append(WILD)
        else:
            toks += re.findall(r"\w+|[^\w\s]", p)
    return toks


def message_forms(path):
    """Every text the program at `path` can print, as token tuples (WILD: a value filled in). A Python tool is read
    with ast: its string constants, f-strings, `+` concatenations, `%` and `.format` templates. Any other file (a
    shell script) line by line, with `$VAR`, `${...}` and `$(...)` as the values."""
    src = read_text(path) or ""
    out = set()
    try:
        tree = ast.parse(src)
    except SyntaxError:
        for line in src.split("\n"):
            out.add(tuple(_word_tokens(_split_format(line, r"\$\{[^}]*\}|\$\([^)]*\)|\$\w+"))))
        return out
    funcs = {}
    for fn in ast.walk(tree):
        if isinstance(fn, ast.FunctionDef) and not any(isinstance(n, (ast.FunctionDef, ast.Lambda))
                                                       for n in ast.walk(fn) if n is not fn):
            rets = [_str_alts(n.value) if n.value is not None else None
                    for n in ast.walk(fn) if isinstance(n, ast.Return)]
            if rets and all(r is not None for r in rets):
                funcs[fn.name] = [s for r in rets for s in r]
    for scope in [tree] + [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
        assigned = {}
        for n in ast.walk(scope):
            if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
                assigned.setdefault(n.targets[0].id, []).append(n.value)
        env = {k: v[0] for k, v in assigned.items() if len(v) == 1}
        for n in ast.walk(scope):
            if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Mod) and isinstance(n.left, ast.Constant) \
                    and isinstance(n.left.value, str):
                forms = [_split_format(n.left.value, r"%[-#0 +]*\d*(?:\.\d+)?[sdrfxi]")]
            elif isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "format" \
                    and isinstance(n.func.value, ast.Constant) and isinstance(n.func.value.value, str):
                forms = [_split_format(n.func.value.value, r"\{[^{}]*\}")]
            elif isinstance(n, (ast.JoinedStr, ast.BinOp, ast.IfExp)) or \
                    (isinstance(n, ast.Constant) and isinstance(n.value, str)):
                forms = _forms(n, env, funcs)
            else:
                continue
            out.update(tuple(_word_tokens(f)) for f in forms
                       if any(isinstance(x, str) and re.search(r"\w", x) for x in f))
    return out


def _quote_tokens(quote):
    """(token, preceded by a space) pairs of a quoted message; ELL for each `…`."""
    out = []
    for i, piece in enumerate(quote.split("…")):
        if i:
            out.append(ELL)
        for m in re.finditer(r"\w+|[^\w\s]", piece):
            out.append((m.group(), i == 0 and m.start() == 0 or m.start() > 0 and piece[m.start() - 1].isspace()))
    return out


# Messages a row quotes that no tool of this project prints: what the row's reader sees comes from elsewhere.
NOT_OURS = {"ccd-rehome: command not found": "the shell's own message when the launcher is not on PATH"}

# What a quote may write where the code fills in a value: `…`, a placeholder in capitals (N, ID, PROFILE), a number,
# a home or profile name of the guides' examples (cli, cli:work, work, default) or a path, with punctuation around
# them (`'…'`). Never an ordinary word: `verify: MISMATCH` is not what `verify` prints (that is
# `work: MISMATCH  Desktop loaded …`), and `(ambiguous …)` is not `(ambiguous: N orgs known for this account)`.
PLACEHOLDER = re.compile(r"[A-Z][A-Z0-9_]*|\d+|cli(?::\w+)?|work|default|\S*[/~\\]\S*")


def printed_word_for_word(quote, forms):
    """Is `quote` (`…` for the parts that vary) a run of a message the code prints, word for word? Every word and
    punctuation mark must be the code's, in its order and case, except where the code fills in a value: there the
    quote has `…` or ONE placeholder without spaces (PLACEHOLDER: `N`, `cli:work`, `'…'`), never words of a sentence
    the code does not print. A `…` may also stand for any part of the message. At least one word must be the
    code's own."""
    q = _quote_tokens(quote)
    groups = []                              # the quote's space-separated words that hold letters or digits
    for x in q:
        if x is ELL:
            continue
        tok, spaced = x
        if spaced or not groups:
            groups.append(set())
        if re.match(r"\w", tok):
            groups[-1].add(tok)
    groups = [g for g in groups if g]
    if not groups:
        return False

    def best(t):
        n = len(t)
        memo = {}

        def m(i, j):
            if i == len(q):
                return 0
            key = (i, j)
            if key in memo:
                return memo[key]
            r = None
            if q[i] is ELL:                  # any part of the message, or none
                for k in range(j, n + 1):
                    s = m(i + 1, k)
                    if s is not None and (r is None or s > r):
                        r = s
            elif j < n and t[j] is WILD:     # a value: an empty one, or one placeholder of the quote
                for k in range(i, len(q) + 1):
                    if k > i + 1 and q[k - 1] is not ELL and q[k - 1][1]:
                        break
                    if k > i and not all(PLACEHOLDER.fullmatch(p) or not re.search(r"\w", p) for p in
                                         "".join("…" if x is ELL else x[0] for x in q[i:k]).split("…")):
                        continue
                    s = m(k, j + 1)
                    if s is not None and (r is None or s > r):
                        r = s
            elif j < n and q[i][0] == t[j]:
                s = m(i + 1, j + 1)
                if s is not None:
                    r = s + (1 if re.match(r"\w", t[j]) else 0)
            memo[key] = r
            return r

        return max((s for s in (m(0, j) for j in range(n)) if s is not None), default=None)

    for t in forms:
        words = set(x for x in t if x is not WILD and re.match(r"\w", x))
        if sum(not g <= words for g in groups) > t.count(WILD):      # cheap: a value covers one word at most
            continue
        s = best(t)
        if s:
            return True
    return False


def message_quotes(md, heading):
    """The messages quoted in the first column of the table(s) under `heading`: the backtick spans outside
    parentheses (`(CLI move)`, `` (`resume-cli`) `` say where a message comes from, they quote no message)."""
    out = []
    for line in section(md, heading).split("\n"):
        if not line.startswith("|") or line.startswith("|---"):
            continue
        cell, depth = line.split("|")[1], 0
        for m in re.finditer(r"``\s?(.+?)\s?``|`([^`]+)`|[()]", cell):
            if m.group() == "(":
                depth += 1
            elif m.group() == ")":
                depth = max(0, depth - 1)
            elif depth == 0:
                out.append(m.group(1) or m.group(2))
    return out


class DocsMatchCode(unittest.TestCase):
    maxDiff = None

    def test_every_cli_refusal_has_a_troubleshooting_row(self):
        """Each refusal the CLI-home code can print is quoted by a row of docs/troubleshooting.md (for people) and of
        the agents' Troubleshooting table (SKILL.md's, with the CLI-home rows of references/cli-homes.md)."""
        templates = cli_refusal_templates(read_text(REHOME))
        self.assertGreater(len(templates), 30, "could not read the refusal messages of ccd-rehome")
        for path, heading in ((os.path.join(ROOT, "docs", "troubleshooting.md"), "## One machine"),
                              (SKILL, "## Troubleshooting")):
            quotes = row_quotes(table_section(path, heading), heading)
            self.assertGreater(len(quotes), 20, f"{path}: no troubleshooting table under {heading!r}")
            missing = ["line %d: %s" % (ln, "".join(x if x is not None else "{}" for x in t)) for ln, t in templates
                       if not any(quoted_matches(q, t) for q in quotes)]
            self.assertEqual(missing, [], f"{os.path.relpath(path, ROOT)}: no row quotes these messages")

    def test_every_quoted_message_is_printed_word_for_word(self):
        """The other direction: each message a troubleshooting row quotes is one the code prints, word for word, so a
        reader who searches for it finds the row, and a row never quotes a message the code does not print. All of
        docs/troubleshooting.md (ccd-rehome, the installer, the session-transporter scripts), SKILL.md's table and
        the CLI-home table of references/cli-homes.md."""
        scripts = os.path.join(SKILLS, "session-transporter", "scripts")
        transporter = [os.path.join(scripts, n) for n in sorted(os.listdir(scripts))
                       if n.startswith("st") and n.endswith((".py", ".sh"))]
        guide, wrong = os.path.join(ROOT, "docs", "troubleshooting.md"), []
        for path, heading, programs in ((guide, "## One machine", [REHOME]), (SKILL, "## Troubleshooting", [REHOME]),
                                        (CLI_HOMES, "## Troubleshooting", [REHOME]),
                                        (guide, "## Installing", [os.path.join(ROOT, "install.py")]),
                                        (guide, "## Between machines", transporter)):
            forms = set()
            for prog in programs:
                forms |= message_forms(prog)
            quotes = message_quotes(read_text(path), heading)
            self.assertGreater(len(quotes), 2, f"{path}: no troubleshooting table under {heading!r}")
            wrong += [f"{os.path.relpath(path, ROOT)} {heading!r}: `{q}`" for q in quotes
                      if q not in NOT_OURS and not printed_word_for_word(q, forms)]
        self.assertEqual(wrong, [], "these rows quote a message that is not what the tool prints:\n"
                         + "\n".join(wrong))

    def test_the_config_dir_row_says_which_names_print_it(self):
        """`is not a Claude Code config dir (no projects/, ...)` is printed for a `cli:NAME` only: a path prints
        `... does not exist`, `not a Desktop profile (no config.json)` or `--to-profile '...' is not a CLI home`
        (the self-test pins which). The rows say so, and `... does not exist` has a row of its own."""
        for path, heading in ((os.path.join(ROOT, "docs", "troubleshooting.md"), "## One machine"),
                              (SKILL, "## Troubleshooting")):
            rows = [l for l in table_section(path, heading).split("\n") if l.startswith("| ")]
            config = [l for l in rows if "is not a Claude Code config dir (no projects/" in l.split("|")[1]]
            self.assertEqual(len(config), 1,
                             f"{path}: one row for `is not a Claude Code config dir (no projects/, …`")
            self.assertNotRegex(config[0], r"`cli:NAME`\W*\(?or a path", f"{path}: a path never prints that message")
            for other in ("does not exist", "is not a CLI home", "not a Desktop profile (no config.json)"):
                self.assertIn(other, config[0], f"{path}: the config-dir row names what a path prints instead")
            self.assertTrue(any("`… does not exist`" in l.split("|")[1] for l in rows),
                            f"{path}: no row for `… does not exist`")

    def test_every_cli_home_has_its_own_conversations(self):
        """No guide, reference or tool text says that every Desktop window (or profile) and the terminal share the
        conversations in ~/.claude: each CLAUDE_CONFIG_DIR home has its own projects/, and Desktop reads
        CLAUDE_CONFIG_DIR ?? ~/.claude. multiple-instances.md's "what is shared" and mechanics.md's storage layout say
        so in as many words."""
        wrong = (r"shared by every profile", r"[Ss]hared by all instances\W+\(and by the terminal",
                 r"the shared ~/\.claude/projects", r"the conversation is shared",
                 r"every Desktop window and the terminal share")
        texts = [os.path.join(ROOT, "README.md"), SKILL, CLI_HOMES, MECHANICS, REHOME]
        texts += [os.path.join(ROOT, "docs", n) for n in sorted(os.listdir(os.path.join(ROOT, "docs")))
                  if n.endswith(".md")]
        found = [f"{os.path.relpath(p, ROOT)}: {rx}" for p in texts for rx in wrong
                 if re.search(rx, flat(read_text(p)))]
        self.assertEqual(found, [], "these say that every window and the terminal share one home's conversations")
        shared = flat(section(read_text(os.path.join(ROOT, "docs", "multiple-instances.md")),
                              "## What is separate, and what is shared"))
        self.assertRegex(shared, r"[Ee]ach `CLAUDE_CONFIG_DIR` home has its own `projects/`",
                         "multiple-instances.md: say that each CLAUDE_CONFIG_DIR home has its own projects/")
        layout = flat(section(read_text(MECHANICS), "## 1. Storage layout"))
        self.assertIn("CLAUDE_CONFIG_DIR ?? ~/.claude", layout,
                      "mechanics.md §1: the conversation is in the home the window reads, "
                      "CLAUDE_CONFIG_DIR ?? ~/.claude")

    def test_the_word_for_word_matcher(self):
        """printed_word_for_word itself: a value of the code stands for one name in the quote, never for words."""
        forms = {tuple(_word_tokens(["--to-profile ", WILD, " is not a CLI home (use cli, cli:NAME, or a path)"])),
                 tuple(_word_tokens([WILD, " is signed out (", "no login file", "): sign in there"])),
                 tuple(_word_tokens(["  ", WILD, " [in ", WILD, "]"]))}
        self.assertTrue(printed_word_for_word("--to-profile '…' is not a CLI home", forms))
        self.assertTrue(printed_word_for_word("is not a CLI home", forms))
        self.assertTrue(printed_word_for_word("is signed out (no login file)", forms))
        self.assertTrue(printed_word_for_word("in cli:work", forms))
        self.assertFalse(printed_word_for_word("is not a Claude Code config dir", forms))
        self.assertFalse(printed_word_for_word("is not a cli home", forms), "case counts")
        self.assertFalse(printed_word_for_word("is signed out (its login file is empty)", forms),
                         "a value of the code never stands for several words of the quote")
        self.assertFalse(printed_word_for_word("--to-profile names no CLI home", forms))
        self.assertFalse(printed_word_for_word("…", forms), "a quote must hold at least one word of the code")

    def test_the_matcher_tells_messages_apart(self):
        """The row matcher itself: a fitting quote matches, another message's quote does not."""
        t = ["--to-profile ", None, " is not a CLI home (use cli, cli:NAME, or a path to one)"]
        self.assertTrue(quoted_matches("--to-profile '…' is not a CLI home", t))
        self.assertFalse(quoted_matches("is not a Claude Code config dir", t))
        t2 = [None, " already has ", None, "; nothing was changed"]
        self.assertFalse(quoted_matches("already has a DIFFERENT transcript", t2))
        self.assertTrue(quoted_matches("already has …; nothing was changed", t2))
        self.assertFalse(quoted_matches("`cli:NAME`", t), "a bare name is no message")
        self.assertFalse(quoted_matches("is OPEN in …", [None, " is open in another process: ", None]))
        self.assertFalse(quoted_matches("`cli` is ambiguous here",
                                        ["archive name ", None, " is ambiguous (", None, " matches)"]))
        self.assertTrue(quoted_matches("is or holds ~/.claude-instances, where the Desktop profiles live",
                                       ["is or holds ", None, ", where the Desktop profiles live"]))

    def test_readme_cli_homes_have_their_own_projects(self):
        """README: each CLAUDE_CONFIG_DIR home has its own projects/, and `move cli` moves or copies the conversation
        between homes. It must not say that one-machine moves never copy a conversation."""
        s = flat(read_text(os.path.join(ROOT, "README.md")))
        for wrong in ("one-machine moves never copy a conversation", "Only a move to another machine copies",
                      "every Desktop window and the terminal share the same conversation files"):
            self.assertNotIn(wrong, s, "README contradicts `move cli`")
        self.assertRegex(s, r"[Ee]ach `CLAUDE_CONFIG_DIR` home has its own `projects/`")
        self.assertRegex(s, r"`move cli` moves the conversation byte for byte[^.]*`--copy`")

    def test_advice_into_the_default_home_is_a_copy(self):
        """Every documented command that brings a conversation from another CLI home into ~/.claude (`move cli:NAME
        … --to-profile cli`: the repair of a record shown `in cli:NAME`, the move register asks for, the one a
        rollback's warning prints) is a --copy. The other home is often a backup that kept an old conversation
        ~/.claude's retention deleted; a move re-dates it, which only postpones that retention, and leaves the backup
        without it (final review of round 3, item F). The retention rows say that re-dating only postpones it."""
        texts = [os.path.join(ROOT, "README.md"), SKILL, CLI_HOMES, MECHANICS]
        texts += [os.path.join(ROOT, "docs", n) for n in sorted(os.listdir(os.path.join(ROOT, "docs")))
                  if n.endswith(".md")]
        version, body = changelog_newest(read_text(os.path.join(ROOT, "CHANGELOG.md")))
        bad = []
        for path, text in [(p, read_text(p)) for p in texts] + [(f"CHANGELOG.md {version}", body)]:
            for cmd in re.findall(r"`([^`\n]*\bmove [^`\n]*--to-profile cli(?![:\w\[])[^`\n]*)`", text):
                if "--copy" not in cmd.split():
                    bad.append(f"{os.path.relpath(path, ROOT) if os.path.isabs(path) else path}: `{cmd}`")
        self.assertEqual(bad, [], "these advise a MOVE into ~/.claude; advise --copy (the other home keeps its own)")
        for path in (os.path.join(ROOT, "docs", "troubleshooting.md"), SKILL):
            row = retention_row(path)
            self.assertRegex(flat(row), r"only postpones", f"{os.path.relpath(path, ROOT)}: the retention row must "
                             f"say that re-dating only postpones the deletion")
            self.assertRegex(row, r"use `--copy`", f"{os.path.relpath(path, ROOT)}: the retention row must say to "
                             f"use --copy (to keep the source's own)")

    def test_retention_rows_follow_the_desktop_rule(self):
        """The retention rows and mechanics.md's Retention fact say what the tool does since the fifth round (final
        review of round 4, items G and H, and Claude Code's documented rule for Desktop transcripts): a conversation
        last continued in Claude Desktop is kept at any age unless desktopSessionCleanupPeriodDays is set (Claude
        Code 2.1.248 and later), and --keep-dates goes ahead only with --copy. No row offers --keep-dates as the way
        to keep a transcript's date on a move, and the setup advice for a new home is a --copy too."""
        for path in (os.path.join(ROOT, "docs", "troubleshooting.md"), SKILL):
            rel = os.path.relpath(path, ROOT)
            text = agent_text(path)
            row = retention_row(path)
            for want in ("desktopSessionCleanupPeriodDays", "2.1.248", "--keep-dates keeps that date",
                         "only with `--copy`" if path != SKILL else "use `--copy`"):
                self.assertIn(want, row, f"{rel}: the retention row must say {want!r}")
            self.assertNotIn("(`--keep-dates` keeps the old time)", row,
                             f"{rel}: the retention row offers --keep-dates on a move")
            for cmd in re.findall(r"`([^`\n]*\bmove [^`\n]*--to-profile cli:NAME[^`\n]*)`", text):
                if not any(x in cmd for x in ("--only", "--project", "…")):      # the whole home, as status advises
                    self.assertIn("--copy", cmd.split(), f"{rel}: `{cmd}` advises a move of a whole home; advise "
                                                         f"--copy")
        fact = flat(next((i for i in re.split(r"\n(?=- )", section(read_text(MECHANICS), "## 4b."))
                          if i.startswith("- **Retention**")), ""))
        for want in ("https://code.claude.com/docs/en/claude-directory", "Cleaned up automatically",
                     "desktopSessionCleanupPeriodDays", "2.1.248", "managed settings", "HIPAA", "entrypoint"):
            self.assertIn(want, fact, f"mechanics.md §4b Retention: say {want!r}")
        self.assertNotRegex(fact, r"^- \*\*Retention\*\* \[I\]", "mechanics.md §4b Retention: the rule is documented "
                            "now; tag it from the documentation, with its URL")


    def test_managed_settings_are_read_and_the_rows_say_so(self):
        """Since the sixth round (final review of round 5, NEW-1 to NEW-3) the tool reads managed settings
        (remote-settings.json, then managed-settings.json), re-dates a transcript's sidecar files with it, and on a
        plain move of a transcript last continued in Desktop reads `claude --version`. No document says managed
        settings are not visible to the tool; mechanics.md §4b has a Managed settings fact from the documentation,
        with every path and the cache's shape tagged [I]; both retention rows name what the tool reads."""
        texts = [os.path.join(ROOT, "README.md"), SKILL, CLI_HOMES, MECHANICS, REHOME,
                 os.path.join(ROOT, "CHANGELOG.md")]
        texts += [os.path.join(ROOT, "docs", n) for n in sorted(os.listdir(os.path.join(ROOT, "docs")))
                  if n.endswith(".md")]
        wrong = (r"not visible to the tool", r"neither is visible", r"the tool sees neither",
                 r"the tool cannot see the last two")
        found = [f"{os.path.relpath(p, ROOT)}: {rx}" for p in texts for rx in wrong if re.search(rx, flat(read_text(p)))]
        self.assertEqual(found, [], "these say managed settings cannot be seen; the tool reads them")
        fact = flat(next((i for i in re.split(r"\n(?=- )", section(read_text(MECHANICS), "## 4b."))
                          if i.startswith("- **Managed settings**")), ""))
        for want in ("https://code.claude.com/docs/en/managed-settings", "remote-settings.json",
                     "managed-settings.json", "/etc/claude-code/", "/Library/Application Support/ClaudeCode/",
                     "C:\\Program Files\\ClaudeCode\\", "managed-settings.d/", "HIPAA"):
            self.assertIn(want, fact, f"mechanics.md §4b Managed settings: say {want!r}")
        self.assertRegex(fact, r"top level, as `settings\.json` does, is \[I\]",
                         "mechanics.md §4b Managed settings: tag the remote-settings.json shape [I]")
        for path in (os.path.join(ROOT, "docs", "troubleshooting.md"), SKILL):
            row = retention_row(path)
            for want in ("remote-settings.json", "managed", "`claude --version`", "sidecar folder"):
                self.assertIn(want, row, f"{os.path.relpath(path, ROOT)}: the retention row must say {want!r}")

    def test_retention_takes_the_shortest_value_and_re_dates_a_copy(self):
        """Since the seventh round (final review of round 6, NEW-1 and NEW-2) the tool does not model how Claude Code
        combines its managed sources: for each setting it takes the SHORTEST value that the target's settings.json,
        remote-settings.json, managed-settings.json or a managed-settings.d/ drop-in sets, on purpose. A --copy the
        target would delete is re-dated by the same rule as a move (the copy, never the source). mechanics.md's
        Managed settings fact says so, with the rule tagged as the tool's choice; no document says the drop-ins are
        not read; both retention rows and the move fact say it."""
        texts = [os.path.join(ROOT, "README.md"), SKILL, CLI_HOMES, MECHANICS, REHOME,
                 os.path.join(ROOT, "CHANGELOG.md")]
        texts += [os.path.join(ROOT, "docs", n) for n in sorted(os.listdir(os.path.join(ROOT, "docs")))
                  if n.endswith(".md")]
        wrong = (r"`?managed-settings\.d/`? (?:are|is) not read", r"Not read: [^.]*`managed-settings\.d/`",
                 r"from the higher of its two sources", r"A `--copy` of it is not re-dated",
                 r"On a `--copy` it is not re-dated")
        found = [f"{os.path.relpath(p, ROOT)}: {rx}" for p in texts for rx in wrong if re.search(rx, flat(read_text(p)))]
        self.assertEqual(found, [], "these describe the round-6 rules (drop-ins not read, the higher source wins, a "
                                    "copy of a Desktop transcript never re-dated)")
        items = re.split(r"\n(?=- )", section(read_text(MECHANICS), "## 4b."))
        fact = flat(next((i for i in items if i.startswith("- **Managed settings**")), ""))
        for want in ("managed-settings.d/*.json", "shortest", "on purpose", "the tool's own choice", "never less"):
            self.assertIn(want, fact, f"mechanics.md §4b Managed settings: say {want!r}")
        move = flat(next((i for i in items if i.startswith("- **What a move does about it**")), ""))
        for want in ("the copy (never the source)", "--keep-dates", "content"):
            self.assertIn(want, move, f"mechanics.md §4b What a move does about it: say {want!r}")
        for path in (os.path.join(ROOT, "docs", "troubleshooting.md"), SKILL):
            row = retention_row(path)
            for want in ("shortest", "managed-settings.d/", "never the source", "would delete the copy"):
                self.assertIn(want, row, f"{os.path.relpath(path, ROOT)}: the retention row must say {want!r}")


class DocsStateTheEvidence(unittest.TestCase):
    def test_cli_home_guides_say_how_far_moves_were_tested(self):
        """Until tested.json records a live `move-cli` run, every guide section about moving between CLI homes says
        that no move has run on a real signed-in CLI home yet, and to dry-run first."""
        with open(TESTED, encoding="utf-8") as f:
            ran = {str(c).split()[0] for e in json.load(f)["tested"] for c in e.get("verified", []) if str(c).strip()}
        if "move-cli" in ran:
            self.skipTest("tested.json records a live move-cli run")
        for path, heading in ((SKILL, "## CLI homes"), (os.path.join(ROOT, "docs", "switch-accounts.md"),
                                                        "## Terminal (CLI) accounts"),
                              (os.path.join(ROOT, "docs", "multiple-instances.md"), "## Several CLI accounts"),
                              (os.path.join(ROOT, "README.md"), "## Status")):
            s = section(read_text(path), heading)
            self.assertTrue(s, f"{path}: no section {heading!r}")
            self.assertRegex(flat(s), r"not (?:yet )?(?:been )?run on a real signed-in CLI home",
                             f"{os.path.relpath(path, ROOT)} {heading!r}: say that no move has run on a real "
                             f"signed-in CLI home yet")
            if path != os.path.join(ROOT, "README.md"):
                self.assertIn("--dry-run", s, f"{os.path.relpath(path, ROOT)} {heading!r}: show the dry run")

    def test_mechanics_says_which_rules_the_selftest_checks(self):
        """mechanics.md §4b names, rule by rule, a self-test check that fails without the rule (quoted from
        selftest.py), and what has no check; never "every rule"."""
        md = read_text(MECHANICS)
        sec = section(md, "## 4b.")
        self.assertNotRegex(flat(md), r"exercises every rule", "mechanics.md claims a coverage the self-test lacks")
        table = [l for l in section(sec, "### What the self-test checks").split("\n")
                 if l.startswith("|") and not l.startswith("|---")][1:]
        self.assertGreater(len(table), 20, "mechanics.md §4b: no table of the rules the self-test checks")
        st = read_text(SELFTEST)
        for line in table:
            quotes = re.findall(r'"([^"]{12,})"', line.split("|")[2])
            self.assertTrue(quotes, f"mechanics.md §4b: no quoted check for {line.split('|')[1].strip()!r}")
            missing = [q for q in quotes if q not in st]
            self.assertEqual(missing, [], "mechanics.md §4b quotes checks that selftest.py does not have")
        self.assertRegex(flat(section(sec, "### What the self-test checks")), r"[Nn]o check",
                         "mechanics.md §4b: say which rules have no check")

    def test_measured_tags_say_what_was_measured(self):
        """In mechanics.md §4b an [M] (measured) claim names when or on what it was measured (a date or a version) in
        the same item; a claim nobody measured is [C], [D] or [I]."""
        sec = section(read_text(MECHANICS), "## 4b.")
        items = re.split(r"\n(?=- |\| )", sec)
        tagged = [i for i in items if re.search(r"\[M\b", i)]
        self.assertTrue(tagged, "mechanics.md §4b has no [M] claim at all; did the section move?")
        for item in tagged:
            self.assertRegex(item, r"\d{4}-\d\d-\d\d|\b\d+\.\d+\.\d+\b",
                             f"an [M] claim without a date or version: {flat(item)[:120]!r}")

    def test_changelog_states_its_check_counts(self):
        """The newest CHANGELOG entry states the self-test counts in the form run_all.py compares with a run
        (`session-rehome N checks (M new: a in "SECTION", ...)`, `session-transporter K`), and M is the sum of the
        section counts it lists."""
        version, body = changelog_newest(read_text(os.path.join(ROOT, "CHANGELOG.md")))
        c = check_count_claims(body)
        self.assertIn("session-rehome", c, f"CHANGELOG {version}: state `session-rehome N checks`")
        self.assertIn("session-transporter", c, f"CHANGELOG {version}: state `session-transporter K`")
        if "new" in c or c["sections"]:
            self.assertEqual(c.get("new"), sum(c["sections"].values()),
                             f"CHANGELOG {version}: the new checks are not the sum of the sections listed")

    def test_the_real_cli_claim_names_its_run_and_its_rerun(self):
        """The one measurement with the real Claude Code CLI (mechanics.md §4b) says whose run it was and with what,
        and names the manual test that re-runs it. That test exists, parses as Python 3.9, is not collected by
        run_all.py, and skips with a message (exit 0) unless SESSION_REHOME_E2E=1 is set and `claude` is on PATH;
        AGENTS.md says how to run it."""
        import subprocess
        import sys
        import tempfile
        sec = flat(section(read_text(MECHANICS), "## 4b."))
        self.assertIn("the orchestrator's run on 2026-11-08 with Claude Code 2.1.319", sec,
                      "mechanics.md §4b: say that the real-CLI claim is one run, whose, and with which CLI")
        self.assertIn("tests/e2e_real_cli.py", sec, "mechanics.md §4b: name the test that re-runs the real-CLI claim")
        self.assertIn("SESSION_REHOME_E2E=1 python3 tests/e2e_real_cli.py", read_text(os.path.join(ROOT, "AGENTS.md")),
                      "AGENTS.md: say how to run the manual real-CLI test")
        e2e = os.path.join(ROOT, "tests", "e2e_real_cli.py")
        src = read_text(e2e)
        self.assertTrue(src, "tests/e2e_real_cli.py is missing")
        ast.parse(src, feature_version=(3, 9))
        self.assertFalse(os.path.basename(e2e).startswith("test_"), "run_all.py would collect the manual test")
        for code in ("SESSION_REHOME_E2E", "CLAUDE_CONFIG_DIR", "ANTHROPIC_BASE_URL", "http://127.0.0.1:1",
                     "CLAUDE_CODE_MAX_RETRIES", "API_TIMEOUT_MS", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC",
                     "No conversation found", "--resume", "rollback", "--version", "CCD_REHOME_SANDBOX"):
            self.assertIn(code, src, f"tests/e2e_real_cli.py does not use {code}")
        base = {k: v for k, v in os.environ.items() if k != "SESSION_REHOME_E2E"}
        with tempfile.TemporaryDirectory() as empty:          # a PATH with no `claude` on it
            for env, why in ((base, "SESSION_REHOME_E2E=1 is not set"),
                             (dict(base, SESSION_REHOME_E2E="1", PATH=empty), "no `claude` executable on PATH")):
                r = subprocess.run([sys.executable, "-I", e2e], capture_output=True, text=True, encoding="utf-8",
                                   errors="replace", env=env, timeout=60)
                self.assertEqual((r.returncode, why in r.stdout and r.stdout.startswith("SKIPPED")), (0, True),
                                 f"tests/e2e_real_cli.py must skip ({why}): {r.stdout + r.stderr}")

    def test_changelog_says_how_it_was_made_and_how_far_it_ran(self):
        """The newest entry says where the feature came from (a local DeepSeek V4.1 model, a written spec), that
        Claude reviewed it in seven adversarial rounds and repaired it, and that the real-CLI result is one run, with
        the manual test that re-runs it."""
        text = read_text(os.path.join(ROOT, "CHANGELOG.md"))
        m = re.search(r"^## 0\.11\.0\b.*?(?=^## |\Z)", text, re.M | re.S)
        self.assertIsNotNone(m, "CHANGELOG.md has no 0.11.0 entry")
        version, body = "0.11.0", " ".join(m.group(0).split())   # the release that introduced CLI homes
        for rx in (r"implemented by a local DeepSeek V4\.1 model from a written spec",
                   r"reviewed by Claude in seven adversarial rounds", r"repaired by Claude",
                   r"the orchestrator's run on 2026-11-08", r"tests/e2e_real_cli\.py"):
            self.assertTrue(re.search(rx, body), f"CHANGELOG {version}: state {rx!r}")


if __name__ == "__main__":
    unittest.main()
