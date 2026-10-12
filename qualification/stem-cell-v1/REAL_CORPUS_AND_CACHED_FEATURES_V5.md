# Real corpus repair and new learning on historical pretrained features

Continuation of PR #1654 at `dbd2e7b9281af3d33948ce6592b54b047448e340`.
No new production runtime, store, model loader, authority or selected model.
The eight-intent BGE execution and four-intent cached-feature study remain
separate jobs. Historical Encoder work is never counted as current execution.

## Actual corpus failure, not another synthetic fixture

Downloaded GitHub Actions artifact **11757461425**, from run **38267578878**,
source `66258d5871cd022c0fa13995dd6ba787b4d2359e`. The specific job
`real-encoder (independent_targets_v2)` / **114873519269** succeeded; the overall
workflow failed in other jobs. This does not qualify the whole workflow.
The ZIP is 1,797,397 bytes, SHA256
`2d4cced3f2f40c9d1759b68e0b6b6886454a71a4c6c98a1d70fafc02c4237505`.

Its original CLINC file is 2,495,390 bytes and reproduces the registered Git blob
`7a7b26c5f2dfbbf213f3e67d2dd0727e1af545aa`. The original eight-intent preparation
FAILS on these authentic bytes: `clinc:train:7424` and `clinc:val:1011` both say
`what is on my to do list`, but their unchanged labels are `todo_list` and
`reminder`. They previously fell in base training and calibration respectively.
There are 1,200 selected rows, 1,199 normalized exact-content groups, and this
one cross-phase, contradictory-label group. Relaxing the leakage validator or
silently removing a row is not an acceptable repair.

`publisher_strict_v1` remains the default and STILL rejects this corpus.
The explicit **protected_content_groups_v2** policy moves a complete normalized
content group only forward in base/adapt/extra/calibration/held-out order. It
uses content and original assignments, not labels, logits or observed accuracy.
All original rows, IDs, texts, option meanings and labels remain. The original
publisher partition/index is retained separately from the derived execution
phase. Conflicting labels are reported, not majority-voted or corrected.

For this corpus, exactly the earlier training occurrence moves to calibration:
base **319**, adapt **240**, extra **240**, calibration **161**, held-out **240**.
No row is dropped. Both contradictory observations stay in one calibration
group, weighted once by the existing group-equal selector. This does not claim
that either label is uniquely true. It is an explicitly DERIVED diagnostic,
not an unchanged official CLINC split, prospective data or all-CLINC benchmark.
The public CI selects this named policy. Staging now validates task data before
querying model metadata/downloading weights, retaining its original failure files.

## New Cell fitting on genuine, already-computed Encoder features

`historical_feature_study.py` accepts only the exact fixed artifact ZIP. Before
restricted `torch.load(weights_only=True)` it checks the full archive hash and
fixed feature hash. It executes no archived source and permits no custom globals.
This .pt input contains features, NOT model weights; the ordinary inference
loader stays unchanged, offline and safetensors-only.

The loader validates original source/model/revision, raw publisher and license
bytes, every utterance's original row/text/label, the 328-row/384-wide tensor
inventory, all eleven original forward-event vector digests, and the original
normalization relationship. Training uses ONLY `raw_vectors`: the old 128-row
normalizer is checked for consistency and then discarded for new fitting.

This archived task contains four intentions: alarm/calendar/weather/time. From
each intent's 32 archived training utterances, content-hash ordering assigns
16/8/8 to base/adapt/extra. All 80 archived original-validation and 120 original-
test utterances are preserved as calibration and held-out. Total: **328 rows**.
A new normalizer is fitted only on the new 64-row base. The old Encoder saw
utterance text only, not the new task's constant question/options. The feature
profile states this explicitly; it is NOT canonical joint-input BGE inference.

The existing five-arm fitter, 200 base steps, 200 total adaptation steps per arm,
rank 8 and seed 7347 are retained. Candidates and their calibration selection
are sealed before separate held-out scoring. A distinct cached-feature run
schema explicitly records **zero Encoder calls in this execution** and retains
the historical preparation cost separately. Replay rejects attempts to label
that record as fresh pretrained inference. No serving/energy result is imputed.

## First observed result, without hindsight selection

The actual cached-feature run trained all five candidates, sealed **600** held-out
predictions and replayed them with **0.0** maximum logit error / **0** argmax
reversals. Calibration chose **wider**, and did NOT support a split. All five
held-out arms got **118/120**, or 98.3333% accuracy. Frozen/continued/wider/
more_data/split Brier values were approximately 0.020897/0.022171/0.022787/
0.022275/0.021510. The selected wider arm was not replaced after seeing test
Brier. No statistically demonstrated gain, split advantage or optimal Stem is
claimed. Content groups are not authenticated independent speakers.

These are new CPU Head-learning results on historical real pretrained vectors,
not new local Encoder execution. Local imports still use the previously declared
partial-checkout function extracts for model_runner/study; they are not committed
as repository replacements. The hosted job requires complete source imports.

## Reproduce

```sh
PYTHONPATH=qualification/stem-cell-v1 python3 qualification/stem-cell-v1/historical_feature_study.py \
  --archive /approved/artifact-11757461425.zip --source-root "$PWD" \
  --expected-source-sha "$(git rev-parse HEAD)" --output /new/cached-study
```

Then use the existing independent
`development_study_replay.py` and `development_study_review.py`, with
`--run /new/cached-study --dataset /new/cached-study/dataset.jsonl` and distinct
create-only `--output` files. The cached job also checks the real eight-intent
corpus and preserves both its strict rejection and explicitly derived manifest.

The existing workflow downloads the one fixed historical ZIP with a read-only
Actions token, then validates its hash locally. Missing/expired archives fail;
there is no substitute artifact. The fresh BGE job remains separate and mandatory
for a new BGE execution claim. Native Worker/CAS/WAL/final-use, actual future NDU,
64–4096 independent-Cell scaling, recurrence and multimodal generation acceptance
remain separate, unfinished requirements. No production or merge gate is waived.
