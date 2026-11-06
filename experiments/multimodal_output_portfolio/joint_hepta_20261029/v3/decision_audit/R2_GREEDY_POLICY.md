# Development greedy policy on the original runner

`r2_greedy_policy.DevelopmentGreedy` connects the existing C-stage `ActionValue`
checkpoint to `dual_runtime.run` through `choose(View)`. It is a development
mechanism, not a qualified R2 strong baseline, EVSI estimator or CE optimizer.
No generator, evaluator, training label, source image bytes or future branch is
read by the policy. Its only online input is the original public `View`.

```python
controller = DevelopmentGreedy(checkpoint, checkpoint_sha256, fit_sha256,
                               Path(output) / "policy")
report = dual_runtime.run(request, backend, controller, output,
                          cpu_tariff=0.02, wall_tariff=0.001)
```

Checkpoint and FIT identities must both be supplied. Actual C loading and source
verification happen lazily inside the first `choose`, so the original runner
charges that work in its controller interval. The trace directory must be new;
any raised initialization or trace-write error permanently fences the instance.
Construct a new instance and trace directory for a new attempt.

## Selection and admissible actions

Every decision lists all seven actions in original `ACTIONS` order. `verify`
requires a current text/image pair. `refine` requires a successful earlier draft
or refinement in public history: the original runner retains `last_image` across
`perceive`/`revise`, even when the current `image_path` is invalidated. Other action
preconditions are unchanged from the original runner.

Every legal, trained action is scored at most once, including STOP. With complete
coverage and no scoring failure, choose the largest strictly positive prediction;
exact ties keep the earlier action in `ACTIONS`. Otherwise choose STOP. Zero is
only the continuation threshold; it is never inserted as an unknown prediction.

Any unknown legal action, failed prediction or exhausted decision budget causes
a conservative STOP fallback, even if another known action scored positively.
Unknown and illegal estimates remain JSON `null`, and failed calls retain their
error and timing. Known candidates are still evaluated within the seven-call
bound, unless the available decision time has expired. This incomplete-coverage
fallback does not claim an argmax over the missing actions. The instance admits
at most 32 decisions. The original runner still checks its deadline after the
controller returns and can refuse dispatch; a trace choice is an intention, not
proof that the action executed.

## Utility and costs

The value returned by C is already a one-step utility increment net of the
historical controller/action CPU and wall intervals and declared action service
fee. D uses that value unchanged. It does not subtract those same terms again or
convert the regression target into population gamma-2 CE.

When storage writes succeed, selected, unselected, unknown and failed scores are
retained in a new `policy/decision-NNN.json`, with public View identity and per-call
CPU/wall time. A trace-write failure or cancellation prevents dispatch and fences
the instance. Its in-memory row and original runner failure remain, but a missing
disk decision is not a complete durable trace.
`POLICY.json` pins C, the runtime/observer, D, checkpoint and FIT identities. All
these diagnostic intervals are subsets of the original runner's inclusive
controller interval; do not add them to its bill. The final trace write is charged
by the runner but excluded from its own pre-write diagnostic timer. Imports,
constructor/orchestration, energy, physical I/O and historical costs retain their
explicit outer or unknown boundaries. No preemptive deadline guarantee is added.

## Controlled validation and remaining qualification

Six focused integration tests passed on the retained `greedy-attempt1` run.
The shared fixture used the existing capture reader and 600 actual SGD updates;
its seven-action checkpoint was copied with only its FIT receipt into a new
process. The unchanged runner then executed **draft, text, stop**, retained a
complete synthetic pair, and made 5, 6 and 7 candidate predictions respectively.
Every recorded score equals C's original prediction, without a second cost
subtraction. A separate partial-coverage fit verifies that a known positive score
cannot conceal unknown legal actions. Fault-injected tests separately cover
legality, ties, failed scores, deadline rejection, wrong FIT identity and fencing;
their `FAULT.json` records distinguish them from the unpatched learned canary.

The independent cold-process review reused a different existing 160-update C
fixture. Its original runner executed **perceive, text, draft, verify**, with four
decisions and 22 predictions, and ended **incomplete** at its declared horizon.
It did not execute STOP or deliver a final pair. That bounded unfinished outcome
is retained alongside the passing prediction/reload checks; it was not rerun or
retuned to obtain delivery.

The fixture backend makes zero real-model calls. Its utility labels are explicitly
synthetic presence controls, with no independent semantic evaluation. The actual
canary remains `pending_independent_evaluation`; delivery is an execution result.
Confirmation still needs new source-separated transitions, independently held
development utility, complete/calibrated cost and service mapping, validated
coverage/generalization, and the preregistered baseline selection/evaluation.
Current versus historical decision-cost calibration is unestablished. The C
feature representation and all scientific gates in `R2_ACTION_VALUE.md` remain
unchanged. This slice runs no four-arm experiment and changes no A/C/SD source.
