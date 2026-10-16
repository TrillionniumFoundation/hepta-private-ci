# Reader failure attribution V1 — four-condition source-scoped hold gate

**RESEARCH ONLY / DRAFT / SHADOW_ONLY / DENY_ALL / NO MODEL OR FINALUSE PROMOTION.**

This is an additive, pure-stdlib, source-free output analysis layered on top of the original #2108/#2115 `prepare -> run -> replay -> score` candidate-level Reader study. It does not replace that study's native Reader, model loader, original V1 score-time reference check, owner labels, producer or independent result journal.

## Scientific question and deliberately narrow estimand

Given identical frozen Reader weights and the four precommitted evidence arms `no_evidence`, `ordinary_retrieval`, `support_candidate`, and `premise_removed`, classify observed candidate errors:

- **Candidate Reader/representation blocker:** reviewer-claimed sufficient evidence is delivered, but the frozen Reader's binary candidate prediction remains wrong.
- **Candidate retrieval gap:** the same Reader predicts the candidate correctly with claimed sufficient evidence, and incorrectly with ordinary retrieval.
- **Evidence usefulness candidate:** ordinary and claimed sufficient evidence are correct, no-evidence prediction is wrong.
- **Premise removal low sensitivity:** two reviewers claim a critical premise made the candidate undecidable, yet the binary probability changes by less than 0.05. This is a sensitivity flag, **not** an accuracy, hallucination or abstention success rate.

All denominators are tied to original `task_id` and original passage `source_group`. Exact or whitespace/case-normalized source-text aliasing across different roots is rejected; it is not proof of independent source families against all paraphrases.

## Input owner separation

Pass five JSON files using read-only, absolute paths and **separately obtained SHA256 values**:

1. Original sealed V1 support plan (no labels).
2. Original label-blind physical observation with all four conditions and original-prediction replay.
3. Independent second physical execution receipt; both call censuses must be complete.
4. Existing owner binary labels (not opened before predictions in the original pipeline).
5. Two separate *post-observation*, label-blind reviewer inventories. Each judgment contains only `task_id`, `source_group`, `support_decidable` and `removed_decidable`; no labels, answer strings or sample omissions are allowed. Both must agree for task-level capacity/retrieval attribution.

Reviewer IDs and the `labels_visible=false` Boolean are **assertions, not cryptographic proof of reviewer independence**. Exact SHA and duplicated-property rejection establish file consistency, not real human adjudication, source ownership, physical re-execution provenance or semantic correctness. The original binary answer label is **never applied** to the `premise_removed` condition.

### Minimal reviewer packet schema (illustration only)

```json
{
  "schema": "hepta.reader.source-blind-adjudication.v1",
  "plan_id": "<exact previously sealed plan digest>",
  "observation_id": "<exact previously sealed Reader observation digest>",
  "labels_visible": false,
  "reviewers": [
    {"reviewer_id":"reviewer-a","rows":[{"task_id":"...","source_group":"...","support_decidable":true,"removed_decidable":false}]},
    {"reviewer_id":"reviewer-b","rows":[{"task_id":"...","source_group":"...","support_decidable":true,"removed_decidable":false}]}
  ],
  "review_id": "<SHA256 of canonical JSON without this field>"
}
```

**Do not generate fake or inferred human reviews.** The example must be extended to cover *every* original task, sourced by separately identified genuine reviewers. Evidence necessity is not established by simply selecting a span and removing it.

### Run on a separately prepared host

```bash
python qualification/stem-cell-v1/reader_failure_attribution_v1.py \
  --plan "$ORIGINAL_SUPPORT_PLAN" --plan-sha256 "$PLAN_SHA" \
  --observed "$ORIGINAL_OBSERVATION" --observed-sha256 "$OBS_SHA" \
  --replay "$INDEPENDENT_REPLAY" --replay-sha256 "$REPLAY_SHA" \
  --labels "$OWNER_LABEL_FILE" --labels-sha256 "$LABEL_SHA" \
  --reviews "$TWO_REVIEWER_FILE" --reviews-sha256 "$REVIEW_SHA" \
  --output "$CREATE_ONLY_REPORT_FILE"
```

The output contains counts and domain-separated root digests only (no original prompt, source, token sequence, raw logits, or human labels). Inconsistencies fail before writing a success report. Every output has `decision=DESCRIPTIVE_HOLD_NO_GO`, `semantic_sufficiency_independently_certified=false`, `reader_capacity_or_retrieval_winner_verified=false`, `production_authorized=false`, and `authority=DENY_ALL`.

## Reproduction and acceptance limits

```bash
python -m unittest discover -s qualification/stem-cell-v1 -p 'test_reader_failure_attribution_v1.py' -v
python -O -m unittest discover -s qualification/stem-cell-v1 -p 'test_reader_failure_attribution_v1.py' -v
python -m py_compile qualification/stem-cell-v1/reader_failure_attribution_v1.py
```

All included tests are **synthetic file and arithmetic tamper fixtures**. There is no new public pretrained ModernBERT/Granite forward, genuine human judgment, stronger reference Reader, source-disjoint future outcome, complete lifecycle cost, trained shared Stem, NDU gain or product deployment. Independent human judgments, real model materials, original label-owning evaluator and forward attestations must be supplied and verified by their rightful owners before scientific advancement. This module never grants those qualifications itself.
