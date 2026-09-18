# intuition.policy: implementation design

Parent: `docs/modules/intuition.policy/TECHNICAL.md`. Lane: `LANE-F-ADAPTIVE-POLICY`.
Status: bounded calibrated decision, core complete-set enforcement, canonical V3 profile, scoring commitments, exact-request admission and authenticated CounterBased assignment are source implemented; production composition and independent acceptance remain separate gates. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`.

## 1. Source and work envelope

Roots: `codex-rs/hepta-intuition`.
Package: `INT-1-CALIBRATED-INTUITION-POLICY`, canonical registry state `source_implemented`.

The policy kernel owns no model, random source, durable writer or effect authority. Trust admission is a consumer boundary in `codex-hepta-intelligence` to avoid creating a learning-ledger dependency cycle.

## 2. Public operations and contracts

Historical replay: `decide_calibrated`.

Current complete-request kernel: `decide_calibrated_v2`, which fails closed on any nonzero `omitted_count_bound`.

Canonical-profile kernel: `decide_calibrated_v3(request, profile)`.

Current authenticated consumer: `decide_authenticated_intuition_v2(request, profile, scoring_commitment, evidence, verifier, now)`.

The output is advisory: selected action/propensity, abstain or slow-path disposition and evidence-bound receipt identity. No path dispatches tools/providers or grants effect authority.

## 3. Identity and state model

Policy, model artifact and scorer contract are independent identities and are explicitly bound by `CanonicalPolicyProfileV1`. The profile also freezes qualification datasets, calibration/OOD artifact identities and measured metadata, thresholds, OOD ceiling, generation/window and risk routing.

`ScoringCommitmentV1` binds the actual decision's model, feature schema/snapshot, candidate-set score outputs, policy, generation and sequence. Decision/exposure/outcome records remain owned by `learning.ledger`.

## 4. Authentication sequence

1. Generator signs exact candidate completeness.
2. Evaluator signs the reusable canonical profile qualification.
3. Evaluator signs the exact per-decision request/profile/scoring tuple.
4. Runtime scorer signs the scoring commitment.
5. CounterBased assignment requires a distinct random-stream owner signature over stream-manifest digest, sequence/counter and draw.
6. `LearningEvidenceVerifierV1` checks trust digest, role, scope/objective, authority epoch, validity, revocation, key and controller/principal separation.
7. V3 checks profile/request consistency and delegates to V2, which independently enforces candidate completeness.

This split prevents a long-lived profile certificate from authenticating mutable request-local scores or random draws.

## 5. Capacity and performance

Candidate count remains bounded at 128. Source qualification has two independent release-mode gates at 1/16/64/128 candidates:

- policy-kernel p50/p95/p99, throughput and allocations;
- authenticated end-to-end p50/p95/p99, throughput and allocations including Ed25519 verification, profile admission, score provenance and RNG evidence.

CI ceilings are regression limits, not target-host production SLOs.

## 6. Verification cases

- INT-01: chosen action is in the complete legal set with exact positive logged probability.
- INT-02: nonzero omission fails inside V2 before selection.
- INT-03: request threshold or accepted calibration/OOD metadata cannot drift from the canonical profile.
- INT-04: policy/model/scorer identities remain distinct but bound.
- INT-05: score/model/feature commitment substitution fails authentication.
- INT-06: CounterBased assignment without independently signed stream/sequence/draw evidence fails.
- INT-07: frozen model/data recompute ECE/OOD metrics and pass only through the real trust verifier.
- INT-08: exact-source and synthetic-merge qualification run both kernel and authenticated performance gates.

## 7. Rollback and authority ceiling

Rollback selects a compatible predecessor for future runs or deterministic abstention if current lineage is revoked. Qualification evidence is not deployment authority. `AuthorityPosture::DENY_ALL` remains the policy output posture.

## 8. Current native implementation and remaining work

- **Kernel:** `codex-rs/hepta-intuition/src/calibrated.rs`, `calibrated_binding.rs`, `qualified.rs`.
- **Authenticated consumer/composition:** `codex-rs/hepta-intelligence/src/intuition_qualification.rs`, including `decide_authenticated_intuition_v2` and `run_qualified_evaluated_shadow_v3`.
- **Tests:** `codex-rs/hepta-intuition/src/calibrated_tests.rs`, `qualified_tests.rs`, `codex-rs/hepta-intelligence/tests/intuition_frozen_qualification.rs`.
- **Performance:** `codex-rs/hepta-intuition/examples/fast_gate.rs`, `codex-rs/hepta-intelligence/examples/intuition_authenticated_fast_gate.rs`, `.github/workflows/hepta-intuition-qualification.yml`.
- **Repository-controlled convergence:** current authenticated V3 shadow composition is source implemented; no remaining repository-controlled gap is asserted by the implementation map.
- **Remaining external/product evidence:** production-selected model/features and target-host measurements; real product execution; independent semantic review; causal/future-time evidence needed for higher claim levels; operator acceptance, canary, promotion and release.

Source qualification does not self-advance `docs/CURRENT.json` from its evidence-governed capability baseline.
