# Qualification clock candidate

## Status and exact scope

This is an isolated, unformatted source candidate on tree `e253b99e0a5c3b3a680569da0d224fabff0781ba` (the 69-path source-gate result). It changes 23 paths, adds three files, and has a pre-format diff of +451/-53. The ordinary owner, original provider attempt, published source refs and native test runs were not modified. `CANDIDATE_MANIFEST.json` and `SOURCE_CAPSULE.json` identify every preimage and postimage. `audit_candidate.py` reproduced the static checks recorded in `STATIC_REVIEW.json`.

No Rust formatter, Rust compilation, Cargo test, Bazel target analysis, Bazel lock regeneration or new full-repository caller gate has run for this candidate. The two original MacIntel failures remain failures in their original evidence. This candidate is not a recovery receipt, an original-owner binding, a model result or a memory-benefit result.

## Original failures and intended behavior

The original MacIntel job `130374692350` used source `2ae5215beaf8d7b7df111a090b82134beae2683d`. Its complete raw log had 5,143,912 bytes and SHA-256 `c5948abb8d63b9bb9e66323476b3443d44c5e5305eca87053b0c82e8fc838084`.

The extension case `local_development_owner::tests::explicit_owner_expires_bound_lease_and_fences_old_witness` failed while opening its bound executor, before it reached the expiry and old-witness refusal checks. The Agentd case `runtime::tests::qualification_prepare_quarantines_expired_registry_attempt_with_h7_evidence` reported 415 ms remaining when minting `floor(real_unix_seconds) + 1`, then 476 ms elapsed at the first H7 append. That append encountered the real expired lease before the intended positive H7 sequence was complete. Repeated lines with the same PID and minted timestamp in the job summary are not additional attempts.

Both cases test live-to-expired behavior. They first require a live lease and successful owner/executor work, then require expiration and refusal. Their `+1` numeric deadline does not by itself provide one full second of wall time after minting. This candidate explicitly changes the qualification fixture to a controlled per-store clock. It retains the `+1` boundary and tests expiry at that boundary; it does not claim that the positive setup completes within a real one-second performance window. The original two-second sleep and 120 iterations of 25 ms remain in the cases. Clock advancement occurs only after all positive setup operations succeed.

## Fresh owner and lifetime boundary

`CognitiveStore::open_new_with_qualification_lease_clock` exists only under `cfg(test)` or the new explicit `qualification-lease-clock` feature. It acquires the original exclusive cognitive-store fence and requires the private cognitive directory to contain only that fence file. Existing databases, sidecars, recovery pointers and any other retained contents are refused. The constructor reuses the original SQLite initialization via the private `open_guarded` helper; it binds the clock after initialization and before returning a store, clone, lease or executor.

There is no setter for an existing store, no environment or protocol selector and no process-global or thread-local clock. The clock starts at the real Unix time observed during construction. Its controller holds a `Weak<AtomicU64>` and only permits monotonic advancement within the SQLite integer range. It does not keep the store alive. Store clones retain the same clock `Arc`; local lease and compact executor handles already retain these store clones.

Ordinary `CognitiveStore::open`, recovery construction and `from_read_only_pool` each initialize `LocalLeaseClock::Real`, including when the qualification feature is compiled. Product defaults and normal Cargo dependencies remain unchanged. The Agentd case now creates the fresh qualification store first and attaches that same `Arc` to its existing runtime state. It no longer opens a second handle with a different clock to the same physical owner. All other uses of `attach_runtime_prerequisites` remain unchanged.

## Expiry checks and real audit time

The changes route exactly ten expiry observations through their existing store:

| File | Checks | Preserved behavior |
|---|---:|---|
| `codex-rs/hepta-memory/src/local_lease_outbox.rs` | 3 | Explicit expiry, head disposition, active-handle validation |
| `codex-rs/hepta-memory/src/logical_turn_registry.rs` | 4 | Reservation, inspection, requested-lease reuse, current requested-lease loading |
| `codex-rs/hepta-memory/src/h7_trajectory_store.rs` | 3 | Recovery read and both checks around the expired-H7 transaction |

The H7 pre-transaction and post-await checks remain separate and retain the original owner, binding, exact-head and journal validation. Lease/H7 reads keep the original checked `i64` conversion and before-epoch rejection. Registry reads retain their original `u64` interpretation. Existing error variants remain in use.

The original wall-clock helper bodies and timestamp insertion expressions in all three files are byte-identical to their preimages. The compact executor file is unchanged; its own wall-clock read records an audit timestamp, while current-lease validation goes through the retained lease/store. Recorded audit timestamps may therefore advance while the qualification lease clock is held fixed. The fixture diagnostics label the logical qualification clock separately from observed real wall time. This separation is intentional and is not asserted as a production time override.

The new memory tests cover owner-clone sharing, independent owners, unchanged old-handle refusal, rejected backwards movement, controller lifetime, refusal of an active ordinary store, and refusal to reopen its retained database with a qualification clock.

## Cargo and Bazel type closure

Cargo enables the feature only through the two roots' dev dependencies. It adds no package dependency and changes no product default. Bazel needs one consistent `CognitiveStore` crate identity through each affected dependency path, so a single Agentd-to-memory replacement is insufficient.

The source-only exact-HEAD scans read 216 Cargo manifests and produced a nine-package closure after including the two roots' direct dev dependencies. The retained query scripts and original output are in `readonly-query-evidence/`; the complete 216 original manifest texts were not copied to this directory. `EXACT_CARGO_DAG.json` retains the selected normal packages' direct edges, and `EXACT_ROOT_DEV_CARGO_DAG.json` adds the infer-worker-host path.

The new helper creates separate, explicitly `testonly` `*-qualification-clock-lib` targets for:

- `codex-hepta-memory` and `codex-hepta-memory-extension`;
- `codex-hepta-cognitive-store` and `codex-hepta-supervisor`;
- `codex-app-server`, `codex-app-server-client`, and `codex-hepta-codex-adapter`;
- `codex-hepta-agentd` and its `codex-hepta-infer-worker-host` dev dependency.

All 17 affected normal edges point to the corresponding clock variants. The helper preserves normal dependency selects and the existing serde_yaml alias policy. Compile-time fixture inputs, existing features and required support source files are carried into the affected variants. It refuses an unreviewed package or a newly present `build.rs`. None of the nine packages has a build script in the pinned tree.

The ordinary Agentd macro and its generic unit/integration dependency map are unchanged. Only its existing explicit cognitive-write qualification library, harness and qualification process targets select the new clock map. The extension's unit tests select the clock dependency as their Cargo dev dependency does. Existing generic test-library names and their dependency definitions remain intact. Product targets retain their original graph. These are static graph checks; actual Bazel analysis and Rust compilation remain necessary, and generated Bazel Cargo lock data must be regenerated through the repository's normal command before qualification.

## Caller and validation boundary

The exact existing `verify_hepta_callers.py` lexical and typed-receiver functions were applied to all changed Rust files before and after the patch. All 160 declared boundaries had equal observed changed-file caller sets and equal typed authority fields. No protected file is changed, and all relevant existing definition markers remain. `CALLERS.toml` is byte-identical. No allowlist, ignored-path policy or authority field is widened. The result is recorded as `PASS_LEXICAL_DELTA_ONLY`, not as a full-tree caller gate.

The eventual source gate must run on the complete combined tree, followed by the normal formatter/lock and native checks. The focused test identities are:

- `cognitive_store::lease_clock::tests::qualification_clock_is_monotonic_and_bound_to_one_owner`
- `cognitive_store::lease_clock::tests::qualification_clock_refuses_existing_or_active_store`
- `local_development_owner::tests::explicit_owner_expires_bound_lease_and_fences_old_witness`
- `runtime::tests::qualification_prepare_quarantines_expired_registry_attempt_with_h7_evidence`

Planned, not executed:

```sh
just test --locked -p codex-hepta-memory --lib -E 'test(=cognitive_store::lease_clock::tests::qualification_clock_is_monotonic_and_bound_to_one_owner) | test(=cognitive_store::lease_clock::tests::qualification_clock_refuses_existing_or_active_store)' --retries 0
just test --locked -p codex-hepta-memory-extension --lib -E 'test(=local_development_owner::tests::explicit_owner_expires_bound_lease_and_fences_old_witness)' --retries 0
just test --locked -p codex-hepta-agentd --features qualification-cognitive-write --lib -E 'test(=runtime::tests::qualification_prepare_quarantines_expired_registry_attempt_with_h7_evidence)' --retries 0
```

The corresponding existing Bazel roots are `//codex-rs/hepta-memory:hepta-memory-unit-tests`, `//codex-rs/ext/hepta-memory:hepta-memory-unit-tests`, and `//codex-rs/hepta-agentd:hepta-agentd-cognitive-write-qualification-test`. No new owner process, provider request or formal effect is needed for these four tests.
