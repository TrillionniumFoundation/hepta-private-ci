# Secret Service dependency compatibility patch

This directory is the published `zbus-secret-service-keyring-store` 1.0.1 crate
(archive SHA-256
`74801d001b9e7729adb4f1825b67b398185fed424749aa3d8bacf70417137d9a`).
Its MIT and Apache-2.0 license files are included unchanged.

The patch changes only its Secret Service dependency from 5 to the vendored 6
compatibility proposal, its zbus dependency from 5 to 6, and imports of
`OwnedObjectPath` to the new zbus location. The `unixexec` and `ibus` transports,
which were available by default before zbus 6, are enabled explicitly.
Repository rustfmt is also applied to the imported Rust sources.

No credential behavior is changed: keyring 4.2's v1 default-store factory still
selects this store on Linux, and the existing store mutex, Diffie-Hellman session,
service/username/target attributes, default collection, labels, ambiguity checks,
prompt behavior, and error mapping remain. Apple and Windows store dependencies
are unchanged. No advisory is ignored and no feature is removed to pass a gate.

The Secret Service patch documents the required runtime adaptation. The native
qualification runs the original and patched dependencies against the same
isolated D-Bus/GNOME Keyring data and checks cross-version reads, updates,
deletions, persistence, error propagation, and Tokio/thread use. Remove these
path patches together when upstream publishes a compatible maintained release
that passes that qualification.
