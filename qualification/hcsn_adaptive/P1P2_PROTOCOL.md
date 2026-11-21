# Adaptive boundary and learner qualification

This is a new research campaign. It does not change or qualify the frozen N256,
HPCA, or earlier HX experiments. Freeze a new manifest only after source tests
pass on the intended runtime. Existing receipts remain attached to their source.

## Stages and hypotheses

1. **Smoke:** one seed, small data, recovery and holdout isolation controls.
   Smoke labels must not be reused as a final qualification holdout.
2. **P1:** fix one readout learner, preferably ridge. Compare fixed boundary,
   training-selected scalar boundary, training-selected input-conditioned
   boundary, and train-fitted continuation boundary. Separately substitute fixed
   versus input-driven drift, and dual/risk-only/call-only/neither channels,
   plus independent `no_margin` and `no_occupation` substitutions.
   A one-factor-at-a-time matrix does not identify all interactions.
3. **P2:** freeze one encoder, boundary and feature matrix. Compare Frozen,
   Ridge, BP, ZerothOrder, ProgrammaticEdit and EditThenBP with the same eligible
   readout weight/bias mask, identical initialization and declared ceilings.
4. P3 real-event adapters and P4 capacity studies may use these interfaces, but
   must state their own task, modality, timing, scale and holdout scope.

The input boundary is `b0+b1*tanh(causal_input_0)`. It is a finite parameter
control law. It is not the He–Xiong optimal economic free boundary. The finite
backend call channel is a frozen-policy continuation value, can be negative,
and is not full HX equity. `transport_precision` and actual state dtype/bytes
are reported separately from input/output dtype; mixed precision must not be
reported as a native FP32 finite process.

## Continuation objective

`fit_continuation` accepts the training split only. States quantize the first
observed input and optionally the sign of a causal context input. It estimates
continue transitions. Reset preserves context and moves to a declared state.
The finite Bellman recursion compares continue and reset using their declared
rewards. Unobserved states remain marked unsupported.

The default running utility is `-(state-0.5)^2` and reset utility is `-0.25`.
Explicit causal training rewards may replace it, with a required definition.
This is an auxiliary reset-control objective for a forecasting task; it is not
automatically the supervised MSE or a causal model of population intervention.

The full discrete policy may be nonmonotone. The code projects it to a lower
threshold, evaluates that projected policy on its own continuation, and reports
the value gap and multiple sign changes. Neither the threshold projection nor
the finite-MDP optimum proves a globally optimal neural network or NDU system.

## Learners and costs

All updating learners optimize the same full-data objective:
`mean_squared_error + lambda/(N*O) * sum(readout_weight^2)`, where `N` is the
training sample count and `O` the output width. Bias is unpenalized. Stochastic
updates keep that full-data penalty coefficient; development selection always
uses plain task MSE. Programmatic coordinate patches include the same lambda,
and the regularized ridge solution is a stationary point for the BP, zero-order
and programmatic update definitions.

Ridge solves this regularized affine readout in closed form. It is not a
closed-form fit of nonlinear dynamics. ProgrammaticEdit chooses a readout
coordinate by residual correlation and applies a bounded least-squares patch.
It uses training labels and algebraic optimization, although it does not call
autograd. It does not reproduce an LLM agent that discovers a weight-space
program. ZerothOrder counts both antithetic forward evaluations. EditThenBP uses
the first half of its declared steps for edits and the remainder for Adam.

All methods may return NoUpdate when the untrained checkpoint has the best
development loss. Common ceilings do not imply matched actual FLOPs or equal
time spent. Reports retain actual training examples, encoder events, forward
and backward examples, proposals, development queries, wall time, overruns and
failures. Shared preprocessing is counted once by feature identity. Every
failed or discarded search remains in a hash-chained cost journal. Missing or
unsettled physical cost is unknown, not zero. Final evaluation and outer
process overhead are reported separately from optimization ceilings.

Every checkpoint reserves a durable cost event before model/optimizer/RNG
snapshot and serialization. It records the model, Adam state, selection/search
controller, Python/NumPy/Torch/CUDA RNG and minibatch generator, plus a settled
cost prefix. Costs after a saved checkpoint remain charged if work is replayed.
A safe checkpoint boundary can resume. An interrupted unclosed operation
blocks resume because its physical wall cost is unknown. This is not a claim
to recover a partially executed CUDA kernel or optimizer step.

## Data and final holdout

Each split is an immutable NPZ file with `x[samples,time,input]`,
`y[samples,output]`, and stable `ids[samples]`. Optional `dt[samples,time]` is in
seconds and must represent exact integer microseconds. Different complete time
schedules are executed in independent groups; no mean-dt replacement is used.
Optional `running_rewards[samples,time]` requires a task definition.
Both optional `dataset.json` and external-adapter `manifest.json` are bound by
the experiment manifest as well as all three NPZ hashes. This includes a real
adapter's query-time, source-data and normalization contract.

Unique split IDs are necessary but do not alone establish group or temporal
independence. A real-data adapter must document and test those split rules.
Future query timestamps may be inputs only when the declared prediction event
actually knows them. Target-row sensor values and labels must remain withheld.

Encoder normalization and boundary search use training data only. Readout
selection uses the development split. `run` never loads final test targets.
`seal_selection_set` requires all planned training attempts to terminate and
binds their selected payloads. `finalize` then evaluates each selected model
once, using an exclusive holdout claim. A crash after that claim leaves that
evaluation unavailable. Repeating finalization returns a matching saved result;
it does not run the test again. Training is refused after the seal exists.

P2/P3/P4 configurations sharing a test set must all be frozen before any such
test result is observed, or they must use new independent final holdouts.
For one-hot classification, all readouts fit the same MSE objective; final
accuracy, macro F1 (zero division is zero), and confusion are additional frozen
metrics, not selection criteria.

Each variant may contain a `flow` object overriding the campaign's flow
configuration; for example `{"flow":{"stages":1}}`, `2`, and `4` compare
Erlang phase counts within one frozen matrix. Every override participates in
cache and experiment identity and is re-applied at final evaluation. Channel
masks are readout feature ablations: they do not remove the corresponding
physical dynamics or claim cheaper channel computation. The reported mask
lists every actual feature, including event/content channels retained in all
variants. Prefer the explicit names `all_four`, `drop_risk`, `drop_call`,
`drop_margin`, and `drop_occupation` for independent scalar-channel controls.
Legacy `risk_only` and `call_only` refer to that dual pair;
margin and occupation remain present in these two controls.

## Commands

Run from the repository overlay root with the intended Python/Torch runtime:

```sh
python -m unittest qualification.hcsn_adaptive.continuation_tests qualification.hcsn_adaptive.learner_tests qualification.hcsn_adaptive.campaign_tests
python -m qualification.hcsn_adaptive.campaign make-data --directory /tmp/adaptive-smoke-data --seed 20261121 --train 32 --dev 16 --test 16 --length 6
python -m qualification.hcsn_adaptive.campaign freeze --config draft.json --manifest frozen.json
python -m qualification.hcsn_adaptive.campaign run --manifest frozen.json --output run
python -m qualification.hcsn_adaptive.campaign finalize --manifest frozen.json --output run
```

Example draft, to be frozen on the target host after source stabilization:

```json
{
  "experiment_id": "HCSN-ADAPTIVE-SMOKE-20261121-v1",
  "stage": "smoke",
  "data_dir": "/tmp/adaptive-smoke-data",
  "device": "cpu",
  "dtype": "float64",
  "seeds": [11],
  "variants": [{"id":"fixed-input-all-four","boundary":"fixed","drift":"input","channels":"all_four"}],
  "methods": ["frozen","ridge","bp","zeroth_order","programmatic_edit","edit_then_bp"],
  "flow": {"bins":4,"stages":2,"content_size":2,"upper_mode":"reflecting"},
  "learner": {"steps":16,"batch_size":16,"evaluate_every":4},
  "budget": {"wall_seconds":60.0,"development_queries":8},
  "feature_budget": {"wall_seconds":120.0}
}
```

`run --stop-after 4` pauses at a complete checkpoint; continue with
`run --resume`. Exact tensors, seed, method, code, runtime flags, data identities
and budgets must match. Do not overwrite a manifest to salvage an earlier run.
`campaign-summary.json` retains denominators and deduplicated journal totals.
