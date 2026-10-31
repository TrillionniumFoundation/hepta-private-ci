# POSTHOC associative-recall query-binding audit

**Posthoc diagnostic; no retraining or checkpoint selection.**

POSTHOC: after observing the registered IID results, the owner noticed that many associative-recall scores were near the query-ignorant majority-value expectation 17/27. Full-history improvement over last-observation-only therefore does not by itself establish key-value binding.

## Data and counterfactual contract

This reuses the first 512 original IID test histories, generated with seed 1700000 in eight batches of 64. Each frozen model is checked against its saved original logits. The history, distractors, query marker and clock remain fixed; only the final query-key token is replaced by each of 0, 1 and 2. Labels are independently decoded from the unchanged history and are passed only to the evaluator.

The three counterfactual queries are dependent observations sharing one history. This is not a new independent held-out dataset. Results are descriptive, with no p-value or confidence interval.

## Query-ignorant majority reference

With three IID values drawn uniformly from three classes, the 27 value triples contain 3 all-same, 18 two-same and 6 all-distinct cases. A fixed majority prediction is correct on 3, 2 and 1 of the three possible queries respectively. Therefore its population accuracy is (3×3 + 18×2 + 6×1)/(27×3) = 17/27 ≈ 62.963%. Ties are broken toward the smallest value. This reference uses history contents but ignores the query key.

Observed subgroup sizes in these fixed histories: {'all_distinct': 114, 'two_same': 337, 'all_same': 61}.

A query-invariant prediction has exactly 1/3 accuracy across the three queries of an all-distinct history, and cannot answer all three correctly. Prediction changes alone do not establish binding: correctness after the query change is necessary.

## All frozen model results

Numbers are percentages, shown as mean [seed minimum, seed maximum] over seeds 11/23/37. Three-query accuracy averages the three queries; all-three measures the fraction of histories on which every query is answered correctly. Change rate compares each of the two alternative queries with the original-query prediction.

| Family | Width | Original accuracy | Three-query accuracy | All three correct | Alternative-query change | Distinct three-query accuracy | Distinct all three correct |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| ordinary | 16 | 63.80 [62.89, 64.84] | 63.48 [63.28, 63.67] | 11.98 [11.91, 12.11] | 2.67 [1.66, 4.39] | 34.50 [33.63, 35.38] | 0.29 [0.00, 0.88] |
| ordinary | 32 | 63.02 [62.30, 63.87] | 63.43 [63.35, 63.61] | 11.91 [11.91, 11.91] | 2.51 [1.37, 3.91] | 34.31 [33.92, 35.09] | 0.00 [0.00, 0.00] |
| ordinary | 64 | 62.37 [61.72, 63.09] | 62.70 [62.43, 63.15] | 12.43 [11.91, 13.28] | 3.81 [1.95, 5.18] | 33.33 [31.87, 34.80] | 0.00 [0.00, 0.00] |
| analytic | 16 | 63.54 [62.70, 64.06] | 63.41 [62.89, 63.93] | 11.98 [11.91, 12.11] | 2.70 [1.17, 5.18] | 34.21 [31.87, 36.55] | 0.29 [0.00, 0.88] |
| analytic | 32 | 63.02 [62.11, 63.67] | 63.32 [63.28, 63.41] | 11.91 [11.91, 11.91] | 2.31 [1.56, 3.42] | 33.82 [33.63, 34.21] | 0.00 [0.00, 0.00] |
| analytic | 64 | 62.24 [61.13, 63.09] | 62.83 [62.17, 63.22] | 12.37 [11.91, 13.09] | 3.65 [2.05, 4.49] | 33.92 [33.04, 34.50] | 0.00 [0.00, 0.00] |
| lif_surrogate | 16 | 37.63 [33.59, 44.34] | 38.02 [34.11, 45.31] | 5.99 [4.10, 8.40] | 0.00 [0.00, 0.00] | 33.33 [33.33, 33.33] | 0.00 [0.00, 0.00] |
| lif_surrogate | 32 | 38.74 [33.59, 48.83] | 38.37 [32.94, 47.53] | 4.95 [2.93, 6.45] | 0.00 [0.00, 0.00] | 33.33 [33.33, 33.33] | 0.00 [0.00, 0.00] |
| lif_surrogate | 64 | 42.84 [33.59, 54.10] | 44.42 [34.64, 55.47] | 8.33 [5.47, 11.91] | 0.00 [0.00, 0.00] | 33.33 [33.33, 33.33] | 0.00 [0.00, 0.00] |
| transformer | 16 | 62.70 [61.72, 64.06] | 63.02 [62.96, 63.09] | 12.43 [11.91, 13.28] | 12.37 [11.23, 13.87] | 32.85 [32.16, 33.63] | 0.88 [0.00, 1.75] |
| transformer | 32 | 61.72 [60.94, 62.30] | 62.22 [61.85, 62.76] | 13.41 [12.11, 15.82] | 14.68 [11.13, 18.65] | 32.36 [30.70, 35.09] | 0.58 [0.00, 1.75] |
| transformer | 64 | 61.59 [59.96, 63.48] | 61.20 [59.24, 62.50] | 12.04 [11.91, 12.30] | 10.29 [0.00, 15.43] | 32.16 [30.12, 33.33] | 0.58 [0.00, 1.75] |

## Reading this evidence

A full-history advantage over last-observation-only can reflect retention of the bag of values. It does not by itself establish that the model associates each value with its key and responds to the requested key. This audit adds query-conditioned counterfactual correctness and the all-distinct subgroup to distinguish those possibilities.

The diagnostic was motivated by already-observed model results and must remain labeled posthoc. It does not replace the original registered scores or retrospectively convert this task into a successful binding benchmark. Frozen sources and checkpoint files are unchanged; input hashes, original-score consistency, in-memory parameter hashes, predictions and logits are saved alongside the report.
