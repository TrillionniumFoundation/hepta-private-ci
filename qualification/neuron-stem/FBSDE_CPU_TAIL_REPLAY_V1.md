# CPU-tail diagnosis without replacing the budget or retrying a policy

Continues #1550 from edc5ecf1924955c493fe73dba25a87b25ee060ea. The 100,000,000 ns
PROCESS CPU admission, all scientific policies, dataset splits, Head parameters,
objectives and native owners are unchanged. This is not another acceptance gate.

## Contemporaneous evidence, not attribution by stage name alone

The existing observe_view cpu_clock port now supports an explicit diagnostic
clock. It samples process CPU, caller-thread CPU, wall time, process context
switches/minor faults and Python GC collections at the SAME five phase endpoints.
Sequential clock snapshots are not simultaneous; signed process-minus-thread
values are retained, including tiny negative differences. The policy still uses
PROCESS CPU for admission. Worker CPU must not disappear by changing clocks.

`--clock-diagnostics` is opt-in at the same study entrypoint. It creates a separate
hash-chained journal bound one-to-one to the original attempt hash, source,
phase, view and status. Both returned and denied calls get these measurements.
The final original outcome audit is unchanged; an independent clock audit checks
endpoint arithmetic and the sidecar binding. A journal error aborts, not grants.
Diagnostic overhead is inside request/run envelopes; most endpoint sampling is
also inside the next measured phase. Post-endpoint bookkeeping is not silently
claimed part of the view CPU interval. These instrumented timings are not a
zero-overhead estimator of uninstrumented latency. GC or switch association is
not proof of causation, and process-minus-thread CPU does not identify a worker.

## Fixed-work replay in fresh interpreters

The new explicit `cpu_tail_replay_v1` profile consumes original acquisition
artifacts. It selects the FIRST recorded failure, otherwise the first attempted
view, without reading outcome labels. It verifies source text hashes, serialized
Head bytes, actual tensor identity and normalization. The original acquisition
Head construction is shared by fitting and replay; no second prediction formula.

Every predeclared configuration gets a NEW Python interpreter:

- historical_2: the original intra-op count 2, ambient inter-op settings;
- bounded_1: one intra-op and one inter-op thread;
- bounded_2: two intra-op and one inter-op thread;
- passive_2: bounded_2 with OMP_WAIT_POLICY=PASSIVE before import.

Thread settings are applied before eager/autograd work. A configuration's import,
load and process lifetime are separately measured, not declared free. Settings
are not assumed portable performance improvements. Profiles execute in a fixed
order; this is not a randomized comparative performance benchmark.

Each child runs the fixed number of diagnostic attempts, including its first
call. Over-budget attempts remain rejected, are counted in all-work quantiles,
and are NEVER returned to a decision policy. Continuing a DIAGNOSTIC schedule
is not resuming a rejected scientific request. Unexpected errors/timeouts fail
the protocol and retain partial evidence. There is no retry-to-green loop.
Real mmBERT replay must use its original pinned weights; absent dependencies or
weights cause a recorded child failure, not a lexical or random substitute.

The existing CI uses live clocks for acquisition and a failure-only replay step.
A successful diagnostic does NOT turn a preceding failed acquisition step green.
All earlier workflow jobs and checks remain. Four children, each bounded to
240 wall seconds, replace no production retry, evaluator or native owner.

## Actual local evidence and limitations

Two archived lexical overrun inputs were replayed on their actual frozen trained
Heads under all four configurations. Probabilities and vector hashes agree on
all common returned attempts. The historical 114/142 ms spikes were NOT
reproduced; this is not proof of a fix. Per-profile output and every exploratory
run remain in the delivery archive. Local mmBERT dependencies were unavailable;
no new local pretrained forward is claimed.

A complete original banking lexical task with live clocks also executed:
6,842 requested views, no rejected view, maximum process CPU 13.562 ms in that
batch. Its decoded decisions reproduce the prior negative scientific result:
NDU/myopic score .84983333 with 502 calls; direct full-symbol score .85166667 with
480 calls, both 227 correct of 240. This is historical-data reuse, not new efficacy
or risk evidence. Neither this successful batch nor repeated identical inputs
certifies source independence, budget reliability or deployment latency.

All 288 model-free regressions passed. Across three separate inherited Torch
invocations, 51 tests passed and one unchanged Encoder-fixture path hit its
original per-prediction 100 ms limit. A preceding combined invocation was stopped
by the tool's 60-second execution limit; its incomplete log is retained. No
scientific threshold was raised, and the overall Torch run is NOT all-green.
The new complete live run and source-bound replay are additional executions,
not reclassification of those failures. Exact-head hosted checks are required.

```sh
PYTHONPATH=qualification/neuron-stem python qualification/neuron-stem/fbsde_study.py \
  --profile semantic_acquisition_v1 --backend hashing_reference_v1 \
  --kernel-profile joint_backoff_cv_v2 --clock-diagnostics \
  --publisher-root /original/publisher --output /new/live-study
PYTHONPATH=qualification/neuron-stem python qualification/neuron-stem/fbsde_study.py \
  --profile cpu_tail_replay_v1 --evidence-dir /original/acquisition-study \
  --replay-count 256 --output /new/replay
```

Runtime reference semantics: Python time.process_time_ns is process-wide, whereas
thread_time_ns measures the calling thread (https://docs.python.org/3/library/time.html).
PyTorch set_num_threads must precede eager/JIT/autograd work
(https://docs.pytorch.org/docs/stable/generated/torch.set_num_threads.html).
These references define APIs, not evidence that a particular tail is fixed.
