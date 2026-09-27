# learning.plasticity developer quickstart

This guide is the shortest path from a frozen self-iteration envelope to an authority-free parameter or topology proposal. It complements `TECHNICAL.md`, `CURRENT_IMPLEMENTATION.md`, and `OPERATIONS.md`; it does not grant selection, installation, topology-apply, activation, promotion, or release authority.

## 1. Parameter proposal: minimum governed flow

A production caller starts from a valid `IterationEnvelopeV1` issued by `control.engineering`. Freeze the exact source artifact, proposal window, mutation grammar, baseline/candidate generations, and current owner frontier before generation.

```rust
let mutation_policy = build_parameter_mutation_policy_v1(
    policy_id,
    iteration_envelope.grammar_digest,
    selected_artifact_digest,
    proposal_window.clone(),
    learnable_parameter_rules,
)?;

let profile = ParameterGeneratorProfileV3 {
    selected_artifact_digest,
    window: proposal_window.clone(),
    norm_layers,
    mutation_policy,
    update_scales,
    signals: owner_resolved_signals,
};
let generated = generate_parameter_candidates_v3(profile.clone())?;
let coverage = build_generator_coverage_receipt_v1(
    &profile,
    owner_evidence_set_digest,
)?;
```

The current trusted Observer signs both the admission payload and `generator_coverage_signing_payload_v1(&coverage)`. Each generated update candidate receives an independently signed evaluation. A zero-update candidate set still requires the existing independent no-admissible-update attestation; `ZeroEligibleSignals` and `PolicyDisabledUpdates` are different terminal dispositions and are not collapsed into that result.

Create `ControlEngineeringParameterIterationRequestV1` with:

- the validated `IterationEnvelopeV1`;
- `freeze_parameter_context_v1(...)` output;
- the fully signed `ParameterPlasticityProductRequestV1`;
- the exact coverage receipt and Observer attestation;
- an absolute logical deadline not later than the envelope expiry.

Submit only through `ControlEngineeringIterationHandleV1::submit_parameter`. The coordinator validates the envelope and frozen context, reconciles an exact terminal replay, and then calls the state-held named Agentd producer. It never receives the proposal registry writer.

Expected committed terminal receipt:

```text
IterationPlasticityTerminalReceiptV1 {
  kind: Parameter,
  disposition: ParameterCommitted,
  envelope_digest,
  freeze_digest,
  proposal_id,
  candidate_generation,
  request_digest,
  terminal_payload_digest,
  coverage_digest,
  predecessor_frame_digest,
  frame_digest
}
```

## 2. Topology proposal: minimum governed flow

Construct a `TopologyPlasticityProductRequestV1` containing one explicit no-change candidate plus bounded typed operations. Every operation binds capability typing, compatibility, lesion/ablation, resource/security review, migration, rollback, writer handoff, and evidence digests. Each writer handoff must name distinct owners and advance the writer fence.

Generator, Observer, and Evaluator attestations are pairwise independent. Build the frozen context with `freeze_topology_context_v1(...)`, then submit `ControlEngineeringTopologyIterationRequestV1` through `ControlEngineeringIterationHandleV1::submit_topology`.

A successful coordinator receipt has `kind: Topology` and `disposition: TopologyCommitted`. It proves proposal admission and durable bookkeeping only. Application requires the separate runtime owner and an independently issued single-use `FinalUse` grant.

## 3. Local verification

From the repository root:

```bash
python3 scripts/test_plasticity_mutation_grammar_contract.py
cargo test --manifest-path codex-rs/hepta-plasticity/Cargo.toml
cargo test --manifest-path codex-rs/hepta-agentd/Cargo.toml control_engineering_iteration
cargo test --manifest-path codex-rs/hepta-agentd/Cargo.toml plasticity_process_bootstrap
cargo clippy --manifest-path codex-rs/hepta-plasticity/Cargo.toml --all-targets -- -D warnings
cargo clippy --manifest-path codex-rs/hepta-agentd/Cargo.toml --all-targets -- -D warnings
cargo fmt --manifest-path codex-rs/Cargo.toml -- --check
```

The standalone Lane-F vertical additionally runs:

```bash
cp codex-rs/Cargo.lock qualification/lane-f-shadow/Cargo.lock
cargo test --locked --manifest-path qualification/lane-f-shadow/Cargo.toml
cargo clippy --locked --manifest-path qualification/lane-f-shadow/Cargo.toml --all-targets -- -D warnings
rm qualification/lane-f-shadow/Cargo.lock
```

## 4. Fault and recovery exercises

The named tests cover these fault classes:

| Exercise | Expected result |
| --- | --- |
| Exact coordinator retry | Original terminal receipt is returned before product I/O |
| Same terminal identity with request/freeze/coverage drift | `Conflict`; no proposal append |
| Registry append succeeds but external anchor commit fails | Writer becomes `Poisoned`; no blind retry |
| Registry rolled back behind retained anchor | `AcknowledgedHistoryMissing` or `AnchorMismatch` |
| Incomplete final frame | Only the incomplete tail is repairable |
| Complete corrupt frame | Fail closed; bytes remain incident evidence |
| Queue deadline expires before start | `DeadlineExceeded`; expensive work is not started |
| Caller drops the response before start | Command is discarded and cancellation metric advances |
| Parameter queue is continuously busy | Topology queue still receives fair dequeue turns |
| Owner signal set is empty | `ZeroEligibleSignals`, not ordinary no-update |
| Grammar disables update scales | `PolicyDisabledUpdates`, not ordinary no-update |
| Owner signal set omits an expected learnable parameter | `IncompleteCoverage` with a bound omission receipt |
| Registry/anchor target-host snapshot identities match | Rollback-domain qualification fails |

Never recover a missing anchor by bootstrapping a new history. Never infer success from a queue acknowledgement, handler completion, or a proposal file without its independent anchor.

## 5. Exact-head evidence artifact

`Hepta Lane F shadow qualification` records each command with `scripts/hepta_ci_exec.py`, then invokes `scripts/hepta-plasticity-exact-head.py`. The generated Markdown and JSON are uploaded as a workflow artifact and bind:

- source SHA, tested SHA, and tested tree;
- implementation-map and host-profile SHA-256 digests;
- exact command receipts and observed test counts;
- workflow run identity;
- finite evidence validity;
- the explicit false boundary for target-host proof, independent acceptance, activation, and release.

The page is intentionally not committed because current workflow runs and their validity are dynamic external facts.

## 6. Target-host qualification checklist

Before any deployment claim, retain all of the following for the exact binary and configuration generation:

1. Parameter and topology registry paths opened without symlink/hardlink aliasing.
2. `PlasticityRollbackDomainReceiptV1` generated from an externally digest-pinned host profile.
3. Registry and anchor devices/mount identities match that profile.
4. Registry and anchor snapshot identities differ for both parameter and topology stores.
5. Crash telemetry for append-before-anchor, anchor-before-response, restart, and reconciliation points.
6. Queue wait, service time, deadline, cancellation, byte-budget, work-budget, success, and failure metrics.
7. Exact-head and deterministic merge receipts.
8. Agentd process bootstrap/restart/idempotent-replay receipt.
9. Lane-F parameter/topology proposal receipt.
10. Live topology cutover, forced fault, separately authorized recovery, serving recovery, and Observer-signed canary receipt.
11. Operator incident-recovery exercise and independent semantic/security acceptance.

Until those receipts exist, source composition may be reported, but product execution, target-host readiness, independent acceptance, activation, and release remain false.
