# R20 reproducibility

This research runner is Linux/POSIX-specific: campaign accounting uses `wait4` and the recorded Linux commands use `taskset`. It does not claim Windows execution or production compatibility.

Run from the repository root with Python 3.12, NumPy and SciPy. Recorded dependencies are Python3.12.14, NumPy2.3.5 and SciPy1.17.0. The source freeze binds the exact R18 helper bytes read back at baseline `ede941c81edaf246486c88725a8a921bf70279ec`; no reconstructed trailing-newline changes are applied.

Preparation and confirmation use separate immutable output directories. Original experiment outputs must be preserved. In a separate checkout, move existing `prepare_01`, `confirm_01`, postcalibration freeze and stage receipts to an external archive before a deterministic replay. Keep the source publication receipt and exact frozen source files.

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 taskset -c 0-6 python -m experiments.hcsn_unknown_generator_r20_20261101.campaign prepare
```

This fits from complete public training streams and performs all declared OOD/risk calibration. `prepare_01/MODELS.json.gz` contains all three compiled laws; `MODELS_ARCHIVE.json` binds both compressed bytes and uncompressed JSON. Fitted diagnostics, public training data, all risk candidates and every raw calibration query remain in the archive.

The original R20 calibration failed all three models' stratified gates. Its confirmation namespace was deliberately left unopened. Do not run `campaign confirm` as a reproduction of an existing result: that original confirmation has no published execution result. Preserve `confirm_01` as absent.

The separate V2 power study uses the same fitted models/OOD, fixed `.95`, seed20021873 and18newbounds. Its successful source revision is `62a621d83112212cb89f76474f5ea5f7a55fa9c6`; the first zero-world disk failure and its old source/publication are preserved in `launch_failure_v1`. The calibration command is:

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 taskset -c 0-6 python -m experiments.hcsn_unknown_generator_r20_20261101.calibrate_v2
```

Use an isolated checkout and archive existing V2 output directories/receipts first. A calibration rerun creates fresh measured CPU/RSS receipts; those resource bytes, and hence their enclosing postcalibration freeze, need not equal the historical receipt. Raw worlds/counts/fitted identities should reproduce under the recorded runtime. Never pretend the old publication receipt binds a newly changed resource ledger.

For a deterministic V2 formal replay, retain the exact published calibration/freeze/auxiliary files and matching `CALIBRATION_V2_PUBLICATION.json`, and move only existing `confirm_v2_01` plus its outer receipt to an external archive. Then:

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 taskset -c 0-6 python -m experiments.hcsn_unknown_generator_r20_20261101.confirm_v2
```

Its separate seed20031873 replays86,016worlds withfivepolicies andgenerator-clusterbootstrap batchesof64. Raw/statistical arrays should reproduce; new CPU/RSS receipts describe the rerun. Fixed seeds are deterministic replay, not additional independent evidence. New confirmation requires a prospectively frozen new namespace/protocol and must not pool these replays or R19 development worlds as new independent samples.

The original model/calibration and V2 audit scripts operate on retained arrays and raw records. The original `audit_statistics.py` and `independent_replay_check.py` were prepared for a confirmation phase that was not opened, so they are not completed original-R20 evidence. The relevant executed/checkable paths are:

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 taskset -c 0-6 python -m experiments.hcsn_unknown_generator_r20_20261101.audit_reference
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 taskset -c 0-6 python -m experiments.hcsn_unknown_generator_r20_20261101.independent_calibration_check
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 taskset -c 0-6 python -m experiments.hcsn_unknown_generator_r20_20261101.independent_v2_calibration_check
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 taskset -c 0-6 python -m experiments.hcsn_unknown_generator_r20_20261101.independent_v2_confirmation_check
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 taskset -c 0-6 python -m experiments.hcsn_unknown_generator_r20_20261101.adoption_coverage
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 taskset -c 0-6 python -m experiments.hcsn_unknown_generator_r20_20261101.independent_v2_adoption_check
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 taskset -c 0-6 python -m experiments.hcsn_unknown_generator_r20_20261101.ambiguity
```

Save `adoption_coverage` stdout as `ADOPTION_COVERAGE_EVALUATION.json` before running the exact-rational independent adoption checker. It adds a separately frozen3.125%coverage subgate without changing any registered research gate. The V2 confirmation checker streams all five policies and independently recomputes registered bootstrap draws by resample-multiplicity contractions; it does not call the candidate sampler or summarizer.

The independent source reviewer also supplies `independent_model_check.py`; it rederives all fitted probability/context-weight/key-law parameters from public training streams and all compiled-law coordinates without importing the candidate implementation. Historical audit receipts describe their exact execution stage and scope; do not call a prepare-only audit a confirmation replay.

Use the final delivered checkout for the complete audit imports. The preformal checkpoint31f0646 omitted `independent_v2_calibration_check.py`, which the frozen confirmation checker imports as its owner-record helper. Its unchanged SHA was recorded in the executed preformal calibration audit, but it was delivered remotely only after formal execution began. `AUDIT_DEPENDENCY_BINDING_ADDENDUM.json` records this delivery gap and resolution; it does not claim a preformal remote binding or modify scientific inputs, POSTV2, policies or outcomes.

The outer campaign receipts meter full child interpreters, imports, fitting, all candidates/attempts, inference, raw output and summaries with `wait4`. They describe the complete scoped campaign, not per-model online CPU or full project lifecycle costs. Independent/development audit internal CPU times exclude interpreter/import startup. Device energy, GPU and production adoption remain outside this experiment.

The initial zero-world V2 disk failure lacks an exact measured CPU/wall receipt, so cumulative known costs remain lower bounds. The revised process guard covers normal execution and caught launch/IO failures with known-worker reaping and stdout receipt custody; it does not claim arbitrary coordinator SIGKILL, orphan or power-loss cost recovery. Worker CPU is already included in each successful outer family receipt and must not be added again.
