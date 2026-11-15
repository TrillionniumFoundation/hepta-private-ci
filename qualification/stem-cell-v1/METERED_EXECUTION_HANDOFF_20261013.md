# Metered execution increment: actual source and acceptance boundary

Parent: `2ab183ac6a03452393a81f4f78182ed5dac83326` (PR #1705).
Tested Python code: `a2ee85f7a4b52636cad67594ded483cb06e1bfb7`.
Delivery branch: `research/shared-stem-metered-execution-20261013`.
Research/qualification only; no main merge, selected-model change or deployment.

## What is implemented and executed

`aten_work.py` gives exact-overload, versioned CPU FP32 eager formulas.
`execution_meter.py` attaches them to the operations actually dispatched during
Encoder materialization, bank initialization, optimization, warmup and request
execution. It also records per-scope elapsed/CPU time, attempted unknown operators
and aborted reservations. It does not profile a different replay and pretend that
replay describes the original run. Unknown overloads are not implicitly zero.

Observe mode runs unsupported operations but leaves the complete phase count
null. Strict mode rejects an unsupported operation or an unaffordable known
formula BEFORE dispatch. A stop is sticky; later model calls cannot proceed.
Failed kernels have unknown executed fractions, so their reservation is retained
separately and not relabeled as completed arithmetic. CPU FP32 is explicit;
compiled/custom kernels, other precision and GPU work need separate profiles.

The unit is a scalar-equivalent formula FLOP, not retired CPU/GPU instructions,
energy or bandwidth. Multiply-add counts two; nonlinear primitives have declared
costs. Comparison, sort, copies, indexing, integer PRNG work and allocation are
tracked operators with zero *floating arithmetic* under this convention, not
zero runtime cost. Python scalar arithmetic and independent observer evaluation
are outside the ATen counter. This distinction follows the same need for an
explicit formula/coverage profile described by PyTorch's FLOP-counter docs.
A supported fixture graph is not universal formula coverage for an HF model.

`host_counters.py` reads Linux process-lifetime RSS high-water marks and optional
read-only RAPL zone counters. The reader never sums parent and child zones,
resets a counter, or calls package energy process energy. Counter identity changes,
missing inputs and ambiguous wraps remain unavailable. The wrap check depends on
an externally declared upper power bound, whose truth this reader does not verify.
No RAPL counter is exposed in this session; all actual energy observations are null.

## Integration and budgets

`freeze_config(..., measurement_policy=...)` creates bound-config V2. Omitting
that argument retains V1 semantics. A V2 execution rejects a missing meter or a
meter with a different policy/phase cap. New source files participate in existing
exact-commit source checks. Configuration hashes are linkage, not independent
approval or authentication.

Policy fields are `schema=hepta.execution-meter-policy.v1`, mode `observe` or
`strict`, positive `wall_time_ns`, optional positive `max_process_rss_bytes`,
optional sysfs `rapl_zone` and optional `rapl_max_power_watts`. Freeze these with
the normal config before the run; do not relax them after observing results.
Strict mode is a useful coverage/budget gate, not a claim that every pretrained
model's operators already have reviewed formulas.

Time/RSS limits are cooperative checks at callback/ATen/publication boundaries.
They do NOT interrupt an in-flight native kernel, prevent an allocation's transient
overshoot, or substitute for OS resource containment. Full end-to-end FLOP caps
remain unverified because observer evaluation and other declared gaps remain.
Supported measured train/inference counts are exported, but incomplete full-scope
coverage, process energy and per-request memory still block the existing audit.

The feature cache now preallocates one retained matrix and copies rows into it,
rather than retaining all vectors plus a second stacked matrix. The cap is a
retained-feature payload cap, not total process/activation memory. Tests check
that metering preserves trained tensor digests and predictions.

Budget failure retains the expected task inventory and a FAILED record with work
observations. Inference stops retain all task IDs and do not run subsequent model
calls. Publication checks the budget before writing the final marker and after
sync; a late failure is fenced by FAILED and no seal is returned. This is the
existing single-writer local publication boundary, not native multi-writer CAS.
The main observation ends before final publication; publication is budget-checked
but its work is not quietly counted as measured model work.

## Verification actually completed

The predecessor's 66 tests were rerun before modification and passed. The complete
updated suite passed twice: 95 tests, zero failures/errors/skips (18 new counter/
formula tests and 11 new integration tests). Python compileall, diff whitespace
and workflow YAML parsing passed. The eight remote Python blob IDs were checked
against the exact local tested bytes. New tests include hand-derived four-bank
forward counts, in-place refusal before mutation, failure reservations, sticky
stops, whole-denominator retention, policy binding, sealed observer export and
preservation of missing metrics.

Four additional sequential fixture runs exercised real PyTorch training with a
synthetic four-dimensional Encoder and tiny 672/1344-parameter banks. They are
NOT executions of a pretrained 421M model despite the plan arm names. The summary
retains that fact. Inference counts include one warmup and two evaluation requests.
Timings include metering overhead and first-run lazy optimizer initialization;
all runs share one process and its cumulative RSS high water mark. They are not
matched performance trials and establish no latency speedup or capability gain.

`METERED_EXECUTION_TEST_RECEIPT_20261013.json` and
`METERED_FIXTURE_SUMMARY_20261013.json` are retained in the repository. The full
raw test log and four-run diagnostic are in the downloadable source package,
with their hashes in the receipt. No fabricated real-weight/energy outcomes exist.

```sh
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 python -m unittest discover \
  -s qualification/stem-cell-v1 -p 'test_*.py' -v
python -m compileall -q qualification/stem-cell-v1
git diff --check
```

The existing workflow now watches the whole stem directory and its own file,
retains the original preregistration job, and adds pinned CPU execution regressions
with exact checkout SHA, package inventory and raw log artifacts. YAML was checked
locally; hosted dependency installation and CI success have not been observed.
No full repository, Rust, native-host or prospective-merge qualification is claimed.

## Remaining next acceptance

The session still has no Transformers installation, approved real model/workload,
target cloud host or RAPL device. No pretrained model experiment, independent
future-task gain, multimodal generation or native 1024/4096-Cell test was run.
Next integrate actual approved HF operator coverage, independent-observer cost
and suitable target-host memory/energy attribution. Run matched quality/retention
comparisons before any efficiency conclusion. Split/NDU/System2 remain explicitly
unsupported by this five-profile bound runner until their real owner execution
and costs are integrated; earlier prototypes are preserved, not relabeled.
