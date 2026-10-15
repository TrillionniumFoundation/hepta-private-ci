# E3 five-arm: eliminate withheld TEST labels and target hashes from model-facing jobs

**2026-10-15 — research-only / Draft / SHADOW_ONLY / DENY_ALL.**
This is a P0 scientific-integrity repair, not new language or multimodal efficacy.

## Exact original obstruction

The research child of #2227/#2258 originally put `HELD_SHA` in the
*workflow-global* `env`, giving both physical OCR+Granite and native
EmbeddingGemma 2 inference jobs the digest of the original 64 TEST answers.
Both producer jobs called the default `e3_scienceqa_stage.py` path, which
materialized original `private_labels/test_labels.jsonl` and its hash in
`source-seals.json` **before** pretrained forward passes. This breaks the
intended producer/independent-judge separation, even if no model code
explicitly opened the target file. The fact that the TEST digest was present
does not show it actually influenced historical predictions, but it prevents
claiming that the prospective five-arm producer was label-blind.

## Isolation repair

1. `e3_source_target_partition.py` guards `answer(split,index)` behind
   the original split check. On `include_test_labels=False`, no TEST callback
   happens, and no fake TEST target values are emitted.
2. `e3_scienceqa_stage.py --predictor-source-only` preserves the full original
   image/question/source cohort and the original TRAIN/CAL labels, but does
   **not read, hash, or write** TEST label values. `private_labels` is not
   created and `source-seals.json.private_test_labels_sha256` is JSON null.
   The original default stage used by a label-owning independent evaluator
   remains byte-compatible with prior source / fit / target digests.
3. Both physical model jobs explicitly require the label-blind source mode,
   assert the target hash is absent and the test-label file is missing before
   loading pretrained material, and do not receive a `HELD_SHA` environment
   variable. The protected TEST digest is provided **only** to
   `independent-five-arm-review` after the full 5-arm prediction seal.
4. The separate lightweight and physical workflow contract jobs now run
   the original 28 five-arm controls *and* isolated TRAIN/TEST visibility
   regressions in normal Python and `python -O`. Original source cohort,
   model revisions, 80 update count, 769-param head, OCR policy and all
   original security/CI requirements remain unchanged.

## Remaining limitations / fail closed

The original Parquet source acquisition process can obtain the published
answer column; this change prevents TEST values and TEST digests from being
materialized into the **successor model-facing** process inputs. It does not
create an independent ground-truth owner, prove noninterference of every
possible information channel, or provide human-adjudicated image necessity.

The older original model outcome remains historical observational evidence.
Any future real OCR/native five-arm performance claim requires an entirely
new exact-SHA physical run with this source version, authentic full source and
model receipts, complete row-level label-blind sealed predictions, and
independent after-seal scoring. A completed unit test or queued Action is not
such evidence. Natural future1/2/3, cost matched 421M comparisons, 4096
native Cells/target-host reliability, NDU and FinalUse remain blocked.

**No selected Stem, main merge, model change, privilege, FinalUse or production
promotion is authorized by this branch.**
