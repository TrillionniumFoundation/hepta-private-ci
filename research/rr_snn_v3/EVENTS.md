# Marked-event neuron runtime

This reference implements actual physical pulses, reset, deterministic refractory
periods, positive pulse debits, deadline obligations, input changes and final
censoring. It uses a finite-state marked continuous-time jump model. It is not a
Brownian network or an installed Hepta owner.

## Run and API

Run `node research/rr_snn_v3/validate_events.cjs`.
The validator emits complete JSON to stdout. There are 22 grouped checks,
including canonical JSON restore, 11 invalid inputs, a 2048-path marked Poisson
reference and a 2048-path ordinary CTMC endpoint reference.

`create(config, initial, continuation, hooks)` constructs a neuron.
`restore(checkpoint, continuation, hooks, expectedIdentity)` restores it.
The instance exposes runUntil, nextEventTime, enqueue, observe, snapshot,
statistics and pulsesSince. Pulses are retained with time, kind and channel.
A pulse on a self-channel remains a physical counted event even when the finite
evidence-state index does not change.

Config binds evidence states, marked channels, resetState, refractory, traceTau,
pulseDebit, budgetCap, horizon, maxRecords and an identity label. The initial
state binds stateIndex, budget, seed, obligations and external events. Hooks
receive only the current observation and delivered input, not the RNG,
residual hazard or future external queue. An owner can inspect nextEventTime
to schedule the system, but it is not a feature available to the neuron.

## Physical and resource semantics

Each stochastic pulse spends pulseDebit, resets the evidence state, increases
the exponentially decaying trace and starts the deterministic refractory period.
Unaffordable pulse channels have zero eligible hazard. Ordinary jumps and
marked self-events retain separate counts. Refractory intervals suppress random
channels but do not pause deadlines, inputs, resource shocks or refills.

A live obligation has id, deadline, renewDebit, renewLoss, emitDebit and emitValue.
At a deadline, the continuation operator jointly chooses renewal, dropping or
emission across all due obligations using the single neuron's shared budget.
At most one physical emission is permitted. A deadline emission pays its
additional emitDebit plus the physical pulseDebit, uses pre-reset evidence for
its reward, and creates one physical pulse. It is not a stochastic hazard event.
Renewal pays renewDebit and renewLoss and makes the obligation retained until the
fixed terminal horizon; this profile has one renewal cycle. Stochastic internal
pulses do not implicitly cancel other live obligations.

At equal times the order is shock, refill, control/input in insertion order,
joint deadline, refractory release, then stochastic event. The experiment
observes [0,H): runUntil(H) returns the terminal left limit with censoring.
Inputs or renewed obligations at H are retained but not executed or recharged.

## Event clocks and likelihood

An exponential residual hazard is anchored at physical changes. Merely observing
the process at an intermediate time does not redraw or reanchor its random clock.
This makes observation slicing and JSON restoration reproduce the entire physical
state and path statistics exactly on the tested JavaScript runtime.

Statistics include all regime rates, eligible channel exposures and counts,
total integrated hazard, event log rates and final censored likelihood.
Each input starts a new statistical regime even when its numeric rates equal
the preceding rates; different feature vectors must not be merged before taking
gradients. A direct redundant control can remain a no-op.

The versioned RNG is lcg32-avalanche-seed-v1. Its seed whitening and initial words
have regression fixtures. It is a deterministic research generator, with no
claim of cryptographic security or universal sampling quality.

## Restoration and bounded execution

The checkpoint retains RNG word and draw count, residual hazard and its anchor,
rates and regimes, evidence index, refractory expiry, trace anchor, complete
resource ledger, obligations, event queue and cursor, logs and physical pulses.
Object-key order is irrelevant; array order and every stored physical value
remain significant. Unknown fields and inconsistent accounting are rejected.
A work-cap failure poisons the instance so that partial work cannot be published
as a valid checkpoint.

These checks establish the stated reference dynamics and serialization contract.
They do not measure CPU energy, target-host performance, independent future
utility, architectural superiority or real Hepta Cell costs.
