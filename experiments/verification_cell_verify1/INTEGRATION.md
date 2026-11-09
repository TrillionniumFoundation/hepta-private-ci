# VERIFY-1 native integration map

## Pinned inspection scope

This map describes the inspected source identities below. It does not imply that
the candidate's Cell interfaces are already on `main` or that later revisions
preserve the same contracts.

| Source | Pinned identity |
| --- | --- |
| Implementation base | `fix/codex-v13-same-model-next-task-20261106` at `6ddfca2406e4d01416cd2f7ab1655a0dc16f8da5` |
| Base tree | `491eace326f335498334fb051c9e8f298ca7a04c` |
| Observed `main` | `732e934ba496d90fbe042b8d41d479ef901643e5` |

The existing native entry points below retain the original implementation-base
audit. In particular, durable dispatch and automation host code differ from the
observed `main`; this document uses the base's dispatch behavior.

The native extension was separately inspected at published snapshot
`0c81508e3cb9ea5c949c12a0c01c61c66e8d4df2`. Its
[SOURCE_BINDING.json](../../qualification/verify1-native-20261108/SOURCE_BINDING.json)
binds the actual Linux run to the base plus eight source files, with separate
tested and formatted hashes. The publication snapshot is not the test subject,
and the test's ephemeral candidate identity is not a production identity.

## What this package establishes

This is a research and engineering harness with actual local SQLite effects,
synthetic tasks, fault injection, typed reports, and descriptive metrics. The
controller retains the goal and checks current state in the acceptance
transaction. This fixture assumes its controller and database access are
trusted; it is not an isolation boundary against another database writer.

`kernel_payload.py` only serializes reports for the JSON payload slot in
`QualificationEvidenceEnvelopeV1`. It creates neither a native signed envelope
nor a `SignedMessage`, invokes no native evidence ingress, and establishes no
production trust registration. Payload identity checking is not signature
verification or an authenticated native store read. Its inner record digest is
not the native payload or envelope digest.

The separate Rust extension and Agentd qualification described below now exercise
typed native report validation, a real fixture-state checker, and signed native
evidence ingress under ephemeral fixture trust. This does not change the Python
serializer's responsibilities or register a production checker, signer, or caller.

Within the original four-policy SQLite runner, the neural self-evaluation,
shared-base roles, distinct-adapter, and distinct-base arms remain `NOT_RUN`.
That runner's `common_misjudgment` fixture injects a shared wrong value; it does not execute correlated model voters. Synthetic source groups do
not become independent real tasks by receiving different identifiers. An
engineering smoke result does not qualify a real-model study, Agentd production
integration, or a statistical guarantee.

Separate real-model execution was retained in PR #5346 at evidence snapshot
`f25124815a9832af9b00652a4741d794a744df06`: see the
[run-v2 provenance](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f25124815a9832af9b00652a4741d794a744df06/qualification/cell-research-stages-20261108/followthrough-20261108/README.zh-CN.md)
and [43-check independent audit](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f25124815a9832af9b00652a4741d794a744df06/qualification/cell-research-stages-20261108/followthrough-20261108/VERIFY1_AUDIT.json).
It records 108 completed policy trajectories, 652 real model forwards and three
trained frozen-feature logistic readouts. The execution is bound to a source
capsule and manifest; `published_model_source_commit` remains `null`. It is not
covered by the native capsule below or automatically part of the observed
phase-1 PR #5351 source. The pilot retains scientific admission **HOLD** and
production authority **NONE**; its optional-call cap is not equal actual cost.

## Existing native entry points

Paths below are relative to the repository root; links resolve from this file.

| Responsibility | Source and entry points | Integration boundary |
| --- | --- | --- |
| Cell input and decision | [hepta-neuron/src/cell_types.rs](../../codex-rs/hepta-neuron/src/cell_types.rs): `CellStepInputV1`, `CellScopeV1`, `CellDecisionReceiptV1`; [cell.rs](../../codex-rs/hepta-neuron/src/cell.rs): `prepare_cell_step`, `enter_cell_step`, `decide_cell` | Bind observation, task/run identity, source frontier, masks, deadline, and cost. The decision receipt is advisory and is never an effect capability. |
| Neuron confidence | [hepta-neuron/src/runtime_types.rs](../../codex-rs/hepta-neuron/src/runtime_types.rs): `NeuronCalibrationProfileV1`, `calibrate` | Error-derived confidence/OOD and profile validity are distinct from measured probabilities for a specified trajectory event. |
| Calibrated routing | [hepta-intuition/src/calibrated.rs](../../codex-rs/hepta-intuition/src/calibrated.rs): `CalibrationArtifactV1`, `OodArtifactV1`, `decide_calibrated` | The host must authenticate artifacts; hard vetoes and legal candidates remain enforced. A digest or high confidence does not authenticate the artifact or grant authority. |
| `kernel.evidence` ingress | [hepta-agentd/src/evidence_host.rs](../../codex-rs/hepta-agentd/src/evidence_host.rs): `EvidenceHost::open`, `kernel_evidence_claims`, `append`, `query`, `verify` | Owner-configured trust, current host generation, canonical signing claims, and bounded ingress remain native responsibilities. |
| Evidence storage and verification | [hepta-evidence/src/qualification.rs](../../codex-rs/hepta-evidence/src/qualification.rs): `QualificationEvidenceStore::append_receipt`, `query_claim`, `verify_chain` | Validate signed provenance, exact candidate/tree/claim identity, freshness, replay, lineage, and current trust. Ordinary JSON payload semantics require a separate checker. |
| Tool/effect authority | [hepta-operations/src/durable_store.rs](../../codex-rs/hepta-operations/src/durable_store.rs): `DurableOperationStore::authorize_dispatch`, `execute_authorized`, `execute_authorized_in_transaction`, `observe_terminal` | `FinalUseAuthority` and `SignedFinalUseGrant`, lease/state checks, and the durable writer fence precede effect execution. Indeterminate dispatch is not permission to retry. |
| Production automation host | [hepta-agentd/src/automation_effect_host.rs](../../codex-rs/hepta-agentd/src/automation_effect_host.rs): `AgentdAutomationEffectHost::open`, `execute`, `reconcile` | Owner-selected endpoint/scope, revocation refresh, TaskFlow fence, destination status lookup, and terminal acknowledgment govern real effects. |
| Provider outcome semantics | [hepta-contracts/src/provider_effect.rs](../../codex-rs/hepta-contracts/src/provider_effect.rs): `ProviderEffectIntent`, `ProviderEffectAckStatus`, `ProviderEffectState` | `Accepted` means admitted, not completed. `Indeterminate` requires reconciliation using the exact effect identity. |
| Qualification-only provider seam | [hepta-evidence/src/provider_effect_store.rs](../../codex-rs/hepta-evidence/src/provider_effect_store.rs): `dispatch_provider_effect_qualification`, `reconcile_provider_effect_with_adapter` | Useful for fault/recovery qualification; this seam is not registered as a production Agentd caller. Invocation is not proof of a physical effect. |
| Full task accounting | [hepta-neuron/src/cell_task_cost.rs](../../codex-rs/hepta-neuron/src/cell_task_cost.rs): `CellTaskCostV2`, `CellTaskCostIdentityV2`, `CellCostEntryV2`, `CellCostAccountingV2` | Bind source/task identity and all stages, including failed or cancelled work. Keep exclusive entries distinct from inclusive envelopes; unmeasured cost is unknown, not zero. |

## Native extension and retained execution

| Component | Source | Executed scope |
| --- | --- | --- |
| Typed report namespace | [verify1_report.rs](../../codex-rs/hepta-evidence/src/verify1_report.rs), [qualification.rs](../../codex-rs/hepta-evidence/src/qualification.rs) | Validate original inner report bytes/digest and typed semantics in `hepta.verify1.report`. Generic append does not invoke a property checker. |
| SQLite property checker | [verify1_checker.rs](../../codex-rs/hepta-evidence/src/verify1_checker.rs), [verify1_fixture_check.rs](../../codex-rs/hepta-evidence/examples/verify1_fixture_check.rs) | Recompute initialized goal, epoch, frontier, values, finished intents and ACK/readback obligations in one read snapshot. Return an unsigned receipt without accepting the task. |
| Agentd evidence path | [verify1_kernel_evidence_product.rs](../../codex-rs/hepta-agentd/tests/verify1_kernel_evidence_product.rs) | Start the actual daemon with ephemeral fixture trust; sign, append, query and verify, including replay, expiry, tamper and current revocation checks. No production principal is registered. |

The [native qualification capsule](../../qualification/verify1-native-20261108/README.md)
records 131 evidence-crate tests passing, one existing ignored test, and four
selected Agentd integration tests passing. Six actual Python SQLite cases
produced seven native checker results. These are engineering observations for the
bound source overlay; final formatting and eventual publication are separate
identities. Tests were not rerun after final formatting.

The checker's property is `fixture_prefix_goal_and_owner_readback_at_snapshot`
in domain `sqlite_two_field_engineering_fixture_v1`. A step-1 result covers only
the left target and cannot become a terminal success result. The checker assumes
a trusted controller goal, a trusted host-selected fixture database, a consistent
SQLite transaction, and trusted owner/epoch-bound readbacks. It does not isolate
another process able to modify that database.

The native qualification capsule records `model_inference=false`, no production
caller and no adoption. This scope is separate from the real-model run-v2 pilot
above and does not assert zero inference across VERIFY-1. It does not include
whole-workspace, Bazel or other-platform qualification.

## Three report contracts and their authority

| Report | Meaning | Required interpretation |
| --- | --- | --- |
| Risk prediction | Probability of a named error event over a specified horizon | Bind model/version, domain, source/state, and event. `p` selects optional checks; it never authorizes an effect or waives a mandatory check. |
| Calibration report | Relationship between predictions and observed outcomes | Bind frozen data/split, model, labels, assumptions, sample scope, and drift conditions. Calibration on one domain does not establish another domain's coverage. |
| Verification receipt | A checker's result for a concrete property | Carry checker identity, property, assumptions, evidence binding, and `proved` / `refuted` / `unknown`. `proved` applies only to that check under those assumptions. |

Native `EvidenceDispositionV1::Supported` is not `proved`. It describes support
under the evidence-chain rules. A valid signature and supported provenance do
not establish that an arbitrary payload's property is true. Typed serialization
also does not establish that the claimed checker ran.

Native role independence requires distinct authenticated principals and signing
identities where specified. It does not establish independent model errors.
Record base model, adapter, training/data provenance, task group, and shared
failure cluster separately from issuer identity. Neither `confidence_ppm`, OOD,
nor a probability may become a `FinalUse` grant or a replacement for readback.

## Faults and the corresponding native observations

The native checker exercised the same retained SQLite states. The final column
lists remaining production or model work, not missing fixture-checker code.

| Injection | Executed fixture and native result | Remaining production or model connection |
| --- | --- | --- |
| Stale read | State changes after an earlier observation; native checker refutes the current wrong values. | Bind Cell source frontier and owner revision, current dispatch fence, and evidence expiry/revocation. Recheck the property against the current destination before acceptance. |
| Missing receipt | Native checker returns unknown after commit without ACK, then proves the pinned snapshot after owner readback without effect replay. | Preserve admission/dispatch identity and `Indeterminate`; use authoritative destination lookup and reconciliation without repeating the effect. |
| Semantic error | Native checker refutes the incorrect goal value despite normal effect execution. | Run a trusted property-specific checker on actual destination bytes/values. Hashes, transport success, and signatures alone do not check meaning. |
| Partial success | Native checker refutes the complete goal when only part is present. | Distinguish `Accepted` from `Completed` and enumerate all terminal obligations. A completed sub-operation is not a completed trajectory. |
| Common misjudgment | Native checker refutes an injected wrong value; no model voters ran in this native capsule. | Collect actual model/voter outputs with frozen base/adapter identities and blinded outcome labels; compare shared failures with an external checker. Native signer diversity is not a substitute. |

## Remaining integration sequence

1. Connect the existing fixture checker or another property-specific checker to
   an owner-selected production trust entry point. Fix its version, property,
   assumptions, evidence sources, freshness policy and result scope. Authenticate
   destination readback and retain `unknown` for unchecked obligations. The
   SQLite fixture's trusted database assumption does not establish this ownership.
2. Supply actual production issuers and caller wiring for the native envelope,
   signing, append/query and current-trust path exercised by the Agentd fixture.
   Bind the real source/tree and evidence identity, and qualify the target's
   revocation, expiry, replay and recovery behavior. The test's ephemeral trust
   configuration must not be reused as production authority.
3. Add actor/tool hooks around observation, optional check selection, effect
   execution, and terminal acceptance. Keep authorization, hard constraints,
   dispatch fencing, and current destination readback in the host. Synchronous
   authorized callbacks must not wait on remote work; asynchronous delivery
   needs the existing durable admission and reconciliation path.
4. For the next scientific comparison, freeze real model/base/adapter artifacts,
   task sources, train/calibration/confirmation splits, and output receipts.
   Preserve the separate run-v2 evidence and its unresolved qualification limits. Keep hidden
   outcome labels away from policies. Use paired tasks and explicit source,
   model-family, adapter, and failure-cluster labels; execute equal-budget voting
   and external-check arms before drawing ensemble conclusions.
5. Measure full costs, including encoding, inference, queues, checks, retries,
   persistence, recovery, and failures. Report unmeasured child CPU/energy and
   missing labels explicitly. Compare accepted-trajectory errors, risk–coverage,
   discovery lead time, shared failures, needless interruptions, and total cost.
6. Evaluate risk-input and check-cost interventions with evidence held fixed.
   These policy interventions do not establish an activation-level causal
   mechanism. State any guarantee for its exact event, horizon, sampling and
   dependence assumptions; per-step budgets alone do not resolve adaptation,
   distribution drift, or finite-sample uncertainty.

Until these gates have their own execution evidence, native production
qualification and real-model scientific acceptance remain open. This package
does not change the existing authorization or effect-readback boundary.
