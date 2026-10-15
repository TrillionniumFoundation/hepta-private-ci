# P0 V5 — Independent numeric replay of physically trained Head artifacts

**RESEARCH / SHADOW / `DENY_ALL`.** This increment is stacked on #2140's
exact frozen development commit `8d9ab972f395df0857f7275b567daa761f017dc2`.
It **does not** make a new model selector, training service, FinalUse issuer,
Neuron Worker, WAL/CAS writer, production run route or independent observer.
No `main` merge or actual pretrained result is asserted here.

## Why this evidence matters

The original P0 Evidence-versus-Question-only paired experiments had per-Head
SHA digests and sealed prediction probabilities, but did **not** archive the
actual learned FP32 Head tensors together with every frozen Q24 Encoder feature.
Without those tensors a second process cannot independently recompute the
reported model probability. A digest alone does not demonstrate a genuine
model-forward lineage. This increment closes that **numerical self-consistency**
loophole, not the independent upstream model-signature or dataset-validity gaps.

## Added physical evidence

For each actual Granite97M, mmBERT-small, and EmbeddingGemma2 CPU run:

1. Keep the **original fully vetted model/tokenizer revision**, unchanged
   40-step Torch-SGD schedule, same-seeded independent Evidence/Question-only
   Heads and initial frozen baselines. The costly frozen Encoder still loads
   once. Four original Head parameter tensors are snapshotted immediately
   from the real Torch modules into safe `safetensors` (no pickle or raw code).
2. Export every **original train/calibration/held case** feature in its
   frozen Q24-derived FP32 form, with **original input IDs and order**. No
   original held labels, raw public text, source credentials or foundation model
   weight files are in the replay archive.
3. Write the feature and Head files first, fsync both, then create a content-
   and source-bound `COMMITTED.json` last. A partial archive has no success
   disposition. Every original Head tensor SHA is checked against the
   original trained/frozen prediction report before any commit is published.
4. A **separate source-only reviewer process** (NumPy + safetensors; it does
   not use Torch, execute the Encoder, download foundation weights or read
   validation labels) verifies complete case census, source/model/head identities,
   archive bytes/geometry, frozen/learned tensor lineage, and independently
   recalculates **every original and question-only held prediction**. The
   floating tolerance of `3e-5` reflects FP32 BLAS order, not arbitrary
   score slack. Changed logits, tensor bytes, probability rows, case IDs,
   training/eval bundle, unexpected Head tensors, nonfinite tensors and
   false-signature/FinalUse claims fail closed.
5. The original **human-label** and **full-cost** reviewer jobs now depend on
   this replay job succeeding. The replay job deliberately never downloads
   the held human-answer receipt. Failure artifacts remain visible. The Laya
   421M original `noul` policy is deliberately **not** renamed as a trainable
   equal-budget Head or falsely replayed with linear-layer math.

## Exact reproduction of source-only research checks

```sh
PYTHONPATH=experiments/shared_stem_cell python -m unittest discover \
  -s experiments/shared_stem_cell -p 'test_p0_physical_replay_v5.py' -v
PYTHONPATH=experiments/shared_stem_cell python -O -m unittest discover \
  -s experiments/shared_stem_cell -p 'test_p0_physical_replay_v5.py' -v
```

The real workflow `hepta-p0-multirc-semantic-four.yml` adds the fifth job
`independent-pretrained-replay`, reusing existing source/material/model jobs.
It stages only original small JSON prediction reports and small `.replay`
archives under `physical-public/`; **never** publishes downloaded 421M, Gemma,
mmBERT or Granite model-weight snapshots. An incomplete model remains
incomplete, and three passing linear Heads do not establish a four-model win.

## What a passing V5 result would and would not mean

It **would mean** the particular materialized Head matrices and frozen
features numerically reproduce all of the received held model probabilities.
It would not independently re-execute the real foundation Encoder nor certify
its checkpoint provenance, prove the actual 40 optimizer steps occurred on
original human training labels, authenticate physical clocks, establish
semantic entailment, benchmark generalization, prospective longitudinal NDU,
4,096-Cell continuous learning, multimodal generation, external CPU/GPU
computer use, target-host energy, p99, or production rights.

A successful local synthetic regression is only mechanism evidence. Real
weights, exact-HEAD hosted CI, independent artifact/label assessment, source
holdouts, resource-accurate alternative baselines and original
`blocking-ci`/Architecture/FinalUse/CAS/WAL gates remain mandatory. Any missing
model, skipped CI, weak/no hard relation contrast or signed-source gap leaves
**model selection refused**. No external effect is permitted.
