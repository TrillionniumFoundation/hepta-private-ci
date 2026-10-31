# Registered secondary original-Hepta feedback bridge

This experiment checks whether the analytic terminal operator actually changes
the original sparse neuron's state and subsequent choice. It is separate from
the three primary task comparisons. All five arms, including unsuccessful ones,
are retained. It is a synthetic numerical self-evaluation task with actual text
and PNG delivery, not an experiment on natural-language or image generation.

## Task law and observation boundary

For each independent trajectory, draw a draft `A ~ Normal(0, 1)`, an independent
hidden error `E ~ Normal(0, 0.8^2)`, and a private target `Y = A + E`. The public
self-evaluation is `S = Y + epsilon`, with independent
`epsilon ~ Normal(0, 0.6^2)`. Seeds are registered by training run:

| Split | Data seed | Independent trajectories per run |
| --- | --- | ---: |
| Training | `90000 + run_seed` | 384 |
| Development | `100000 + run_seed` | 128 |
| Confirmation | `110000 + run_seed` | 256 |

The five run seeds are 11, 23, 37, 53, 71. Models freeze after training and
development, before any confirmation trajectory is generated or evaluated.

Each arm delivers `A` as actual text and PNG and reopens both. It then acquires
`S` through the public observation file and computes `R = S - readback(A)`.
That residual is itself written to text and PNG and reopened. Only this final
residual readback and a digest of its actual text/PNG bytes supply feedback to
the native bridge. The private target does not enter that bridge or its head.

The two choices are stop and repair. Stop redelivers the initial readback.
Repair delivers `readback(A) + kappa * readback(R)` and pays 0.12. The selected
final output is again reopened before the private target is accessed for
scoring. Actual utility is

`1 - (final_readback - Y)^2 - 0.12 * I(repair)`.

The repair formula uses only acquired information. It is not an oracle repair
that directly reads `Y`. The synthetic action charge enters utility; measured
execution and archive costs are reported separately rather than assigned an
arbitrary conversion into utility units.

## Training and arms

Using training readbacks and supervised targets only, estimate

`kappa = clip(sum(E*R) / sum(R^2), 0, 1)`

and `conditional_variance = max(mean((E - kappa*R)^2), 1e-6)`.
The prior mean of the error is fixed at zero by the registered task. These
estimated Gaussian posterior parameters are shared across every arm, including
the common repair formula. No arm receives private true parameters at test time.

The numeric scaling constant is three training standard deviations of `R`,
with a positive floor. The encodings are registered as follows:

| Arm | Feedback and state used by the learned head |
| --- | --- |
| `numeric` | Clip `R / (3 * training_std(R))` to [-1, 1], then original two ticks |
| `analytic_probability` | Shared `event_probs(kappa*R, conditional_variance, 0, 0)`; send `p(call)-p(put)` into the original two ticks |
| `zero` | Zero numeric feedback; preserve the original constant drive and two ticks |
| `state_reset` | Analytic evidence on tick one, then reset all state before the zero-input second tick |
| `matched_history` | The same acquired residual in a 21-dimensional polynomial/RBF history representation |

Both analytic thresholds are zero, so the neutral interval is empty. The call
and put channels are complementary terminal directions of the residual under
the learned Gaussian law. They are not first-passage events or discounted
financial prices. Their difference is a deterministic scalar re-encoding, not
a new information source. Before numerical saturation it is monotone; Q24
quantization and numeric clipping can lose information. This experiment cannot
establish a new neural function class merely from this transformation.

For each native arm, round the evidence to Q24 using nearest/ties-to-even and
execute the pinned original `sparse_tick` twice. The second tick receives ten
zero drive coordinates. The only head features are an intercept and the ten
activation plus ten eligibility coordinates from that second tick. Checkpoint
continuity, the reset intervention, `DENY_ALL`, and the calibration-required
receipt are validated. No residual bypass enters this native-state head.

The history arm uses `[1, z, z^2, z^3]` and 17 Gaussian radial basis functions,
where `z = R / training_std(R)`. Centers are the training z quantiles from 0.05
through 0.95, inclusive; RBF bandwidth is 0.5. The representation has 21
coordinates and receives the same acquired feedback. It is an explicitly
stronger nonlinear information reference, not a claim that the two feature
maps have identical expressive capacity.

All arms train a separate 21-coefficient linear logistic head. Supervised labels
are whether the repair's actual squared-error reduction exceeds its cost. For
both training and development, the potential repair is actually delivered and
reopened to construct these labels. The numerical improvement is retained,
including all negative improvements. This is permitted offline supervision;
online confirmation exposes the private target only after final delivery.

Every head starts at zero and receives 600 full-batch gradient steps at learning
rate 0.15. Candidate L2 strengths are 0.001, 0.01, 0.1; the intercept is not
penalized. Feature centering/scaling is fitted on training data and folded back
into the stored 21 raw-feature coefficients. Development probability thresholds
are 0.0, 0.1, ..., 1.0; the endpoints force always-repair and always-stop.
The 33 candidate pairs are selected by development paired-label mean utility,
then fewer repairs, stronger L2, and a larger threshold on exact ties. This
classification objective plus development utility selection is a specified
heuristic, not a proof of optimal expected-utility control.

Training evidence includes initial/final parameter hashes, parameter changes,
losses, feature/label hashes, every candidate score, and the number of varying
state coordinates. In particular, `zero` and `state_reset` should have zero
varying state coordinates. The original sparse kernel parameters are fixed;
the input calibration and heads are learned.

## Evidence, replay, and costs

`feedback_chain.py` exposes `build_feedback_dataset`, `fit_feedback_models`, and
`evaluate_feedback_chain`. Model and receipt results contain only JSON-native
values. The driver separately retains datasets and the model files in the
freeze manifest. Each online record contains the actual native receipts,
readback digests, head input/score/threshold, selected action, final output,
private scoring target, utility, and causal timestamps.

Training and evaluation report actual adapter request/tick count deltas, native
kernel nanoseconds, adapter round-trip nanoseconds, Python-process CPU time,
and full phase wall time. The Python CPU measurement does not include native
subprocess CPU. Archive verification/compression time is separately recorded
and included in phase wall time. Native tick time and adapter round-trip time
overlap and must not be added as disjoint costs.

Each acquired-file tree contains an `ARCHIVE_MANIFEST.json` with the SHA256 and
size of every other file, including transport receipts. Before deleting the
temporary tree, the archive is reopened and every file, including the manifest,
is checked against its source digest and size. Missing, duplicate, unexpected,
or non-regular files abort removal. Archives, per-file manifests, receipt hashes,
all targets/outcomes and native states remain available for independent replay.

State-value disagreements and actual action disagreements are reported against
the numeric arm. A changed state does not by itself establish improved utility;
action changes, paired utility and the history reference must be examined
separately. These secondary observations do not alter the primary three-test
superiority gate. No production-owner admission or end-to-end kernel training
is claimed, and using PNG to carry exact numerical values does not establish
natural multimodal learning or generalization.
