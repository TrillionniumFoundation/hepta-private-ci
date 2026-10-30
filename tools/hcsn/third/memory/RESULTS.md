# Third-stage memory mechanism: recorded findings

**All 48 declared trainings and the independent evidence audits completed. The
development quality gate failed:** FullHX mass ridge improved memory512 by
25.7161 percentage points but reduced retrieval512 by1.9531 points, exceeding
the predeclared maximum1-point regression. No new confirmation cohort or
full-backbone training was started, and no quality threshold was changed.

## Scope

This is a controlled investigation of the shared associative-memory read rule.
It does not change the old `next/` evidence, and memory improvements are not
automatically attributable to the financial operators. The frozen development
matrix completed before its final gate decision. No new confirmation dataset
or full-backbone training is created by this stage's runner.

## Already-exposed checkpoint diagnosis

`diagnostic_results.json` independently reproduces twenty old-checkpoint test
conditions with NumPy: ten checkpoints, each at lengths 128 and 512. All original
accuracies match exactly. Parameters, recurrent states, keys, values and write
gates are held fixed; only the final ridge convention changes.

| Old model | Length | Original fixed normalized ridge | Mass-consistent ridge |
| --- | ---: | ---: | ---: |
| FullHX | 128 | 98.7695% | 100.0000% |
| FullHX | 512 | 63.3594% | 98.2031% |
| Old sigmoid | 128 | 98.5742% | 100.0000% |
| Old sigmoid | 512 | 63.4375% | 98.6719% |

These are means over five historical seeds. FullHX seed 2 at length 512 still
has errors after the counterfactual, improving from 23.8281% to 91.0156%.
The counterpart sigmoid seed improves to 93.3594%. This supports a material
normalization mechanism and simultaneously shows that the benefit is not
specific to financial gates. These exposed tests are exploratory evidence,
not fresh confirmation or retroactive passes of the original protocol.

All twenty old memory checkpoints have a nonzero write on at least one of the
four ordinary filler symbols. The exact orthogonal-distractor example isolates
normalization shrinkage even without key interference. Actual checkpoints can
also have key interference and changing values, so that example does not explain
every individual error uniquely.

## Numerical repair and retained failures

The first new implementation failed its declared float32 adjoint test at
inverse mass 1/4097 and condition about 327761. The maximum normalized adjoint
error was 0.007966, exceeding the fixed 0.005 tolerance, despite a small solve
residual. This failure, original code and first freeze remain in `revision1/`.

All eight branches now construct and solve their 16-by-16 systems in float64,
with the read cast back to state dtype. No tolerance was relaxed, no mass
gradient detached and no ridge floor introduced. The two intermediate evidence
serialization failures remain in `revision2/` and `revision3/`. They are not
training runs and are not counted as completed numeric receipts.

The current `numerical_validation.json` passes all 16 real-graph/dtype checks
and all 16 solve stress cases. Maximum recorded normalized directional error
is1.65e-9 in float64 and1.42e-4 in float32, below their respective unchanged
2e-5 and0.005 tolerances. Maximum independent solve-adjoint error is2.24e-8. The maximum
condition-times-solver-epsilon indicator is 7.28e-11. The separately recorded
condition-times-state-epsilon indicator still reaches 0.0391 for float32
states: internal double precision does not erase rounding in the accumulated
state, and none of these checks proves uniform long-time accuracy or gradients.

## Completed development matrix

The 48-run matrix consists of 8 branches, 3 new seeds, and 2 tasks. Every run
has the same 600-update/batch32 budget and approximately 6200 trainable
parameters. The current sigmoid control retains the identical FullHX Call;
the C1 control uses two nonfinancial functions. Persistent state and fixed table
bytes are separately recorded, and are not presented as equal FLOP budgets.

The full numerical receipt and exact input-overlap audit preceded training.
The six dynamic branches each have6217 trainable parameters and width62; the
two pure-memory branches have6250 parameters and width66. Dynamic branches
have identical initial parameters within each task/seed. Parameters and updates
are approximately matched; persistent state and computation are not matched.

Accuracies below are percentages averaged over development seeds11,29,47.
These are descriptive development results, not confidence intervals or a new
confirmation test. Every length128/512 condition has512 samples per seed.

| Branch | Memory128 | Memory512 | Retrieval128 | Retrieval512 |
| --- | ---: | ---: | ---: | ---: |
| FullHX fixed | 100.0000 | 74.2839 | 100.0000 | 99.6745 |
| FullHX mass | 100.0000 | 100.0000 | 100.0000 | 97.7214 |
| Sigmoid fixed | 100.0000 | 74.2839 | 100.0000 | 99.6745 |
| Sigmoid mass | 100.0000 | 100.0000 | 100.0000 | 97.8516 |
| Ordinary C1 fixed | 100.0000 | 74.2839 | 100.0000 | 99.6745 |
| Ordinary C1 mass | 100.0000 | 100.0000 | 100.0000 | 97.2005 |
| Pure memory fixed | 91.0807 | 74.2839 | 100.0000 | 100.0000 |
| Pure memory mass | 100.0000 | 100.0000 | 100.0000 | 96.4844 |

The pure-memory fixed branch's memory128 result includes a73.2422% failure in
seed11; the other two seeds reach100%. This failure is retained. The common
memory512 improvement also appears with ordinary C1 gates and with no fast/slow
dynamics, so these results do not establish a financial-operator-specific gain.

The primary FullHX per-seed results make the tradeoff explicit:

| Seed | Memory512 fixed | Memory512 mass | Retrieval512 fixed | Retrieval512 mass |
| --- | ---: | ---: | ---: | ---: |
| 11 | 22.8516 | 100.0000 | 100.0000 | 94.3359 |
| 29 | 100.0000 | 100.0000 | 100.0000 | 98.8281 |
| 47 | 100.0000 | 100.0000 | 99.0234 | 100.0000 |

The memory512 mean improvement is25.7161458 points. The retrieval512 mean change
is-1.953125 points, below the allowed-1 point. FullHX mass passes both per-seed
length128 thresholds, and all numerical checks pass. `retrieval512_delta` is
the sole failed quality check in the complete matrix. The candidate therefore
does not advance to fresh confirmation or larger-scale training. This decision
is independently recomputed in `development_summary.json`.

## Independent replay and numerical observations

`development_audit.json` independently replays all48 saved checkpoints with
NumPy at both lengths:96 conditions. All original accuracies are reproduced;
the maximum difference across accuracy, loss, Brier score and ECE is4.075e-6,
below the frozen5e-5 replay tolerance. It checks checkpoint bytes, recreated data
fingerprints and matching dynamic-family initialization identities.

The separate post-run evidence audit verifies a complete unique48-run matrix,
the600-update/batch32 budget, validation-loss-only checkpoint selection, finite
logged training quantities, source/checkpoint hashes and both inter-run restarts.
Every evidence check passes. An evidence audit pass does not change the failed
quality gate.

Across all trained development checkpoint evaluations:

| Numerical quantity | Maximum observed |
| --- | ---: |
| Matrix condition number | 1530.5203 |
| Relative solve residual | 7.013e-16 |
| Condition times float64 solver epsilon | 3.398e-13 |
| Condition times float32 state epsilon | 1.825e-4 |
| Absolute pre-tanh read coordinate | 1.8979 |
| Accumulated write mass | 190.5474 |

These measurements cover these small trained systems. They do not erase the
larger state-rounding indicator in the retained rank-one stress case or prove
unbounded-horizon numerical accuracy.

## Exploratory retrieval failure diagnosis

The separate diagnosis plan was recorded after32 development runs were exposed.
It is explicitly an analysis of seen development data, cannot change the gate,
and does not count as confirmation. It evaluates all six FullHX development
checkpoints, preserving each entire learned trajectory and all parameters,
and swaps only the final read convention. All12 original checkpoint/length
conditions are reproduced.

| Training convention | Evaluation length | Fixed read | Mass read |
| --- | ---: | ---: | ---: |
| Fixed | 128 | 100.0000% | 100.0000% |
| Fixed | 512 | 99.6745% | 100.0000% |
| Mass | 128 | 68.2943% | 100.0000% |
| Mass | 512 | 34.5703% | 97.7214% |

This refines the interpretation of the failed new training. The mass formula
does not inherently hurt these fixed-trained checkpoints at inference; swapping
their read actually reaches100% in this exposed cohort. Conversely, mass-trained
weights strongly depend on the matching mass read. The observed development
tradeoff therefore involves adaptation to the training/read regularization
convention. The experiment does not uniquely identify the optimization or key
interference mechanism. In particular, the post-hoc100% row cannot be promoted
to a newly confirmed fixed-training/mass-inference deployment recipe.

`retrieval_counterfactual_plan.json`, `retrieval_counterfactual.json` and the
source hash preserve this distinction from the predeclared development result.

## Costs and execution history

| Scope | Recorded measurement |
| --- | ---: |
| Completed training runs | 48 |
| Total optimizer updates | 28,800 |
| Cumulative training-call wall time | 900.10s |
| Compilation within those calls | 584.50s |
| Optimizer execution within those calls | 196.56s |
| Validation within those calls | 93.24s |
| Host batch preparation within those calls | 17.69s |
| Recorded runner elapsed time | 1579.46s |
| Additional original pause before first restart | 406.96s |
| Additional pause before final-run restart | 203.54s |
| Maximum process RSS over all runs | 741,552,128 bytes,707.2MiB |
| Maximum unclipped training gradient norm | 3.1468 |

Training-call components are included in the900.10s total and must not be added
to that total again. Runner time also includes evaluation and other in-process
work/waits; it excludes the two separately recorded inter-run gaps and separate
diagnostic/audit processes. Numerical-validation retries are not training runs.
These shared-CPU timings are not a model speed comparison, a GPU measurement,
an energy result or an equal-quality cost frontier.

Dynamic branches retain1373 float32 state scalars per sequence; pure memory
retains1313. FullHX and the sigmoid-with-FullHX-Call control report131,128 bytes
of shared fixed float32 operator-array data. These logical state/table counts
exclude parameters, transient float64 solve buffers, backward history, compiler
and runtime memory; they are not substitutes for process-memory measurement.

The original7.5GB raw-cgroup admission rule was amended after the first completed
run and before the second. A separately hashed driver retains at least1.5GB
estimated headroom after conservatively excluding clean inactive file cache.
All scientific source hashes, numerical receipts, data, precision, quality
thresholds and budgets remained unchanged. Original first-run evidence is
preserved byte for byte. A second inter-run restart after47 completed runs
released idle JAX caches; the same driver and1.5GB guard resumed only the last
run. No training attempt was interrupted or repeated.

The final admission had3.217GB estimated headroom. Since the operational
amendment, shared-cgroup maximum-limit/reclaim events increased25,738, while
OOM and OOM-kill counters did not increase. Counters include other work in the
shared cgroup and are not attributed to this model. `operational_handoff.json`,
`final_run_handoff.json`, both preserved-result directories, all logs and the
original failed numerical revisions remain available for audit.
