# Actual state recovery and paid reprocessing

This module supplies the missing intervention mechanism. Its behavioral checks
are not evidence of positive task utility. A separate frozen study must fit or
select its recovery rule on training and validation objects before confirmation.

## Prefix, fault and four actions

The observation budget and timestamps are public. A fixed intervention follows
`T-2` acquired frames by default. The service retains a trusted raw-event cache;
the fault affects the model's content moment, not its parameters, probability
law or cached input. Registered faults erase or negate content. A service alarm
identifies that an injected fault occurred, without identifying its kind or
providing the target label. The same prefix, alarm, prices and suffix reach all
four actions. Fault assignments depend only on a frozen random seed and group
identity. This is a diagnosed synthetic storage-fault profile; it does not test
a realistic fault detector or spontaneous unobserved faults.

| Action | Actual state operation | Cached input work |
|---|---|---|
| `none` | Preserve damaged state | None |
| `reset_only` | Replace the complete state by `initial_state` | None |
| `replay_only` | Preserve damaged state and call `observe` on each old event | Re-encode each cached event; no second physical propagation |
| `reset_replay` | Start from `initial_state`, reconstruct the original prefix with `step` | Re-encode each cached event and reproduce its source interval |

Every arm then processes the actual remaining suffix and produces a class
prediction. A real reset therefore loses content unless reprocessing reconstructs
it. The model does not receive a hand-authored correctness reward for recovery.
Correctness is measured from that final prediction. The clean, uncorrupted
continuation is a separately timed diagnostic, not a free production oracle.

Replay carries original source timestamp metadata. `reset_replay` reconstructs a
historical state as a computation; it does not roll back real time. `replay_only`
reapplies observations to the current state without propagating elapsed physical
time again. Service latency is charged separately. The external task does not
evolve during this service latency in this profile. Recovery in a changing
external environment remains a separate experiment.

## Causal selector and held-out procedure

`paired_recovery(model, x, dt, labels, ...)` executes all four actions and returns
per-object predictions, correctness, fees, utilities and pre-action features.
Labels enter only the evaluator. Pre-action features contain class probabilities,
their entropy and margin, the alarm, public clocks, prefix length, cache size and
prices. They never contain future payload, future correctness or a preferred
action. All source events used by the encoder are the current paid event and
its paid predecessor, with public clock features.

`fit_selector(training, validation)` considers four alarm-conditional fixed
actions and three ridge value models. Ridge targets are actual four-action
training returns. Validation utility selects the complete rule; an exact tie
prefers the earlier candidate, starting with no recovery. The result includes
the serialized rule, its hash and all validation candidate scores.
`apply_selector(frozen_policy, confirmation)` receives that unchanged rule.
No-alarm objects take `none` under every candidate. Monitoring and cache costs
still apply. Fault cohorts are not independent model-training seeds.

The default integration should evaluate both distribution cores, both original
tasks, all independent fit seeds and both faults, along with an all-no-fault
cohort. Both families must receive identical fault masks and prices. Positive
recovery utility within one family does not establish an analytical-core
advantage; the paired between-family difference must be reported separately.
This module completes all input frames. Its result is a read-all recovery profile,
not the value of the original STOP controller or an optimal recovery policy.

`recovery_run.py` connects this interface to the main campaign's selected
value-trained models. Its ordered CLI stages are `prepare`, `fit`, `freeze`,
`confirm`, and `aggregate`, each taking `--output` with the campaign directory.
`fit` and `confirm` also take `--task` and `--seed`. A job handles both
distribution families. `freeze` requires every registered policy to exist;
`confirm` verifies every policy hash before accessing the test split.

The registered campaign uses the no-fault, sign-flip and zero-content cohorts.
Fault prevalence is one half in each fault cohort, assigned at context-group
level. Recovery rules are selected only on IID training/validation objects.
Confirmation covers IID and long-distractor objects for every fit seed. The
selector is separately calibrated for each trained family, so this recovered
system comparison is not an exactly shared-selector core-only intervention.

Confirmation also runs the chosen action as an actual streamed computation,
without first running the other three actions inside that execution. Its
predictions and choices must equal the four-arm evaluator's selected outcomes.
Its full-batch CPU and processed-frame count are reported separately. Source
state, fault and prefix features are recomputed in this actual execution.

The price sensitivity keeps the validation-selected policy fixed and scales
all incremental protected-service costs by 0, 0.5, 1, 2 and 4. Original
acquisition/time costs remain fixed. No policy is refitted on confirmation
outcomes or chosen using the sensitivity result. Per-object arrays and every
validation candidate score are retained.

## Costs and operational evidence

The frozen normalized utility prices are:

| Component | Price |
|---|---:|
| Original raw-frame acquisition | 0.0025 per frame |
| Original physical time | 0.0005 per source time unit |
| Monitoring | 0.001 per object |
| Prefix cache | 0.00000001 per stored byte |
| Reset | 0.005 per reset |
| Cached-event reacquisition | 0.0025 per replayed event |
| Replay processing | 0.00025 per replayed event |
| Replay service latency | 0.05 time units per replayed event |
| Reset service latency | 0.1 time units per reset |

Service latency uses the same time price. The entire prefix cache and monitor
are charged to every protected arm. In addition to the matched protected
`none` arm, `gain_vs_unprotected_none` subtracts a no-cache/no-monitor alternative
with the same damaged predictions. It is an accounting comparator; the study
does not claim to have benchmarked its separate implementation.

The code records actual batch process CPU, wall time, raw-frame reads, cache
reads, reconstructed frame count and parameter count. Shared prefix computation
is counted once in experiment CPU; operational per-action CPU can combine its
common prefix with that action's suffix and recovery work. Selector CPU is
measured separately. Action calibration, four-arm counterfactual collection and
clean diagnostics are research costs, not costs of a deployed single action.
Tariffs are declared synthetic task prices. They are not measured provider
billing, GPU energy, physical Joules, or real network acquisition latency.

## Behavioral verification

Run from the repository root:

```bash
PYTHONPATH=/tmp/hcsn-torch-runtime:$PWD python -m \
  experiments.hcsn_distribution_content_r15_20261101.recovery_checks \
  --output experiments/hcsn_distribution_content_r15_20261101/recovery_checks.json
```

Checks include independent additive-state action outcomes and fee calculations,
source-state isolation, future-payload and label noninterference, no-fault
overhead, and actual streaming/reconstruction equivalence for both distribution
cores. The transparent additive witness is expressly excluded from model-quality
claims.
