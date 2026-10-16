# E3 source-only predictor / independent TEST owner — 2026-10-16

**Status: DRAFT, SHADOW_ONLY, DENY_ALL.** Stacked on the exact
research #2227 source commit
`1fc1c87b8490cae2eb48b7fd464827f57278750e`. This
child is not a production model, does not change any rustc/Cargo runtime,
NDU, CAS, Worker, CNS, FinalUse, Cell Split or main.

## Why this qualifies as a new experimental safety gate

The original #2227 physical workflow used default
`e3_scienceqa_stage.py`, writing the historical ScienceQA TEST label
file into the model job filesystem and setting the exact held TEST
target digest globally. A model producer did **not** receive those labels
as API arguments, so we do **not** claim proven exploitation or actual
trained-on-TEST weights. But a source-directory / job environment
target leak invalidates the strong phrase "TEST targets absent from
physical predictor".

The older, independently developed [#2304](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2304)
had a proper source-only mode on exactly the same original 192-sample
ScienceQA cohort. This child brings the **reviewed exact source files**
to the newest #2227 environment rather than dropping #2227's original
real OCR producer, Gemma2 8,192-token model-context binding, honest
1,120-token image reserve, 769-parameter same-head negative control,
37+ original five-arm regressions and independent original OCR auditor.

## Source-first isolation protocol

- Predictor staging: `e3_scienceqa_stage.py --predictor-source-only`.
  The full 192-sample original source (96 TRAIN, 32 CAL, 64 TEST)
  and 128 TRAIN/CAL labels are exactly preserved. **No TEST answer
  callback, TEST label file, TEST label materialization or target-content
  digest** may be produced by the model-facing staging function.
- Source SHA:
  `a561916c7d56b6677c5511c329a49bbeec94879f019d29f159ff59be83359202`.
  FIT SHA:
  `e8506bc65f96501b6b2fa4e4ae04c094c2b6b17b353de528a051136569e2849e`.
  Both must match the original #2173 physically executed ScienceQA
  cohort. Predictor source seal's TEST label SHA must be `null`.
- Both physically separate OCR+Granite and native Gemma2 jobs run a
  source acquisition subprocess with explicit isolated
  `HF_HOME`/`HF_DATASETS_CACHE`, then delete that original raw
  Parquet/Arrow cache before executing any pretrained model producer.
  The source-only material directory is checked for
  `private_labels/test_labels.jsonl` absence.
- Independent OCR historical scorer and independent complete five-arm
  reviewer are **different jobs**. They re-open, byte-verify and seal
  already emitted original model predictions, then independently
  re-stage original public historical TEST answers. Their
  `HELD_SHA` environment variable exists only in these independent
  scoring jobs, never in source-contract, OCR or native model job env.
  The OCR scoring module no longer hardcodes the target SHA: it only
  receives `--held-sha256` from its independent evaluator owner.
- All four expensive model/reviewer jobs are **push-only**, while
  read-only source/contracts run on both same-repo PR and push.
  Concurrency is scoped to workflow, event kind and branch, so a PR
  source-only event does not cancel a legitimate in-flight push
  pretrained job. Skipped PR physical jobs are **not** evidence of
  pretrained execution. Production CI remains independent and cannot
  be waived by a research PASS.

## Scientific and runtime limitations

This is **process-/source-artifact isolation, not cryptographic
third-party label ownership**. The public Parquet source preparation
process has temporary access to original public release data, but
it is a separate process that exits and whose local raw acquisition
cache is removed before any model producer executes. Published
historical label SHA pins may be knowable through earlier research
artifacts; only absence of model-job env, output files and API
arguments is enforced. A truly independent prospective future
evaluation still needs authenticated external source and label owners.

The original Google source and version remain fixed:
`google/embeddinggemma-2@914f7f89142e33e77833254d9c9b90c3cef7303b`.
The preceding original Gemma2 run **did not produce held predictions**:
it failed at safe runtime token-context validation. This child retains
the newer 8,192-context fix, but must itself physically run and prove
complete 1,344 text/image/choice token preflights, same original 96
TRAIN/64 TEST matched 769-parameter Heads, and its own original
physical model result. Do not reuse the original non-blind job as a
prospective/label-independent five-arm scientific baseline.

Inherited source-only partition tests are run both with ordinary
`python3` and `python3 -O`, plus original five-arm/Token/capacity/
OCR independent-contract tests. There is no ability to grant NDU
model selection or FinalUse, even if the pure source tests pass.
