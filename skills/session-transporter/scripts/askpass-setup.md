<!-- Generalised from the reference migration. `ORIGIN_HOST` is the origin's ssh host and
     `ORIGIN_USER` the account you reach it as; substitute both before quoting any command
     to a user. Nothing here is run by any script — every option ends with the USER typing
     something at their own terminal. -->

# Providing the ORIGIN_HOST admin password without me seeing it

**Current status: not needed.** Everything so far — SSH, reading `~/.claude`, reading
`~/Projects`, rsync pull — works as `ORIGIN_USER` with the existing SSH key. No `sudo` has
been required and none is anticipated for the migration itself.

If a genuinely privileged operation comes up (installing a system package on ORIGIN_HOST,
reading another user's files, loading a kext for capture), here are the options, best first.
In all of them the password lands in the kernel/keychain or in a process's stdin — never in
my context, never in a file I read, never in a shell history, and never in the transcript.

## Option 1 — Passwordless sudo for one specific command (best)

You run this once, at your own terminal on ORIGIN_HOST:

```sh
# on ORIGIN_HOST, in your own terminal
sudo visudo -f /etc/sudoers.d/claude-transporter
```

and add a line scoped to exactly what's needed, e.g.:

```
ORIGIN_USER ALL=(root) NOPASSWD: /usr/sbin/tcpdump
```

Nothing to transmit, revocable by deleting the file, and scoped to one binary. I'd tell you
the exact command string to authorize before you add it, and you can decline any of them.

## Option 2 — SSH_ASKPASS handoff (password never touches my context)

You run this in **your own** terminal, and it stays resident:

```sh
# on ORIGIN_HOST, in your own terminal — reads the password into the agent's memory only
mkdir -p ~/.private && chmod 700 ~/.private
cat > ~/.private/askpass.sh <<'EOF'
#!/bin/sh
cat "$HOME/.private/.p"
EOF
chmod 700 ~/.private/askpass.sh
read -rs -p "admin password: " P && printf '%s' "$P" > ~/.private/.p && unset P && echo
chmod 600 ~/.private/.p
```

Then I invoke privileged commands as:

```sh
ssh ORIGIN_HOST 'SUDO_ASKPASS=$HOME/.private/askpass.sh sudo -A <command>'
```

I never read `~/.private/.p`, never `cat` it, and never echo it. You delete it when we're
done: `shred -u ~/.private/.p` (or just `rm`).

**I will explicitly commit to this:** I will not read, print, copy, or checksum that file,
and I will not run any command whose output could contain it.

## Option 3 — macOS Keychain (no plaintext on disk at all)

```sh
# on ORIGIN_HOST, in your own terminal
security add-generic-password -a "$USER" -s claude-transporter -w
# (prompts for the value interactively; stored encrypted in the login keychain)
```

Then:

```sh
ssh ORIGIN_HOST 'security find-generic-password -a "$USER" -s claude-transporter -w | sudo -S <command>'
```

Caveat: a non-interactive SSH session often can't unlock the login keychain, so this
usually needs the keychain already unlocked by your GUI login. Works well when you're
sitting at the machine; unreliable otherwise.

## Option 4 — you run it, I read the output

For one-off privileged commands, the lowest-tech option is best: I give you the exact
command, you paste it into your terminal, you paste back the output. Zero trust required.

---

## What I will never do

- Type a password into a prompt, form, or field.
- Store one in a variable that ends up in a transcript, log, or file I've read.
- Read `.credentials.json`, `oauth:tokenCache` values, `~/.config/gh/hosts.yml` tokens,
  or `_research/re/server_keys/` contents. These are excluded from the backup manifest's
  *readable* set — where they must be copied for fidelity, they're copied byte-wise
  without being opened.

## Recommendation

Do nothing for now. If sudo turns out to be needed, I'll come back with the exact command
string and we'll use **Option 1** scoped to just that command.
