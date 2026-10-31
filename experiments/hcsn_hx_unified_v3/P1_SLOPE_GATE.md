# P1 local-slope mechanism probe — exploratory, not admission evidence

**DRAFT / RESEARCH ONLY / DENY_ALL / all_blockers_closed=false / production_activation_allowed=false.**

Parent: HCSN P0 scalar branch-point draft #4424 at exact head
8edb08246673a7c78e8bc9d96b8662220be3bff6, itself stacked on #4377.
The scope adds two Python research files and this note; it does not alter HX
formulas, scalar stopping/QVI, existing data/results, Rust, GPU, owner,
authorization, CI workflows or model deployment.

## What is implemented

- A frozen affine output transform alpha + beta * channel(z) matching
  ordinary sigmoid value and signed first derivative at a **training-only**
  anchor. Both derivatives are estimated independently by five-point
  stencils at h and h/2, with left/right consistency checks.
- Explicit refusal for near-zero or unstable derivatives, nonsmooth curves,
  excessive gains, invalid stencil/domain, nonfinite values, and impossible
  HX probability ordering. No clipping and no reclassification of refusals.
- Real financial features are isolated from neural state: Call = literal
  HX equity E(V), Risk = first-passage F(T), Survival = 1-F(T),
  Margin = bond value minus principal/maturity. The input coordinate
  is z = log(V/V_B) and an excluded near-barrier region is declared.
  E(V)>=0 and 0<=G<=F<=1 are **necessary-only** checks: neither proves
  global HX obstacle consistency nor coupled fixed-point optimality.
- A local math counterexample demonstrates that matching first derivatives
  and values at one anchor does **not** match curvature off anchor.

## Validation scope

Local Python 3.13.5 / SciPy 1.17.0 / CPU: 9 of 9 unittest methods pass.
Generic math probe used the exact new source. HX integration tests used a
**locally transcribed reconstruction** of the corresponding upstream HX
formulas, not an exact-byte full repository checkout. Original remote HX
source-exact integration, wider parameter grid, low-precision execution and
full repository CI are NOT claimed as passed. Report a branch-specific CI
status only after checking the final exact HEAD.

Reproduce on an actual checkout of the stacked branch:

    python -m unittest -v experiments.hcsn_hx_unified_v3.test_matched_slope

The local diagnostics validate the instrumentation only and are not a
pre-registered P1 causal experiment or numerical interval certification.

## Remaining admission gates

No P1 win: the prior 0/4 mechanism gates remain binding negative evidence.
Before genuine P1 training, freeze an untouched task/data/seed protocol and
anchors; match active trainable parameters, optimizer, data, token streams,
compute budget and independently measure complete costs. Run Call/Risk/Margin
alone and in two- and three-channel ablations against separately tuned
ordinary gates, fixed-threshold LIF and no-renewal controls; report paired
held-out net task utility with the predeclared multiple-comparison family.

P0 full HX global coupled obstacle/QVI, all-domain interval/precision and
gradient admission; P2 repeated-event memory superiority; P3 paired
text/image/audio/video; P4 real Rust/GPU 64-4096 Cells and energy/recovery;
and P5 equal-budget backbone advantage ALL REMAIN OPEN.
Do not merge or activate as production.
