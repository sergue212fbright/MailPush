#!/bin/sh
set -eu
umask 077
mkdir -p "$GNUPGHOME" "$PASSWORD_STORE_DIR" "$XDG_CONFIG_HOME" "$XDG_CACHE_HOME" "$XDG_DATA_HOME"
chmod 0700 "$GNUPGHOME" "$PASSWORD_STORE_DIR"
if [ ! -f "$PASSWORD_STORE_DIR/.gpg-id" ]; then
    # This is a local credential-store key, separate from Proton's mailbox keys.
    # The mounted private volume is its trust boundary; it has no passphrase so
    # Bridge can restart unattended. Protect/encrypt that volume at the host.
    if ! gpg --batch --list-secret-keys --with-colons 2>/dev/null | awk -F: '$1 == "fpr" {found=1} END {exit !found}'; then
        gpg --batch --pinentry-mode loopback --passphrase '' --quick-generate-key 'MailPush Bridge local store' default default never >/dev/null 2>&1
    fi
    mailpush_store_fingerprint="$(gpg --batch --with-colons --list-secret-keys 2>/dev/null | awk -F: '$1 == "fpr" {print $10; exit}')"
    test -n "$mailpush_store_fingerprint"
    pass init "$mailpush_store_fingerprint" >/dev/null
fi
exec protonmail-bridge "$@"
