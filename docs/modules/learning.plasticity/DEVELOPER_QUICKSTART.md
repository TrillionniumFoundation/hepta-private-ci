# learning.plasticity developer quickstart

This guide is the shortest executable route through the current governed
plasticity source. It supplements `TECHNICAL.md`, `CURRENT_IMPLEMENTATION.md` and
`OPERATIONS.md`; it does not replace their authority, persistence or deployment
requirements. Runtime quota, cache, shutdown and crash-recovery invariants are
specified in [RUNTIME_RESOURCE_RECOVERY.md](RUNTIME_RESOURCE_RECOVERY.md).

The module is proposal-only. None of the examples below select, install, activate,
promote or release a parameter or topology candidate.

## 1. Read the boundary first

The normal parameter path is:

```text
control.engineering IterationEnvelopeV1
  -> exact MutationGrammarManifestV1 semantic digest
  -> ParameterMutationPolicyV1 projection
  -> current artifact/window/generation and owner evidence
  -> generate_parameter_candidates_v3
  -> GeneratorCoverageDraftV1
  -> independent Observer coverage attestation
  -> independent candidate evaluation or no-update attestation
  -> ControlEngineeringPlasticityCoordinatorV1
  -> Agentd state-held named producer
  -> long-lived PlasticityRuntimeOwnerV1
  -> authenticated product adapter
  -> proposal registry append
  -> independent anchor commit
  -> create-only control.engineering terminal receipt
```

The topology path stops at a governed proposal and structural-canary observation.
Only the separate runtime owner may apply an independently accepted topology under
a distinct single-use FinalUse grant.

## 2. Minimal parameter proposal

The example uses one learnable parameter, one norm layer and one positive scale.
All digests stand for independently obtained facts; replacing a digest with a
non-zero placeholder is suitable only for a unit fixture.

```rust
use codex_hepta_plasticity::{
    LayerNormDenominatorV2, ParameterGeneratorProfileV3,
    ParameterMutationRuleV1, ParameterMutationSurfaceV1,
    ParameterPlasticitySignalV3, ProposalWindowV2,
    build_parameter_mutation_policy_v1, generate_parameter_candidates_v3,
};
use codex_hepta_types::{Digest32, FixedQ32, StableId};

let artifact = Digest32::of_bytes(b"selected-artifact");
let window = ProposalWindowV2 {
    window_id: StableId::new("window:example")?,
    window_digest: Digest32::of_bytes(b"frozen-window"),
};
let grammar_digest = Digest32::of_bytes(b"canonical-mutation-grammar");
let policy = build_parameter_mutation_policy_v1(
    StableId::new("policy:example")?,
    grammar_digest,
    artifact,
    window.clone(),
    vec![ParameterMutationRuleV1 {
        parameter_id: StableId::new("parameter:adapter")?,
        layer_id: StableId::new("layer:adapter")?,
        surface: ParameterMutationSurfaceV1::LearnableParameter,
        minimum_delta: FixedQ32::from_raw(-(1_i64 << 24)),
        maximum_delta: FixedQ32::from_raw(1_i64 << 24),
    }],
)?;
let profile = ParameterGeneratorProfileV3 {
    selected_artifact_digest: artifact,
    window,
    norm_layers: vec![LayerNormDenominatorV2 {
        layer_id: StableId::new("layer:adapter")?,
        baseline_squared_l2_raw_q64: 1_u128 << 64,
    }],
    mutation_policy: policy,
    update_scales: vec![FixedQ32::ONE],
    signals: vec![ParameterPlasticitySignalV3 {
        layer_id: StableId::new("layer:adapter")?,
        parameter_id: StableId::new("parameter:adapter")?,
        eligibility: FixedQ32::ONE,
        modulator: FixedQ32::ONE,
        learning_rate: FixedQ32::from_raw(1_i64 << 20),
        lower_bound: FixedQ32::from_raw(-(1_i64 << 24)),
        upper_bound: FixedQ32::from_raw(1_i64 << 24),
        evidence_digest: Digest32::of_bytes(b"owner-bound-signal-evidence"),
    }],
};
let generated = generate_parameter_candidates_v3(profile.clone())?;
```

Before submission, build `GeneratorCoverageDraftV1` with the exact expected
learnable set. Every expected parameter omitted from `profile.signals` needs one
`GeneratorCoverageGapV1` with a non-zero, content-addressed reason. An empty signal
set produces `ZeroEligibleSignals`; a non-empty signal set with no enabled scales
produces `PolicyDisabledUpdates`; neither is collapsed into ordinary
`NoAdmissibleUpdate`.

The independent Observer signs
`generator_coverage_observer_payload_v1(&coverage_draft)`. The same trusted
Observer identity must sign the admission frontier. The coordinator rejects a
coverage signature from a different principal or controller.

## 3. Minimal topology proposal

Each update candidate contains exactly one typed operation and one exact writer
handoff. The following fixture proposes replacement but does not apply it:

```rust
use codex_hepta_plasticity::{
    ProposalWindowV2, TopologyChangeV2, TopologyOperationV2,
    TopologyProposalRequestV2, build_writer_handoff_plan_v1,
    propose_topology_v2,
};

let handoff = build_writer_handoff_plan_v1(
    StableId::new("module:adapter")?,
    StableId::new("owner:old")?,
    StableId::new("owner:new")?,
    7,
    8,
    Digest32::of_bytes(b"source-store"),
    Digest32::of_bytes(b"migration"),
    Digest32::of_bytes(b"rollback"),
    Digest32::of_bytes(b"acknowledgement-contract"),
)?;
let artifact = Digest32::of_bytes(b"selected-artifact");
let proposal = propose_topology_v2(TopologyProposalRequestV2 {
    proposal_id: StableId::new("topology:proposal:example")?,
    proposer_id: StableId::new("generator:example")?,
    evaluator_id: StableId::new("evaluator:example")?,
    selected_artifact_digest: artifact,
    window: ProposalWindowV2 {
        window_id: StableId::new("window:example")?,
        window_digest: Digest32::of_bytes(b"frozen-window"),
    },
    baseline_generation: Generation::new(7)?,
    candidate_generation: Generation::new(8)?,
    evaluation_digest: Digest32::of_bytes(b"independent-evaluation"),
    rollback_predecessor_digest: artifact,
    changes: vec![TopologyChangeV2 {
        module_id: StableId::new("module:adapter")?,
        operation: TopologyOperationV2::Replace,
        predecessor_digest: Some(Digest32::of_bytes(b"old-module")),
        candidate_digest: Some(Digest32::of_bytes(b"new-module")),
        capability_typing_digest: Digest32::of_bytes(b"capability-typing"),
        compatibility_plan_digest: Digest32::of_bytes(b"compatibility-plan"),
        lesion_ablation_digest: Digest32::of_bytes(b"lesion-ablation"),
        resource_review_digest: Digest32::of_bytes(b"resource-review"),
        security_review_digest: Digest32::of_bytes(b"security-review"),
        migration_digest: handoff.migration_digest,
        rollback_digest: handoff.rollback_digest,
        writer_handoff_digest: handoff.plan_digest,
        evidence_digest: Digest32::of_bytes(b"topology-evidence"),
    }],
})?;
```

The product adapter must authenticate Generator, Observer and Evaluator roles,
call `admit_governed_topology_v1`, append the complete governed record and commit
the external anchor. `StructuralCanaryControllerV1` observes a candidate only; it
has no topology-application method.

## 4. Runtime submission with deadline and cancellation

The compatibility APIs assign a bounded default deadline and recommended work
budget. New callers should pass an explicit context:

```rust
use codex_hepta_agentd::{
    PlasticityRuntimeRequestContextV1, recommended_parameter_budget_v1,
};
use tokio_util::sync::CancellationToken;

let budget = recommended_parameter_budget_v1(&product_request)?;
let context = PlasticityRuntimeRequestContextV1::new(
    evidence_time_unix_seconds,
    absolute_deadline_unix_seconds,
    budget,
    CancellationToken::new(),
)?;
let outcome = handle
    .propose_parameter_with_context(product_request, context)
    .await?;
println!("queue wait: {} us", outcome.timing.queue_wait_micros);
```

Parameter and topology requests use separate bounded queues with alternating
preference. Synchronous signature, registry and fsync work runs on Tokio's
blocking pool. A cancelled or expired queued request is discarded before expensive
work; once a durable append has begun, callers reconcile through proposal and
terminal-receipt idempotency rather than assuming cancellation undid the write.

## 5. Local verification commands

Run from the repository root:

```bash
python3 scripts/test_learning_plasticity_grammar_contract.py
python3 scripts/hepta-docs.py verify
python3 scripts/hepta-module-docs.py refresh-derived --check
python3 scripts/hepta-implementation-maps.py verify
```

Run native checks from `codex-rs/`:

```bash
cargo fmt --manifest-path Cargo.toml \
  --package codex-hepta-plasticity \
  --package codex-hepta-learning-artifacts \
  --package codex-hepta-agentd -- --check

cargo check --locked --all-targets \
  -p codex-hepta-plasticity \
  -p codex-hepta-learning-artifacts \
  -p codex-hepta-agentd

just test --locked -p codex-hepta-plasticity \
  -p codex-hepta-learning-artifacts --test-threads=1
just test --locked -p codex-hepta-agentd --lib plasticity_ --test-threads=1
just test --locked -p codex-hepta-agentd \
  --test plasticity_process_e2e --test-threads=1
just test --locked -p codex-hepta-runtime \
  authenticated_canary_forces_live_fault_then_rolls_forward_to_reconciled_predecessor_semantics \
  --test-threads=1

cargo clippy --locked --all-targets \
  -p codex-hepta-plasticity \
  -p codex-hepta-learning-artifacts \
  -p codex-hepta-agentd -- -D warnings
```

The protected qualification workflow executes the same source-head checks and a
deterministic synthetic merge-tree run. A queued or skipped workflow is not a
passing receipt.

## 6. Fault-injection cases

Use the named tests rather than editing completion flags:

| Fault | Expected result |
| --- | --- |
| candidate order permutation | identical generated set and digest |
| one coverage frontier/digest mutation | `DigestMismatch` |
| malformed registry bytes | typed error, never panic |
| external anchor commit failure | writer becomes poisoned |
| retained anchor plus rolled-back registry | reopen rejects missing acknowledged history |
| complete unacknowledged frame | preserved and rejected for reconciliation |
| incomplete final crash tail | repaired only after every complete predecessor validates |
| stale generation or readiness fence | runtime returns unavailable/fenced |
| expired deadline | request rejected before expensive work |
| caller cancellation while queued | request discarded before admission |
| registry and anchor hard-link alias | storage-domain qualification rejects `Alias` |
| identical mount and snapshot domain | qualification rejects `SameRollbackDomain` |

## 7. Expected receipts

A successful parameter self-iteration produces three separate facts:

1. `ParameterPlasticityProductReceiptV1`: authenticated proposal, registry frame,
   committed proposal-registry anchor and deny-all authority;
2. `GeneratorCoverageReceiptV1`: expected set, actual signal set, omitted reasons,
   scale policy, grammar, artifact/window, owner frontiers and verified Observer;
3. `ControlEngineeringParameterIterationReceiptV1`: exact envelope digest,
   candidate generation, proposal ID, request digest, product composition and
   create-only terminal idempotency key.

Repository qualification also generates an expiring exact-head status page with
source commit/tree, implementation-map digest, workflow run, test receipt, host
profile digest and TTL. That page keeps `targetHostEvidence=false`,
`independentAcceptance=false`, `activation=false` and `release=false`.

## 8. Common failures

- **Envelope grammar mismatch:** the control.engineering envelope does not bind the
  exact `MutationGrammarManifestV1.semanticDigest` used by the parameter policy.
- **Coverage missing gap:** an expected learnable parameter is neither represented
  by a signal nor accompanied by one explicit disabled reason.
- **Observer mismatch:** admission and coverage were signed by different principals
  or controllers.
- **Underdeclared budget:** encoded-byte or work estimate is lower than the native
  conservative estimator.
- **Deadline exceeded:** use a new request context; do not mutate a signed envelope
  or reinterpret timeout as “not written.”
- **Anchor persistence failed:** discard the poisoned writer and reopen only against
  independently retained acknowledged history.
- **Storage identity changed:** stop; retain paths, inode/device observations and
  host mount/snapshot evidence before any repair.

## 9. Target-host qualification checklist

Repository source qualification is necessary but not deployment evidence. A
selected host must additionally record all of the following:

- exact binary/source commit and tree;
- parameter and topology registry inode/device identities;
- anchor-journal inode/device identities;
- independently derived mount identity and snapshot-domain digest for each side;
- proof that registry and anchor cannot be rewound by the same rollback action;
- `O_NOFOLLOW | O_CLOEXEC`/directory-fd open result and post-open fstat identity;
- file and parent-directory fsync telemetry;
- first append, restart, anchored reopen and idempotent replay;
- append-ack crash followed by registry-only rollback rejection;
- incomplete-tail repair and complete-frame corruption rejection;
- parameter/topology queue wait, blocking execution and total latency;
- forced live topology stop/fault, separately authorized next-generation recovery
  and independently signed canary observation;
- operator recovery exercise and incident decision;
- independent semantic/security acceptance;
- separate activation and release decisions.

Until those receipts exist and remain unexpired, production execution,
independent acceptance, activation and release remain false.
