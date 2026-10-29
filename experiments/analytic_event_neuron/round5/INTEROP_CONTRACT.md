# Round5 typed operator interoperability

This small research adapter reuses existing operators and tests their semantic
boundaries. It introduces no new fitted model, confirmation study, native owner,
production authority, or promotion decision. Round1–4 sources remain unchanged.

## Exact sources

Terminal laws and signed transport are imported from terminal Round4 commit
`62728e442acac6c67831b9b4adffadc075294f62`. Four files from first-passage commit
`2abafe82a99d6def2132e605e57af183e3080194` are copied byte for byte into
`vendor/first_passage_cell`. Relative imports continue to use those original
copies. `DEPENDENCIES.json` records each original path, pinned commit, Git blob
SHA1, content SHA256, local path and byte count. It also records the environment
in which the conformance checks ran. It is not a full environment lockfile.

The only new operator logic is typed dispatch, upper/lower reflection, clock
validation, output labels and delegation. The probability formulas, absorbing
filter, signed packet decoding and stochastic cell are the original code.

## Executable interfaces and event meanings

| Interface | Required information | Meaning |
| --- | --- | --- |
| `forecast(TerminalForecast(...))` | Explicit Round4 conditional law, condition time, horizon, finite strictly ordered thresholds | Three disjoint endpoint events: `X_T <= lower`, `lower < X_T <= upper`, `X_T > upper` |
| `forecast(FirstPassageForecast(...))` | `BrownianPath` with actual initial level, drift, diffusion, barrier and `BoundarySide`; physical time, horizon, discount | First hit of one fixed barrier during one unreset Brownian cycle |
| `observe_cycle(CycleObservation(...))` | Positive distance grid, live masses, prior absorbed mass, drift/diffusion, time, explicit `EventObservation` | Projected lower-barrier absorbing belief updated only by declared observations |
| `new_regenerative_cell(...)` | Original `CellParameters`, actual initial level, RNG seed | Original stateful lower-barrier cell, including multiple events, reset, refractory time and RNG counter |
| `restore_regenerative_cell(...)` | Original checkpoint and independently expected model digest | Original strict restoration and subsequent continuation |
| `decode_communication(...)` | Original Round4 signed-event decoder and actual packed bytes | Terminal-law communication with packet kind, clock and zero-delta flag preserved |

All forecast probabilities are physical FP64 values, with stable logarithms.
This adapter does not apply Round4's positive Q24 release operation. The signed
packet decoder still has its original quantized state reconstruction rules.

### Endpoint law and physical path

`TerminalForecast.law` must already describe the requested endpoint conditional
on the available information. Its horizon is declared metadata, not an
instruction to propagate that law again. A terminal mixture does not identify
the process between now and the endpoint; it cannot supply `BrownianPath` or
`CellParameters`. Untyped dictionaries and a terminal law passed as the path
are rejected. The caller remains responsible for the provenance of physical
parameters and the correctness of the conditioning information.

The inherited runtime schema permits one or two Gaussian components with
strictly positive weights and variances. It requires `lower < upper`; a
same-threshold binary pair or deterministic terminal atom is outside this
three-channel adapter's effective domain. The common-threshold call/put
complement identity is a mathematical property, not an accepted request to this
strictly ordered three-channel API.

For a lower barrier, the pinned kernel receives
`distance = initial_level - barrier` and the original drift. For an upper
barrier it receives `distance = barrier - initial_level` and the negated drift.
Initial states must be on the live side or exactly on the boundary. Coefficients
remain constant during the requested segment; diffusion is strictly positive.

`hit_probability` and `survival_probability` complement each other for that
one barrier. Two separately evaluated lower/upper hitting probabilities can
overlap and sum above one. They are never normalized into complementary
call/put channels. A competing two-barrier first-exit law would require a
separate operator and is not provided here.

`hit_density_per_time` is an ordinary positive-time density, not a probability.
`discounted_hit_weight = E[exp(-q*tau) 1(tau <= horizon)]` is not a probability
when `q > 0`. The boundary atom has hit/weight one, survival zero and ordinary
density zero, including at horizon zero. An interior state at horizon zero has
no hit. Physical timestamps and horizons are finite and nonnegative.

### Absorbing-cycle observations

Live grid masses plus the prior event atom sum to one. `MISSING` supplies no
likelihood evidence and retains both live and absorbed mass. `OBSERVED_SURVIVAL`
conditions on no hit and removes the absorbed atom. `OBSERVED_EVENT` means the
cycle has been absorbed by the observation time, including an earlier absorbed
atom; it does not identify a newly timed event in this interval. A timed event
needs the appropriate density/interval likelihood elsewhere.

An optional Gaussian live-state sensor is accepted only with observed survival.
The original finite-grid projection reports tail mass and explicitly does not
preserve the continuous semigroup or produce an exact Gaussian posterior.
This is a single absorbing cycle; hidden-state renewal after unobserved resets
is not implemented. No missing packet or zero transport count supplies survival
evidence to this filter.

### Physical state, reset and communication

New regenerative cells start at physical time zero. The original `advance`
handles an immediate event at/below its lower barrier, every subsequent reset,
refractory carry and all remaining segment time. Original restrictions apply,
including finite duration in `[0,10]`, two inputs, positive reset distance,
refractory floor and the segment-dependent 128-event bound.

The returned object is the original `FirstPassageCell`. Its `repair()` is an
explicit intervention and does not increment natural event count. A task driver
must charge the intervention and other task costs; this adapter contains no
payoff evaluator and makes no all-cost utility claim.

Checkpoints bind physical parameters, model digest, level, time, refractory
remainder, event count, RNG seed and counter. Replay checks use identical future
segments and inputs. Identical seeds with different segment schedules are not
claimed to describe an identical Brownian sample path. Terminal decoder state
and physical cell state have separate schemas; neither restores the other.

Signed packet counts describe changes to terminal-law parameters. A zero-delta
packet can be `observed`, `missing`, or `propagation` under the original protocol.
`decode_communication` preserves the actual kind and advances only its original
decoder. A zero delta is communication silence, not a physical no-hit event,
an absent observation, a call/put sample or a physical reset. No packet means
there is nothing for this function to decode.

## Conformance and evidence limits

Run from the repository root:

```bash
python3 -m unittest experiments.analytic_event_neuron.round5.test_interop -v
```

The tests exercise original implementations: an independently calculated
zero-drift terminal/first-hit disagreement; overlapping one-sided hits;
boundary atoms and discounting; missing/survival/event updates; multiple actual
events and refractory carry; exact checkpoint continuation; rejected semantic
and checkpoint conversions; actual signed transport with zero deltas; and
content identity of every reused dependency.

These checks establish narrow interoperability. First-passage branch utility
results, terminal Round4 calibration/transport results, free-boundary learning
results, and adaptive surrogate results retain their original tasks, source
seals, denominators and acceptance criteria. No result transfers through this
adapter. A common downstream task needs its own registered information/cost
contract, controls, fits if applicable, and independent evaluation. No new
native Q32/Q24 numerical-profile conversion or production backend is supplied.
