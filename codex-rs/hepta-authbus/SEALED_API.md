# Native external-call boundary contract

These examples are compiled by `cargo test -p codex-hepta-authbus --doc`.
An inventory scan does not substitute for this command. Handles describe the
registry that issued them; they do not authenticate an arbitrary caller's choice
of bootstrap root or protect a process from hostile code sharing its OS identity.
Production hosts own bootstrap paths and must resolve current registry state at
admission, dispatch, and settlement boundaries.

A registration can be inspected without granting mutation of its trusted view:

```rust
use codex_hepta_authbus::IssuerRegistration;
fn is_revoked(registration: &IssuerRegistration) -> bool {
    registration.revoked
}
```

There is no externally accessible raw database writer:

```compile_fail
use codex_hepta_authbus::AuthBusAuthorityStore;
```

The read-only view cannot be promoted into a trusted registration:

```compile_fail
use codex_hepta_authbus::{IssuerRegistration, IssuerRegistrationView};
fn forge(view: IssuerRegistrationView) -> IssuerRegistration {
    view.into()
}
```

A genuine registration does not permit revocation or epoch rewriting:

```compile_fail
use codex_hepta_authbus::IssuerRegistration;
fn un_revoke(mut registration: IssuerRegistration) {
    registration.revoked = false;
}
```

Untrusted serialized data cannot mint a registration:

```compile_fail
use codex_hepta_authbus::IssuerRegistration;
fn decode(untrusted: &str) -> IssuerRegistration {
    serde_json::from_str(untrusted).unwrap()
}
```

Settlement registrations are not deserializable authority either:

```compile_fail
use codex_hepta_authbus::SettlementIssuerRegistration;
fn decode(untrusted: &str) -> SettlementIssuerRegistration {
    serde_json::from_str(untrusted).unwrap()
}
```
