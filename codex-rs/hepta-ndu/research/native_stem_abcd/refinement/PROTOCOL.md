# R10: staged quadrature and monitor-budget allocation

Parent PR #1871, exact `33b73a48006a1a9d13c862d424322d112f79bc60`.
This protocol is pushed before any R10 efficacy run. It is an exploratory
follow-on informed by R9, not externally preregistered or independently blinded.
All prior source, outcomes, native contracts, CURRENT and selected models remain
unchanged.

## Fixed scientific object

Retain the same continuous uniform initial law, known affine plant, observed
Markov preference transition, entropic recursion, quartic terminal cost and
inherited nonlinear forward Stem. Width64/256 means 498/1842 actual trainable
parameters. The physical state, task, horizon and data-generating law are not
scaled. There is no pretrained encoder, optimal-action label, unknown-dynamics
learning, language model or continuous-time viscosity claim.

Within each width/seed, all solvers and allocation conditions start from exactly
identical parameter bytes. Solvers remain Adam, L-BFGS-B, explicit-adjoint
matrix-free trust-ncg and ordinary-AD matrix-free trust-ncg. Hyperparameters are
unchanged from R9. No warm start from an earlier experiment or post-hoc restart.

## Two allocation interventions

Full factorial:

- widths 64 and 256;
- seeds 11, 23 and 47;
- four solvers;
- training schedule `fixed_gl5` or `stage_gl3_gl5`;
- monitoring allocation `frequent_lazy` or `terminal_only`.

Total: 96 fresh-process fits. Order rotates by width/seed.

`fixed_gl5` uses the 5-point positive Gauss-Legendre tensor rule throughout.
`stage_gl3_gl5` uses the 3-point positive Gauss-Legendre tensor rule until four
wall seconds of the metered fitting phase, then restarts the same optimizer class
from the last accepted weights on GL5 for the remaining fitting budget. The
restart, rule construction and cache invalidation are charged. GL3 has 81 nodes,
GL5 has 625. This intervention reallocates finite compute; it does not alter the
ideal continuous population or claim that GL3 is accurate enough by itself.

`frequent_lazy` evaluates the unchanged R9 gate at the initial candidate and
after accepted updates/callbacks at a 0.5-second completed-check cadence. It uses
the exact short-circuit: compute CC5 first and skip CC9 only when CC5 already
makes the original predicate false. Unlike R9, intermediate qualification is
recorded but DOES NOT stop fitting.

`terminal_only` performs no intermediate gate evaluation. Both monitor policies
receive the same 12-second fitting budget, which includes optimizer setup,
training-rule construction, gradients, HVPs, line-search/trust work, switching
and all intermediate monitoring. After the fitting budget, weights are frozen.
Every run then receives one mandatory FULL terminal qualification outside the
fitting budget. Its wall/CPU/RSS cost is measured separately and included in
whole-process cost, but it cannot change or resume fitting.

This endpoint design intentionally changes the R8/R9 first-observed-time question.
R10 asks whether reallocating the SAME fitting budget changes final candidate
quality. It does not report a time-to-quality speedup. Intermediate gate hits are
exploratory trajectory records only and are not used for checkpoint selection.
The final selected tensor is always the latest accepted tensor at fitting-budget
exit.

## Unchanged quality target

The final gate is exactly:

    max(J_CC5, J_CC9) <= 0.04850
    and abs(J_CC9 - J_CC5) <= 1e-6.

No GL5 substitution, threshold relaxation, integration penalty, favorable
checkpoint selection, after-the-fact stopping or CC17-based admission. Final
terminal qualification is full for every run. CC17, GL9 and QMC are independent
post-fit diagnostics and never feed fitting or qualification.

Primary: at width256 with `terminal_only`, compare `stage_gl3_gl5` against
`fixed_gl5` separately for all four solvers and all seeds, reporting final joint
qualification counts, CC17 cost and fitting work. This tests whether cheap early
optimization plus accurate late optimization can unlock the largest width.

Secondary: at width256 with `fixed_gl5`, compare `terminal_only` against
`frequent_lazy`, measuring final qualification, CC17 cost, optimizer work and
paid monitor time. Width64 is a fully retained cross-check. Explicit C versus
Adam remains the central paired contrast, with ordinary AD and L-BFGS mandatory.

## Evidence and accounting

Save initial/final tensors, every intermediate monitor checkpoint, stage-switch
weights, complete solver histories, training laws and raw outputs. Freeze selected
weights before terminal qualification and post-fit scoring. Evaluate all final
candidates on CC5, GL5, CC9, GL9, CC17 and four new scrambled Sobol1024 rules
(seeds 2026101501..04), plus changed amplitude, dynamics and horizon-four panels.
No evaluation resumes fitting.

Record fitting-only wall/CPU, stage-specific work, monitor wall/CPU, terminal-gate
wall/CPU, full-process wall/CPU, HVPs, objectives, accepted changes, cache builds
and process RSS before and after final evaluation. Matrix-free methods construct
zero dense Hessians. Operation overshoot is visible; no exact FLOP/time/energy
matching is claimed. FLOPs, energy and GPU measurements remain null.

A read-only audit reconstructs every law, initial tensor, stage switch, monitor
predicate, final terminal gate and selected tensor; replays all saved predictions;
checks all 96 factorial identities; independently recomputes omitted intermediate
CC9 values after fitting; and rejects missing cases, changed tensors, rehashed
false stages/gates/costs or altered quadrature weights. Independent NumPy action-
coordinate checks remain limited implementation checks, not global optimality.

This is assistant-container CPU/FP64 research, not the user's project cloud,
native Neuron deployment, full Rust/Bazel acceptance, universal approximation,
global optimization or general LLM/world-model superiority evidence.
