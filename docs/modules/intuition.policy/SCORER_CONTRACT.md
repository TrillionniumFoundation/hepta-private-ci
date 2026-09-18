# intuition.policy learned scorer contract V1

Status: current-generation source contract. This document does not activate a model, select a production artifact, promote a candidate, or grant effect authority.

## Ownership boundary

`codex-hepta-intuition` does **not** train, load, execute, mutate, select or promote a learned model. It is the bounded deterministic policy kernel over an already scored, complete legal candidate set. Immutable model bytes and lineage belong to `learning.artifacts` / the registered scorer owner; current trust admission is composed by `codex-hepta-intelligence`.

The identities are deliberately independent:

- `policy_digest`: semantics of the fast-policy generation and its decision rules.
- `model_digest`: exact immutable learned model bytes used by the upstream scorer.
- `scorer_contract_digest`: versioned preprocessing, forward-scoring and postprocessing contract.

None of these digests is required to equal another. The canonical profile binds them together explicitly. This permits a model rollback without relabeling policy semantics, a policy/profile change without rewriting model identity, and a scorer-contract revision without pretending the model bytes changed.

## LearnedScorerContractV1

The scorer contract binds:

- `model_digest`: exact immutable learned model artifact.
- `feature_schema_digest`: canonical feature ordering, units, fixed-point scaling, bounds and missing-value behavior.
- `output_schema_digest`: canonical ordering/representation of `utility`, `calibrated_confidence` and `ood_score`.
- `score_semantics_digest`: meaning of those outputs.
- `scorer_contract_digest`: versioned pure scoring interface including preprocessing and postprocessing.

Changing feature construction, normalization, model format, output transformation, score meaning or tie semantics creates a new digest/generation.

## ScoringCommitmentV1

A contract alone proves what scorer *should* run; it does not prove which scorer produced one decision's values. Every current authenticated decision therefore carries `ScoringCommitmentV1`, which binds:

- `decision_id`;
- `model_artifact_digest`;
- `feature_schema_digest`;
- `feature_snapshot_digest`;
- `scorer_contract_digest`;
- exact `candidate_set_digest`;
- `scored_candidates_digest` over candidate ID, utility, calibrated confidence, OOD score and support;
- `policy_digest`, generation and sequence.

`canonical_scoring_commitment_digest_v1` fails if the commitment is inconsistent with either the canonical profile or the actual calibrated request. A score vector cannot therefore be swapped under an otherwise valid model/profile identity.

## Canonical model/calibration linkage

`CanonicalPolicyProfileV1` is the source of truth for policy generation and qualification limits. It binds the independent policy/model/scorer identities plus:

- objective class and validity window;
- minimum confidence;
- maximum ECE;
- maximum OOD false-acceptance rate;
- maximum in-domain OOD score;
- risk-routing rule;
- frozen calibration/OOD dataset digests;
- accepted calibration artifact, measured ECE and subgroup-audit digest;
- accepted OOD artifact, measured false-acceptance rate, detector digest and support digest.

V3 rejects request-local threshold or artifact-metadata drift. Request fields remain only for compatibility with the historical wire shape; they cannot loosen the canonical profile.

## Per-decision authentication

Current consumer admission separates long-lived qualification from request-local facts:

1. an independent Evaluator signs the canonical policy profile qualification;
2. a legal-set Generator signs exact completeness;
3. an Evaluator signs the exact decision request plus profile/scoring commitment;
4. the runtime scorer signs the `ScoringCommitmentV1` payload;
5. for `CounterBased` assignment, an independent random-stream owner signs the exact stream-manifest digest, generation/sequence counter, draw and abstain probability.

The scorer and randomizer use the existing authenticated `Observer` evidence role but must be different principals, credential chains, signing keys and controllers. Payload domains distinguish their semantics. The Generator, Evaluator, scorer and randomizer cannot collapse into one trust identity.

## Feature and output invariants

A registered feature schema is closed-world and bounded. It defines field order, units, numeric profile, missingness, maximum dimensionality and source-snapshot binding. Unknown critical fields, NaN/floating nondeterminism, implicit feature reordering and process-global mutable preprocessing are prohibited.

`CalibratedActionCandidateV1` is still the policy-kernel input. Upstream scoring must cover the authenticated complete set. The scorer cannot add/remove candidates, clear a hard veto, change legality, choose the random draw or grant effect authority.

## Compatibility and claim boundary

V1 remains historical replay. V2 remains complete-request binding and now fails closed on nonzero omission. V3 is the canonical-profile kernel. New current-generation admission should use `decide_authenticated_intuition_v2`.

Source qualification does not advance the capability ladder by itself. In particular, `docs/CURRENT.json` and generated status remain at the evidence-governed baseline until the registered product/causal requirements are independently satisfied.
