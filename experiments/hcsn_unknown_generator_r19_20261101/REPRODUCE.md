# R19 finite content-law study

Run from the repository root with Python 3.12, NumPy and SciPy. The recorded runtime uses Python 3.12.14, NumPy 2.3.5 and SciPy 1.17.0. CPU affinity is an execution placement choice; BLAS uses one thread.

The current archive audits do not retrain or open another holdout:

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 taskset -c 0-6 python -m experiments.hcsn_unknown_generator_r19_20261101.audit_reference
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 taskset -c 0-6 python -m experiments.hcsn_unknown_generator_r19_20261101.audit_statistics
```

The scalar reference independently enumerates every legal assignment from the missing raw-event alphabet in its bounded cases. It compares posterior marginals, acquired-token successors and paid READ decisions, then checks every retained calibration/confirmation owner target, acquisition receipt and fee. The statistical audit reconstructs all calibration counts, simultaneous CP bounds, frozen threshold selection, panel-specific bootstrap bounds and gates directly from the raw archives.

For a deterministic full replay, use an isolated checkout of the published R19 source. Move the existing `prepare_01`, `confirm_01`, `POSTCALIBRATION_FREEZE.json` and process receipts to an external archive first, leaving all old bytes intact. Keep the exact source publication receipt. Run:

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 taskset -c 0-6 python -m experiments.hcsn_unknown_generator_r19_20261101.campaign prepare
```

Compare the new models, OOD controls, calibration, archive index and postcalibration-freeze bytes to the published originals. Only after equality is verified may the original matching `CALIBRATION_PUBLICATION.json` authorize this deterministic replay:

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 taskset -c 0-6 python -m experiments.hcsn_unknown_generator_r19_20261101.campaign confirm
```

The fixed seeds reproduce the existing confirmation worlds. This is a replay, not new independent confirmation. New scientific confirmation requires a prospectively declared new namespace and independently frozen protocol; do not pool deterministic repetitions as new samples.

`ENGINEERING_PREPARE_V1` preserves the first successful preparation using locally reconstructed dependencies with one extra trailing newline. Its source/preparation checkpoints are `f50c16c54d1813c078a566f5bce6667b1e42ca30` and `9af439b265a7bac2e6887f3d5e8211f690a525ae`. Before any confirmation, those dependencies were restored to their exact original Git blob identities, a corrective source freeze was published at `7ea3a2ef04a8f8d3a8e9805304e9c0707780e0fd`, and preparation was repeated. Original preparation CPU is charged once; duplicate bytes in the repair record are not another execution or another sample. Archive paths inside the historical first preparation retain their original historical-root interpretation.

The study is an ordinary finite probability reference with supplied symbolic addresses and two to four missing events. It does not qualify arbitrary unknown laws, semantic or real audiovisual binding, a restricted streaming network, analytic-core D−B, GPU/energy economics or production activation.
