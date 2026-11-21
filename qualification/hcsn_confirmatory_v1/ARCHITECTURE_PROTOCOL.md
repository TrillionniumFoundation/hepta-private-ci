# Architecture comparison, stage C

Status: implementation written, AST checked. The model numerical gate and all
formal fit/final work await root's frozen source/resource admission.

## Implementations and parameter matching

This is a fresh synthetic mechanism pilot with a new namespace. No stage-A/B or
historical final may choose widths, optimizer settings or implementations.

| Declared name | Actual implementation | Preset width | Expected trainable parameters |
|---|---|---:|---:|
| hcsn_finite | Existing PreparedSequenceModel, finite conservative population, full same-generator value/risk features; unused next-sensor head removed | content 28, bins 4, phases 2 | 280 |
| gru | torch.nn.GRU, one layer | 6 | 253 |
| diagonal_linear_ct_ssm | Stable diagonal continuous linear state equation, exact zero-order-hold update, learned input map and decay; NOT Mamba/S4 | 28 | 281 |
| lif_surrogate | Leaky integrate-and-fire with hard endpoint spikes/reset, physical refractory duration, learned tau/threshold and logistic surrogate gradients | 12 | 277 |
| causal_transformer | Two real self-attention/FFN TransformerEncoderLayer blocks, causal mask, residuals, layer norms, physical-time sinusoidal position features | 4, one attention head, FFN 4 | 309 |
| official_cfc | Installed official ncps.torch.CfC, default mode, one backbone layer of width 4 | 10 | 295 |

These are a predeclared 280 ±15% parameter band, not exactly equal parameter
counts or equal state/memory/FLOPs. Runtime counts are checked against [238,322]
and recorded. Counts above are code-derived expectations awaiting the numerical
gate. No disconnected padding parameters are used. Sizes/state complexity differ
and must not be hidden in an efficiency claim.

Official CfC API/source: [documentation](https://ncps.readthedocs.io/en/latest/api/torch.html)
and [official repository](https://github.com/mlech26l/ncps). Freeze records the
installed distribution version and every ncps Python source file's hash. If absent,
record UNAVAILABLE and run no stand-in. A changed installation requires a fresh
freeze. Individual physical intervals are expanded over CfC hidden units to avoid
the documented timespan squeeze/broadcast mismatch; none are averaged.

The SNN detects events at observation endpoints, with logistic surrogate derivatives
through hard-forward reset; it is not an exact event-time method or EventProp.
Its synaptic trace is real valued. No energy advantage follows from this code.
The linear CT SSM has a different model class from selective nonlinear SSMs; its
name must not be shortened to a claimed Mamba reproduction.

## Shared inputs, readout, training and selection

Every architecture receives the same four observed channels plus
log1p(actual_dt / 0.1), and the same per-example physical intervals. Derived causal
elapsed time is permitted. No timestamp resampling/averaging occurs. All share
last/mean/query-times-mean pooling and a scalar linear readout. The query is the
observed final fourth channel, used identically for every task/model, not a label.
There is no task-specific HCSN semantic encoder initialization in this stage.

Random initialization uses the same paired seed, with architecture-specific tensor
shapes. Each architecture first fits a train-only conditional ridge readout and
freezes that feature normalization. Twelve full-model BP steps then use Adam
(.005), readout regularization .001/n, and gradient norm clipping at 1.0.
Both incumbent and candidate are evaluated once on the same dev examples.
Candidate wins only on strict dev improvement; otherwise retain the exact
incumbent (NoUpdate). All model parameters have gradient presence/finite checks.
This small fixed schedule is not a tuned learning frontier for any architecture.

Pilot matrix: four independent task laws × three paired seeds × six declared
architectures (including optional unavailable CfC), 24 train/12 dev windows,
24 final windows per IID/unseen-clock regime, length eight. Staging may freeze
one to three seeds. Data seeds exclude architecture identity: within a task/seed/
split all architectures have identical data hashes and IDs.

First passage is an aligned physical-law probe. Burst, asynchronous sensor fusion
and associative recall are external signal/memory probes. Labels never call HCSN.
The unseen 180–450 ms clock range is absent from train/dev (40–120 ms), while
teacher physical laws and observation count are held fixed. This combines longer
duration and changed sampling; it is not a pure resampling-invariance test.

## Freeze, gate, fit, single final

Allocate a new namespace starting hcsn-architecture-confirmatory-v1/ with at least
54 characters. The source closure includes the prepared kernel, finite generator,
finite_control.py and impulse_execution.py, and the complete new package.
Freeze binds Python/NumPy/Torch, optional official CfC sources, CPU capabilities
and affinity, Torch build/parallel backend, deterministic mode and actual thread
pools. Source or execution identity drift refuses the run.

```sh
python -m qualification.hcsn_confirmatory_v1.architecture_run freeze --manifest NEW_ARCH_FREEZE.json --namespace ROOT_ALLOCATED_NAMESPACE --seeds ROOT_ALLOCATED_SEEDS
python -m unittest qualification.hcsn_confirmatory_v1.architecture_tests -v
python -m qualification.hcsn_confirmatory_v1.architecture_run fit --manifest NEW_ARCH_FREEZE.json --output NEW_ATTEMPT
python -m qualification.hcsn_confirmatory_v1.architecture_run final --manifest NEW_ARCH_FREEZE.json --output NEW_ATTEMPT --selection-sha256 EXACT_SELECTION_SHA256
```

The gate uses an independent unit-test-only namespace and checks causal prefixes,
actual parameter band and full-model finite gradients. Retain gate evidence and
cost against the source freeze. Formal fit generates only train/dev, and writes
each case before the aggregate selection. Root seals the exact selection SHA.
Final creates the exclusive consumed marker before any holdout generation. Failed
or interrupted final attempts are not silently retried under another directory.

## Cost and interpretation

The write-ahead CostLedger charges construction, common readout fitting, all BP
forwards/backwards, dev/final, failures and unavailable construction attempts.
Each candidate's BP work uses one block reservation rather than per-step disk
flushes. Actual completed optimizer steps are retained, including on failure;
reserved work remains a conservative upper charge after an interrupted block.
Initial ceiling: 180 wall seconds across fit/final with declared work caps.
Operation checks are soft boundaries; root supplies hard watchdog/RSS admission.
A companion cost JSON is written after primary receipt serialization/checkpoint;
its own serialization, stdout and process exit require root's external process
meter. The few-minute bound is a budget, not an observed performance result.

Report task × clock × seed paired MSE, all error arrays, failure denominators,
parameters and elapsed total work. With three seeds, give descriptive differences
and ranges, no significance claim. Do not pool tasks with different target scales
or bootstrap individual windows as independent fitted models. General inference
requires a new adequately powered preregistered namespace and adjusted contrasts.

No quality or speed claim is warranted until actual completed receipts are read.
This experiment does not test multimodal foundation models, token-scale attention,
general pretraining replacement, biological fidelity or neuromorphic hardware
energy. Feature ablations are a separate H1 stage and cannot be selected on these
architecture final outcomes.

