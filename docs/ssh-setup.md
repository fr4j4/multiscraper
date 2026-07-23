# SSH Setup

`multiscraper` reads ROMs from a remote host with the
`SshTransport` class in `src/multiscraper/transport/ssh.py`. The
transport is built on [`asyncssh`](https://asyncssh.readthedocs.io/)
and supports key-based auth, password auth, SSH agent, and
ProxyJump. Host key verification defaults to **strict**; you can
opt into `auto-trust` for LANs.

## When do you need SSH?

Use SSH when your ROMs live on a different machine — a Raspberry Pi
running RetroPie, a Batocera box, a NAS — and you do not want to
mount the share. The transport only reads metadata (size, mtime)
and computes hashes (`crc32` / `sha1sum`) on the remote host. The
ROM bytes are not transferred; only media files end up on your
local `media_root`.

## Authentication modes

### Key-based (recommended)

Generate a key pair on the local machine and copy the public key to
the remote host's `~/.ssh/authorized_keys`:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519 -C "multiscraper"
ssh-copy-id -i ~/.ssh/id_ed25519 pi@192.168.1.42
```

In `systems.yaml`:

```yaml
roms_root: ssh://pi@192.168.1.42:22/home/pi/RetroPie/roms

ssh_profiles:
  arcade01:
    host: 192.168.1.42
    port: 22
    user: pi
    key_file: ~/.ssh/id_ed25519
    known_hosts: ~/.ssh/known_hosts
```

`asyncssh` looks for the key file at the path you give it. If the
file is passphrase-protected, `asyncssh` will prompt on the
terminal.

### Password (via env var)

For hosts that do not accept keys (typical on consumer NAS firmware
or default RetroPie installs), you can fall back on a password.
Resolve it from an env var so the YAML stays portable:

```yaml
ssh_profiles:
  arcade01:
    host: 192.168.1.42
    user: pi
    password: ${env:ARCADE_SSH_PASS}
```

Set the env var before running:

```bash
export ARCADE_SSH_PASS='hunter2'
multiscraper scrape
```

Prefer a key. Passwords in the YAML are visible in `ps` and in any
process listing.

### SSH agent

If `key_file` is omitted, `asyncssh` consults the running agent
(`SSH_AUTH_SOCK`). Start the agent, add the key, and run
`multiscraper` from the same shell:

```bash
eval "$(ssh-agent -s)"
ssh-add ~/.ssh/id_ed25519
multiscraper scrape
```

This is the most ergonomic option on developer workstations and is
the only way to use a passphrase-protected key without interactive
prompts in batch runs.

### ProxyJump

For hosts behind a bastion:

```yaml
ssh_profiles:
  arcade01:
    host: 10.0.0.5
    user: pi
    key_file: ~/.ssh/id_ed25519
    jump_host: user@bastion.example.com
```

`asyncssh` tunnels the connection through the bastion. The bastion
needs the same key (or a different one configured separately; in
this minimal setup we reuse the same key).

CLI flag equivalent:

```bash
multiscraper scrape --ssh-jump user@bastion.example.com ...
```

## Host key verification (`known_hosts`)

By default, `SshTransport` enforces strict host key checking
(spec decisión #15). On the first connection the host's key must
already be in the `known_hosts` file; otherwise the connection
fails with `SshAuthError`.

### Recommended workflow

1. Add the host manually with `ssh-keyscan` and the canonical port:

   ```bash
   ssh-keyscan -p 22 192.168.1.42 >> ~/.ssh/known_hosts
   ```

2. Verify by hand once with `ssh pi@192.168.1.42` so the fingerprint
   is on your screen.

3. Run `multiscraper scrape`. Subsequent runs will succeed
   automatically.

### `--auto-trust` (LAN convenience)

For trusted LANs (RetroPie at home, a development board on your
desk) you can skip the strict check:

```bash
multiscraper scrape --auto-trust --roms-root ssh://pi@192.168.1.42/roms
```

The flag is wired in `SshTransport._ensure_connected`:

```python
if self._auto_trust:
    kh = None
elif self._known_hosts:
    kh = self._known_hosts
else:
    kh = []
```

With `--auto-trust`, `asyncssh` will accept any host key on the
first connection. **Do not use this on networks you do not control.**

## `SshTransport` internals

Source: `src/multiscraper/transport/ssh.py`.

```python
class SshTransport:
    def __init__(
        self,
        host: str,
        port: int = 22,
        user: str | None = None,
        password: str | None = None,
        key_file: str | None = None,
        known_hosts: str | None = None,
        auto_trust: bool = False,
        jump_host: str | None = None,
    ): ...
```

The transport implements the `RomTransport` Protocol from
`src/multiscraper/transport/base.py`:

- `list_dir(path)` runs `ls -1 <path>` on the remote shell.
- `file_info(path)` runs `stat -c '%s %Y' <path>` and returns a
  `FileInfo(path, size, mtime, is_file=True)`.
- `hash(path, algo)` runs `crc32 <path>` (note: this is the
  `crc32` package; install on the remote host if missing) or
  `sha1sum <path> | cut -d' ' -f1`.
- `open_read(path, max_bytes=None)` streams the file via
  `conn.create_process("cat <path>")`, yielding 64 KiB chunks.
- `close()` closes the connection.

A single SSH connection is reused for the whole run. If the
connection drops mid-run, the next call to `_ensure_connected`
re-opens it (the `is_closed()` check returns `True` after a
network error). The transport does not implement automatic
reconnect with backoff; the orchestrator's supervisor handles job
retries at a higher level.

## End-to-end example

```bash
# 1. Add the host key once
ssh-keyscan -p 22 192.168.1.42 >> ~/.ssh/known_hosts

# 2. Test the connection
ssh pi@192.168.1.42

# 3. Configure systems.yaml
cat > config/systems.yaml <<'EOF'
roms_root: ssh://pi@192.168.1.42:22/home/pi/RetroPie/roms
media_root: ~/multiscraper_data/media

ssh_profiles:
  arcade01:
    host: 192.168.1.42
    port: 22
    user: pi
    key_file: ~/.ssh/id_ed25519
    known_hosts: ~/.ssh/known_hosts
EOF

# 4. Run
multiscraper scrape --systems snes,psx
```

The same flow with the CLI flags instead of `systems.yaml`:

```bash
multiscraper scrape \
  --roms-root ssh://pi@192.168.1.42:22/home/pi/RetroPie/roms \
  --ssh-host 192.168.1.42 \
  --ssh-user pi \
  --ssh-key ~/.ssh/id_ed25519 \
  --ssh-port 22 \
  --systems snes,psx
```

## Troubleshooting

- **`SshAuthError: host key mismatch`** — the host's key changed
  (reinstall, new fingerprint). Remove the old line from
  `known_hosts` and re-`ssh-keyscan`.
- **`SshAuthError: no auth methods available`** — neither key nor
  password worked. Check file permissions on `~/.ssh` and
  `authorized_keys` on the remote.
- **`asyncssh.PermissionDenied`** — the user exists but cannot log
  in. Verify with `ssh -v pi@host` first.
- **`crc32: command not found`** on the remote — the host lacks
  `crc32`. Install it (Debian: `apt install crc32`) or pass
  `--hash sha1` to skip the CRC step.
- **Hangs forever** — the bastion or the host is unreachable. Run
  with `-vv` to see the asyncssh debug output.
