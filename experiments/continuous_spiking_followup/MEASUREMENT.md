# Batch, streaming and fresh-process replay measurements

Run measurements serially after training and other research work have ended.
The machine may still be shared; no exclusive-host claim follows from this
execution policy. The contract is CPU float32, one PyTorch thread.

```bash
python -m experiments.continuous_spiking_followup.stream_measure \
  --run PATH_TO_COMPLETED_BUDGET_RUN \
  --cache-dir PATH_TO_DATA_CACHE \
  --output NEW_MEASUREMENT_DIRECTORY \
  --batch-size 16 --repeats 7
```

Add `--cross-process` only for the protocol's preselected replay cases. The
Python API is `measure_run(run_directory, cache_dir, output, batch_size=16,
repeats=7, cross_process=False)`. Output is a fresh directory containing
`MEASUREMENT.json` and hashed numerical evidence. Existing outputs are never
silently replaced; exceptions leave `FAILED.json` and any completed evidence.

## Identity and shared inputs

The selected checkpoint is read from the completed training result and checked
against the selection record and candidate checkpoint hash. The exact tensors
and dtypes are checked after reload. The dataset is rebuilt from the saved
specification, and its full manifest, episode/source identities and labels are
compared with the training artifacts. The fixed batch is the first heldout
test episodes in their saved order. The result binds source seals, checkpoint,
data, input tensors and episode identities by hash. Development fixtures are
explicitly marked unsealed rather than silently treated as formal results.

## Timed scopes

Both modes receive the exact same checkpoint and inputs. Each mode has two
warmups and seven measured repetitions by default. The order alternates between
batch-first and stream-first to avoid always giving the same mode one position.
All raw CPU/wall samples and their chronological order are retained.

Batch timing covers the complete existing model forward to final logits,
including its auxiliary tensor creation. Streaming timing covers one pass over
all observations using real state/KV caches, including per-step input checks,
Python loop/view operations and auxiliary creation. Streaming latency does not
include reset and model hashing; those are recorded for every invocation.
An additional encompassing reset-plus-forward interval records that combined
scope. Batch state initialization remains inside the original model forward.

Construction, a standalone model-hash probe, checkpoint reload, data rebuilding,
warmup, state-size tracing, output verification and recovery are separately
recorded. State-size tracing does not run inside forward timers. Quantiles are
descriptive repeated measurements, not confidence intervals. Persistent state
bytes count tensor payloads; they are not peak allocation, RSS, energy or FLOPs.
Nested phase times must not be added again to their enclosing totals.

## Equivalence checks

A separate untimed pass compares every prefix, not just final predictions.
The fixed numerical tolerance is `rtol=3e-5, atol=3e-6`. All errors, tensor
entries outside tolerance and predicted-class changes are recorded. A passing
record requires every prefix within tolerance, zero prefix class changes and
agreement with the training run's saved final predictions within tolerance.
The numerical arrays remain available even when parity fails. Tolerances are
not changed after observing model performance.

The pre-seal trained T128 diagnostic exposed float32 running-sum drift in the
Transformer time encoding. Its failing receipt is retained. The corrected
stream uses float64 cumulative time and rounds once per step to the model
dtype; this change is covered by T128 regression fixtures and a repeat of the
same trained diagnostic. It does not assert arbitrary-device or unbounded-time
bitwise equality between batch and incremental arithmetic.

## Fresh-process recovery

The parent saves model-bound state halfway through a fixed batch. Only the
remaining observations and time increments are supplied to a new Python
interpreter; no expected logits or task labels enter the child's request.
The child strictly reloads the model, restores the numeric stream state, and
executes the remainder. The parent compares every remaining logit and the
complete final stream-state digest exactly. Distinct process IDs and command,
request, input, state and result hashes are retained.

Parent preparation/reference costs, child import/setup, model reload, state
restore, input read, continuation and serialization are recorded. The external
wall timer covers interpreter startup through shutdown. On platforms exposing
`RUSAGE_CHILDREN`, external child CPU is also retained; otherwise it is null,
not zero. Parent CPU excludes child CPU. This verifies model/stream recovery,
not optimizer continuation, task-owner recovery or an authenticity signature.
