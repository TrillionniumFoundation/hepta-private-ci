# learning.plasticity developer quickstart

This guide is the shortest supported route from a frozen control-engineering
iteration to a governed parameter or topology proposal. It is a source-development
and qualification guide. Nothing here selects, trains, installs, activates, promotes,
deploys or releases a candidate.

## 1. Boundary in one picture

```text
IterationEnvelopeV1
  + canonical MutationGrammarManifestV1
  + exact artifact/window/generation
  + current owner evidence
  + deterministic generator
  + GeneratorCoverageReceiptV1
  + independent Generator / Observer / Evaluator evidence
      |
      v
ControlEngineeringSelfIterationCoordinatorV1
      |
      | AgentdState::submit_parameter_plasticity_v1
      v
state-held AgentdLearningPlasticityProducerV1
      |
      v
bounded PlasticityRuntimeOwnerV1
      |
      v
parameter/topology registry append -> independent anchor commit -> deny-all receipt
```

The coordinator owns only its append-only terminal journal. It never receives a
proposal-registry writer. The Agentd producer owns only bounded queue handles. The
long-lived owner alone retains writers, trust state, live owner stores and anchor
committers.

## 2. Minimal parameter proposal

A parameter iteration starts with a validated `IterationEnvelopeV1`. Compute its
canonical identity with `iteration_envelope_digest_v1`. The envelope's
`objective_digest` and `grammar_digest` must exactly match the product request.

Build the mutation policy from the control.engineering manifest projection:

```rust,ignore
let policy = build_parameter_mutation_policy_v1(
    StableId::new("policy:adapter-v1")?,
    mutation_grammar_semantic_digest,
    selected_artifact_digest,
    window.clone(),
    vec![ParameterMutationRuleV1 {
        parameter_id: StableId::new("parameter:adapter.weight")?,
        layer_id: StableId::new("layer:adapter")?,
        surface: ParameterMutationSurfaceV1::LearnableParameter,
        minimum_delta: FixedQ32::from_raw(-128),
        maximum_delta: FixedQ32::from_raw(128),
    }],
)?;
```

Construct `ParameterGeneratorProfileV3` with explicit norm denominators, positive
scales and owner-derived signals. Generate rather than hand-author the candidate set:

```rust,ignore
let generated = generate_parameter_candidates_v3(profile.clone())?;
verify_generated_parameter_candidates_v3(profile.clone(), &generated)?;
```

Construct `GeneratorCoverageReceiptV1` from the expected learnable parameter set and
actual signal set. Every expected parameter must be represented by a signal or have
one evidence-bound exclusion. Empty profiles use distinct terminal states:

- `ZeroEligibleSignals`: scales are enabled, but no eligible owner-derived signal exists;
- `PolicyDisabledUpdates`: the frozen scale policy disables updates;
- `Covered`: at least one signal and scale are present.

A generic `NoAdmissibleUpdate` receipt is not a substitute for those coverage facts.
An independent Observer signs `generator_coverage_signing_payload_v1`.

Create `CoordinatedParameterPlasticityRequestV1` from the envelope, coverage receipt,
coverage attestation and the existing `ParameterPlasticityProductRequestV1`. Submit
through `ControlEngineeringSelfIterationCoordinatorV1` and the
`AgentdSelfIterationSubmissionV1` extension. The idempotency key is exactly:

```text
(envelope_digest, candidate_generation, proposal_id)
```

The same key with the same request digest replays its durable terminal receipt. The
same key with semantic drift is a conflict. A surviving `Pending` record is
`Indeterminate` and requires reconciliation; it is never treated as permission for a
blind retry.

### Expected parameter receipts

A first successful call returns:

- `ParameterPlasticityProductReceiptV1` with the proposal, registry frame, committed
  external anchor and composition digest;
- `SelfIterationTerminalReceiptV1` in `Committed` state, binding the envelope,
  generation, proposal ID, request digest and all product durability digests.

An idempotent replay returns the terminal receipt with `replayed=true`; the product
receipt is omitted because the durable proposal registry remains its source of truth.

## 3. Minimal topology proposal

Topology construction remains proposal-only:

```rust,ignore
let proposal = propose_topology_v2(TopologyProposalRequestV2 {
    proposal_id,
    proposer_id,
    evaluator_id,
    selected_artifact_digest,
    window,
    baseline_generation,
    candidate_generation,
    evaluation_digest,
    rollback_predecessor_digest: selected_artifact_digest,
    changes: vec![TopologyChangeV2 {
        module_id,
        operation: TopologyOperationV2::Replace,
        predecessor_digest: Some(old_digest),
        candidate_digest: Some(new_digest),
        capability_typing_digest,
        compatibility_plan_digest,
        lesion_ablation_digest,
        resource_review_digest,
        security_review_digest,
        migration_digest,
        rollback_digest,
        writer_handoff_digest,
        evidence_digest,
    }],
})?;
```

Every update needs one exact `WriterHandoffPlanV1` with distinct owners, an advancing
writer fence, source-store identity, migration, rollback and acknowledgement-contract
bindings. Submit through `AgentdState::submit_topology_plasticity_v1`; never open the
registry or invoke the runtime topology executor from proposal-generation code.

A structural canary begins only from the exact durable topology proposal/candidate
binding. `StructuralCanaryControllerV1` observes signed evidence and cannot apply a
topology. Healthy replacement and stopped/quarantined recovery remain separate,
FinalUse-authorized operations in the runtime owner.

## 4. Local verification

Run from the repository root unless noted:

```bash
python3 tools/hepta-engineering-control/test_plasticity_bridge.py
python3 scripts/hepta-docs.py verify

cd codex-rs
cargo fmt --all -- --check
cargo test --locked -p codex-hepta-plasticity
cargo test --locked -p codex-hepta-agentd plasticity
cargo clippy --locked -p codex-hepta-plasticity --all-targets -- -D warnings
cargo clippy --locked -p codex-hepta-agentd --all-targets -- -D warnings
```

The cross-module test reads
`qualification/fixtures/learning.plasticity/mutation-grammar-projection-v1.json` in
both Python and Rust. A change to canonical grammar bytes, rule ordering, surface tags,
Q32 bounds or policy encoding must update the fixture intentionally in the same
reviewed change.

## 5. Fault-injection cases

Focused repository cases include:

```bash
cd codex-rs
cargo test --locked -p codex-hepta-intelligence \
  anchor_commit_failure_poison_writer_after_durable_append
cargo test --locked -p codex-hepta-agentd \
  real_append_ack_crash_then_registry_rollback_is_rejected_on_restart
cargo test --locked -p codex-hepta-agentd \
  topology_real_append_ack_crash_then_registry_rollback_is_rejected_on_restart
cargo test --locked -p codex-hepta-runtime \
  authenticated_canary_forces_live_fault_then_rolls_forward_to_reconciled_predecessor_semantics
```

The coordinator journal tests additionally cover idempotency conflicts, surviving
`Pending` state and incomplete-tail repair. Decoder/property qualification must cover
bounded arbitrary bytes, canonical order permutations, single-field digest mutation,
capacity, lock contention and long rollover/recovery sequences.

## 6. Common failures

| Failure | Meaning | Required action |
| --- | --- | --- |
| `DeadlineExceeded` | Wall-clock deadline expired; evidence time is not used as a scheduler clock | Rebuild a fresh request with a new explicit deadline |
| `BudgetExceeded` | Encoded-byte or deterministic-work ceiling exceeded | Narrow the frozen candidate profile; do not bypass the budget |
| `JournalConflict` | Same envelope/generation/proposal identity has semantic drift | Allocate a new proposal identity or reconcile the caller bug |
| `Indeterminate` | A durable `Pending` transition survived without a terminal record | Inspect proposal registry and external anchor before reconciliation |
| `GeneratorDigestMismatch` | Candidate set is not the exact deterministic regeneration | Discard caller candidates and regenerate from the frozen profile |
| `MissingCoverage` | Expected learnable parameter has neither signal nor exclusion | Repair owner-evidence/grammar projection |
| `AnchorPersistenceFailed` | Proposal append may exist but independent anchor did not commit | Poison the handle and reopen only from reconciled external history |
| `AcknowledgedHistoryMissing` | Registry was rolled back behind an external acknowledgement | Stop; preserve bytes and perform operator recovery |
| `OwnerPoisoned` | Runtime resource owner lock was poisoned | Stop the generation and recover through normal Agentd restart |

## 7. Target-host qualification checklist

A production-execution claim requires one frozen source SHA/tree and all of the
following evidence:

- `CI required` and `Architecture required` succeed on that exact candidate;
- document verification, fmt, all-target compilation, strict clippy and focused tests
  succeed on source-head and deterministic synthetic merge;
- Agentd process E2E reconstructs owner stores from independent receipts and exercises
  the state-held named producer;
- Lane F runs deterministic generation, role separation, coverage, no-update terminal,
  anchor/fence and restart/replay cases;
- live runtime canary performs cutover, forced serving fault, separately authorized
  stopped/quarantined recovery, serving verification and Observer-signed observation;
- registry and anchor journal identities include device/mount/snapshot evidence and the
  deployment proves physically independent rollback domains;
- crash/recovery telemetry reports queue wait, verification/append/anchor duration,
  registry sequence, writer fence and reconciliation result without secrets or raw
  model parameters;
- an operator executes and signs the incident-recovery drill;
- independent semantic/security review, activation, promotion, deployment and release
  remain separate decisions.

Passing source tests proves repository composition only. It does not by itself prove a
target-host run, independent acceptance, activation or release.
