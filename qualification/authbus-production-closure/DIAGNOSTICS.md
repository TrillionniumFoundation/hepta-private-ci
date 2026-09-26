# AuthBus production-closure diagnostics

- workflow run: 36249470630
- workflow attempt: 1
- trigger SHA: a808addc66438c8136e0aea289bfa66bca95404e
- tested worktree tree: 34a8e606c699614ff831b0c34fc5b9174dabfd2a
- generator SHA-256: 5cbb479a1799bcc174eed43df46d337e0355e3c641b28001cf206a914634d2db
- runner: macOS / ARM64

## Gate outcomes

| Gate | Outcome |
|---|---|
| generator | success |
| cargo fmt | failure |
| AuthBus all-targets | failure |
| evidence AuthBus tests | failure |
| Bao product caller | failure |
| Agentd composition | failure |
| public API inventory | failure |
| strict clippy | failure |

## Changed paths

```text
 M codex-rs/Cargo.lock
 M codex-rs/hepta-agentd/src/authbus_trust.rs
 M codex-rs/hepta-agentd/src/evidence_trust.rs
 M codex-rs/hepta-authbus/Cargo.toml
 M codex-rs/hepta-authbus/src/authority.rs
 M codex-rs/hepta-authbus/src/authority_store.rs
 M codex-rs/hepta-authbus/src/host.rs
 M codex-rs/hepta-authbus/src/lib.rs
 M codex-rs/hepta-authbus/src/quota_store.rs
 M codex-rs/hepta-authbus/src/recovery.rs
 M codex-rs/hepta-authbus/src/settlement.rs
 M codex-rs/hepta-authbus/src/settlement_store.rs
 M codex-rs/hepta-authbus/src/settlement_store_tests.rs
 M codex-rs/hepta-authbus/src/signed.rs
 M codex-rs/hepta-authbus/src/signed_tests.rs
 M codex-rs/hepta-authbus/src/trust_store.rs
 M codex-rs/hepta-bao-adapter/src/https_consumer.rs
 M codex-rs/hepta-bao-adapter/src/https_consumer_tests.rs
 M codex-rs/hepta-evidence/Cargo.toml
 M codex-rs/hepta-evidence/src/authbus_outbox_issuer_tests.rs
 M codex-rs/hepta-evidence/src/authbus_outbox_quarantine_tests.rs
 M codex-rs/hepta-evidence/src/authbus_outbox_tests.rs
 M codex-rs/hepta-evidence/src/authbus_recovery_tests.rs
 M codex-rs/hepta-evidence/src/authbus_store_tests.rs
 M codex-rs/hepta-evidence/src/qualification_tests.rs
?? codex-rs/hepta-authbus/src/host_tests.rs
?? codex-rs/hepta-authbus/src/issuer_registry.rs
?? codex-rs/hepta-authbus/src/owner_lock.rs
?? qualification/authbus-production-closure/
?? scripts/check-authbus-api-inventory.py
```

## authbus-apply tail

```text
```

## authbus-fmt tail

```text
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
Warning: can't set `imports_granularity = Item`, unstable features are only available in nightly channel.
```

## authbus-tests tail

```text
218 |         .expect("expire after dispatch");
    |                               ^^^^^^^^ unknown prefix
    |
    = note: prefixed identifiers and literals are reserved since Rust 2021
help: consider inserting whitespace here
    |
218 |         .expect("expire after dispatch ");
    |                                       +

error: prefix `snapshot` is unknown
   --> hepta-authbus/src/settlement_store_tests.rs:223:24
    |
223 |         .expect("quota snapshot");
    |                        ^^^^^^^^ unknown prefix
    |
    = note: prefixed identifiers and literals are reserved since Rust 2021
help: consider inserting whitespace here
    |
223 |         .expect("quota snapshot ");
    |                                +

error: prefix `settlement` is unknown
   --> hepta-authbus/src/settlement_store_tests.rs:231:32
    |
231 |         .expect("late terminal settlement");
    |                                ^^^^^^^^^^ unknown prefix
    |
    = note: prefixed identifiers and literals are reserved since Rust 2021
help: consider inserting whitespace here
    |
231 |         .expect("late terminal settlement ");
    |                                          +

error: prefix `snapshot` is unknown
   --> hepta-authbus/src/settlement_store_tests.rs:235:24
    |
235 |         .expect("quota snapshot");
    |                        ^^^^^^^^ unknown prefix
    |
    = note: prefixed identifiers and literals are reserved since Rust 2021
help: consider inserting whitespace here
    |
235 |         .expect("quota snapshot ");
    |                                +

error: prefix `policy` is unknown
   --> hepta-authbus/src/settlement_store_tests.rs:252:25
    |
252 |         .expect("revoke policy");
    |                         ^^^^^^ unknown prefix
    |
    = note: prefixed identifiers and literals are reserved since Rust 2021
help: consider inserting whitespace here
    |
252 |         .expect("revoke policy ");
    |                               +

error: prefix `expiry` is unknown
   --> hepta-authbus/src/settlement_store_tests.rs:271:38
    |
271 |         .expect("refund undispatched expiry");
    |                                      ^^^^^^ unknown prefix
    |
    = note: prefixed identifiers and literals are reserved since Rust 2021
help: consider inserting whitespace here
    |
271 |         .expect("refund undispatched expiry ");
    |                                            +

error: prefix `snapshot` is unknown
   --> hepta-authbus/src/settlement_store_tests.rs:276:24
    |
276 |         .expect("quota snapshot");
    |                        ^^^^^^^^ unknown prefix
    |
    = note: prefixed identifiers and literals are reserved since Rust 2021
help: consider inserting whitespace here
    |
276 |         .expect("quota snapshot ");
    |                                +

error: prefix `reservation` is unknown
   --> hepta-authbus/src/settlement_store_tests.rs:293:30
    |
293 |         .expect("cancel held reservation");
    |                              ^^^^^^^^^^^ unknown prefix
    |
    = note: prefixed identifiers and literals are reserved since Rust 2021
help: consider inserting whitespace here
    |
293 |         .expect("cancel held reservation ");
    |                                         +

error: prefix `snapshot` is unknown
   --> hepta-authbus/src/settlement_store_tests.rs:298:24
    |
298 |         .expect("quota snapshot");
    |                        ^^^^^^^^ unknown prefix
    |
    = note: prefixed identifiers and literals are reserved since Rust 2021
help: consider inserting whitespace here
    |
298 |         .expect("quota snapshot ");
    |                                +

error: prefix `retry` is unknown
   --> hepta-authbus/src/settlement_store_tests.rs:311:29
    |
311 |             .expect("cancel retry"),
    |                             ^^^^^ unknown prefix
    |
    = note: prefixed identifiers and literals are reserved since Rust 2021
help: consider inserting whitespace here
    |
311 |             .expect("cancel retry "),
    |                                  +

error: character literal may only contain one codepoint
   --> hepta-authbus/src/settlement_store_tests.rs:320:55
    |
320 |         "UPDATE authbus_quota_reservation SET state = 'settled'
    |                                                       ^^^^^^^^^
    |
help: if you meant to write a string literal, use double quotes
    |
320 -         "UPDATE authbus_quota_reservation SET state = 'settled'
320 +         "UPDATE authbus_quota_reservation SET state = "settled"
    |

error: prefix `accepted` is unknown
   --> hepta-authbus/src/settlement_store_tests.rs:326:62
    |
326 |     assert!(illegal.is_err(), "direct illegal state jump was accepted");
    |                                                              ^^^^^^^^ unknown prefix
    |
    = note: prefixed identifiers and literals are reserved since Rust 2021
help: consider inserting whitespace here
    |
326 |     assert!(illegal.is_err(), "direct illegal state jump was accepted ");
    |                                                                      +

error: prefix `accepted` is unknown
   --> hepta-authbus/src/settlement_store_tests.rs:332:62
    |
332 |     assert!(deleted.is_err(), "live reservation deletion was accepted");
    |                                                              ^^^^^^^^ unknown prefix
    |
    = note: prefixed identifiers and literals are reserved since Rust 2021
help: consider inserting whitespace here
    |
332 |     assert!(deleted.is_err(), "live reservation deletion was accepted ");
    |                                                                      +

error: prefix `dispatch` is unknown
   --> hepta-authbus/src/settlement_store_tests.rs:346:23
    |
346 |         .expect("mark dispatch");
    |                       ^^^^^^^^ unknown prefix
    |
    = note: prefixed identifiers and literals are reserved since Rust 2021
help: consider inserting whitespace here
    |
346 |         .expect("mark dispatch ");
    |                               +

error: prefix `retry` is unknown
   --> hepta-authbus/src/settlement_store_tests.rs:374:33
    |
374 |         .expect("archived exact retry");
    |                                 ^^^^^ unknown prefix
    |
    = note: prefixed identifiers and literals are reserved since Rust 2021
help: consider inserting whitespace here
    |
374 |         .expect("archived exact retry ");
    |                                      +

error: prefix `snapshot` is unknown
   --> hepta-authbus/src/settlement_store_tests.rs:379:24
    |
379 |         .expect("quota snapshot");
    |                        ^^^^^^^^ unknown prefix
    |
    = note: prefixed identifiers and literals are reserved since Rust 2021
help: consider inserting whitespace here
    |
379 |         .expect("quota snapshot ");
    |                                +

error[E0765]: unterminated double quote string
   --> hepta-authbus/src/settlement_store_tests.rs:379:32
    |
379 |           .expect("quota snapshot");
    |  ________________________________^
380 | |     assert_eq!((quota.available, quota.reserved, quota.consumed), (5, 0, 5));
381 | | }
    | |__^

For more information about this error, try `rustc --explain E0765`.
error: could not compile `codex-hepta-authbus` (lib test) due to 29 previous errors
```

## authbus-evidence tail

```text
   Compiling png v0.18.0
   Compiling darling v0.21.3
   Compiling debugserver-types v0.5.0
   Compiling hyper-tls v0.6.0
   Compiling tower-http v0.6.8
   Compiling hyper-rustls v0.27.7
   Compiling gix-commitgraph v0.35.0
   Compiling textwrap v0.11.0
   Compiling codex-utils-rustls-provider v0.0.0 (/Users/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/utils/rustls-provider)
   Compiling starlark_derive v0.14.2
   Compiling serde_urlencoded v0.7.1
   Compiling rama-udp v0.3.0-alpha.4
   Compiling rama-unix v0.3.0-alpha.4
   Compiling gix-quote v0.7.0
   Compiling lru v0.18.2
   Compiling opentelemetry v0.31.0
   Compiling gix-sec v0.13.2
   Compiling erased-serde v0.3.31
   Compiling rustversion v1.0.22
   Compiling strsim v0.10.0
   Compiling cmp_any v0.8.1
   Compiling maplit v1.0.2
   Compiling thiserror v1.0.69
   Compiling sqlx-core v0.9.0
   Compiling tracing-opentelemetry v0.32.1
   Compiling codex-utils-cache v0.0.0 (/Users/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/utils/cache)
   Compiling rama-http-backend v0.3.0-alpha.4
   Compiling rama-socks5 v0.3.0-alpha.4
   Compiling reqwest v0.12.28
   Compiling gix-revwalk v0.29.0
   Compiling icu_locale v2.2.0
   Compiling serde_with_macros v3.17.0
   Compiling zstd v0.13.3
   Compiling image v0.25.9
   Compiling rama-tls-rustls v0.3.0-alpha.4
   Compiling gix-ref v0.61.0
   Compiling codex-utils-home-dir v0.0.0 (/Users/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/utils/home-dir)
   Compiling strum_macros v0.27.2
   Compiling concurrent-queue v2.5.0
   Compiling fixed_decimal v0.7.2
   Compiling globset v0.4.18
   Compiling multimap v0.10.1
   Compiling thiserror-impl v1.0.69
   Compiling regex-lite v0.1.8
   Compiling urlencoding v2.1.3
   Compiling codex-utils-path-uri v0.0.0 (/Users/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/utils/path-uri)
   Compiling codex-utils-string v0.0.0 (/Users/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/utils/string)
   Compiling codex-execpolicy v0.0.0 (/Users/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/execpolicy)
   Compiling codex-network-proxy v0.0.0 (/Users/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/network-proxy)
   Compiling icu_decimal v2.2.0
   Compiling event-listener v5.4.1
   Compiling strum v0.27.2
   Compiling sqlx-sqlite v0.9.0
   Compiling codex-utils-image v0.0.0 (/Users/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/utils/image)
   Compiling codex-http-client v0.0.0 (/Users/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/http-client)
   Compiling serde_with v3.17.0
   Compiling gix-command v0.8.0
   Compiling chardetng v0.1.17
   Compiling codex-extension-items v0.0.0 (/Users/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/ext/items)
   Compiling codex-utils-redacted-string v0.0.0 (/Users/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/utils/redacted-string)
   Compiling gix-packetline v0.21.2
   Compiling strum_macros v0.28.0
   Compiling gix-glob v0.24.0
   Compiling codex-async-utils v0.0.0 (/Users/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/async-utils)
   Compiling gix-url v0.35.2
   Compiling crossbeam-queue v0.3.12
   Compiling clru v0.6.3
   Compiling futures-intrusive v0.5.0
   Compiling quick-xml v0.41.0
   Compiling sys-locale v0.3.2
   Compiling wildmatch v2.6.1
   Compiling sqlx-macros-core v0.9.0
   Compiling codex-protocol v0.0.0 (/Users/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/protocol)
   Compiling gix-pack v0.68.0
   Compiling gix-transport v0.55.1
   Compiling arc-swap v1.9.0
   Compiling filedescriptor v0.8.3
   Compiling gix-revision v0.43.0
   Compiling gix-shallow v0.10.0
   Compiling gix-config-value v0.17.1
   Compiling atoi v2.0.0
   Compiling serial2 v0.2.33
   Compiling maybe-async v0.2.10
   Compiling downcast-rs v1.2.1
   Compiling unicode-bom v2.0.3
   Compiling gix-config v0.54.0
   Compiling portable-pty v0.9.0
   Compiling gix-protocol v0.59.0
   Compiling gix-refspec v0.39.0
   Compiling gix-odb v0.78.0
   Compiling curve25519-dalek v4.1.3
   Compiling sqlx-macros v0.9.0
   Compiling gix-discover v0.49.0
   Compiling gix-traverse v0.55.0
   Compiling gix-diff v0.61.0
   Compiling gix v0.81.0
   Compiling sqlx v0.9.0
   Compiling codex-file-system v0.0.0 (/Users/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/file-system)
   Compiling ed25519-dalek v2.2.0
   Compiling codex-utils-pty v0.0.0 (/Users/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/utils/pty)
   Compiling similar v2.7.0
   Compiling codex-git-utils v0.0.0 (/Users/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/git-utils)
   Compiling codex-history v0.0.0 (/Users/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/history)
   Compiling codex-hepta-types v0.0.0 (/Users/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/hepta-types)
   Compiling codex-state v0.0.0 (/Users/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/state)
   Compiling codex-hepta-authbus v0.0.0 (/Users/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/hepta-authbus)
error[E0432]: unresolved import `crate::AuthBusAuthorityStore`
  --> hepta-authbus/src/host.rs:20:5
   |
20 | use crate::AuthBusAuthorityStore;
   |     ^^^^^^^^^^^^^^^^^^^^^^^^^^^^ no `AuthBusAuthorityStore` in the root
   |
help: a similar name exists in the module
   |
20 - use crate::AuthBusAuthorityStore;
20 + use crate::AuthBusAuthorityError;
   |
help: consider importing this struct instead
   |
20 | use crate::authority_store::AuthBusAuthorityStore;
   |            +++++++++++++++++

error[E0432]: unresolved import `crate::AuthBusAuthorityStore`
 --> hepta-authbus/src/quota_store.rs:9:5
  |
9 | use crate::AuthBusAuthorityStore;
  |     ^^^^^^^^^^^^^^^^^^^^^^^^^^^^ no `AuthBusAuthorityStore` in the root
  |
help: a similar name exists in the module
  |
9 - use crate::AuthBusAuthorityStore;
9 + use crate::AuthBusAuthorityError;
  |
help: consider importing this struct instead
  |
9 | use crate::authority_store::AuthBusAuthorityStore;
  |            +++++++++++++++++

error[E0432]: unresolved import `crate::AuthBusAuthorityStore`
 --> hepta-authbus/src/recovery.rs:6:5
  |
6 | use crate::AuthBusAuthorityStore;
  |     ^^^^^^^^^^^^^^^^^^^^^^^^^^^^ no `AuthBusAuthorityStore` in the root
  |
help: a similar name exists in the module
  |
6 - use crate::AuthBusAuthorityStore;
6 + use crate::AuthBusAuthorityError;
  |
help: consider importing this struct instead
  |
6 | use crate::authority_store::AuthBusAuthorityStore;
  |            +++++++++++++++++

error[E0432]: unresolved import `crate::AuthBusAuthorityStore`
 --> hepta-authbus/src/settlement_store.rs:8:5
  |
8 | use crate::AuthBusAuthorityStore;
  |     ^^^^^^^^^^^^^^^^^^^^^^^^^^^^ no `AuthBusAuthorityStore` in the root
  |
help: a similar name exists in the module
  |
8 - use crate::AuthBusAuthorityStore;
8 + use crate::AuthBusAuthorityError;
  |
help: consider importing this struct instead
  |
8 | use crate::authority_store::AuthBusAuthorityStore;
  |            +++++++++++++++++

error[E0432]: unresolved import `crate::SettlementIssuerRegistration`
  --> hepta-authbus/src/settlement_store.rs:15:5
   |
15 | use crate::SettlementIssuerRegistration;
   |     ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^ no `SettlementIssuerRegistration` in the root
   |
help: consider importing this struct instead
   |
15 | use crate::settlement::SettlementIssuerRegistration;
   |            ++++++++++++

error[E0432]: unresolved import `crate::AuthBusAuthorityStore`
  --> hepta-authbus/src/trust_store.rs:10:5
   |
10 | use crate::AuthBusAuthorityStore;
   |     ^^^^^^^^^^^^^^^^^^^^^^^^^^^^ no `AuthBusAuthorityStore` in the root
   |
help: a similar name exists in the module
   |
10 - use crate::AuthBusAuthorityStore;
10 + use crate::AuthBusAuthorityError;
   |
help: consider importing this struct instead
   |
10 | use crate::authority_store::AuthBusAuthorityStore;
   |            +++++++++++++++++

For more information about this error, try `rustc --explain E0432`.
error: could not compile `codex-hepta-authbus` (lib) due to 6 previous errors
warning: build failed, waiting for other jobs to finish...
```

## authbus-bao tail

```text
   Compiling zeroize v1.8.2
   Compiling smallvec v1.15.1
   Compiling tracing-core v0.1.36
   Compiling aws-lc-rs v1.16.2
   Compiling rustls-pki-types v1.14.0
   Compiling tracing v0.1.44
   Compiling futures-util v0.3.32
   Compiling icu_normalizer v2.2.0
   Compiling rustls v0.23.43
   Compiling idna_adapter v1.2.1
   Compiling rustls-webpki v0.103.13
   Compiling idna v1.1.0
   Compiling security-framework-sys v2.15.0
   Compiling core-foundation v0.9.4
   Compiling rustix v1.1.4
   Compiling url v2.5.8
   Compiling tokio-util v0.7.18
   Compiling der v0.7.10
   Compiling h2 v0.4.16
   Compiling system-configuration-sys v0.6.0
   Compiling parking_lot_core v0.9.12
   Compiling tempfile v3.27.0
   Compiling sqlx-core v0.9.0
   Compiling hyper v1.8.1
   Compiling parking_lot v0.12.5
   Compiling system-configuration v0.7.0
   Compiling spki v0.7.3
   Compiling security-framework v2.11.1
   Compiling core-foundation v0.10.1
   Compiling socket2 v0.5.10
   Compiling hyper-util v0.1.20
   Compiling native-tls v0.2.14
   Compiling security-framework v3.5.1
   Compiling sqlx-sqlite v0.9.0
   Compiling pkcs8 v0.10.2
   Compiling futures-intrusive v0.5.0
   Compiling webpki-roots v1.0.9
   Compiling ed25519 v2.2.3
   Compiling publicsuffix v2.3.0
   Compiling tower v0.5.3
   Compiling sqlx-macros-core v0.9.0
   Compiling curve25519-dalek v4.1.3
   Compiling rustls-native-certs v0.8.3
   Compiling tokio-native-tls v0.3.1
   Compiling tokio-rustls v0.26.4
   Compiling flume v0.12.0
   Compiling futures-executor v0.3.32
   Compiling tower-http v0.6.8
   Compiling serde_urlencoded v0.7.1
   Compiling tracing-subscriber v0.3.22
   Compiling hyper-tls v0.6.0
   Compiling hyper-rustls v0.27.7
   Compiling cookie_store v0.22.1
   Compiling sqlx-macros v0.9.0
   Compiling ed25519-dalek v2.2.0
   Compiling opentelemetry v0.31.0
   Compiling tracing-log v0.2.0
   Compiling reqwest v0.12.28
   Compiling tracing-opentelemetry v0.32.1
   Compiling sqlx v0.9.0
   Compiling codex-utils-rustls-provider v0.0.0 (/Users/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/utils/rustls-provider)
   Compiling futures v0.3.31
   Compiling rcgen v0.14.7
   Compiling codex-hepta-authbus v0.0.0 (/Users/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/hepta-authbus)
error[E0432]: unresolved import `crate::AuthBusAuthorityStore`
  --> hepta-authbus/src/host.rs:20:5
   |
20 | use crate::AuthBusAuthorityStore;
   |     ^^^^^^^^^^^^^^^^^^^^^^^^^^^^ no `AuthBusAuthorityStore` in the root
   |
help: a similar name exists in the module
   |
20 - use crate::AuthBusAuthorityStore;
20 + use crate::AuthBusAuthorityError;
   |
help: consider importing this struct instead
   |
20 | use crate::authority_store::AuthBusAuthorityStore;
   |            +++++++++++++++++

error[E0432]: unresolved import `crate::AuthBusAuthorityStore`
 --> hepta-authbus/src/quota_store.rs:9:5
  |
9 | use crate::AuthBusAuthorityStore;
  |     ^^^^^^^^^^^^^^^^^^^^^^^^^^^^ no `AuthBusAuthorityStore` in the root
  |
help: a similar name exists in the module
  |
9 - use crate::AuthBusAuthorityStore;
9 + use crate::AuthBusAuthorityError;
  |
help: consider importing this struct instead
  |
9 | use crate::authority_store::AuthBusAuthorityStore;
  |            +++++++++++++++++

error[E0432]: unresolved import `crate::AuthBusAuthorityStore`
 --> hepta-authbus/src/recovery.rs:6:5
  |
6 | use crate::AuthBusAuthorityStore;
  |     ^^^^^^^^^^^^^^^^^^^^^^^^^^^^ no `AuthBusAuthorityStore` in the root
  |
help: a similar name exists in the module
  |
6 - use crate::AuthBusAuthorityStore;
6 + use crate::AuthBusAuthorityError;
  |
help: consider importing this struct instead
  |
6 | use crate::authority_store::AuthBusAuthorityStore;
  |            +++++++++++++++++

error[E0432]: unresolved import `crate::AuthBusAuthorityStore`
 --> hepta-authbus/src/settlement_store.rs:8:5
  |
8 | use crate::AuthBusAuthorityStore;
  |     ^^^^^^^^^^^^^^^^^^^^^^^^^^^^ no `AuthBusAuthorityStore` in the root
  |
help: a similar name exists in the module
  |
8 - use crate::AuthBusAuthorityStore;
8 + use crate::AuthBusAuthorityError;
  |
help: consider importing this struct instead
  |
8 | use crate::authority_store::AuthBusAuthorityStore;
  |            +++++++++++++++++

error[E0432]: unresolved import `crate::SettlementIssuerRegistration`
  --> hepta-authbus/src/settlement_store.rs:15:5
   |
15 | use crate::SettlementIssuerRegistration;
   |     ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^ no `SettlementIssuerRegistration` in the root
   |
help: consider importing this struct instead
   |
15 | use crate::settlement::SettlementIssuerRegistration;
   |            ++++++++++++

error[E0432]: unresolved import `crate::AuthBusAuthorityStore`
  --> hepta-authbus/src/trust_store.rs:10:5
   |
10 | use crate::AuthBusAuthorityStore;
   |     ^^^^^^^^^^^^^^^^^^^^^^^^^^^^ no `AuthBusAuthorityStore` in the root
   |
help: a similar name exists in the module
   |
10 - use crate::AuthBusAuthorityStore;
10 + use crate::AuthBusAuthorityError;
   |
help: consider importing this struct instead
   |
10 | use crate::authority_store::AuthBusAuthorityStore;
   |            +++++++++++++++++

For more information about this error, try `rustc --explain E0432`.
error: could not compile `codex-hepta-authbus` (lib) due to 6 previous errors
warning: build failed, waiting for other jobs to finish...
```

## authbus-agentd tail

```text
    Checking sentry v0.46.1
    Checking codex-collaboration-mode-templates v0.0.0 (/Users/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/collaboration-mode-templates)
    Checking codex-models-manager v0.0.0 (/Users/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/models-manager)
    Checking codex-feedback v0.0.0 (/Users/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/feedback)
    Checking codex-aws-auth v0.0.0 (/Users/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/aws-auth)
    Checking codex-response-debug-context v0.0.0 (/Users/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/response-debug-context)
    Checking codex-model-provider v0.0.0 (/Users/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/model-provider)
    Checking codex-connectors v0.0.0 (/Users/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/connectors)
    Checking codex-code-mode v0.0.0 (/Users/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/code-mode)
    Checking codex-rmcp-client v0.0.0 (/Users/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/rmcp-client)
    Checking codex-exec-server-test-support v0.0.0 (/Users/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/exec-server/tests/support)
    Checking num-complex v0.4.6
    Checking codex-diagnostics v0.0.0 (/Users/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/diagnostics)
    Checking jsonptr v0.7.1
    Checking predicates-core v1.0.9
    Checking codex-tools v0.0.0 (/Users/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/tools)
    Checking codex-mcp v0.0.0 (/Users/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/codex-mcp)
    Checking symphonia-core v0.6.0
    Checking nucleo-matcher v0.3.1 (https://github.com/helix-editor/nucleo.git?rev=4253de9faabb4e5c6d81d946a5e35a90f87347ee#4253de9f)
    Checking rayon v1.11.0
    Checking difflib v0.4.0
    Checking termtree v0.5.1
   Compiling assert_cmd v2.1.2
    Checking predicates-tree v1.0.12
    Checking predicates v3.1.3
    Checking nucleo v0.5.0 (https://github.com/helix-editor/nucleo.git?rev=4253de9faabb4e5c6d81d946a5e35a90f87347ee#4253de9f)
    Checking codex-context-fragments v0.0.0 (/Users/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/context-fragments)
    Checking ignore v0.4.25
    Checking wait-timeout v0.2.1
    Checking codex-file-search v0.0.0 (/Users/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/file-search)
    Checking symphonia-metadata v0.6.0
    Checking runfiles v0.1.0 (https://github.com/dzbarsky/rules_rust?rev=b56cbaa8465e74127f1ea216f813cd377295ad81#b56cbaa8)
    Checking codex-utils-cargo-bin v0.0.0 (/Users/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/utils/cargo-bin)
    Checking codex-rollout v0.0.0 (/Users/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/rollout)
    Checking codex-extension-api v0.0.0 (/Users/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/ext/extension-api)
   Compiling lzma-sys v0.1.20
   Compiling bzip2-sys v0.1.13+1.0.8
   Compiling codex-experimental-api-macros v0.0.0 (/Users/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/codex-experimental-api-macros)
   Compiling codex-app-server-protocol-noop-macros v0.0.0 (/Users/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/app-server-protocol-noop-macros)
    Checking symphonia-common v0.6.0
   Compiling darling_core v0.20.11
    Checking codex-app-server-protocol v0.0.0 (/Users/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/app-server-protocol)
   Compiling include_dir_macros v0.7.4
   Compiling codex-skills v0.0.0 (/Users/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/skills)
    Checking unsafe-libyaml v0.2.11
    Checking serde_yaml v0.9.34+deprecated
    Checking include_dir v0.7.4
   Compiling darling_macro v0.20.11
   Compiling zip v2.4.2
    Checking bzip2 v0.5.2
    Checking xz2 v0.1.7
   Compiling darling v0.20.11
    Checking zopfli v0.8.3
    Checking lzma-rs v0.3.0
   Compiling stop-words v0.9.0
    Checking filetime v0.2.27
   Compiling pulldown-cmark v0.10.3
    Checking extended v0.1.0
    Checking deflate64 v0.1.10
    Checking symphonia-format-riff v0.6.0
    Checking tar v0.4.45
   Compiling cached_proc_macro v0.25.0
    Checking symphonia-format-ogg v0.6.0
    Checking symphonia-format-mkv v0.6.0
    Checking symphonia-format-isomp4 v0.6.0
    Checking symphonia-bundle-mp3 v0.6.0
    Checking codex-hooks v0.0.0 (/Users/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/hooks)
    Checking cached_proc_macro_types v0.1.1
    Checking web-time v1.1.0
    Checking cached v0.56.0
    Checking symphonia v0.6.0
    Checking codex-apply-patch v0.0.0 (/Users/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/apply-patch)
    Checking codex-shell-escalation v0.0.0 (/Users/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/shell-escalation)
    Checking rust-stemmers v1.2.0
    Checking deunicode v1.6.2
    Checking bm25 v2.3.2
    Checking codex-utils-audio v0.0.0 (/Users/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/utils/audio)
    Checking codex-prompts v0.0.0 (/Users/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/prompts)
    Checking codex-rollout-trace v0.0.0 (/Users/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/rollout-trace)
    Checking codex-agent-graph-store v0.0.0 (/Users/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/agent-graph-store)
    Checking codex-memories-read v0.0.0 (/Users/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/memories/read)
    Checking whoami v1.6.1
    Checking codex-utils-stream-parser v0.0.0 (/Users/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/utils/stream-parser)
    Checking codex-hepta-cognitive-types v0.0.0 (/Users/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/hepta-cognitive-types)
    Checking codex-analytics v0.0.0 (/Users/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/analytics)
    Checking codex-thread-store v0.0.0 (/Users/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/thread-store)
    Checking codex-core-plugins v0.0.0 (/Users/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/core-plugins)
    Checking codex-skills-extension v0.0.0 (/Users/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/ext/skills)
    Checking codex-hepta-memory-retrieval v0.0.0 (/Users/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/hepta-memory-retrieval)
    Checking codex-hepta-prompt-registry v0.0.0 (/Users/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/hepta-prompt-registry)
    Checking codex-core v0.0.0 (/Users/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/core)
    Checking codex-hepta-paths v0.0.0 (/Users/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/hepta-paths)
    Checking codex-hepta-kg v0.0.0 (/Users/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/hepta-kg)
    Checking codex-hepta-operations v0.0.0 (/Users/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/hepta-operations)
    Checking codex-backend-openapi-models v0.0.0 (/Users/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/codex-backend-openapi-models)
    Checking codex-backend-client v0.0.0 (/Users/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/backend-client)
    Checking codex-hepta-cognitive-read v0.0.0 (/Users/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/hepta-cognitive-read)
    Checking is_ci v1.2.0
    Checking codex-hepta-memory-federation v0.0.0 (/Users/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/hepta-memory-federation)
    Checking is-terminal v0.4.17
   Compiling owo-colors v4.3.0
   Compiling codex-linux-sandbox v0.0.0 (/Users/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/linux-sandbox)
    Checking supports-color v2.1.0
    Checking codex-hepta-memory v0.0.0 (/Users/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/hepta-memory)
    Checking supports-color v3.0.2
    Checking codex-hepta-authbus v0.0.0 (/Users/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/hepta-authbus)
error[E0432]: unresolved import `crate::AuthBusAuthorityStore`
  --> hepta-authbus/src/host.rs:20:5
   |
20 | use crate::AuthBusAuthorityStore;
   |     ^^^^^^^^^^^^^^^^^^^^^^^^^^^^ no `AuthBusAuthorityStore` in the root
   |
help: a similar name exists in the module
   |
20 - use crate::AuthBusAuthorityStore;
20 + use crate::AuthBusAuthorityError;
   |
help: consider importing this struct instead
   |
20 | use crate::authority_store::AuthBusAuthorityStore;
   |            +++++++++++++++++

error[E0432]: unresolved import `crate::AuthBusAuthorityStore`
 --> hepta-authbus/src/quota_store.rs:9:5
  |
9 | use crate::AuthBusAuthorityStore;
  |     ^^^^^^^^^^^^^^^^^^^^^^^^^^^^ no `AuthBusAuthorityStore` in the root
  |
help: a similar name exists in the module
  |
9 - use crate::AuthBusAuthorityStore;
9 + use crate::AuthBusAuthorityError;
  |
help: consider importing this struct instead
  |
9 | use crate::authority_store::AuthBusAuthorityStore;
  |            +++++++++++++++++

error[E0432]: unresolved import `crate::AuthBusAuthorityStore`
 --> hepta-authbus/src/recovery.rs:6:5
  |
6 | use crate::AuthBusAuthorityStore;
  |     ^^^^^^^^^^^^^^^^^^^^^^^^^^^^ no `AuthBusAuthorityStore` in the root
  |
help: a similar name exists in the module
  |
6 - use crate::AuthBusAuthorityStore;
6 + use crate::AuthBusAuthorityError;
  |
help: consider importing this struct instead
  |
6 | use crate::authority_store::AuthBusAuthorityStore;
  |            +++++++++++++++++

error[E0432]: unresolved import `crate::AuthBusAuthorityStore`
 --> hepta-authbus/src/settlement_store.rs:8:5
  |
8 | use crate::AuthBusAuthorityStore;
  |     ^^^^^^^^^^^^^^^^^^^^^^^^^^^^ no `AuthBusAuthorityStore` in the root
  |
help: a similar name exists in the module
  |
8 - use crate::AuthBusAuthorityStore;
8 + use crate::AuthBusAuthorityError;
  |
help: consider importing this struct instead
  |
8 | use crate::authority_store::AuthBusAuthorityStore;
  |            +++++++++++++++++

error[E0432]: unresolved import `crate::SettlementIssuerRegistration`
  --> hepta-authbus/src/settlement_store.rs:15:5
   |
15 | use crate::SettlementIssuerRegistration;
   |     ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^ no `SettlementIssuerRegistration` in the root
   |
help: consider importing this struct instead
   |
15 | use crate::settlement::SettlementIssuerRegistration;
   |            ++++++++++++

error[E0432]: unresolved import `crate::AuthBusAuthorityStore`
  --> hepta-authbus/src/trust_store.rs:10:5
   |
10 | use crate::AuthBusAuthorityStore;
   |     ^^^^^^^^^^^^^^^^^^^^^^^^^^^^ no `AuthBusAuthorityStore` in the root
   |
help: a similar name exists in the module
   |
10 - use crate::AuthBusAuthorityStore;
10 + use crate::AuthBusAuthorityError;
   |
help: consider importing this struct instead
   |
10 | use crate::authority_store::AuthBusAuthorityStore;
   |            +++++++++++++++++

For more information about this error, try `rustc --explain E0432`.
error: could not compile `codex-hepta-authbus` (lib) due to 6 previous errors
warning: build failed, waiting for other jobs to finish...
```

## authbus-api-inventory tail

```text
test-support enabled by production dependency: /Users/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/hepta-authbus/Cargo.toml
```

## authbus-clippy tail

```text
    = note: prefixed identifiers and literals are reserved since Rust 2021
help: consider inserting whitespace here
    |
218 |         .expect("expire after dispatch ");
    |                                       +

error: prefix `snapshot` is unknown
   --> hepta-authbus/src/settlement_store_tests.rs:223:24
    |
223 |         .expect("quota snapshot");
    |                        ^^^^^^^^ unknown prefix
    |
    = note: prefixed identifiers and literals are reserved since Rust 2021
help: consider inserting whitespace here
    |
223 |         .expect("quota snapshot ");
    |                                +

error: prefix `settlement` is unknown
   --> hepta-authbus/src/settlement_store_tests.rs:231:32
    |
231 |         .expect("late terminal settlement");
    |                                ^^^^^^^^^^ unknown prefix
    |
    = note: prefixed identifiers and literals are reserved since Rust 2021
help: consider inserting whitespace here
    |
231 |         .expect("late terminal settlement ");
    |                                          +

error: prefix `snapshot` is unknown
   --> hepta-authbus/src/settlement_store_tests.rs:235:24
    |
235 |         .expect("quota snapshot");
    |                        ^^^^^^^^ unknown prefix
    |
    = note: prefixed identifiers and literals are reserved since Rust 2021
help: consider inserting whitespace here
    |
235 |         .expect("quota snapshot ");
    |                                +

error: prefix `policy` is unknown
   --> hepta-authbus/src/settlement_store_tests.rs:252:25
    |
252 |         .expect("revoke policy");
    |                         ^^^^^^ unknown prefix
    |
    = note: prefixed identifiers and literals are reserved since Rust 2021
help: consider inserting whitespace here
    |
252 |         .expect("revoke policy ");
    |                               +

error: prefix `expiry` is unknown
   --> hepta-authbus/src/settlement_store_tests.rs:271:38
    |
271 |         .expect("refund undispatched expiry");
    |                                      ^^^^^^ unknown prefix
    |
    = note: prefixed identifiers and literals are reserved since Rust 2021
help: consider inserting whitespace here
    |
271 |         .expect("refund undispatched expiry ");
    |                                            +

error: prefix `snapshot` is unknown
   --> hepta-authbus/src/settlement_store_tests.rs:276:24
    |
276 |         .expect("quota snapshot");
    |                        ^^^^^^^^ unknown prefix
    |
    = note: prefixed identifiers and literals are reserved since Rust 2021
help: consider inserting whitespace here
    |
276 |         .expect("quota snapshot ");
    |                                +

error: prefix `reservation` is unknown
   --> hepta-authbus/src/settlement_store_tests.rs:293:30
    |
293 |         .expect("cancel held reservation");
    |                              ^^^^^^^^^^^ unknown prefix
    |
    = note: prefixed identifiers and literals are reserved since Rust 2021
help: consider inserting whitespace here
    |
293 |         .expect("cancel held reservation ");
    |                                         +

error: prefix `snapshot` is unknown
   --> hepta-authbus/src/settlement_store_tests.rs:298:24
    |
298 |         .expect("quota snapshot");
    |                        ^^^^^^^^ unknown prefix
    |
    = note: prefixed identifiers and literals are reserved since Rust 2021
help: consider inserting whitespace here
    |
298 |         .expect("quota snapshot ");
    |                                +

error: prefix `retry` is unknown
   --> hepta-authbus/src/settlement_store_tests.rs:311:29
    |
311 |             .expect("cancel retry"),
    |                             ^^^^^ unknown prefix
    |
    = note: prefixed identifiers and literals are reserved since Rust 2021
help: consider inserting whitespace here
    |
311 |             .expect("cancel retry "),
    |                                  +

error: character literal may only contain one codepoint
   --> hepta-authbus/src/settlement_store_tests.rs:320:55
    |
320 |         "UPDATE authbus_quota_reservation SET state = 'settled'
    |                                                       ^^^^^^^^^
    |
help: if you meant to write a string literal, use double quotes
    |
320 -         "UPDATE authbus_quota_reservation SET state = 'settled'
320 +         "UPDATE authbus_quota_reservation SET state = "settled"
    |

error: prefix `accepted` is unknown
   --> hepta-authbus/src/settlement_store_tests.rs:326:62
    |
326 |     assert!(illegal.is_err(), "direct illegal state jump was accepted");
    |                                                              ^^^^^^^^ unknown prefix
    |
    = note: prefixed identifiers and literals are reserved since Rust 2021
help: consider inserting whitespace here
    |
326 |     assert!(illegal.is_err(), "direct illegal state jump was accepted ");
    |                                                                      +

error: prefix `accepted` is unknown
   --> hepta-authbus/src/settlement_store_tests.rs:332:62
    |
332 |     assert!(deleted.is_err(), "live reservation deletion was accepted");
    |                                                              ^^^^^^^^ unknown prefix
    |
    = note: prefixed identifiers and literals are reserved since Rust 2021
help: consider inserting whitespace here
    |
332 |     assert!(deleted.is_err(), "live reservation deletion was accepted ");
    |                                                                      +

error: prefix `dispatch` is unknown
   --> hepta-authbus/src/settlement_store_tests.rs:346:23
    |
346 |         .expect("mark dispatch");
    |                       ^^^^^^^^ unknown prefix
    |
    = note: prefixed identifiers and literals are reserved since Rust 2021
help: consider inserting whitespace here
    |
346 |         .expect("mark dispatch ");
    |                               +

error: prefix `retry` is unknown
   --> hepta-authbus/src/settlement_store_tests.rs:374:33
    |
374 |         .expect("archived exact retry");
    |                                 ^^^^^ unknown prefix
    |
    = note: prefixed identifiers and literals are reserved since Rust 2021
help: consider inserting whitespace here
    |
374 |         .expect("archived exact retry ");
    |                                      +

error: prefix `snapshot` is unknown
   --> hepta-authbus/src/settlement_store_tests.rs:379:24
    |
379 |         .expect("quota snapshot");
    |                        ^^^^^^^^ unknown prefix
    |
    = note: prefixed identifiers and literals are reserved since Rust 2021
help: consider inserting whitespace here
    |
379 |         .expect("quota snapshot ");
    |                                +

error[E0765]: unterminated double quote string
   --> hepta-authbus/src/settlement_store_tests.rs:379:32
    |
379 |           .expect("quota snapshot");
    |  ________________________________^
380 | |     assert_eq!((quota.available, quota.reserved, quota.consumed), (5, 0, 5));
381 | | }
    | |__^

For more information about this error, try `rustc --explain E0765`.
error: could not compile `codex-hepta-authbus` (lib test) due to 29 previous errors
warning: build failed, waiting for other jobs to finish...
For more information about this error, try `rustc --explain E0432`.
error: could not compile `codex-hepta-authbus` (lib) due to 6 previous errors
```
