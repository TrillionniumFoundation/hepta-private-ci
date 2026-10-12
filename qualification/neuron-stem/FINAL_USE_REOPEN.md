# Shared Stem Final-use claim persistence — shadow qualification

**Scope:** a local, protected, journal-backed Final-use verifier reopens and
refuses a previously claimed signed grant. This experiment is stacked on the
signed Worker PR #1517, not activated on production.

## Exactly what is exercised

The native `model_worker_tests.rs` fixture constructs a properly signed
Ed25519 `FinalUseGrant` over an actual bounded `StemFeatureRefV1` and
`WorkerRequest`. The test calls the verifier's real `claim` method, which
must persist the one-use Nonce *before* permitting an effect. It verifies:

- a claimed signed grant dispatches through the native Worker Driver and
  returns its typed scoped receipt with `DENY_ALL` authority;
- after the signed effect and the original verifier are closed, another
  verifier reading the **same protected directory** refuses the old signed
  grant as `AlreadyClaimed`;
- a signed grant that was claimed but never entered into the Worker remains
  consumed after clean verifier reopen, preventing an abandoned token from
  being used to reissue work.

The fixture uses a non-production Ed25519 key with the same pinned verifying
key and state directory on reopen. The same public-key record and durable Nonce
journal are real components; no mock ledger or fresh ephemeral cache is used
for the replay verdict.

## Explicit non-claims

This is a **clean, cooperative owner close/reopen test**, not process-kill,
power failure, lost ACK, disk corruption, time rollback, cross-machine
anti-rollback verification, target-machine performance, online NDU or
production source artifact attestation. Using the compatibility
`FinalUseAuthority::open_state_dir` constructor does not supply the
production `AuthorityClock` and protected external `AuthorityFrontierStore`.
The model driver still uses a deterministic test fixture, **not actual Jina
weights**. No output, policy, Cell Head or model is promoted by this test.

## Verification

```sh
cd codex-rs
cargo +1.95.0 fmt --all -- --check
cargo +1.95.0 test --locked -p codex-hepta-infer-worker-host --lib model_worker::tests:: -- --nocapture
cargo +1.95.0 clippy --locked -p codex-hepta-infer-core -p codex-hepta-infer-worker-host --all-targets -- -D warnings
```

The stacked workflow also runs the actual App Server/Agentd integration and
transitive-owner replay tests; do not claim the full global CI is green based
on the focused native contract alone.

**Next dependency:** protected issuer and revocation clock/frontier, then
real CAS model loading and full worker-ledger transaction ID reconciliation
under SIGKILL, duplicate, lost-ack, rollback and generation rollover fault
injection. Finally, real frozen Jina weight/Head learning and 64–4096 Cell
hardware measurements must pass before any production promotion.
