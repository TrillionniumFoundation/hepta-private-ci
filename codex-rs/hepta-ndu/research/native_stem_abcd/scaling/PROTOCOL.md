# R8: parameter scaling and time to fixed quality

Parent PR #1826, exact fd83665f764ea654f260090712d8bec370ec123a.
This protocol is pushed before the R8 efficacy sweep. R7 results informed the
quality target; this is an exploratory follow-on, not externally preregistered
or blinded confirmation. No prior source, result, native contract, CURRENT or
main change. Execution is in the assistant CPU container, not a native device.

## Fixed population and model family

Retain R5/R6/R7's known affine plant, observed preference transition, entropic
recursion, quartic terminal cost and continuous uniform initial population:
h in [-.25,.25]^2, x in [-.8,.8]^2, two equiprobable initial regimes. All future
branches are enumerated. Train on the unchanged positive CC5 tensor rule.

Only widen the shared 4->w->2 tanh subnetwork in the forward feedback policy.
The six 2x4 layer/regime matrices remain trainable; total parameters =50+7w.
Widths 4,16,64,256 give 78,162,498,1842 parameters. No dummy parameters. This
scales representation width, NOT physical-state dimension, task difficulty,
sequence length, or actual LLM size. Known dynamics/preference laws are not
learned. There is no pretrained encoder or optimal-action training label.

Initialization uses the inherited random law with output weights scaled by
sqrt(4/w) to avoid a trivially growing initial output variance. At width4 the
weights and computation must match R7 exactly. Within EACH width/seed, Adam,
L-BFGS, explicit-adjoint matrix-free trust-ncg and ordinary-AD matrix-free
trust-ncg receive byte-identical initial weights, points, weights and objective.
Different widths do NOT have identical initial functions or function classes.
Three seeds 11/23/47, four widths and four solvers: 48 fresh-process fits.
Method order rotates by seed/width. No tuning on R8 output, restart or warm start.

## Primary: observed time to a common numerical quality gate

Fixed cost target tau=.04850, chosen from the already disclosed R7 range, NOT
from an R8 run. Fixed integration-consistency target epsilon=1e-6.
A monitored accepted candidate qualifies when BOTH J_CC5 and J_CC9 <=tau and
abs(J_CC9-J_CC5)<=epsilon. This is a common stopping/monitoring criterion on the
known population, NOT an independent held-out generalization score or a proof
of a uniform quadrature error bound. A global optimum is not known.

Every method checks its initial candidate, then its latest accepted candidate
at the first completed optimizer update at least .5 wall seconds after the
last completed check. A final check occurs on normal convergence/budget exit.
The full check time, initial generation, rule construction, optimizer setup,
HVP/cache work, rejected trials and checkpoint bookkeeping count in elapsed
wall/CPU time from entry to fit. Imports/process startup are also reported
separately in spawn-to-exit totals. No unmetered prewarming of an efficacy fit.

Stop at the first completed qualifying check if it finishes within the 12-second
wall cap. A check or nonpreemptible operation may overshoot; report actual time.
A check finishing after the cap is NOT a within-budget success. Incomplete
attempts retain the last accepted weights, not a line-search trial. Censored
runs retain null time-to-quality and an explicit reason; never impute the cap
as a success time or average only easy successful runs without counts.

Time means FIRST OBSERVED qualifying check. Discrete polling can miss an earlier
transient crossing; do not call the observation an exact first hitting time.
Do not infer a hitting-time interval from a failed preceding check for a
nonmonotone optimizer. Compare success counts and all paired observed times at
each width; report median times among successes WITH denominators. Main contrast
is explicit matrix-free C versus Adam; L-BFGS and AD are mandatory strong controls.

Adam lr=.015; L-BFGS-B gtol=1e-9, ftol=1e-14, maxls=40; trust-ncg gtol=1e-9,
initial radius1, maximum radius1000, eta=.15. No full Hessian in matrix-free fits.
Cached derivative graphs invalidate on every parameter change. Every width
must have explicit-gradient/AD, HVP/finite-difference and nonzero-gradient checks.

## Post-stop evaluation and evidence

Freeze all chosen weights and monitor checkpoints before independent scoring.
Every candidate, successful or censored, gets CC17, GL9 and four new scrambled
Sobol1024 evaluations (seeds 2026101481..84) on the same population. Also retain
doubled-amplitude, changed-dynamics and declared modulo-three horizon4 panels.
No post-stop evaluation is allowed to resume or replace a fitted model.
Refinement agreement and scramble dispersion are numerical diagnostics, not
uniform error certificates or guaranteed confidence intervals. Repeated nodes,
seeds and readouts are not independent empirical tasks.

Save initial/final tensors, every monitor checkpoint, full gate history, source
hashes, law arrays, prediction arrays, actual CPU/wall and fit-phase peak process
RSS. Monitor work is reported separately but never subtracted from the primary
time. Total-process peak memory also includes evaluation and is kept separate.
RSS includes runtime allocation. HVP counts are not exact FLOP equivalents.
Energy, complete FLOPs and GPU measurements remain null. No full physical TCO,
production acceptance, global optimum, universal FBSDE/viscosity theorem or
Transformer/LLM superiority follows from this numerical scaling study.

A read-only audit reconstructs the law and model, verifies all 48 identities,
initial bytes, monitor predicates and chosen checkpoint, independently replays
reported gates/final predictions, and rejects missing rows, altered tensors,
rehashed false costs, integration weights or success timing. Failures are
retained and outputs are create-only. Source/mechanism development tests are
separate costs and not efficacy trials.

Primary implementation references (not efficacy sources):
https://docs.scipy.org/doc/scipy-1.17.0/reference/optimize.minimize-trustncg.html
https://docs.pytorch.org/docs/2.10/generated/torch.autograd.grad.html
