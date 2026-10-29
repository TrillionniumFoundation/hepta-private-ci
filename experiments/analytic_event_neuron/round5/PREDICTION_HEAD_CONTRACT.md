# Research trained terminal prediction head

This separate adapter makes a trained prediction-head path executable. It does
not alter the 107 frozen selection-study sources, train a model, activate a
production owner or repair the failed Round5 calibration/joint qualification.
It supplies no new efficacy, utility, native execution, energy or latency claim.

## Input and model identity

`PredictionHead(run_dir, seed=..., window=..., arm=...,
expected_freeze_sha256=...)` verifies the exact reviewed source, numerical
environment, prepared evidence and freeze through the original study verifier.
It rechecks the selected checkpoint bytes before loading that selected model.
Only the registered zero-extra-context FP64 arms are supported. Verification
hashes the existing prepared datasets for provenance; inference never opens
datasets or reads labels. No confirmation files are consulted by this adapter.

`PublicHistory` has exactly five fields: observations, physical times, Boolean
observation/occupancy masks and sensor variances. Their common two-dimensional
shape has at least one query and one to eight slots. Occupied times are finite,
nonnegative and chronological; seen variances are positive. Public inputs are
copied, normalized by the original public-history projection and made read-only.
Missing-slot values and variances provide no likelihood evidence. The API has
no query identifier, hidden law, future target, unacquired-action observation,
context-history or calibration-label argument. A dataset dictionary is rejected.
This is a dataflow boundary, not a sandbox against hostile Python mutation.

`checkpoint()` returns model/source identity without model parameters or query
state. `PredictionHead.restore(checkpoint, run_dir)` reloads through the same
verification and requires exact binding equality, including the adapter and
interop source hashes. No physical membrane, reset, RNG or packet state is
represented or restored by this stateless head checkpoint.

## Terminal output and numerical domain

`head.forecast(public, row=..., horizon=..., lower=..., upper=...)` returns an
explicit `interop.TerminalForecast`. Horizons are exactly `0,.5,1,2`; nearby
unregistered values are rejected. The original `cal.predict_distribution`
already propagates to all those horizons. This adapter selects the requested
row/horizon slice and never propagates it a second time. Conditioning time is
the latest occupied physical slot, even when that scheduled observation is
missing. The declared endpoint is conditioning time plus horizon.

The inherited `cal.law_at` prunes structural zero components with log weight
`-inf`. A numerical zero with finite log weight is an underflowed positive
component: conversion is rejected, because discarding it could change stable
extreme log tails. The runtime law requires one or two strictly positive
Gaussian weights and variances. Same-threshold call/put pairs, reversed or
nonfinite thresholds and deterministic terminal atoms are outside its domain.
The three endpoint channels retain `X_T<=lower`, `lower<X_T<=upper`, `X_T>upper`.
Nothing in this API constructs a first-passage, survival or regenerative law.

`release_q24(terminal_forecast)` separately calls the actual inherited
`runtime_law.release_law`. Its positive Hamilton counts sum to `2**24`; released
probabilities are distinct from the returned physical probabilities/logs.
This is the existing Python release operation, not new native Q24 execution.

## Conformance

Run `python -m unittest experiments.analytic_event_neuron.round5.test_prediction_head -v`
with the registered prepared evidence and freeze restored. Tests use a separate
unit namespace, the existing selected checkpoint and saved development history;
they do not generate or inspect registered confirmation arrays. Tests compare
actual learned component moments and independently calculated call/put logs,
registered endpoint selection, missing-observation clocks, private-input
rejection, structural-zero pruning versus actual finite-log underflow rejection,
the original Q24 release, and model/source-bound checkpoint restoration.
