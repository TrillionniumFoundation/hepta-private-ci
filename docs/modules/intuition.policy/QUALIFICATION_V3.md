# intuition.policy current-generation qualification V3

Status: source-level qualification implementation. Green source and merge tests establish exact-candidate behavior only; they do not establish production activation, operator acceptance, promotion or release.

## Qualification model

Qualification is intentionally split into a reusable generation-level certificate and lightweight per-decision commitments.

### Generation-level profile

`CanonicalPolicyProfileV1` freezes independent policy/model/scorer identities, objective class, generation/window, confidence/ECE/OOD limits, maximum in-domain OOD score, risk routing, frozen qualification datasets and the exact accepted calibration/OOD measurements and artifact metadata.

An independent Evaluator signs `canonical_profile_qualification_evidence_payload_v1`. This profile evidence may be reused while its trust snapshot, generation and validity window remain current.

### Per-decision commitments

Every current decision additionally requires:

1. **Completeness** — the Generator signs `canonical_completeness_evidence_payload_v1`; V2 itself also rejects `omitted_count_bound != 0`.
2. **Exact request** — an Evaluator signs `canonical_decision_request_evidence_payload_v1`, which commits to the complete calibrated request, canonical profile and scoring commitment.
3. **Scoring provenance** — a distinct runtime scorer signs `canonical_scoring_evidence_payload_v1` for `ScoringCommitmentV1`, binding model, feature snapshot/schema, candidate-set score outputs, policy, generation and sequence.
4. **Assignment** — deterministic requests carry no assignment signature. `CounterBased` requests require a distinct random-stream owner signature over `canonical_assignment_evidence_payload_v1`, binding the stream-manifest digest, state/candidate-set identity, generation, sequence/counter, exact draw and abstain probability.

`codex-hepta-intelligence::decide_authenticated_intuition_v2` verifies all applicable evidence through `LearningEvidenceVerifierV1` before invoking V3. Trust digest, objective/scope, authority epoch, signer key, validity window and revocation are checked. Generator/Evaluator/scorer/randomizer identities are separated by principal, credential chain, key and controller.

The older `decide_authenticated_intuition_v1` remains a compatibility API for the original exact-request qualification scheme; new source qualification uses V2.

## Policy kernel

`decide_calibrated_v3` remains pure and authority-free. It rejects:

- canonical profile/request threshold drift;
- policy/objective/generation/window mismatch;
- calibration or OOD artifact substitution;
- calibration/OOD measured-metadata drift;
- incomplete candidate sets via V2;
- risk classes disallowed by the profile.

Policy identity is no longer equated to model identity.

## Frozen-data qualification

`codex-rs/hepta-intelligence/tests/intuition_frozen_qualification.rs` consumes repository-controlled immutable fixtures:

- `fixtures/intuition-policy/linear-scorer-v1.model`;
- `fixtures/intuition-policy/frozen-calibration-v1.csv`;
- `fixtures/intuition-policy/frozen-ood-v1.csv`.

The test hashes and executes the actual reference model, computes measured ECE/OOD false-acceptance metrics, materializes artifact digests, uses a policy digest distinct from the model digest, builds an exact scoring commitment, and creates four distinct trust identities: Generator, Evaluator, runtime scorer and random-stream owner. It verifies missing/tampered per-decision evidence fails before accepting the signed decision.

These fixtures prove the source chain only. They are not production-selected learned artifacts.

## Performance qualification

`.github/workflows/hepta-intuition-qualification.yml` runs exact-source and deterministic synthetic-merge qualification and retains two independent performance surfaces at 1/16/64/128 candidates:

- **Kernel gate** — `codex-rs/hepta-intuition/examples/fast_gate.rs` measures V3 policy-kernel p50/p95/p99, throughput, allocation count and allocated bytes after trust admission.
- **Authenticated end-to-end gate** — `codex-rs/hepta-intelligence/examples/intuition_authenticated_fast_gate.rs` measures the current V2 consumer path, including Ed25519 evidence verification, canonical profile checks, exact-request admission, score provenance, random-stream evidence and V3 decision.

Both are conservative CI regression gates rather than production SLOs. Target-host activation must retain hardware/runtime identity and may impose stricter bounds.

## Compatibility host

`run_qualified_evaluated_shadow_v2` remains a compatibility adapter for the legacy `HighOnlySlowPath` coordinator. The current source path is `run_qualified_evaluated_shadow_v3`, which consumes the full authenticated V2 admission chain and preserves all canonical V3 risk rules while keeping policy and model-artifact identities separate.

## Remaining non-claims

This source closure does not select a production model, prove production feature extraction/inference, establish a production caller, prove external intervention execution, establish causal/longitudinal efficacy, or authorize operator acceptance, canary, promotion or release. Capability claims remain governed by `docs/evidence/CLAIMS.json`; source qualification alone does not advance `docs/CURRENT.json`.
