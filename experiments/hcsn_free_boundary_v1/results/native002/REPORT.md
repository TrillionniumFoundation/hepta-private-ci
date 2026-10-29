# Trained checkpoint and native owner evaluation: native002

## Result

**The continuous signals reach the real native owner, but the predeclared
maxout controller does not improve task utility on this cohort.** It chooses
KEEP on every observation and purchases all 32 observations in all 32 episodes.
The continuation-only control does the same. Their predictions and read counts
equal the `read_all` reference, with additional native execution cost.

The ordinary affine controller stops in 28 of 32 episodes. It uses fewer reads
but loses substantial accuracy. It has greater read-only utility at the two
higher declared read prices. No controller was fitted or changed after these
outcomes, and the experiment has not established an optimal stopping policy.

## Frozen inputs and execution

- Source freeze: `caa1a503288d4986bf2f0bc3608bc211a12e221a45c822bfbd19fdacce953bc3`.
- Training run: `study001/runs/mnist/free_dual/9101`; selected LR 0.003,
  update 134, width 32, depth 1.
- Selected numeric checkpoint SHA-256:
  `069ecacf9fa21cb8e4360893a2d6aa68621a1860d4baa6b9ae1c7343df289cfd`.
- Dataset SHA-256:
  `43967ccabb05540a3b6c831f3737ece02d2ddea16c79e139b46dcb14fd2a4895`.
- The first 32 test episodes were specified before native outcomes. This is a
  descriptive cohort from one checkpoint, not the full 512-episode task result
  and not an independent replication across training seeds.
- Execution used one Python process and one Torch thread, plus the unchanged
  native child executable. The wider study had three concurrent training
  workers; these timings are not isolated microbenchmarks.

All 38 source-freeze entries matched before and after execution. The driver
completed successfully without modifying source, model weights, controller
coefficients, native guards, or authority. All outcomes are retained.

## Accuracy, reads, and utility

Accuracy and read decisions were identical across price scenarios. Read price
is an accounting input to these policies; their actions do not adapt to it.
Utility below is `correctness - read_price * actual_reads`, averaged over the
32 episodes. It excludes the separately reported CPU scenario charge.

| Policy or reference | Correct / 32 | Accuracy | Mean reads | Utility at 0.005 | Utility at 0.02 | Utility at 0.05 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| causal_maxout | 19 | 59.375% | 32 | 0.433750 | -0.046250 | -1.006250 |
| continuation_only | 19 | 59.375% | 32 | 0.433750 | -0.046250 | -1.006250 |
| ordinary_affine | 8 | 25.000% | 11.8125 | 0.190938 | 0.013750 | -0.340625 |
| read_all | 19 | 59.375% | 32 | 0.433750 | -0.046250 | -1.006250 |
| fixed8 | 1 | 3.125% | 8 | -0.008750 | -0.128750 | -0.368750 |
| fixed16 | 5 | 15.625% | 16 | 0.076250 | -0.163750 | -0.643750 |
| fixed24 | 9 | 28.125% | 24 | 0.161250 | -0.198750 | -0.918750 |

Every reference executes its own actual sequence of `model.step` calls. No
prefix predictions are precomputed and then retrospectively selected. Native
STOP immediately exits the corresponding model loop. Horizon completion is
recorded as `finite_horizon`, not as a native STOP.

### Why the maxout controller keeps reading

Inspection of all 1,024 maxout owner ticks at the middle declared price finds
the margin coordinate, index 2, as the sole surviving top-k coordinate on
every tick. Its normalized margin ranges from 0.739379 to 0.999963. All 1,024
actions are KEEP. In the continuation-only control, the positive continuation
coordinate wins all 1,024 ticks; its normalized value ranges from 0.113488 to
0.620427. The ordinary affine control produces 350 KEEP and 28 STOP actions.

The separate `native001` interventions show that each of the four channels can
causally change an action from an identical durable prefix. They do not show
that all four channels materially influence decisions on this trained cohort.
Here the maxout controller is dominated by margin and fails to stop. This
distinction separates API causality from useful task behavior.

## Actual execution and CPU scenarios

Per-episode CPU below includes each policy's Python execution loop and its exact
native-child CPU. Python time already includes model time, so it is not added a
second time. Fixed references do not invoke the native owner.

| Policy or reference | CPU ms/episode at price 0.005 | At 0.02 | At 0.05 |
| --- | ---: | ---: | ---: |
| causal_maxout | 143.245 | 142.756 | 132.379 |
| continuation_only | 156.899 | 136.937 | 135.029 |
| ordinary_affine | 65.328 | 69.652 | 51.493 |
| read_all | 99.106 | 93.803 | 100.589 |
| fixed8 | 26.828 | 26.843 | 20.267 |
| fixed16 | 52.154 | 48.353 | 49.043 |
| fixed24 | 77.200 | 74.063 | 72.967 |

These are repeated executions of the same observations, not additional
independent accuracy samples. Timing differences across price runs reflect
measurement conditions rather than price-dependent computation.

The complete evaluation executes 288 native policy episodes and 384 fixed
reference episodes, plus three separate recovery-verification episodes. Across
all these executions it performs 15,029 actual model steps, 7,349 native owner
ticks, 7,355 native kernels including recovery replay, and 7,352 NDU calls
including recovery validation. The 85 reported native rejections are the
intentional post-STOP guard probes; no unexpected native failure occurred.

Measured evaluation costs are:

| Cost | Measured value | Scope |
| --- | ---: | --- |
| Driver Python CPU | 52.946036 s | From entering `run_study` to final accounting cutoff |
| Exact native-child CPU | 4.694132 s | `wait4` receipts for all native child PIDs |
| Elapsed evaluation wall time | 71.137529 s | Driver measurement, with concurrent training workers |
| Shared setup/source/report-preparation CPU | 0.442978 s | Subset of Python CPU outside per-policy loops |
| Complete training-child CPU charged | 46.474767 s | Includes import/startup, both LRs, validation, saving and heldout evaluation |
| Summary-derived search CPU | 43.499653 s | Retained detail; not substituted for complete child cost |

The native driver's own Python/Torch module imports precede its timed
`run_study` region. Final self-serialization of the two summary files follows
the accounting cutoff. These small boundary costs are not measured by the
driver's parent-CPU field; the training charge has a different, complete
process scope.

`COST_SCENARIOS.json` contains all 252 declared combinations: seven policies,
three read prices, CPU prices 0 / 0.0001 / 0.001 / 0.01 utility units per CPU
second, and amortization populations 1,000 / 10,000 / 100,000 episodes. Each
standalone policy scenario pays:

\[
\text{accuracy} - p\,\text{mean reads}
-\lambda\left(
\frac{46.474767}{N}
+\text{measured policy CPU per episode}
+\frac{\text{policy recovery-verification CPU}}{N}
+\frac{0.442977502}{N}\right).
\]

All 252 rows were independently recomputed from the saved ledger and agree.
The complete shared setup charge is conservatively assigned to each separate
deployment scenario; different policy scenarios must not then be summed
together. These are hypothetical utility conversions, not measured financial
prices, joules, or production deployment costs.

## Recovery and limits

All three policies continue after the first observation of the predeclared
recovery episode, so all three exercise a saved tensor state, a fresh neural
model object, a new native child, and durable owner resume. Their raw signals,
predictions, Q24 activations, NDU numerical scores, tie/frontier outputs, and
actions match uninterrupted execution. Context-dependent digests differ
between the separate price identities and are explicitly excluded from this
cross-scenario numerical comparison. `native001` separately compares identical
context checkpoint/digest identities.

Full recovery-verification CPU charges are 0.151187 s for maxout, 0.172596 s
for continuation-only, and 0.075560 s for ordinary affine. They include repeated
prefix/suffix computation and are not estimates of pure restart overhead. The
Python interpreter is unchanged; true fresh-interpreter neural recovery is
separate evidence in `scaling002`.

The owner remains `DENY_ALL`. This study does not establish a trained native
head, task-level Bellman optimality, calibrated early-stopping confidence,
energy savings, natural multimodal performance, or an advantage over ordinary
sequence architectures. It establishes real execution and accounting while
preserving the negative stopping result for the chosen maxout policy.

Primary evidence is `SUMMARY.json`, `COST_SCENARIOS.json`, `INPUT_IDENTITY.json`,
the three per-price `LEDGER.json` files, every individual episode receipt, and
the original native journals/witnesses. Summary SHA-256:
`17a9a8bd3a7b880382ed261b8cf1c1e5c423b4ea29479162d852171ecaa34e56`.
