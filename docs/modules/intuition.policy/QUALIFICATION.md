# `intuition.policy` authenticated qualification

## Status and claim boundary

This document defines the production-oriented qualification boundary implemented by
`codex-rs/hepta-intuition/src/qualified/`. It closes the earlier gap in which a request could
name calibration, OOD and completeness digests without the policy crate authenticating the
named qualification material. The qualified boundary also authenticates the exact assignment plan so caller-controlled exploration probabilities, random-stream identity, draw, or abstain mass cannot drift after qualification.

The authenticated path is `qualified::decide_qualified_v1`. Historical
`decide_calibrated` remains available for V1 receipt replay. The bound V2 path,
`decide_calibrated_v2`, is the minimum executable path for new callers and rejects any
candidate-set completeness receipt with `omitted_count_bound != 0` before producing a V2
request commitment.

This qualification does not itself grant execution authority. All receipts preserve
`AuthorityPosture::DENY_ALL`.

## Trust model

Qualification uses HMAC-SHA256 over canonical payload digests. The implementation deliberately
uses the repository SHA-256 digest primitive, so the crate adds no new cryptographic dependency
or lockfile edge.

Three trusted keys are required and MUST be independently provisioned by the host:

- **artifact qualification key** — authenticates the canonical policy profile, calibration
  artifact, OOD artifact and decision-specific candidate completeness receipt;
- **learned scorer key** — authenticates the decision-specific learned-scorer output batch;
- **assignment key** — authenticates the decision-specific action-assignment plan, including ordered candidate probabilities, assignment mode, random-stream identity, exact draw and abstain probability.

Each key carries a stable key identifier, key epoch and revocation state. The MAC envelope also
binds the subject, artifact class/scope, canonical payload digest, policy generation and valid
sequence interval. A revoked key, wrong key epoch, wrong subject, wrong scope, wrong payload,
wrong generation, invalid interval, expired interval or invalid MAC fails closed.

HMAC is a symmetric authentication mechanism. Any holder of a trusted MAC key can mint an
envelope for that key. Therefore host key custody is part of the trusted computing base. This
contract provides integrity and authenticity relative to the configured secret key; it is not a
public-key non-repudiation scheme. Production key material MUST NOT be supplied by a decision
request and MUST NOT be stored in qualification fixtures.

## Canonical authenticated material

The qualified path recomputes canonical content digests instead of trusting opaque caller
digests:

1. `CanonicalPolicyProfileV1`
2. `CalibrationArtifactV1`
3. `OodArtifactV1`
4. `CandidateSetCompletenessBindingV1`, additionally bound to state, policy generation and
   decision sequence
5. `LearnedScorerContractV1`
6. the per-decision ordered `LearnedScoreEvidenceV1` batch
7. the exact decision-specific assignment commitment produced by `canonical_assignment_digest_v1`

The authenticated profile transitively binds the learned-scorer contract. The scorer contract
binds the exact model artifact, feature schema, score semantics, calibration artifact, OOD
artifact and OOD detector. Calibration/OOD bodies are then independently recomputed and
authenticated. Completeness, scorer-output and assignment envelopes are decision-specific and MUST have a
validity interval equal to the decision sequence.

## Canonical policy profile

`CanonicalPolicyProfileV1` is authoritative for policy thresholds. Request fields are retained
for wire compatibility, but they are only accepted when they exactly mirror the authenticated
profile:

- `minimum_confidence`
- `maximum_ece_ppm`
- `maximum_ood_false_acceptance_ppm`
- risk-policy identifier
- `require_zero_omissions`

A caller therefore cannot relax ECE/OOD/confidence limits by sending different request values.
V1 currently qualifies `RiskPolicyV1::HighAlwaysSlowPath`: low and elevated risk may enter the
calibrated fast path and high risk is routed to the existing slow path. Reserved risk policies
fail closed until the calibrated kernel has matching slow-path semantics.

## Candidate completeness

New bound decisions require `omitted_count_bound == 0` inside `codex-hepta-intuition` itself.
The V2 request commitment rejects non-zero omission before calling the historical calibrated
selector. `decide_qualified_v1` independently requires the authenticated canonical profile to
set `require_zero_omissions = true` and rejects non-zero omission before artifact admission.
Consumer-side checks remain useful defense in depth but are no longer the primary enforcement
point.

## Assignment provenance

`canonical_assignment_digest_v1` binds the assignment authority to the exact decision context: decision/state/objective/policy identity, authenticated policy profile, authenticated scorer output, policy generation and sequence, ordered candidate assignment probabilities, assignment mode, random-stream digest, exact draw and abstain probability. The resulting digest is authenticated with the independently provisioned assignment key and is valid only for the exact decision sequence.

Candidate completeness already commits the complete candidate-set bytes, including candidate-level assignment probabilities, but completeness authority is not treated as assignment authority. The separate assignment envelope makes ownership explicit and additionally binds counter-based randomness that is not part of the candidate set. Changing a normalized distribution from 50/50 to 100/0, swapping the random stream, or changing the draw therefore invalidates assignment authentication before policy execution.

The assignment authority attests that the supplied distribution/random draw is the approved one for the decision. Correct generation of the random stream remains a responsibility of the trusted assignment issuer and host random-stream boundary; a nonzero digest alone is never accepted as that proof.

## Current-generation rule

The trusted host supplies `QualificationTrustV1::expected_generation`. The profile and scorer
contract must match that generation and the request `policy_generation`. Every MAC envelope must
also carry that generation. The existing calibration/OOD checks additionally require their
artifact generation to match the request policy generation.

Sequence validity remains explicit. Long-lived profile/calibration/OOD envelopes may cover a
bounded sequence interval. Completeness, scorer output and assignment are single-decision artifacts and are
required to be valid only at the exact decision sequence.

## Frozen qualification vertical

The repository-owned qualification fixture lives under:

- `qualification/intuition-policy/frozen-v1/model.snapshot`
- `qualification/intuition-policy/frozen-v1/validation.csv`
- `codex-rs/hepta-intuition/tests/frozen_qualification.rs`

The test reads the actual committed model bytes, computes the model artifact digest, performs
reference inference over the frozen validation set, computes ECE and OOD false acceptance from
those predictions, writes those measured values into canonical calibration/OOD artifacts,
authenticates all required material with fixture-only keys, and finally executes
`decide_qualified_v1`.

The reference snapshot is a deterministic qualification model, not a claim that this tiny model
is the product model. A production promotion substitutes an immutable production model artifact
and frozen dataset while preserving the same model-digest → measured-metrics → authenticated
artifacts → policy-decision chain.

## Key rotation and revocation

A production host should treat `(key_id, key_epoch)` as the admitted key identity for each of the artifact, scorer and assignment roles. The three roles require distinct key identifiers and distinct secret material; reusing the same HMAC secret under different identifiers is rejected. Rotation
increments the epoch or changes the key identifier. Old epochs are not accepted by a trust
configuration holding the new epoch. Emergency revocation sets the trusted key record to
revoked; both issuance helpers and verification then fail closed.

Because this crate does not own secret storage, durability, recovery and operator key rotation
belong to the host security/qualification boundary. The crate owns canonicalization and
verification behavior.

## Required CI

The dedicated workflow is `.github/workflows/hepta-intuition-policy.yml`. It runs:

```bash
cargo test --locked --manifest-path codex-rs/Cargo.toml -p codex-hepta-intuition
cargo clippy --locked --manifest-path codex-rs/Cargo.toml -p codex-hepta-intuition --all-targets -- -D warnings
cargo fmt --manifest-path codex-rs/Cargo.toml --package codex-hepta-intuition -- --check
cargo test --locked --release --manifest-path codex-rs/Cargo.toml \
  -p codex-hepta-intuition --test fast_benchmark_gate -- --ignored --nocapture
```

Exact-head and deterministic synthetic-merge qualification are both required on pull requests.
