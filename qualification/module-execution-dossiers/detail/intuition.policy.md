# intuition.policy: implementation design

Parent: `docs/modules/intuition.policy/TECHNICAL.md`. Lane: `LANE-F-ADAPTIVE-POLICY`.
Status: bounded calibrated decision, complete-request binding, qualified-artifact/profile gating, frozen-data reference qualification and fast-path measurement are source implemented; independent product composition and acceptance remain external gates. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-intuition`.
Packages: `INT-1-CALIBRATED-INTUITION-POLICY`.

Operation signatures below describe the target contract. Section 8 identifies the implemented native subset and remaining integration; names in section 2 are not automatically native API symbols. Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

The learned scorer is upstream-owned. Its formal boundary is `LearnedScorerContractV1`: feature schema, immutable model artifact, calibration artifact, OOD artifact, score semantics, policy digest and generation are one canonical commitment. `intuition.policy` does not load, train or mutate a model at decision time.

The production-oriented native path is `decide_qualified(QualifiedDecisionRequestV1, QualificationAuthorityVerifier)`. It consumes the upstream learned candidate fields plus a canonical policy profile and an authenticated current-generation qualification manifest. Output includes chosen action, exact propensity, abstain/slow-path mass and artifact receipt digests. The policy never executes the selected action.

Historical `decide_calibrated` remains a V1 replay surface. `decide_calibrated_v2` retains complete request binding and now fails closed when `omitted_count_bound != 0`.

## 3. State records and transaction design

No authoritative facts or current-run weight writer. Selected policy/calibration/model/qualification artifacts are immutable and lineage-bound. Ephemeral decision state contains only approved features and exact source/model/objective generations. Decision/exposure/outcome records go through learning.ledger. Calibration labels come from independent observed outcomes, not the policy's own confidence.

The qualification authority is external to this advisory crate. `QualificationAuthorityVerifier` is the only production admission boundary: its implementation must verify the manifest against the current trusted signer set, revocation state and current-generation qualification registry. The crate binds and checks the authenticated result but owns no signing key and mints no authority.

## 4. Deterministic algorithm and scheduling

Apply hard legality and support checks before selection; consume bounded upstream learned scores; verify complete candidate enumeration; verify canonical policy/profile generation; verify calibration/OOD/completeness artifact identities through the qualification manifest; then apply confidence, OOD and risk gates. Include explicit abstain/no-op and use a recorded counter-based random stream when randomized. High-risk, unsupported, OOD or insufficient-confidence cases take deterministic validation/slow path.

Request-local confidence/ECE/OOD knobs are legacy compatibility fields only. On the qualified path they must exactly equal the authenticated `CanonicalPolicyProfileV1`. High risk is never admitted to the fast path; elevated risk is admitted only when the canonical profile explicitly permits it.

## 5. Capacity and performance profile

Pilot <=128 legal candidates. The independent `intuition_fast` Divan benchmark runs 1/16/64/128 candidate cases under `AllocProfiler`, recording latency and allocation behavior. `tests/fast_gate.rs` independently measures p50/p95/p99 and throughput in release profile and fails closed when p99 exceeds 20 ms or throughput falls below 50 decisions/s on the CI host.

Those CI ceilings are conservative source gates, not target-host production SLOs. Target-host qualification must retain the exact benchmark host/profile and can impose stricter canonical limits.

## 6. Concrete verification cases

- INT-01: chosen action belongs to the complete legal set and logged probability is exact/positive.
- INT-02: `omitted_count_bound > 0` fails inside `codex-hepta-intuition`, independent of consumer checks.
- INT-03: an unauthenticated, wrong-generation or artifact-mismatched qualification manifest fails before selection.
- INT-04: request-local threshold drift from the authenticated canonical profile fails before selection.
- INT-05: frozen validation data derives ECE/OOD metrics, binds a frozen model digest and scorer contract, then flows through `decide_qualified`.
- INT-06: 1/16/64/128 candidate release-profile performance produces p50/p95/p99, throughput and allocation evidence.

Source test identities are not independent acceptance receipts. Production qualification replaces the reference fixtures with retained production-candidate model/data artifacts and an independently verified authority implementation.

## 7. Integration, rollback and capability ceiling

C1 first uses read-only/reversible supported decisions. Fast path selection is not effect authority. Rollback selects the compatible calibrated predecessor for future runs, or deterministic abstention when its lineage is revoked.

Use all eighteen dossier receipt fields. Immediate revocation/stop remains effective across frozen snapshots. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.

## 8. Current native implementation

- **Implemented entrypoints:** `decide_calibrated` in [codex-rs/hepta-intuition/src/calibrated.rs](../../../codex-rs/hepta-intuition/src/calibrated.rs); `decide_calibrated_v2` in [codex-rs/hepta-intuition/src/calibrated_binding.rs](../../../codex-rs/hepta-intuition/src/calibrated_binding.rs); `decide_qualified` plus `CanonicalPolicyProfileV1`, `QualificationManifestV1` and `QualificationAuthorityVerifier` in [codex-rs/hepta-intuition/src/qualified.rs](../../../codex-rs/hepta-intuition/src/qualified.rs); learned-scorer ownership contract in [codex-rs/hepta-intuition/src/learned_scorer.rs](../../../codex-rs/hepta-intuition/src/learned_scorer.rs).
- **Completeness invariant:** V2 and qualified paths reject any nonzero `omitted_count_bound` inside the intuition crate. Consumer checks may remain as defense in depth but are no longer the sole enforcement point.
- **Canonical policy profile:** qualified decisions require request thresholds/risk admission to exactly match the canonical profile digest and current policy generation.
- **Qualification chain:** qualification manifests bind authority/signer-set/run, frozen validation data, model artifact, scorer contract, profile, policy/objective generation and exact completeness/calibration/OOD artifact digests. Authentication is delegated to the external verifier boundary so this crate does not own keys or self-authorize.
- **Frozen-data test:** [codex-rs/hepta-intuition/tests/frozen_qualification.rs](../../../codex-rs/hepta-intuition/tests/frozen_qualification.rs) derives calibration/OOD metrics from retained frozen fixture data, binds a retained model artifact and exercises the qualified policy.
- **Fast gate:** [codex-rs/hepta-intuition/tests/fast_gate.rs](../../../codex-rs/hepta-intuition/tests/fast_gate.rs), [codex-rs/hepta-intuition/benches/intuition_fast.rs](../../../codex-rs/hepta-intuition/benches/intuition_fast.rs) and `.github/workflows/hepta-intuition-fast-policy.yml` provide release-profile latency/throughput gating and Divan allocation profiling at 1/16/64/128 candidates.
- **Source tests:** [codex-rs/hepta-intuition/src/calibrated_tests.rs](../../../codex-rs/hepta-intuition/src/calibrated_tests.rs) plus the qualified/scorer unit tests. These are source test identities, not independent acceptance receipts.
- **Remaining work before production claims:** wire a named product caller to the repository signed-artifact/current-qualification authority; replace reference model/data fixtures with independently retained production-candidate artifacts; retain exact target-host performance evidence; prove consumer execution; complete independent semantic review, operator acceptance, canary, promotion and release.
