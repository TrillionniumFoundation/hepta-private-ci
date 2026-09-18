# intuition.policy: implementation design

Parent: `docs/modules/intuition.policy/TECHNICAL.md`. Lane: `LANE-F-ADAPTIVE-POLICY`.

Status: bounded calibrated decision, complete-request binding, canonical profile enforcement, per-decision learned-score provenance, four-role signed admission and split kernel/authenticated performance gates are source implemented on this candidate. Product composition, real production artifacts, independent acceptance and release remain separate gates.

## 1. Source and work envelope

Owner root: `codex-rs/hepta-intuition`. Registered consumer adapter: `codex-rs/hepta-intelligence/src/intuition_qualification.rs`.

Package: `INT-1-CALIBRATED-INTUITION-POLICY`.

This source path grants no model/tool/provider/effect authority.

## 2. Native public surfaces

- Historical replay: `decide_calibrated`.
- Request-bound compatibility: `decide_calibrated_v2`.
- Current source path: `decide_calibrated_v3(request, profile, scoring_commitment)`.
- Host admission: `decide_authenticated_intuition_v1`.
- Scoring provenance: `ScoringCommitmentV1` and `scoring_commitment_for_request_v1`.

V2 and V3 reject nonzero `omitted_count_bound`.

## 3. Identity and authority partition

The source separates:

- policy semantics: `policy_digest`;
- immutable learned model: `model_artifact_digest`;
- scorer interface: `scorer_contract_digest`;
- exact feature snapshot/schema;
- calibration/OOD artifact and dataset identities;
- candidate completeness;
- learned outputs;
- random assignment.

No model digest is used as the policy digest by construction.

The policy crate owns no durable state, trust keys, assignment randomness or effect authority.

## 4. Canonical profile

`CanonicalPolicyProfileV1` is the only current-generation threshold/routing source. It binds:

- policy/objective class/generation and profile window;
- confidence, ECE, OOD FAR and maximum in-domain OOD thresholds;
- risk routing;
- model/scorer identities and schemas;
- frozen calibration/OOD datasets;
- admitted calibration/OOD artifact identities;
- measured ECE, subgroup audit, OOD false-acceptance, detector/support;
- exact calibration/OOD validity windows.

Request compatibility fields must equal the profile. Callers cannot loosen them.

## 5. Per-decision provenance and scheduling

The current authenticated flow is:

1. Generator signs candidate identity and completeness.
2. Scorer signs `ScoringCommitmentV1` over model, feature snapshot/schema and exact output values.
3. Evaluator signs the reusable canonical profile qualification.
4. RandomSource signs exact stream + request sequence/counter + draw + assignment distribution for CounterBased requests.
5. The host verifies all evidence through `LearningEvidenceVerifierV1`, including revocation/window/authority and signer/controller independence.
6. The host computes the exact calibrated request digest.
7. V3 validates profile and scoring correspondence, then delegates bounded selection to V2.
8. The authenticated receipt binds exact request, all evidence payloads/signatures and V3 receipt.

Deterministic assignment has no RandomSource evidence. Randomized assignment without it fails closed.

## 6. Verification cases

- INT-01: selected action is legal, not hard-vetoed and has exact logged propensity.
- INT-02: nonzero omission fails inside the intuition crate.
- INT-03: request-local threshold or qualified artifact metadata drift fails before selection.
- INT-04: model/policy/scorer identities are independent and explicitly bound.
- INT-05: score mutation after `ScoringCommitmentV1` fails.
- INT-06: missing/tampered scorer or RandomSource evidence fails.
- INT-07: frozen reference model/data derive ECE/OOD artifacts and exercise the complete signed chain.
- INT-08: kernel and authenticated end-to-end gates both report 1/16/64/128-candidate p50/p95/p99 and throughput.

These are source qualification tests, not production efficacy evidence.

## 7. Performance

Kernel gate: `codex-rs/hepta-intuition/examples/fast_gate.rs`.

Authenticated end-to-end gate: `codex-rs/hepta-intelligence/tests/intuition_authenticated_fast_gate.rs`.

The second gate includes Ed25519 trust verification, role/controller independence, profile/scoring/RNG admission and the V3 decision. CI limits are regression ceilings, not product SLOs.

## 8. Current native implementation and remaining work

Implemented:

- `codex-rs/hepta-intuition/src/calibrated.rs`
- `codex-rs/hepta-intuition/src/calibrated_binding.rs`
- `codex-rs/hepta-intuition/src/qualified.rs`
- `codex-rs/hepta-intelligence/src/intuition_qualification.rs`
- `codex-rs/hepta-learning-ledger/src/signed_evidence.rs`
- `codex-rs/hepta-intelligence/tests/intuition_frozen_qualification.rs`
- `codex-rs/hepta-intelligence/tests/intuition_authenticated_fast_gate.rs`
- `codex-rs/hepta-intuition/examples/fast_gate.rs`

Remaining repository/product work:

- compose a named product caller instead of shadow/qualification-only composition;
- add a native V3 host port for stricter risk routing;
- replace reference fixtures with independently retained production-candidate artifacts;
- retain target-host authenticated end-to-end measurements;
- establish real consumer execution and independent semantic/operator acceptance;
- canary, promotion and release remain external.

The capability claim therefore remains below production activation even though the source implements calibrated-policy mechanics.
