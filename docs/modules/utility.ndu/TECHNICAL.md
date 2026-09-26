# utility.ndu technical development guide

**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0  
**Module:** `utility.ndu`  
**Owner / deputy:** `intelligence-platform` / `learning-platform`  
**Lifecycle:** `target`  
**Source status:** `existing_bound`  
**Bootstrap work package:** `NDU-0-PREFERENCE-UTILITY-CONTRACTS`

This guide is the stable implementation and operations entry for `utility.ndu`. Canonical ownership, contract, protocol, data-domain, delivery and threat facts remain in the JSON registries. This document explains the concrete implementation and repeats the generated registry projection exactly; it grants no runtime, production, selection, promotion, merge or release authority.

## 1. Identity, mission and ownership

`utility.ndu` maintains bounded preference and recursive-utility projections for system, domain, agent and episode subjects. The primary owner controls the declared source root and is accountable for deterministic semantics, compatibility, persistence, tests and rollback. The deputy independently reviews public contracts, hierarchy semantics, authority checks, durability, migrations, resource bounds and activation evidence.

The module may compute advisory recommendations and authenticated local evidence. It may not mint authority, mutate hard constraints, dispatch physical effects, select a stochastic artifact without external evidence, or absorb another owner's durable facts.

## 2. Source binding and implementation status

The exclusive source root is:

- `codex-rs/hepta-ndu`

Named product composition additionally uses bounded callers and authority surfaces in Agentd, the agent protocol, Control, learning artifacts, learning evaluation and intelligence admission. Those paths are evidence and integration paths; they do not transfer ownership of their facts to `utility.ndu`.

The source root contains deterministic evaluation, profile-bound scalarization, candidate quarantine, hierarchy-snapshot validation, a bounded solver, stochastic coefficient kernels, a hash-chain projection journal, a crash-bounded durable store, authenticated owner binding, operational metrics and backup/restore drill evidence types. Source existence is not activation. Exact source-head and synthetic-merge receipts remain mandatory.

## 3. Boundary, responsibilities and non-goals

Direct dependencies are `platform.types`, `cognitive.read`, `learning.ledger` and `learning.artifacts`. Authoritative projection domains are listed in Section 6. Explicitly denied capabilities are `hard_constraint_mutation`, `authority_issuance` and `physical_effect`.

Ingress is bounded, versioned and digest-bound. Unknown critical fields, stale revisions, mixed objectives, mixed generations, invalid policy, stale hierarchy snapshots, scope mismatch and authority mismatch fail closed. Non-abstain candidate malformation may be quarantined only through the V3 layered-error API; malformed or infeasible `abstain`, invalid global policy, invalid scalarization and invalid batch identity remain global failures.

Non-goals include becoming a general state store, using model prose as authority, treating a queue acknowledgement as success, silently adopting a legacy writer, or converting qualification evidence into production authority.

## 4. Internal architecture and component decomposition

The implementation is divided into:

- deterministic utility/profile/policy validation and aggregation;
- `ValidatedScalarizationProfileV1`, bound to the exact utility profile;
- V3 candidate-local quarantine with globally fail-closed `abstain`;
- authenticated hierarchy snapshot/revision validation for strict System → Domain → Agent → Episode edges;
- bounded preference solving with iteration receipts and explicit exhaustion;
- stochastic conditional-moment, covariance, coordinate-conversion and coefficient-profile kernels;
- `NduProjectionJournalV1` and `NduProjectionStoreV1`;
- `NduAuthenticatedOwnerV1` and named Agentd product owner;
- versioned external admission and replay protection;
- stochastic current/withdrawn/revoked lifecycle plus signed selection and independent evaluator evidence;
- `NduOperationalMetricsV1`, backup policy and restore-drill receipt validation.

Production-policy validation completes before owner store open, lock acquisition or durable I/O. Configuration is frozen for one owner generation. Semantic changes require a new policy, hierarchy, authority or host revision rather than hidden mutable state.

## 5. Contracts, ports and compatibility

The following lists are the exact generated projection from `docs/modules/MODULE_DOCS.json`; they are not maintained as an independent hand-written registry.

Produced contracts:

- `DomainRead::ndu_preference_projectionV1`
- `DomainRead::ndu_utility_projectionV1`
- `ModulePort::utility.ndu::control.runtime`
- `ModulePort::utility.ndu::intelligence.control`
- `ModulePort::utility.ndu::intuition.policy`
- `ModulePort::utility.ndu::prompt.optimizer`
- `NduBoundaryConditionV1`
- `NduCoefficientManifestV1`
- `NduPreferenceStateV1`
- `NduSummaryReceiptV1`
- `NduUpdateReceiptV1`

Consumed contracts:

- `DomainRead::learning_artifact_registryV1`
- `DomainRead::learning_credit_ledgerV1`
- `DomainRead::learning_episode_ledgerV1`
- `DomainRead::learning_unlearning_lineageV1`
- `DomainRead::operator_sensor_core_registryV1`
- `GoldenFixtureManifestV1`
- `ModulePort::cognitive.read::utility.ndu`
- `ModulePort::learning.artifacts::utility.ndu`
- `ModulePort::learning.ledger::utility.ndu`
- `ModulePort::platform.types::utility.ndu`
- `NduBoundaryConditionV1`
- `NduWellPosednessCertificateV1`
- `ObjectiveFunctionV1`
- `OutcomeWatermarkV1`
- `RandomStreamManifestV1`
- `RunStartSnapshotV1`

Critical protocol schemas:

- `GoldenFixtureManifestV1`
- `NduBoundaryConditionV1`
- `NduCoefficientManifestV1`
- `NduPreferenceStateV1`
- `NduSummaryReceiptV1`
- `NduUpdateReceiptV1`
- `NduWellPosednessCertificateV1`
- `ObjectiveFunctionV1`
- `OutcomeWatermarkV1`
- `RandomStreamManifestV1`
- `RunStartSnapshotV1`

Every producer validates output before publication and binds semantic fields into the declared digest scope. Every consumer validates version, bounds, producer identity, scope and digest before use. Compatibility is additive only where registered; unknown critical fields are rejected and authority interpretation never changes in place.

Rust types and canonical wire representations must retain identical meaning. Tests cover canonical ordering, digest stability, bounds, missing/unknown fields, invalid enums, stale revisions, replay drift and exact duplicate idempotence.

## 6. Data authority, persistence and migrations

Owned authoritative or rebuildable domains:

- `ndu_coefficient_manifest_v1`
- `ndu_preference_projection`
- `ndu_update_receipt_v1`
- `ndu_utility_projection`

Read-only data dependencies:

- `golden_fixture_manifest_v1`
- `learning_artifact_registry`
- `learning_credit_ledger`
- `learning_episode_ledger`
- `learning_unlearning_lineage`
- `ndu_well_posedness_certificate_v1`
- `operator_sensor_core_registry`
- `outcome_watermark_v1`
- `random_stream_manifest_v1`

For every owned domain, the registered owner is the only authoritative writer. Mutation identities are idempotent only for identical semantics and conflict on reuse with different content. Records bind schema, source identity, logical sequence, objective, subject, predecessor and lineage sufficient for correction, deletion and revocation.

`NduProjectionJournalV1` is the bounded semantic journal. `NduProjectionStoreV1` uses one live writer lock, complete-image temporary write, file synchronization, atomic rename and Unix parent-directory synchronization. Rename success followed by directory-sync failure returns `Indeterminate` and poisons the handle until reopen. Store open rejects non-directories, symlinks, non-regular files, oversized images, corruption and truncation before unbounded allocation.

Backup restore validates the complete image and rejects regression. Older valid backups may not remove later records or resurrect revocation. Schema and owner-binding migrations are explicit and reviewed; a nonempty legacy store is never silently adopted.

## 7. Runtime, concurrency and transaction model

The named process bootstrap is `codex-hepta-agentd --ndu-bootstrap-descriptor <absolute-path> --ndu-bootstrap-descriptor-digest <sha256>`. The descriptor binds agent identity, canonical private paths, authority signer/key, independent revocation distributor/key, signed feed location and complete bounded policy.

`AgentdNduOwnerHostV1` is the named writer for one Fleet generation. Context, prepare, apply, selection and outcome use the existing bounded control socket. Prepare returns an unsigned final-use binding at an exact journal head; it does not authorize a write. Apply requires an externally signed matching grant, exact expected head, current fence and current independently authenticated revocation view. The final lifecycle guard is rechecked at physical mutation entry.

External admission V2 binds caller, request, idempotency key, issue/deadline time, host generation, fence, revocation head, payload digest and critical extensions. Exact replay is idempotent; semantic drift under the same identity conflicts. Product replay state is bounded. Durable outcome reconciliation uses mutation identity and journal history rather than blind grant replay.

## 8. Failure semantics, recovery and rollback

Failures are classified as rejected, unavailable, busy, indeterminate, quarantined or terminally failed. Candidate quarantine never converts malformed `abstain` or malformed global policy into success. Solver exhaustion is unavailable, not convergence. `Busy` means another writer owns the store. `Indeterminate` means rename may have committed without acknowledged directory durability and requires close/reopen/reconcile.

The fault matrix covers temporary write, file sync, rename, post-rename directory sync, process kill at every persistence cut, writer contention, corrupt/truncated journal, restore regression, disk full and read-only filesystem. Real child-process kill tests exercise the same persistence path; production acceptance repeats them on the selected target filesystem.

Rollback fences the active generation, preserves the journal and receipts, verifies binary/schema compatibility and reopens without automatic legacy adoption. Crossing an authority epoch, policy, owner binding or schema boundary requires an explicit migration.

## 9. Security, privacy and threat controls

Owned threats are `parent_child_NDU_oscillation`, `preference_state_goal_drift` and `recursive_utility_instability`. Controls are least authority, bounded input, exact semantic digests, independent revocation trust, generation fencing, external final-use signatures and deny-all advisory outputs.

Credentials, raw grants, signatures and sensitive utility inputs never enter general metrics, learning datasets or prompt factors. Negative tests cover forged/revoked keys, stale heads, purpose substitution, replay drift, unknown critical extensions, oversize input, scope escape and revocation resurrection.

## 10. Performance, capacity and hot-path policy

Registered source bounds include 128 candidates, 4096 contributions, eight utility dimensions, bounded risk/resource dimensions, bounded required organs, a bounded preference solver and a 4096-record journal with revocation capacity reserved for every live projection.

Named-host qualification measures the exact 32-candidate × 8-organ workload for 100 runs and records p50/p95/p99 latency. Current acceptance thresholds are p95 ≤ 2 ms and p99 ≤ 5 ms for that fixture. It also exercises maximum candidate/contribution capacity, full-envelope revocation, restart recovery, bounded oversized-image rejection and process resource observations.

## 11. Observability and operations

`NduOperationalMetricsV1` provides monotonic counters and bounded gauges for:

- evaluation count, total/max latency and host p50/p95/p99;
- convergence runs, iterations and exhaustion;
- candidate rejection and quarantine;
- store `Busy` and `Indeterminate`;
- reopen and restore failure;
- journal bytes and verified backup age.

`NduBackupPolicyV1` binds policy revision, minimum/retained copies, maximum age, off-host destination digest and encryption-profile digest. `NduRestoreDrillReceiptV1` binds source/restored journal heads, backup digest, immutable off-host object version, operator, target host, timestamps, size and record count. Validation fails closed on stale backup, identity/time regression, head mismatch or failed drill.

The complete startup, metric, backup, retention, restore, incident and promotion procedure is in [OPERATOR_RUNBOOK.md](OPERATOR_RUNBOOK.md). Repository tests validate local semantics and evidence shapes; they do not prove that a production object store, KMS, protected clock or network transfer occurred.

## 12. Verification and qualification

The dedicated workflow executes six independent suites on both source-head and a deterministic synthetic merge:

- source identity, lock/source policy, closed-world map and format;
- NDU core, authority, independent convergence/well-posedness, stochastic admission, current artifacts, signed evidence and value-learning tests;
- Control caller regressions;
- protocol, normal binary, named owner and normal process tests;
- strict selected-package/all-target Clippy with `-D warnings` and no unrelated dependency lint debt;
- fault cuts and named-host qualification.

Every suite writes a receipt containing source SHA/tree, parents, host/kernel, commands, exit codes and log hashes. Source-head and synthetic-merge artifacts are retained separately. A cancelled, skipped, stale or identity-mismatched run is not a pass.

The closed-world validator treats the primary and extension implementation maps as one inventory, verifies exact candidate SHA/tree, real native/test symbols, all tracked Rust source files and this guide's exact registry projection.

Execution specifications are [NDU_SYSTEM_EXECUTION.md](../../readiness/NDU_SYSTEM_EXECUTION.md) and [NDU_FBSDE_SPEC.md](../../learning/NDU_FBSDE_SPEC.md). The module implementation dossier is [utility.ndu.md](../../../qualification/module-execution-dossiers/detail/utility.ndu.md).

## 13. Implementation sequence and work packages

Applicable work packages are:

- `NDU-0-PREFERENCE-UTILITY-CONTRACTS`;
- `NDU-1-DETERMINISTIC-UTILITY-BASELINE`;
- `NDU-2-AGENT-DOMAIN-HIERARCHY`.

Contract and policy validation precede owner open. Deterministic semantics precede product composition. Product composition precedes target-host fault qualification. Target-host qualification and independent evidence precede activation. No work package widens authority merely by becoming source-complete.

## 14. Activation, compatibility and retirement

Current source contains request-local read-only callers, a named authenticated owner candidate, a selected local durable writer path, external admission, stochastic lifecycle composition and independent-evidence validation. Production activation remains stronger: it requires governed enrollment, protected time/key/frontier, selected off-host backup, current restore drill, exact receipts, operator acceptance and release approval.

Compatibility adapters are temporary. Retirement requires every named caller migrated, no old path use, historical record interpretability and a rehearsed rollback. A source library, fixture or GitHub runner is never substituted for a target host.

## 15. Definition of module completion

Documentation completion requires this guide, exact registry agreement and closed-world validation. Source completion requires code in the declared root and exact-candidate tests. Product composition requires the named authenticated caller/owner, selected writer, host fence, revocation feed and bounded external admission. Operational completion requires target-host fault receipts, metrics export, retention, verified off-host backup and restore drill. Qualification, acceptance, selection, promotion and release remain separate governed states.

For `utility.ndu`, this guide grants no runtime, production, model, provider, tool, network, filesystem, secret, fleet, acceptance, promotion or release authority.

<!-- BEGIN GENERATED EXACT REGISTRY PROJECTION -->
### Exact closed-world registry projection

This projection is generated from the canonical registries and is intentionally identical to Sections 5 and 6.

**Produced contracts:**
- `DomainRead::ndu_preference_projectionV1`
- `DomainRead::ndu_utility_projectionV1`
- `ModulePort::utility.ndu::control.runtime`
- `ModulePort::utility.ndu::intelligence.control`
- `ModulePort::utility.ndu::intuition.policy`
- `ModulePort::utility.ndu::prompt.optimizer`
- `NduBoundaryConditionV1`
- `NduCoefficientManifestV1`
- `NduPreferenceStateV1`
- `NduSummaryReceiptV1`
- `NduUpdateReceiptV1`

**Consumed contracts:**
- `DomainRead::learning_artifact_registryV1`
- `DomainRead::learning_credit_ledgerV1`
- `DomainRead::learning_episode_ledgerV1`
- `DomainRead::learning_unlearning_lineageV1`
- `DomainRead::operator_sensor_core_registryV1`
- `GoldenFixtureManifestV1`
- `ModulePort::cognitive.read::utility.ndu`
- `ModulePort::learning.artifacts::utility.ndu`
- `ModulePort::learning.ledger::utility.ndu`
- `ModulePort::platform.types::utility.ndu`
- `NduBoundaryConditionV1`
- `NduWellPosednessCertificateV1`
- `ObjectiveFunctionV1`
- `OutcomeWatermarkV1`
- `RandomStreamManifestV1`
- `RunStartSnapshotV1`

**Typed protocols:**
- `GoldenFixtureManifestV1`
- `NduBoundaryConditionV1`
- `NduCoefficientManifestV1`
- `NduPreferenceStateV1`
- `NduSummaryReceiptV1`
- `NduUpdateReceiptV1`
- `NduWellPosednessCertificateV1`
- `ObjectiveFunctionV1`
- `OutcomeWatermarkV1`
- `RandomStreamManifestV1`
- `RunStartSnapshotV1`

**Owned data domains:**
- `ndu_coefficient_manifest_v1`
- `ndu_preference_projection`
- `ndu_update_receipt_v1`
- `ndu_utility_projection`

**Read data domains:**
- `golden_fixture_manifest_v1`
- `learning_artifact_registry`
- `learning_credit_ledger`
- `learning_episode_ledger`
- `learning_unlearning_lineage`
- `ndu_well_posedness_certificate_v1`
- `operator_sensor_core_registry`
- `outcome_watermark_v1`
- `random_stream_manifest_v1`

**Work packages:**
- `NDU-0-PREFERENCE-UTILITY-CONTRACTS`
- `NDU-1-DETERMINISTIC-UTILITY-BASELINE`
- `NDU-2-AGENT-DOMAIN-HIERARCHY`

**Owned threats:**
- `parent_child_NDU_oscillation`
- `preference_state_goal_drift`
- `recursive_utility_instability`

<!-- END GENERATED EXACT REGISTRY PROJECTION -->

## 16. V8.2 pre-coding implementation-readiness overlay

Mandatory readiness specifications are [SOURCE_BASELINE_AND_BRANCH_POLICY.md](../../readiness/SOURCE_BASELINE_AND_BRANCH_POLICY.md), [PARALLEL_DEVELOPMENT.md](../../readiness/PARALLEL_DEVELOPMENT.md) and [NDU_SYSTEM_EXECUTION.md](../../readiness/NDU_SYSTEM_EXECUTION.md). Owned readiness protocols are `NduIterationReceiptV1` and `UtilityContributionV1`; consumed readiness protocols are `NduConvergenceCertificateV1`, `ObjectiveCompileReceiptV1` and `ObjectiveConstraintSetV1`.

Ordinary repository coding does not receive runtime authority from an execution envelope. Runtime admission still verifies exact source, frozen contract/readiness digest, expiry and zero authority delta.

## 17. Source implementation receipt

The bootstrap source-location obligation is implemented in `codex-rs/hepta-ndu`. Source-head and deterministic synthetic-merge qualification, closed-world source mapping, package tests, strict lint, clean-tree checks and retained receipts are required for each candidate. A workflow definition or pending run is not a passing receipt. Source evidence grants no activation, operator acceptance, selection, promotion, merge or release authority.
