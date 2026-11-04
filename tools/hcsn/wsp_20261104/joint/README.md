# Hepta Neuron frozen continuation-head study, 2026-11-04

This is a reproducible **negative/inconclusive efficacy result** using five real, previously published Hepta Neuron checkpoints. The repository `TrillionniumFoundation/hepta-private-ci` is public despite its name. Every model/data-derived fixture here comes from its already-published, pinned joint-model archive. No newly private HeptaTrader model, market data or live training artifact is included.

The original protocol, source files and pretrained weights are identified by SHA256. The experiment changes 147 continuation-head coefficients while freezing the representation and belief row. An analytic proximal least-squares edit, gradient updates on the same head, norm-matched random candidates, no edit and three single-action ablations are evaluated on common data. This is not a full-model retraining comparison or an implementation of generic language-model circuit understanding.

## Observed result

| Selected arm | IID mean utility | IID change | OOD mean utility | OOD change |
| --- | ---: | ---: | ---: | ---: |
| No edit | .21309701 | — | .11797339 | — |
| Analytic edit | .22727900 | +.01418199 | .14490749 | +.02693410 |
| Gradient head | .22891382 | +.01581681 | .14436131 | +.02638792 |
| Random edit | .23049919 | +.01740218 | .12482056 | +.00684717 |

Five-fit paired descriptive 95% intervals for the analytic change are IID `[-.01849575,.04685973]`, OOD `[-.02344963,.07731782]`. Neither establishes a positive general effect. Random editing has the highest IID sample mean. All methods' five selected validation gains exceed the common `.005` acceptance threshold, so a common acceptance/revert gate would preserve every observed selected result. The frozen experiment implements explicit reversion for the direct arm; it does not claim that rejected GD/random candidates were restored on disk.

GD shares the regularization value selected by the analytic search. Its six step budgets are selected separately, but this is not independent hyperparameter optimization, equal total compute or full-model retraining. Historical ~59-second full-model fits are contextual cost records, not a controlled speedup baseline.

The TRAIN feasibility diagnostic later tests expressivity, without adding efficacy candidates or using holdout data. Three fits have immutable wrong terminal-action rankings with frozen belief, making perfect oracle action matching impossible for continuation edits of any magnitude. Fit71 is infeasible even in a componentwise box containing the original L2 trust ball; a numerical Farkas witness is recorded. Fit11 is feasible in the relaxed box, which does not establish feasibility in the smaller L2 ball. No feasibility solution is deployed or evaluated as a new candidate.

Read [REPORT_ZH.md](REPORT_ZH.md) for architecture semantics, limitations and the mathematical details. [records/ACCEPTANCE_AUDIT.json](records/ACCEPTANCE_AUDIT.json) explicitly leaves the scientific effectiveness and training-superiority gates false.

## Reproduce

Use Python 3.11+ with NumPy and SciPy. The recorded macOS experiment used Python 3.9.6 and NumPy 2.0.2; independent Linux linear-algebra/LP checks used Python 3.12.14, NumPy 2.3.5, SciPy 1.17.0. BLAS implementations can differ. Numeric acceptance tolerances are stated explicitly; new timings are not expected to match.

```sh
python -m pip install -r requirements.txt
python verify_delivery.py
python verify_truth_tables.py
```

Recover the input archive from the exact public commit. Existing checkout objects avoid downloading the large repository. Without `--repository`, the script downloads the ten exact public raw-GitHub parts. An already downloaded archive may instead be supplied with `--archive`.

```sh
python acquire_inputs.py --repository /absolute/path/to/hepta-private-ci --output /absolute/path/to/new-inputs
python strict_replay.py /absolute/path/to/new-inputs /absolute/path/to/new-strict-results
python verify_delivery.py --results /absolute/path/to/new-strict-results/results.json
```

Each destination must be new. Acquisition validates the binary Git blob identity of every fetched part, the 14,316,376-byte archive, and all 3,550 regular member hashes before writing the selected five renewal checkpoints and five original train/validation datasets. Neither live checkpoints nor remote services are written. The independent finite-law evaluator uses already TRAIN-fitted observation confusion; it does not open or decode new FullHX packets.

The strict replay executes every matrix product through an explicit reduction reference. BLAS output is compared as a diagnostic only. Overflow, invalid and divide exceptions are raised for the execution path and linear solver. The original and checked scripts remain available, unchanged, for provenance.

Reproduce the TRAIN geometry and feasibility diagnostics:

```sh
python export_train_geometry.py /absolute/path/to/new-inputs /absolute/path/to/new-train-geometry.npz
python train_policy_feasibility.py /absolute/path/to/new-train-geometry.npz /absolute/path/to/new-feasibility.json
```

Or reproduce the LP directly from the publicly derived packaged geometry:

```sh
python train_policy_feasibility.py fixtures/train_linear_geometry.npz /absolute/path/to/new-feasibility.json
```

The frozen efficacy protocol is written before its run but was not externally preregistered. Strict replays are numerical repeats, not additional independent fits. The LP is a separately disclosed, later diagnostic on original TRAIN states only; it does not retroactively change the efficacy protocol.

## Artifact map

- `SOURCE_MANIFEST.json`, `INPUT_ACQUISITION.json`, `PARTS.json`, `MODEL_FREEZE.json`, `archive_index.json.gz`: exact public-source provenance and recovery contracts.
- `run_head_edit.py`, `checked_replay.py`, `strict_replay.py`: fixed scientific experiment and numerical verification paths.
- `joint_*.py`, `joint_protocol.json`, `legacy_task.py`: exact vendored upstream dependency bytes, linked in `SOURCE_MANIFEST.json`.
- `truth_transitions.npz`, `verify_truth_tables.py`: finite-space CTMC truth matrices and independent SciPy regeneration check.
- `records/results_*.json.gz`, `records/strict_*.json`, `records/matmul_audit.json`: complete aggregate results, strict-repeat comparison and numeric evidence.
- `fixtures/rust_fixture.json`: actual fit11 linear system, base weights and independently recomputed expected solution for Rust validation.
- `fixtures/train_linear_geometry.npz`, `train_policy_feasibility.py`, `records/train_policy_feasibility.json`: actual original TRAIN features and finite policy feasibility evidence.
- `DELIVERY_MANIFEST.json`: every delivered file's byte count and SHA256; checked by `verify_delivery.py`.

The reusable implementation is the constrained fixed-feature quadratic problem and its verified data path. This package does not claim successful repair of state representation, First-Passage/Reset, belief calibration, financial Call/Put semantics, general NDU optimality, HeptaTrader returns, or full-model training efficiency.
