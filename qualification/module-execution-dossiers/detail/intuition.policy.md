# intuition.policy: implementation design

Parent: `docs/modules/intuition.policy/TECHNICAL.md`. Lane: `LANE-F-ADAPTIVE-POLICY`.
Status: bounded calibrated decision, complete-set enforcement, canonical V3 profile and signed current-generation qualification admission are source implemented; remaining production composition and independent acceptance are listed in section 8. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-intuition`.
Packages: `INT-1-CALIBRATED-INTUITION-POLICY`.

Operation signatures below describe the target contract. Section 8 identifies the implemented native subset and remaining integration; names in section 2 are not automatically native API symbols. Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`score_legal_set(objective, candidates, ndu, neural_signals, evidence) -> BoundedScores`; `calibrate(scores, profile, support) -> ActionDistribution`; `choose(distribution, random_stream, risk_profile) -> IntuitionDecisionReceiptV1`. Output includes complete legal set, chosen action, propensity, confidence/OOD, abstain/ask or slow-path disposition. The policy never executes the selected action.

## 3. State records and transaction design

No authoritative facts or current-run weight writer. Selected policy/calibration artifacts are immutable and lineage-bound. Ephemeral decision state contains only approved features and exact source/model/objective generations. Decision/exposure/outcome records go through learning.ledger. Calibration labels come from independent observed outcomes, not the policy's own confidence.

## 4. Deterministic algorithm and scheduling

Apply hard legality and support checks before scoring; consume bounded cached NDU and qualified neural signals; normalize a bounded action distribution using the canonical numeric profile; include explicit abstain/no-op; select with a recorded counter-based random stream when randomized. High-risk, unsupported, OOD or insufficient-confidence cases take deterministic validation/slow path. Calibration uses disjoint data and is assessed by task/risk/subgroup, not only an overall average.

## 5. Capacity and performance profile

Pilot <=128 legal candidates, input dimensions/bytes bounded by selected model profile, no central synchronous RPC or unrestricted hidden state. ECE/OOD/safety thresholds are inherited from the canonical qualification profile and cannot be changed by the policy. Measure decision p99 and safe-abstention coverage.

`codex-rs/hepta-intuition/examples/fast_gate.rs` now supplies a release-mode source qualification gate at 1/16/64/128 candidates and reports p50/p95/p99 latency, throughput, allocation count and allocated bytes. The checked ceilings are conservative CI regression bounds rather than activation SLOs; production target-host SLOs remain an external evidence gate.

## 6. Concrete verification cases

- INT-01: chosen action belongs to the complete legal set and logged probability is exact/positive.
- INT-02: a high-score forbidden action never reaches execution; an uncalibrated neural signal forces slow path.
- INT-03: OOD and protected-slice calibration failures cannot be hidden by average success.
- INT-04: deterministic baseline, no-NDU and no-neural ablations compare behavior under equal resource limits.
- INT-05: current V2/V3 rejects any non-zero omitted candidate bound inside `codex-hepta-intuition`.
- INT-06: V3 rejects request threshold/artifact/generation drift from the canonical profile.
- INT-07: frozen model bytes and frozen calibration/OOD data produce measured metrics, signed completeness/qualification evidence and only then an authenticated policy decision.

## 7. Integration, rollback and capability ceiling

C1 first uses read-only/reversible supported decisions. Fast path selection is not effect authority. Rollback selects the compatible calibrated predecessor for future runs, or deterministic abstention when its lineage is revoked.

Use all eighteen dossier receipt fields. Immediate revocation/stop remains effective across frozen snapshots. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.

Current-generation trust admission deliberately lives in `codex-hepta-intelligence`, which already depends on both `codex-hepta-intuition` and `codex-hepta-learning-ledger`; putting signature verification in `codex-hepta-intuition` would create an ownership/dependency cycle because the ledger already depends on intuition types.

## 8. Current native implementation

- **Implemented entrypoints:** historical `decide_calibrated` in [codex-rs/hepta-intuition/src/calibrated.rs](../../../codex-rs/hepta-intuition/src/calibrated.rs); current complete-set `decide_calibrated_v2` in [codex-rs/hepta-intuition/src/calibrated_binding.rs](../../../codex-rs/hepta-intuition/src/calibrated_binding.rs); canonical-profile `decide_calibrated_v3` and evidence payloads in [codex-rs/hepta-intuition/src/qualified.rs](../../../codex-rs/hepta-intuition/src/qualified.rs); signed consumer admission in [codex-rs/hepta-intelligence/src/intuition_qualification.rs](../../../codex-rs/hepta-intelligence/src/intuition_qualification.rs).
- **State and recovery:** V2/V3 fail closed when `omitted_count_bound != 0`. V3 binds model/scorer lineage, objective class, generation/window, frozen calibration/OOD datasets, accepted artifact digests, thresholds and risk routing into `CanonicalPolicyProfileV1`. The consumer verifies independent Generator/Evaluator Ed25519 evidence against the existing trust snapshot, including role, authority epoch, validity and revocation, before V3 is invoked.
- **Learned scorer ownership:** model training/inference and immutable model lineage belong to `learning.artifacts` / the registered scorer owner; `codex-hepta-intuition` is the deterministic policy kernel over already-scored candidates. The normative source contract is [docs/modules/intuition.policy/SCORER_CONTRACT.md](../../../docs/modules/intuition.policy/SCORER_CONTRACT.md).
- **Source tests:** [codex-rs/hepta-intuition/src/calibrated_tests.rs](../../../codex-rs/hepta-intuition/src/calibrated_tests.rs), [codex-rs/hepta-intuition/src/qualified_tests.rs](../../../codex-rs/hepta-intuition/src/qualified_tests.rs), [codex-rs/hepta-intelligence/tests/intuition_frozen_qualification.rs](../../../codex-rs/hepta-intelligence/tests/intuition_frozen_qualification.rs). The frozen-data test hashes and executes repository-controlled model bytes, measures ECE/OOD FAR on frozen CSV data, signs exact qualification payloads through the real verifier, then obtains a decision. These are source qualification receipts, not a production-model selection claim.
- **Fast qualification:** [codex-rs/hepta-intuition/examples/fast_gate.rs](../../../codex-rs/hepta-intuition/examples/fast_gate.rs) and `.github/workflows/hepta-intuition-qualification.yml` gate 1/16/64/128-candidate latency/throughput/allocation regressions on exact source and deterministic synthetic merge.
- **Implementation and operating references:** [docs/modules/intuition.policy/TECHNICAL.md](../../../docs/modules/intuition.policy/TECHNICAL.md), [docs/modules/intuition.policy/QUALIFICATION_V3.md](../../../docs/modules/intuition.policy/QUALIFICATION_V3.md), [codex-rs/hepta-intelligence/EVALUATED_SHADOW.md](../../../codex-rs/hepta-intelligence/EVALUATED_SHADOW.md).
- **Remaining work / non-claims:** authenticate the eventual owner-supplied `CounterBased` random draw; compose stricter V3 risk profiles through a native V3 host port; qualify the production-selected learned model and target-host SLOs; obtain real consumer execution, operator acceptance, canary, promotion and release evidence. None of those states is inferred from green source CI.
