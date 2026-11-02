# Frozen execution

Run from the repository root with Python 3.12.14, NumPy 2.3.5 and SciPy 1.17.0.
The complete required mpmath runtime source is included in the bounded ZIP;
`dependency.py` checks its archive and every member before import. The four
project imports and all original R20 evidence are bound in `INPUT_IDENTITIES`.
The source/protocol manifest must first be published and read back remotely.
`PUBLICATION.json` must contain `readback_verified: true`, the checkpoint SHA,
and the matching `source_freeze_sha256`. Fresh output directories are mandatory.

```bash
export PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
taskset -c 1 python -B -m tools.hcsn.continuous_task_v2_r22_20261102.measure --receipt tools/hcsn/continuous_task_v2_r22_20261102/ENGINEERING_PROCESS.json -- python -B -m tools.hcsn.continuous_task_v2_r22_20261102.study --phase engineering --output tools/hcsn/continuous_task_v2_r22_20261102/engineering_run
taskset -c 1 python -B -m tools.hcsn.continuous_task_v2_r22_20261102.measure --receipt tools/hcsn/continuous_task_v2_r22_20261102/CONFIRM_PROCESS.json -- python -B -m tools.hcsn.continuous_task_v2_r22_20261102.study --phase confirm --output tools/hcsn/continuous_task_v2_r22_20261102/confirm_run
taskset -c 1 python -B -m tools.hcsn.continuous_task_v2_r22_20261102.measure --receipt tools/hcsn/continuous_task_v2_r22_20261102/ENGINEERING_CHECK_PROCESS.json -- python -B -m tools.hcsn.continuous_task_v2_r22_20261102.record_check --run tools/hcsn/continuous_task_v2_r22_20261102/engineering_run --out tools/hcsn/continuous_task_v2_r22_20261102/ENGINEERING_REPLAY.json
taskset -c 1 python -B -m tools.hcsn.continuous_task_v2_r22_20261102.measure --receipt tools/hcsn/continuous_task_v2_r22_20261102/CONFIRM_CHECK_PROCESS.json -- python -B -m tools.hcsn.continuous_task_v2_r22_20261102.record_check --run tools/hcsn/continuous_task_v2_r22_20261102/confirm_run --out tools/hcsn/continuous_task_v2_r22_20261102/CONFIRM_REPLAY.json
```

The standard-library checker imports no candidate or numerical dependency.
It independently checks every saved left/right directional scalar against the
analytic reference, the whole old error decomposition, the exact binary oracle,
roster completeness and hashes. It replays arithmetic, not interval execution;
the independently coded interval residual certificate and primal complex replay
are executed during the scientific run. Control summaries are not independently
reexecuted by the record checker. Failures remain in the saved attempt roster.

Outer process CPU includes imports, input validation, computation and archive
serialization; scientific inner CPU is nested and must not be added to it.
Wrapper CPU is separately recorded before receipt serialization. Simultaneous
family peak RSS, GPU and energy are unmeasured. Development directories preserve
prefreeze probes and their executed source snapshots. In particular, V1's
`development03/PROBE_LIMITATION.json` records a shallow-copy bug in that probe;
it does not grant scientific acceptance. No development probe draws fresh
profiles from the registered confirmation seed.

V1's complete78-case diagnosis and standalone replay are retained under the
original `continuous_task_r22_20261102`. V2 does not repeat that whole roster.
Its three selected old cases are labeled engineering, followed by the unchanged
unopened fresh roster. V1's initial-left corruption finding is preserved in
its `development05`; V2 adds independent adversarial controls and both bounds
to the executable admission gate. No old failed finite-step test is relabeled.
