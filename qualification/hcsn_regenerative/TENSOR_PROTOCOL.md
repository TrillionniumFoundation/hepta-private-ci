# Fixed-boundary regenerative tensor candidate: prospective qualification

Candidate identity: `hcsn-regenerative-tensor-20261107-1631115f163f-v1`.
Reference source: `65bf6680c77338d89cd933e2d0d032b88a3e5078` (PR #5195).
This is a new numerical candidate. It is not an identity in the original
`f355cfe2ae96b2bc9a5409f8eeb857894f1b0c5b` 170-run campaign.
This protocol is written before executing the new tensor qualification.

## Model selected

Let `X = log(V) - log(b)` and keep the boundary `b` fixed throughout each
trajectory. While active, `dX = mu dt + sigma dW`, killed at zero. At a hit,
pay the fixed hit reward, remain refractory for a strictly positive physical
duration `d`, and restart at fixed distance `a > 0`. The deadline retains only
the remaining physical horizon after both the hit and the refractory period.
Running and terminal rewards are constant and paid only while active.

Risk, the killed survivor law, repeated-reset state and both E and U use this
same generator. The forward process and nonlocal boundary condition are those
in `REGENERATIVE.md`. This candidate chooses a **fixed boundary**. It does not
solve a regenerative QVI, optimize an HX boundary, or identify financial value
with measured task utility. It implements the restricted regenerative process;
the historical financial HX stationary extension remains a separate reference.

The numerical parameter domain is `abs(mu) <= 2`, `.05 <= sigma <= 4`,
`.01 <= discount <= 4`, `0 <= horizon <= 8`, and finite `x >= 0`.
Positive discount permits an analytically integrated occupation formula.
Exact boundary and zero-time atoms are evaluated, but their derivatives are
not admitted. The domain bounds alone are not a global numerical certificate.
The successor quadrature must also resolve the requested distribution.

Trainable continuous inputs in strict interior cases are x, mu, sigma,
discount, and horizon. A diagnostic log-boundary derivative is obtained through
`x = log(V) - log(b)`; it does not authorize a time-varying boundary process.
Reset distance, refractory duration, bin edges, quadrature orders, and maximum
renewal terms are fixed hyperparameters. No gradient through discretization,
atom ownership, an integer term count, or a policy choice is claimed.

## Registered numerical checks

The central case is `x=.35, T=1.4, mu=-.1, sigma=.3, q=.15,
a=.25, d=.11, active_reward=.4, terminal_reward=.2, hit_reward=1`.
Additional cases are near-boundary `(x=1e-5,T=.7)`, short-time
`(x=1e-4,T=1e-4)`, low-noise `(x=.12,T=.8,mu=-.2,sigma=.05)`,
positive drift `(x=.4,T=1.2,mu=.2)`, and far-tail `(x=4,T=.5)`.
All other central parameters remain fixed.

1. Compare E, U, discounted hit count, active probability and discounted active
   occupation with the separately implemented FP64 reference. Absolute value
   tolerances are `2e-8` for FP64 and `3e-4` for FP32.
2. Compare first-hit and survivor probabilities with positive density integrals.
   Extreme FP32 tail underflow is recorded explicitly. Absolute probability
   agreement does not qualify relative tail accuracy or a log-risk gradient.
3. Compare autograd of a scalar combining value, risk and survivor mass against
   five-point finite differences of the FP64 reference. Central steps are
   `1e-4` and `5e-5`; both are retained. Gradient tolerances are
   `2e-5 + 2e-4*abs(oracle)` in FP64 and
   `3e-3 + 3e-3*abs(oracle)` in FP32.
4. Compare the regenerative successor with the independent scalar convolution,
   preserve upper-tail and refractory remaining-time mass, and compare time
   quadrature orders and spatial-bin aggregation. A normalized survivor vector
   cannot substitute for the original unconditional measure.
5. Compare independently refined delayed-boundary PDE values. This is an
   approximation check, not an exact continuum or floating-point proof.
6. Save model/optimizer/RNG/configuration and numerical input state, resume in
   a fresh Python process, and compare the next training block with uninterrupted
   execution. This bounded numerical fitting probe is not task-quality evidence.

Every attempt receives its own output directory, exact source SHA256 map,
software/device identity, monotonic wall time, process CPU time and terminal
status. Failed attempts are retained. A revised implementation gets a new
source hash and does not rewrite the old attempt.

## Separate scientific gates

Passing these tests can qualify the recorded bounded tensor operator. It does
not finish the original 170 runs, the 20 full-budget B audits, new mechanism
ablations, or the actual A/B/C/D x frozen/joint task experiment.

The latter requires independent training repeats, separate episode seeds,
validation-selected deployable comparators, immutable test materials and an
independent evaluator. Its predeclared minimum useful difference, retention
and complete-cost gates must pass before enlargement. Unknown physical energy
remains null and cannot be replaced with TDP. Production activation is false.

## V2 review amendment, before revised execution

V1 passed the registered ordinary cases on both CPU and CUDA. A separate
post-review stress attempt retained two failures: at
`x=.35,T=1.4,mu=-2,sigma=.05,q=.01`, FP32 U and occupation exceeded the same
`3e-4` tolerance; at `x=0,T=d` the value path admitted a time derivative at a
terminal-payoff jump. V2 rationalizes the small discounted-hit roots and
rejects x/time autodiff on exact boundary/zero-time atoms. It does not promote
FP32 arithmetic to FP64. The stress case is added to the ordinary audit and
all historical attempts remain separate. Nonfinite log probabilities from
otherwise finite extreme inputs are explicitly unresolved, not trainable zeros.

The log-boundary derivative holds log reset distance a fixed, so the absolute
reset target `V_reset=b*exp(a)` changes with b. It is not the derivative at a
fixed absolute reset target, does not solve a free-boundary/QVI problem, and
does not qualify a trainable or time-varying policy boundary.

The recovery probe proves the next block for model parameters, optimizer state,
the dedicated RNG and the consumed input-horizon schedule. Its stored active
probability is diagnostic and is not consumed as the next block's state.
Full survivor/refractory continuation and production-owner recovery remain
unqualified. Audits now preserve already completed checks if later work raises;
the recovery probe records its child deadline as a failed receipt.

V2 also refuses an observed discounted hit exceeding its undiscounted hit or a
negative occupation. These are numerical failures, not clipped probabilities.
The small-time FP32 relative-occupation and gradient limits remain explicitly
unqualified outside the recorded tested cases; an absolute gate alone does not
establish relative accuracy near zero.

## V3 review amendment, before revised execution

V2 passed 185 ordinary audit checks per device and the retained strong-drift
stress, but an independent tiny-horizon observation found a real CUDA FP32
occupation error: at `x=1e-5,T=1e-6,mu=-.1,sigma=.3,q=.15`, the value returned
approximately `1e-6` instead of `5.208050870920706e-8`. CPU FP32 rejected G>F.
The old default scalar occupation quadrature was itself inaccurate by about
`2.54e-5` relatively at this tiny scale. These observations remain preserved;
the V2 observation wrapper's successful exit does not qualify its values.

V3 uses the same killed-generator survivor S and positive dimensionless-time
quadrature for `q*T < 1e-3`: occupation is the direct integral of `exp(-qt)*S`,
and `G=F-q*integral exp(-qt)*(S(t)-S(T)) dt`. Post-release occupation integrates
`exp(-qt)*(S_(x+a)-S_x)`. Exact boundary release uses its separate atom law.
The transformation `t=T*u^2` and fixed Gauss orders 64/128 retain the input
dtype and physical-time derivatives. The unselected unstable analytic graph
is replaced by safe inputs before subset evaluation. There is no hidden
FP64 promotion, probability clipping, or state normalization.

This adds explicit numerical acceptance conditions: in each short regular
subproblem, `x/(sigma*sqrt(T)) >= 1e-3` for FP32 or `>=1e-8` for FP64; x=0
atoms are handled separately. Positive integrands and finite values must
resolve. The order difference must not exceed `rtol*abs(fine)+32*eps*T`, with
rtol `2e-4` for FP32 and `1e-7` for FP64. Otherwise the call rejects. The
per-batch `quadrature_error` reports an output-weighted order difference
estimate, not an enclosure or a global error bound. No global relative
accuracy claim follows from these gates.

The new independent short gate covers pre-release `(x=1e-5,T=1e-6,d=.11)`,
regular post-release `(x=1e-5,T=2.1e-6,d=1e-6)`, and the exactly representable
boundary release `(x=0,d=.125,T=.125+2^-20)`, with a=.25 and the same mu/sigma/q.
It uses scaled positive survivor integrals, positive elapsed-time moments for
q derivatives, deadline active mass for T derivatives, and two five-point
steps for x/mu/sigma. The oracle evaluates the represented tensor inputs and
fixed hyperparameters, while retaining requested values in the receipt.
Boundary x/T gradients remain inadmissible; the last case tests parameters.

The independent JSON gate uses relative value tolerances `3e-4` (FP32) and
`2e-7` (FP64), and gradient tolerances `4e-3` / `2e-5`, respectively, with
scale floor `abs(occupation)*1e-9` for zero derivatives. Finite-difference
reference step disagreement must be at most `1e-4` relatively. Six added unit
test methods separately use tighter case-specific gates for short values,
occupation gradients, discounted-hit density-score gradients, exact release,
batched graphs, and explicit unresolved-scale rejection. The original value,
gradient, state and refinement gates are unchanged. Revised audit and actual
fresh-process recovery must use this same frozen source set.

## V4 review amendment, before revised execution

The real V3 retry passed all 57 unit methods and the retained 12 stress checks,
but the independent short gate produced FP32 NaN derivatives after release.
Its strict JSON writer then failed, and the partial original file is retained.
A separately identified logging-only diagnostic preserved every result using
explicit nonfinite markers: 52/64 passed and 12/64 failed. CPU and CUDA each
failed the regular-release x/T/mu/sigma derivatives and released-atom mu/sigma
derivatives. Every value and FP64 check passed. The q derivatives also passed.

An anomaly-detection probe localized the actual backward failure to
SpecialLogNdtrBackward0 in the upper survivor of a later release integral.
V4 preserves the native torch.special.log_ndtr forward exactly and supplies
the mathematically identical first derivative. For z<=0, it uses
`phi(z)/Phi(z)=sqrt(2/pi)/erfcx(-z/sqrt(2))`; the positive branch uses its
ordinary well-scaled expression. Unselected branches receive safe inputs.
There is no asymptotic truncation, probability clipping, hidden FP64 promotion,
or altered generator. Nonfinite ratios or upstream products reject explicitly.
Only first-order reverse-mode differentiation is supported by this primitive;
higher-order differentiation is explicitly blocked, not silently qualified.

Four regression unit methods cover unchanged forward values, exact first
normal-tail derivatives and zero upstream products, the ordinary release
counterexample and its independent x derivative, released-atom parameter
sensitivities, and the higher-order rejection. All previous numerical gates
and independent short-gate thresholds remain unchanged. The V4 gate's JSON
serialization now preserves nonfinite observations as explicit failure
markers rather than losing subsequent rows. Its computations are unchanged.
All prior attempts and costs, including unknown, failed and diagnostic ones,
remain independent. A fresh complete audit and recovery must bind this same
revised source before recorded numerical qualification.
