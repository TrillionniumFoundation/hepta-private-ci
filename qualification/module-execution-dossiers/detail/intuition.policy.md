# intuition.policy: implementation design

Parent: `docs/modules/intuition.policy/TECHNICAL.md`. Lane: `LANE-F-ADAPTIVE-POLICY`.
Status: specified target, not implemented or independently accepted. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-intuition`.
Packages: `INT-1-CALIBRATED-INTUITION-POLICY`.

Operation signatures below are design contracts, not assertions of existing native symbols. Bind each to an existing or planned symbol and consumer inside the owner envelope. Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`score_legal_set(objective, candidates, ndu, neural_signals, evidence) -> BoundedScores`; `calibrate(scores, profile, support) -> ActionDistribution`; `choose(distribution, random_stream, risk_profile) -> IntuitionDecisionReceiptV1`. Output includes complete legal set, chosen action, propensity, confidence/OOD, abstain/ask or slow-path disposition. The policy never executes the selected action.

## 3. State records and transaction design

No authoritative facts or current-run weight writer. Selected policy/calibration artifacts are immutable and lineage-bound. Ephemeral decision state contains only approved features and exact source/model/objective generations. Decision/exposure/outcome records go through learning.ledger. Calibration labels come from independent observed outcomes, not the policy's own confidence.

## 4. Deterministic algorithm and scheduling

Apply hard legality and support checks before scoring; consume bounded cached NDU and qualified neural signals; normalize a bounded action distribution using the canonical numeric profile; include explicit abstain/no-op; select with a recorded counter-based random stream when randomized. High-risk, unsupported, OOD or insufficient-confidence cases take deterministic validation/slow path. Calibration uses disjoint data and is assessed by task/risk/subgroup, not only an overall average.

## 5. Capacity and performance profile

Pilot <=128 legal candidates, input dimensions/bytes bounded by selected model profile, no central synchronous RPC or unrestricted hidden state. ECE/OOD/safety thresholds are inherited from the canonical qualification profile and cannot be changed by the policy. Measure decision p99 and safe-abstention coverage.

Pilot ceilings are design targets, not measurements. Stricter canonical limits prevail. Bind actual schema/migration, host and measurements before composition; stateless modules prove absence rather than inventing state.

## 6. Concrete verification cases

- INT-01: chosen action belongs to the complete legal set and logged probability is exact/positive.
- INT-02: a high-score forbidden action never reaches execution; an uncalibrated neural signal forces slow path.
- INT-03: OOD and protected-slice calibration failures cannot be hidden by average success.
- INT-04: deterministic baseline, no-NDU and no-neural ablations compare behavior under equal resource limits.

These are required product test designs, not executed-test receipts. Each implementation supplies native test identity, exact input/output and independent oracle evidence.

## 7. Integration, rollback and capability ceiling

C1 first uses read-only/reversible supported decisions. Fast path selection is not effect authority. Rollback selects the compatible calibrated predecessor for future runs, or deterministic abstention when its lineage is revoked.

Use all eighteen dossier receipt fields. Immediate revocation/stop remains effective across frozen snapshots. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.
