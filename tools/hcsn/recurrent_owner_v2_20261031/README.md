# Incremental recurrent cell ownership

This package fixes an implementation asymmetry in the previous task-value
experiment. Both ordinary and finite analytic cells retain their current state
between decisions. The generator, reset law, weights, input records, critics and
task policy are unchanged. The old research commit remains immutable:
`8fef2abec58dc0b40287de1e656f9042371979b5`.

## Contract

`CellOwner.query(driver, horizon)` reads the current state without advancing its
clock or random generator. `advance(sequence, driver, duration, reset)` consumes
one causal interval; a task reset occurs at its end. Repeated latent events and
the first latent event have distinct outputs. The finite analytic state has
three active states and two Erlang recovery phases. This does not turn an
auxiliary latent event into the task's answer-submission action.

The owner binds its family, mode, eleven frozen parameters, state, sequence and
elapsed time. Its sampled mode also checkpoints PCG64; its two 128-bit fields
are decimal strings so JSON consumers cannot round them to float64. Duplicate,
stale or out-of-order intervals fail before consuming physical state. One lock
serializes interval consumption. Checkpoints verify integrity and model identity;
they do not authenticate a hostile process, prevent rollback by an authorized
restorer, or guarantee exactly-once external side effects across arbitrary
crashes. Changing fitted dynamics requires a new owner and causal-history replay.

Kernel caching is per owner and bounded to 128 entries. Ordinary gates receive
the same incremental-state treatment. Distribution and sampled modes preserve
their respective laws; sampled state is not a distribution-valued state.

## Qualification

```bash
OPENBLAS_NUM_THREADS=1 python -m unittest tools.hcsn.recurrent_owner_v2_20261031.owner_tests
OPENBLAS_NUM_THREADS=1 python -m tools.hcsn.recurrent_owner_v2_20261031.qualification \
  --frozen /path/to/frozen-v1-evidence --out /path/to/new-replay-results
```

The replay is an implementation regression on already published data. It does
not refit, select models, change the old confirmation result, or supply a new
independent efficacy sample. Across all 3,200 applicable episodes and 18,238
decisions, maximum feature error is `3.33e-16`, maximum critic error is `8.89e-16`,
and action mismatches are zero. All 640 sampled paths reproduce the same random
events. A 2,048-interval irregular long stream, including resets and checkpoint
restores, has maximum mass error `2.00e-15`.

| Frozen policy | Legacy cell CPU (s) | Incremental cell CPU (s) |
| --- | ---: | ---: |
| Ordinary / myopic | 0.215490 | 0.151383 |
| Ordinary / continuation value | 0.209326 | 0.144420 |
| Analytic / myopic | 2.416625 | 1.189700 |
| Analytic / continuation value | 2.312606 | 1.244195 |
| Analytic / sampled continuation | 1.530735 | 1.631902 |

The paired implementation order is randomized. These measurements include cell
construction, queries and consumed intervals, and exclude content IO and critic
computation. The incremental distribution path additionally advances the last
interval, which the former query-only implementation omitted. The result fixes
repeated-history work; it does not demonstrate analytic-cell superiority over
ordinary gates or hardware energy savings. The sampled owner incurs integrity
and transactional RNG-copy work and is slightly slower in this measurement.

The unit tests cover irregular recurrence, sampled checkpoint continuation,
identity/corruption rejection, failure atomicity and concurrent duplicate
consumption. See `evidence/REPORT.json`, `evidence/REPLAYS.json.gz` and
`evidence/UNIT_TESTS.json` for exact identities and measured results.

Native task integration binds the external cell checkpoint in a durable native
action receipt. The physics in this package remains Python/SciPy; receipt binding
alone is not native analytic propagation. Main activation remains false.
