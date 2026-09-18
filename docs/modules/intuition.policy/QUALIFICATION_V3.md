# intuition.policy current-generation qualification V3

Status: source-level qualification implementation. Green tests establish the exact candidate's source behavior; they do not establish production activation, operator acceptance, promotion or release.

## Closed qualification chain

The current path is:

1. A legal-set generator produces the complete bounded candidate set and `CandidateSetCompletenessBindingV1`.
2. `codex-hepta-intuition::decide_calibrated_v2` fails closed when `omitted_count_bound != 0`; consumer-only compensation is no longer sufficient for a current decision.
3. A `CanonicalPolicyProfileV1` freezes the model/scorer contract, objective class, generation/window, confidence/ECE/OOD thresholds, OOD in-domain ceiling, risk routing rule, frozen qualification datasets and accepted calibration/OOD artifact digests.
4. The generator signs `canonical_completeness_evidence_payload_v1` over the exact state and complete candidate-set receipt.
5. An independent evaluator signs `canonical_profile_qualification_payload_v1` over the canonical policy profile, immutable model/scorer lineage, frozen qualification datasets and accepted calibration/OOD artifacts. This evidence may outlive one decision within its validity/revocation window.
6. The runtime scorer emits `ScoringCommitmentV1`, binding the immutable model, exact feature snapshot/schema, scorer contract, candidate set and scored outputs. `AssignmentCommitmentV1` separately binds deterministic assignment or the RNG owner, stream, sequence counter and exact draw.
7. An independent observer signs `canonical_runtime_commitment_payload_v1`, which binds the exact calibrated request, canonical profile, scoring commitment and assignment commitment.
8. `codex-hepta-intelligence::decide_authenticated_intuition_v2` verifies Generator/Evaluator/Observer evidence against `LearningEvidenceVerifierV1`: payload bytes, role, trust digest, objective/scope, authority epoch, signer key, validity window, revocation and principal/controller separation are checked before policy evaluation.
9. `decide_calibrated_v3` rejects profile/request drift and returns a receipt whose V3 digest commits to the original request, canonical profile and bounded V2 decision.
10. Historical `decide_authenticated_intuition_v1` and `run_qualified_evaluated_shadow_v2` remain compatibility surfaces. Production-oriented new composition should use the V2 authenticated admission so per-decision scores and RNG provenance are not caller assertions.

Stricter V3 risk rules (`ElevatedAndHighSlowPath`, `AlwaysSlowPath`) are implemented in the policy kernel. They require a native V3 host port rather than the legacy Lane-F compatibility adapter, so the wrapper fails closed instead of silently weakening them.

## Frozen-data qualification test

`codex-rs/hepta-intelligence/tests/intuition_frozen_qualification.rs` consumes repository-controlled immutable fixtures:

- `fixtures/intuition-policy/linear-scorer-v1.model`
- `fixtures/intuition-policy/frozen-calibration-v1.csv`
- `fixtures/intuition-policy/frozen-ood-v1.csv`

The test hashes and parses the actual model artifact, runs its deterministic scorer over frozen calibration/OOD rows, computes measured ECE and OOD false-acceptance metrics, materializes artifact digests from those measured results, binds those artifacts and dataset digests into the canonical policy profile, keeps `policy_digest`, `model_digest` and `scorer_contract_digest` independent, builds a scoring commitment, and independently signs completeness, profile-qualification and runtime payloads. The real trust verifier admits all three roles before the policy decision. Editing model bytes, frozen data, scores, feature snapshot, thresholds, artifact metadata, signatures, generation, candidate set or assignment provenance changes a bound digest or fails qualification.

This is a deterministic repository qualification model used to prove the chain. It is not a claim that this fixture model is a production-selected learned artifact.

## Fast gate

`.github/workflows/hepta-intuition-qualification.yml` runs exact-source and synthetic-merge qualification with two separate performance surfaces. `codex-rs/hepta-intuition/examples/fast_gate.rs` measures release-mode V3 policy-kernel latency/throughput/allocation behavior at candidate counts 1, 16, 64 and 128. `codex-rs/hepta-intelligence/examples/intuition_authenticated_fast_gate.rs` independently measures the authenticated end-to-end path, including Generator/Evaluator/Observer signature verification, canonical profile admission, scoring/RNG provenance validation and the final V3 decision.

Both surfaces report p50/p95/p99 and throughput; the kernel gate additionally reports allocator activity. CI ceilings are conservative regression bounds, not production SLOs. Target-host production qualification must retain the exact host/profile and may impose stricter limits.

## Remaining non-claims

This change does not train or select a production model, prove an external runtime has executed an intervention, establish a named production caller, or authorize release. Counter-based assignment now has a source-level authenticated owner/stream/counter/draw contract, but the eventual production RNG owner and real runtime execution remain deployment evidence, not source claims.
