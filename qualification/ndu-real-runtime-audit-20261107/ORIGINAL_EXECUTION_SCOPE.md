# Executed scope and interpretation boundary

Recorded during tuning, before the development pilot and its analysis. This is
a source-based clarification of the frozen execution, not a change to its
models, cohorts, endpoints, selection rules, or attempt inventory.

## What the real pilot executes

The locked plan `139a8c0ce912f4eadb62d80463674ac7295b04fad4c455296654ec7630946880`
executes a receipt-field and source-image-region portfolio. Real Tesseract OCR
reads released pixels; actual neural checkpoints select text candidates and
predict region adjustments. Actual PNG crops are produced and independently
scored against source pixels. All actor access to private references is denied
by the tested Linux boundary. The external scorer runs after the actor exits.

The model has 15,132 stored parameters: 8,093 content parameters and 7,039
auxiliary parameters. Four independently initialized fits share the same
prospectively collected real training observations. All 152 grid jobs and both
collector jobs have original execution receipts. The 256 tuning profiles map
to the 152 grid checkpoints; profile count is not an independent-fit count.

The 24 profiles per fit comprise both regimes of A/B/C/D and initial, fixed,
VOI, and MPC controls on both cores. Light uses a learned router; NDU uses
bounded nested entropic backups; VOI uses the same fitted forecast for one-step
decisions; MPC evaluates bounded open-loop plans and replans after the next
actual observation. The live controllers cannot read later evaluator outcomes.
Three locked trials per active arm provide a finite tuning opportunity. Fixed
schedule and learning-rate candidates are paired by trial index, not expanded
into a nine-way Cartesian search. No claim is made that this finite grid is the
best possible fixed, VOI, or MPC implementation.

## Hepta mechanism scope

The exact backbone is `hepta.output-portfolio.interval-end-mean.v1` from
`experiments/multimodal_output_portfolio/joint_hepta_20261029/hepta_core.py`,
SHA-256 `54c2e9724f6cb924582451bea907d671fe510963879117dd5f00cf4e95f1e978`.
Its documented numerical model uses frozen-interval Brownian first-passage
probability and mean propagation with reset at interval end. It does not
implement sampled spikes, continuous renewal, a refractory timer, or an
endogenous value boundary.

The deployed `ReceiptPortfolioModel.content` creates fresh core state and calls
`core.step(..., 0.5)` once per candidate encoding. It does not carry the returned
voltage, event, adaptation, or semantic state into the next action's encoding.
Initial voltage, previous event, and adaptation are zero. Thus recurrence
through recovery, regeneration, and adaptation history is not exercised by
this task adapter. Merely storing these tensors or parameters does not establish
that their mechanisms contributed to the observed output.

Accordingly, D-B identifies the incremental effect of the executed dual
first-passage gate profile relative to its ordinary sigmoid-gate ablation under
the same deployed NDU. It is not evidence for every Hepta mechanism. B-A, D-C,
and their interaction remain required and are reported regardless of direction.
Neither a favorable D-A nor a favorable single contrast closes this boundary.
The pilot does not claim the legacy exact-active-capacity qualification gate;
stored, trainable, and functionally active capacity must not be conflated.

## Task and evaluation scope

The five families are constructed workflows on independently grouped real
SROIE receipt scans in one domain. They are not five unrelated data domains.
Some workflow inputs deliberately supply an already-correct committed handoff;
that handoff comes from the registered material and is not claimed as a
previous model's generated output. Image delivery is source-pixel editing/crop,
not unrestricted image synthesis. Pretraining exposure of the public source
to Tesseract or other preexisting components remains unknown.

Retention tests the registered receipt-field capability. A separate incumbent
panel actually executes the same-core pretrained decoder with WRITE_TEXT then
STOP. It does not measure all historical Hepta language, image, audio, or video
abilities. Four independent training fits support a development pilot; episode
count does not turn them into thousands of independent training repetitions.

The locked deterministic scorer and OS actor boundary establish a reproducible
evaluation implementation and actual actor information isolation. They do not
create three independently controlled native Generator/Observer/Evaluator
authorities. The same researcher selecting and implementing a rubric is not
rebranded as an externally appointed independent evaluator.

## Cost, confirmation, and native scope

The net objective subtracts 0.01 times measured deployment wall seconds. This
is a prospective research latency preference, not an owner-approved monetary
or energy conversion. Energy, provider charges, and unmeasured historical
environment work stay unknown. Research includes every candidate and original
failed attempt; nested component meters are not added again to their enclosing
training or episode cost.

The study is a development pilot. Confirmation and retention-test references
remain denied; 67 unexposed confirmation source groups and 27 retention-test
groups are future material capacity, not executed confirmation sample sizes.
Actual variance, the predeclared alternatives, multiplicity, independent
training repeats, and these capacities determine a provisional next study.

The native research runner can bind actual model bytes, execute actual incumbent
tasks, and record/replay a Cell journal. Importing all historical attempts does
not retroactively make them native-admitted original attempts. A separate
same-incumbent inference is not formal learning-cycle FinalUse consumption.
Missing protected authority and signed owner admission remain explicit blockers.

The permitted study outcome is Inconclusive or Failed. The implementation of an
Adoptable/NoUpdate/Inconclusive/Failed contract does not authorize an update.
NoUpdate remains a finite-contract result, never a zero-delta V5 submission or
an exception to no-op rejection and positive-gain rules.
