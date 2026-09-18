# intuition.policy learned scorer contract V1

Status: current-generation source contract. This document does not activate a model, select a production artifact, promote a candidate, or grant effect authority.

## Ownership boundary

`codex-hepta-intuition` does **not** execute or train a learned model. Its native responsibility is the bounded, deterministic policy kernel: validate a complete legal candidate set, enforce the authenticated canonical policy profile, apply calibration/OOD/confidence/risk gates, produce propensities, and select/abstain/route to slow path.

Immutable learned model bytes and lineage belong to `learning.artifacts` / the `learning_artifact_registry`. A composition host supplies scored candidates only after selecting an immutable model artifact and executing the registered scorer contract. The Lane-F consumer in `codex-hepta-intelligence` owns current-generation qualification admission; it verifies signed completeness, profile qualification and per-decision runtime evidence before V3 is usable. No scorer, artifact registry, or consumer may mint effect authority through this contract.

## `LearnedScorerContractV1`

A canonical policy profile binds all scorer identity fields:

- `model_digest`: `Digest32` identity of the exact immutable learned model bytes used to score this generation.
- `feature_schema_digest`: canonical feature ordering, units, fixed-point scaling, bounds and missing-value behavior.
- `output_schema_digest`: canonical ordering and representation of `utility`, `calibrated_confidence`, and `ood_score` outputs.
- `score_semantics_digest`: semantic contract for what each score means. Utility is an ordering signal under the frozen objective; confidence is the calibrated probability/coverage signal used by policy admission; OOD score is monotone with distance from the qualified support and is rejected above the profile ceiling.
- `scorer_contract_digest`: versioned preprocessing, pure forward-scoring, and postprocessing contract. Changing feature construction, normalization, model format, output transformation, or tie semantics creates a new digest/generation.

`CalibratedActionCandidateV1` remains the policy-kernel input. The upstream scorer must emit one entry for every candidate in the authenticated complete legal set. Candidate identity/order are canonical and cannot be added, removed, reordered or rescored after completeness and qualification evidence are signed.

## Model/calibration linkage

`CanonicalPolicyProfileV1` binds three independent identities: `policy_digest` for policy semantics, `scorer.model_digest` for immutable model bytes, and `scorer.scorer_contract_digest` for the scoring interface. None is required to equal another. The profile binds their relationship for one objective class and generation together with frozen calibration/OOD dataset digests and the only accepted calibration/OOD artifact digests. V3 rejects objective-class/generation drift, expired profile windows, artifact substitution, or request thresholds that differ from the profile.

The policy kernel does not trust a nonzero artifact digest by itself. Current-generation admission requires a trusted consumer to verify the canonical evidence payloads against a host-owned trust snapshot. The current Lane-F consumer uses independent `Generator`, `Evaluator` and `Observer` roles with Ed25519 verification, validity windows, authority epoch, revocation and controller/principal separation. `Evaluator` signs the longer-lived canonical profile qualification; `Generator` signs exact candidate completeness; `Observer` signs each runtime commitment.

## Per-decision scoring commitment

`ScoringCommitmentV1` closes the gap between a qualified model contract and the actual scores consumed by the policy. It binds:

- immutable `model_artifact_digest`;
- exact `feature_snapshot_digest` and canonical `feature_schema_digest`;
- `scorer_contract_digest`;
- exact `candidate_set_digest`;
- `scored_outputs_digest` over candidate identity, utility, calibrated confidence, OOD score and support digest;
- `policy_digest` and generation.

`AssignmentCommitmentV1` is separate from model scoring. Deterministic assignment is explicit. Counter-based assignment binds the RNG owner digest, stream digest, `counter == request.sequence`, and exact draw. `canonical_runtime_commitment_payload_v1` then binds the complete calibrated request, canonical profile, scoring commitment and assignment commitment into the per-decision `Observer` evidence payload.

This split permits longer-lived model/profile qualification without allowing a caller to rescore candidates, substitute feature snapshots, or choose a favorable draw after qualification.

## Feature and output invariants

A registered feature schema must be closed-world and bounded. It must define field order, units, numeric profile, missingness, maximum dimensionality and source snapshot binding. Unknown critical fields, NaN/floating non-determinism, implicit feature reordering and process-global mutable preprocessing are prohibited.

Scorer outputs consumed by `intuition.policy` are fixed-point values already tied to the same `model_digest`, objective class and generation as the profile. The scorer cannot mark an illegal candidate legal, clear a hard veto, create omitted candidates, change a support digest, choose the assignment draw, or grant action authority.

## Compatibility

V1/V2 calibrated decisions remain interpretable for historical replay. New qualification and composition must use V3 plus authenticated evidence. Any learned-scorer schema change is additive only where explicitly registered; a semantic change to an existing digest is forbidden.
