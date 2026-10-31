# POSTHOC query-binding diagnostic

## Trigger and status

This diagnostic was proposed **after the registered IID model results had been
observed**. Several ordinary, renewal-flow and Transformer associative-recall
scores were around .63, close to the query-ignorant majority-value expectation
17/27. This raised a concrete alternative explanation: a model may remember the
bag of values without associating each value to its key.

The diagnostic is posthoc, descriptive and additional to the registered study.
It does not retrain, adjust parameters, choose seeds or select checkpoints. It
must never be relabeled as a preregistered endpoint or an independent new test set.
All 36 frozen recall models are retained: four families, three widths, three seeds.

## Shared raw data and label separation

Replay the first 512 IID examples with seed 1700000 in eight batches of 64, in the
same sequence as the original test evaluator. Verify every batch hash against
each existing IID metric report. Verify replayed original logits and labels
against the first 512 saved test examples for every model.

Decode the three key/value pairs from the raw history independently of the task
generator's returned label. Preserve the complete history, distractors, query
marker and all elapsed times. For each history, replace only the final query-key
one-hot token by key 0, 1 and 2. Recompute the corresponding labels from the same
unchanged history. The model receives raw input and elapsed time only; labels enter
the evaluator after inference and are never passed to the model.

Original and replacement input hashes, shared raw arrays, every model's original
and three-query logits/predictions, subgroup masks and labels are retained.
Every model receives the same 512 histories and all three query substitutions.
The three substitutions share a history and are dependent observations.

## Majority baseline and subgroups

For three independent values uniformly distributed over three classes, there
are 27 possible ordered value triples:

| Pattern | Number of triples | Correct queries for fixed majority prediction |
| --- | ---: | ---: |
| All three the same | 3 | 3 of 3 |
| Exactly two the same | 18 | 2 of 3 |
| All three distinct | 6 | 1 of 3 |

With uniformly queried keys, population majority accuracy is
`(3*3 + 18*2 + 6*1)/(27*3) = 17/27 = .629629...`. A tied majority predicts the
smallest value. Record the empirical majority accuracy on the fixed original
queries as well as on all three substituted queries; neither is assumed to equal
the population expectation in a finite sample.

Report original-query accuracy for every subgroup, plus three-query accuracy and
all-three-query correctness. On an all-distinct history, a query-invariant answer
is exactly 1/3 correct across all three queries and cannot answer all three
correctly. This provides a direct diagnostic that cannot be explained solely by
majority-value retention. Query-dependent predictions alone are insufficient;
they must also be correct for the requested key.

## Metric definitions

- `original_accuracy`: accuracy on the unchanged original query.
- `three_query_mean_accuracy`: correctness averaged over all 512×3 substitutions.
- `all_three_queries_correct_history_rate`: fraction of histories on which all
  three requested keys are answered correctly.
- `query_0/1/2_accuracy`: accuracy for each substituted query key separately.
- `alternative_query_prediction_change_rate`: among the two nonoriginal query
  keys per history, fraction whose prediction differs from the original answer.
- `any_query_prediction_change_history_rate`: fraction of histories whose three
  query predictions are not all identical.
- `pairwise_query_prediction_change_rate`: mean disagreement over the three
  unordered query pairs per history.
- `prediction_change_when_target_changes`: prediction disagreement restricted
  to query pairs whose true labels differ; this measures sensitivity, not accuracy.

The per-model CSV and JSON retain all subgroup results. Summary tables show the
three fixed seeds' arithmetic mean and observed min/max, not confidence intervals.
No pooled significance test is performed.

## Identity and execution

Before inference, verify the existing run config, receipt, IID metric and
checkpoint identities and all frozen source hashes. After inference, confirm
both in-memory parameter arrays and checkpoint files are unchanged. Original-key
substitutions must reproduce the unchanged-query logits. Output directories are
created with `exist_ok=False`; interrupted or completed evidence is preserved.

This script does not itself prove the earlier remote freeze chronology; that
proof belongs to the original owner orchestration receipts. It verifies local
file identities against those records and records its posthoc status explicitly.

Only run after the owner releases CPU time, outside formal timing measurements:

```
python recall_binding_audit.py
```

Default output is `analysis/recall_binding_posthoc/`, containing shared inputs,
36 raw prediction payloads, `per_model.csv`, `summary.json`, and
`RECALL_BINDING_POSTHOC.md`. No existing frozen source is changed.

A full-history score around .63 exceeding a last-input-only score around .33
must not by itself be called evidence that the model learned key-value binding.
Interpret the query substitutions and distinct-value subgroup before making that
claim, and retain the diagnostic's posthoc status in any final report.
