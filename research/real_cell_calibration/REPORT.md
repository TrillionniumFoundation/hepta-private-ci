# Bounded Cell fusion pilot: aggregate results

No new independent natural-data validation has completed. Results below are
synthetic engineering checks and reanalysis of already-seen P39 development data.
The 50% coverage minimum is this pilot's pre-run frozen DEVELOPMENT criterion,
not an original-system requirement. No historical rule was altered.

Four checks passed: analytic gradients against finite differences, transitive
source/hash clustering, split isolation and frozen-input drift rejection, and
missing-input/zero-acceptance behavior. Two full prediction ledgers replayed
byte-for-byte locally. This publication patch intentionally omits those ledgers,
labels, media, feature banks, trained weights and third-party source text.

| Historical model | Macro-F1 | Positive recall | Coverage at confidence .8 |
|---|---:|---:|---:|
| Projected concat-linear | .5073 | .4766 | 0 |
| Gated, 65 parameters | .8588 | .9219 | .0117 |
| Rank-1, 65 parameters | .6070 | .5313 | .1875 |
| MLP, 65 parameters | .3333 | 1.0000 | 0 |
| Full-dimensional linear | .4843 | .4766 | 0 |
| Text-only | .4997 | .4766 | 0 |
| Image-only | .4980 | .4375 | 0 |
| Fixed-threshold cosine / cache-inspired | .3333 | 1.0000 | .3789 / .4102 |

Historical features are embeddinggemma, not CLIP; original image input includes
fixed neutral text. Balanced historical labels have no minority class, so its
minority recall is null; positive/per-class recalls are available locally.

The fixed .25 cosine threshold is unsuitable for this feature space: all-positive
predictions are a weak-baseline failure, not evidence of Head superiority. No
threshold was retuned. An unchanged historical strong cosine script, with two
train-fitted scalar parameters, replayed at 250/256 accuracy, 251/256 coverage
at confidence .70, and NLL .07438. Original Head accuracy was 251/256, with paired
difference interval [-.0078125,.015625], crossing zero. This historical .70 rule
is different from the new pilot's .80 confidence rule; neither was modified.

Gated macro-F1 fell from .8588 to .3333 under constant state and .4154 under
shuffled state. Rank-1 fell from .6070 to .4534 under text shuffle and .3333 under
missing text. These artificial diagnostics retain original labels. They establish
neither natural missingness behavior nor advantage over directly using cosine,
and say nothing about dynamic refinement. Gated coverage .0117 fails the new
pilot's .50 development minimum. Historical bootstrap statistics are descriptive.

Synthetic paired macro-F1: linear .4000, gated .4565, rank-1 .5705, MLP .5115,
cosine .9685, cache 1.0000. Learned Heads did not beat strong controls. Only 14
synthetic test blocks were available, below the frozen 50-block minimum.

First-run wall time / peak RSS: synthetic 6.514 s / 193568 KiB; historical
7.216 s / 161020 KiB. At most four CPU threads and one sequential model job.
Each learned model used 300 steps. Paired projected models have 65 parameters;
historical full-linear has 1537. Unimodal arrays allocate 65, with only 33 affecting
output. Runtime includes evaluation/bootstrap, not original Encoder execution.

Fresh WIT sample, image-license metadata and CLIP checkpoint acquisition were
blocked by HTTP 403. No retry or alternate source was used. Fresh per-image
rights evidence, original-image feature extraction and exact natural-data freeze
remain incomplete. Natural mode therefore fails closed. References and public
source/weight hashes are in PROTOCOL.md and SOURCES.json.

Reproduce the data-free engineering path from repository root:

```sh
python -m unittest discover -s research/real_cell_calibration -p 'test_*.py' -v
python research/real_cell_calibration/experiment.py fixture /tmp/cell-fixture-new
python research/real_cell_calibration/experiment.py freeze /tmp/cell-fixture-new --output /tmp/cell-run-new
python research/real_cell_calibration/experiment.py run /tmp/cell-fixture-new --output /tmp/cell-run-new
```

Requires Python 3, NumPy, SciPy and scikit-learn. Recorded versions were Python
3.12.14, NumPy 2.3.5, SciPy 1.17.0 and scikit-learn 1.8.0. Historical import needs
an independently verified original archive; no such data is in this patch.

## Post-run custody-only correction

The scores above were produced by the original experiment source SHA256
20676235ba36ba955500efb4613da80b18d94086fe44fb79d9784400318699d1.
An independent offline review reran that unchanged source: 11,340 synthetic plus
13,824 historical prediction records (25,164 model/condition records, not unique
examples), reproducing the reported aggregates and negative results.

Review found that the historical input checked the feature bank but did not pin
the derived manifest before freezing. A modified label and false archive identity
could therefore be accepted into a new freeze. The subsequent custody-only fix
pins the complete deterministic historical import manifest to SHA256
3fae2bd29e33c390424ee00638d341cd9c0f4146f540c8f132152c69ae7b2189.
This digest was derived using the unchanged importer only after rechecking the
externally pinned archive manifest and all 91 restored members. It covers labels,
endpoints, source groups, original splits and archive identity, not just features.

The corrected code passed the original four tests plus one new regression test
with label, split, block, source ID, source hash and archive-identity mutations.
The genuine verified historical import was accepted; a modified copy was rejected
before an output freeze was created. No model or threshold changed, and no model
was retrained with the corrected source. Original evidence and freezes were kept
unchanged; their code hashes still identify the original execution. These checks
are engineering custody verification, not a new natural validation or scientific
PASS.
