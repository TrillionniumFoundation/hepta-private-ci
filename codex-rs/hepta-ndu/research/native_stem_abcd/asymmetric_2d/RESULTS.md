# R18 completed: asymmetric positive-risk, truly two-dimensional global Stem certificate

## Provenance and exact scientific scope

Research-only R18 stacks on R17 Draft PR #2051 at exact parent `9c2ac1e0814f3160038fffc5e599d8698b46ccfc`. The protocol was pushed BEFORE the 64-run efficacy sweep at commit `4b982a80c3e246debbb2ae80c68f075fd531449a`. The candidate and its first numerical/interval pilots preceded the freeze, hence the round is exploratory and not an independent blinded preregistration. The same frozen core ran all child fits; no weight, seed, optimizer, budget, checkpoint or success rule was selected after examining R18 results.

This is a finite known-state **two-step positive-entropic-risk NDU special case**. The two learned forward weights interact nonlinearly, with a genuine off-diagonal optimum; the entire stochastic population consists of 16 enumerated leaves. Neither unknown dynamics, rich multi-task shared encoders, generic deep-network nonconvex global optima, continuous-input measures, viscosity solutions nor LLM/world-model language learning are evaluated. All execution occurred in the assistant container on CPU, not project cloud/native target hardware.

## Strict two-dimensional proof, not R17 symmetry reuse

H1=aX; H2=bH1+(a-b)^2/4+epsilon2/10, target X+1, P0/P1/P2 binary preferences, gamma=.9, risks rho=(.5,1), stage P1/20, terminal (H2-X-1)^2+P2/50. The noise and shifted target break R17's `C(t,d)=C(t,-d)` identity. With t=ab, d=(a-b)^2/4, the feasible quotient K={d>=0,t+d>=0} is convex and the full objective is EXACTLY C(t,d)+t/2+d. The two-variable risk-sensitive objective has globally positive Hessian >=81/50 I; the exact quotient is strongly convex and genuinely two-dimensional.

The original integer-rational candidate is a=1.669246516087578580991543, b=.416891900252459728989673. The independent directed 10^65 interval-gradient computation bounds quotient root distance by **9.74124536716e-25** and actual global population cost excess by **7.68624076556e-49**. The parameter-coordinate distance to one of four true global weight solutions is <=**1.94824907343e-24**. All inequalities are strict rational bounds, not Monte Carlo confidence intervals or float Newton residuals. Forcing a=b has certified true regret >**.124530095007**; forcing b=0 has regret >**.392258976249**. The outward gradient of F(t,d) in the omitted d-direction at d=0 is <-.64458 near the optimum, making the second parameter channel essential.

Positive entropic risk moves the optimal quotient relative to its exactly known risk-neutral comparator (56/81,31/81): the t shift is >.00453732739 and d shift >.00938197156. The global finite-law theorem uses a special **exact 2D convex quotient**, not a generic 2D interval branch-and-bound or a theorem for arbitrary neural model classes.

The separate zero-shift (target X) ablation has its OWN independent global proof. Its normal d-derivative at d=0 is globally >=.838 by a uniform tanh bound, and its certified diagonal optimum has rational a=b=.834232264397470736714151 with true regret bound <5.596e-49. The asymmetric certificate is never transferred to the ablation.

## Actual 64 matched fits: negative local-optimization evidence

2 targets (shifted primary and zero-shift control) x8 fixed seeds/starts x4 solvers = **64/64 successful child executions; zero execution failures**, all real forward weights. Each fit uses .75 **process CPU-second** nominal cap, with actual overshoot counted. All start tensor bytes are identical across the eight conditions of each seed. The certificate NEVER enters the training objective, derivative, optimizer callback or checkpoint selector. Endpoints are evaluated only after sealing; success requires weight distance <1e-6 to the corresponding certified global solution set AND population excess <1e-9, using explicit reference-error allowance and an additional 1e-12 FP64 diagnostic guard. These flags are numerical checks of fitted endpoints, not separate interval-enclosed per-fit certificates.

| Method | Asymmetric shifted 2D global-quality passes | Zero-shift independent-global-control passes |
|---|---:|---:|
| Adam | 0/8 | 3/8 |
| BFGS | 0/8 | 5/8 |
| L-BFGS-B | 0/8 | 5/8 |
| trust-exact | **7/8** | **7/8** |

Thus no universal speed advantage follows: the full-Hessian trust-exact baseline is much stronger in this tiny asymmetric problem, while the other methods frequently converge with essentially zero gradients at negative-curvature stationary points. In particular the origin is an exact stationary saddle under BOTH targets (asymmetric Hessian minimum approximately -1.143585). There are also nonzero wrong stationary points in the asymmetric case at cost ~1.285490 with Hessian minimum ~-.644587, versus the certified global cost ~1.1591143474. All failures and seeds are retained. Results describe ONE small CPU/FP64 numerical problem, not all optimizers or algorithm settings.

## Independent numerical stress and known-law scope

For the SAME frozen asymmetric certified candidate, changing the input distribution from equiprobable X to P(X=+1)=.7 yields evaluated cost about **1.2807592720**; the separately numerically optimized cost on that altered population is approximately **1.2315198458** (observed difference about **.0492394262**). This law-change result is **not** accompanied by a new rigorous global certificate; no independent target-law transfer is inferred. No retraining or favorable model selection based on this changed law occurred.

## Full audit and reproduction

The read-only auditor checks all original core SHA256 values, full 64-case census/plan order, exact per-seed eight-condition initial bytes, all 16 branch values per final tensor, 4,112 archived optimization checkpoints, checkpoint CPU monotonicity, final gradients/Hessians, signed receipt hashes and after-seal global classifications. The same saved checkpoint costs replay with **maximum difference 0.0**. Independent pure-Python entropic tree scoring differs from SciPy-based evaluation by at most **4.440892098500626e-16**; independent leaf arrays replay with maximum difference **0.0**. All eight start groups match exactly.

**107 distinct tests passed with zero skips**: 25 new mathematical, interval, derivative and recursion tests; nine true-file tamper tests; plus **73 unchanged legacy R13–R17 mathematical tests** (15+20+6+14+18). The first new tamper pass had one assertion too specific to the missing-census exception text; the initial FAIL log is retained, specificity corrected post-sweep, and all nine final tamper tests passed. No original experimental weights or results changed.

Whole 64-fit sweep: **75.455648431 wall seconds and 73.693462 child CPU seconds** including interpreter startup and serialization. Auditor: **6.782005427 CPU seconds** (wall 6.783819182 seconds). Per-fit budget is .75 CPU seconds and whole-process metrics are separately saved in every report; runtime/import overhead is not confused with solver-only cost. Adversarial tests and historical tests, preparation, packaging and GitHub connector work are additional, not a complete physical research TCO. Full FLOPs/energy/GPU peak are null. No native-target acceptance or hardware-attested benchmark is claimed.

R17's checked exact-head **nonproduct symmetry certificate CI succeeded**, but R17's **blocking-ci and two inherited numerical research lanes failed**; they must not be described as passing. R18's exact-head hosted CI and project-global gates require separate observation before any promotion. The new work remains Draft, without main merge, CURRENT alteration or production routing.

## Delivery

Git research directory includes protocol, exact mathematical proof, self-contained certificate and ablation certificate, complete numerical driver, all final binary64 weights as hexadecimal CSV, full positive/negative group and case summaries, independent audit and adversarial tests, and new scoped CI. The conversation archive additionally contains all 64 raw run directories, original scores, 4,112 checkpoints, leaf tables, source files and full development/test/CI-independent logs, with a per-file SHA256 manifest. It is not represented as an uploaded Git binary archive.

Next discriminating direction: break this exact two-dimensional quotient entirely (e.g. learned nonlinear state-dependent coupling), then provide a valid global bound via genuine interval branch-and-bound / validated relaxations without laundering a local optimizer's residual into a proof. The R18 result does NOT demonstrate a general model architecture or LLM training advantage.
