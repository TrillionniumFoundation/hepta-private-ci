# learning.plasticity developer quickstart

This guide is the shortest supported route from a frozen control-engineering work
envelope to a durable plasticity terminal receipt. It does not grant candidate
selection, parameter installation, topology application, activation, promotion or
release authority.

## 1. Boundaries

The production source path is:

```text
MutationGrammarManifestV1 (control.engineering)
  -> ParameterMutationPolicyV1
  -> ParameterGeneratorProfileV3
  -> GeneratedParameterCandidateSetV3
  -> GeneratorCoverageReceiptV1 + Observer signature
  -> independent candidate evaluation
  -> ControlEngineeringPlasticityCoordinatorV1
  -> AgentdLearningPlasticityProducerV1
  -> PlasticityRuntimeOwnerV1
  -> governed proposal registry + independent anchor journal
  -> IterationPlasticityTerminalJournalV1
```

The coordinator owns only the frozen work context and terminal journal. Mutable
proposal writers, trust roots, current ArtifactRegistry/DurableLedger handles and
anchor stores remain inside the long-lived Agentd runtime owner.

## 2. Minimal parameter proposal

The exact values below are illustrative; tests must create valid signed evidence from
the repository trust fixtures rather than copying placeholder digests.

```rust
let grammar = control_engineering_manifest.semantic_digest;
let policy = build_parameter_mutation_policy_v1(
    id("policy:adapter:1"),
    grammar,
    artifact_digest,
    window.clone(),
    vec![ParameterMutationRuleV1 {
        parameter_id: id("parameter:adapter:weight"),
        layer_id: id("layer:adapter"),
        surface: ParameterMutationSurfaceV1::LearnableParameter,
        minimum_delta: FixedQ32::from_raw(-100),
        maximum_delta: FixedQ32::from_raw(100),
    }],
)?;

let profile = ParameterGeneratorProfileV3 {
    selected_artifact_digest: artifact_digest,
    window: window.clone(),
    norm_layers: vec![LayerNormDenominatorV2 {
        layer_id: id("layer:adapter"),
        baseline_squared_l2_raw_q64: 1_000_000,
    }],
    mutation_policy: policy,
    update_scales: vec![FixedQ32::ONE],
    signals: vec![ParameterPlasticitySignalV3 {
        layer_id: id("layer:adapter"),
        parameter_id: id("parameter:adapter:weight"),
        eligibility,
        modulator,
        learning_rate,
        lower_bound: FixedQ32::from_raw(-100),
        upper_bound: FixedQ32::from_raw(100),
        evidence_digest: parameter_signal_receipt_digest,
    }],
};

let generated = generate_parameter_candidates_v3(profile.clone())?;
let coverage = build_generator_coverage_receipt_v1(
    &profile,
    vec![id("parameter:adapter:weight")],
    Vec::new(),
    current_owner_frontier_digest,
)?;
```

The same trusted Observer signs both the exact admission payload and
`generator_coverage_signing_payload_v1(&coverage)`. Every generated update candidate
requires its independent Evaluator bundle. A profile with no signals uses
`ZeroEligibleSignals`; a profile with no scales uses `PolicyDisabledUpdates`. Neither
is collapsed into ordinary `NoAdmissibleUpdate`.

Freeze the work before submission:

```rust
let frozen = freeze_iteration_plasticity_context_v1(
    iteration_envelope,
    artifact_digest,
    window,
    baseline_generation,
    candidate_generation,
    now,
)?;
let mut coordinator = ControlEngineeringPlasticityCoordinatorV1::new(
    frozen,
    plasticity_runtime_handle,
    learning_evidence_verifier,
    terminal_journal_file,
    4_096,
)?;
let receipt = coordinator
    .submit_parameter(
        covered_request,
        now,
        PlasticityRuntimeRequestBudgetV1::bounded(
            4 * 1024 * 1024,
            8_192,
            deadline_unix_seconds,
        ),
        cancellation,
    )
    .await?;
```

An identical retry keyed by `(envelope_digest, candidate_generation, proposal_id)`
returns the original terminal receipt without creating another proposal history.

## 3. Minimal topology proposal

A topology update contains one typed operation and one exact writer handoff:

```rust
let handoff = build_writer_handoff_plan_v1(
    id("module:adapter"),
    id("owner:old"),
    id("owner:new"),
    predecessor_writer_fence,
    successor_writer_fence,
    source_store_digest,
    migration_digest,
    rollback_digest,
    acknowledgement_contract_digest,
)?;

let change = TopologyChangeV2 {
    module_id: id("module:adapter"),
    operation: TopologyOperationV2::Replace,
    predecessor_digest: Some(old_digest),
    candidate_digest: Some(new_digest),
    capability_typing_digest,
    compatibility_plan_digest,
    lesion_ablation_digest,
    resource_review_digest,
    security_review_digest,
    migration_digest: handoff.migration_digest,
    rollback_digest: handoff.rollback_digest,
    writer_handoff_digest: handoff.plan_digest,
    evidence_digest,
};
```

The topology product request must carry independent Generator, Observer and Evaluator
attestations. Submission goes through `ControlEngineeringPlasticityCoordinatorV1::submit_topology`.
The resulting record is a proposal only. A separate runtime owner must consume a
single-use FinalUse grant before any live topology replacement or recovery.

## 4. Local verification commands

Run from the repository root:

```bash
python3 scripts/test_learning_plasticity_grammar_contract.py
python3 -m unittest tools/hepta-engineering-control/test_mutation_grammar.py
python3 scripts/hepta-docs.py verify

cargo fmt --manifest-path codex-rs/Cargo.toml --all -- --check
cargo check --manifest-path codex-rs/Cargo.toml \
  -p codex-hepta-plasticity \
  -p codex-hepta-intelligence \
  -p codex-hepta-agentd \
  --all-targets
cargo test --manifest-path codex-rs/Cargo.toml \
  -p codex-hepta-plasticity \
  -p codex-hepta-intelligence \
  -p codex-hepta-agentd
cargo clippy --manifest-path codex-rs/Cargo.toml \
  -p codex-hepta-plasticity \
  -p codex-hepta-intelligence \
  -p codex-hepta-agentd \
  --all-targets -- -D warnings

cargo test --manifest-path codex-rs/Cargo.toml \
  -p codex-hepta-agentd --test plasticity_process_e2e
cargo test --manifest-path codex-rs/Cargo.toml \
  -p codex-hepta-runtime \
  authenticated_canary_forces_live_fault_then_rolls_forward_to_reconciled_predecessor_semantics
```

Lane F exact-head and synthetic-merge qualification remains in
`.github/workflows/hepta-lane-f-shadow-qualification.yml`. The dedicated plasticity
workflow additionally generates an expiring exact-head status artifact.

## 5. Fault injection

The focused tests cover these durable failure points:

```bash
cargo test --manifest-path codex-rs/Cargo.toml -p codex-hepta-plasticity \
  incomplete_tail_is_removed_before_recovery_returns
cargo test --manifest-path codex-rs/Cargo.toml -p codex-hepta-intelligence \
  anchor_commit_failure_poison_writer_after_durable_append
cargo test --manifest-path codex-rs/Cargo.toml -p codex-hepta-agentd \
  real_append_ack_crash_then_registry_rollback_is_rejected_on_restart
cargo test --manifest-path codex-rs/Cargo.toml -p codex-hepta-agentd \
  terminal_journal_reopens_and_replays_idempotently
```

A test may simulate an anchor commit failure, incomplete final frame, stale writer
fence, old-prefix rollback, cancellation before execution and deadline expiry. Never
convert `Indeterminate`, `Poisoned`, `AnchorPersistenceFailed` or a terminal-journal
failure after proposal commit into an ordinary retry success.

## 6. Expected receipts

A successful parameter submission returns:

- `CoveredParameterPlasticityProductReceiptV1`, binding proposal, registry frame,
  committed external anchor, generator/admission/evaluation/coverage authentication;
- `PlasticityRuntimeTelemetryV1`, binding queue wait, blocking execution duration and
  admitted byte/work estimates;
- `IterationPlasticityTerminalReceiptV1`, binding frozen envelope, generation,
  proposal identity, terminal class and product composition digest;
- deny-all authority at every receipt boundary.

A replay returns the durable terminal receipt with disposition `Replayed`; it does not
invent a second in-memory product receipt.

## 7. Common failures

| Error | Meaning | Required response |
| --- | --- | --- |
| `FreezeBinding` | artifact, window, objective, grammar or generation drift | rebuild from the current frozen envelope; do not patch the request |
| `MissingPartition` | expected learnable parameter was neither signalled nor explained | obtain owner evidence or add an evidence-backed missing reason |
| `ZeroEligibleSignals` | grammar permits updates but no eligible signal exists | preserve the explicit terminal and investigate owner evidence |
| `PolicyDisabledUpdates` | the admitted scale policy contains no update scale | preserve the explicit terminal; policy revision requires a new envelope |
| `DeadlineExceeded` | request expired before execution | issue a new envelope; do not extend the old signed deadline |
| `BudgetExceeded` | encoded-byte or work estimate exceeds admission | reduce the bounded profile or issue a new authorized budget |
| `AnchorPersistenceFailed` / `Poisoned` | registry append may exist without durable external acknowledgement | discard the writer handle and reconcile with the independently retained anchor |
| `TerminalJournalAfterCommit` | proposal committed but terminal bookkeeping did not | reconcile by proposal identity and product composition digest before resubmission |

## 8. Target-host qualification checklist

Source qualification is necessary but not deployment evidence. A selected host must
produce receipts for all of the following:

- exact source SHA and tree plus deterministic synthetic merge;
- `CI required`, `Architecture required`, document verification, strict clippy and
  focused unit/E2E tests;
- Agentd process reconstruction, restart and idempotent replay;
- Lane F deterministic vertical and live structural-canary fault/recovery test;
- registry and anchor opened with no-follow/close-on-exec protections and post-open
  file identity verification;
- parent-directory fsync for newly created registry and anchor entries;
- registry and anchor mount/device/snapshot identity proving physically independent
  rollback domains;
- crash telemetry for append, sync, anchor commit and terminal-journal commit points;
- queue wait, verification, append and anchor-commit latency telemetry;
- forced topology cutover fault followed by separately FinalUse-authorized recovery;
- operator recovery drill and independently signed observation receipt.

Generate the transient status page with:

```bash
python3 scripts/hepta-learning-plasticity-status.py \
  --output /tmp/learning-plasticity-exact-head.md \
  --workflow-receipt "CI required:<run-id>:success" \
  --workflow-receipt "Architecture required:<run-id>:success" \
  --workflow-receipt "learning.plasticity exact head:<run-id>:success" \
  --workflow-receipt "Hepta Lane F shadow qualification:<run-id>:success" \
  --test-receipt "exact-head:<sha>:passed" \
  --evidence-ttl-seconds 86400
```

Do not commit the generated page as a cached current-state claim. Upload it as an
exact-run artifact or retain it in the external evidence system.
