# Task-driven regenerative free boundary

`neural_control.py` adds an endogenous release rule to the existing constant
log-diffusion/reset family. It maximizes discounted retention benefit minus
active maintenance/delay cost and release cost:

\[
E_y[\int_{\rm active}e^{-\rho t}(\alpha Y_t-\ell)dt
      -\sum_n e^{-\rho T_n}K].
\]

Active state has `dY=mu dt+sigma dW`. Each intervention pays `-K`, suspends
active dynamics/reward for deterministic `d`, then returns to fixed absolute
log state `a`. Task parameters stay fixed during an episode. The module
exposes `(mu,sigma,rho,a,d,alpha,ell,K)` in `PARAMETER_NAMES` order and returns
existing `PhysicalParameters` for first-passage/reset calculations.

Assume `alpha,K,rho,d,sigma>0`, `ell>=0`, and an interior boundary `b<a`.
Write `eta=exp(-rho*d)`, `kappa=(mu+sqrt(mu²+2rho sigma²))/sigma²`,
`s=alpha/rho`, `p(y)=s*y+alpha*mu/rho²-ell/rho`. A threshold policy has

\[
U_b(y)=p(y)+A_b e^{-\kappa(y-b)},\quad
A_b={-K+\eta p(a)-p(b)\over1-\eta e^{-\kappa(a-b)}}\quad(y>b).
\]

Below the trigger its value is the immediate intervention value `U_b(b)`.
Matching is `U_b(b)=-K+eta*U_b(a)`; smooth pasting sets `A_b=s/kappa`.
The resulting residual has derivative
`R_b=s*(1-eta*exp(-kappa*(a-b)))>0`. Its unique interior root exists iff
`R(a)=(1-eta)*(p(a)+s/kappa)+K>0`. The implementation requires the root's
reset distance strictly inside `(1e-4,8)`, within the inherited physical
domain; an optimum outside that domain is rejected, not clipped.

This solves the full QVI, not merely optimization within thresholds. Above
`b`, `U'=s*(1-exp(-kappa*(y-b)))>=0`, hence `U>=-K+eta U(a)` and the
continuation PDE is zero. Below `b`, the continuation residual is at most
`-sigma²*s*kappa/2<0`, and intervention attains equality. The value is C1,
has linear growth, and discounted Brownian state satisfies transversality.
With `d>0`, interventions cannot accumulate in finite time. These facts
give the verification argument for the lower-boundary policy.

`optimal_boundary` uses a monotone bracket and first-order implicit AD
`db/dtheta=-R_theta/R_b`. All eight parameters receive gradients; higher
derivatives through this custom root are unsupported. `policy_value` also
supports directly learning a threshold from task return. Remaining
refractory value is `exp(-rho*r)*U(a)`: the event cost is already paid.

Run `python -m qualification.hcsn_differentiable.neural_control_study
--output NEW.json` (one command line) for three tasks, an independent sparse
finite-difference Bellman policy iteration at three grid spacings, Lambert-W
boundary comparison, eight-parameter central differences, and direct LBFGS
threshold learning from three initial gaps. Limits precede execution in
`LIMITS`; every fit and numerical error is retained. The Bellman oracle
uses no analytic boundary or optimal-value input. Its finite upper endpoint
uses the affine particular solution, so spatial truncation remains a
separate approximation. This is the specified control task; C2, N256 and
real-encoder comparison retain their own experiments and results.

## Executed CPU results

[attempt003](evidence/neural-control-20261119/attempt003.json) records the final
source hashes and Torch 2.8.0+cpu run. All three tasks and nine optimizer
starts pass the original limits: boundary implicit/central differences differ
by at most 2.53e-10; learned boundaries differ from the optimum by at most
5.32e-9. The finest independent grid puts the trigger within 0.336 grid cells
and reset value within 1.24e-5 relative error. Four integration/gradient tests
pass in [tests-final.log](evidence/neural-control-20261119/tests-final.log).
The separate domain-expansion observation changes reset values by less than
8.2e-14. Attempt001 retains a SciPy boolean-selector construction failure;
attempt002 passed after a numeric-selector fix, without changing limits.
Attempt003 additionally reserves its output before any optimization so an
existing output cannot silently cause duplicate work.
