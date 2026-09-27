# learning.plasticity developer quickstart

This guide is for source development and repository qualification. It does not
activate plasticity, select a candidate, apply topology, approve a target host or
authorize release. The only production-side mutable owners remain inside the
long-lived Agentd plasticity runtime.

## 1. Read the boundaries first

Read, in order:

1. [`TECHNICAL.md`](TECHNICAL.md) — stable architecture and authority ceiling;
2. [`CURRENT_IMPLEMENTATION.md`](CURRENT_IMPLEMENTATION.md) — current source truth;
3. [`OPERATIONS.md`](OPERATIONS.md) — host, recovery and stop conditions;
4. [`IMPLEMENTATION_MAP.json`](IMPLEMENTATION_MAP.json) — machine source/test map;
5. this file — repeatable development examples and commands.

The core rule is simple: plasticity may generate and durably record next-snapshot
proposals. It cannot select, train/install, activate, promote or release them.

## 2. Minimal parameter proposal flow

A real control-engineering caller starts from one validated `IterationEnvelopeV1`
and freezes all of the following before submission:

```text
exact base commit/tree
+ objective digest
+ MutationGrammarManifestV1 semantic digest
+ selected artifact and proposal window
+ baseline and exact-successor generation
+ expected learnable parameter inventory
+ current ArtifactRegistry / DurableLedger / owner-evidence frontiers
+ deterministic scale policy and parameter signals
+ independent Generator / Observer / Evaluator evidence
```

The source sequence is:

```rust,no_run
// 1. Project the control.engineering grammar into an authority-free allowlist.
let policy = build_parameter_mutation_policy_v1(
    policy_id,
    iteration_envelope.grammar_digest,
    selected_artifact_digest,
    window.clone(),
    mutation_rules,
)?;

// 2. Generate every unique candidate in the declared bounded V3 search.
let profile = ParameterGeneratorProfileV3 {
    selected_artifact_digest,
    window: window.clone(),
    norm_layers,
    mutation_policy: policy,
    update_scales,
    signals,
};
let generated = generate_parameter_candidates_v3(profile.clone())?;

// 3. Account for the entire expected learnable inventory. Empty signals and
//    disabled scales are dedicated terminals, not ordinary no-update results.
let coverage = build_generator_coverage_receipt_v1(
    &profile,
    expected_learnable_parameter_set_digest,
    expected_parameter_count,
    owner_frontier_digest,
    missing_parameters,
)?;

// 4. Derive an idempotent proposal identity from the frozen envelope,
//    generation and exact semantics; then collect independent signatures.
request.proposal_id = parameter_iteration_proposal_id_v1(
    &iteration_envelope,
    &coverage,
    &request,
)?;

// 5. Submit through the state-held AgentdLearningPlasticityProducerV1. The
//    producer owns only a bounded handle; final owner/frontier/trust/anchor
//    verification remains inside PlasticityRuntimeOwnerV1.
```

Expected success evidence consists of:

- `GeneratorCoverageReceiptV1`;
- `ParameterPlasticityProductReceiptV1`;
- `SelfIterationParameterReceiptV1`;
- the parameter registry frame and externally committed anchor named by those receipts.

`GeneratorCoverageDispositionV1::Incomplete` is never admissible. A
`ZeroEligibleSignals` or `PolicyDisabledUpdates` result requires its exact signed
terminal context and must not be relabeled as an update candidate.

## 3. Minimal topology proposal flow

Topology construction starts with exactly one no-change candidate and one bounded
candidate per typed operation. Every update must carry capability typing,
compatibility, lesion/ablation, resource, security, migration, rollback,
writer-handoff and evidence digests.

```rust,no_run
let proposal_id = topology_iteration_proposal_id_v1(&iteration_envelope, &request)?;
request.proposal_id = proposal_id;

// Generator, Observer and Evaluator attestations are verified by the product
// adapter. A typed WriterHandoffPlanV1 is required for every update.
// Submission goes through the named Agentd producer and durable topology registry.
```

Expected success evidence consists of:

- `TopologyPlasticityProductReceiptV1`;
- `SelfIterationTopologyReceiptV1`;
- the governed topology record, original append frame and committed anchor;
- for a later canary, an independently authenticated observation chain.

An accepted canary is still not topology-apply authority. Healthy replacement and
stopped/quarantined recovery consume distinct single-use FinalUse grants in the
external runtime owner.

## 4. Local source verification

Run from the repository root:

```bash
python3 scripts/test_learning_plasticity_contract.py
cargo fmt --all -- --check
cargo test -p codex-hepta-plasticity
cargo test -p codex-hepta-intelligence plasticity
cargo test -p codex-hepta-agentd plasticity
cargo clippy -p codex-hepta-plasticity -p codex-hepta-intelligence \
  -p codex-hepta-agentd --all-targets --all-features -- -D warnings
python3 scripts/hepta-module-docs.py refresh-derived --check
python3 scripts/hepta-docs.py verify
```

The repository CI dependency planner remains the source of truth for reverse
consumers; the commands above are the focused inner loop, not a substitute for
`CI required`, `Architecture required` or Lane-F qualification.

## 5. Recovery and fault-injection checks

Focused tests include:

```bash
cargo test -p codex-hepta-plasticity \
  resume_unacknowledged_bootstrap_repairs_only_pre_frame_crash_state
cargo test -p codex-hepta-intelligence \
  anchor_commit_failure_poison_writer_after_durable_append
cargo test -p codex-hepta-agentd \
  real_append_ack_crash_then_registry_rollback_is_rejected_on_restart
cargo test -p codex-hepta-agentd \
  agentd_lifetime_owner_submits_restarts_and_reconciles_idempotently
cargo test -p codex-hepta-runtime \
  authenticated_canary_forces_live_fault_then_rolls_forward_to_reconciled_predecessor_semantics
```

Never “repair” a complete invalid frame, invent an anchor from a suspect registry,
issue a new fence to skip an interrupted generation, or retry a poisoned writer.
Preserve the bytes and reconcile against the independently retained anchor.

## 6. Common failures

| Failure | Meaning | Correct action |
| --- | --- | --- |
| `IncompleteCoverage` | expected learnable inventory is not fully accounted for | freeze submission; obtain missing owner/policy evidence |
| `ProposalIdentity` | envelope/generation/semantics do not match the derived id | rebuild from the exact frozen inputs |
| `InvalidDeadline` / `DeadlineExceeded` | request deadline is absent, extended or elapsed | issue a new bounded attempt; do not reuse stale evidence |
| `BudgetExceeded` | encoded/work estimate exceeds the owner ceiling | narrow the declared profile; never bypass the queue |
| `AnchorPersistenceFailed` / `Poisoned` | append outcome cannot be safely acknowledged | discard handle and perform anchored reconciliation |
| `AcknowledgedHistoryMissing` | registry rolled behind an external acknowledgement | stop and perform operator recovery |
| owner/frontier drift | source facts changed after preparation | regenerate and independently reevaluate |

## 7. Exact-head evidence artifact

CI generates, but does not commit, an expiring status artifact:

```bash
python3 scripts/hepta-learning-plasticity-status.py \
  --output /tmp/learning-plasticity-exact-head.json \
  --receipt contract=/tmp/contract-test.log \
  --receipt plasticity=/tmp/plasticity-test.log
```

The artifact binds the exact commit/tree, implementation-map digest, host-profile
digest, workflow run, command receipts and expiry. `not_observed`, `queued` or
failed workflow states remain non-success. Target-host execution, physical
rollback-domain independence, independent acceptance, activation and release stay
false unless separately issued external receipts prove them.

## 8. Target-host qualification checklist

A target host is not qualified until all items are evidenced for one frozen source:

- `CI required` and `Architecture required` succeeded for the exact SHA;
- exact-head build, tests and strict lint succeeded;
- deterministic synthetic-merge tests succeeded;
- Agentd process E2E and Lane-F qualification succeeded;
- the live topology cutover, forced fault and separately authorized recovery canary succeeded;
- registry and anchor journal identities prove physically independent rollback domains;
- file and parent-directory durability was fault tested on the selected filesystem;
- queue, verification, append and anchor timing telemetry is retained;
- operator recovery drill and independent semantic/security review are accepted.

Only the external deployment/acceptance authorities may change activation or
release state.
