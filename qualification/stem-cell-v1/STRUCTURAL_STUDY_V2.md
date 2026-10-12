# Shared Stem structural study: executable fitting, selection and sealed scoring

Parent: Draft PR #1645, exact source `a9bd346198a2dddb5e67ed1bfcf42c1402dcff3b`.
This continuation leaves that branch unchanged so its pending CI is not cancelled.
It uses the existing `SharedStemEngine`, strict `FrozenLocalHfBackend`,
`model_runner.train_head`, `BasisCellHeads` and `split_candidate`. It does not
merge the separate FBSDE research tree or create another runtime/store/owner.

## What this increments

The first development slice provided operators and mechanism tests. This study
actually fits and compares a shared trained parent, continued learning, a wider
Head, extra training data, and an inherited two-Cell split. It freezes a
calibration-only structural decision, writes candidate safetensors, closes the
prediction file, and scores those original predictions in a separate command.
The ordinary real-weight entrypoint has no fixture, random-Encoder, model-fetch,
custom-code or pickle fallback. All results remain non-authorizing research.

### Dataset and information boundary

Use JSONL with exactly these fields:

`sample_id`, `source_group`, `episode_id`, `scope`, `language`, `split`,
`training_phase`, `observed_at`, `state`, `question`, `options`, `label`.

Existing `study.load_jsonl/validate_dataset` remain authoritative parser and
basic grouping primitives. Additional checks reject phase-level source/episode
leakage, repeated normalized source text even under a changed question/ID,
reordered action meanings, mixed scopes, missing classes and non-timezoned dates.
There are at most 4096 rows / 16 MiB of input. Canonical state/question/ordered
options, never labels or source-group IDs, enter the frozen Encoder.

Training rows use `split=train` and `training_phase=base|adapt|extra`. All other
rows have `training_phase=null`. Base, adaptation, extra-data, calibration and
held-out windows are mandatory and strictly ordered. Future windows are optional
and never fabricated. OOD has no invented ordering. Supported language labels
retain the existing `zh|en|cross` contract. Caller-supplied observation times and
origin strings do not authenticate prospective outcomes or permissions.

The normalizer learns from base training only. The router uses adaptation
features and training residuals only. Fitting receives base/adaptation/extra
labels, and selection receives calibration labels. Held-out/future/OOD labels
are absent from the fitting entrypoint. A negative test permutes all of them and
requires unchanged checkpoint bytes, structural selection and prediction bytes.

### Actual arms, costs and split decision

| Arm | Computation |
| --- | --- |
| frozen | One parent trained on the base window, then unchanged. This is NOT the existing production no-change model. |
| continued | Update only the parent's private coefficient/gate parameters on adaptation data. |
| wider | Double the frozen basis rank; inherit original directions and insert initially inactive directions. Report the additional shared storage. |
| more_data | Same unsplit parent and optimizer-step ceiling, using adaptation plus independent extra-data rows. |
| split | Inherit two identical private Heads and a bounded, training-only two-means router. Fit both candidates within ONE total optimizer-step budget. |

A rank-r split trains `4r+2` private scalars; the wider Head trains `4r+1`.
They are intentionally reported as near-matched, NOT falsely exactly equal.
The wider basis, router centers, frozen parameters, normalizer, data acquisition,
shared base fitting and preparation are not free. Actual CPU/wall and sample
presentations are recorded. Equal steps/minibatch ceilings are NOT equal actual
compute, especially for smaller training folds. Shared physical preparation is
counted once in the complete study, not allocated to fictitious standalone arms.

Split eligibility uses group-equal accuracy differences against EACH of four
unsplit controls. For n independent groups and bounded differences in [-1,1],
the one-sided Hoeffding radius is `sqrt(2*log(4/alpha)/n)`. A registered optional
stored-scalar penalty is subtracted. Every lower bound must exceed zero and the
minimum group floor must hold. Group independence is an explicit assumption,
not proved by source strings. This calibration gate is not an independent
scientific efficacy finding or a promotion grant. A nonpositive or unsupported
split leaves the best calibrated unsplit control in place. Identical-feature
router collapse is explicitly unavailable, not relabelled a successful split.

### Physical Encoder path

The CLI requires an immutable local safetensors Encoder snapshot and dataset
SHA256, exact clean source SHA, and an explicit research scope/frontier binding.
It verifies every loaded tensor using the existing backend, measures a
same-resident-Encoder serial/no-cache versus batch/reuse comparison, then encodes
the study inputs through the existing cache. It rejects feature widths above 512
instead of silently truncating; wider models still require their own approved
projection integration. The benchmark is a randomized-order component probe,
not a duplicated-421M memory comparison or statistically qualified p99 test.

It rechecks physical tensors and snapshot bytes before and after Head fitting,
and checks dataset bytes before a successful run record. Failures retain partial
files and a FAILED record; a failed run cannot be scored as successful. These
checks are not OS isolation, anti-rollback attestation, or crash-safe owner CAS.
Whole-process Linux high-water RSS is not a per-arm incremental peak. Model,
training, router preparation and complete experiment costs remain distinguishable.

The pinned published mmBERT-small revision `abc32620dd4f6ab06f5fbe905dc25f310618e09f`
contains `pytorch_model.bin`, while this backend deliberately requires
safetensors and exact base-tensor inventory. An independently reviewed conversion
or another approved compatible snapshot is therefore still required. This PR
DOES NOT weaken the loader or introduce a new pickle conversion path.

## Run on an approved, provisioned host

Install the repository's compatible pinned Transformers environment together
with CPU Torch 2.10.0 and safetensors 0.7.0. The model and data are provisioned
separately; this script never downloads them.

```sh
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=qualification/stem-cell-v1
python qualification/stem-cell-v1/development_study.py \
  --source-root "$PWD" --expected-source-sha "$(git rev-parse HEAD)" \
  --dataset "$APPROVED_DATASET" --dataset-sha256 "$APPROVED_DATASET_SHA256" \
  --snapshot "$APPROVED_ENCODER" --snapshot-sha256 "$APPROVED_ENCODER_SHA256" \
  --config qualification/stem-cell-v1/structural_study_config.jsonl \
  --revocation-frontier-sha256 "$RESEARCH_FRONTIER_SHA256" \
  --output /outside/source/new-structural-study
python qualification/stem-cell-v1/development_study_review.py \
  --run /outside/source/new-structural-study --dataset "$APPROVED_DATASET" \
  --output /outside/source/new-structural-review.json
```

The frontier here is a content-bound research descriptor, not a signed live
production frontier. The scorer verifies the sealed file hashes, complete paired
census, input fingerprints and finite logits, then reports group-equal accuracy
and Brier scores. It never retrains, changes the selected arm, inserts truth into
predictions or invents independent signatures. Runtime selection, topology,
checkpoint CAS/WAL, revocation and final-use remain with the existing owners.

## Observed local evidence, not model qualification

58 local tests passed without failures/skips: the prior 31, three repository
factory/fitter composition tests, and 24 new study tests. The local environment
is a PARTIAL checkout; `model_runner` and `study` use connector-fetched source
function extracts for unavailable full modules. The hosted workflow must test
actual complete repository modules on its own exact head/merge SHA. The local
extracts are not committed over repository source.

A separate 512-row synthetic exercise actually fit all five arms and wrote five
safetensors checkpoints plus 1280 predictions. All arms tied on its held-out
fixture, so calibration retained `frozen` and refused unnecessary splitting.
This is an intentionally easy mechanism check, NOT pretrained model quality,
future learning, general retention, 4096-Cell target-host performance, multimodal
generation or 10T/100T equivalence. Local model download failed, Transformers and
approved weight/data snapshots were absent, and `just fmt` could not run because
`just` was absent. No native Rust source or dependency lock is changed.
