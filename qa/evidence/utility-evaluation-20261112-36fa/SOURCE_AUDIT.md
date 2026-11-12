# Real utility evaluation: source audit and remaining qualification gates

## Status and provenance

**HOLD. This is a source audit and blocker map, not an execution or efficacy certificate.**

The ordinary-path audit read the integrated source at local commit
`0b450608d0fa577b2d4c4c198883e7f5a432bf92`, tree
`e68a7ffb394bdac721259fd6295d799800d564c3`. That source contains the
`#6163` evaluated-retention work and the subsequent original Model/readback
integration and explicit Dataset v3 change. Publication identity, final source
identity, and native results must be supplied by their actual records; this
note does not infer them from an earlier commit or a PR description.

The seven-file utility change was independently inspected at local commit
`b19f15923760da49cf735f550da3a50beb9c50a2`, tree
`8cd35e01cc02146606457a8481ecc1d8dda22158`, against that baseline: seven files,
217 insertions and seven deletions. Static review found no blocking defect;
`git diff --check` passed. This audit did not execute tests or formatting.
Native execution and any later publication remain separately attested facts.

The seven-file utility fix changes the precedence of incomplete evidence and a
known failed metric in the independent and legacy comparators. Before the fix,
one failed metric could classify a partially observed comparison as
`Ineligible`; the learning bridge then treated that as a completed negative
evaluation. The intended fixed behavior retains the known failed metrics but
returns `InsufficientEvidence` whenever a required evidence gate is missing.
The existing learning bridge refuses to construct an Evaluation receipt for
that disposition. Exact-source tests and their results are separate evidence.

All new comparator and learning-bridge tests are **synthetic mechanism
fixtures**. They add zero real authorized A tasks, zero independent future B
episodes, zero ordinary C consumers, zero adopted releases, and zero complete
daemon-plus-Root cold recovery qualifications. They do not establish task
benefit, independent custody, cost coverage, fraud, or production permission.

Source references below identify the concrete owner or verifier inspected.
“Present” means that the implementation exists in that source, not that the
ordinary deployment has exercised it successfully. “Missing” is scoped to this
integrated path and this audit; it is not a claim that no other branch contains
research or partial implementation.

## Result semantics

| Result | Required meaning | Present source behavior | Qualification boundary |
| --- | --- | --- | --- |
| Adopt | A complete comparison passes the registered utility and hard constraints, followed by separate authorization of the actual new version | `closure.rs` produces `EligibleForIndependentSelection` with `AuthorityPosture::DENY_ALL`; `neuron_cell_learning_evaluation.rs` can produce `Qualified`; original Model Proposal and positive Selection receipt components exist | Eligibility is not adoption. Original Artifact selection, CURRENT, FinalUse, actual C consumption, and ordinary route execution remain necessary |
| Complete NoUpdate / Ineligible | Complete evidence supports retaining the parent; known negative findings stay recorded | `neuron_cell_learning_evaluation.rs::prepare_cell_learning_evaluation_v1` maps complete `Ineligible` to Evaluation `NoUpdate`; evaluated-retention context authenticates the separate four-receipt cut | A completed negative comparison cannot be inferred from missing measurements, missing cost, incomplete support, or unavailable owners |
| InsufficientEvidence / Unknown | Required evidence, support, source, independence, cost, or authorization is missing | The utility fix gives `InsufficientEvidence` precedence while retaining known `failed_metrics`; the original learning bridge returns a typed error before creating a receipt | Missing evidence remains unresolved. A known failure may prevent adoption without certifying that the whole comparison completed |
| Objective Fraud | A separately reproducible deterministic violation, with an identified evidence and challenge process | The inspected evaluation and retention APIs return typed errors, refused decisions, or uncertainty; they do not themselves implement a fraud adjudication or penalty protocol | A metric failure, estimator rejection, malformed input, or missing result must not be relabeled fraud. Any challenge or disposition requires its own actual contract and authorized owner |

Relevant source: `codex-rs/hepta-intelligence-eval/src/closure.rs`,
`codex-rs/hepta-intelligence-eval/src/lib.rs`,
`codex-rs/hepta-agentd/src/neuron_cell_learning_evaluation.rs`, and
`codex-rs/hepta-agentd/src/circuit_evaluated_retention_context.rs`.

## Gate-by-gate map

### U0. Frozen external objective and distinct learned objects

**Target.** Preserve the user/task objective independently of predicted
consequences, the action policy, critic, independently measured terminal
outcomes, and any public reward contract. Changes in a learned object must not
rewrite the objective or its observation rules.

**Present.** The original Dataset v3 profile binds the RunStart NDU snapshot,
task objective, original output policy, complete candidates, and actual action.
Decision support binds the original Source publication. Outcome support remains
an independently signed measurement reference. The original B provider checks
the original policy and publication against Decision facts and consumes
independent terminal Outcome facts. The NDU model represents fixed objective,
axis-registry and normalization identities, resource/risk ceilings, and
separate candidate contributions.

**Missing.** This code does not supply an independent source of actual results,
the original public reward contract, or evidence that a deployed optimizer
cannot influence the task/objective author and observer. Those must be frozen
and authenticated in the actual authorized run.

**Original paths.** `codex-rs/hepta-agentd/src/cell_q24_dataset.rs`;
`codex-rs/hepta-agentd/src/circuit_original_evaluation_provider_records.rs::Episode::read_episode`;
`codex-rs/hepta-ndu/src/model.rs::{UtilityProfile,EvaluationPolicyV1}`;
`codex-rs/hepta-learning-ledger/src/production.rs`.

### U1. Complete deployment identity and strongest deployable baseline

**Target.** Freeze the base, Cell/adapters, router/selector, runtime and tool
configuration, task distribution, numerical profile, and all release material
for both the candidate and the actual deployable baseline. Preserve the
registered old-task, rare-task, safety, privacy, and authorization constraints.

**Present.** `CellBundleComponentsV1` binds base, organ/Cell adapters, heads,
composition, encoder, tokenizer, normalizer, calibration, numeric profile, and
state/output schemas. `CellTrainingLineageV1` binds source bundle, Dataset,
update rule, evaluation profile, and rollback predecessor. Evaluation freezes
metric roles and margins and supports primary superiority, noninferiority,
and absolute constraints. Its default decision carries no effect authority.

**Missing.** A model bundle digest alone is not the complete deployable
environment. The actual chosen router, external tools, runtime, distribution,
deployment material, strongest baseline selection, and mandatory-task
coverage still need owner-backed records for this experiment. The existing
matched comparison contract cannot by itself prove that the chosen fixed
expert is the strongest deployable alternative.

**Original paths.** `codex-rs/hepta-learning-artifacts/src/cell_bundle.rs`;
`codex-rs/hepta-agentd/src/neuron_cell_evaluation_contract.rs::CellComparisonContractV1`;
`codex-rs/hepta-intelligence-eval/src/metric_roles.rs`;
`codex-rs/hepta-intelligence-eval/src/closure.rs`.

### U2. Complete cost contract and accounting scope

**Target.** Charge actual training and search attempts, failures, cancellations,
evaluation, transfer/download, activation, inference, shared work, maintenance,
and recovery under the frozen allocation and metering contract. Unknown cost
is not zero, and quality averages do not waive hard constraints.

**Present.** `CellTaskCostV2` retains immutable exclusive charges and separate
inclusive envelopes; failed, cancelled, and rejected exclusive entries remain
charged. Its optional measurements preserve unknown values. The comparison
owner requires drained actual journals, nonmissing stages, known required
metrics, and matching owner/source identities. `CellTrainingBudgetV1`
explicitly describes cumulative work, including inherited pretraining and
candidate search under the preregistered allocation convention.

**Precise open scope.** `CellEvaluationCostScopeV1` currently has only
`TaskLedgersBeforeFinalHoldout`. The `CellEvaluationRecordV1` source comment
explicitly excludes the later holdout estimator, signature verification, and
publication overhead from those totals. The ledger types and nonzero meter
references do not authenticate physical meters or establish exhaustive work
coverage. Actual transfer/download, activation, service, and maintenance costs
must be reconciled to an explicit broader contract before a full-deployment
net-benefit claim is made.

**Original paths.** `codex-rs/hepta-neuron/src/cell_task_cost.rs`;
`codex-rs/hepta-agentd/src/neuron_cell_evaluation.rs::{CellEvaluationRecordV1,CellEvaluationCostScopeV1}`;
`codex-rs/hepta-agentd/src/neuron_cell_evaluation_contract.rs::{CellEvaluationArmRecordV1::read,validate_required_metrics}`.

### U3. Independent evaluation custody

**Target.** Verify operational control, task provenance, model/training
lineage, evaluator lineage, and temporal separation; distinct keys alone must
not count as independence.

**Present.** The authenticated evidence path is stronger than key inequality:
`verify_signed_actor_separation` checks the shared trust/objective domain,
validity and revocation, principal/credential/key separation, and different
`controller_id` values. Trusted signer configuration explicitly assigns the
controlling authority and states that the host is responsible for that mapping.
Temporal training excludes held-out principals, episodes, windows, and
decisions. Signed plan and evaluator payloads bind the frozen evaluation.

**Missing.** Host-declared controller identities do not prove the real control
relationship. Actual task-source independence, evaluator model/teacher
relationships, training contamination, organizational control, and holdout
custody need their own authenticated provenance. The inspected types do not
establish resistance to an unknown colluding committee. No new independent
data owner or evaluator has been created by these tests.

**Original paths.** `codex-rs/hepta-learning-ledger/src/signed_evidence.rs::{TrustedLearningSignerV1,verify_signed_actor_separation}`;
`codex-rs/hepta-learning-ledger/src/causal_v2.rs::verify_independent_roles`;
`codex-rs/hepta-intelligence-eval/src/signed_evaluation.rs`;
`codex-rs/hepta-intelligence-eval/src/temporal_fold.rs`;
`codex-rs/hepta-agentd/src/circuit_original_evaluation_provider_contract.rs`.

### U4. Action-dependent outcomes, critic isolation, and positive Adopt support

**Target.** Retain decision-time state and actual behavior probabilities, fit
the critic only on authorized prior or cross-fitted data, and require support
and identification conditions before evaluating a changed policy.

**Present.** `evaluate_temporal_holdout` rebuilds predictions from earlier
training outcomes and label-free targets rather than trusting supplied critic
values. Joins must be bijective and temporal/lineage exclusions are enforced.
OPE checks finalized observed outcomes, complete action distributions,
effective sample size, and weight limits; unsupported actions are errors,
not zero-reward observations. Provider records bind the Decision to the
actual Source policy.

**Precise open support condition.** The original provider's `probability`
function accepts only zero or one million ppm, and the Decision check requires
`selected_propensity == ProbabilityQ32::ONE`. The OPE core rejects an action
with positive evaluation probability and zero behavior probability. A changed
deterministic action therefore cannot receive a supported OPE claim from this
logged behavior alone. A new positive Adopt study needs actual authorized
sampling/experimental support and a frozen identification contract. Historical
propensities must not be retrofitted. The temporal fold primitive is not itself
a complete cross-fitting orchestrator or proof of real-world causal assumptions.

**Original paths.** `codex-rs/hepta-agentd/src/circuit_original_evaluation_provider_records.rs::{Episode::read_episode,observation,probability}`;
`codex-rs/hepta-intelligence-eval/src/temporal_evaluation.rs::evaluate_temporal_holdout`;
`codex-rs/hepta-intelligence-eval/src/temporal_fold.rs::fit_temporal_fold`;
`codex-rs/hepta-intelligence-eval/src/ope.rs::{estimate_ope,estimate_row}`.

### U5. Preserve the two different NoUpdate paths

| Property | Strict TrainingNoUpdate path | Evaluated NoUpdate path |
| --- | --- | --- |
| Actual training result | `TrainingNoUpdateV2`; unchanged parameters | A changed Candidate remains the actual Training result |
| Decision prefix | E/D/T, three receipts | E/D/T/Evaluation, four receipts |
| Independent B | Not created by the unchanged-training result | A complete independently authenticated negative comparison is required |
| Existing ordinary command owners | Original strict Version, Selector, and C Observer implementations exist | Low-level authenticated context, publication, and recovery exist; ordinary Version/Selector/C purposes are absent in this path |
| Forbidden conversion | Cannot be fabricated from an evaluation failure or missing result | Cannot replace Candidate with `TrainingNoUpdateV2` to enter the old three-receipt route |

The evaluated context checks exactly four receipts, the original Training
receipt and full signature, the original Evaluation receipt and full
signature, actor separation, a changed candidate, and actual
`Evaluation::NoUpdate`. Both original command owners are reread at publication
boundaries. Readback contexts cannot prepare new work; uncertain preparation
or publication preserves the original intent for same-operation recovery.

**Original paths.** `codex-rs/hepta-agentd/src/circuit_evaluated_retention_context.rs`;
`codex-rs/hepta-agentd/src/circuit_evaluated_retention_publication.rs`;
`codex-rs/hepta-agentd/src/circuit_evaluated_retention_recovery.rs`;
`codex-rs/hepta-agentd/src/circuit_retained_version_context.rs`;
`codex-rs/hepta-agentd/src/circuit_selection_command.rs::OriginalCircuitSelectionCommandContextV1::authenticate`.

### U6. Ordinary startup and original owner assembly

**Target.** The actual daemon must receive the original task, material,
training, evaluation, model, selection, version, and final-use owners under
the same authorized operation and invoke their concrete interfaces.

**Present.** `main.rs` calls `startup.receive()`. Production startup receives
the original Root learning capability, and configuration refuses to run while
that capability lacks real stage owners. Root resident construction consumes
concrete stage bundles and installs its execution gate only after its own
fresh admission. Candidate evaluation and original Model Proposal dispatch
now exist; it is inaccurate to describe this source as lacking all original
Model functionality.

**Missing.** `AgentdConfig::with_root_learning_stage_owners` has no product
caller in the inspected source and its CALLERS entry has `product_callers=[]`.
`into_candidate_runtime` has no ordinary caller. The five evaluated-retention
context/prepare/publish/recovery boundaries likewise have empty product
caller sets. JSON metadata, a digest, or a new callback cannot create these
original owner capabilities.

**Original paths.** `codex-rs/hepta-agentd/src/main.rs`;
`codex-rs/hepta-agentd/src/production_launcher.rs::{AgentdProductionStartup::receive,AgentdProductionLaunch::run}`;
`codex-rs/hepta-agentd/src/config_root_learning.rs`;
`codex-rs/hepta-agentd/src/authority_host_learning_resident.rs`;
`codex-rs/hepta-agentd/src/cell_q24_candidate_stage_model.rs`;
`CALLERS.toml`.

### U7. Version publication, Selector, and distinct ordinary consumer C

**Target.** The actual original authorized version is published, the original
Selector attests its actual physical selection, and a distinct ordinary C
loads and uses the expected material under its own task authority.

**Present.** Evaluated-retention publication uses original Artifact selection,
CURRENT, and exact FinalUse. Strict TrainingNoUpdate command owners include
physical publication and C readback. Positive Model Selection has a separate
receipt owner that reads original SourceBound Training, Model, completed
independent Evaluation, and an already authorized publication.

**Missing.** The Candidate stage and Root stage gate both refuse Selection and
NextUse unless the prefix is the old `TrainingNoUpdateV2` profile. This is an
intentional safe boundary. The existing live read protocol is fixed to the
three-receipt T prefix or its four-receipt S extension and checks T/S, not
T/E/S. The C constructor records D/T/S directly and cannot consume the new
Evaluation predecessor. Positive Model receipt components are not a completed
ordinary cross-process command route.

**Original paths.** `codex-rs/hepta-agentd/src/cell_q24_candidate_stage_owners.rs::execute_stage`;
`codex-rs/hepta-agentd/src/authority_host_learning_resident_stages.rs::require_stage`;
`codex-rs/hepta-agentd/src/circuit_learning_read_wire.rs::{mode,context_binding}`;
`codex-rs/hepta-agentd/src/circuit_selection_readback_host.rs`;
`codex-rs/hepta-agentd/src/circuit_next_use_readback_host.rs`;
`codex-rs/hepta-agentd/src/circuit_model_selection_receipt_owner.rs`.

### U8. Daemon and Root cold recovery, availability, and external receipts

**Target.** A fresh daemon and Root process recover the same original
operation, full receipts and signature windows, physical CURRENT and
revocation state, available model bytes, and actual C consumption. Recovery
must not mint a new execution or retry an uncertain effect.

**Present.** Resident recovery is explicitly read-only and requires a
separate current readback authorization. Evaluated-retention recovery uses
the original Control intent and original T/E owners and does not contain a
fresh prepare or FinalUse grant. Model recovery rereads D/T/E and the actual
original Model record. Artifact/model material identities and existing reader
capabilities support exact byte inspection.

**Missing.** No complete ordinary A/B/C cold recovery is established by this
source audit or the new tests. All original owners, observed denial/uncertainty,
revocations, physical process identities, and material availability must be
demonstrated together on one frozen deployable source. A content root
identifies bytes; it does not establish sustained availability, authorization,
or later use. Connecting any chain receipt to accessible material and real
consumer readback is a separate integration gate, not a consequence of these
off-chain digests.

**Original paths.** `codex-rs/hepta-agentd/src/authority_host_learning_resident.rs::recover_resident_learning_v3`;
`codex-rs/hepta-agentd/src/authority_host_learning_resident_runtime.rs`;
`codex-rs/hepta-agentd/src/circuit_evaluated_retention_recovery.rs`;
`codex-rs/hepta-agentd/src/cell_q24_candidate_stage_model.rs::read_original_model`;
`codex-rs/hepta-agentd/src/neuron_cell_evaluation_model_material_service.rs`.

## Implementation order justified by the inspected dependencies

1. Validate the utility precedence repair on the exact frozen source and retain
   both the before-fix counterexample and after-fix native result. Preserve
   `failed_metrics`, signature rejection, and the unchanged Training cut.
2. Implement a separate evaluated-retention Version purpose that retains the
   original Evaluator connection and four-receipt cut through preparation,
   exact FinalUse, publication, and permanent readback after uncertainty.
3. Add the matching explicit live-read/Selector/C profile carrying T/E/S
   evidence; retain the strict old three-receipt protocol and the existing
   Candidate/Root refusal until the new owners are genuinely installed.
4. Install the actual owner descriptors into ordinary startup. Run an
   authorized complete negative comparison first, with actual C and full
   daemon/Root restart. Local fixture signatures do not supply those owners.
5. Execute a narrowly scoped positive Adopt study with supported actual
   policy behavior, independent future outcomes, a justified deployable
   baseline, complete cost scope, and all registered hard constraints.

The existing four-receipt context already performs the needed local
authentication; duplicating it would not close the next blocker. The next
executable host step crosses Version, live-read, Selector/C, Root stages, and
their source guards. It should be implemented as separate reviewable changes
with original-owner evidence, not by deleting current refusal checks.

