# E2 semantic task readout — independent causal gate (research only)

This is the next experiment after the V0/V1 feature-geometry bridge. A higher
cosine score is **not** evidence that a Cell used image/audio/video evidence
to complete a real task. This patch adds a strictly source-pinned independent
task-outcome evaluator with the following complete paired arms:

- `text_only`: frozen text Stem without visual input.
- `ocr_text`: OCR converted into text then passed to same Stem.
- `unaligned_vision`: untrained visual feature, negative control.
- `aligned_bridge`: train-only fitted bridge + Cell inference.
- `native_multimodal`: separately pinned native multimodal model.

Case conditions: `text_sufficient`, `vision_required`,
`visual_evidence_removed`, `visual_evidence_swapped`.
Answers are evaluated as exact registered labels, not free-form semantic
equivalence; the labels and whether an image is necessary require independent
human/benchmark review. Add an audio temporal protocol in a distinct
version rather than mislabeling image scores as audio/video performance.

## Roles, leakage prevention, and execution

1. Source/label owner defines original cases, group identities and
   `future1`/`future2`/`future3` chronological windows.
2. Training owner receives only TRAIN and permitted calibration data, fitting
   any bridge only on TRAIN. The prediction owner receives future source
   inputs **without target labels** and emits all 5 arms for every case.
3. Seal future-only predictions as a byte-identical SHA-256 artifact
   before the independent scorer receives targets.
4. The scorer rechecks exact case/arm parity, no train partition, strict
   source digests, disjoint future group sets, absence of target-bearing
   fields in predictions, and exact per-case answer results. A missing
   modality/arm is a failure rather than a zero or excluded case.
5. Report correctness, rescued/harmed relative to `text_only`,
   split by both chronological window and evidence intervention.
   Favorable geometry alone is insufficient, and this scorer never emits
   a selected Stem.

### Schema

Prediction file:

```json
{"schema":"hepta.e2.semantic-predictions.v1",
 "rows":[{"case_id":"example-01","arm":"text_only",
          "answer":"yes","source_sha256":"<64 hex>"}]}
```

Independent target-only file:

```json
{"schema":"hepta.e2.semantic-targets.v1",
 "rows":[{"case_id":"example-01","group_id":"source-A",
          "condition":"vision_required","label":"no",
          "source_sha256":"<64 hex>","partition":"future1"}]}
```

Files must contain a **complete Cartesian product of cases and five arms**;
the one-row fragments above are illustrative only. Hashes are independently
supplied exact byte pins, not provenance signatures or ground-truth authority.

```sh
PYTHONPATH=experiments/shared_stem_cell python3 -m unittest \
    discover -s experiments/shared_stem_cell -p test_e2_semantic_outcomes.py -v

python3 experiments/shared_stem_cell/e2_semantic_outcomes.py \
    --predictions sealed-predictions.json \
    --predictions-sha256 "$PRED_SHA" \
    --targets independent-future-targets.json \
    --targets-sha256 "$TARGET_SHA" \
    --output new-readout.json
```

## Remaining actual blockers

This evaluator **does not load real images, model weights, or train a bridge**.
It is an additive readout component to be connected to the pre-existing
`multimodal_alignment.py` and actual model-forward pilot. Complete real
future visual data, authentic publisher material, source-independent label
adjudication, task-relative confidence and abstention, negative transfer,
fair token/compute/Head budgets, hardware RSS/p95/p99, genuine deployed
no-change, three real prospective windows, and native Worker FinalUse/revoke
remain hard blockers. Latest exact-head and prospective merge `blocking-ci`
are mandatory. Keep **DRAFT / SHADOW_ONLY / DENY_ALL**; no main merge or
production activation from these contract tests.
