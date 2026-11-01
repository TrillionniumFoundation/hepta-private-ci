# Mechanism interpretation review: development evidence only

## Scope and source identity

Reviewed `digital-runs/development_v2`, fits **101, 103, 107**: 24 fitted
candidates per fit, 32 validation worlds per fit, both fixed/value controllers
and two Bayes reference controllers. All three processes exited zero. The
4,800 validation executions reuse **96 worlds and three independent fits**;
they are not 4,800 independent experimental replications. No confirmation
outcomes were inspected or used for this report.

The formal frozen source is `d3d71246a49664a050e04ef4a44a782350990865`.
Development used the earlier per-episode diagnostic-oracle implementation.
`diagnostic_cache_replay.json` separately records 36 actual DEV executions,
12 paired cases and zero action/teacher/outcome mismatches for the later cache
change. Development timing is not relabelled as timing of the formal source.
No frozen Python, Rust or protocol file was changed by this review.

## Table 1 — terminal consistency and actual terminal decisions

Each value is the equal-weight mean of the three fit means. Q-MSE is the
episode-weighted mean squared error of the selected action on each policy's
own visited states. Wrong-submit counts are per 100 episodes, using the
registered fitted-oracle regret threshold `.02`; they are not conditional
classification error rates.

| Family, value controller | Free-Q utility | Structured utility | Difference | Selected Q-MSE, free → structured | Wrong submits / 100, free → structured |
| --- | ---: | ---: | ---: | ---: | ---: |
| Ordinary base | .206875 | .203047 | −.003828 | .037548 → .042002 | 12.50 → 11.46 |
| Ordinary bank | .271823 | .088151 | −.183672 | .038623 → .028163 | 6.25 → 12.50 |
| Clocked bank | .343880 | .181510 | −.162370 | .039131 → .035427 | 13.54 → 14.58 |
| First-passage bank | .307344 | .239141 | −.068203 | .041110 → .037311 | 9.38 → 12.50 |
| Raw history | .203984 | .182214 | −.021771 | .026370 → .024099 | 7.29 → 17.71 |

All structured/impulse decisions have **zero terminal-structure residual** in
the raw DEV records. Wrong STOP is zero for both columns in every family, so
this development panel cannot demonstrate its reduction. The terminal
identities hold, while the five-family mean utility difference is
**−.087969**. Four families reduce selected Q-MSE yet reduce utility. These
descriptive results separate an enforced identity, calibration on selected
states and actual task performance; they do not predict the fresh-confirmation
outcome.

## Table 2 — visited-state calibration and control utility

All entries below use structured heads and fixed-update training. `On` means
the one-halfway-snapshot supervised occupancy augmentation. Margin is the
mean predicted gap between the top two legal Q values; a large gap alone is
not evidence that the chosen action is correct.

| Candidate / value controller | Utility | Value − fixed | Selected Q-MSE | Mean margin | Behavior strata unseen % | After augmentation unseen % |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Ordinary bank, on | .292188 | −.020703 | .030630 | .104150 | 12.05 | 2.83 |
| First-passage, off | .239141 | −.052240 | .037311 | .112691 | 12.13 | 12.13 |
| First-passage, on | .104505 | −.133880 | .038869 | .101307 | 13.45 | 2.96 |
| First-passage impulse, on | .293594 | +.019687 | .043105 | .110666 | 9.80 | 2.51 |
| Raw history, on | .248125 | −.184323 | .020646 | .112361 | 16.11 | 1.79 |
| Evidence accumulator, on | .408646 | −.010495 | .010328 | .105004 | 5.86 | 1.54 |

Coverage is over the coarse tuple `(tick, budget, broken, pending, history
length, last symbol)`. It omits exact observations, timings, prices and cell
state. The sharp decline in unseen strata therefore does not prove full
deployment-state coverage or successful Q correction. The first-passage
on-minus-off utility difference is **−.134635**, while impulse-minus-sustained
on is **+.189089**. These are DEV means, not accepted mechanism effects.

For the final report, preserve these columns separately for IID and OOD.
Present the four preregistered paired contrasts and their adjusted fit-level
intervals before secondary calibration/coverage tables. Do not pool fit,
episode and decision counts as equivalent replications. Keep equal-CPU results
separate from this fixed-update panel.

## Table 3 — trained readout immediately before and after events

The existing raw DEV output supports the following additional descriptive
join. Consecutive decisions were required to match the preceding complete
successor state. Intervals with any READ completion or failure outcome were
excluded, and the fitted teacher belief was verified unchanged. Entries pool
the listed transition pairs across the same three fits; this is not an
additional preregistered efficacy test.

| Trained first-passage policy | Transition | Pairs | Belief readout MSE before | After | Paired change |
| --- | --- | ---: | ---: | ---: | ---: |
| Sustained, structured/on | Event | 30 | .004982 | .012132 | +.007150 |
| Sustained, structured/on | Recovery | 16 | .034533 | .026473 | −.008060 |
| Impulse, structured/on | Event | 36 | .013592 | .011659 | −.001933 |
| Impulse, structured/on | Recovery | 16 | .028328 | .042534 | +.014206 |

This measures the **trained readout's** error against the unchanged fitted
belief. Elapsed time, task flags and selected trajectories still change; there
is no randomized matched counterfactual holding them fixed. It is neither the
maximum belief information recoverable by a new decoder nor a causal estimate
of event-sign/reset effects. The different signs across mechanisms are a
reason to retain the distinctions, not a basis for choosing one after seeing
confirmation.

## Table 4 — what the retention evidence establishes

| Evidence | What was actually computed | Interpretation / remaining scope |
| --- | --- | --- |
| 30 retained information probes | Initial fit-101 physical parameters; one `.85`-reliable observation; balanced class; exact finite-law Bayes recovery from full cell, active state, event sign, merged signs and forced/equal resets | Controlled initialized-cell diagnostic; not fitted-policy quality |
| Trained episode belief fields | Learned belief and fitted teacher belief on every actual visited decision | Supports readout error, selected-Q calibration and the descriptive event join above |
| True trained-task recoverable information | No independent decoder is trained/evaluated before/after events under a matched causal intervention | **Remains open**; do not substitute initialized probes or readout MSE |
| Continuous renewal subsystem | Separate CTMC distribution/event/checkpoint checks | Does not silently replace the inherited interval law used for task efficacy |

At elapsed time 3 in the initialized probes, first-passage cell-only optimal
class recovery is `.63614` for sustained drive and `.52644` for impulse; the
shared public last-observation channel retains `.85` in both. Removing event
sign lowers cell-only recovery to `.53146` and `.50436`. These numbers belong
to the initialized analytic probe and must never be placed in a table headed
"trained held-out accuracy".

The user's before/after recoverable-belief requirement is therefore partially
covered: controlled finite-law information and actual trained readout traces
exist, but trained causal attribution of memory/event-sign/reset is not closed.
A later diagnostic should preregister a decoder and matched interventions,
fit it only on TRAIN records, and assess it on a fresh diagnostic cohort; this
review does not change the current frozen confirmation design.

## Exact input and source hashes

| DEV fit | `validation_summary.json` SHA-256 | `validation_episodes.json.gz` SHA-256 |
| --- | --- | --- |
| 101 | `799b65e7ff7c929e71737982a2c5124006667af1c4fb57b98299eaafbd3f89e7` | `e62cf550bbfb6f851b1be2ca0e4ae354902d537659f687ef75071682a05d4037` |
| 103 | `f10b254186c02ac086155740406e6344a825a58d4bba89dea122c87f778e485d` | `be5b1732cd9914e2192147ffbaf4de1150794c51b6ab0551360cba646e70f07d` |
| 107 | `41c573c1f1c2662e607a995ccf1280a11b44fee723af28e36e43ba74c51c96c5` | `6584cf56c0582db9b4bbfd7e73afe7866cbb8c2b09d589a7cdf0e29188c887ba` |

Retention record `evidence/retention_and_runner_checks.json` SHA-256:
`4e5aeb5ff70cc279cd4e2efae6fcee16c9a5f8311edfd32be32357866d5e1a8a`.

| Frozen source | SHA-256 |
| --- | --- |
| `models.py` | `a1ba992b5756e53317964629aeb063b60732d632670ad8da2193700cb33ef495` |
| `training.py` | `7bdf1274dd3f2207e0c79c82a6e92a5f122cbc1acaac7a77ef78d310c9600f46` |
| `execution.py` | `6435bc3a5c2bd3c40009ddd53fbf56026a99c44a4e4a9a757db019b11e416df7` |
| `run_study.py` | `eae06e0e86aa9d31bc2f31d1c2c0034955fda0cecd311064bd57dae0d667af5b` |
| `protocol.json` | `8b26adfe6ade5a6de9d92ab3ab344fb402216dc5468b0800684e0cf9a4ad47b3` |

DEV execution/run-study hashes were respectively `c8d604228be101a452a8aef9753d6f3d7844b83126773ec76504c6637e79911b`
and `94cfae89eaea6abf0bc07f7aec557d2f8731a1a5e32d3bbfdcc7a5d161004382`;
its protocol hash was `4d8f80916516c5837f65197eef457ca63ccf32ab026bb465a81d3aed51efc1bc`.
The model/training hashes were unchanged. Final protocol fit-count selection
comes from the retained DEV variance planning, whose resource cap binds and
whose `planned_power_claim` remains false.
