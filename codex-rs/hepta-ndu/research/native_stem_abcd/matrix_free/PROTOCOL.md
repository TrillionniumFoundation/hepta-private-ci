# R7: matrix-free population-adjoint comparison

Parent #1811 at 569f302a5dbdfb1dd15e3454d6c2ddc5e8170321.
This is a local protocol freeze pushed before efficacy execution, not external
preregistration. Seventeen math/derivative/training-only tests preceded freezing.
No R7 evaluation result selected these settings. Historical source is unchanged.

## Fixed scientific problem
Use R6's known continuous law: independent uniform h in [-.25,.25]^2, x in
[-.8,.8]^2, two equally probable starting regimes. Retain the exact R5/R6
78-weight nonlinear feedback, quartic terminal error and entropic recursive
cost, horizon 3. All conditional branches are exactly summed. The primitive
plant and preference transition are known, not learned endogenous dynamics.
This is shared forward-weight learning in a small special case, not an LLM,
unknown world model, continuous-time FBSDE or viscosity convergence theorem.

## Methods and full work
C uses a cached explicit-adjoint gradient graph and Hessian-vector products
inside SciPy trust-ncg. It NEVER forms a full Hessian in its fit. A reverse
derivative computes (Dg)^T v; because g is the smooth scalar objective gradient,
Hessian symmetry gives H v. Unit tests compare dense H v, forward jvp and
centered differences. A cached ordinary-AD trust-ncg control uses the same
algorithm. Dense explicit-adjoint trust-exact, Adam and L-BFGS are retained.
The implementation caches only the last candidate's graph; changing parameters
or integration rules invalidates it. Cache builds, products, rejected trials,
callback counts and distinct weight changes are charged and distinguished.

Primary B/C share model family, initial bytes, information, objective, fixed
CC5 rule and nominal eight-second CPU cap. Adam lr=.015, trust gtol=1e-9,
default trust-ncg radius/acceptance; L-BFGS ftol=1e-14/maxls=40. No per-method
hyperparameter search. Cached dense is newly executed, not claimed bit-identical
to R6's uncached solver. No optimal labels, ridge, holdout checkpoint selection,
gradient-root-as-optimum or general global-optimum claim.

## Integration / optimization balance
Fixed CC3 and CC5 positive tensor quadrature approximate the same continuous
integral. A separately labelled adaptive schedule starts CC3. Every five distinct
accepted updates it compares g3 and g5 at the same theta, using training rules
only. Promote to CC5 when ||g5-g3||inf > .25||g3||inf or ||g3||inf <1e-3.
Also promote at half the training CPU budget or coarse optimizer termination.
Once promoted, restart each optimizer at the last accepted theta, resetting all
moment/quasi-Newton/cache state. The checks, rule construction and restart cost
are charged. The estimate is a heuristic gradient-integration discrepancy, not
a uniform quadrature bound. It does not consume CC9/17, GL9, QMC or reference
evaluations. No reverse promotion or final held-out selection.

## Frozen run census
Five methods (Adam, dense, explicit matrix-free, AD matrix-free, L-BFGS) x
three seeds 11/23/47 x fixed CC5/adaptive =30 fits.
Fixed CC3 Adam/explicit matrix-free xthree seeds =6 fits.
Three untrained initial controls. Total39 runs, 36 fits.
All run in separate one-thread CPU/FP64 processes. Rotate method order per seed.

Primary: fixed-CC5 explicit matrix-free versus Adam, mean CC17 cost with every
paired seed shown. Dense and L-BFGS/AD matrix-free are mandatory strong controls.
Adaptive and CC3 are secondary, never substituted for an unsuccessful primary.

## Evaluation
Seal all weights and predictions before reference fitting. Evaluate every model
on CC3/5/9/17, separate GL9, four fresh scrambled Sobol512 sets with seeds
2026101471..74, plus doubled amplitude, changed dynamics and declared horizon4
layer reuse. The last three are changed problems. Same-law probes and repeated
seeds are not independent semantic domains. Report costs, gradients on CC5/CC9,
quadrature discrepancies and paired QMC errors; they are numerical diagnostics,
not guaranteed intervals or global optimality gaps. No probability head exists.

Independent NumPy convex action-tree reference covers only first eight fresh
Sobol states x two regimes. Its support-plane optimum bracket is finite-subset
and richer-policy only, not the continuous-population or neural-family optimum.
Re-evaluate saved action paths for first two states x two regimes per model.
Reload every tensor and replay all panels; report the complete failure census.

## Resources and authority
Whole-child CPU and spawn-to-exit wall include imports and startup. Fit CPU,
HVP/cache/dense-H counts, every promotion check, predictions, diagnostics, audit
and reference work are separately retained. Cap checks precede nonpreemptible
operations; actual overshoot is visible. RSS is process peak including runtime;
capture fit peak before post-fit diagnostics. FLOPs, energy and GPU are unknown.
No exact-compute, first-time-to-quality or physical full-research-TCO claim.
Output files are create-only; all failures and adverse outcomes remain.
No main/CURRENT, native contract, selected-model or production authority change.

## Reproduce
From this directory, use the inherited pinned requirements (NumPy2.3.5,
SciPy1.17.0, PyTorch2.10.0 CPU) and Python3.13:
    OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 python -m unittest -v
    OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 python run_matrix_free.py sweep --out /new/path

Implementation references (not efficacy sources):
https://docs.scipy.org/doc/scipy-1.17.0/reference/optimize.minimize-trustncg.html
https://docs.pytorch.org/tutorials/intermediate/jacobians_hessians.html
