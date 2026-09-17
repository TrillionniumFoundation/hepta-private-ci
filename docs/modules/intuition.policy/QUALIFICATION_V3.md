# intuition.policy current-generation qualification V3

Status: source-level qualification implementation. Green tests establish the exact candidate's source behavior; they do not establish production activation, operator acceptance, promotion or release.

## Closed qualification chain

The current path is:

1. A legal-set generator produces the complete bounded candidate set and `CandidateSetCompletenessBindingV1`.
2. `codex-hepta-intuition::decide_calibrated_v2` fails closed when `omitted_count_bound != 0`; consumer-only compensation is no longer sufficient for a current decision.
3. A `CanonicalPolicyProfileV1` freezes the model/scorer contract, objective class, generation/window, confidence/ECE/OOD thresholds, OOD in-domain ceiling, risk routing rule, frozen qualification datasets and accepted calibration/OOD artifact digests.
4. The generator signs `canonical_completeness_evidence_payload_v1` over the exact state and complete candidate-set receipt.
5. An independent evaluator signs `canonical_qualification_evidence_payload_v1` over the exact calibrated request plus canonical profile.
6. `codex-hepta-intelligence::decide_authenticated_intuition_v1` verifies both signatures against `LearningEvidenceVerifierV1`: payload bytes, role, trust digest, objective/scope, authority epoch, signer key, validity window, revocation and role/controller separation are checked before policy evaluation.
7. `decide_calibrated_v3` rejects profile/request drift and returns a receipt whose V3 digest commits to the original request, canonical profile and bounded V2 decision.
8. `run_qualified_evaluated_shadow_v2` is the current qualified Lane-F compatibility wrapper. It authenticates before any host port, proves V2/V3 decision parity for the supported `HighOnlySlowPath` host rule, and rebinds the shadow run request digest to the authentication/profile/decision digests before execution.

Stricter V3 risk rules (`ElevatedAndHighSlowPath`, `AlwaysSlowPath`) are implemented in the policy kernel. They require a native V3 host port rather than the legacy Lane-F compatibility adapter, so the wrapper fails closed instead of silently weakening them.

## Frozen-data qualification test

`codex-rs/hepta-intelligence/tests/intuition_frozen_qualification.rs` consumes repository-controlled immutable fixtures:

- `fixtures/intuition-policy/linear-scorer-v1.model`
- `fixtures/intuition-policy/frozen-calibration-v1.csv`
- `fixtures/intuition-policy/frozen-ood-v1.csv`

The test hashes and parses the actual model artifact, runs its deterministic scorer over frozen calibration/OOD rows, computes measured ECE and OOD false-acceptance metrics, materializes artifact digests from those measured results, binds those artifacts and dataset digests into the canonical policy profile, independently signs completeness/qualification payloads, verifies them through the real trust verifier, and only then asks the policy for a decision. Editing model bytes, frozen data, thresholds, artifact metadata, signatures, generation or candidate set changes a bound digest or fails qualification.

This is a deterministic repository qualification model used to prove the chain. It is not a claim that this fixture model is a production-selected learned artifact.

## Fast gate

`.github/workflows/hepta-intuition-qualification.yml` runs exact-source and synthetic-merge qualification. `codex-rs/hepta-intuition/examples/fast_gate.rs` measures release-mode V3 policy-kernel latency, throughput and allocator activity at candidate counts 1, 16, 64 and 128. It reports p50/p95/p99 latency, decisions/second, allocation count per decision and allocated bytes per decision, and fails the workflow when a bound is exceeded.

The benchmark intentionally measures the pure decision kernel after trust admission; Ed25519 evidence verification is the consumer admission boundary, not part of the bounded candidate-scoring/selection hot path. Benchmark ceilings are conservative CI regression bounds, not a production SLO. Production p50/p95/p99 SLOs must be tightened against the selected host profile before activation.

## Remaining non-claims

This change does not train a production model, choose a production model artifact, prove an external runtime has executed an intervention, authenticate a counter-based assignment draw from its eventual random-source owner, or authorize release. Those are separate owner/activation/evidence states.
