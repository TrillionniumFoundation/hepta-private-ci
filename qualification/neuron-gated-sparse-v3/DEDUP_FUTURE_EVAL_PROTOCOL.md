# Frozen physical model identity before future evaluation (A3 shadow)

**RESEARCH ONLY.** Stacked on Draft #2019 / #1979 / #1884, not main. No
selected Cell V1 weight, CAS checkpoint, authority final-use or CNS route is
changed. This module produces no runnable execution permission.

## Why: nominal cap aliases are not independent learned models

The existing 5-ceiling x 4-arm physical synthetic study can store **20 files
but only four effective models**. Each arm's five cap labels may point to
identical physical tensors, and simply applying a second file SHA or a
different safetensors metadata label cannot manufacture a new statistical
model hypothesis. Counting the resulting 20 evaluations independently would
artificially inflate selection multiplicity and confidence.

The additive dedup_prospective_gate.py CLI requires an existing **frozen,
hash-pinned** training receipt, all 20 physical candidate safetensors,
v2 pre-outcome seal, and separately signed witness/outcome envelopes. It
runs the current precommit_future.score verifier itself using two supplied
trusted Ed25519 public keys. It never accepts cached unsigned score summaries
as evidence. Its signed timestamp/host statements are *format checks*, not
independent trusted-clock or genuine production-execution attestation.

Before counting candidates it also reruns realized_budget_audit.audit to
check tensor names, shapes, dtype, actual bytes, signed Q24 bounds and
parameter caps, then binds the sealed predictions to the exact training
receipt, common Cell/Encoder/cutoff and frozen selected V1 SHA.

## Canonical tensor fingerprint and alias safety

Model identity is keyed by (arm, **canonical physical tensor digest**).
The digest includes every tensor's name, dtype, shape and exact payload,
with length-delimited binary data and a versioned domain separator. It
deliberately ignores safetensors JSON ordering and descriptive metadata,
which would otherwise let copies of identical weights count as new models.

Each candidate model is scanned with a pinned physical SHA and immutable
file-identity stat check; after scoring, all 20 model SHA checks run again.
Within one canonical model group, every alleged alternative budget label
must emit the **same case-level future and OOD probabilities** and exactly
the same independently scored summary. A divergent prediction or metric
blocks the entire evaluation rather than voting the two labels separately.

Different model arms are *not* combined merely because their weights have
identical serialized values: the temporal equation defines model semantics.
The no-change V1 Owner baseline remains an *external*, frozen comparator.

## Read-only signed future CLI

    python qualification/neuron-gated-sparse-v3/dedup_prospective_gate.py \
      --trained-root "$PHYSICAL_STUDY" \
      --training-receipt-sha256 "$EXACT_TRAIN_SHA" \
      --seal-file "$SEALED_FUTURE" \
      --seal-sha256 "$EXACT_SEAL_SHA" \
      --signed-witness "$SIGNED_PRECOMMIT_WITNESS" \
      --witness-pubkey "$INDEPENDENT_WITNESS_PUBLIC_PEM" \
      --signed-outcomes "$SIGNED_FUTURE_LABELS" \
      --outcome-pubkey "$INDEPENDENT_OUTCOME_PUBLIC_PEM" \
      --report "$CREATE_ONLY_REVIEW_JSON"

For a synthetic-only test, explicitly add --synthetic-canary. Never pass
synthetic key material as an actual A0 or signed target-host authority.

The emitted versioned output (deduplicated-future-model-review.v1)
reports the **unique model groups**, every nominal cap alias, physical
realized private parameters/bytes, future and OOD Brier claims, redundant
cap label count, separate no-change baseline marker and a
**descriptive parameter-vs-Brier Pareto frontier**. This frontier is not
a causal/utility model selector; Brier alone cannot establish NDU benefit,
negative transfer, calibration, or full system resource performance.

All reviews force:
- independent_future_ndu_causality_verified = false
- f32_native_q24_parity_verified = false
- ndu_eligible = false
- production_qualification = false
- decision = NO_MODEL_PROMOTION

The output file is created exclusively; no earlier signed research
review may be overwritten in place.

## Runnable source regression

    python -m unittest discover \
      -s qualification/neuron-gated-sparse-v3 \
      -p test_dedup_prospective_gate.py -v

The 13 local tests exercise actual physically serialized safetensors for
all 20 nominal candidates. They cover four independent hypotheses,
metadata-only SHA changes, changed tensor SHA, duplicate future prediction
drift, duplicate signed-summary drift, wrong V1/Encoder/training binding,
missing future/OOD, tampered cohort, false production claims and correct
create-only behavior. One test generates distinct Ed25519 witness and
outcome keys, checks legitimate chronology through the actual
precommit_future.score and the end-to-end new CLI, then verifies that
backdating labels is rejected.

Run the preceding 15 actual-byte budget tests separately. Passing all
28 tests confirms only source invariants under synthetic fixtures; hosted
CI on the exact Git SHA and target-host A0/A4 remain independent blockers.

## Scientific next

Actual learning comparisons must hold a common pre-registered Encoder,
dataset chronology, optimizer/FLOPs, model-loading identity and Q24
mechanism fixed while measuring future labels and negative-transfer NDU.
Duplicate budget labels get **one** candidate estimate/variance cluster,
not independent significance. Incomparable private model dimensions
require cost/quality Pareto analysis, not a manufactured equal-parameter
victory. Even a favorable shadow Pareto result never authorizes Cell
migration, CNS cutover or effects.
