# R6: a common continuous parent law, before efficacy execution

Parent PR #1793, exact SHA 30f62c04bc7b21ed0de15b2d9c383c829e0a5d10.
Historical source, weights and negative findings remain unchanged. This protocol
is pushed before the new efficacy sweep. It is not external preregistration.

## Target, information and model

Use the unchanged R5 nonlinear forward feedback, affine primitive plant,
quadratic-plus-quartic terminal errors, entropic continuation eta=.4, gamma=.93,
known two-regime law and horizon three. The primary nonlinear family has the
same 78 parameters, initialization seeds 11/23/47 and no pretrained encoder.
The target initial law is now CONTINUOUS and fixed for every method:
independent uniform h1,h2 in [-.25,.25], x1,x2 in [-.8,.8], equal initial regimes.
All conditional binary branches remain exactly enumerated. New integration
points are not a different underlying distribution. No independent optimum is
provided to fitting. This is not unknown-world learning or a general FBSDE theorem.

Training uses tensor Clenshaw-Curtis rules with 3 or 5 points per coordinate
(81 or 625 states), exact positive weights normalized to expectation. Nodes nest
under refinement; center nodes are set exactly to zero. Both methods receive
the SAME states, weights, nonlinear objective and initial tensor within each pair.
A corner rule retains the old 16-state surrogate as a separately labeled
coverage control; it is not called the exact continuous target law.

Primary: explicit-adjoint trust-exact C versus Adam B, CC5, no regularizer,
8-second nominal training CPU cap, all three seeds. All weights are shared over
inputs and branches. Explicit costates must use WEIGHTED root mass as well as
risk-tilted reach, not uniform counts. Compare ordinary-AD trust-exact,
L-BFGS and full-gradient root on CC5 with the same information and budget.
A scalar ridge .5*.001*mean(theta^2) is separately tested for B/C on CC5; this
changes the optimization objective and is NOT pooled into the primary comparison.
Report unregularized task utility and regularized training objective separately.
No weight normalization is claimed intrinsic to function space.

## Frozen run census and stopping

Three seeds x corner/CC3/CC5 x Adam/adjoint: 18 runs. Three seeds x
CC5 x AD trust/L-BFGS/root: 9. Three seeds x CC5 x Adam/adjoint with ridge: 6.
Three from-scratch Transformer/Adam CC5 controls: 3. Three untrained nonlinear
controls: 3. Matrix-only Adam/adjoint and scalar Adam/root CC5 at seed11: 4.
Total 43 processes, 40 fitting attempts, three untrained controls.
All fitted runs use an 8 CPU-second cap. Root/trust methods can terminate early
on their training-only criteria. No holdout chooses iterations, seed, solver,
regularizer or quadrature. Count distinct accepted weight changes separately
from optimizer callbacks; do not reinterpret callback counts as updates.
Preserve the initial weights when no completed accepted iterate fits the cap.
No first-time-to-quality or exact-FLOP matching claim follows from this budget.

## Integration and evaluation, frozen before fitting

Every run seals weights before evaluation. Evaluate the original continuous
objective on CC3/CC5/CC9/CC17 (nested grids), and a separate tensor Gauss-Legendre
9-point rule. Chunking bounds memory but not the total integration work.
Also evaluate four separately scrambled Sobol replicates of 512 states, seeds
2026101461/62/63/64, from the SAME continuous parent law. Report replicate means
and between-scramble standard error, not an exact confidence certificate.
Primary reporting uses CC17 cost, checked against GL9 and the four Sobol means.
Report paired differences, every seed, and all numerical discrepancies.
The magnitudes |J17-J9|, |J17-JGL9| and QMC disagreement are integration-error
DIAGNOSTICS, not rigorous bounds on the true integral. Convergence of numerical
estimates is not proof that the full distribution has been integrated exactly.
Training-only diagnostics use CC5 and CC9 gradients at the selected weights;
small coarse-rule gradient does not imply small true population gradient.

First 16 states of Sobol replicate one (both initial regimes) form a clearly
labeled finite reference panel. Reuse the independent NumPy convex adapted-action
solver and supporting-hyperplane bounds. Those reference bounds apply to those
32 cases and the richer action policy class, NOT the whole continuous integral
or the shared-neural optimum. References are computed only after all fitted
predictions have been sealed. Candidate action costs are independently reevaluated
in NumPy on a fixed subset. Keep separate physical branch probabilities and
risk-tilted utility weights. No learned probability head: calibration is N/A.

Secondary stresses use the first 128 fresh Sobol states: doubled amplitude,
changed primitive dynamics, and horizon-four declared modulo-three layer reuse.
They change the target problem and must not be pooled with same-law integration.
Untrained, matrix and scalar controls remain even if they outperform a primary
method. Transformer capacity and functional prior are not matched to B/C.

## Evidence, costs and limits

Use create-only run directories, sealed input/weight/prediction bytes, source
hashes, failure-inclusive census and saved-model replay. Keep all methods and
all panels. Reference, dense integration, diagnostic gradients, Hessians,
initialization, inference, serialization, imports and replay are actual paid
work. Store child CPU/wall and process peak RSS; numerical reports identify
phase coverage, budget overshoot and evaluator call counts. FLOPs, energy and
GPU metrics stay null when unmeasured. Tests and tooling are additional costs.
No full repository CI, target-device or production claim; no main/CURRENT change.

Mechanism tests: quadrature moments and positive mass, nesting, nonuniform
weighted adjoint versus AD/finite differences, Hessian agreement, ridge
separation, create-only evidence, chunking/replay equality and rejection of
altered weights/weights-of-integration/rehash-falsified scores. No efficacy
result is inferred merely because these tests pass.

Primary source references for numerical API semantics:
https://docs.scipy.org/doc/scipy-1.17.0/reference/generated/scipy.stats.qmc.Sobol.html
https://docs.scipy.org/doc/scipy-1.17.0/reference/generated/scipy.optimize.minimize.html
