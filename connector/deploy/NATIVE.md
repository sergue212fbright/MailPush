# Native installation

Docker is optional. Use an existing logged-in Proton Mail Bridge and its generated IMAP credentials. Keep Bridge running independently. Python 3.11+ is required.

## Foreground / pipx

From `connector`:

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-lock.txt
.venv/bin/pip install --no-deps .
cp config.example.toml config.toml
mkdir -m 700 secrets
```

Configure Bridge trust, password file and mailbox IDs as described in `README.md`. Pair the fork's embedded receiver using `mailpush pair`, import its receipt, run `check`, `test`, then `run`. Stop with Ctrl+C. `pipx install .` is an alternative (it resolves pinned direct dependencies but not the supplied transitive lock).

On Windows use `.venv\Scripts\python.exe`, `pip.exe`, and `mailpush.exe`. Set private NTFS ACLs on secrets/state. macOS/Windows process supervision is owner-managed; no launchd/Windows-service installer or validation is supplied.

## Linux systemd

Install the package, configure/pair as a dedicated user, then start the service:

```sh
sudo useradd --system --home-dir /var/lib/mailpush --shell /usr/sbin/nologin mailpush
sudo install -d -o root -g root -m 755 /opt/mailpush
sudo python3 -m venv /opt/mailpush/venv
sudo /opt/mailpush/venv/bin/pip install -r requirements-lock.txt
sudo /opt/mailpush/venv/bin/pip install --no-deps .
sudo install -d -o root -g mailpush -m 750 /etc/mailpush /etc/mailpush/secrets
sudo install -d -o mailpush -g mailpush -m 700 /var/lib/mailpush
sudo install -o root -g mailpush -m 640 config.example.toml /etc/mailpush/config.toml
```

Edit `/etc/mailpush/config.toml` and set `state_dir = "/var/lib/mailpush"` so pairing and the service share the same source UUID. Set a verified Bridge certificate pin/CA. Install Bridge's generated password at `/etc/mailpush/secrets/bridge-password`, root:mailpush mode0640. Do not pass passwords in shell arguments.

For pairing, temporarily allow the service user to write the secrets directory (`chmod 770 /etc/mailpush/secrets`), place the encrypted request in a private location that user can read, and run:

```sh
sudo -u mailpush /opt/mailpush/venv/bin/mailpush pair --config /etc/mailpush/config.toml --request /private/path/phone.mailpush --receipt /var/lib/mailpush/phone.receipt --device phone
sudo chmod 750 /etc/mailpush/secrets
```

Compare fingerprints, copy/import the receipt privately on the phone, and delete transfer files. The subscription file created by pairing is owned by mailpush mode0600. Then:

```sh
sudo -u mailpush /opt/mailpush/venv/bin/mailpush check --config /etc/mailpush/config.toml
sudo -u mailpush /opt/mailpush/venv/bin/mailpush test --config /etc/mailpush/config.toml --device phone
sudo install -o root -g root -m 644 deploy/mailpush.service /etc/systemd/system/mailpush.service
sudo systemctl daemon-reload
sudo systemctl enable --now mailpush
sudo journalctl -u mailpush -f
sudo -u mailpush /opt/mailpush/venv/bin/mailpush status --state-dir /var/lib/mailpush
```

`ProtectHome=true` prevents the service reading secrets in home directories. `StateDirectory` maintains private state; the unit does not manage Bridge. Upgrade by stopping the service, backing up config/secrets/state privately, replacing the wheel and restarting. Preserve the database. Uninstalling binaries need not destroy credentials or state; discard those only deliberately.
