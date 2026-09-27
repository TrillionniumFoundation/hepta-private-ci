# learning.plasticity developer quickstart

This guide is the shortest safe path from an independently governed iteration to a
durable parameter or topology proposal. It does **not** authorize selection,
training, installation, topology application, promotion or release. The current
runtime artifact remains immutable; all outputs are next-generation proposals.

## 1. Ownership and call path

The production source path is:

```text
control.engineering IterationEnvelopeV1
  -> ControlEngineeringPlasticityCoordinatorV1
  -> AgentdState named learning producer
  -> PlasticityRuntimeOwnerV1
  -> authenticated parameter/topology product adapter
  -> append-only proposal registry
  -> independently retained anchor/fence journal
```

The coordinator owns no registry writer. The state-held producer owns only bounded
queue handles. The long-lived Agentd owner exclusively retains the writers, trust
verifier, current ArtifactRegistry/DurableLedger handles, owner-evidence resolver
and external anchor/fence stores.

## 2. Minimal governed parameter proposal

A valid submission requires all of the following before the coordinator is called:

1. A valid, unexpired `IterationEnvelopeV1` whose objective and grammar identify the
   exact control.engineering iteration.
2. A frozen selected artifact, window and exact-successor generation.
3. A `ParameterMutationPolicyV1` projected from the canonical
   `MutationGrammarManifestV1.semanticDigest` and bound to the same artifact/window.
4. One norm denominator for every referenced layer.
5. Explicit parameter signals with exact eligibility, modulator, learning rate,
   bounds and owner-evidence digest.
6. A deterministic V3 candidate set regenerated from the profile.
7. A Generator signature over the generated-set digest.
8. An Observer signature over the exact artifact, owner-frontier and lineage facts.
9. Independent Evaluator evidence for every update candidate, or an independent
   terminal attestation when no update exists.
10. The deterministic proposal identity returned by
    `parameter_iteration_proposal_id_v1`.

Illustrative construction order:

```rust,ignore
let generated = generate_parameter_candidates_v3(profile.clone())?;
let coverage = derive_generator_coverage_receipt_v1(
    &profile,
    admission.owner_evidence_set_digest,
)?;
let envelope_digest = iteration_envelope_digest_v1(&envelope)?;
let proposal_id = parameter_iteration_proposal_id_v1(
    envelope_digest,
    admission.candidate_generation,
    generated.generator_digest,
    coverage.coverage_digest,
)?;

let iteration = ParameterPlasticityIterationV1 {
    envelope,
    expected_learnable_parameter_set_digest:
        coverage.expected_learnable_parameter_set_digest,
    request: ParameterPlasticityProductRequestV1 {
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

let receipt = ControlEngineeringPlasticityCoordinatorV1
    .submit_parameter(&agentd_state, iteration, now)
    .await?;
```

`IncompleteSignalCoverage` is rejected. Empty signals and empty scales are not
collapsed into an ordinary no-update result; they become `ZeroEligibleSignals` and
`PolicyDisabledUpdates` terminal classes and still require the independent
no-change attestation carried by the product request.

## 3. Minimal governed topology proposal

A topology request requires:

- the same valid objective/envelope and exact-successor generation;
- a structural grammar digest equal to the envelope grammar;
- one typed operation per update candidate;
- capability typing, compatibility, lesion/ablation, resource and security reviews;
- exact migration, rollback, writer-handoff and evidence digests;
- one validated `WriterHandoffPlanV1` per change, with distinct owners and an
  advancing writer fence;
- authenticated Generator, Observer and Evaluator roles;
- a deterministic proposal identity returned by
  `topology_iteration_proposal_id_v1`.

Illustrative construction order:

```rust,ignore
let generation_digest = Digest32::of_bytes(
    &topology_generation_signing_payload_v1(&request)?,
);
let proposal_id = topology_iteration_proposal_id_v1(
    iteration_envelope_digest_v1(&envelope)?,
    request.candidate_generation,
    generation_digest,
    envelope.grammar_digest,
)?;
request.proposal_id = proposal_id;

let receipt = ControlEngineeringPlasticityCoordinatorV1
    .submit_topology(
        &agentd_state,
        TopologyPlasticityIterationV1 {
            structural_grammar_digest: envelope.grammar_digest,
            envelope,
            request,
            deadline_unix_seconds,
        },
        now,
    )
    .await?;
```

This records a proposal only. Live replacement and stopped/quarantined recovery are
separate runtime-owner operations requiring distinct single-use FinalUse grants.

## 4. Local verification commands

Run from the repository root unless noted:

```bash
python3 scripts/test_learning_plasticity_grammar_contract.py
python3 scripts/hepta-implementation-maps.py verify --expected-sha "$(git rev-parse HEAD)"
python3 scripts/hepta-technical-receipts.py verify
python3 scripts/hepta-implementation-dossiers.py verify
python3 scripts/hepta-docs.py verify

cd codex-rs
cargo fmt --all -- --check
cargo test -p codex-hepta-plasticity --all-targets --locked
cargo clippy -p codex-hepta-plasticity --all-targets --locked -- -D warnings
cargo test -p codex-hepta-agentd plasticity --all-targets --locked
cargo clippy -p codex-hepta-agentd --all-targets --locked -- -D warnings
```

Lane F and the live structural-canary regression:

```bash
cp codex-rs/Cargo.lock qualification/lane-f-shadow/Cargo.lock
cargo metadata \
  --manifest-path qualification/lane-f-shadow/Cargo.toml \
  --locked --offline --format-version 1 >/dev/null
python3 qualification/lane-f-shadow/verify_lock.py
cargo test \
  --manifest-path qualification/lane-f-shadow/Cargo.toml \
  --locked --offline
cargo test \
  --manifest-path codex-rs/Cargo.toml \
  -p codex-hepta-runtime \
  authenticated_canary_forces_live_fault_then_rolls_forward_to_reconciled_predecessor_semantics \
  --locked --offline
```

## 5. Fault-injection cases

The focused suites must cover at least:

- registry append succeeds but external anchor commit fails: writer becomes poisoned;
- retained anchor is presented with a rolled-back registry prefix: reopen fails;
- incomplete final frame: only the incomplete crash tail is repaired;
- complete unacknowledged frame: bytes are preserved and explicit reconciliation is
  required;
- stale predecessor/frame digest: append conflicts without consuming capacity;
- second process attempts the same writer lock: acquisition fails closed;
- expired/revoked/wrong-role evidence or controller collision: admission rejects;
- owner evidence has the right signature but wrong owner/frontier/value: admission
  rejects;
- queue deadline or caller cancellation before service starts: no expensive work is
  started;
- caller disappears after durable work starts: completion is counted as late and the
  deterministic proposal identity is used for reconciliation;
- structural canary safety, lineage or rollback failure: terminal abort;
- separately authorized stopped-generation recovery restores predecessor semantics.

Never inject a fault by deleting or rewriting a complete acknowledged frame.

## 6. Expected receipts

A successful parameter iteration returns a
`PlasticityIterationTerminalReceiptV1` binding:

- envelope digest;
- deterministic proposal ID and candidate generation;
- parameter/topology kind and exact terminal class;
- coverage digest for parameter proposals;
- durable registry sequence and frame digest;
- product composition digest;
- whether the append was an idempotent replay;
- terminal receipt digest.

The underlying product receipt additionally binds Generator/Observer/Evaluator
trust evidence and the independently committed registry anchor. A queue acceptance,
handler return or signed observation is not, by itself, proof of deployment,
activation or external-effect success.

The `Learning plasticity convergence` workflow retains a generated exact-head JSON
artifact containing candidate SHA/tree, workflow run identity and host profile. Its
`deploymentQualification` field remains false; target-host and operator evidence are
external gates.

## 7. Common failures

| Failure | Meaning | Required action |
| --- | --- | --- |
| `InvalidEnvelope` / `Expired` | Envelope malformed or no longer current | Freeze a new exact iteration; do not extend the old digest |
| `InvalidDeadline` | Deadline is elapsed or exceeds envelope expiry | Issue a bounded deadline inside the envelope window |
| `IncompleteCoverage` | Learnable policy parameter lacks a signal | Repair owner evidence/profile; do not relabel as no-update |
| `BudgetExceeded` | Estimated bytes/work exceed the runtime admission ceiling | Split at the control-engineering envelope, not inside the writer |
| `DeadlineExceeded` / `Cancelled` | Request did not start before the caller boundary | Reconcile deterministic proposal identity before retrying |
| `AnchorPersistenceFailed` / `Poisoned` | Registry append cannot be safely acknowledged | Freeze admission and perform anchored reopen/reconciliation |
| `AcknowledgedHistoryMissing` / `AnchorMismatch` | Registry was rolled back or mismatched | Preserve bytes and invoke operator recovery; never fresh-bootstrap |
| `UnacknowledgedHistoryPresent` | Complete frame exists without retained acknowledgement | Explicitly reconcile it; never skip the fence |
| `Binding` | Objective, grammar, artifact, window, generation or evidence drift | Rebuild the entire frozen request from current owner facts |

## 8. Target-host qualification checklist

A deployment claim requires all boxes below for one exact binary/source candidate:

- [ ] Parameter registry and its anchor journal are proven to reside in physically
      independent rollback domains.
- [ ] Topology registry and its anchor journal are proven independently as well.
- [ ] Opened-file device/inode and mount/snapshot identity are retained in the host
      qualification receipt.
- [ ] Crash points cover append, data sync, directory sync, anchor append, anchor
      sync and acknowledgement return.
- [ ] Restart telemetry proves anchored reopen, incomplete-tail repair and rejection
      of complete unacknowledged or rolled-back history.
- [ ] Queue wait, verification/service, durable append and anchor-commit timings are
      emitted with bounded IDs/digests only.
- [ ] Capacity, deadline, cancellation and overload stop policies are exercised.
- [ ] A live topology cutover is followed by a forced stopped/faulted host and a
      distinct FinalUse-authorized recovery generation.
- [ ] An independent Observer signs the resulting canary facts, with replayable raw
      telemetry and metric-version evidence available to the evaluator.
- [ ] Operator recovery drill and incident decision are retained.
- [ ] Independent semantic/security review is complete.
- [ ] Promotion, activation and release are separately authorized.

Until these external receipts exist, source implementation may be complete while
`productExecutionProved`, `independentAcceptance`, `activation` and `release` remain
false.
