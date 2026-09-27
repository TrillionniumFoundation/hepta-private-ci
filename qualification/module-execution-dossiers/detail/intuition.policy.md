# intuition.policy: implementation and execution dossier

Parent: `docs/modules/intuition.policy/TECHNICAL.md`. Lane: `LANE-F-ADAPTIVE-POLICY`.

Status: **implemented source under qualification; product closure not yet established**. The calibrated kernel, bounded product contract, split runtime commitments, three-party admission, complete Agentd pins and host-owned learning-ledger path have source implementations. The presence of `intuition_policy_serving.rs` does not prove its invocation from the canonical module tree. The actual hook, exact-head and synthetic-merge execution, real process E2E and independent acceptance are separate facts. Pending composition scripts and workflow definitions cannot establish them.

Common execution rules: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged. This dossier preserves the target design and labels the remaining evidence rather than reducing module scope.

## 1. Source and work envelope

Primary roots:

- `codex-rs/hepta-intuition`: pure bounded policy contract and canonical digests;
- `codex-rs/hepta-intelligence`: independent evidence verification and authenticated admission;
- `codex-rs/hepta-agentd`: exact-generation host, serving composition and product-writer adapter;
- `codex-rs/hepta-learning-ledger`: durable authenticated Decision storage and independent witness.

Packages: `INT-1-CALIBRATED-INTUITION-POLICY`, `codex-hepta-intelligence`, and the bounded `codex-hepta-agentd` consumer surface. No new execution authority, model owner, random-number owner, evaluator, or ledger implementation is introduced. Changes remain on the intuition closure branch; they do not activate a policy or merge another module's work.

## 2. Public operations and contract details

Current source operations are:

- `decide_calibrated_v4(request, profile) -> ProductionIntuitionReceiptV1`;
- `canonical_candidate_identity_digest_v2` for generator-owned identity, legality, hard-veto, support, and order;
- `canonical_scored_outputs_digest_v2` and `canonical_scoring_commitment_digest_v2` for scorer outputs and scorer identity;
- `canonical_assignment_distribution_digest_v2` and `canonical_assignment_commitment_digest_v2` for assignment mass, stream, counter, draw, and RNG owner;
- `canonical_runtime_commitment_payload_v2` for the exact anti-substitution envelope;
- `decide_authenticated_intuition_v3` for generator/evaluator/observer authenticated admission;
- `AgentdIntuitionPolicyHostV1::{prepare_v3,commit_v3}` for identity/generation/profile/time binding and durable Decision append.

`AgentdState::start_canonical_intelligence` is the intended ObjectiveStart composition point. Its authenticated hook must be inspected in committed source and exercised through the actual process; a separate unreferenced module or pending finalizer is insufficient.

Historical `decide_calibrated` and `decide_calibrated_v2` remain compatibility surfaces. Feature-gating a crate-root re-export does not by itself retire direct internal consumers. The source composition must disable the default legacy root surface and migrate those consumers without silently replacing product admission by an advisory result. Qualified V3 remains a compatibility substrate; current product semantics require V4 plus authenticated V3 evidence and complete host pins.

The policy output is advisory and carries `AuthorityPosture::DENY_ALL`. Neither a prepared value nor a durable Decision receipt grants tool/model dispatch, memory mutation, or effect authority.

## 3. State records and transaction design

The policy kernel is pure. Authoritative mutable state stays with its registered owners:

1. the generator signs exact complete-candidate evidence;
2. the evaluator signs exact profile/calibration/OOD qualification;
3. the observer signs exact scoring and assignment commitments;
4. Agentd pins profile, policy, generation, objective class, model, scorer contract, calibration artifact, OOD artifact, risk rule, and optional RNG owner;
5. a selected result becomes one deterministic `ProductionDecisionV2` through the sole `LedgerWriter` held by `IntuitionPolicyLearningSink`;
6. abstain and slow-path append no selected Decision and cannot become an execution instruction.

The selected Decision must be durably committed and witnessed before product success is returned. Identity/generation/trust are checked during preparation and commit. Commit additionally recomputes the full host binding: hosts with the same Agent ID, generation and trust but different profile pins cannot consume each other's prepared values.

Preparation captures its time and the earliest expiration of the three qualification evidence envelopes. Commit rejects clock reversal and an expired qualification even when the separate Decision signature has a later expiration. These bounds are included in the `hepta.agentd.prepared-intuition.v2` digest. Existing durable Decision encodings are unchanged.

The service retains a committed receipt if the final admission check returns either `false` or an error. That result is indeterminate for downstream admission, not evidence that the ledger append never occurred. End-to-end recovery must preserve this typed information through the outer serving error boundary as well.

Idempotent replay uses the deterministic record identity, exact signed evidence and original predecessor. The current host implements one bounded exact replay for a ledger-committed/witness-not-advanced error. Ordinary rejection is not retried. A later reconciliation failure must not erase an already-known durable commit; interruption tests must cover both the first append and the retry boundary. Reopen-after-clean-drop is not a substitute for killing a process after append but before witness/acknowledgement.

## 4. Deterministic algorithm and scheduling

Hard legality and hard veto are applied before selection. Calibration, OOD, candidate completeness, policy generation, and validity windows are fail-closed. Candidate order is semantic and committed. Product entry validation applies `Ppm` bounds `[0,1_000_000]` and nonzero `PolicyGeneration`; these wrappers do not by themselves enforce monotonic cross-process updates.

The product receipt preserves original request risk and distinguishes request-high-risk, profile-risk-rule, OOD, low-confidence, and unsupported reasons. V4 currently wraps the qualified legacy kernel; preserving the product receipt semantics must not be confused with removing every internal legacy risk transformation.

Randomized assignment requires a separately owned RNG identity, stream, exact counter, exact draw, and complete distribution commitment. Deterministic assignment has no ambient draw. Assignment probabilities are excluded from scorer outputs. The scorer and assignment commitments deliberately share a generator identity digest while keeping their owned payload fields separate.

## 5. Capacity and performance profile

The kernel admits at most 128 ordered candidates. Digests and scalar encodings are fixed-width or length-prefixed and deterministic. The policy crate introduces no network RPC or hidden mutable scoring state.

Qualification definitions:

- kernel fast gate: `codex-rs/hepta-intuition/examples/fast_gate.rs`;
- authenticated gate: `codex-rs/hepta-intelligence/examples/intuition_authenticated_fast_gate.rs`;
- exact command recorder: `scripts/intuition_qualify_exact.py`;
- independent source/merge workflow: `.github/workflows/hepta-intuition-qualification.yml`.

The recorder captures actual exit codes, timestamps, durations, log hashes, checked-out SHA/tree, source/base identities, host/toolchain and Cargo.lock digest. Evidence is written outside the checkout, retained on failure, and accompanied by a final unchanged-tree check. It does not format, migrate, commit, push or sign acceptance.

Measured p50/p95/p99 values must come from execution artifacts bound to a named source and host. Kernel latency and authentication-only latency are not a measurement of the combined Agentd request, signature checks, ledger persistence, witness and final admission path. That combined measurement remains a required production deliverable; no percentile is asserted in this dossier.

## 6. Concrete verification cases

Existing test sources specify hard veto, legality, complete-set/count/order binding, OOD, calibration, validity windows, deterministic/randomized assignment, profile/risk semantics, stable errors, bounded values and commitment mutation checks. Their presence is not a passing result.

Additional committed test sources include:

- `intuition_policy_product_v3.rs`: real signed qualification fixtures, durable writer append, exact idempotent replay and clean reopen;
- `intuition_policy_commit_boundary.rs`: ten changed complete-host pins under the same identity/generation/trust, qualification expiry despite a later-valid Decision signature, clock rollback, and a final sequence-one append proving rejected cases did not write;
- host unit tests: eleven pin-binding mutations and prepared-time edge cases;
- service unit tests: preserve the exact committed token after final-gate false/error, and retain it on success;
- `scripts/intuition_golden_vectors.py`: independent Python reconstruction of five deterministic V2 digest encodings from the shared JSON fixture and 512 seeded scorer/assignment separation mutations;
- the retained `cargo-fuzz` target and Rust golden tests.

The Python encoder was exercised locally during the 2026-09-27 change with five matching digests and 512 passing owner-separation mutations. This narrow result does not establish a Rust build, final-SHA workflow success, randomized golden coverage, a real process E2E, or external acceptance.

Required remaining cases include actual process/request E2E, crash-at-boundary recovery, signed revocation and rollback across generation changes, late qualifier/principal expiration, concurrent append/retry failures, and combined target-host latency. Every claimed execution must identify its tested commit/tree and actual command outcome.

## 7. Integration, rollback and capability ceiling

Required serving sequence:

```text
signed ObjectiveStart / durable RunStart
  -> host-owned canonical invocation provider
  -> seven-owner advisory pipeline
  -> authenticated V3 completeness/profile/runtime verification
  -> V4 product disposition and complete Agentd pin validation
  -> canonical/authenticated parity or explicit fail-closed routing
  -> complete prepared binding and qualification-lifetime checks
  -> selected-only durable Decision through the sole LedgerWriter
  -> current-run/generation revalidation
  -> run/context admission under its own authority
```

The gate source defines explicit compatibility behavior: neither host nor product material permits historical advisory composition; exactly one being configured fails closed. This behavior is an implementation contract, not proof that the real serving hook already invokes it.

Rollback must select a separately configured, still-qualified predecessor under a new admitted configuration/generation. A trusted evaluator signature alone cannot switch host-pinned semantics. Revocation, stop and old-generation fences must remain effective across frozen snapshots and prepared values. Their process-level tests and operator rehearsal remain required; immutable pins alone do not establish a live revocation controller.

No generator self-acceptance, self-merge, self-promotion, or self-release is permitted. `ACCEPTANCE_TEMPLATE.json` contains no valid independent approval merely by existing in the repository.

## 8. Current native implementation and claim boundary

Source surfaces include the calibrated/qualified/runtime/production policy files, authenticated V3 intelligence admission, Agentd host/service/gate/ingress, the implementation map, updated technical guide, independent golden encoder, adversarial tests and read-only qualification workflow.

Separate current states are:

| Fact | State |
| --- | --- |
| Product policy/commitment/authentication/host source exists | implemented source |
| Complete prepared profile and evidence-lifetime fences | implemented source; Rust execution unverified |
| Sole host-held writer and direct durable fixture | implemented source; Rust execution unverified |
| Canonical ObjectiveStart hook materialized and compile-reachable | not established by a pending script |
| Actual Agentd process/request E2E | not established |
| Exact source and synthetic-merge command outcomes | require current execution artifacts |
| Independent evaluator acceptance | not established |
| Operator target-host acceptance/canary | not established |
| Activation, promotion and release | not authorized by this branch |

An aggregate workflow check named `Intuition required` exists in source. Whether branch protection requires it is a separate repository administration fact; this document does not claim that configuration was changed.

`score_legal_set` and `calibrate` remain upstream responsibilities. Generator/scorer owners produce bounded candidate/scoring facts and evaluators qualify calibration/OOD artifacts. The policy authenticates those facts and selects or abstains. Future in-crate scoring/calibration is a distinct ownership change requiring contract review, not an omitted implementation hidden by a completion flag.
