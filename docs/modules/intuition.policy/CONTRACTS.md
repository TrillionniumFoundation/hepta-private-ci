# intuition.policy contracts and evidence traceability

Generated from CURRENT_STATE.json by scripts/intuition_state.py. Source references are not test-pass evidence.

## Version matrix

| Contract | Layer | Status |
| --- | --- | --- |
| `CalibratedDecisionRequestV1` | Historical request shape | Still decoded; bounded and authenticated at the current product boundary. |
| `CalibratedIntuitionReceiptV1 / decide_calibrated_v2 / decide_calibrated_v3` | Compatibility receipt and entry points | Historical encodings preserved; downstream retirement remains open. |
| `ProductionIntuitionReceiptV1 / decide_calibrated_v4` | Native product risk routing | Explicit risk rule and original request; legacy digest reproduced only for compatibility. |
| `ScoringCommitmentV2 / AssignmentCommitmentV2` | Owner-separated commitments | Candidate identity, score output and assignment distribution have distinct ownership. |
| `AuthenticatedIntuitionDecisionV3` | Three-party admission | Signed generator/evaluator/observer evidence and pairwise controller separation. |
| `PreparedAgentdIntuitionDecisionV3` | Host preparation | Private in-memory original request and signed qualification with trust generation/distribution binding; not a durable handoff journal. |
| `AgentdIntuitionDecisionReceiptV2` | Host policy commit | Selected outcomes include the existing authoritative ledger append receipt. |
| `PreparedAgentdIntelligenceRunV1 / PreparedEvaluationUseV1` | Canonical selected-run preparation | Snapshot-pinned original signed evaluation session, exact input, candidate and receipt retained for final-use revalidation; private in-process state, not durable recovery or outward transport. |
| `CanonicalIntuitionAdmissionV2` | Internal Agentd result envelope | Binds policy, run and context in process; not a new wire contract or delivery acknowledgement. |
| `ObjectiveRunAdmission V1` | Existing outward transport | Unchanged; policy-receipt transport migration remains required. |

## Implemented request sequence

```text
Immutable startup profile / current signed ObjectiveStart
  -> existing canonical seven-owner preparation
  -> authenticated generator/evaluator/observer evidence
  -> native explicit risk routing / immutable host pins
  -> sole writer lock / fresh owner clock / current trust and three-role revalidation
  -> one signed seven-owner manifest / RunStart authority and source deadline fence
  -> selected original evaluation proofs and canonical deadline revalidation
  -> selected-only LedgerWriter commit with independent witness
  -> repeated canonical currentness check / final run/context admission with retained policy receipt
  -> in-process bound outcome (not a wire or durable delivery acknowledgement)
```

A post-policy failure retains the exact acknowledged receipt and its typed cause. The kernel and receipt grant no dispatch authority.
The canonical final-use callback can reject admission but receives only a read-only clock interface. The sink samples time again and revalidates policy qualification after the callback. These checks do not create a cross-owner durable transaction or restart reconciliation.

## Durable orchestration target, not a completed state machine

```text
Prepared(intent durable before effect)
  -> PolicyCommitted(owner receipt verified)
  -> RunStarted -> ContextAttached -> Delivered(explicit acknowledgement)
Any interrupted stage -> ReconcileRequired -> current-authority exact replay
Revoked/stale/unverifiable state -> Quarantined (no silent compatibility fallback)
```

Do not treat tracing output, a clean drop/reopen, or a digest-only record as durable authenticated recovery. The Agentd orchestration journal must not replace the sole authoritative learning ledger or its independent witness.

## Requirements, source tests and immutable evidence

| Requirement | Source and symbol | Test sources | Required execution evidence |
| --- | --- | --- | --- |
| `native_policy` | `codex-rs/hepta-intuition/src/production_native.rs` / `native_profile_decision` | `codex-rs/hepta-intuition/src/production_tests.rs` | Fixed-tree kernel tests, risk-rule matrix and golden vectors. |
| `authenticated_roles` | `codex-rs/hepta-intelligence/src/intuition_qualification_v3.rs` / `verify_verified_role_separation` | `codex-rs/hepta-agentd/tests/intuition_policy_product_v3.rs` | Signed product tests including distinct principals sharing one evaluator/observer controller. |
| `host_commit` | `codex-rs/hepta-agentd/src/intuition_policy.rs` / `commit_v4` | `codex-rs/hepta-agentd/tests/intuition_policy_product_v3.rs`; `codex-rs/hepta-agentd/tests/intuition_policy_commit_boundary.rs`; `codex-rs/hepta-learning-ledger/src/trust_distribution_tests.rs`; `codex-rs/hepta-agentd/src/intelligence_candidate_bound_tests.rs` | Exact-source, merge and independent boundary/trust logs for writer-wait expiry, scheduled revocation, distribution expiry, trust rotation and append; process interruption remains required. |
| `admission_receipt` | `codex-rs/hepta-agentd/src/state.rs` / `start_canonical_intelligence` | `codex-rs/hepta-agentd/src/intuition_policy_admission_tests.rs`; `codex-rs/hepta-agentd/src/intelligence_product_signed_tests.rs`; `codex-rs/hepta-agentd/src/intelligence_evaluation_tests.rs`; `codex-rs/hepta-agentd/src/intelligence_product_final_use_tests.rs`; `codex-rs/hepta-agentd/src/intelligence_objective_replay_tests.rs`; `codex-rs/hepta-agentd/src/intelligence_objective_host_replay_tests.rs` | Signed final-use, snapshot-pinned evaluation, live lifecycle and concurrent/reopened-owner retry-isolation regressions; real daemon requests, durable recovery, process-kill replay and delivery evidence remain required. |
| `authority_read` | `codex-rs/hepta-agentd/src/intelligence_authority.rs` / `fn read_manifest` | `codex-rs/hepta-agentd/src/intelligence_authority_read_tests.rs`; `codex-rs/hepta-agentd/src/intelligence_authority_snapshot_tests.rs`; `codex-rs/hepta-agentd/src/intelligence_evaluation_owner_pin_tests.rs` | Canonical intelligence_product logs for bounded growth, coherent signed-manifest fences and snapshot-pinned evaluator ownership; target-host owner-file admission still requires execution artifacts. |
| `startup_profile` | `codex-rs/hepta-agentd/src/state.rs` / `new_with_intuition_profile` | `codex-rs/hepta-agentd/src/intuition_policy_serving.rs`; `codex-rs/hepta-agentd/src/intelligence_product_tests.rs` | Default Production and explicit development tests; real process startup and restart qualification. |
| `telemetry` | `codex-rs/hepta-agentd/src/intuition_policy_serving.rs` / `agentd_error_reason` | `codex-rs/hepta-agentd/src/intuition_policy_serving.rs` | Source tests plus actual target-host exporter, audit delivery and alert observations. |
| `source_qualification` | `.github/workflows/hepta-intuition-qualification.yml` / `Intuition required` | `scripts/tests/test_intuition_exact.py` | Current same-run command records, nonzero test execution, retained binaries and agreement artifacts. |
| `source_projection` | `scripts/intuition_state.py` / `def project` | `scripts/tests/test_intuition_state.py` | Read-only projection check and adversarial generator tests on the exact candidate. |

Qualification requires the fixed source commit/tree, fixed base and recomputed merge tree, real command exit codes and logs, retained binaries, and independent same-run evidence agreement. An authoring job never supplies this acceptance.

## Digest boundaries

Generator identity/order, scorer outputs and assignment distribution remain separately committed. Product receipts bind original risk, matched profile rule, full propensities and disposition. Historical risk encoding is a read-only compatibility view; it cannot alter the request used by the native kernel.

Historical generator completeness evidence V1 still binds the V1 candidate-set digest, including utility, confidence, OOD and assignment probability. V2 scorer/distribution separation does not remove that compatibility signing coupling; uncoupling it requires a new signed payload version and consumer migration.

The private prepared digest uses hepta.agentd.prepared-intuition.v3 and binds qualification lifetime plus admitted trust generation/distribution. The committed service digest uses hepta.agentd.committed-intuition.v2 and additionally binds final-use time and current trust distribution. Historical durable ProductionDecisionV2 encodings remain unchanged.

The in-process admission digest binds the service receipt, authenticated decision, host binding, dispatch proposal, immutable run snapshot, context attachment and observed run revision. It does not redefine the V1 transport or claim remote delivery.
