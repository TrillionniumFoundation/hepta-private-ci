# Independent result review

## Frozen audit execution

This section reviews the completed, registered conditional-value and broker
audits. It does **not** report the 108,800-trajectory confirmation result, which
must be assessed from its complete receipt and summary separately.

The frozen manifest is
`3cda25b5fc17774e624d590679267066b51a9246072801c53453ee964b2202f0`,
frozen at `2026-10-31T02:23:47.523187+00:00`. Audit launch was recorded at
`2026-10-31T02:25:35+00:00`; completion was observed at
`2026-10-31T02:26:24+00:00`. The CLI exited successfully with empty stderr.
The measured audit-body wall time was 15.514 seconds. Launch/finish records are
`evidence/AUDIT_LAUNCH.json` and `evidence/AUDIT_FINISH.json`. All frozen file
hashes were checked again after execution and remained unchanged.

| Output | SHA256 |
| --- | --- |
| `evidence/audits/AUDIT_SUMMARY.json` | `c7eb2f743b0348c5a448357fbccbc446eb8462f18e8638035b24ff6492597442` |
| `evidence/audits/conditional_qpi.json` | `0a671f157fe597f5e628b51ec3351704680f6612f02e441a9a093a0b96b2a363` |
| `evidence/audits/broker_trace.json` | `8eafa4fd452fb136100bd2fe907659b18dc055be682fbf56e799dbffbcee1863` |
| `evidence/audits/native_manifest.json` | `c826d119952bee7ffef6d479a0c6f9248ffa7eee876c2717dc698b2b90b826ee` |
| `evidence/audits/snapshot_audit.json` | `65d317465a9733cd4237a6f29f5cccad1a129ea625fd06c7e7bf0a70e12d5769` |

## Conditional values: execution complete, calibration remains imperfect

All five fitted seeds, 40 registered scripted public prefixes, and 119 legal
state-action cells are present. Each cell has 64 conditional continuations:
7,616 in total. Prefix identity, public-state digests, legal actions, the actual
post-transition latent state, call count, and future-randomness namespaces were
independently checked. Truth is resampled from the public posterior; unseen
sources and future internal draws are resampled, with common innovations across
candidate actions within a replicate. The current neuron event fee is sunk and
is not charged again in action Q; the current compute fee is charged.

The exact comparison is finite joint-state **greedy deployed-policy Qpi**.
It is not original task Qstar and not a continuous controlled-diffusion QVI.
The fitted head was initialized from task Qstar and refined against a soft-policy
joint return, so its greedy-deployment calibration needs explicit measurement.

| Descriptive quantity | Result |
| --- | ---: |
| Learned head versus exact greedy Qpi, RMSE | 0.145696 |
| Learned head versus exact greedy Qpi, MAE | 0.127377 |
| Learned head versus exact greedy Qpi, bias | -0.058027 |
| Largest absolute learned-value error | 0.354189 |
| Conditional Monte Carlo versus exact greedy Qpi, RMSE | 0.100182 |
| Mean conditional Monte Carlo standard error | 0.086377 |
| State-action cells within descriptive mean ± 1.96 SE | 105 / 119 |
| Largest absolute standardized Monte Carlo residual | 3.13944 |
| Mean regret of selected first action under the same greedy continuation | 0.001194 |
| Largest such first-action regret | 0.015755 |
| Prefixes with zero regret to numerical tolerance | 35 / 40 |

The 119 cells are correlated within prefixes and are not 119 independent model
fits. Seven of 40 prefixes have at least one mean outside its descriptive 95%
interval. The intervals are plug-in, finite-sample Monte Carlo summaries, not a
registered simultaneous coverage test. This fixed 64-continuation audit must
not be described as a high-precision Monte Carlo oracle or automatically
expanded until agreement looks favorable. The independent exact finite graph
is the stronger reference available for this task.

### Deterministic diagnostic after the registered audit

An explicitly **post-hoc** calculation evaluated the same frozen models and
the same prefix/internal states under the exact soft-policy graph. It generated
no new stochastic episodes, changed no model, and selected no checkpoint.
Results are saved in
`evidence/audits/SOFT_GREEDY_CALIBRATION_DIAGNOSTIC.json`, SHA256
`e784fd55908973a80e9b8090ac267c1a68aa0ba9bb7698a6b8fce53eb22a7c7d`.

- Learned head versus exact soft Qpi RMSE: **0.144984**.
- Exact soft versus exact greedy Qpi RMSE: **0.013276**.
- Learned STOP-relative advantages versus exact greedy advantages RMSE:
  **0.176819**.

Thus the absolute-value calibration gap cannot mainly be explained by changing
from the soft training policy to greedy deployment. Its precise cause is not
identified by this diagnostic; possible approximation/training tradeoffs must
be investigated separately. Good action selection at many easy prefixes is
not equivalent to reliable numerical calibration of marginal action values.

All five nonzero first-action regrets occur at the initial state of preset 6.
READ costs 0.004 and WAIT costs 0.012 before their common latency charge. Every
fit selects WAIT, whereas READ has higher exact value with that same fitted
policy used afterward. The five regrets are 0.015755, 0.008002, 0.008001,
0.007970 and 0.008012. This is a reproducible cost-sensitivity limitation; it
must remain in the report rather than be hidden by the overall mean regret.

## Actual artifacts and short-window continuation

The 16 independent broker episodes used the frozen D11 hard policy's actual
selected actions. They are a functional integration audit, not extra efficacy
samples for the main comparison.

| Observed operation | Count |
| --- | ---: |
| READ | 6 |
| WAIT | 25 |
| REPAIR | 4 |
| STOP | 16 |
| Successful independent client/server terminal readbacks | 16 / 16 |
| Guard fallbacks | 0 |
| Exact policy-resumption windows | 35 / 35 |

The broker performed 19 observed-source reads totaling 4,864 bytes, wrote 1,024
bytes for four repairs, and initially wrote 16,384 fixed-size source bytes.
Terminal output artifacts total 5,128 bytes. All 16 artifact hashes were
independently rechecked against the recorded receipts. Actual JSONL transport
was 8,155 request bytes and 95,995 response bytes. These are different from
policy packets that were only encoded in memory.

The 35 saved policy snapshots total 5,950 bytes. Their cumulative measured
read/restore time was 2.603 ms. Resumed actions, latent masses, Q values and state
hashes matched exactly on the recorded continuations. These are short finite
episodes with preserved public inputs and frozen model weights. They do not
establish long-run training recovery, optimizer restoration, whole-worker
migration, or production process fault tolerance.

The broker section took 0.561 seconds including its operations and continuation
checks. Nested source, roundtrip and restoration timers must not be added again
to the inclusive total. No energy measurement was performed.

## Native handoff and claims still requiring evidence

The exact native input manifest is
`evidence/audits/native_manifest.json`. Its inputs are explicitly declared
Gaussian proxies from public terminal posteriors. A separate native execution
receipt is required before claiming that handoff executed. Even successful
execution of the historical adapter would not install Round7 dynamics or
learned weights in Rust or activate a production Hepta neuron.

This audit closes the registered execution/readback and policy-continuation
checks at their declared scope. It does not close marginal-value calibration,
the identified cheap-READ cost regime, open-domain/raw-document learning,
continuous free-boundary theory, or measured hardware/energy superiority.
The main efficacy and full resource comparison remain subject to the complete
fixed-sample confirmation review.

## Subsequent native execution review

The completed `evidence/native_bridge/SUMMARY.json` was independently reviewed
after the audit handoff above. Its SHA256 is
`c45ea6f8dd37f42d612939797e278cd4d287ef4f6c4661471a0c53d586fa2879`.
All 16 execution receipts match their manifest inputs and actual terminal
artifact hashes. The pinned executable and historical build-receipt hashes
also match. This run made 48 native subprocess calls and 80 original sparse
ticks; all 16 within-pair continuity checks and reset controls passed.
The detailed review is `evidence/audits/INDEPENDENT_NATIVE_REVIEW.json`.

All 16 typed results explicitly retain `DENY_ALL`, abstain, and report no
calibrated success probability. Feedback verifies a writer/readback SHA256
match, never hidden task truth. The native probability head takes the declared
Gaussian proxy of the public posterior, not the learned Round7 latent state.
These results establish actual local execution of the historical typed and
sparse runtime bridge. They do not establish that Round7 dynamics or learned
weights have been installed in Rust, that an Agentd owner has been activated,
or that the original native neuron is calibrated for this task.

Measured native-bridge wall time was 109.796 ms, with 33.494 ms controller CPU
excluding child processes and 30.350 ms child CPU. The 55.871 ms subprocess
roundtrip measure is nested within wall time and must not be added again.
No fresh compilation occurred; historical build expense remains separately
identified rather than treated as zero.

## Completed confirmation review

The completed fixed-sample confirmation has now been independently reviewed;
this section supersedes the earlier pending-confirmation status. I scanned all
108,800 compressed raw trajectory records once, checked the complete expected
identity grid and both external/internal seed formulas, reconciled every
trajectory's step, task-cost, compute-proxy and event-proxy accounting, and
recomputed all 59 arm summaries and 23 reported paired contrasts. The bootstrap
and seed-t results match the frozen analysis. No models, frozen inputs,
registered sample sizes or comparison definitions changed during this review.

The compressed raw SHA256 is
`51ddaeb9be178ca068408360c530f5ee24df4225aa282b51ef292148ceb6d863`.
There are no missing identities, duplicate identities, seed mismatches or
operational failures, and zero guard fallbacks. The largest reconciled
trajectory accounting residual was 4.44e-16. Every frozen file hash still
matches. Detailed checks and evidence hashes are retained in
`evidence/audits/INDEPENDENT_CONFIRMATION_REVIEW.json`.

### Registered primary results

The following are the three registered primary contrasts, with their
Bonferroni-adjusted 98.333% two-sided bootstrap intervals. All three registered
gates fail; the seed-level t sensitivity checks also fail.

| Contrast | Mean registered-return difference | Adjusted interval | Positive fit means | Required lower bound | Gate |
| --- | ---: | --- | ---: | ---: | --- |
| B - A | +0.017705 | [-0.000029, +0.037513] | 4 / 5 | > 0.005 | Fail |
| D - B | -0.001919 | [-0.012061, +0.004177] | 3 / 5 | > 0.005 | Fail |
| (D - C) - (B - A) | +0.020317 | [-0.015013, +0.076335] | 3 / 5 | > 0 | Fail |

B - A is a favorable point estimate for the full-return controller package in
the clocked model, but it does not clear the registered uncertainty and
practical-effect gate. It is not an isolated causal estimate of planning
horizon: the shared core is optimized with the full head, while the one-step
head is an auxiliary learner. D - B does not establish that the finite
first-passage law improves the matched full controller. Nor does an interval
that includes zero establish equivalence or the absence of all possible gains.

The apparent positive interaction is heterogeneous. Fit 14 contributes
+0.107597; the other four fit contrasts average -0.001503. Five fitted seeds
provide limited evidence about retraining variability. These are conditional
empirical uncertainty summaries on the fixed shared train/dev process and
eight registered nominal presets, not a theorem of coverage or a claim about
open-domain Hepta workloads.

### Secondary patterns, strictly descriptive

All intervals in this subsection are **unadjusted descriptive 95% intervals**.
They do not carry the primary family's multiplicity guarantee and must not be
presented as familywise-confirmed discoveries.

| Contrast | Mean difference | Descriptive interval | Positive fit means | Interpretation |
| --- | ---: | --- | ---: | --- |
| D - direct_Q | -0.003642 | [-0.012319, -0.000137] | 0 / 5 | No demonstrated benefit over the direct public-feature control |
| D - continuous_hard | +0.005288 | [-0.010030, +0.024624] | 2 / 5 | Same hard deployment; unresolved event-law gain |
| D_mean - continuous | +0.004139 | [-0.009764, +0.020481] | 2 / 5 | Same distribution deployment; unresolved gain |
| D - temperature | -0.000567 | [-0.002992, +0.000396] | 3 / 5 | No stable advantage over the matched parameter-count mechanism control |
| D - freeze_content | +0.015342 | [+0.006629, +0.024242] | 5 / 5 | Consistent descriptive contribution of trainable content encoding |
| D - freeze_dynamics | +0.003254 | [-0.006199, +0.014939] | 2 / 5 | No stable contribution established |
| D - D_mean | -0.000315 | [-0.000585, -0.000101] | 0 / 5 | Difference between sampled hard-state and full-mass deployment policies |
| D - D_soft | +0.021871 | [+0.010922, +0.032732] | 5 / 5 | Greedy versus soft action selection with sampled hard latent states |

The D - direct_Q bootstrap interval is negative, but its five-seed t sensitivity
interval is [-0.012384, +0.005100]. The evidence supports reporting the observed
negative direction and lack of established benefit, without silently upgrading
this secondary comparison to a confirmatory superiority claim for direct_Q.

Noise, boundary, reset and recovery freezes also have intervals spanning zero,
with mean differences -0.000042, -0.000014, -0.000738 and +0.000033 respectively.
Their marginal benefits are not established by this experiment. Content
freezing has the clearest descriptive signal, but it concerns the content
encoder on already computed public Bayesian features, not learned perception
from raw evidence. In the aggregate sample, D and freeze_content have the same
answer accuracy (84.0625%); the observed utility difference is associated with
action and decision costs, rather than an average accuracy increase.

The D - D_mean contrast changes how the recurrent internal state is deployed
and can change subsequent actions. D - D_soft instead changes action selection
from the soft training policy to greedy actions while retaining sampled latent
states. Neither quantity should be mislabeled as a generic continuous-training
approximation error. Separately, D - continuous mixes event law and deployment;
the matched-deployment controls above are the more interpretable comparisons.

The three registered stress regimes also do not rescue D - B: mean differences
are -0.003023 (drift), -0.001753 (missing), and -0.001780 (cost shift); each
descriptive interval spans zero. These stress tests are limited to the declared
public parameter transformations, not arbitrary distribution shift.

### Q24 versus floating mass: raw mechanism check

The following deterministic comparisons used the already completed paired raw
records. They are descriptive mechanism checks and did not select a model or
change the study.

| Paired deployment comparison | Complete action-sequence agreement | Quality / task-return agreement | Maximum absolute registered-return difference |
| --- | ---: | ---: | ---: |
| Nominal B_q24 versus B_mean | 2560 / 2560 | 2560 / 2560 | 1.6684e-11 |
| Nominal D_q24 versus D_mean | 2560 / 2560 | 2560 / 2560 | 1.6892e-11 |
| Drift D_q24 versus D_mean | 1280 / 1280 | 1280 / 1280 | 2.0428e-11 |
| Missing D_q24 versus D_mean | 1280 / 1280 | 1280 / 1280 | 1.8371e-11 |
| Cost-shift D_q24 versus D_mean | 1280 / 1280 | 1280 / 1280 | 1.4263e-11 |

Every corresponding final public state also matches. Across all these records,
the largest same-step latent-mass difference is about 1.04e-7, so the mass
vectors are not bit-identical. The tiny registered-return differences arise
from rounding changes to the expected event-fee proxy; they do not reflect
changed answers or action sequences in these samples. This supports Q24
fidelity on the tested paths, not an unrestricted guarantee for thresholds,
long recurrent runs or other tasks.

### Resource boundary and overall decision

The fixed confirmation took 511.301 wall seconds and 511.193 process CPU
seconds. The measured online per-episode CPU means were 4.208 ms for B,
4.821 ms for D, 3.757 ms for continuous, and 2.432 ms for direct_Q. D therefore
has no observed CPU advantage in these comparisons. The partial per-fit epoch
CPU means were 6.158 s, 44.480 s, 6.213 s and 3.227 s respectively; these are
not all-inclusive training costs. Batch receipts separately sum to 2,126.195
CPU seconds and 3,622.734 wall seconds and include the superseded temperature
attempts. Overlapping job wall times are workload sums, not elapsed wall time.
Setup, serialization, shared data/oracle work, development and historical build
costs must retain the inclusions and exclusions declared by their receipts.
The CPU component and inclusive-batch totals overlap and must not be added.

Primary registered_return uses fixed utility coefficients per decision/event.
It is not net utility after measured CPU prices or an energy assessment.
Serialized packet bytes are not physical network savings; actual broker
transport was measured separately. The original task_DP optimizes task_return
without the neural fees, so it must not be called the optimum for
registered_return. A separately labeled joint reference would be needed for
that specific optimality comparison.

The complete result supports retaining this as a reproducible finite-task
research implementation, with working training, independent conditional
checks and artifact-backed integration. It does not support promotion on the
registered efficacy gates, a first-passage superiority claim, reliable
numerical Q calibration, or a hardware/production advantage. The negative and
unresolved results should guide the next experiment rather than be removed by
post-hoc arm selection or additional favorable sampling.

## Subsequent fixed-core optimal-control diagnostic

A separate, explicitly post-freeze deterministic diagnostic now supplies the
joint controller reference mentioned above:
`evidence/JOINT_OPTIMAL_DIAGNOSTIC.json`, SHA256
`53ff67b18189c121363acdca73597f9b5b6b49092a15e6d58733373b3a150d7b`,
with lossless full tables in `evidence/JOINT_OPTIMAL_TABLES.jsonl.gz`.
It covers five modes, five fitted seeds and all eight nominal configurations.
The independent review of its sources, tests, tables and saved occupancy
identities is recorded in
`evidence/audits/INDEPENDENT_JOINT_OPTIMAL_REVIEW.json`.

The reference holds each checkpoint's encoder, drive, Markov grid, noise,
boundary, reset and recovery fixed, and optimizes its action controller under
the same task and neural utility-proxy fees. Its Bellman recursion never reads
the learned Q head. It conditions only on the public sufficient state and the
controller's own realized latent state. Current event fees are charged before
the action phase; Q_after excludes this already incurred fee while including
current compute and all future fees.

I independently verified the 25 table-line and checkpoint hashes, every legal
Q mask and optimal argmax, every saved action-group advantage, and reconstructed
all 200 configuration gaps from the saved deployed-policy occupancy and optimal
action regrets. The largest reconstruction error was 2.74e-16. Four separate
post-freeze tests cover explicit private-world enumeration, STOP causality and
fees, head independence, repeated events, reset/recovery, and agreement with
the frozen policy evaluator. These are separate from the original 45-test
freeze. The largest raw kernel row-mass error was 1.21e-14; the largest change
from deployment clipping/normalization was 7.44e-15. Results are FP64 finite-law
expectations with this stated roundoff, not a continuous-diffusion exactness
certificate.

| Fixed-core mode | Optimal expected registered return | Learned greedy expected return | Optimal minus learned | Wrong group rate among strictly comparable occupied decisions |
| --- | ---: | ---: | ---: | ---: |
| Clocked | 0.653599 | 0.633042 | 0.020557 | 13.2456% |
| First passage | 0.653604 | 0.629975 | 0.023629 | 13.1880% |
| Continuous, hard state deployment | 0.653767 | 0.630536 | 0.023231 | 15.7451% |
| Direct | 0.653767 | 0.633481 | 0.020286 | 13.1868% |
| Event temperature | 0.653595 | 0.630170 | 0.023425 | 12.5351% |

These are known finite-model expectations, not reruns of the 108,800 sampled
confirmation and not new primary confidence intervals. They cannot replace
the frozen primary gates after seeing the results. The optimum is a controller
reference for a fixed cell; it does not optimize the architecture, establish
learned voltage-boundary optimality, or include physical CPU/energy prices.
The gap can reflect controller function-class, approximation and optimization
limitations, and should not be assigned to one cause without additional work.

The action-group metric compares the best REPAIR/STOP action with the best
READ/WAIT action, using a fixed 1e-10 strict-margin tolerance. REPAIR can itself
reveal information. Forced-action and tied states are reported separately,
and within-group READ-versus-WAIT mistakes are not counted as group mistakes.
This categorical controller boundary is distinct from the neuron's voltage
threshold.

One failure is especially transparent: preset 4 has horizon two, no read
budget, and a delayed source that arrives only at tick two. Because STOP uses
the evidence already available before submission, waiting once cannot improve
the eventual answer. The exact after-event STOP value is -0.0075 for every
latent state. All 25 fitted checkpoints nevertheless choose WAIT at every
initial latent state they can reach. This establishes a concrete missed
stop/continue boundary within the declared task. It supplies a useful target
for the next study without suggesting that a post-hoc fix has been tested.

The earlier Qpi audit and this Qstar reference measure different quantities.
The earlier audit uses 40 prefixes from presets 0, 3, 5 and 6, changes the first
action, and then follows the same fitted greedy continuation. This diagnostic
uses all eight configurations and accumulates the gap to optimal subsequent
actions over the full deployed-policy occupancy. Its larger total regret is
therefore not a contradiction of the smaller first-action Qpi regret, nor may
the two be pooled as if they estimated one outcome.
