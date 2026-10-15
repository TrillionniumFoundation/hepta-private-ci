# Nested exclusion audit of opportunity-model transfer

Parent: `e605e7aea52b1727cd2c49ef8d23510300c45552`, existing PR #2319.
Research / DENY_ALL. Original sources, selected artifacts and production owners
are unchanged. No new source is claimed by this experiment.

## Question

A leave-one-curve-out check is not record-held validation when the other curves
were trained using the held curve's evaluation records. This experiment adds an
outer record exclusion before forming ANY opportunity prior. It tests learning
curve forecasts and physical stop/continue decisions on those excluded records,
not just arithmetic agreement with the fitted model.

Use only the original64 TRAIN records to define four outer48-fit/16-evaluation
folds, with label-independent, domain-separated case-ID ordering. Each outer
fit pool is subdivided into three32-fit/16-validation inner folds. The prior's
three full0/8/32/128 curves have no outer-evaluation labels or examples in ANY
of their training/normalization/validation sets. Original32 CAL remains disjoint
from all64 TRAIN records and is consumed only after actual policy updates.
The old32 HOLDOUT set is excluded from this entire new study, including scoring.

The outer16 records are absent from that worker's labels. Its prior fitter uses
only outer48 FIT inputs, not even the outer16 features. A source coordinator
writes label-free workers and separate reviewer labels. The reviewer reopens
the immutable original archive and rechecks the full mapping. This is data-flow
separation, not signed or operating-system-isolated label custody. Other outer
workers contain different permitted training labels; there is no cross-worker
model/cache sharing. The outer folds overlap in training, and CAL is reused;
four statistically independent task/source families are NOT established.

All records were used in previous research. This is a retrospective nested
reanalysis, not an untouched-source, future-time or prospective generalization
experiment. The32-to48 learning-size extrapolation and conditional binomial/IID
model remain assumptions. New compatibility is not inferred from vector width;
no existing compiled policy's source binding is relaxed or replaced.

## Physical work and control

The size-qualified trainer executes true FP64 full-batch SGD on original frozen
384D mmBERT features. Architecture385x4, zero initialization, lr0.1, nonbias
L2=0.001, and train-only coordinate mean/RMS floor1e-6 are unchanged. The parent
hard64-row trainer is untouched. There is one newly fitted Head for each policy.
Policies: fixed0, fixed8, fixed32, finite belief-neutral and belief-NDU using the
original declared low-fee scenario. The inherited finite planner reads only
executed disjoint8/8/16 calibration counts; the inherited independent rational
planner rechecks each emitted decision. NDU is still a specified discrete
preference profile, not a trained neural preference model or general FBSDE.

For each outer fold the prior pays3x128=384 updates plus12 scoring calls. Every
policy pays its actual own training and calibration. A separate full128-update
target Head produces held-record probabilities at all4 checkpoints for forecast
evaluation; that diagnostic is deliberately AFTER policy execution and NEVER
fed to the controller. Its512 total updates are charged as diagnostic work,
not falsely counted as updates executed by an early-stopping policy. Prior is
physically fit once per outer fold, not multiplied by cold-start attribution to
multiple compared methods. Setup charges are shown separately, with no presumed
future reuse count or dollars conversion. Local CPU is self-observed and not an
online Encoder/Reader service benchmark.

Forecasts are written before any target training and scored after the run seal.
For each coordinate, report prior mean, realized correct/16, signed/absolute
error, binomial-mixture count log score and central95% MODEL predictive interval.
The interval is not a confidence guarantee;16 correlated curve coordinates do
not establish coverage on future tasks. Posterior expected accuracy at selected
checkpoints is also reported separately from recursive utility.

## Validation and reproducibility

The reviewer calls neither the new trainer nor the numerical planner. It uses
the original separately written scalar SGD implementation with the actual32/48
training divisor, and the independent exact Fraction recursion. It rechecks all
normalizers/weights/losses, source IDs, source-held labels, future-free forecasts,
calibration slices, gradient authorization/event order, fees, summaries and
negative transfer claims. Same author/separate implementation, not an independent
institution, signer or hardware witness. Unknown/new-source transfer remains
unqualified even when every arithmetic check passes.

From repository root, Python3.13 / NumPy2.3.5, one BLAS thread:

```sh
D=experiments/ndu_tree_fbsde_gates/merton/real_head/replication_news/opportunity/transfer
export NEWS_ARCHIVE=/path/to/original-11870475540.zip
python "$D/nested.py" prepare --archive "$NEWS_ARCHIVE" --output /tmp/nested-material
python -m unittest discover -s "$D" -p test_nested.py -v
# Run each fold with worker SHA from /tmp/nested-material/manifest.json:
python "$D/nested.py" run --worker /tmp/nested-material/fold-0/worker.npz \
  --worker-sha <original-fold-worker-sha256> --output /tmp/nested-runs/fold-0
# Repeat for folds1..3, then use the separate reviewer:
python "$D/audit_nested.py" --archive "$NEWS_ARCHIVE" --material /tmp/nested-material \
  --runs /tmp/nested-runs --output /tmp/nested-audit.json
```

Outputs are create-only. Interrupted runs have failure journals and no success
seal. Do not overwrite/reseal earlier study evidence after a source change.
Source/merge hosted CI must separately execute. No main merge, production
promotion, source-selection override, new Encoder/Reader or world-model claim.
