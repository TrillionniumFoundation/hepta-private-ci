# Continuous reference for the bounded impulse-control fixture

This extension compares the existing finite DP with an independently solved
continuous diffusion **for the same bounded control problem**. It does not
change the HCSN network, its fixed half-line regeneration law, numerical gates,
or the original C2 training records.

## Model and boundary equations

On [0,L], waiting follows dX = mu dt + sigma dW with reflecting endpoints and
earns g(x)=x. Intervening pays -K, waits deterministic time d with zero reward,
and resets to x_r. Discount q is positive. In the interior-threshold regime,
the intervention region is [0,b] and the continuation region is (b,L].
The common intervention value is H=-K+exp(-qd)U(x_r).

On the continuation region,

0.5 sigma^2 U'' + mu U' - q U + x = 0.

The independent ODE solution uses

U(x) = x/q + mu/q^2 + A exp(r_plus (x-L)) + C exp(r_minus (x-b)),

where r_plus and r_minus solve 0.5 sigma^2 r^2 + mu r - q = 0.
The three equations are U'(L)=0, U'(b)=0, and U(b)=H. The FP64
implementation eliminates A,C from the two derivative equations and bisects
the matching equation. The 80-digit reference independently solves all three
equations with unscaled exponential bases.

The intervention generator residual has its maximum at b and is b-qU(b).
Continuation slope and obstacle gaps are sampled and reported. Analytically,
the slope solves a linear ODE with positive forcing and zero endpoint values;
the maximum principle explains its nonnegativity in this model. Numerical
root bracketing and residuals are not rigorous interval arithmetic or a formal
verification theorem.

## What is compared

The runner retains fixed-threshold value at b=0.4, the continuous free boundary,
and 21/41/81/121-node optimal finite-DP values and boundary brackets. It also
checks the original independent value iteration at 21 nodes. Finite Bellman
residuals can be tiny while continuum value error remains material; both are
reported. The existing soft-threshold comparison remains in run_oracle.py and
keeps its own finite uniformization semantics.

The implicit derivative with respect to intervention cost includes movement
of the boundary. It is compared with an independent 80-digit central difference.
The condition number belongs to the explicit, unscaled three-equation Jacobian;
it mixes slope and value units and is not a coordinate-invariant stability
certificate. Unsupported endpoint or no-intervention regimes raise an error.

## Execution and evidence

    OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -B -m unittest qualification.hcsn_qvi.tests.test_oracle qualification.hcsn_qvi.tests.test_continuum -v
    OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -B -m qualification.hcsn_qvi.run_continuum --output qvi-results/continuum.json

The runner requires NumPy and mpmath, binds its three source files, refuses
overwriting prior results, and records its fixed limits and runtime costs.
Execution logs and output must be retained before reporting any result.
The initial implementation was prepared during an unavailable cloud executor;
source publication alone establishes no successful test or numerical run.

A successful fixture would narrow the finite-versus-continuous boundary gap.
It would not establish learned-content benefit, a neural optimal boundary,
whole-training numerical coverage, physical energy savings, or product adoption.
