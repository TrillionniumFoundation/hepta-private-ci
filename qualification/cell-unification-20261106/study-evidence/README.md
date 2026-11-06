# Executed Cell differentiation reference study

## Observed outcome

The frozen #4890 Python reference now has actual execution evidence. Both its
normal and optimized (`python -O`) 24-case suites passed, and the unmodified
full study completed all 10 preregistered trials, all 60 arms and all 11,520
test predictions. There were no failed arms. **Both scenarios remain HOLD.**

This result closes the missing Python execution evidence in the stated scope.
It does not close native Rust qualification, cross-language policy parity,
seven semantic neural roles, model-backend adoption, production lifecycle or
positive product net benefit.

## Source and reproduction

- Frozen source: `caf06e0d9c78ba2b8e2ab860ec1b37f049e30f1b` (#4890).
- All six executable Python modules and the original test file were fetched
  at that commit and independently checked with Git blob SHA-1. The initial
  download added one trailing newline; this was removed before any execution,
  and the resulting bytes match the original blobs. `source-binding.json`
  preserves the acquisition correction and final source SHA-256 values.
- This was a sparse source export, not a complete local Git checkout. The
  Python/source identity is verified; a whole-repository build is not claimed.
- Runtime: Python 3.12.14, NumPy 2.3.5, Linux x86_64, CPU FP64.
- Seeds, splits, 128 training steps, six comparators and policy thresholds
  remained unchanged. There was one full study execution, without retuning.

From the repository root:

```bash
python3 -m unittest discover -s qualification/cell-differentiation -p 'test_*.py' -v
python3 -O -m unittest discover -s qualification/cell-differentiation -p 'test_*.py' -v
python3 qualification/cell-differentiation/run_study.py \
  --source-commit caf06e0d9c78ba2b8e2ab860ec1b37f049e30f1b \
  --output /tmp/cell-study.json
python3 qualification/cell-unification-20261106/replay_study.py \
  qualification/cell-unification-20261106/study-evidence/study.json.gz \
  /tmp/cell-study-replay.json
```

`study.json.gz` preserves the complete canonical JSON, including model
parameters, every prediction, demand observation, migration replay and cost
event. `summary.json` records the compressed/uncompressed sizes and hashes.
The raw source digest is
`19a6a6261d6d832243f394d73f2cbc80f1d063f127da71e3c08bf636c0a485a9`.
The uncompressed report SHA-256 is
`26c32dfb400ed591b9ee7fe2a0e47713291f0c7e8e9d2dd3ec2293f242b399bd`.

## Six-arm result

Values are descriptive means across the five fixed seeds. Lower MSE is better.
Each scenario/arm has 960 requested and completed test predictions.

| Arm | Conflicting-task test MSE | Redundant-task test MSE | Estimated FP operations per arm, including common pretraining |
| --- | ---: | ---: | ---: |
| Unchanged parent | 6.044695446 | 0.002540785 | 829,312 |
| Continued parent | 3.305500808 | 0.002565705 | 1,652,352 |
| Expanded monolith | 0.022421920 | 0.002601138 | 2,185,600 |
| Fixed experts | 0.002614898 | 0.002615538 | 1,656,192 |
| Random grouping | 3.311785582 | 0.002620424 | 1,656,192 |
| Demand specialization | 0.002552108 | 0.002540785 | 1,251,346 conflicting; 837,906 redundant |

The registered protocol fixes 128 optimizer steps per fitted model and caps
candidate FP operations at three times the continued-parent total. It does not
match total compute exactly across all six arms; their different measured-plan
operation counts remain visible. No equal-total-budget efficacy win is claimed.

In the conflicting-task scenario, persistent error and negative-transfer
diagnosis trigger a child in all five seeds. The candidate preserves the old
task's parent exactly and dramatically improves the incompatible new task.
It still fails the original requirement to beat **every comparator** by at
least 0.0005 MSE in every seed. Mean gain over fixed experts is only
0.00006279064223624; all five seeds fail that comparator gate.

In the redundant-task scenario, demand and negative transfer are absent. The
candidate retains the parent rather than growing the population. Its outputs
equal the unchanged parent and its diagnostic work adds cost. The frozen gate
correctly returns HOLD rather than treating extra mechanisms as progress.

## Independent readback and costs

The original study audits its serialized report. A separate replayer imports
none of its modules: it regenerates the NumPy RNG inputs, evaluates serialized
models with scalar `math.fsum`, recomputes losses, demand conditions, comparator
gains and decisions, and reconciles recorded cost totals. It checked **30,720
prediction records**, including validation, test, serialization replay and
diagnostic monitoring. Maximum absolute difference from the original vector
predictions was **1.4432899320127035e-15**.

The independent replay counted 655 captured cost events once, including common
work once per trial: **49,090,740 estimated FP operations** and **37,120 routing
decisions**. Per-arm totals above deliberately include common pretraining for
each comparison; summing those columns would duplicate that shared work.

The external full-study command exited 0 in 3.085912248 seconds; child CPU was
3.862871 user seconds plus 0.220195 system seconds. The execution receipt's
71,492 KiB maximum RSS is the cumulative child high-water mark of the sequential
test/study wrapper, not an isolated model memory measurement. Raw stage wall
times, process receipts and test logs are preserved separately.

The independent checker shares NumPy's RNG implementation, does not retrain
the models, and does not attest the costs with independent hardware counters.
The operation estimates, routing counts and measured time have different units.
There is no physical-energy, GPU, network or production-throughput result.
Parameter serialization is an in-process readback exercise, not cross-host
state migration or a live owner handoff. These limits and the HOLD results are
retained without changing the original protocol.
