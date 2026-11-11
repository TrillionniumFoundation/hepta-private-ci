# Numerical qualification of visited states

The constructor's accepted parameter range is an input contract. It does not
qualify training throughout that range. The new tools retain actual visited
states and keep three distinct questions separate:

1. Did the recorded probability transport and event counts replay with the
   same source, physical parameters, geometry and durations?
2. How accurately does the projected chain represent a continuum continuation
   from the **reconstructed recorded law**?
3. Did a sufficiently trained model improve a real task at an acceptable cost?

These numerical tools address the first two questions. They never grant
scientific admission or formal-study completion credit.

## Record before updating model weights

Create `TrainingDomainRecorder(path, data_sha256=..., configuration_sha256=...)`
with a new path and hashes of the exact dataset and run configuration. Call
`capture(network, input_state, output, dt, episode_id=..., update_index=...,
valid_mask=...)` after a `return_trace=True` forward and **before** the optimizer
updates any parameter. Call `close()` after all intended captures.

The trace binds numerical source hashes, tensor-state model digests, all five
physical values, grid/operator configuration, prior/posterior probabilities,
interval counts and valid batch indices. Padding is excluded explicitly.
Actual zero-time observations remain valid records. Source hashes are checked
again at close and audit. The training ledger must also establish that every
intended forward was captured; the recorder cannot discover calls it never saw.

The default record budget is 4,096 batched time/layer records and the default
byte budget is 32 MiB. A byte ceiling of 64 MiB prevents creating a trace that
the reader cannot admit. On exhaustion, ranges and seen counts continue, while
the retained prefix is sealed with a digest and an explicit truncation reason.
Truncated traces, partial audits, empty traces and changed sources cannot pass.
Recording time and bytes belong in the experiment's cost accounting.

## Independent replay and perpetual continuation

```sh
python -m qualification.hcsn_differentiable.training_domain_audit \
  --trace run/trace.jsonl --output run/new-domain-audit.json --max-records 256
```

The oracle integrates perpetual continuum value over every active uniform
cell, the returning exponential tail and every remaining-time phase using
80-digit arithmetic. Forward automatic differentiation is compared against
80-digit central differences for **all basis coefficients**, covering every
retained posterior/batch mixture at those parameters. Posterior coefficients
are held fixed in this derivative check. It does not qualify differentiation
through the learned filter or second-order derivatives.

The projected continuation repeats each observed positive gap forever. For a
zero-time observation the report explicitly uses a `refractory/2` probe. This
is a constant-gap pressure test, not a reconstruction of future sensor events.
Very short repeated gaps expose QPR's lack of an exact semigroup: fixed-width
reprojection can introduce a large error even when each transition preserves
mass. Both that failure and its precise domain must remain in the evidence.

## Actual finite gap schedules

`training_domain_finite.audit_finite_schedule` compares a retained starting law
under a supplied actual gap sequence, with future observations disabled. Its
independent renewal reference checks terminal-once value, event count,
discounted count and active probability. Initial remaining-time phases are
integrated before reset/release. This is a shadow continuation fixture; it
does not claim that future learned posteriors equal a continuum filter.

Each finite report retains the full probability vector, gap schedule, physical
parameters, grid and operator configuration with a digest. By default the
operator uses active/hit/terminal rewards `0.4/1.0/0.2` and regeneration. Pass
the model's operator explicitly when rewards differ. A mismatched grid or a
nonregenerative operator is rejected; ablations do not inherit this oracle's
qualification automatically.

The finite reference uses 80-digit point formulas and positive Gaussian
quadrature at two orders. Order-doubling differences are measured numerical
sensitivities, not certified error bounds. Explicitly omitted tiny source
weights have a reported conservative contribution bound and are never
renormalized. The error scale is `abs(error)/max(1,abs(reference))`; rare event
checks on this scale constrain absolute error, not relative tail error.

`_first_hit_logprob` separately preserves finite log F/log G and first-order
derivatives when FP64 probability itself underflows. The network's existing
`risk` readout remains a conditional expected interval count. The log primitive
does not silently change network channels or confer FP32 qualification.

## Additional P1 input/precision diagnostics (new candidate)

The finite-schedule oracle now admits at most 4,096 explicitly fixed, finite
real interval scalars before any model computation; Torch scalars (even if
they have no gradient), strings and booleans are rejected rather than silently
converted. An unbounded iterable is stopped after a 4,097-item admission
probe. This does not permit optimizing a time schedule through the finite
continuation audit.

The existing 1% **scaled** value/count/discounted-count/active-probability
gate is unchanged. Reports additionally include absolute and ordinary
relative errors per quantity. A zero reference with nonzero discrepancy is
reported as JSON `null` (undefined relative error), never an implicit pass.
These diagnostics expose rare-event relative errors that were hidden by the
`max(1, abs(reference))` denominator; they are **not** a new numerical
accuracy certificate or a new scientific acceptance gate.

Historical C2 and original numerical evidence remain pinned to their original
source identities. This change must be tested and accepted as a distinct
candidate; do not rebind earlier training traces to this source.
