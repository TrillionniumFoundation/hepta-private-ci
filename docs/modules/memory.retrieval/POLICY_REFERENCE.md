# memory.retrieval policy reference

## Policy ownership

A production policy is protected host configuration. Requests may select neither weights nor safety thresholds. The policy digest is included in the Lane C generation vector and therefore changes only through an authenticated context rotation.

## Retrieval policy fields

- `channel_weights`: canonical, unique channel entries. A zero weight disables semantic contribution and cannot satisfy coverage.
- `maximum_candidates`: hard owner/channel capacity, never a soft hint.
- `maximum_results`: final upper bound after admission and safety handling.
- `minimum_total_score`: score floor for the policy-admitted set.
- `maximum_ood`: calibrated maximum OOD probability for admitted candidates.
- `minimum_distinct_channels`: counted only from positive-weight admitted evidence.
- `abstain_on_contradiction`: permits whole-request abstention only for an unresolved opposite-polarity proposition inside the admitted set.

## HNMF dynamics

- `minimum_activation` must be in `(0, 1]`.
- `leak` and `lateral_inhibition` are in `[0, 1]`.
- zero-weight edges never expand semantic support, alter activation, or create contradiction receipts.
- active confidence is `sum(activation × confidence) / sum(activation)`.
- node, edge, hop, step, population and active-node limits are hard validation bounds.

## Contradiction model

A contradiction claim is identified by a non-zero proposition digest and one polarity: `Affirms` or `Denies`. An unresolved conflict requires both polarities for the same proposition after policy admission. Multiple records with the same polarity are independent support only when their source identities are independently valid; they do not cause abstention by count alone.

## Vector owner

The vector index snapshot binds:

- Lane C generation-vector digest;
- encoder/index owner generation;
- model digest;
- fixed dimension;
- exact record revision and content identity;
- calibrated per-record OOD probability;
- canonical index digest.

Queries must bind the same generation and model, remain within 512 emitted candidates, and use components in `[-1, 1]`. Similarity is deterministic fixed-point normalized L1 similarity. A future model may replace the similarity rule only through a versioned API and digest domain.

## Product profiles

The intended operating states are:

- **compatibility**: SQLite owner ranking only; no HNMF claim.
- **shadow**: run HNMF and record comparison receipts, never change delivered context.
- **canary**: HNMF delivery only for an authenticated deterministic cohort; retain compatibility comparison.
- **required**: every retrieval requires a current leased context and fails closed on absence, expiry, rotation or revocation.

Until the runtime dispatch implements all four states and target-host evidence is accepted, only the existing compatibility and fail-closed required composition may be treated as implemented.

## Calibration and change control

Threshold changes require a new policy digest, exact-head tests, calibration evidence, canary comparison and rollback rehearsal. A policy with `maximum_ood=1`, `minimum_total_score=0` and one-channel coverage is a compatibility baseline, not a calibrated production-safety profile.
