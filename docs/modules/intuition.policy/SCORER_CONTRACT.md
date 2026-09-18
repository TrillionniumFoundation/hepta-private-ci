# intuition.policy learned scorer and per-decision provenance contract

Status: current-generation source contract. This document does not activate a model, select a production artifact, promote a candidate, or grant effect authority.

## Ownership boundary

`codex-hepta-intuition` is the bounded deterministic policy kernel. It does not train, load, mutate, or self-select a learned model. Immutable model bytes belong to `learning.artifacts`; a composition host executes the registered scorer and provides a signed per-decision scoring commitment.

Three identities are deliberately independent:

- `policy_digest`: policy semantics, thresholds/routing generation and compatibility identity;
- `model_artifact_digest`: exact immutable learned model bytes;
- `scorer_contract_digest`: preprocessing/forward/postprocessing interface semantics.

No equality between these digests is required. `CanonicalPolicyProfileV1` binds the tuple explicitly.

## LearnedScorerContractV1

The canonical profile binds:

- `model_artifact_digest`;
- `feature_schema_digest`;
- `output_schema_digest`;
- `score_semantics_digest`;
- `scorer_contract_digest`.

A model replacement may therefore retain compatible policy semantics, and a policy/profile revision may retain the same model artifact. Any semantic scorer change creates a new scorer-contract digest and qualification profile.

## ScoringCommitmentV1

Every current-generation V3 decision carries one exact scorer-owned commitment containing:

- decision ID, objective/objective-class digests and state digest;
- policy digest and generation/sequence;
- model artifact and scorer-contract digests;
- feature snapshot and feature-schema digests;
- output-schema and score-semantics digests;
- canonical candidate-identity digest;
- exact scored-candidate digest covering utility, calibrated confidence and OOD outputs.

Assignment probabilities and the random draw are intentionally excluded: those belong to the random-source owner.

`decide_calibrated_v3` validates the commitment against both the canonical profile and the exact request before selection. Mutating one candidate score, model identity, feature snapshot, generation or scorer schema after commitment fails closed.

## Canonical policy profile

The profile is the sole current-generation source for:

- confidence threshold;
- maximum ECE;
- maximum OOD false-acceptance rate;
- maximum in-domain OOD score;
- risk routing;
- policy generation/window;
- model/scorer identities;
- calibration/OOD dataset and artifact identities;
- measured ECE and subgroup-audit digest;
- measured OOD false-acceptance, detector and support digests;
- calibration/OOD artifact validity windows.

Request-local compatibility fields must match the authenticated profile exactly; they cannot loosen it.

## Per-decision authenticated ownership

The consumer verifies four signed facts through the existing `LearningEvidenceVerifierV1` trust snapshot:

1. `Generator`: legal candidate identity and completeness, including `omitted_count_bound == 0`;
2. `Scorer`: the exact `ScoringCommitmentV1`;
3. `Evaluator`: the reusable canonical profile qualification;
4. `RandomSource`: for CounterBased decisions only, the exact stream, request sequence/counter, draw, abstain mass and assignment distribution.

The four verified principals/controllers must be independent. Deterministic assignment requires no random-source evidence; supplying one is rejected.

The authenticated consumer then binds the exact calibrated request digest, profile digest, all verified payload/signature digests and the V3 decision receipt into one authentication digest.

## Compatibility and authority

V1 remains historical replay. V2 remains complete-request-bound compatibility and fails closed on nonzero omission. New current-generation qualification uses V3 plus the scorer/profile/random-source evidence chain.

None of these contracts grant effect authority. The policy cannot dispatch a tool/model/provider, clear a hard veto, write another owner store, promote an artifact or authorize release.
