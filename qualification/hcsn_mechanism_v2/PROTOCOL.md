# HCSN mechanism study v2

## Decision and scope

Keep reverse-mode BP and the dense FP64 backend. Investigate four mechanisms
before making broader architecture or training-speed claims:

1. Does the current shared value/risk feature pair contain useful incremental
   information once representation rank, units and regularization are visible?
2. Under the same decision clock, how much of the optimal-control versus gate
   difference comes from the policy class and how much from finite optimization?
3. Which mechanisms explain the old horizon-shift prediction failures, and does
   the declared continuous process survive subdivision of one physical path?
4. When conditional BP is actually optimized, what cost does solving a linear
   readout remove, and what remains in encoder adaptation and program creation?

The parent evidence is commit
`b1a19b3b6b4ce24548a293a075ad9ed7088c6987`; its numerical source remains
`a0b38d3d12c45a4fd254ca27fe1d4266b4c75c53`. Previously consumed final data are
diagnostic material only. New evidence uses the five seeds and independent
namespace in `study_plan.json`. Every stage receives a distinct namespace suffix.
The original source packages are unchanged. No N256, C2, HPCA, deployment or
production-backend qualification is transferred to this study.

## Representation intervention

For four external task families, freeze the previous 4-input/4-content encoder
prior and compare three 20-dimensional feature banks: current value/risk,
zeroed value/risk columns, and two fixed ordinary tanh projections represented
by their last and pooled values (four replacement columns). All banks
pay for the complete common encoding and projection calculation. A readout has
20 slopes and one unpenalized intercept. Training uses 128 windows, development
64, and each independent final distribution 256; windows have 12 observations.

The crossed settings are:

- Legacy observation pooling versus explicitly exposure-normalized interval
  increments. Event/content increments use a rate or total-over-total-time;
  state-like features use exposure weights. Endpoint quadrature and interval
  first-hit probabilities do not become exact instantaneous intensities.
- Empirical training standard deviation with a `1e-8` floor versus a predeclared
  absolute `0.05` scale floor. Means and scales are fitted on training data only.
- Raw linear output, plus a shared post-fit `[0,1]` projection for first passage.
  Both use the same raw-MSE training objective. No logistic closed-form claim.

The scale floor changes the ridge prior in raw feature coordinates. It is not
merely a more accurate linear algebra implementation. Centered SVD solves
`sum squared error + 0.001 * squared slope norm`, with a free intercept. Save the
training matrices, singular values, residual rank of the extra columns, effective
degrees of freedom, normal-equation residuals, raw slopes and final contribution
ranges. Feature rank and feature usefulness are separate questions.
If raw slopes are `b_j=w_j/s_j`, the penalty is `lambda * sum((s_j*b_j)^2)`.

Each arm compares its development MSE with a training-mean incumbent. Save both
candidate and selected weights. Report candidate and selected final outcomes,
including all NoUpdate decisions. Muting frozen analytic readout contributions
is an algebraic sensitivity calculation, not an independently refitted causal
ablation; the zero-column bank supplies the separately refitted comparison.
Representation identity/clip arms make separate development acceptance
decisions. Their candidate difference isolates output projection; their selected
difference can also include different fallback decisions. In the readout-cost
study, raw development MSE selects once before either final output link.

The old prior has zero drive/boundary input weights on association and
asynchronous tasks, and the probability state has no content feedback. Its
value/risk channels therefore encode the random time grid, not input content.
Timing can still help decode fading content. This does not imply mathematically
zero conditional usefulness, nor does it test every possible task-aligned
free-boundary operator.
The current `call` is a fixed-policy continuation functional of
`(rho I-G)^(-1)r`, and `risk` is an interval first-hit functional. They are not
the He-Xiong equity/put pair with an endogenous smooth-pasting default boundary.

## Common review clock

Use the known six-state finite process with five active states and one locked
reset phase. A decision occurs only at `t = k * Delta`. Both continue and reset
then evolve for one complete interval before the next decision. For generator
`G`, discount `rho`, running utility vector `r` and immediate reset payoff `k`,

\[
 D=e^{(G-\rho I)\Delta},\qquad
 H=(\rho I-G)^{-1}(I-D),\qquad C=Hr+Dv,
\]
\[
 R_i=k_i+C_{\rm reset},\qquad
 v_i=(1-\pi_i)C_i+\pi_iR_i.
\]

The locked phase has `pi=0`. This is a review-time MDP, not the continuous
observation impulse QVI. Its Bellman map has contraction factor
`beta=exp(-rho*Delta)`. Use `residual/(1-beta)` as a value-error bound.

For `Delta={0.125,0.5,2}` and bounded sigmoid logits `L={6,10}`, compare hard
Howard policy iteration, Howard in the exact bounded probability class, and
actual autograd Adam gate optimization in that same class. Independently
enumerate all 32 corner policies. Oracle values do not supply labels, gradients
or a stopping target to the gate. Stop only on the predeclared residual bound
or the common step/wall cap; budget exhaustion is not convergence.

The training-objective gap decomposes exactly as

\[
 J^*_{\rm hard}-J_{\rm BP}
 =(J^*_{\rm hard}-J^*_{[\epsilon,1-\epsilon]})
 +(J^*_{[\epsilon,1-\epsilon]}-J_{\rm BP}),
 \quad \epsilon=\operatorname{sigmoid}(-L).
\]

This decomposition concerns the training reward estimate. It is not a
decomposition of generalization error. Independent final reward measurements
evaluate frozen candidate/selected policies and the entire predeclared budget
curve. Fixed-policy return is affine in the reward vector, so one adjoint solve
per unique policy gives all reward-probe returns; exact-policy reuse is recorded.
Final rows reflect reward-measurement uncertainty, not independent retraining.
Use the non-fallback candidate for the training decomposition. The never-reset
fallback `pi=0` lies outside the bounded class when `epsilon>0`; a selected
fallback must not be inserted into that class-specific identity.

## Physical resolution and continuous writing

The prior `final_clock` changes both total horizon and trajectory/input
distribution. Its observation count is fixed. Do not call it paired resampling,
and do not attribute its whole prediction failure to extra observation writes.
It remains a separate, explicitly named horizon-shift outcome here.

New paired streams hold controls constant over each physical segment. A refined
stream subdivides each segment four ways, adds no information or noise, retains
the same IDs/labels/horizon, and preserves each real write exactly once. External
labels come from a hazard integral, a stable scalar filter or two key/value
events. These labels document the external task; this stage does not train a
predictor or claim task accuracy.

Compare three specified laws on the same finite generator:

1. Legacy: write fraction `0.35` at every observation.
2. Physical-event mask: write `0.35` only at declared real events.
3. New continuous-write process, with active-state diagonal selector `D_a`:

\[
 \dot p=pG,\qquad
 \dot q=qG-\kappa qD_a+\kappa mpD_a,\quad
 \kappa=-\log(0.65)/0.1.
\]

For a held mark, `e=q-mp` obeys `e'=e(G-kappa D_a)`. Two small matrix
exponentials yield the exact finite held-process terminal state and integrated
marked-event output. Test against an independently assembled coupled block
exponential, constant-input analytic solution, subdivision and finite
differences. The continuous law is a new candidate process; the event-mask law
retains event-writing semantics. Neither is silently identified with the other.

Compare terminal probability/content and cumulative event/occupation quantities.
Predeclared expected subdivision tolerance is `1e-9` for event-mask and
continuous-write arms. Keep every numerical failure. No quadrature average is
substituted for an exact cumulative quantity. All arms prepare both kernels, so
this stage makes no execution-speed claim.

Old first-passage/asynchronous inputs are interval-end observations, whereas the
old executor applies a control based on that observation over the interval just
elapsed. It is causal in the token prefix but is not automatically a physical
left-held online filter. The new paired tasks explicitly define left-held
controls; their semigroup statement is restricted to that process.

## Conditional optimization and complete adaptation costs

Use the same frozen features, target, penalty and 21-parameter readout mask for
direct centered SVD, actual L-BFGS BP, the unchanged public semantic program,
and that program followed by L-BFGS BP. Rotate execution order deterministically
by task/seed. Retain shared cold optimizer/SVD startup separately; never charge
that one-time event selectively to the first BP arm.

BP receives only features and labels, not the direct solution or oracle target.
It has 2,048 optimizer iterations and a nominal 4,096 function-evaluation cap;
Torch's line search can finish an iteration beyond the nominal evaluation cap,
so record actual calls. Check the final objective against the direct optimum
after fitting, with tolerance `1e-8`, gradient norm and a strong-convexity error
bound. Report all failures to attain that tolerance. Trial line-search points
are not selected final checkpoints. Development compares the final candidate
with zero and preserves candidate and selected parameters.
Small training objective gaps do not ensure identical extrapolated predictions:
large standardized inputs can amplify differences along flat directions. Report
final prediction/MSE differences separately. A same-quality cost screen permits
an MSE increase of at most `max(1e-6, 0.01 * zero_dev_MSE)` for each readout case;
the nonlinear screen uses the analogous frozen incumbent development MSE.
These are predeclared engineering screens, not significance tests.

Additionally compare ordinary Adam BP, variable-projection BP, and the unchanged
semantic outer initialization followed by variable-projection BP on the two
predeclared task families, first passage and association. All have the same
51-parameter union: 30 encoder/boundary parameters and 21 readout parameters.
The profiled methods solve the 21 readout parameters conditionally and retain
BP for the 30 outer parameters. With positive ridge and fixed normalization,
holding the conditional optimum fixed gives the envelope derivative. Check it
by finite differences that rebuild the encoder and resolve the readout.

These nonlinear arms use 64 train/64 dev/128 final windows, eight observations,
512 updates and the same fixed development checkpoint grid. A non-grid wall
terminal point is diagnostic only and cannot read dev or become selected. A
small training gradient is a stationary-point observation, not a global optimum;
all exhausted budgets remain labelled as such. No claim of sufficient nonlinear
training is made solely because 512 steps is longer than the old 12-step budget.

Record data/feature preparation, solves, backward passes, optimizer work,
validation, serialization, process startup/exit and CPU/RSS. Add shared setup
back when comparing standalone arms, but do not double count it in actual
campaign totals. Legal reuse is restricted to unchanged parameters and data.
Every outer edit rebuilds the operator and features.

The semantic programs are reused source artifacts. Their historical authoring
time, token count and API bill are unknown, not zero. Record their actual runtime
application/assembly costs and the observable new research authoring windows
separately. Parallel authoring windows are not additive elapsed latency. Report
end-to-end savings only to the extent complete costs are known; any break-even
calculation with an assumed design cost must be labelled a scenario.

## Ownership, execution and reporting

The source closure contains real published Git commit/tree/blob identities and
file SHA-256 values. It is not a fabricated full checkout. Runtime identity and
the canonical contents of both plan and source manifest are frozen and bound to
an exclusive allocation. Fit and final each consume a registry marker once.
Final requires an externally supplied selection digest and the exact complete
set of fitted case hashes. Source and runtime are checked again at execution.

There are 70 fit case records and 70 final case records across the five stages.
Their inner arm counts differ and are reported separately. Numerical failures
are serialized before preventing successful completion; no failure is changed
to PASS, silently dropped or retried under the same namespace. Previous data,
test fixtures and development API checks use separate identities.

For prediction contrasts, retain all five paired seed effects, their arithmetic
mean and observed minimum/maximum. No confidence interval or significance claim
is inferred from that observed range. Do not treat hundreds of rows from one fitted model as hundreds
of independently trained models. No favorable subset replaces the declared
grid. This study does not establish a multimodal, biological, sparse-energy,
GPU, foundation-model, Transformer-replacement or whole-network no-BP result.

Canonical `just fmt` is executed on the actual published-head CI checkout.
Its selector does not own qualification Python, so the new package also has an
explicit Ruff format check. Mathematical fixtures, development API checks,
formal evidence and repository-wide CI status remain distinct evidence scopes.

## Primary financial-model reference

Zhiguo He and Wei Xiong, *Rollover Risk and Credit Risk*, Journal of Finance
67(2), 391-430 (2012), [author-hosted published paper](https://www.princeton.edu/~wxiong/papers/rollover.pdf).
Section II.B and Appendix A couple equity continuation value to rollover cash
flows and determine the endogenous default threshold by value matching and
smooth pasting. The finite-process operators above are separately specified
research constructions; their correctness and learning utility require their
own tests and cannot be inherited from that financial model.
