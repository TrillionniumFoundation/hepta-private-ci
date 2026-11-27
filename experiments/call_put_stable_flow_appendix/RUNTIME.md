# CPU full-sequence inference-cost appendix

This is a separately registered appendix. It adds `runtime.py` and
`RUNTIME_SPEC.json` without modifying the previously registered checkpoint
precision implementation or its two-file source binding.

The immutable registration is at
`research_evidence/hepta_stable_flow_20261029/inference_cost_appendix001/`.
It was made **during formal training, before validation/test scoring and before
any timing execution**. It does not claim to be a pretraining registration.

Protocol SHA-256:

```text
b605b13d59a34701f1aaf8dfb2987c490fc72b12d003539dec3d84ce26505f5c
```

Registration seal SHA-256:

```text
11e4e8337980b687e780e0cd8776bc8f18864e178771a4a23a692dc3ed85e50d
```

## Fixed measurement matrix

The measurement matrix contains seed 81301, all five arms, both tasks, and both
`cpu30`/`updates384` selected endpoints: 20 aliases. Physically repeated weights
can share one computation for a fixed task and arm, but all aliases remain in
the output.

Each physical checkpoint is measured at batch sizes 1 and 32, using the first
32 registered **training** episodes. Batch 1 always uses episode 0. Every call
starts a fresh production forward over all 32 ticks, including production
initial-state and sequence-coefficient preparation. Models and input tensors
are loaded before timing. This API does not expose persistent streaming state,
so these measurements describe whole-sequence calls, not token decoding.

The CPU uses one Torch intra-op thread and one inter-op thread, with `eval` and
`torch.no_grad`. Every case receives three warmups and eleven timed calls.
Case order is shuffled with fixed registered seeds in each complete round.
No case or repetition is omitted according to task quality or measured speed.

Each timed call records process CPU and wall nanoseconds. After the timer stops,
its output is checked for finiteness and the same deterministic byte digest as
the warmed result. All raw samples are retained, with summary distributions and
amortized sequence/token throughput. Repeated timings are not independent
training seeds.

Before actual timing, all 60 training candidates and the full registered
checkpoint precision appendix must finish. Numerical failure/unresolved flags
are retained; outstanding execution errors prevent timing. Root then schedules
the run while its training and diagnostic workloads are idle. The command-line
flag records that scheduling condition; it does not claim control of unrelated
host processes.

## State payload and quality

The unmodified `model.accounting()` output is saved. Its scalar counts are
converted to bytes using actual dtypes: float32 recurrence variables, two int64
counters and one bool flag. With the registered configuration, that is 147
float scalars and 17 discrete bytes, or **605 counted state bytes per episode**.
This excludes inputs, outputs, temporary tensors, Python/allocator overhead and
weights; it is not a peak-memory measurement or an implemented KV-cache result.

All 20 aliases are timed regardless of later observed accuracy. A separate join
to immutable primary held-out scores identifies narrow descriptive comparisons:

- Both timed models have validation and test accuracy at least 0.90.
- Their observed test accuracy differs by no more than 0.005.
- Their observed test cross entropy differs by no more than 0.01.

This label is `empirical_quality_band_eligible`. It is not a statistical
equivalence test or evidence of equal population quality. Only qualifying
analytic-versus-comparator pairs receive a derived median CPU/wall cost ratio;
every individual timing and score remains visible even if a pair is ineligible.
No new endpoints or models are selected by this join.

The scope is one timed training seed, the measured CPU environment, and these
full-sequence calls. It yields no GPU, energy, streaming-token, SNN, Transformer,
multimodal or scaling result.

## Execution after training and numerical checks

The registration command has already run. No inference timing was performed
during registration or pure metadata/state-accounting validation.

When Root has scheduled an idle interval after all training and numerical
checks, run from the repository root:

```sh
python -m experiments.call_put_stable_flow_appendix.runtime run \
  --study research_evidence/hepta_stable_flow_20261029/formal_run001 \
  --numerics research_evidence/hepta_stable_flow_20261029/trained_numerics_appendix001 \
  --output research_evidence/hepta_stable_flow_20261029/inference_cost_appendix001 \
  --idle-cpu-attested
```

After the primary test scores exist, join them without changing timing data:

```sh
python -m experiments.call_put_stable_flow_appendix.runtime join-quality \
  --study research_evidence/hepta_stable_flow_20261029/formal_run001 \
  --numerics research_evidence/hepta_stable_flow_20261029/trained_numerics_appendix001 \
  --output research_evidence/hepta_stable_flow_20261029/inference_cost_appendix001
```

The runner verifies core/appendix source identities, input/checkpoint hashes,
training/selection seals and the completed numerical appendix before measuring.
Its `execution/` directory contains a declared case order, raw event log, raw
clock arrays, output hashes, accounting and summaries. The separate
`quality_join.json` binds those summaries to the primary score-file hash.
