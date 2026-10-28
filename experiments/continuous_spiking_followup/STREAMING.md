# Incremental inference contract

`StreamingClassifier` consumes one new observation per active row. It reuses
the frozen study001 model parameters and recurrence equations without changing
the historical package. Model weights must remain immutable while the stream is
active. Construction, reset and snapshot/restore bind the exact configuration
and state tensors through SHA-256. Per-step weight hashing is intentionally not
performed and must not be described as per-step authenticity verification.

```python
from experiments.continuous_spiking_followup.streaming import StreamingClassifier

stream = StreamingClassifier(model.eval()).reset(batch_size=16)
logits, auxiliary = stream.step(x_t, dt_t)
stream.select_batch(continuing_row_indices)
receipt = stream.save_state(new_state_directory)
resumed = StreamingClassifier(identical_model.eval()).load_state(new_state_directory)
```

`x_t` has shape `[active_batch,input_dim]` and `dt_t` has shape `[active_batch]`.
Both must be finite and match the model dtype/device; time increments must be
nonnegative. Elapsed time is accumulated per row in float64 and rounded to the
input dtype for the shared frontend and positional encoding. This avoids the
observed drift of repeated float32 additions relative to CPU `cumsum` on T128
histories. It does not assert arbitrary-length bitwise equivalence for all
devices or dtypes. Removing finished rows
preserves the other rows' causal state without replaying prior inputs.
An empty selection represents a fully stopped batch and cannot be advanced.

## Actual retained state

| Architecture | State per layer |
|---|---|
| HCSN dual/single/no-adaptation/ordinary | Content, pressure, adaptation, preceding event |
| Continuous RNN / two gates / CfC | Recurrent hidden vector |
| LIF | Membrane and previous binary spike |
| Mamba-1 | Last convolution inputs and selective SSM state |
| Transformer | Causal key/value cache |

Mamba uses one convolution window and one recurrence update per token.
Transformer attends the current query to its accumulated keys and values;
all cached positions are legal past/current positions. No adapter calls the
full-sequence model or retains a raw input prefix. Recurrent state payloads are
constant in history length; Transformer KV payload grows with consumed length.
This statement does not measure transient allocation, process RSS or energy.

## Outputs and accounting

`step` returns `(logits, auxiliary)`. For HCSN, auxiliary values expose the last
layer's `content`, `voltage`, `adaptation`, `margin`, `event_probability`,
`recovery`, `regeneration`, `drift`, `pre_reset_mean`, `boundary` and `diffusion`.
`margin` means natural boundary minus updated pressure. The event probability
has the old model's interval first-passage or ordinary-gate semantics. Neither
quantity is automatically a task continuation value, calibrated task risk or
owner authorization. Baselines expose their architecture and LIF event count.

`steps` counts incremental calls. `processed_rows` sums active batch sizes at
those calls, retaining work already spent on rows that later stopped.
`state_bytes` counts persistent state tensor payload bytes, including elapsed
time, and excludes weights, Python metadata and transient forward work.
Snapshot receipts separately report serialized bytes. Benchmarking must state
whether model hashing, reset, selection, serialization and policy costs are
inside the measured scope; the adapter does not hide or subtract their time.

## Recovery and verification

Snapshots use JSON metadata and numeric NPZ arrays with pickle disabled. The
payload and each array are hashed; the format binds model configuration and
every model state tensor. Restore validates all fields before replacing running
state. The 256 MiB state limit applies to decoded numeric payload, with a small
additional allowance for NPZ headers. SHA-256 provides integrity checking, not
a signature or authority grant. Task/owner state, optimizer and training RNG
must be handled by their own contracts.

The focused suite covers all ten model variants at depths one and two, every
prefix, zero/nonintegral time increments, active-row removal, exact same-order
cold replay, cache structure, mismatched models, corrupted state and invalid
inputs. Sequence-vs-incremental comparisons allow `rtol=3e-5, atol=3e-6` because
batch matrix shapes and cumulative-time evaluation order differ. Same-order
cold restart is checked with exact tensor equality. These tests establish
implementation equivalence on their fixtures, not benchmark superiority or
error bounds for arbitrary trained weights and unbounded histories.
