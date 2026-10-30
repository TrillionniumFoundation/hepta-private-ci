# HCSN conservative acceleration: mathematical and execution contract

## Scope and source identity

This package changes the evaluation order of the registered finite regenerative
operator and explicitly integrates the existing conservative probability profile
into the content model. It does not change the physical generator, the affine
local reward, the value boundary equation, the content recurrence, or the learned
parameter shapes. `SOURCE_BASELINE.json` identifies the exact parent source
bytes. The sealed v1/v2 experiments remain unchanged.

The scalar regenerative oracle in `hcsn_free_boundary_v1` and the finite CTMC in
`hcsn_distributional_v2` are different mathematical objects. Both were inspired
by endogenous value boundaries. Neither is the original He--Xiong financial
model, and the network's two value channels are not literal option prices.

## 1. Symbols, information, and units

At observation time t, let I_t contain the observations already received, the
stored content state, the complete active/refractory probability vector, and
the declared model parameters. Coefficients prepared from the current observation
are frozen over its declared elapsed interval. No future observation, test label,
neighboring example, or batch maximum may change a token's physical operator.
The existing content model maps an input duration dt to physical CTMC time
0.1*dt. This factor is unchanged and is distinct from the native owner's READ
or tick counter. The caller's sampling interval is not silently interpreted as
seconds of measured hardware execution.

The requested six-symbol vocabulary follows the existing six-stage report.
Subscripts and conditioning information are necessary, even when code omits
them. In particular, bare C/P do not mean financial Call/Put in these records.

| Symbol | Definition | Type and unit |
| --- | --- | --- |
| C(s | z,I_t) | E[N_s | z,I_t], including every reset cycle and any initial boundary-jump event | Expected count in [0,infinity), not a probability |
| P(s | z,I_t) | Pr(N_s>=1 | z,I_t) for the explicitly specified initial full state and moving-boundary convention | Probability in [0,1], not a financial Put |
| F(s | z,I_t) | Probability that the next first firing occurs by elapsed time s, with a specified active initial condition and frozen operator | CDF in [0,1] |
| f(s | z,I_t) | The absolutely continuous part of the first-firing-time distribution | Density, 1/time; atoms must be stored separately |
| H_rho(s | z,I_t) | E[exp(-rho*T_1) 1{T_1<=s} | z,I_t] | Discounted first-event weight, dimensionless |
| K | Immediate affine firing cost in reward(z)=z-K | Reward units; not a probability or transition kernel |

Use J^pi for the policy value and G^pi for the immediate-intervention value
including reset continuation. These are the two value channels in this package,
sometimes called “Call/Put” in the proposed analogy. Those nicknames are not
probability API names. Use mathcal K for a reset kernel, T for a probability
transition, and N_s for the number of all firings. In particular, F(s),
H_rho(s), E[N_s], and a payoff
E[exp(-rho*T_1) reward(X_T_1)] are not interchangeable. A terminal event such as
Pr(X_s >= b) is not a first-passage probability. The finite recurrent model
propagates a regenerative distribution and E[N_s], not just F(s).
P and F agree only when their initial condition, filtration, event, boundary
jump, and refractory conventions agree. Existing derivations that call the
boundary residual H(b) use a different object; this contract calls that residual
Psi(b), reserving H_rho for the discounted first-event transform.

The financial analogy is only a naming aid. A value is not a force. Task-trained
gate weights determine the effect of J^pi and G^pi on content. J^pi is the value of a
whole policy, rather than a pure continue-action Q value. J^pi-G^pi need not be
nonnegative for a suboptimal fixed/direct threshold.

## 2. Oracle, boundary, and model distinction

For the continuous scalar oracle with generator L, strictly positive diffusion
sigma>0, discount rho>0, deterministic refractory duration tau>=0, reset r<K,
and firing reward x-K, the intervention operator is

    M U(x) = x-K + exp(-rho*tau) U(r).

The stationary impulse-control problem is

    max{L U-rho U, M U-U}=0.

Its optimum includes the post-firing continuation. At an admissible smooth
upper boundary, U(b)=M U(b) and U'(b)=(M U)'(b)=1. These are reward-value
conditions. The first-event CDF does not inherit them. A finite-horizon task
value would additionally require its own reward, terminal condition, sufficient
state, and controlled dynamics.

The trained model instead declares eight active cells on [L,b), L=-2, plus
two Erlang refractory stages with rate 2/tau. Tau is the mean waiting time;
the waiting time is not deterministic. The local boundary is derived from
the Brownian/Erlang affine reward problem; the two supplied value vectors are
the actual finite generator's own-policy J^pi and G^pi. Its reflecting lower
boundary and coarse cells do not silently become the unbounded Brownian oracle.

Cross-entropy trains content, drift, diffusion, local cost, discount, reset,
refractory time and boundary pathways jointly. This establishes differentiable
joint learning. It does not prove that the local affine boundary is optimal for
classification. An optimal finite-grid value cannot be substituted without
also changing the controlled event flow and reward consistently.

## 3. Event chronology and reset

1. Receive the observation and causally prepare its physical coefficients.
2. Remap the previous piecewise-uniform active density to the new boundary.
   A lowered boundary fires covered mass immediately, even when elapsed time
   is zero. Its reward uses the pre-reset physical position.
3. Propagate all active cells and existing refractory stages over the elapsed
   interval. An upper exit counts one firing, enters refractory stage zero,
   and returns to the interpolated reset position only after the final stage.
4. Count every later firing in the same interval. Existing refractory mass is
   not restarted by an observation. With zero refractory stages, immediate
   reinjection can return to the same cell and still counts as an event.
5. Update the vector content with the registered model recurrence and transfer
   continuous state/value features to the next layer. This content update is
   not an exact continuous-time semigroup merely because the CTMC is one.

The probability state includes the refractory phases; collapsing it to its
mean would change subsequent nonlinear dynamics. Expected counts may exceed
one. The probability-flow network does not sample discrete biological spikes.
Native KEEP/STOP messages are actual owner actions whose semantics and costs
are separately recorded; expected internal counts are not native message counts.

## 4. Equivalent polynomial evaluation

Use a row generator Q with nonnegative off-diagonals and zero row sums. With
the registered rate Lambda=8.1, define R=I+Q/Lambda and e=lambda_event/Lambda.
The augmented matrix

    A = [[R, e], [0, 1]]

has upper-left block R^k and upper-right block sum(j=0..k-1) R^j e in A^k.
Therefore the same conditional Poisson polynomial

    S = sum(k=0..21) w_k A^k / sum(k=0..21) w_k,
    w_k = exp(-Lambda*dt) (Lambda*dt)^k/k!,

returns exactly the original transition and event expectation in exact
arithmetic. The new backend evaluates this degree-21 polynomial in blocks of
five using positive-coefficient Paterson--Stockmeyer multiplication. It uses
eight dense products of small augmented matrices in place of the original
21-step sparse Python recurrence. Neither the generator nor the truncation
order is fitted or changed.

Each token independently divides elapsed time into chunks no longer than .36.
Transition/event pairs compose as

    (T_a,e_a) o (T_b,e_b) = (T_a T_b, e_a + T_a e_b).

Binary composition retains the original per-token chunk count and duration.
The maximum loop count only schedules work; it does not determine another
token's operator. The original conditional-Poisson tail certificate is retained.
That certificate excludes floating-point roundoff, spatial approximation, and
global gradient error. Independent SciPy and finite-difference checks cover
the particular forward/gradient cases recorded in `results/validation001`.

## 5. Explicit conservative probability profile

The `raw` profile preserves the original neural arithmetic for equivalence
diagnostics. The registered content comparison uses `stable` for both the
reference and accelerated backends. Only a transition explicitly tagged as
regenerative unit-mass probability may apply

    q = p T;    p_next = q / sum(q).

The denominator remains in autograd. There is no clipping. Events and rewards
are computed from the incoming p and their own vectors before this roundoff
correction. Killed/substochastic survival mass and unnormalized measures must
not use this profile. Correction magnitude and raw mass defects are measured.
This correction is part of the declared numerical model, not a new theorem
that arbitrary invalid states represent valid distributions.

Reset interpolation and integer chunk choices are piecewise differentiable.
Tests at interpolation knots establish forward continuity and the chosen
autodiff convention, not a unique classical derivative at every knot.

## 6. Training, measurement, and claim boundaries

`PROTOCOL.json` freezes fresh synthetic episodes, model seeds, parameter
matching, the validation selection rule, tolerances, and budgets before formal
training. Reference/accelerated pairs use identical initial tensors, minibatch
streams, losses, and stable profiles. Selected checkpoints are locked before
test arrays are opened. The cached CREMA-D evaluation is descriptive because
its heldout examples were observed in previous studies.

Fixed-update fidelity and speed, equal-CPU quality, and external-architecture
quality/cost are separate questions. Whole-worker CPU includes initialization,
validation, losing checkpoints, audit, and I/O. Its total must not be added to
the training CPU that it already contains. Wall time is measured on a shared
CPU host; no joule or GPU figure is inferred from expected event counts.

Passing this contract establishes a faithful finite-model computational
improvement. It does not establish positive net value for free boundaries,
dual value channels, task-optimal stopping, a foundation model, or an advantage
over strong tuned SNN/Transformer systems.
