# intuition.policy: implementation design

Parent: `docs/modules/intuition.policy/TECHNICAL.md`. Lane: `LANE-F-ADAPTIVE-POLICY`.
Status: bounded calibrated decision and candidate/request binding implemented; remaining target capabilities and independent acceptance are listed in section 8. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

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

## 8. Current native implementation

- **Pure policy:** `decide_calibrated_v3` in `codex-rs/hepta-intuition/src/qualified.rs`; legacy baseline and calibrated V1/V2 remain compatibility kernels, never authentication.
- **Scoring ownership:** `runtime_commitment_v2.rs` separates scorer outputs from assignment probabilities. Legacy V1 bytes are unchanged. Exact request/runtime evidence continues to bind masks, support, assignment and risk fields.
- **Admission:** `codex-rs/hepta-intelligence/src/intuition_qualification_v3.rs` authenticates Generator, Evaluator and Observer, including exact objective and pairwise controller isolation, before invoking the pure kernel.
- **Consumer:** `AgentdOwnerPortsV1::decide_intuition` consumes `AgentdAuthenticatedIntuitionInputV1` and calls the installed `AgentdIntuitionPolicyHostV2`; missing host fails closed. The authoritative invocation provider now carries signed input, not a raw V2 request.
- **Currentness:** host-selected profile and owner implementation are separate identities. The signed owner file is checked before and after policy evaluation, and the existing coordinator checks final snapshot currency. A detected owner mismatch retires the host permanently within that process. Descriptor pin and Agentd generation prevent reuse under a different configured generation.
- **Bootstrap:** the ordinary binary accepts `--intuition-policy-file` with `--intuition-policy-digest` and the existing intelligence-authority options. The expected digest must originate in trusted deployment configuration. Root-signed trust distribution validation does not let the descriptor select its own accepted hash.
- **Verification:** module tests, valid-signature V2/V3 boundary tests, frozen model/data qualification, real product signed-evaluation/RunStart tests, bootstrap substitution and live-owner race tests. Commands and both CI lanes are detailed in the module guide; source references are not successful execution receipts.
- **Remaining:** concrete selected model/evidence providers and durable independent authority recovery frontier, representative calibration/slice/baseline experiments, registered target-host performance and physical terminal observation/learning closure. Source composition is not independent acceptance, efficacy, activation or release.
