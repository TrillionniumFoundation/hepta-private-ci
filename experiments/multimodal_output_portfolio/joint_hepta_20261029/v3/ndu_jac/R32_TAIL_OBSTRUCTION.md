# Why the original Gaussian R32 cost cannot be exponentiated directly

The retained R32 target is the expected nonnegative cost `E[C]`. Its terminal
cost contains `0.1 * u_M**4 / q`, while the U3 and M8 tasks have `eps > 0`.
Conditional on the penultimate state and bounded actor action, the last update is
`u_M = mu + sqrt(h) * sqrt(2*eps) * (1 + 0.2*sin(x)) * Z`, where `Z` is standard
Gaussian and the conditional noise coefficient is at least
`0.8 * sqrt(2*h*eps) > 0`.

For any non-degenerate Gaussian `Y` and any `a > 0`, the integral defining
`E[exp(a*Y**4)]` diverges: its exponent grows as a positive quartic minus the
Gaussian density's quadratic. Since all other R32 cost terms sum to a
nonnegative quantity, `C >= 0.1*u_M**4/q`; hence `E[exp(eta*C)]` is infinite for
every `eta > 0` in these tasks. Taking reward `X = -C` therefore gives an infinite
entropic moment `E[exp(-eta*X)]`. At the terminal entropic decision this obstruction
already occurs, so it is not cured by earlier discounting or nested recursion.

Finite polynomial moments, the R32 expected-cost truncation correction, and a
finite observed Monte Carlo sample do not establish exponential integrability.
A bounded replacement experiment is a new, explicitly declared target; it does
not extend the original Gaussian target's certificate. U0/C80 do not have this
specific direct quartic-Gaussian obstruction, but their exponential integrability
would still need a separate proof and admissible risk-parameter domain.

Source: [the immutable R32 simulator](https://github.com/TrillionniumFoundation/ICLR-2027/blob/8b796bcea7038f22b20592df2d79a792a396093a/05_NDU_RL_NeurIPS/revision_20261104_r32/r31_numpy_simulator.py).
