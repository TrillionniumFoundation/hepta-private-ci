# `learning.operator` developer guide

Canonical admission semantics are in [ADMISSION_CONTRACT.md](ADMISSION_CONTRACT.md).
[STATUS.json](STATUS.json) distinguishes implemented components, the generic
shadow coordinator, default runtime composition and external acceptance.

## Default qualification path

For a cold dependency cache, run
`cargo fetch --locked --manifest-path codex-rs/Cargo.toml` before the independent
API consumer script. This provisions all target archives from the workspace lock;
the actual consumer projections and 19 compilation probes remain offline and
reject dependency pin drift.

1. Replay the authoritative `learning.ledger` and freeze an owner-issued
   `DatasetSnapshotReceiptV3` with the exact source set, authority and expiry.
2. Construct `LearningEvidenceVerifierV1` from host-owned trust configuration.
   Candidate inputs do not choose signer keys, roles, scope or authority epoch.
3. Derive `TrainingProfileV1` or `WorldModelProfileV1` from semantic values. Their
   profile/runtime identities are computed internally; do not accept an unrelated
   caller-supplied digest as evidence of the profile.
4. Bind exact row semantics to independent `Observer` attestations and prepare
   `TabularTrainingRequestV1` or `WorldModelTrainingRequestV1`.
5. Issue the opaque capability through `issue_tabular_final_use_capability_v1`
   or `issue_world_model_final_use_capability_v1`. Bind the current durable owner,
   fence, issuance witness, exclusive deadline and shared work controls.
6. Consume it once through `fit_tabular_final_use_v1` or
   `fit_world_model_final_use_v1`. Revalidation before and after fitting is part
   of the operation; it must not be removed to save time.
7. Freeze independent evaluation data and evaluate the exact immutable candidate
   under the preregistered plan. Obtain a separately authenticated selection.
8. Persist the independently selected candidate create-only through the existing
   artifact owner, binding its payload and complete `TabularPayloadPinV2`.
9. Load in a fresh process and observe the candidate through a read-only host.
   `LoadedTabularOperatorV2` validates immutable payload/pin identity; selection,
   current owner state, revocations, clock and stop state require host checks at
   final use. An opaque selected wrapper is not a live owner witness.
10. Restore the exact immutable predecessor and its original complete pin after
    shadow qualification; never retrain or rewrite it during rollback.

The generic `coordinate_learning_operator_shadow_v1` enforces stage ordering
when a host supplies its ports. Its current tests use fixture ports; real owner
publication is implemented by `LearningOperatorArtifactOwnerV1`, reached through
`AgentdIntelligenceProductRunnerV1::persist_learning_operator_candidate`.
`EvaluatedTabularShadowConsumerV3` provides qualified read-only loading with
separate training/evaluation sources and currentness refresh. Those components
still need the remaining coordinator ports, a configured runtime caller,
distinct-process shadow loading and exact predecessor rollback composed together.
Signed component E2E exercises the ledger/evaluator/selector/ranker separately.

Direct V3 verify/fit primitives and structural V1/V2 fitters are available only
under `qualification-unverified-input`, in `compatibility`. They are diagnostic
and migration surfaces, not the default capability path. Existing V1 payload
pins and immutable predictors remain exported for named owner-bound adapters;
they do not establish current selection or runtime authority.

`codex-hepta-contracts::learning_operator_protocol` provides untrusted canonical
V1 transport codecs for the registered sensor, regularity and applicability
schemas. Dispatch requires the protocol identity and version; strict decoding
rejects unknown fields and noncanonical bytes. Its SHA-256 commits transport
fields, not a signer, owner capability or scientific qualification. Enum values
and nested profile member semantics remain undefined in the registry. The
registered `BellmanOperatorArtifactV1` has no canonical field schema and is
explicitly rejected. Native profile names do not imply wire parity: conversion
still needs measured profiles, horizon and lifecycle context from their owners.
Existing correctly pinned `HEPTTB01`
payloads can be read, while new V2 source commitments require new independent
admission; there is no implicit digest-version downgrade.

The final-use, real publication and qualified shadow APIs use Unix microseconds;
registered transport expiry uses Unix milliseconds. Supply explicit owner context
and checked unit conversion; do not equate an interval with a horizon/profile.
World-model row signatures cover rows and their owner context, not independent
measurement of request-supplied calibration, future-window or retention fields.

Plasticity process embeddings migrate explicitly to
`hepta.agentd.plasticity-bootstrap.v2` and `load_plasticity_process_bootstrap_v2`.
Supply the independently retained root key/validity and exact root-signed trust
distribution, including generation, effective/issued/expiry times and signature.
V1 signer-only descriptors reject; do not synthesize a root or signature from them.

`RankerAdmissionSnapshotV2::new` now requires the opaque
`ActivatedLearningTrustV1`, rather than a bare signer verifier. Retain the actual
root-admitted distribution; each ranker use revalidates its root window at the
native effective time. Distribution, trust, epoch or runtime changes require
explicit reload. The configured provider must still refresh current owner and
revocation state; a cached signed distribution cannot reveal later changes.

The current Agentd CLI constructs `AgentdIntelligenceProductRunnerV1::new`
without installing evaluation trust. `with_evaluation_trust` is exercised by
signed tests; plasticity's V2 bootstrap does not configure the product runner.
Its evaluation/publication entry therefore rejects with
`host learning trust unavailable` until the host composes an independently
pinned root configuration. Completing that bootstrap is part of the remaining
default caller work below.

## Implementing the remaining coordinator ports

The following is an implementation contract for the remaining host composition,
not a claim that these ports are configured. The public coordinator receipts in
`learning_operator_coordinator_types.rs` describe stage bindings; their IDs and
digests do not authenticate a dataset, candidate, selection or storage result.
The adapter must retain the actual verified objects and derive each coordinator
receipt from them. Keep the host's exclusive execution fence, cancellation domain
and independently sampled clock across the operation. Every effect is idempotent
under `(run_id, stage)` and rejects conflicting input; the coordinator does not
retry effects itself.

| Port | Existing implementation to compose | Retained binding and required behavior |
|---|---|---|
| `now_unix_micros` | Host clock, independent of request and receipt timestamps | Sample current Unix microseconds and enforce monotonic elapsed deadlines while synchronous work runs. |
| `freeze_training` | `LedgerWriter::freeze_dataset` and `read_dataset_records` | Retain the actual `DatasetSnapshotReceiptV3`, current durable ledger and exact bounded source records; use independently signed freeze evidence. |
| `derive` | `TrainingProfileV1` and signed `TabularTrainingRequestV1` | Derive profile/runtime identities from semantic values; bind sensor design, objective, rows, dataset and support policy. |
| `fit` | `issue_tabular_final_use_capability_v1` then `fit_tabular_final_use_v1` | Consume one opaque owner-borrowed capability and retain its `FinalUseTabularCandidateV1`; derive payload and artifact bindings from its publication view. |
| `freeze_evaluation` | Evaluation ledger's `LedgerWriter::freeze_dataset` | Retain a second actual receipt with disjoint active source records and independently observed future data; freeze after candidate publication time. Changing IDs or freeze time cannot make old observations future evidence. |
| `evaluate` | `ProductEvaluationRunnerV1::evaluate_temporal_comparison` and `qualify_and_persist` | Retain the frozen plan, estimator-derived temporal result and sealed `ProductQualificationReceiptV1`; consume the real fenced holdout and durably publish qualification evidence. |
| `select` | `prepare_self_evolution_selection_v1` and `admit_self_evolution_selection_v1` | Reauthenticate the sealed qualification against exact data, timing and policy; retain `VerifiedSelfEvolutionSelectionV1` from an independent selector. |
| `persist` | `AgentdIntelligenceProductRunnerV1::persist_learning_operator_candidate` | Supply `LearningOperatorPublicationInputsV1` with the real candidate, both dataset receipts, verified selection, shared control and externally admitted publication request; retain the exact `LearningOperatorStorageReceiptV1`. |
| `fresh_process_load` | Child-owned `EvaluatedTabularShadowConsumerV3::load` | Independently admit the complete V3 load binding and V2 model pin against current owners in a new process. Obtain actual process/boot evidence and exact payload/storage bindings. A copied parent handle or caller-authored boot nonce is insufficient. |
| `shadow` | Child-owned `EvaluatedTabularShadowConsumerV3::predict_shadow` | Use bounded read-only observations, refresh both ledgers, CURRENT and selection before/after each prediction, and preserve synthetic/deny-all outputs. |
| `revalidate` | Current ledger, artifact owner and selection verifier | Bind actual current heads, epochs, eligibility and revocation state to the retained candidate/selection; cached stage DTOs cannot supply currentness. |
| `rollback` | Independently configured cleanup and predecessor-loading owner | Reconcile the exact persisted object, reopen the original immutable predecessor with its original full pin, and verify current eligibility. Derive rollback evidence from the actual result; do not synthesize a replacement model or matching receipt. |

The persistence and load inputs include authority that the coordinator DTOs
cannot reconstruct. In particular, `LearningArtifactPublishRequestV1` needs an
externally admitted manifest and owner authorization; a candidate publication
view cannot issue either. The child must reauthenticate the signed evidence
against its independently retained host trust configuration and current owner
state. An IPC transfer of public digests does not serialize opaque admission.
If a predecessor is withdrawn or cannot be reopened, stop instead of reviving
its cached bytes.

## Acceptance of one composed shadow lifecycle

Implement and test the configured caller in one source tree. These cases apply
when exercising the candidate runtime boundary; they are not extra prerequisites
for ordinary source-only edits:

1. Retain the eligible predecessor's original payload, complete pin and owner
   binding. Open actual durable training/evaluation owners and a fenced artifact
   owner, then invoke the configured caller through the default API surface.
   Bind the run to host trust, current authority/stop epochs and one deadline.
2. Execute freeze, derive and final-use fit. Record the actual candidate identity
   and publication time. Obtain disjoint evaluation observations after that time,
   consume the real final holdout, publish estimator-derived qualification and
   obtain independently authenticated selection. Fixture keys and short virtual
   windows may test protocol behavior but cannot issue longitudinal acceptance.
3. Persist through the ProductRunner entry and the actual artifact owner. Start a
   distinct child process, re-admit against current owners, and verify that its
   loaded payload, complete pin and storage acknowledgement match the candidate.
   Run bounded shadow predictions and revalidation through the qualified V3
   consumer; a separate-process immutable-payload test alone does not close this
   lifecycle.
4. Finish a healthy run by reopening the exact predecessor and checking its
   original bytes, pin and current owner eligibility. Reopen the durable owners
   again after process exit to verify the storage and cleanup result. No step
   installs a candidate policy or changes production activation.
5. Exercise expiry/cancellation during fit, evaluation and persistence; source
   correction or withdrawal; trust/authority/stop movement; altered payload,
   pin or selector evidence; and child death during load or shadow. After known
   persistence, every failure must reach verified cleanup and predecessor reopen
   or preserve a terminal recovery obligation. Cleanup of a known object remains
   necessary after the work deadline.
6. Kill at the owner write/ack and cleanup/reopen boundaries. For unknown
   persistence, retain the exact request and use `reconcile_status` to discover
   historical storage without issuing a retry or loading stale bytes. For
   `PersistedButNotCurrent`, retain the known receipt. An unavailable predecessor
   or unverified cleanup must preserve recovery identity and stop the run.
7. Retain commands, source/tree, actual process identities, stage results and
   raw-log hashes for the same composed execution. Inspect every failed, skipped
   or missing stage. Successful component tests or a development-profile document
   check cannot substitute for this runtime qualification, independent scientific
   acceptance or target-host capacity evidence.

## Local checks

For ordinary development, run document checks against the working tree with the
development profile and run the affected Rust package tests through the repository
`just` recipe. Python commands below run from the repository root; `just` selects
the Rust workspace automatically:

```bash
python3 scripts/hepta-docs.py verify --profile development
python3 scripts/hepta-module-docs.py verify --profile development
just test -p codex-hepta-contracts --locked --lib -E 'test(learning_operator_protocol::tests)'
just test -p codex-hepta-bellman-operator --locked
just test -p codex-hepta-agentd --lib -E 'test(cognitive_ranker::evaluated_tests)'
just test -p codex-hepta-agentd --lib -E 'test(learning_operator_coordinator::tests)'
just test -p codex-hepta-agentd --lib -E 'test(learning_operator_artifact_owner::tests) | test(learning_operator_shadow_loader::tests) | test(learning_operator_source_binding::tests)'
```

For the candidate-execution qualification path, additionally run the dedicated
contracts and dossier checks, and use the qualification profile for exact-source
and historical navigation validation:

```bash
python3 scripts/hepta-lane-e-closure.py self-test
python3 scripts/hepta-lane-e-closure.py verify
python3 scripts/hepta-learning-operator-contract.py verify
python3 scripts/hepta-implementation-dossiers.py verify
python3 scripts/hepta-module-docs.py verify --profile qualification
```

Exact-source CI independently records documentation, API consumer checks,
compilation, tests, mutation, coverage, resource regression and static quality.
`hepta-implementation-maps.py verify` additionally requires the retained source
observations to exist in local Git history. Missing historical objects or stale
observations are diagnostics, not current execution evidence. The authoritative
qualification script is an exact committed-candidate workflow; inspect every
stage receipt and any skip instead of treating command presence as a pass.

## Error semantics

Use `ClassifyOperatorAdmissionFailure::disposition`; do not parse display strings.
Correct request-local failures, re-admit stale evidence against current owners,
reject invalid candidates, abstain on unsupported cells, and stop the consumer on
owner, clock or authority failure. Reopening failure of the exact predecessor is
terminal.

## Ownership boundaries

`learning.operator` constructs deterministic qualification candidates. The
ledger, artifact registry, evaluator, selector, activation policy, production
writer and rollback authority remain with their existing owners. Repository
success does not issue scientific acceptance or production activation.
