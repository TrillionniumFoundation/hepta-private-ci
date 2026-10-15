# V20 — Real pretrained frozen Stem, equal Head budget, original AG News heldout pilot

**Research only. Never a production model selector or independent NDU/future-window certification.**

V18 real original-pretrained forward and V10 paired material-rehash acceptance
are now established. V20 moves beyond source smoke tests to genuine, small,
heldout supervised learning by TWO real pretrained frozen Encoders, while
keeping independent evidence limits explicit. Neither baseline synthesis nor
model promotion is allowed.

## Pre-registered public corpus

The external corpus is `szhuggingface/ag_news` at immutable dataset commit
`98c532231d96ae10e176a909192ecac548949288` (Apache-2.0).
Only these two original Parquet files are permitted:

| Split | Exact filename | Original SHA-256 |
| --- | --- | --- |
| Train | `data/train_1_1.5k-00000-of-00001.parquet` | `cc35afe9d5e7ff01878c9aeba08bb0bdfa16947702789530b216a580a1bc09d5` |
| Heldout | `data/test-00000-of-00001.parquet` | `2237e86474314bae6c611718e5bd16a42b4e8dfae53bb4a84abdae1bc1c5d3ee` |

Original byte sizes, SHA-256 and dataset row counts are checked BEFORE
sampling. Selection is deterministic and seed 7347, 32 TRAIN examples and
16 HELDOUT examples per each of four classes. Exact text duplicates
between sources are rejected, and all rows are sorted by a stable ID.
The original test set is a heldout public benchmark, NOT a time-sealed
future stream. Its publicly published labels remain known in general.

## Three separate process phases

1. `prepare`: freezes original source bytes and emits `train.jsonl`
   (texts + train labels), `heldout-source.jsonl` (texts ONLY),
   `heldout-targets.jsonl` (heldout labels ONLY) and canonical SHA-bound plan.
2. `fit-predict`: receives only training inputs and heldout source text.
   It revalidates the **actual V10 joined** frozen model manifest, reloads
   each original pretrained checkpoint through `execution.LocalEncoder`,
   and encodes exactly the same articles. Models are FP32, 384-dimensional,
   native pooling: mmBERT mean and Granite CLS+unit L2.
   Two equal 384x64/rank-8/4-class `StateGatedCellHead` arms are trained per
   model: genuine labels and a shuffled-training-label negative control.
   Both run 64 identical AdamW steps, minibatch 32, seed 7347; pretrained
   Encoder weights are frozen. Head weights and paired source-only
   probabilities are saved. CPU, wall, RSS and actual Encoder forward counts
   are observed and reported rather than imputed.
3. `evaluate`: runs **separately**, receives the heldout targets, and
   independently scores both pretrained arms on the same 64 cases:
   accuracy, multiclass Brier, log loss, ECE and class recall. It checks
   source/target SHA-256, candidate coverage, Head budgets and authority.

The uniform-probability arm is a chance reference only and is explicitly
named `uniform_reference_not_no_change`. **The real deployed no-change
baseline has NOT been observed**; no fake no-change probabilities are
manufactured. The dataset is not an independent prospective future window;
negative transfer against a deployed system and NDU cannot be inferred.

All reports have `winner: null`, `selection_permitted: false`,
`production_accepted: false`, `authority: DENY_ALL`.

The push-only GitHub workflow performs exact model acquisition and original
V10 handoff, freezes dataset, trains Head arms, runs independent evaluator
and retains **numeric-only** evidence (no original model weights, input
text, heldout target labels or Head weights are uploaded).
The paired text workload is a research baseline only. Next: independent
heldout/training provenance, deployed no-change, future-window drift tests,
negative transfer and target-host 64–4096 Cell measurement.
