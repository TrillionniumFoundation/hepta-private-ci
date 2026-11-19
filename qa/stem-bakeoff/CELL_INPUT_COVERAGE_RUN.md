# Run the fixed input coverage diagnostic

Read `CELL_INPUT_COVERAGE_PROTOCOL.md` first. The protocol and execution source
must be committed before source preparation, feature extraction or scoring.
The matched policies are experimental alternatives; neither is predeclared a
quality improvement. This is an isolated CPU study with `DENY_ALL` authority.

The executed snapshot lives under `/data/hepta-cell-input-20261024` on main.
Its isolated `.venv` uses CPU Torch 2.10.0, Transformers 5.1.0, NumPy 2.2.6,
PyArrow 21.0.0 and scikit-learn 1.7.2. The complete resolved environment is kept
with the run. Existing model caches and environments are read only.

From `qa/stem-bakeoff`, using that Python and single-threaded BLAS:

```sh
python prepare_input_coverage.py --raw DATA/raw --output DATA/cohorts-v1 \
  --protocol CELL_INPUT_COVERAGE_PROTOCOL.md
python coverage_feature_export.py --dataset DATA/cohorts-v1 --output DATA/features-v1
python fit_input_coverage.py --dataset DATA/cohorts-v1 --features DATA/features-v1 \
  --output DATA/fitted-v1
python score_input_coverage.py --dataset DATA/cohorts-v1 --features DATA/features-v1 \
  --fitted DATA/fitted-v1 --output DATA/score-v1
```

Use absolute paths in place of `DATA`. Feature extraction loads the one exact
cached LFM snapshot recorded in the protocol and verifies its local model code.
It compares actual native token, padding, and attention-length work. Both
policies use one shared representation matrix for all private Heads.

Preparation emits predictor/selection receipts and separate label files. The
fitter reads only training and calibration labels, persists all model states,
controls, calibrated settings and evaluation probabilities, and seals them.
The independent scoring process reloads every learned Head and requires exact
prediction equality before parsing evaluation labels. Source group bootstrap
keeps targets and training seeds paired. It is not a task-independent confidence
guarantee. All four fixed targets must be available for the primary contrast.

Do not replace a partial failed directory or a failed seal. Keep its execution
log and diagnose the implementation. Reuse of an already completed stage is
allowed only if its manifest and code identity still match. After scoring, this
historical evaluation cohort is exposed and cannot be a new acceptance set.

Keep raw sources, labels, tensors, fitted states, detailed token positions and
execution logs outside Git. Publish generating code, aggregate metrics, text-free
selection IDs, source/checkpoint digests, resource receipts, all failures, and
the interpretation. An archive of the raw run must bind exact repository
commit, protocol, input data and all logical artifacts before it is called
independently reproducible.
