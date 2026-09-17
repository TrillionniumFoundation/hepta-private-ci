# intuition.policy authenticated qualification V3

Status: source implemented on the `codex-hepta-intuition` owner path. Product composition, deployment trust-anchor provisioning, independent operator acceptance, promotion and release remain separate evidence gates.

## 1. Purpose

V3 closes the gap between a request that merely *names* calibration/OOD/completeness digests and a decision that is admitted only after those artifacts are authenticated against the current deployed policy generation.

The production-facing entrypoint is:

```rust
codex_hepta_intuition::qualification::decide_qualified_v3(...)
```

Historical `decide_calibrated` remains a V1 replay/compatibility surface. `decide_calibrated_v2` remains a request-binding compatibility surface and now rejects any non-zero `omitted_count_bound` inside `codex-hepta-intuition` itself. Neither historical surface is the authenticated production qualification boundary.

## 2. Trust model

The host provisions `QualificationVerifierV1` from an independent authority store. The verifier pins all of the following values before it observes a signed artifact:

- qualification issuer id;
- qualification issuer epoch;
- Ed25519 public key;
- current policy digest;
- current policy generation;
- current canonical policy-profile digest.

A signed artifact cannot select its own trust anchor, current generation or current profile. An old but correctly signed artifact therefore fails the current-generation/profile fence.

V3 defines separate signature domains for static policy qualification and dynamic candidate completeness. Cross-use of a signature is prevented by domain-separated canonical digests.

## 3. Canonical policy profile

`CanonicalPolicyProfileV1` is the authenticated source of truth for decision thresholds and risk rules. It freezes:

- `policy_digest`;
- `objective_class_digest`;
- `generation`;
- `minimum_confidence`;
- `maximum_ece_ppm`;
- `maximum_ood_false_acceptance_ppm`;
- whether elevated-risk decisions may stay on the direct path;
- the invariant that high risk forces the slow path;
- the complete learned-scorer contract.

The legacy request fields for confidence/ECE/OOD limits remain for wire/source compatibility. V3 requires them to equal the authenticated profile and then executes from the profile values. A caller therefore cannot loosen a threshold by constructing a different request.

A profile that attempts to disable the high-risk slow-path invariant is rejected before signature admission.

## 4. Learned scorer ownership

Model inference is intentionally **not owned by `codex-hepta-intuition`**. The crate is the bounded policy/qualification kernel. The external learned scorer owns feature extraction and model inference and must conform to `LearnedScorerContractV1`.

The contract binds:

| Field | Meaning |
|---|---|
| `owner_id` | accountable scorer owner/service identity |
| `scorer_service_digest` | exact scorer implementation/service generation |
| `model_digest` | immutable model artifact |
| `feature_schema_digest` | exact feature names, order, types, normalization and missing-value semantics |
| `score_semantics_digest` | exact meaning/scaling of utility, calibrated confidence and OOD score |
| `calibration_link_digest` | exact calibration artifact used to interpret scorer confidence |
| `support_digest` | support/domain definition shared with OOD qualification |

`canonical_scorer_contract_digest_v1` is embedded in the signed policy profile and repeated in every signed candidate-completeness artifact.

The candidate-set digest commits the exact candidate ids, legal/veto flags, utilities, calibrated confidences, OOD scores, assignment probabilities and support digests. Consequently the dynamic completeness signer attests the exact scored set under the pinned scorer contract rather than merely attesting a list of ids.

## 5. Authenticated calibration and OOD artifacts

`CalibrationArtifactV1.artifact_digest` is no longer treated as an arbitrary non-zero reference in V3. It must equal `canonical_calibration_artifact_digest_v1` over:

- policy digest;
- objective-class digest;
- generation;
- validity window;
- measured ECE;
- subgroup-audit digest.

`OodArtifactV1.artifact_digest` must likewise equal `canonical_ood_artifact_digest_v1` over:

- policy digest;
- detector digest;
- support digest;
- generation;
- validity window;
- maximum admitted in-domain score;
- measured false-acceptance rate.

`SignedPolicyQualificationV1` then signs the canonical profile digest, canonical calibration digest, canonical OOD digest, frozen validation-data digest, qualification-report digest and qualification validity window.

The qualification window must be contained by the calibration and OOD validity windows. Measured ECE and OOD false acceptance must satisfy the authenticated profile limits before the qualification artifact is accepted.

## 6. Authenticated candidate completeness

Every decision requires a `SignedCandidateCompletenessV1`. It binds:

- issuer and issuer epoch;
- decision id;
- objective and objective-class digests;
- state digest;
- policy digest and generation;
- sequence;
- current profile digest;
- current scorer-contract digest;
- generator/grammar/hard-filter/truncation digests;
- candidate-set digest;
- canonical-order digest;
- candidate count;
- omitted-count bound.

The canonical digest of this payload **must equal** `CandidateSetCompletenessBindingV1.receipt_digest`, and the Ed25519 signature is verified against the independently pinned key.

`omitted_count_bound` must be exactly zero. V3 returns `IncompleteCandidateSet` otherwise. V2 also fails closed on a non-zero value within the owner crate, so correctness no longer relies on `hepta-intelligence` repeating the check. Consumers should retain their duplicate guard as defense in depth.

## 7. V3 decision sequence

For every qualified decision:

1. validate static qualification shape and metric ranges;
2. verify the issuer/epoch against the pinned trust anchor;
3. enforce current policy digest, generation and profile digest;
4. verify the static Ed25519 policy-qualification signature;
5. enforce the qualification sequence window;
6. validate dynamic completeness shape and `omitted_count_bound == 0`;
7. verify dynamic issuer/epoch, current-generation/profile fences and Ed25519 signature;
8. require request objective/state/policy/sequence fields to match the signed completeness payload;
9. require the signed scorer contract and profile digests to match static qualification;
10. require request compatibility threshold fields to match the signed profile;
11. require request calibration/OOD values to be byte-for-byte equivalent to the signed qualification values;
12. require request completeness values to equal the signed completeness values;
13. apply the authenticated risk rule (high risk always slow path; elevated risk follows the signed profile);
14. execute the bounded V2 decision kernel from the authenticated profile values;
15. emit `QualifiedIntuitionReceiptV3`, binding original request, profile, scorer contract, static qualification, dynamic completeness and inner V2 receipt.

The V3 receipt retains `AuthorityPosture::DENY_ALL`. Qualification is evidence admission, not dispatch or effect authority.

## 8. Frozen-data qualification

The repository-controlled qualification corpus is under:

```text
qualification/intuition-policy-v3/
  frozen_model_v1.json
  frozen_validation_v1.json
```

`codex-rs/hepta-intuition/tests/frozen_qualification.rs` performs the complete vertical path:

```text
serialized frozen model artifact
        -> deterministic model inference
frozen validation corpus
        -> measured calibration ECE
        -> measured OOD false-acceptance rate
        -> canonical calibration/OOD artifacts
        -> canonical learned-scorer contract
        -> canonical policy profile
        -> Ed25519-signed policy qualification
        -> exact scored candidate set
        -> Ed25519-signed completeness receipt
        -> decide_qualified_v3
        -> qualified advisory decision receipt
```

The test additionally proves fail-closed behavior for request threshold loosening, qualification-signature tampering and a non-zero omission bound.

The deterministic key embedded in the test is CI-only test material. Production keys must be independently provisioned and must never be derived from request/artifact bytes.

## 9. Fast-policy benchmark gate

`codex-rs/hepta-intuition/benches/fast_policy.rs` benchmarks the authenticated V3 path, including request cloning, both Ed25519 verifications, canonical binding and receipt construction.

The gate measures candidate counts `1`, `16`, `64` and `128` and fails on any of:

- p50 latency budget;
- p95 latency budget;
- p99 latency budget;
- minimum throughput;
- maximum allocation count per operation;
- maximum allocated bytes per operation.

Current CI budgets are intentionally qualification ceilings rather than product SLO claims:

| candidates | p50 | p95 | p99 | min throughput | max allocs/op | max bytes/op |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 1.0 ms | 1.5 ms | 2.5 ms | 250 ops/s | 256 | 128 KiB |
| 16 | 1.2 ms | 2.0 ms | 3.5 ms | 200 ops/s | 384 | 192 KiB |
| 64 | 2.0 ms | 3.5 ms | 5.5 ms | 125 ops/s | 640 | 256 KiB |
| 128 | 3.0 ms | 5.0 ms | 8.0 ms | 75 ops/s | 1024 | 512 KiB |

`.github/workflows/hepta-intuition-policy.yml` runs unit/integration tests, strict Clippy, the benchmark gate and formatting checks on relevant pull requests and pushes to `main`. The benchmark output is retained as a CI artifact.

These values are not permission to claim a target-host SLO. A product deployment still needs target-host benchmark evidence and the normal operator/canary/release gates.

## 10. Migration rules

- New production composition must call V3, not V1/V2.
- V1 remains historical replay only.
- V2 remains bounded compatibility and request-binding logic; its new zero-omission guard is mandatory.
- A deployment must provision `QualificationVerifierV1` from an authority store outside the remote request.
- Rotating the qualification key increments issuer epoch and updates the independent trust anchor.
- Promoting a new model/profile updates policy/model/profile digests and policy generation, then regenerates frozen-data qualification evidence.
- No artifact is current merely because its signature verifies; it must pass the verifier's current policy/generation/profile fences.

## 11. Remaining external gates

Repository-controlled source now provides the authenticated qualification primitive, frozen-data vertical test and fast-policy CI gate. The following claims still require evidence outside this source implementation:

- a product consumer actually uses V3 on its effect-adjacent path;
- production trust anchors are provisioned and rotated by the named authority owner;
- the production model and validation corpus are the artifacts named by deployment configuration;
- target-host performance satisfies the product SLO;
- independent operator acceptance, canary, promotion and release have completed.

Those gates must not be inferred from source implementation or CI success alone.
