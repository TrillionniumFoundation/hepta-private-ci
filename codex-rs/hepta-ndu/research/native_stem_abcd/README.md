# Native NDU Stem: A/B/C/D population-law experiment

Research-only. No pretrained encoder, native Q24/Q32 installation, production
model selection, effect authority, or changes to existing Hepta owners.

## Question and implemented scope

Can a from-scratch non-Transformer Stem obtain better approximation and transfer
by **directly solving the shared-weight FBSDE equations**, rather than optimizing
the same objective with Adam? Does an exact structure-preserving operator provide
a useful numerical reference? A generic quasi-Newton control checks whether an
observed improvement is merely a second-order optimization effect.

This first executable experiment learns a **nonlinear conditional solution
operator**, not natural-language representations or a general optimal policy.
Its entire finite training law is known and enumerated. A forward process with
experience-dependent bounded preference is supplied exactly. All learned weights
are fitted from scratch; no frozen model supplies hidden features. The backward
operator is an entropic recursive **cost** (negative utility), not a relabeled
linear discounted score. Unknown preference coefficients are not fitted here.

This deliberately separates three claims: numerical recovery on a known finite
law; transfer to explicitly changed conditions; general language/world-model
superiority. Only the first two are measured, and only on generated tasks.

## Mathematical problem

The state is S=(X,P). X is a d-bit shift register, and P is a bounded preference
state in {0,1,2}. A Bernoulli branch updates both X and P. Thus the preference
transition depends on observed experience, with known coefficients. The training
world has d=2 and 12 joint states. Both successor IDs and the exact branch
probability p(S) are supplied. All probabilities are strictly between zero and
one. The risk coefficient is rho(S)=0.35+0.4P; gamma=0.9.

For a supplied terminal contract g and remaining horizon h,

    U^0(S) = g(S)
    U^(h+1)(S) = c(S) + gamma/rho(S) *
                  log[p(S) exp(rho(S) U^h(left(S)))
                      +(1-p(S)) exp(rho(S) U^h(right(S)))].

At rho=0 the exact limit is c+gamma*E[U^h]. This limit is used in a separately
labeled factual-probability diagnostic, not claimed to be the original utility.

The forward law is mu_(k+1)=mu_k P. With m=I_left-p, the martingale representation
is exact: Z=U(left)-U(right), U(S_next)-E[U(S_next)|S]=Z*m and Var(m|S)=p(1-p).
The discrete BSDE generator is T(U)-E[U_next|S]. No unit-covariance shortcut,
unsupported inversion, learned-Z-as-parameter-gradient claim or continuous-time
viscosity convergence is used.

The **full collocation population** is the uniform product of 12 terminal
contracts, all 12 initial states, and remaining horizons 1,2,3: 432 equations.
It is a distribution of separate state-started conditional equations, not a
claim that a single trajectory's occupancy is uniform. Actual forward occupancy
is computed separately and retained. Each model starts with the exact terminal,
then repeatedly applies its same shared block. Its objective is

    J(theta) = mean_(g,S,h) [U_theta^(h+1)(S)-T(U_theta^h)(S)]^2.

The target side is NOT detached: all cross-depth parameter dependence remains.
This is an operator-recovery objective; it is NOT the Pontryagin system for
maximizing an arbitrary agent's unconstrained utility.

## Arms and information equality

- **A**: randomly initialized Transformer, one full 2-head attention/FFN block,
  width 8, FFN width 16, no dropout, fitted using Adam (learning rate .002).
- **B**: a shared nonlinear state-evolution block, 6->8->1 tanh correction to a
  common exact conditional-mean skip. All 65 weights are trainable. Adam (.01).
- **C**: EXACTLY B's class, initialization, parameter box [-12,12], objective,
  training population and inputs. SciPy trust-region reflective least squares
  solves the reduced shared-weight FBSDE collocation system with full forward-AD
  Jacobians through every step. No Adam, pretrained model or solved-value labels.
- **D**: directly constructed monotone entropic operator with known coefficients;
  no fitted weights. This is a specialized exact-structure reference, not evidence
  of a learned universal Stem. Model construction and inference still cost work.
- **B_LBFGS**: B's identical class and objective, strong-Wolfe L-BFGS. This added
  optimization control prevents confusing “better than Adam” with a uniquely
  FBSDE-derived advantage.

Every arm receives the complete two-point conditional law as raw numeric input:
left/right continuation values, probability, risk, cost and discount. Every
learned arm receives the same conditional-mean skip. There are no oracle hidden
features, state embeddings from a pretrained model or evaluation labels in fit.
D encodes extra *structure*, not extra data; all arms have the same coefficients.
A and B do not have equal parameter counts; A/B alone cannot isolate parameter
capacity. B/C and B/B_LBFGS do.

C is a **reduced-space nonlinear equation solver**, not a free optimization of
independent per-task states: one shared parameter vector determines every state
and every depth. The forward law is already known; the backward values are
eliminated by the tied rollout. FBSDE equation consistency at the final terminal
anchors the problem. A small finite collocation residual is not a proof of
finding a global optimum or solving every possible terminal function.

## Independent reference and error checks

D uses vectorized FP64 logaddexp. A separate scalar Decimal implementation with
50-digit precision computes the reference; it does not call D/exact_step. At
zero risk, an additional independent matrix-power calculation checks predicted
probabilities. Outputs from ALL panels are sealed before oracle scoring starts.
No evaluation metric selects a checkpoint, seed, optimizer or stopping point.

The exact operator is monotone and gamma-Lipschitz in the sup norm. Along any
fixed terminal's evaluated trajectory, let r_h be the maximum statewise equation
defect. Then e_(h+1)<=r_h+gamma e_h, with e_0=0. We compute this error envelope
on the complete finite state domain and compare it to the independent reference.
This is a numerical check of an analytic bound for each evaluated contract,
NOT an interval-certified floating-point proof and NOT a uniform certificate over
unseen contracts, continuous states or changed physical laws.

## Frozen evaluation panels

1. Exact training-law reconstruction: all states and 12 terminal contracts.
2. New terminal contracts: eight different functions, same forward generator.
3. Longer horizon: the new terminals, horizon 8 rather than training horizon 3.
4. Higher dimension: two to six binary physical coordinates; 12 to 192 joint
   states, same coefficient-generation family, frozen weights. This is discrete
   dimension scaling, not a high-dimensional continuous-language result.
5. Changed dynamics: an additional bit flip changes the kernel; the new kernel
   is supplied to EVERY arm. This is adaptation to known new coefficients, NOT
   robustness to an unobserved change or the original-law guarantee.
6. Factual probability: indicator terminals, zero risk, zero cost and unit
   discount. This changes the utility profile and is explicitly a stress test.

A nonuniform initial-state distribution is also evaluated from the same value
fields; it is not counted as a new independent task cohort. Terminals in panels
2--6 are outside the finite training objective. Knowing the full training law is
not claimed to mean that the optimizer included every possible future task.

Metrics include full-domain RMSE/max error, an actual initial choice between
paired terminal contracts (oracle-measured regret and non-tie decision accuracy),
raw out-of-range probability frequency, raw/clipped excess Brier, expected Brier
and expected ECE10. Raw probabilities are never silently replaced by clipped
ones; both interpretations are reported.

## Budgets, provenance and reproducibility

The sweep freezes two nominal training CPU caps (2 and 8 seconds), seeds
11/23/47, all panels and the primary contrast before the sweep. It rotates arm
order and uses one fresh process per fit, with one CPU thread. The 8-second
B/C new-terminal comparison is primary. L-BFGS uses the same three seeds at the
8-second cap. D is run once, not counted as three independent observations.
A preceding 0.6-second C development smoke and unit tests are disclosed; this
is a local protocol freeze, not externally registered blind confirmation.

The cap is checked before each residual/Jacobian evaluation. A single operation
may overshoot; actual CPU and wall time, every residual/Jacobian call, forward-AD
tangent lanes, optimizer steps, inference, high-precision oracle, process peak
RSS and whole-child wall time are retained. Generic line-search trials and
Jacobian construction are paid. Unfinished L-BFGS trials revert to the last
accepted weights. There is no same-FLOP or exactly equal-time claim. FLOPs and
energy remain null because neither has been completely measured.

Process peak RSS includes imports/runtime allocation. The process is fresh but
there is no background-load control or hardware attestation. The parent measures
spawn-to-exit wall time, including imports and final serialization. Source tests
and the preliminary smoke are separately retained; they are additional costs,
not part of one arm's reported inference. This container is not the user's
project cloud or dot computer.

All output directories and files are create-only. PLAN/STARTED, complete raw
prediction arrays, seals, independent oracle arrays, selected weight vectors,
per-run reports, logs, failure census and paired summaries are retained. Saved
weights can be restored with `assign`; they are real numerical arrays, not only
digest declarations. Source hashes bind the exact code used in every run.

    python -m pip install -r requirements.txt
    OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
      python -m unittest -v
    OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
      python sweep.py --out /absolute/new/output_directory

CPU-budget stopping can change the exact iterate across machines. Reproduction
means the same protocol with reported actual work, not byte-identical weights
under a time cap. Fixed saved weights permit exact-source replay within declared
numerical tolerance. No global Rust/Bazel/CI, native deployment or model-quality
claim follows from these Python experiments.

## Relationship to existing research

This path is additive under the existing hepta-ndu research owner. It neither
replaces NDU_FBSDE_SPEC.md nor reinterprets the native stochastic/Q32 profiles.
It complements, rather than recycles as new evidence, the existing shared-encoder,
Reader, Head, System2 and Riccati studies.

Relevant primary references:
- Qi, Universal Approximation Theorem of Deep Q-Networks, ICML 2025,
  https://arxiv.org/abs/2505.02288 . Representation is not automatic parameter recovery.
- Qi, Viscosity Convergence Analysis for Deep Q-Networks, JMLR 2026,
  https://www.jmlr.org/papers/v27/25-1164.html . Operator-level conditions and
  neural projection error must be separated.
- E, Han and Li, A Mean-Field Optimal Control Formulation of Deep Learning,
  https://arxiv.org/abs/1807.01083 . Shared population parameters, HJB/PMP
  conditions and their assumptions are separate from this reduced collocation test.
