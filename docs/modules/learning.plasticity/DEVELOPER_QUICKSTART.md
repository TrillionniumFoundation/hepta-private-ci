# learning.plasticity developer quickstart

This guide is the shortest supported path from a frozen self-iteration envelope to
a governed parameter or topology proposal. It does not grant selection, weight
installation, topology application, promotion, deployment or release authority.
The stable requirements remain in `TECHNICAL.md`; current truth remains in
`CURRENT_IMPLEMENTATION.md` and `IMPLEMENTATION_MAP.json`.

## 1. Boundary at a glance

```text
control.engineering IterationEnvelopeV1
  -> exact objective / grammar / generation freeze
  -> expected learnable parameter set
  -> current owner evidence
  -> deterministic generator + GeneratorCoverageReceiptV1
  -> independent Generator / Observer / Evaluator evidence
  -> AgentdState named learning producer
  -> long-lived PlasticityRuntimeOwnerV1
  -> proposal registry append + independent anchor commit
  -> control.engineering terminal receipt
```

The coordinator owns the envelope and terminal bookkeeping only. It never receives
a proposal-registry writer. Agentd keeps the current artifact, learning-ledger,
owner-evidence, trust and anchor/fence owners behind a bounded runtime handle.

## 2. Minimal governed parameter proposal

The following is schematic Rust. Production callers must use current owner receipts
and real independent signatures rather than fixture digests.

```rust
let window = ProposalWindowV2 {
    window_id: StableId::new("window:next-snapshot")?,
    window_digest: current_window_digest,
};

let mutation_policy = build_parameter_mutation_policy_v1(
    StableId::new("policy:adapter")?,
    admitted_mutation_grammar_digest,
    selected_artifact_digest,
    window.clone(),
    vec![ParameterMutationRuleV1 {
        parameter_id: StableId::new("parameter:adapter")?,
        layer_id: StableId::new("layer:adapter")?,
        surface: ParameterMutationSurfaceV1::LearnableParameter,
        minimum_delta: FixedQ32::from_raw(-100),
        maximum_delta: FixedQ32::from_raw(100),
    }],
)?;

let profile = ParameterGeneratorProfileV3 {
    selected_artifact_digest,
    window: window.clone(),
    norm_layers,
    mutation_policy,
    update_scales,
    signals: current_owner_verified_signals,
};
let generated = generate_parameter_candidates_v3(profile.clone())?;
let coverage = build_generator_coverage_receipt_v1(
    &profile,
    reasoned_missing_signals,
    current_owner_frontier_digest,
)?;

let iteration = ParameterSelfIterationRequestV1 {
    envelope,
    coverage,
    product: ParameterPlasticityProductRequestV1 {
        proposal_id,
        generator_profile: profile,
        generated,
        generator_attestation,
        admission,
        admission_attestation,
        no_change_attestation,
        evaluations,
        expected_registry_predecessor,
    },
    deadline_unix_seconds,
};
```

Expected successful output:

- a `ParameterPlasticityProductReceiptV1` whose proposal and registry frame are
  exact-content bound;
- an externally committed registry anchor;
- a `SelfIterationTerminalReceiptV1` bound to envelope digest, request digest,
  candidate generation, proposal identity and idempotency digest;
- deny-all authority in the proposal receipt.

`ZeroEligibleSignals` and `PolicyDisabledUpdates` are explicit coverage dispositions.
They are not silently converted into the ordinary `NoAdmissibleUpdate` result.

## 3. Minimal governed topology proposal

```rust
let handoff = build_writer_handoff_plan_v1(
    module_id,
    predecessor_owner,
    successor_owner,
    predecessor_writer_fence,
    successor_writer_fence,
    source_store_digest,
    migration_digest,
    rollback_digest,
    acknowledgement_contract_digest,
)?;

let iteration = TopologySelfIterationRequestV1 {
    envelope,
    topology_grammar_digest: admitted_mutation_grammar_digest,
    product: TopologyPlasticityProductRequestV1 {
        proposal_id,
        generator_id,
        observer_id,
        evaluator_id,
        objective_digest,
        selected_artifact_digest,
        artifact_registry_binding,
        artifact_registry_head_digest,
        qualification_evidence_head_digest,
        window,
        baseline_generation,
        candidate_generation,
        evaluation_digest,
        rollback_predecessor_digest: selected_artifact_digest,
        changes,
        handoffs: vec![handoff],
        generator_attestation,
        observer_attestation,
        evaluator_attestation,
        expected_registry_predecessor,
    },
    deadline_unix_seconds,
};
```

A successful topology proposal is still proposal-only. Live replacement and stopped
or quarantined recovery are separate `codex-hepta-runtime` transitions and each
requires its own exact, single-use FinalUse grant.

## 4. Focused local verification

Run from the repository root:

```bash
python3 scripts/hepta-docs.py verify
python3 scripts/hepta-implementation-maps.py verify

cargo fmt --manifest-path codex-rs/Cargo.toml --all -- --check
cargo test --manifest-path codex-rs/Cargo.toml -p codex-hepta-plasticity
cargo test --manifest-path codex-rs/Cargo.toml -p codex-hepta-agentd \
  --test plasticity_grammar_contract
cargo test --manifest-path codex-rs/Cargo.toml -p codex-hepta-agentd \
  --test plasticity_process_e2e
cargo test --manifest-path codex-rs/Cargo.toml -p codex-hepta-agentd \
  agentd_lifetime_owner_submits_restarts_and_reconciles_idempotently
cargo test --manifest-path codex-rs/Cargo.toml -p codex-hepta-runtime \
  authenticated_canary_forces_live_fault_then_rolls_forward_to_reconciled_predecessor_semantics

cargo clippy --manifest-path codex-rs/Cargo.toml \
  -p codex-hepta-plasticity -p codex-hepta-agentd -p codex-hepta-runtime \
  --all-targets -- -D warnings
```

Lane F also runs its standalone exact-head and deterministic synthetic-merge profile:

```bash
cp codex-rs/Cargo.lock qualification/lane-f-shadow/Cargo.lock
cargo metadata --format-version 1 \
  --manifest-path qualification/lane-f-shadow/Cargo.toml >/dev/null
cargo test --locked --manifest-path qualification/lane-f-shadow/Cargo.toml
cargo clippy --locked --manifest-path qualification/lane-f-shadow/Cargo.toml \
  --all-targets -- -D warnings
rm qualification/lane-f-shadow/Cargo.lock
```

## 5. Fault-injection checks

The focused source tests exercise the supported crash boundaries:

```bash
cargo test --manifest-path codex-rs/Cargo.toml -p codex-hepta-plasticity \
  recovery_repairs_only_incomplete_crash_tails
cargo test --manifest-path codex-rs/Cargo.toml -p codex-hepta-plasticity \
  complete_corruption_and_second_writer_fail_closed
cargo test --manifest-path codex-rs/Cargo.toml -p codex-hepta-agentd \
  real_append_ack_crash_then_registry_rollback_is_rejected_on_restart
cargo test --manifest-path codex-rs/Cargo.toml -p codex-hepta-agentd \
  topology_real_append_ack_crash_then_registry_rollback_is_rejected_on_restart
cargo test --manifest-path codex-rs/Cargo.toml -p codex-hepta-agentd \
  journal_never_discards_a_complete_invalid_frame
```

Only an incomplete final frame may be repaired. A complete checksum, sequence,
fence, context or anchor failure remains intact and fails closed for reconciliation.

## 6. Expected receipt chain

For parameter self-iteration, retain at least:

```text
IterationEnvelopeV1 digest
GeneratorCoverageReceiptV1 digest
GeneratedParameterCandidateSetV3 generator digest
Generator attestation digest
Observer admission attestation digest
Evaluator decision or explicit terminal attestation digest
ParameterProposalV2 proposal digest
DurableProposalAppendReceiptV1 frame digest
DurableRegistryAnchorV1 frame digest
SelfIterationTerminalReceiptV1 receipt digest
```

Topology adds the governed admission digest, writer-handoff-set digest, durable
topology frame and, when separately executed, FinalUse and structural-canary receipts.

## 7. Common failures

| Failure | Meaning | Required response |
| --- | --- | --- |
| `Binding` / `ContextMismatch` | Artifact, window, objective, grammar or generation drift | Freeze a new envelope; never rewrite an acknowledged proposal |
| `MissingGap` | A learnable parameter has neither signal nor reasoned omission | Resolve owner evidence and rebuild coverage |
| `ProtectedSurface` | A mutation targets authority, evaluator, deletion, topology or credential state | Reject; do not relax the policy |
| `Overloaded` | Lane, byte or work budget is exhausted | Apply bounded backpressure; do not create another writer |
| `DeadlineExceeded` | Absolute envelope/request deadline expired | Reconcile any dispatched operation before retry |
| `AnchorPersistenceFailed` / `Poisoned` | Registry append may exist without acknowledged external anchor | Stop the handle and reopen only from independent history |
| `UnacknowledgedHistoryPresent` | Complete proposal frame exists without retained acknowledgement | Preserve bytes and perform explicit reconciliation |
| `AnchorMismatch` / `AcknowledgedHistoryMissing` | Registry history rolled back or diverged | Incident recovery; never bootstrap fresh history |

## 8. Target-host qualification checklist

Repository tests are not deployment evidence. A selected target host must retain an
exact receipt proving all of the following:

- exact source SHA and tree, exact dependency lock and clean checkout;
- `CI required`, `Architecture required`, document verification, strict lint,
  exact-head and deterministic synthetic-merge success;
- Agentd process bootstrap and lifetime E2E on the selected binary;
- Lane F exact-head and synthetic-merge qualification;
- proposal registry and anchor journal are on independently administered rollback
  domains, including device/mount/snapshot identity and restore policy;
- crash after registry append but before anchor acknowledgement is reconciled;
- incomplete tails repair and complete corrupt frames remain intact;
- queue wait, verification, durable append and anchor-commit telemetry are present;
- live topology cutover, forced stopped/faulted host, distinct FinalUse-authorized
  recovery and Observer-signed canary observation complete with production telemetry;
- operator incident-recovery exercise and independent semantic/security review.

No checklist item changes `independentAcceptance`, `activation` or `release` until its
separate external decision is issued.

## 9. Exact-head status artifact

`.github/workflows/hepta-learning-plasticity-qualification.yml` generates
`learning-plasticity-exact-head-status.json` and `.md` for the exact checked-out SHA.
The artifact records source/tree identity, implementation-map digest, workflow run,
command receipt, operating-profile digest and evidence validity window. It is an
external qualification artifact because a committed file cannot truthfully contain
the hash of the commit that contains itself.
