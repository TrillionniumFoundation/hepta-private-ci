# Per-regime serving costs of the frozen predictors

## What this continuation establishes

The original cost study measured serving work on IID inputs, then used that
same cost in each regime's amortization formula. Those original numbers remain
intact. Their non-IID amortization rows are now explicitly described as a
shared-IID-cost pricing scenario.

This continuation measures the four regimes separately with an independent
NumPy backend. It reuses the exact frozen weights and observations and verifies
that protective actions are unchanged. It does not retrain any model, generate
new confirmation examples, replace the original PyTorch timing, or establish
a matched-hardware speedup over PyTorch.

## Protocol, identity and deployment inputs

`NUMPY_COST_20261031_PROTOCOL.json` was written before timing. It specifies
all 13 predictors (four trained families with three frozen seeds, plus the
ordinary exact filter), the four regimes, nine batch repeats and 64 scalar
queries per predictor and regime. Every repeat covers each predictor once in
each regime, with independently randomized regime and predictor order.
There are **3,796 timing observations**: 468 batch calls and 3,328 scalar calls.
Each batch has 2,048 queries. Repeated timing calls are not counted as new
efficacy observations.

The benchmark preloads checkpoint weights as NumPy arrays. Its deployment
function accepts only history, lengths and query. Teacher probabilities,
posteriors and latent labels are absent from the deployment argument list.
The timed work includes float32 rounding of input arrays followed by NumPy
float64 execution, all observed features, the full predictor, protective
action selection and JSON output. Scalar input slicing is included.
Compressed fixture loading, model loading and verification/warmup are listed
separately. Native journals, durable recovery, training, energy and the rest
of the Hepta application are outside this serving fixture.

Before timing, 52 complete model/regime forward checks covered 106,496
predictor-example pairs over the same 8,192 unique confirmation examples.
The maximum prediction difference from the original PyTorch float32 records
was `1.23580826e-6`, below the unchanged `3e-6` tolerance. All protective actions
were identical. Source, checkpoint, amendment and evidence-manifest hashes
were verified. The reviewed replay also verifies 22 frozen inputs and 30
archived evidence files and records its own source identity.

The current executor used Python 3.12.14, NumPy 2.3.5 and SciPy 1.17.0 on
Linux x86-64, with OpenBLAS, OMP and MKL thread settings all one. Timing is
descriptive for this execution configuration. The measured campaign after
protocol creation used 7.242 process-CPU seconds and 7.242 wall seconds.
Serving calls account for 6.431946 CPU seconds, model and fixture loading
for 0.031288 seconds, and forward checks/warmup for 0.694080 seconds.
The remaining 0.084314 seconds include loop bookkeeping, raw audit-JSON
logging, aggregation and source checks; those activities were not timed
individually. Initial provenance validation and final report serialization
are outside the campaign timer.

## Results

Each entry is the arithmetic mean over the three checkpoint-specific medians;
the exact filter has one implementation. CPU times below include output JSON.
Every underlying CPU/wall observation is retained in
`evidence/NUMPY_COST_20261031_RAW.jsonl`; individual medians and wall-time
summaries remain in `evidence/NUMPY_COST_20261031.json`.

### Batch CPU microseconds per query

| Predictor | IID | Longer history | Low noise | Moving boundary |
| --- | ---: | ---: | ---: | ---: |
| Analytic filter | 2.229 | 2.347 | 2.470 | 2.313 |
| Sufficient-statistic MLP | 2.494 | 2.524 | 2.560 | 2.496 |
| GRU | 14.860 | 26.884 | 14.843 | 15.099 |
| Memoryless MLP | 2.399 | 2.538 | 2.476 | 2.543 |
| Ordinary exact filter | 2.346 | 2.348 | 2.480 | 2.288 |

### Scalar CPU microseconds per query

| Predictor | IID | Longer history | Low noise | Moving boundary |
| --- | ---: | ---: | ---: | ---: |
| Analytic filter | 72.269 | 75.737 | 72.820 | 72.075 |
| Sufficient-statistic MLP | 46.326 | 50.500 | 47.853 | 48.580 |
| GRU | 280.001 | 695.431 | 307.315 | 302.573 |
| Memoryless MLP | 45.948 | 49.617 | 45.472 | 46.104 |
| Ordinary exact filter | 70.740 | 79.373 | 71.426 | 74.942 |

The longer-history GRU scalar cost is 2.484 times its IID value. This is a
concrete instance where applying IID timing to another regime hides serving
work. The analytic and ordinary exact filters have similar costs, and their
measured ordering changes with regime and workload. Small timing differences
are not a universal dominance claim or a confidence-interval test. The cheaper
learned MLPs retain their originally measured quality errors; lower latency
alone does not make them equivalent-quality controls.

Both exact and calibrated analytic predictors use the same Brownian risk
operator. These results neither show that the risk operator is dispensable
nor establish that spikes are necessary. They preserve the narrower finding:
the known synthetic risk calculation has a nonspiking implementation using
the same public inputs.

### Separately measured model loading

| Predictor | Mean loading CPU milliseconds |
| --- | ---: |
| Analytic filter | 0.156436 |
| Sufficient-statistic MLP | 0.815204 |
| GRU | 1.699697 |
| Memoryless MLP | 0.805446 |
| Ordinary exact filter | 0.000691 |

These are single per-checkpoint reads/parses/array preparations after artifact
hash verification, so filesystem caches may be warm; they are not cold-start
latency distributions. The exact filter has no checkpoint to parse. Fixture
loading used 0.020857 CPU seconds in total, and the full forward checks/warmup
used 0.694080 seconds. The report retains each loading observation separately.

## Original setup and amortization audit

`RECOVERY_REPLAY_REVIEWED_20261031.json` reconciles the original fitting total
`31.871366577` seconds and the shared train/development teacher-generation
total `0.061428020` seconds. The original family setup summaries exceed their
corresponding mean fit plus shared-generation values by:

| Predictor | Inherited loading residual, seconds |
| --- | ---: |
| Analytic filter | 0.0008783267 |
| Sufficient-statistic MLP | 0.0011622297 |
| GRU | 0.0020712993 |
| Memoryless MLP | 0.0011553523 |
| Ordinary exact filter | 0.0000352820 |

These residuals agree with the scope of the old setup calculation, but the
original per-checkpoint loading records were not retained. Therefore the
residuals are explicitly inherited measurements, not independently timed
components. All 128 original amortization formulas were re-evaluated from
their documented inputs; the 32 involving the exact ordinary filter remain
statements about the original shared-IID-serving-cost scenario. This new
NumPy timing report does not silently substitute its costs into that historical
experiment or blend old-host training CPU with a new backend into an unlabelled
complete-cost result.

## Verification and reproduction

An independent readback recomputed all 104 checkpoint/regime/workload medians
and all 40 family summaries from the 3,796 raw timing rows. The maximum
family-summary difference was `2.17e-19` seconds, attributable to floating-point
addition order. The protocol, raw-file and source hashes match. See
`evidence/NUMPY_COST_READBACK_20261031.json` for the readback receipt and
campaign accounting. The new timing protocol, raw observations and main
timing report occupy 632,088 bytes in total.

Use new output names; exclusive creation protects previous records:

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 python3 -m tools.hcsn.round8_20261031.state_task.replay --output /tmp/state-reviewed-replay.json
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 python3 -m tools.hcsn.round8_20261031.state_task.cost_replay --reviewed-replay /tmp/state-reviewed-replay.json --output /tmp/state-numpy-cost.json
```

The original `RECOVERY_REPLAY_20261031.json`, all frozen checkpoints, raw
confirmation predictions and original PyTorch costs remain unchanged.
