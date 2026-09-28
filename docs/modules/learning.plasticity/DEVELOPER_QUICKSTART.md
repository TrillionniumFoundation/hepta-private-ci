# learning.plasticity developer quickstart

This guide is the shortest supported route from a frozen self-iteration envelope to
a durable plasticity terminal receipt. It supplements `TECHNICAL.md`,
`CURRENT_IMPLEMENTATION.md`, and `OPERATIONS.md`; it does not grant selection,
activation, topology-application, promotion, or release authority.

## 1. Product path at a glance

```text
IterationEnvelopeV1
  -> exact artifact/window/generation/MutationGrammarManifestV1 projection
  -> expected learnable-parameter inventory
  -> current owner-evidence frontier
  -> ParameterMutationPolicyV1
  -> ParameterGeneratorProfileV3
  -> GeneratorCoverageReceiptV1
  -> deterministic GeneratedParameterCandidateSetV3
  -> signed Generator + Observer + independent Evaluator evidence
  -> AgentdLearningPlasticityProducerV1
  -> PlasticityRuntimeOwnerV1
  -> governed parameter/topology registry append
  -> external anchor commit
  -> SelfIterationTerminalReceiptV1
```

`SelfIterationPlasticityCoordinatorV1` owns only the coordination journal. It never
receives a proposal writer. The state-held named producer owns only a bounded handle;
the long-lived runtime owner retains all mutable writers and current trust/owner
stores.

## 2. Minimum parameter proposal

A valid parameter attempt requires all of the following before submission:

1. A valid, unexpired `IterationEnvelopeV1` whose `grammar_digest` equals the exact
   `MutationGrammarManifestV1` semantic digest consumed by the parameter mutation
   policy.
2. Exact-successor `baseline_generation` and `candidate_generation`.
3. A `ParameterMutationPolicyV1` bound to the selected artifact and proposal window.
4. A nonempty expected learnable-parameter inventory. Every expected parameter must
   appear either as one exact signal or one typed, evidence-bound exclusion.
5. A `GeneratorCoverageReceiptV1` whose disposition is one of:
   `Complete`, `ZeroEligibleSignals`, or `PolicyDisabledUpdates`.
6. A regenerated V3 candidate set equal to the submitted candidate set.
7. Current dataset, update-rule, mutation-policy, NDU modulator, broadcast-policy,
   neuron eligibility, and exact parameter-signal owner evidence.
8. Signed Generator and Observer evidence plus one independent Evaluator decision for
   every update candidate. A no-update result requires an independently signed
   terminal disposition.

Illustrative construction shape:

```rust,ignore
let coverage = build_generator_coverage_receipt_v1(
    &generator_profile,
    GeneratorCoverageRequestV1 {
        expected_parameter_ids,
        exclusions,
        owner_frontier_digest,
    },
)?;

let generated = generate_parameter_candidates_v3(generator_profile.clone())?;
let request = ParameterPlasticityProductRequestV1 {
    proposal_id,
    generator_profile,
    generated,
    generator_attestation,
    admission,
    admission_attestation,
    no_change_attestation,
    evaluations,
    expected_registry_predecessor,
};

let terminal = coordinator
    .submit_parameter(
        producer_handle,
        frozen_context,
        coverage_request,
        coverage,
        request,
        now_unix_seconds,
        cancellation,
    )
    .await?;
```

The production embedding should pass the state-held
`AgentdLearningPlasticityProducerV1` boundary. The lower-level runtime handle exists
for Agentd composition and focused tests; it carries no writer or authority.

## 3. Minimum topology proposal

A topology request requires:

- the same valid envelope, exact artifact/window, and exact-successor generations;
- one typed operation per initial candidate;
- one exact `WriterHandoffPlanV1` per update;
- distinct source and destination owners;
- an advancing writer fence;
- capability typing, compatibility, lesion/ablation, resource, security, migration,
  rollback, acknowledgement, and evidence digests;
- signed Generator, Observer, and independent Evaluator evidence;
- the exact durable topology-registry predecessor.

Illustrative submission:

```rust,ignore
let terminal = coordinator
    .submit_topology(
        producer_handle,
        frozen_context,
        topology_request,
        now_unix_seconds,
        cancellation,
    )
    .await?;
```

The resulting proposal is still proposal-only. Live replacement is owned by the
external runtime executor and requires a separately issued, single-use FinalUse grant.

## 4. Local verification commands

Run from `codex-rs` unless the command says otherwise:

```bash
cargo fmt --all -- --check
cargo check --locked -p codex-hepta-plasticity -p codex-hepta-intelligence -p codex-hepta-agentd
cargo test --locked -p codex-hepta-plasticity
cargo test --locked -p codex-hepta-intelligence plasticity
cargo test --locked -p codex-hepta-agentd plasticity
cargo clippy --locked -p codex-hepta-plasticity -p codex-hepta-intelligence -p codex-hepta-agentd --all-targets -- -D warnings
```

From the repository root:

```bash
python3 scripts/hepta-docs.py verify
python3 scripts/hepta-implementation-maps.py verify
python3 scripts/learning_plasticity_contract_check.py
```

The named test identities are source anchors. Only terminal CI receipts for the exact
unchanged source and deterministic synthetic-merge trees are execution evidence.

## 5. Fault-injection cases

Focused tests cover these incident boundaries:

```bash
cargo test --locked -p codex-hepta-plasticity incomplete_tail
cargo test --locked -p codex-hepta-plasticity unacknowledged
cargo test --locked -p codex-hepta-intelligence anchor_commit_failure
cargo test --locked -p codex-hepta-agentd registry_rollback
cargo test --locked -p codex-hepta-agentd cancellation_is_only_effective_before_start
cargo test --locked -p codex-hepta-agentd global_budget_reservation_is_released_on_drop
cargo test --locked -p codex-hepta-runtime authenticated_canary_forces_live_fault
```

For filesystem qualification, repeat create/reopen/recovery with registry, anchor,
and terminal-journal files on the selected target filesystems. Verify `O_NOFOLLOW`,
post-open inode/device identity, parent-directory durability, incomplete-tail repair,
and complete-frame corruption rejection.

## 6. Expected receipts

A successful parameter update path produces:

- `GeneratorCoverageReceiptV1` with `Complete`;
- `ParameterPlasticityProductReceiptV1` with proposal, durable registry receipt,
  committed registry anchor, authentication digests, and composition digest;
- `SelfIterationTerminalReceiptV1` with `Committed`, coverage digest, composition
  digest, registry frame digest, envelope digest, request digest, generation pair,
  idempotency key, receipt digest, and journal frame digest.

An empty eligible signal set produces `ZeroEligibleSignals`. A policy with no enabled
update scales produces `PolicyDisabledUpdates`. Neither is collapsed into ordinary
`NoAdmissibleUpdate`, and neither grants activation.

A deadline that expires while work is still queued is `DeadlineExceeded`. Once the
exclusive owner marks durable work started, caller cancellation is refused; a
caller-side deadline then returns `Indeterminate` until the terminal journal and
proposal registry are reconciled.

## 7. Common failures

| Failure | Meaning | Required response |
| --- | --- | --- |
| `MissingCoverage` | An expected learnable parameter is neither signalled nor excluded | Repair the inventory; do not submit |
| `SignalExclusionOverlap` | The same parameter is both active and excluded | Reject the profile |
| `ContextMismatch` | Artifact, window, grammar, storage, or owner frontier drifted | Re-freeze from current owners |
| `BudgetExceeded` | Per-request or aggregate queued byte/work budget exceeded | Back off; do not bypass the bounded owner |
| `Cancelled` | Cancellation won before owner start | Safe to retry with the same idempotency key |
| `Indeterminate` | Deadline/worker failure occurred after owner start | Reconcile; never assume not-applied |
| `AnchorPersistenceFailed` | Registry append may exist but external acknowledgement failed | Poison writer and anchored-reopen |
| `AcknowledgedHistoryMissing` | Retained acknowledgement is ahead of registry bytes | Incident; never bootstrap fresh |
| `UnacknowledgedHistoryPresent` | Complete proposal frame exists without accepted anchor | Preserve bytes and reconcile explicitly |

## 8. Target-host qualification checklist

A deployment claim requires one frozen source SHA and its deterministic synthetic
merge tree, with all of the following terminal-success evidence:

- module document and implementation-map verification;
- locked all-target compilation, focused tests, strict Clippy, and rustfmt;
- Agentd process bootstrap and named-producer E2E;
- Lane F qualification;
- parameter and topology exact-lifetime recovery tests;
- actual live topology cutover, forced serving fault, distinct-authorized recovery,
  and authenticated Observer canary receipt;
- registry, anchor journal, and control-engineering terminal journal placed in
  declared rollback domains with recorded device/mount/snapshot identity;
- crash telemetry for append, sync, anchor commit, restart, and reconciliation;
- operator recovery drill and retained incident receipt;
- independent semantic/security review.

Repository test success proves source composition only. Target-host execution,
independent acceptance, activation, promotion, and release remain separate facts.
