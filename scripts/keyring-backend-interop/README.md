# Keyring encrypted transport interoperability

This qualification uses a private `dbus-run-session` and an in-memory synthetic
Secret Service. It never opens a user's existing bus or credential store.

The baseline binary uses the original keyring 3.6.3
`linux-native-async-persistent` transport. The candidate binary calls the actual
`codex-keyring-store::DefaultKeyringStore` from this checkout, whose Linux feature
uses `linux-native-sync-persistent`, `crypto-rust`, and vendored libdbus. The
production credential API and keyring version remain unchanged.

The test reads and updates each other's credentials in both directions, deletes
those credentials, distinguishes missing entries from errors, handles ambiguous
matches, and unlocks a locked synthetic item. The fixture rejects every plain
session. It derives DH/HKDF/AES keys independently in Python and checks the real
Rust clients' encrypted payloads. The candidate executable must not dynamically
link libdbus.

The current keyring 3.6.3 persistent default builder returns `SsCredential`; both
binaries assert this actual behavior. The qualification does not assume that
`Entry::new` wraps the keyutils cache merely from the feature's name.

On Linux, install `dbus`, `python3-gi`, `python3-cryptography`, a C toolchain and
Rust 1.95.0, then run:

```sh
/usr/bin/python3 scripts/keyring-backend-interop/run.py --output /tmp/keyring-interop-evidence
```

The standalone probe lock deliberately includes the original zbus transport as
an interoperability oracle. The production dependency audit remains separate;
its full policy must pass without exceptions for the retired zbus crates. The
runner binds the keyring/dbus/libdbus/tracing versions and checksums to the
production lock and records both lock hashes, source SHA, input file hashes,
binary hashes, every client result and the fixture's encrypted session events.

`keyring-backend-interop.yml` is reusable/manual and also runs on the two isolated
WSP repair branch patterns. No secrets are requested, and job permissions are
read-only. It tests Linux transport compatibility, not macOS/Windows backend
execution or a real desktop's UI prompt implementation.
