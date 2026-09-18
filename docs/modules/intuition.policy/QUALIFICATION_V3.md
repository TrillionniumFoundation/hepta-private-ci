# intuition.policy current-generation qualification V3

Status: source-level qualification implementation. Green exact-source and merge-candidate tests establish candidate source behavior only; they do not establish production activation, operator acceptance, promotion or release.

## Closed qualification chain

The current path separates long-lived qualification from per-decision provenance:

1. A legal-set generator emits the bounded candidate identities and completeness facts.
2. `decide_calibrated_v2` fails closed when `omitted_count_bound != 0`.
3. A reusable `CanonicalPolicyProfileV1` freezes policy semantics, model/scorer identities, generation/window, confidence/ECE/OOD thresholds, maximum in-domain OOD score, risk routing, frozen qualification datasets, admitted artifact identities, measured calibration/OOD metadata, detector/support digests and artifact validity windows.
4. An independent evaluator signs only the canonical profile qualification payload. This attestation can be reused for decisions in the profile validity window.
5. For each decision, the generator signs candidate identity/completeness, the scorer signs `ScoringCommitmentV1`, and CounterBased assignment requires a RandomSource signature over exact `(stream, request sequence/counter, draw, abstain mass, distribution)`.
6. `codex-hepta-intelligence::decide_authenticated_intuition_v1` verifies all required signatures against `LearningEvidenceVerifierV1`: trust digest, role, signer key, authority epoch, objective/scope, validity, revocation and principal/controller independence.
7. The consumer computes the exact calibrated request digest and binds it with all verified evidence. No evaluator per-decision signature is required because every mutable decision-time domain has a separately authenticated owner.
8. `decide_calibrated_v3` validates profile/request equality and the scoring commitment, then returns a receipt binding exact request + canonical profile + scoring commitment + bounded V2 outcome.

The legacy Lane-F wrapper still accepts only `HighOnlySlowPath`; stricter V3 risk profiles require a native V3 host port and fail closed at that compatibility boundary.

## Identity separation

`policy_digest`, `model_artifact_digest`, and `scorer_contract_digest` are distinct identities. The canonical profile binds the tuple; it never assumes model bytes are the policy identity.

This supports model replacement under stable policy semantics, policy/profile revisions over one model, and independent scorer-interface versioning.

## Scoring provenance

`ScoringCommitmentV1` binds:

- decision/objective/objective-class/state/generation/sequence;
- model artifact and scorer contract;
- feature snapshot/schema;
- output schema and score semantics;
- candidate identity;
- exact utility/confidence/OOD outputs and randomized assignment probabilities.

Changing score outputs after commitment fails even when the candidate IDs are unchanged.

## Random assignment provenance

CounterBased assignment cannot be caller-chosen. The scorer/policy-output commitment authenticates the assignment probabilities; `RandomSource` then signs a payload binding the random-stream digest, request sequence as counter, exact draw, abstain mass, candidate identities and that same assignment distribution context.

A randomized request without that evidence fails closed. Deterministic requests reject unexpected RandomSource evidence.

## Frozen-data qualification test

`codex-rs/hepta-intelligence/tests/intuition_frozen_qualification.rs`:

- hashes and parses the retained reference model;
- computes measured ECE and OOD false-acceptance from frozen datasets;
- derives calibration/OOD artifact identities;
- uses a policy digest distinct from the model artifact digest;
- builds an exact feature/scoring commitment;
- creates independent Generator, Scorer, Evaluator and RandomSource trust principals;
- signs the corresponding payloads;
- rejects tampered scorer evidence and missing RNG evidence;
- obtains the current-generation V3 policy decision only after all admission checks pass.

The fixtures prove the chain, not production model quality.

## Two performance gates

The qualification workflow intentionally reports two different latency surfaces.

### Kernel fast gate

`codex-rs/hepta-intuition/examples/fast_gate.rs` measures the pure V3 policy kernel at 1/16/64/128 candidates, including profile and scoring-commitment validation. It reports p50/p95/p99, throughput and allocator activity.

### Authenticated end-to-end gate

`codex-rs/hepta-intelligence/tests/intuition_authenticated_fast_gate.rs` measures the host admission path at 1/16/64/128 candidates. It includes four-role Ed25519 verification, trust/revocation/window checks, signer/controller independence, exact request binding, profile admission, scorer provenance, RNG provenance and the V3 decision.

These CI bounds are regression gates, not target-host production SLOs. Target-host activation must retain its own exact host/profile measurements.

## Remaining non-claims

This source change does not select a production model, prove real future-time calibration efficacy, create a named product caller, prove external intervention execution, grant effect authority, establish operator acceptance, promote an artifact or authorize release.
