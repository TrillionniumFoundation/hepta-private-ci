# `intuition.policy` learned-scorer contract

## Ownership decision

The learned scorer is **external to `codex-hepta-intuition`**. The intuition crate does not load
model weights, execute tensor kernels, train models or own feature extraction. Its responsibility
is to authenticate a learned scorer's current-generation output and then apply bounded,
deterministic intervention-policy semantics over the complete legal candidate set.

This boundary is intentional:

```text
state / frozen context
        |
        v
external learned scorer
(model + feature pipeline)
        |
        | authenticated score batch
        v
codex-hepta-intuition
qualification + policy gates + assignment
        |
        v
advisory decision receipt (DENY_ALL)
```

A future in-crate inference implementation would require a new contract/version; it MUST NOT be
silently substituted behind `LearnedScorerContractV1`.

## `LearnedScorerContractV1`

The canonical contract binds:

- `policy_digest` — policy family the scorer serves;
- `objective_class_digest` — objective class for which calibration is valid;
- `model_artifact_digest` — exact immutable model bytes/snapshot;
- `feature_schema_digest` — exact feature names/order/types/normalization contract;
- `utility_semantics_digest` — definition and units of candidate utility;
- `confidence_semantics_digest` — definition of calibrated confidence;
- `ood_semantics_digest` — definition of OOD score and direction;
- `calibration_artifact_digest` — exact calibration evidence used by the scorer;
- `ood_artifact_digest` — exact OOD qualification evidence;
- `ood_detector_digest` — exact detector implementation/configuration identity;
- `generation` — policy/model generation admitted by the host.

`contract_digest` is recomputed from all fields. An authenticated canonical policy profile binds
that exact contract digest, so swapping the scorer contract changes the profile payload and
invalidates admission.

## Feature schema

`feature_schema_digest` is the stable commitment to the scorer input schema. A production schema
artifact should define at least:

- feature identifier and canonical order;
- scalar/tensor type and dimensions;
- units and normalization;
- missing-value semantics;
- clipping/range rules;
- state/context source and freshness constraints;
- version and compatibility rules.

Per-decision `LearnedScoreEvidenceV1::feature_digest` commits to the exact feature payload used for
that candidate. The intuition crate does not decode the feature vector; it verifies that the
scorer-signed output is bound to the evidence supplied for the candidate.

## Score semantics

Each `LearnedScoreEvidenceV1` contains:

- `candidate_id`;
- `feature_digest`;
- `utility`;
- `calibrated_confidence`;
- `ood_score`;
- `support_digest`.

The ordered evidence batch must have the same length and candidate order as the policy request.
Utility, confidence, OOD score and support digest must exactly equal the values in the matching
`CalibratedActionCandidateV1`. This prevents a caller from authenticating one score batch and
executing the policy with different numeric scores.

The semantics digests in the scorer contract define how those fields are interpreted. They are
not free-form labels at decision time.

## Model and calibration linkage

The scorer contract MUST bind the same calibration artifact and OOD artifact used by the policy
request. It also binds the exact OOD detector digest. The qualified path rejects any mismatch.
This closes the previously ambiguous state in which scores could name a model while calibration
or OOD evidence referred to another generation/model support.

A production promotion therefore advances as one coherent tuple:

```text
(model artifact,
 feature schema,
 score semantics,
 calibration artifact,
 OOD artifact/detector,
 scorer contract,
 canonical policy profile,
 generation)
```

Partial promotion is not admitted.

## Scorer authentication

The scorer output batch is canonicalized with:

- decision id;
- state digest;
- scorer contract digest;
- model artifact digest;
- ordered per-candidate evidence.

That digest is authenticated with the **scorer key**, which is distinct from the artifact
qualification key. The scorer envelope is valid only for the exact decision sequence. A replay at
a different sequence, state or decision id produces a different canonical digest or violates the
sequence window.

The scorer key must be provisioned from trusted host configuration and may be independently
rotated/revoked. Request data can never introduce a trusted scorer key.

## Calibration semantics

`calibrated_confidence` is not accepted merely because it lies in `[0,1]`. The scorer contract
binds the confidence semantics and the exact calibration artifact. The authenticated canonical
profile sets the maximum accepted measured ECE. The frozen qualification vertical recomputes ECE
from committed model bytes and a committed frozen validation set before constructing the
calibration artifact.

Production qualification should additionally stratify/subgroup audit as required by the product
risk model. `CalibrationArtifactV1::subgroup_audit_digest` is the binding point for that evidence.

## OOD semantics

`ood_score` uses the direction defined by the contract: larger values represent stronger evidence
of being out of distribution. `OodArtifactV1::maximum_in_domain_score` is the fast-path admission
threshold. The authenticated profile bounds measured OOD false acceptance.

The production OOD artifact must be generated against the same model/support generation and the
same detector digest bound in the scorer contract.

## Failure behavior

Any of the following fails closed before a qualified fast-path decision is returned:

- scorer contract digest mismatch;
- zero/empty required model/schema/semantics digest;
- model generation mismatch;
- calibration/OOD linkage mismatch;
- evidence count mismatch;
- evidence/candidate value mismatch;
- scorer envelope key/epoch/subject/scope/payload/generation/window mismatch;
- scorer MAC failure.

The qualified policy receipt remains advisory and carries `AuthorityPosture::DENY_ALL`.
