# R14: task-aligned finite-state Hepta neuron experiment

This experiment extends the exact R13 source at
`b0802dc314251f5332bd026cb2984a0b5c75f768` (PR #4542).
It preserves the original financial kernel and production Rust source.
`PROTOCOL.json` is the controlling preregistration; `REPORT_ZH.md` reports the
eventual executed results and the scientific conclusions they support.

The new task is external sensor repair over the original joint phase/content
process. Sensor maintenance and the cell's natural absorption/recovery have
different semantics. Every baseline can execute the same paid maintenance.
The learning objective includes exact actual frozen-policy Q-pi targets and
fixed cost-sensitive action weights. A matched CPU CE-only branch isolates
objective choice from additional training. These are finite synthetic tasks,
not semantic-memory, original financial-optimality or production claims.

## Reproduce the local scientific checks

Use Python 3.12 with NumPy, SciPy and threadpoolctl. The source manifest records
the exact installed versions used in the evidence. Limit BLAS to one thread:

```sh
OPENBLAS_NUM_THREADS=1 python -m unittest \
  tools.hcsn.task_aligned_r14_20261101.test_identifiability \
  tools.hcsn.task_aligned_r14_20261101.test_task \
  tools.hcsn.task_aligned_r14_20261101.test_models \
  tools.hcsn.task_aligned_r14_20261101.test_qpi \
  tools.hcsn.task_aligned_r14_20261101.test_propagation_audit \
  tools.hcsn.task_aligned_r14_20261101.test_summarize
```

## Training and confirmation order

1. Register the complete source closure with `campaign register --output RUN`.
2. Publish that source and protocol. Train each of the eight protocol seeds with
   `campaign train --output RUN --seed SEED --source-commit PUBLISHED_SOURCE_SHA`.
3. Run `campaign freeze --output RUN --source-commit PUBLISHED_SOURCE_SHA`.
   Publish `FREEZE.json` and all training artifacts before opening confirmation.
4. For each registered fit/domain run
   `campaign confirm --output RUN --seed SEED --domain iid|ood --freeze-commit PUBLISHED_FREEZE_SHA`.
5. Run `summarize --run RUN` only after all sixteen confirmation runs complete.

All module commands above use the prefix
`python -m tools.hcsn.task_aligned_r14_20261101.`. Supply real source/freeze
commit SHAs obtained from GitHub; the program checks hashes and SHA format but
does not independently authenticate remote publication. Source and training
artifacts are checked again after every confirmation run. Existing starts and
confirmation results are never silently overwritten.

## Retained evidence

Per-fit ZIP archives preserve every raw JSON/NPZ byte, including selected and
final weights, matched CE weights, optimizer traces, common data and exact
policy targets. The archive indexes list every member's SHA-256 and size.
`evidence_pack restore --index INDEX --destination RUN` safely restores and
verifies them. Copy the separately retained source/freeze manifests to RUN.
Fresh reruns require a new output directory; the published confirmation cohort
is immutable. CPU budgets can produce different optimizer update counts on
different hosts, so the executed checkpoints and raw records are authoritative.

Online estimator/controller CPU, simulated complete execution CPU, and shared
preparation/candidate-selection costs are reported separately. A generic HMM
with D's final matrices is mandatory: identical filtering/actions prevent
attributing its behavior to an HX-exclusive inference mechanism.
