# Matrix SDK 0.19 compatibility qualification

## Source lineage

This change is stacked on `74b933d71ee4464245c0e31eb12556b0344a0218`
(`codex/channel-matrix-adversarial-audit-20261001`). That candidate contains
31 Matrix source/test files with fixes absent from main at inspection time,
including durable terminal recovery, outbox uncertainty, active-redaction
quarantine and startup lifecycle denial. They are retained, not reconstructed.
Main inspected: `c6f90d48c40f7b5267db587bb3c3f4934f1414a8`.
A local integration commit `76adcc6e4` preserved an exploratory main/candidate
merge; it is not this PR's base and neither source branch was moved.

The upgrade resolves to Matrix SDK/crypto/SQLite **0.19.1**, the published
compatible patch release. RUSTSEC-2026-0318 requires crypto >=0.19.0. No waiver
is added for it. Rust/Cargo/Bazel/CI move together to **1.96.0**.

## Reviewed dependency adaptations

- Unmodified upstream Matrix SQLite0.19.1 uses rusqlite0.40.2 and native
  libsqlite3-sys0.38.2 (bundled SQLite3.53.2). SQLx0.9's manifest range is patched
  to that exact native version; its implementation is unchanged. This moves
  forward from SQLite3.51.3, preserving the WAL-reset fix rather than reverting
  the existing SQLx0.9 alignment. The workspace direct native dependency matches.
- Starlark0.14.2's exact BLAKE3 pin moves1.8.2→1.8.7 because upstream Matrix
  store encryption requires1.8.7. No interpreter/authorization source changes.
- Matrix's only source patch replaces unmaintained anymap2 with anymap3 1.1.0
  in event-handler context storage. Native Clone+Send+Sync and Wasm Clone
  contracts remain intact. Crypto, authentication, storage and transport
  source are upstream bytes. See each vendor directory's HEPTA_PATCH.md.
- imbl7.0.2 and imbl-sized-chunks0.2.0 remove the old bitmap dependency path.
  The obsolete0247 exception is removed from both deny/audit policy files.
- Rustls minimum0.23.45 fixes the additionally detected0285 advisory.
  The SDK explicitly enables its rustls-aws-lc-rs feature: reqwest0.13 otherwise
  panics during client construction when no process-wide provider was installed.

Official registry archive hashes are recorded in `vendor-provenance.json`.
Vendored changes are mechanical except the small event-handler type aliases.
Old vendor sources remain in repository history; no live database is opened.

## Persistence and rollback

SDK0.19 changes derived Event Cache event-ID/token encoding and resets its
contents; media storage is now separate. The SDK `sqlite` feature enables state,
event-cache and media stores. Treat cache rehydration as necessary, never as
permission to delete Hepta's authoritative inbox/outbox, checkpoints, bindings,
uncertainty, quarantine or recovery records. The upgrade must preserve the
existing sender/room/generation and lifecycle authority boundaries.

Before installed-host rollout, stop the paired processes and back up the entire
paired state using the established procedure. Do not run the older SDK against
upgraded files. Rollback requires the matching pre-upgrade paired binaries and
state backup; copying only the derived cache is not a valid rollback.
This PR does not authorize deployment or live migration.

## Test boundaries

- `crypto_advisory`: real OlmMachine instances and signed device keys exercise
  both affected custom-to-device APIs with a recipient lacking cross-signing.
- `event_handler_context`: real SDK sync processing checks replacement of
  same-type context, isolation of distinct types and clone-based extraction.
- `sdk_store_upgrade`: a synthetic0.18 schema14 cache migrates through the
  actual0.19 SQLite backend, closes, reopens and passes SQLite integrity check.
- Existing SDK/store/protocol/daemon tests cover checkpoint replay, gaps,
  tombstones, restart recovery, isolation and unchanged authorization.
- State and execpolicy regressions cover the shared SQLite/BLAKE3 adaptations.
- `crypto-migration-qualification`: a separately locked real0.18 generator
  writes encrypted account/cross-signing keys, a Megolm session/ciphertext,
  pending gossip and a sliding-sync position.0.19 must preserve keys/decryption
  and gossip state through schema17→19 and a second reopen while clearing only
  the intended sliding-sync position and preserving an actual Hepta checkpoint.
  This is a required hosted gate; the legacy producer is intentionally isolated
  from the production dependency graph, has no networking calls and is never
  run against a supplied or live database.
- `synapse-sdk-qualification`: a separate pinned disposable Synapse on loopback
  exercises encrypted wire content, real send/sync and SQLite-session reopen.
  It does not certify dual-agent/paired-host process or crash acceptance.

The existing `real-synapse-e2e` paired-host runner retains every admission
check. This Linux executor's preflight exits69 because its fixed Homebrew
bootstrap profile is unavailable; Docker is also absent. That precise runner
remains an external target-host gate. The separate Linux CI lane is not a
replacement for it. No default test silently skips a requested qualification.

## Qualification status

Local focused run:344 tests passed, zero skipped, across SDK/store/protocol,
state and execpolicy. Cargo-deny advisories, bans, licenses and sources pass.
The final scoped lint and real protocol/daemon CI results are separate gates.

This is a draft. Final test/CI results and unresolved gates are recorded in the
PR. Do not equate dependency resolution, a focused pass, or an SDK protocol
pass with full installed-host acceptance.
