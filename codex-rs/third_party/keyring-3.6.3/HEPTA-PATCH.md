# keyring 3.6.3 Secret Service 6 transport backport

This directory preserves the official `keyring` 3.6.3 package, including its
original name, version, MIT/Apache licenses, pre-normalization manifest, VCS
record and `UPSTREAM.crate`. The archive SHA-256 is
`eebcc3aff044e5944a8fbaf69eb277d11986064cba30c468730e8b9909fb551c`;
its upstream commit is `315cbdf6c6a9153d8c9f88b56568f29862d3e39d`.
`UPSTREAM-PINS.json` binds the unchanged implementation and license files.
Every file under `src/` is byte-for-byte identical to that official package.

The normalized Cargo manifest makes the following transport-only changes:

- Require official stable `secret-service =6.0.0` for Linux and the BSD targets.
  That release was published on 2026-11-22 at commit
  `f308f62e8507fc905dc94a845b6b338520c19c93` and depends on zbus 6, which incorporates
  the formerly standalone zvariant, zvariant_derive and zbus_names crates.
- Remove keyring's unused direct zbus 4 dependency. No keyring implementation
  refers to a zbus Rust type. Secret Service owns its zbus 6 dependency.
- Forward the existing `tokio` and `async-io` feature names to Secret Service 6's
  `rt-tokio` and `rt-default`, respectively, following its official migration
  instructions. Its blocking API still provides the methods keyring uses.
- Raise the declared MSRV to 1.89, matching Secret Service 6. This workspace uses
  Rust 1.95.0.

The workspace uses this directory as its explicit keyring dependency and
excludes it from workspace membership. This preserves each consuming crate's
existing platform feature selection; it also avoids treating a third-party
crate's mutually exclusive backend features as first-party `--all-features`.
The package is still named `keyring` and is still included in dependency audits.
No advisory exclusions, license allowances or graph exclusions are added.

Linux retains `linux-native-async-persistent` and `crypto-rust`. Its encrypted
Secret Service path remains pure Rust; no new vendored libdbus is enabled.
macOS/Windows platform backends and BSD's existing synchronous backend selection
are unchanged. The keyring credential identity, lookup, update, error mapping,
explicit keyutils/Secret Service composition and mock APIs are unchanged source.
As in upstream 3.6.3, the default persistent builder actually returns
`SsCredential`; this patch does not silently change that existing behavior.
The synthetic qualification separately exercises the explicit keyutils wrapper,
including recovery after removing its cache and rollback after a backing-store
write failure.

This is a workspace compatibility backport, not a newly published general-purpose
3.6.3 release: callers that name Secret Service's concrete error types would see
the dependency's major-version change. The known workspace consumers are checked
against the shared path dependency. The migration fixture deliberately builds a
separate crates.io 3.6.3 baseline so that its old transport cannot be accidentally
patched into the candidate.

To retire this backport, migrate to an official keyring release on zbus 6,
validate the existing credential identities and consumer behavior with the same
synthetic qualification, remove this directory/path dependency and regenerate
both production locks.

Official sources:

- https://static.crates.io/crates/keyring/keyring-3.6.3.crate
- https://github.com/open-source-cooperative/secret-service-rs/releases/tag/v6.0.0
- https://github.com/open-source-cooperative/secret-service-rs/blob/v6.0.0/README.md
