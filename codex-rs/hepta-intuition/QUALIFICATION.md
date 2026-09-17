# intuition.policy authenticated qualification and fast-path contract

This document defines the source-level qualification boundary implemented by
`codex-hepta-intuition`. It does **not** activate a production caller, grant
dispatch/effect authority, select a deployment, or replace independent operator
acceptance.

## 1. Versioned decision paths

- `decide_calibrated` is retained for historical V1 replay.
- `decide_calibrated_v2` binds the complete request and now fails closed when
  `omitted_count_bound != 0` inside `codex-hepta-intuition` itself.
- `decide_calibrated_v3` is the authenticated qualification path. It accepts a
  legacy calibrated request only when the policy profile and the calibration,
  OOD, and completeness qualification artifacts all verify against one
  independently pinned Ed25519 trust anchor.

V3 keeps `AuthorityPosture::DENY_ALL`; a qualified policy receipt is advisory
and cannot dispatch a model/tool or mint effect authority.

## 2. Trust anchor and signed artifacts

`QualificationArtifactVerifierV1` is constructed by the host from:

1. an expected signer `StableId`;
2. a non-zero signer epoch; and
3. an Ed25519 public key supplied outside every artifact envelope.

An artifact cannot choose its own verifier. Detached signatures cover a domain,
artifact kind, canonical artifact digest, signer identity, and signer epoch.
V3 rejects signer/epoch mismatch, malformed/invalid signatures, digest drift,
generation drift, stale windows, and cross-profile/cross-model substitution.

The signed artifact set is:

- `SignedPolicyProfileV1` — canonical thresholds and risk rule revision;
- `SignedCalibrationQualificationV1` — calibration metric plus frozen dataset,
  model/scorer and frozen-prediction lineage;
- `SignedOodQualificationV1` — OOD metric/threshold plus the same frozen
  lineage;
- `SignedCompletenessQualificationV1` — exact generator/grammar/filter,
  candidate set/order/count, zero omission bound, and the scorer outputs used by
  the *current* decision.

The V3 receipt commits to all four artifact digests, the scorer descriptor,
current scorer predictions, the complete request, and the V2 decision receipt.

## 3. Canonical policy profile

Callers no longer choose qualification thresholds on the V3 path. The signed
`CanonicalPolicyProfileV1` freezes:

- `policy_digest` and objective-class digest;
- policy generation and sequence validity window;
- `minimum_confidence`;
- `maximum_ece_ppm`;
- `maximum_ood_false_acceptance_ppm`;
- `maximum_in_domain_score`; and
- the current risk rule (`Low`/`Elevated` may enter the fast path; `High` must
  take the deterministic slow path).

The duplicated V1 request fields are compatibility carriers only. V3 requires
exact equality with the signed profile before it invokes the existing decision
kernel. Changing the risk rule requires a new profile/kernel revision rather
than a caller parameter change.

## 4. Learned scorer ownership and interface

Model fitting, model persistence, and model inference are **not owned by
`codex-hepta-intuition`**. They remain upstream learning/inference
responsibilities and must be composed through a registered product adapter.
`intuition.policy` owns validation and policy selection over authenticated,
bounded scorer outputs.

`LearnedScorerDescriptorV1` is the formal boundary. It commits to:

- producer module identity;
- interface digest;
- feature-schema digest;
- score-semantics digest;
- model digest; and
- generation.

`LearnedScorerOutputBindingV1` additionally commits the state digest, complete
candidate-set digest, and a canonical prediction digest. The prediction digest
covers, for each candidate, `utility`, `calibrated_confidence`, `ood_score`, and
`support_digest`. Legal/hard-veto and assignment-probability fields remain part
of the complete candidate-set commitment rather than learned-score semantics.

Calibration/OOD qualification artifacts bind the same scorer descriptor and
model to their frozen prediction set. The completeness qualification binds the
same descriptor to the current decision's prediction digest. This closes the
previous gap where authenticated historical model evidence could otherwise be
combined with substituted current scores.

## 5. Frozen-data qualification fixture

`qualification/frozen_model_v1.csv` and
`qualification/frozen_validation_v1.csv` are immutable source fixtures for the
focused V3 qualification test.

The test performs this chain in one process:

1. hash the frozen model and validation bytes;
2. score the frozen rows from the model artifact;
3. compute fixed-point expected calibration error with
   `expected_calibration_error_ppm_v1`;
4. compute OOD false-acceptance ppm with
   `ood_false_acceptance_ppm_v1`;
5. construct the current-generation canonical signed profile;
6. construct and Ed25519-sign calibration/OOD qualification artifacts using the
   measured values and frozen lineage;
7. construct and sign completeness over the exact current candidates and
   scorer prediction digest; and
8. call `decide_calibrated_v3` and require the expected advisory decision.

The metric functions are deterministic integer calculations; the test does not
accept caller-supplied ECE/FAR as an oracle.

## 6. Fast-path performance gate

`src/bin/intuition-fast-gate.rs` executes the **authenticated V3 path** in
release mode for candidate counts `1`, `16`, `64`, and `128`. Request cloning is
performed before each timed region, so the measured region is the policy-owned
verification/decision call.

For every size the gate records and prints:

- p50 / p95 / p99 wall-clock latency;
- measured throughput;
- p99 allocation count; and
- p99 allocated bytes.

The initial portable CI ceilings are deliberately conservative enough for a
shared `ubuntu-24.04` runner while still preventing accidental unbounded or
multi-second regressions:

| metric | ceiling/floor |
|---|---:|
| p50 | `<= 10 ms` |
| p95 | `<= 15 ms` |
| p99 | `<= 25 ms` |
| throughput | `>= 40 decisions/s` |
| p99 allocations | `<= 4096` |
| p99 allocated bytes | `<= 1 MiB` |

The benchmark-only global allocator delegates to `System` and counts allocation
operations/bytes. The library continues to forbid unsafe code. Target-host
qualification may impose stricter ceilings; these CI ceilings are not a claim
about production host latency.

## 7. CI gate and stop conditions

`.github/workflows/hepta-intuition-policy-qualification.yml` runs, on relevant
pull requests and pushes to `main`:

- exact-source binding;
- frozen fixture SHA-256 reporting;
- package tests;
- the release-mode `intuition-fast-gate`;
- strict all-target Clippy; and
- rustfmt/diff/clean-worktree checks.

Any signature, lineage, profile, omission, metric, compilation, lint, formatting
or performance failure is a stop condition. Product execution and independent
acceptance remain separate evidence gates.
