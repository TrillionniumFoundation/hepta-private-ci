# Terminal structure and evidence-drive mechanisms

## Fixed inherited identity

This additive candidate imports the PR #4540 source at
`012bcf3505cb9306d9cef094a1acc3ca34c978be`, under
`tools/hcsn/digital_read_before_20261031`. The earlier models, confirmation
cohorts, source/model freezes and negative findings remain historical evidence.
This candidate does not qualify under the old native model schema.

## Terminal-value structure

`MechanismPolicy(family, fit, terminal_mode, drive_mode)` retains 36 public and
12 representation inputs, a 32-unit tanh hidden layer, and a seven-value task
interface in this order:

`STOP, WAIT, READ, REPAIR, SUBMIT_0, SUBMIT_1, belief_logit`.

For `terminal_mode="structured"`, the learned final layer has four rows:
`WAIT, READ, REPAIR, belief_logit`. If `b = sigmoid(belief_logit)`, the returned
terminal scores are exactly `STOP=0`, `SUBMIT_0=1-2*b`, `SUBMIT_1=2*b-1`.
This guarantees the terminal ranking relative to the model's own belief. It
does not guarantee that belief is correct, that continuation scores are
calibrated, or that the selected action maximizes task utility. A positive
belief error can still produce a confidently wrong submission.

`terminal_mode="free"` retains all seven learned rows. Both candidates start
with the same first-layer parameters, and the structured candidate copies
continuation/belief rows 1, 2, 3 and 6 from the paired free initialization.
Changing output matrix shape can alter floating-point dot-product rounding;
paired initial outputs agree within `2e-15`, not necessarily bit for bit.
Construction preserves the caller's Torch RNG state.

## Evidence-drive semantics

| Mode | Interval propagation | Successful READ completion | Forecast bank assumption |
| --- | --- | --- | --- |
| sustained | Inherited last-symbol drift on every elapsed interval | Updates the public last-symbol fields | The last observed symbol continues driving future drift |
| impulse | Baseline drift bias and diffusion, with no observation drive | One bounded voltage translation after that interval | No further observation injection; neutral input drive |
| accumulator | Deterministic completed-evidence features | Adds the actual observation to bounded history | No stochastic cell forecast |

`transition_context(public, before, after)` requires one elapsed task step and
append-only history. It emits `injection_symbol` and `injection_reliability`
only when a successful READ becomes available. A delayed READ has no injection
at request time; a failed READ has none. The old symbol drives the sustained
interval before the new completion, preserving the causal READ order.

The impulse is a declared alternative input operator. For normalized active
voltage `u`, its target is
`tanh(atanh(u) + gain*symbol*(2*reliability-1)/boundary)`. Linear interpolation
onto active centers conserves probability; extreme targets fold into the
outermost centers. It creates no instantaneous firing. It is piecewise
differentiable, not an exact continuous diffusion solution. Refractory rows
remain refractory, so evidence arriving during recovery cannot change cell
voltage. The shared public last-symbol information is still available to every
readout. This choice must be considered when attributing information loss.

The single `evidence_accumulator` comparator uses a signed reliability sum,
positive/negative sums, count, bounded transforms and explicit elapsed-time
interactions. It uses only completed observations and the public clock. It is
not supplied the calibrated confusion matrix, teacher posterior, private
label or unread packet. It currently recomputes at most three observations;
the actual computation must be charged. Selecting accumulator mode with
different family names yields the same representation and is not independent
mechanism replication.

## Capacity accounting

| Representation | Free allocated / structurally active | Structured allocated / structurally active |
| --- | ---: | ---: |
| ordinary base or bank | 1,806 / 1,739 | 1,707 / 1,640 |
| clocked or first-passage bank | 1,806 / 1,806 | 1,707 / 1,707 |
| raw history | 1,799 / 1,799 | 1,700 / 1,700 |
| evidence accumulator | 1,799 / 1,799 | 1,700 / 1,700 |

The ordinary count removes three physical parameters and 64 first-layer
weights attached to unreachable refractory flags. A structured head removes
99 independent learned parameters for every family. Structural counts do not
prove equal identifiable statistical capacity: event families still have
extra physical parameters and usable refractory coordinates, while raw
history retains addressed observations explicitly. Equal update and measured
CPU panels must therefore remain separate comparisons.

## Interfaces and validation

`initial_mass`, `latent_inputs`, `latent_outputs`, `predict`,
`transition_for_context`, `prefix_mass`, `export` and `from_export` are the
execution/training APIs. `prefix_mass` remains conditional on the specified
behavior prefix. Autonomous policy return requires action probabilities in
the joint path weights and must not differentiate a supervised prefix loss
as though it were that return.

Run the model mechanism checks with:

```sh
PYTHONPATH=/tmp/hcsn-torch-runtime OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
python -m unittest tools.hcsn.digital_mechanisms_20261101.model_checks -v
```

The checks exercise terminal order/extremes, causal delayed completion,
single injection, retained probability mass, neutral WAIT behavior, a physical
finite-difference derivative, reachable-weight accounting, export/reload and
external RNG preservation. The initial development run had one failed
assertion requiring bitwise output equality between 7-row and 4-row matrix
products; exact copied parameter checks plus a `2e-15` output tolerance correct
that numerical overclaim. It was a development assertion failure, not a
scientific outcome.

`retention_diagnostics` supplies 30 finite-cell information probes. A balanced
hidden label generates one observation with reliability `.85`; the probes
compute the Bayes-recoverable label accuracy/Brier from cell state, active
states, event sign, merged event flags, and forced reset states. Removing
event sign or forcing equal reset cannot create information. Public
last-symbol features are deliberately excluded from these cell-only probes;
they already retain the observation. These are diagnostic distributions, not
new independent task samples or evidence of actual policy improvement.
