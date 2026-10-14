# Shared Stem V6 — independently pinned operator material admission

**Research-only control. No pretrained model, publisher, future-learning, NDU,
production authorization or release capability is conferred.** This is an
additional *preflight* for physically staged candidates used by the V5
train/predict path, not a substitute for V5's real `LocalEncoder` forward or
its independently evaluated V4 no-change baseline.

## Problem closed

V5 checked manifest SHA-256, actual model tensor materialization and isolated
train/predict phases. An attacker who authored their own checkpoint could
compute perfectly valid SHA-256 hashes and call it `mmbert_small` or
`granite_97m`. An exact hash cannot establish who reviewed that checkpoint or
whether the weights came from a publisher.

V6 requires an independently installed SHA-256-pinned operator trust store,
an Ed25519 signature from the corresponding private review key, an exact
frozen V4 plan and V2 profile, a bounded expiry/revocation policy and the
actual saved model file bytes. It physically reads safetensors tensor *headers*
to verify the stored floating-element count is consistent with the signed
claim and the operator-pinned model policy. The signature covers the model
repository/revision, candidate, plan, profile, snapshot and claimed tensor
inventory under a dedicated domain separator.

This attests only that **the operator's registered review key signed this
material claim**, not that the model publisher signed it. No real publisher
signature or independently validated training provenance is yet available.
The trusted store SHA **must be pinned by a separate host/CI policy**; an
attacker-supplied key and digest cannot bootstrap their own trust. A research
key must not be treated as a production authority key. Private signing keys
MUST NEVER be committed to the repository or placed inside model artifacts.

## Model policy

The operator-owned trust store uses schema
`hepta.stem-offline-operator-trust.v6` with a single key, issuer, sorted
`allowed_models` (candidate name, expected upstream repository, output width,
model kind, minimum/maximum *saved floating tensor elements*) and sorted
revocation sets for snapshot digests and signing key digests.

The signed assertion schema is `hepta.stem-offline-operator-claim.v6`, with
`issuer`, a bounded `signed` object (candidate, plan/profile/snapshot SHA,
upstream repo/revision, actual floating element count, issued/expiry UNIX
seconds) and a lowercase-hex Ed25519 signature. It must be created by a
separate operator reviewer *after* examining the actual model material and
release provenance, **not by the candidate training process itself**. A claim
can live for at most 30 days and may be revoked earlier.

`mmbert_small` and `granite_97m` policy entries should use independent official
repository IDs and the appropriate 384D output. Their numerical weight ranges
must be frozen from real, reviewed model file inventories, not inferred from a
model nickname or manually padded to pass a policy. Current available official
model information includes mmBERT-small ≈140M model parameters and Granite
97M Multilingual R2 ≈97M. Stored floating elements are not the same thing as
unique trainable parameters, especially with tied weights and task heads.

## CLI

The operator must independently pin `TRUST_SHA` and stage the complete
model snapshot. Reuse the existing V4 plan / V2 profile and explicitly
precompute the canonical JSON file SHA-256 for every document. Admission
must run on the same exact model bytes to be used for training and for
prediction, and a changed generation or candidate requires revalidation.

```sh
python experiments/shared_stem_cell/multimodal_material_admission.py \
  --plan plan.json --plan-sha256 PLAN_SHA \
  --profile granite-profile.json --profile-sha256 PROFILE_SHA \
  --model-snapshot /offline/model-root \
  --operator-trust /separately-owned/trust-store.json \
  --operator-trust-sha256 HOST_PINNED_TRUST_SHA \
  --signed-claim /operator-reviewed/claim.json \
  --signed-claim-sha256 SIGNED_CLAIM_SHA \
  --output /independent-new-receipts/model-admission.json
```

The result is a *new-file-only* canonical JSON receipt recording the exact
identities and observed file/tensor inventory. Its terminal flags include:

- `operator_review_signature_verified: true` when this gate succeeds;
- `local_snapshot_bytes_verified: true` when this gate succeeds;
- `model_publisher_authenticated: false`;
- `actual_pretraining_proven: false`;
- `task_efficacy_proven: false`, `independent_ndu_verified: false`;
- `worker_final_use_authorized: false`, `production_accepted: false`.

The output **does not sign itself** or grant a physical worker capability.
V6 now also **requires admission in the existing V5 command-line train and
predict entrypoints for all non-fixture candidates**. Both phases rescan the
physical saved model and reverify the signature, plan and independent trust
root. The train receipt is bound to the reviewed assertion SHA-256, and predict
rejects a training receipt bearing a different assertion. V5 `tiny_random` is
an explicitly unreviewed mechanism fixture and may not attach V6 credentials.

The direct research Python `train()`/`predict()` functions are not authorization
entrypoints, and the V4 evaluator still does not independently authenticate
these local receipts. A future production caller must authenticate the review
receipt through the dedicated owner, verify physical model identity at final
use and enforce generation fencing before any activation. This implementation
does not make the V5 results production-authorized.

## Verification and unresolved external evidence

Run `PYTHONPATH=experiments/shared_stem_cell python -m unittest discover
-s experiments/shared_stem_cell -p test_multimodal_material_admission.py -v`.
This suite uses real local safetensors and generated ephemeral Ed25519 keys,
never a pretrained checkpoint or a checked-in private key. Tests exercise
signature failure, other keys, external anchor drift, scope/plan/model swaps,
revocation, expiration, byte modification, truncated/missing/extra files,
symlinked roots, tensor inventory, and non-overwrite CLI receipts.

A complete candidate selection still requires: genuine published revision
verification and publisher/custodian review, actual mmBERT and Granite weights,
qualified model forward, frozen fair Head training, independently frozen
no-change, source-disjoint future-task readout, independent NDU and negative
transfer, real physical Worker final-use fencing, and target-host p95/p99 and
crash/recovery evidence. None has been fabricated by this preflight.
