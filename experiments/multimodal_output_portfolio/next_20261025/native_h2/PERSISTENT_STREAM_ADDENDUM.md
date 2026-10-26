# Persistent owner state and inference boundaries

This is a read-only interpretation of the already completed H2 execution and
the sealed H1 source. It changes no source used for execution, protocol, model,
score, action, cost, interval or gate. No new source or model run was opened.

## H2: actual continuity, not independent owner restarts

In [run_v2.py](run_v2.py), `run` constructs one `Native` owner for each policy
before its `for case in range(args.count)` loop. Both recovery paths resume that
policy's same state directory. Only the generator's public state is initialized
for each episode. Owners close after the entire 128-pair panel.

[online_bootstrap.rs](online_bootstrap.rs) initializes the zero-prior NDU
projection and native journal only when `resume` is false. Resume restores the
original checkpoint and control history. [episodes.rs](episodes.rs) closes or
replaces pending/continuation identities; it does not reset the owner, NDU
projection, temporal state, activity, thresholds or eligibility.

Every candidate in [online.rs](online.rs) executes a new original-owner tick
against the preceding checkpoint. The original `SparseJournal::commit` invokes
`sparse_tick` with its current checkpoint. That function reads prior temporal,
activity, threshold and eligibility vectors. The original `calibrate` function
checks active fraction, projection count and the sequence window, and the
runtime also checks measured execution resources. The `AgentdNeuronOwner`
composition is an adapter around that runtime and inference control; it has no
separate metabolic subsystem in this execution.

The byte-bound [stream reconciliation](evidence/confirm-001-stream-state-addendum.json)
checks the saved journals and public rollouts. Each policy has one bootstrap,
256 episodes and 63 transitions between writer groups. Every logged step uses
the last observed modulator, including across episode and writer boundaries.
Native sequences are continuous: 1–1,800 for NDU and 1–1,740 for correctness.
The source files and original journal SHA values are included in that addendum.

The separate [independent stream review](CONTROL_STREAM_INFERENCE_REVIEW.md)
reached the same lifecycle and inference-boundary conclusions from the executed
source without running a model or changing the original intervals.

Therefore the original writer-bootstrap endpoints are **nominal intervals for
the fixed observed ordered streams**. Writer identities are distinct sources,
but they are not independently restarted native policy experiments. Resampling
their realized rows does not rerun the owner under the resampled history. No
stream-order invariance, absence of all interference, independent repetition of
the full policy stream, or population interval coverage was established. The
observed +5.613517 ms request difference is retained; its nominal positive
interval is not a universal causal-cost certificate.

## Projection binding and numerical feedback are separate

In [online_port.rs](online_port.rs), the numerical drive has its first coordinate
equal to one Q24 unit and its other 32 coordinates equal to zero for every
candidate. The teacher moments and correctness probabilities are computed from
the current 103 public feature coordinates. The port does not read a numerical
utility or modulator when computing those heads. The NDU modulator digest binds
the tick, receipt and journal identity; no plasticity update or numerical
modulator-to-head path is called here.

Actual generated content does enter the next H1 decision through the public
frame and encoder. That causal path is exercised, and the public-sensor outcome
is durably projected before the following tick. These facts support actual
execution and recovery, but persistence of the projection digest by itself does
not establish a numerical NDU-modulation benefit or show that a previous writer's
public utility changes the next writer's predicted moments.

The existing logs do show that actual resource conditions can affect admission.
The complete [single-tick census](evidence/confirm-001-individual-tick-resource-census.json)
finds one exception among 3,540 candidates: NDU sequence 546, case 38, H1 `stop`,
has execution time 60,038 microseconds and is rejected by the unchanged
8,000-microsecond single-tick limit despite confidence 0.953893. No other recorded
candidate exceeds the five checked runtime/owner resource ceilings. Four
measured process p95/p99 summaries nevertheless pass; two observation-only
recovery processes are N/A. The original summary, outlier, rejection and complete
cost remain retained. This is not evidence that sparse-state carryover caused
that particular delay or that it explains the quality result.

## The original Q backup does not solve the new constrained problem

The preserved teacher's `abc_next/value.py::train` forms H2 targets from a
source-out-of-fold minimum of conditional H1 predictions on actual child states.
It excludes H1 semantic refinement by its original dominance rule. It does not
include the later correctness admission head, original-owner future resource
failures, continuing owner state or this experiment's terminal rejection utility
of -1 in that backup. The deployed code takes an argmin of those same moments on
the currently admitted set at each step.

Exact value parity therefore establishes execution of the specified masked
teacher, not an exact Bellman solution for the new feasibility constraints.
It does not transfer the positive unrestricted-teacher control result or certify
long-horizon optimal portfolio choice. This limitation was not repaired by
changing the teacher or thresholds after the native result; the whole original
comparison remains intact.

## Separate annotation of the already sealed H1 study

The earlier [H1 runner](../native/run.py) also creates each policy's owner before
its case loop, then reuses the policy state directory across the 96 pairs and
both views. Its restarts use `resume`, not a per-case new runtime. The H1
[bootstrap](../native/online_bootstrap.rs), [controller](../native/online.rs) and
[value port](../native/online_port.rs) have the same native persistence and
constant-drive numerical-head distinction. Their current bytes were compared
with the original H1 execution protocol pins; all four match, as recorded in
[the exact source-pin check](review/HISTORICAL_H1_STREAM_SOURCE_PINS.json). No H1 raw data or
archived report was changed or rerun.

Accordingly, H1's previously reported writer-bootstrap intervals also require
the fixed-ordered-stream, nominal interpretation rather than independent owner
trial coverage. H1's old observer used private audit truth before subsequent
requests; that earlier boundary remains part of its preserved evidence and must
not be replaced retrospectively with H2's public-only observer claim. This
addendum neither grants H1 new qualification nor alters its unsuccessful native
effectiveness finding.
