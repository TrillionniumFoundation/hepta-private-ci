# Shared Stem: single-owner durable pre-effect fence (shadow qualification)

This PR adds **actual fsync-backed execution admission** to the existing
`codex_hepta_infer_core::durable_control::DurableInferenceControl` rather than
inventing a second persistent writer or an unaudited digest-only ledger.

**Not production acceptance:** no Jina weights, native Artifact CAS, signed
output receipt, independently pinned host trust, NDU adjudication, or target
machine performance is claimed. Draft and `DENY_ALL` remain required.

## Control owner's durable state transition

Existing canonical inference.control caller sequence:

```text
Submit(request + Principal + model/payload/semantic digest)
  → Reserve(lease / quota / authority epoch)
  → Assign(actual Worker ID / Generation / signed request-binding digest)
  → BeginEffect(exact signed Final-use binding digest) [append + fsync]
  → Validate and consume independently verified Final-use token
  → Call actual already-loaded NeuronFeatureDriver
  → Observe terminal and settle using independently measured resources
  → CAS-commit successor state and checkpoint with trusted owner
```

`begin_effect` adds a backward-compatible `effect-v1` journal event to the
**existing** single-writer WAL. The `RequestRecord.effect_binding_digest`
is `None` for all historical records, `Some(digest)` once the irreversible
effect *might* happen. The state remains `Assigned` rather than pretending
completion. A second begin attempt is **always rejected**, even with identical
bytes. Reopening on a different process preserves the marker; a missing
post-crash acknowledgement requires external reconciliation, not a second
native Worker run. No historical event or replay format is rewritten.

The signed Worker
`run_verified_stem_feature_durably_v1(control, authority, token, ...)`
verifies the **actual** current control owner record against the complete
request/Principal, model and payload digest, resource semantic digest,
reservation ID, quota, authority epoch, deadline and current Worker
ID/Generation and its exact request/assignment digest. It then calls
`begin_effect` before consuming the signed token or executing the real
Driver. Rejected or conflicting inputs do not append. Uncertain I/O poisons
the control writer by its existing `append` invariant.

For a successful native Head call, the returned
`BoundStemFeatureExecutionV1` is a **typed observed Worker result, not a
committed Checkpoint CAS**, and the durable request intentionally remains
`Assigned` with a one-shot effect marker. The external owner must verify the
actual signed artifact, actual token/usage and terminal evidence and call
`settle` under the current revision, then independently CAS-commit the
correct Neuron successor. No producer may substitute invented zero usage,
manufacture a terminal observation, or silently free a request slot.

This WAL marker is necessary but insufficient: a local verified effect may
have been sent even if a subsequently revoked token fails; the journal must
remain reconcile-only. A held-out comparison or research score is never
production authorization.

## Tests / falsification

Rust qualification tests cover:

- Native owner single-writer lock, fsync replay and exact revision
- Matching authenticated-at-effect signed Final-use → real mock Driver
- Crash/restart after an effect → marker persisted, **no second dispatch**
- Invalid Scope/Principal/assignment → no WAL append and no execution
- Revocation after claim but before effect → denied and durable reconcile-only
- Inference.control legacy replay and settlement semantics remain unchanged

```sh
cd codex-rs
cargo +1.95.0 fmt --all -- --check
cargo +1.95.0 test --locked -p codex-hepta-infer-core --lib
cargo +1.95.0 test --locked -p codex-hepta-infer-worker-host --lib model_worker::tests::
cargo +1.95.0 clippy --locked -p codex-hepta-infer-core -p codex-hepta-infer-worker-host --all-targets -- -D warnings
```

The full existing Worker/App Server E2E and global Blocking CI are **also**
required on the exact final combined SHA; green shadow tests are not
equivalent to a production signed Artifact CAS, independent NDU, unclean
crash recovery or a measured 4096 Cell host. Final approval is external.
