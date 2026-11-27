# Broker session admission has no practical count budget

## Exact owner and affected source

The current [#210](https://github.com/TrillionniumFoundation/trillionnium-os-desktop/pull/210) head is `987d0d992ad5faa522676759a508d2bbdccdf3fa`. Its `ui/broker/src/lib.rs` has Git blob `6b1da02bc04dc09a96d86eb3afa9ca999ef1f80c` and SHA-256 `bbde2c304566567b9bd12e6214bcf0d52a3f96f3dc889352e14926072617aba5`. The fetched source at [#218](https://github.com/TrillionniumFoundation/trillionnium-os-desktop/pull/218), head `37ad0cb43621ce3f47e92052972e086c24eca159`, is byte-identical. That combined owner therefore retains the same admission behavior. These live metadata and source reads are indexed in `source-index.json`.

The independently evolving [#225](https://github.com/TrillionniumFoundation/trillionnium-os-desktop/pull/225) remains at `84e2c9fb45ff88f4352853f5ed4462dd56c6a01d`; fetching this broker path at that exact head returns 404. It is an inode/storage owner, and this finding does not treat it as a broker successor or infer that its kernel work fixes the broker. This is a focused owner check, not semantic examination of every open OS PR.

## Source finding

`Broker` stores `sessions: BTreeMap<u64, SessionRecord>`. `open_session` authenticates the peer and validates the hello through the supplied authenticator, filters requested capabilities, advances `next_session` with checked arithmetic, and inserts a fresh record. It has no session-count budget, per-peer count limit, expiration or duplicate-client/nonce admission check. The integer overflow guard is correct and prevents ID wrap; it is not a useful operating memory budget.

Every successful open adds a retained map entry, even when the same valid `SameUidAuthenticator` hello and peer are used repeatedly. `close_session` removes an entry only when explicitly called with a handle belonging to the same Broker. `SessionHandle` has no Drop implementation that removes its entry; its Arc protects broker identity, not automatic session reclamation. Dropping or losing all user-held handles can therefore leave an unreachable map entry until the broker is destroyed. Existing notification/replay bounds do not bound this map.

The impact is a process-local resource exhaustion and leaked-session lifetime risk for a caller able to invoke repeated authenticated admissions without corresponding closes. A long-lived transport adapter would need a budget and reliable disconnect cleanup. Source inspection establishes this API behavior; it does not establish an internet-facing attack path or measure memory consumption.

## Current caller and authority limits

The pinned UI workspace includes the independent `trill-ui-broker` library. Its other four package manifests (`app-window`, `core`, `session`, `shell`) do not declare a broker dependency. The seven-path #210 change adds the broker library and session-identity tests, plus workspace metadata and documentation; it does not add a broker server or device dispatch binary. The concrete calls inspected here are its unit/integration tests. This bounded inspection does not assert that every repository file or external consumer was searched.

The existing five session-identity tests protect foreign handles, broker restart identity and explicit close/clone invalidation. They do not exercise session-capacity exhaustion or automatic disconnect cleanup. Same-UID authentication remains distinct from application identity, and `SubmitEffect` / `CancelEffect` remain denied. The resource finding does not demonstrate an authority bypass, production capability or actual device effect.

## Reproduction and follow-up boundary

`session_admission_repro.rs` is a diagnostic integration test against the public API. In an isolated exact-source checkout, place it under `ui/broker/tests/` and run:

```sh
cargo test --manifest-path ui/Cargo.toml --locked -p trill-ui-broker --test session_admission_repro
```

It performs 4,096 identical valid peer admissions, verifies that every handle can still submit a local-only draft, and checks that an explicit close invalidates just the closed handle. The expected result follows directly from the pinned source. **This diagnostic was not compiled or executed in this audit**, and 4,096 is a demonstration workload, not a proposed production capacity.

A future child of the existing broker owner can address bounded admission and close/disconnect capacity release while retaining broker-instance binding and all denied effect capabilities. The limit and error contract need an explicit design choice. This audit adds no production fix, changes no owner ref and enables no effect.
