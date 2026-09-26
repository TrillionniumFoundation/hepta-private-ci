# intuition.policy: implementation and execution dossier

Parent: `docs/modules/intuition.policy/TECHNICAL.md`. Lane: `LANE-F-ADAPTIVE-POLICY`.

Status: **source-integrated production qualification candidate**. The calibrated kernel, bounded product contract, split runtime commitments, three-party authenticated admission, Agentd pins, canonical serving gate, and sole learning-ledger writer path are repository implemented. Exact-head and synthetic-merge qualification must pass before the implementation map may claim product execution. Independent evaluator review, operator acceptance, canary, promotion, and release remain external gates and are not self-issued by this branch.

Common execution rules: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Primary roots:

- `codex-rs/hepta-intuition`: pure bounded policy contract and canonical digests;
- `codex-rs/hepta-intelligence`: independent evidence verification and authenticated admission;
- `codex-rs/hepta-agentd`: exact-generation product host, serving composition, and sole product writer;
- `codex-rs/hepta-learning-ledger`: durable authenticated Decision storage and independent witness.

Packages: `INT-1-CALIBRATED-INTUITION-POLICY`, `codex-hepta-intelligence`, and the bounded `codex-hepta-agentd` consumer surface. No new execution authority, model owner, random-number owner, evaluator, or ledger implementation is introduced.

## 2. Public operations and contract details

Current product operations are:

- `decide_calibrated_v4(request, profile) -> ProductionIntuitionReceiptV1`;
- `canonical_candidate_identity_digest_v2` for generator-owned identity, legality, hard-veto, support, and order;
- `canonical_scored_outputs_digest_v2` and `canonical_scoring_commitment_digest_v2` for scorer-owned outputs and scorer identity;
- `canonical_assignment_distribution_digest_v2` and `canonical_assignment_commitment_digest_v2` for assignment mass, stream, counter, draw, and RNG owner;
- `decide_authenticated_intuition_v3` for generator/evaluator/observer authenticated admission;
- `AgentdIntuitionPolicyHostV1::{prepare_v3,commit_v3}` for exact Agentd identity/generation binding and durable Decision append;
- `AgentdState::start_canonical_intelligence` as the actual ObjectiveStart serving composition boundary.

Historical `decide_calibrated` and `decide_calibrated_v2` are replay/migration surfaces behind `legacy-intuition-api`; they are not sufficient for product serving. V3 profile qualification remains a compatibility substrate. Product serving requires V4 semantics plus authenticated V3 evidence and Agentd host pins.

The policy output is advisory and carries `AuthorityPosture::DENY_ALL`. It never dispatches a tool/model, modifies memory, or grants effect authority.

## 3. State records and transaction design

The policy kernel is pure. Authoritative mutable state is outside the crate:

1. the generator signs exact complete-candidate evidence;
2. the evaluator signs exact profile/calibration/OOD qualification;
3. the observer signs exact scoring and assignment commitments;
4. Agentd pins profile, policy, generation, objective class, model, scorer contract, calibration artifact, OOD artifact, risk rule, and optional RNG owner;
5. a selected result becomes one deterministic `ProductionDecisionV2` through the sole `LedgerWriter` held by `IntuitionPolicyLearningSink`;
6. abstain and slow-path results append no Decision and cannot cross an execution adapter as a selected action.

The selected Decision must be durably committed and independently witnessed before Agentd admits the run. A post-commit generation change returns an indeterminate receipt and does not authorize dispatch. Idempotent replay uses the deterministic record identity and original predecessor. A one-event ledger/witness lag is reconciled only by replaying the exact same event.

## 4. Deterministic algorithm and scheduling

Hard legality and hard veto are applied before selection. Calibration, OOD, candidate completeness, policy generation, and validity windows are fail-closed. Candidate order is semantic and committed. `Ppm` bounds all parts-per-million fields to `[0,1_000_000]`; `PolicyGeneration` rejects zero.

Risk routing preserves the original request risk and records one explicit reason: request high risk, profile risk rule, OOD, low confidence, or unsupported input. It no longer rewrites a profile-forced request to `High` merely to reuse a legacy branch.

Randomized assignment requires a separately owned RNG identity, stream, exact counter, exact draw, and complete distribution commitment. Deterministic assignment has no ambient draw. No request may substitute any of these owner values.

## 5. Capacity and performance profile

The kernel admits at most 128 ordered candidates. All digests and scalar encodings are fixed-width or length-prefixed and deterministic. The normal path allocates only bounded request/receipt vectors; no network RPC or hidden mutable state is introduced inside `codex-hepta-intuition`.

Qualification records:

- kernel fast gate: `codex-hepta-intuition/examples/fast_gate.rs`;
- authenticated evidence gate: `codex-hepta-intelligence/examples/intuition_authenticated_fast_gate.rs`;
- source-host profile and exact command record: produced by `.github/workflows/hepta-intuition-qualification.yml` and retained as exact-SHA artifacts.

Measured p50/p95/p99 values are evidence artifacts, not timeless documentation constants. They must be read from the exact-head workflow artifact and must include host/CPU/toolchain metadata.

## 6. Concrete verification cases

Repository tests cover:

- hard veto, illegality, duplicate IDs, complete-set/count/order binding, OOD, calibration, validity windows, deterministic and counter-based assignment;
- all profile, model, scorer, artifact, generation, objective, signer role, and RNG owner pins;
- split digest ownership and mutation completeness;
- explicit profile-rule slow-path reason and original-risk preservation;
- stable product error codes and bounded scalar rejection;
- Rust/JSON canonical golden vectors;
- deterministic mutation fuzzing plus a retained `cargo-fuzz` target;
- Agentd host identity/generation fencing, prepare/commit separation, and selected-only ledger append;
- canonical serving parity between the historical advisory stage and authenticated product result;
- exact-source and deterministic synthetic-merge compilation, linting, tests, and fast gates.

Required production evidence still includes real process/request E2E, crash/reopen/idempotent replay, profile rollback/revocation, and exact-host latency artifacts. Those tests are qualified only when the exact-head workflow completes successfully.

## 7. Integration, rollback and capability ceiling

Serving sequence:

```text
signed ObjectiveStart / durable RunStart
  -> host-owned canonical invocation provider
  -> seven-owner canonical advisory pipeline
  -> authenticated V3 completeness/profile/runtime verification
  -> V4 production disposition and full Agentd pin validation
  -> canonical/authenticated parity check
  -> selected-only durable Decision append through sole LedgerWriter
  -> generation revalidation
  -> run/context admission
```

Compatibility mode is explicit: when neither product host nor authenticated invocation material is configured, the historical advisory composition may run. A configured host without product material, or product material without a configured host, fails closed. Rollback selects a separately configured, still-qualified predecessor profile/generation; a current host never silently accepts a different signed profile merely because the evaluator is trusted.

Immediate revocation, generation fencing, and stop remain effective across frozen snapshots. No generator self-acceptance, self-merge, self-promotion, or self-release is permitted.

## 8. Current native implementation and claim boundary

Implemented source surfaces:

- `codex-rs/hepta-intuition/src/calibrated.rs`, `qualified.rs`, `runtime_commitment.rs`, and `production.rs`;
- `codex-rs/hepta-intelligence/src/intuition_qualification_v3.rs`;
- `codex-rs/hepta-agentd/src/intuition_policy.rs`, `intuition_policy_service.rs`, `intuition_policy_serving.rs`, `intelligence_ingress.rs`, and `state.rs`;
- `docs/modules/intuition.policy/IMPLEMENTATION_MAP.json`;
- `.github/workflows/hepta-intuition-qualification.yml`.

Current claim boundary:

- native source mapping: complete for the implemented V4/authenticated-V3 product surface;
- product caller: composed at the canonical Agentd ObjectiveStart path;
- production writer: sole Agentd-held `LedgerWriter` path implemented;
- exact-head execution: pending the latest successful workflow result and its command record;
- independent semantic acceptance: pending;
- activation, canary, promotion, and release: pending.

`score_legal_set` and `calibrate` are not owned by `intuition.policy`. Generator/scorer owners produce bounded candidate/scoring facts; evaluator owners qualify calibration/OOD artifacts. This module authenticates those facts and selects or abstains. Any future in-crate scorer or calibrator would be a separate ownership change and requires a new contract review.
