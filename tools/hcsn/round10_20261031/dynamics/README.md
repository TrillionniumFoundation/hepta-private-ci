# Round 10 dynamics evidence

## Completed: two reproduced source defects

`SOURCE.json` pins both upstream commits and Git blob identities. `vendor/upstream`
contains byte-exact original source, verified before every regression run.
`vendor/patched` contains narrow corrected copies. The repository-path patch is
`patches/two_reference_fixes.patch`; these copies do not activate production code.

1. The linear moving-boundary reference directly evaluated
   `(nu + sqrt(nu**2 + 2*q*sigma**2))/sigma**2`. For negative drift and tiny
   noise, subtraction lost the discount completely: four source executions
   admitted `G=1` instead of approximately `exp(-q)`. The correction uses the
   algebraically equivalent `2*q/(sqrt(...) - nu)` for negative drift. Independent
   Decimal arithmetic reproduces the cancellation. A Brownian pathwise bound
   bounds the true discounted weight around the deterministic crossing time.
   Zero-discount output is set exactly equal to its probability.
2. The repeated-event CTMC accepted impossible saved joint states whose
   no-fire active mass exceeded physical active mass (or the corresponding
   refractory inequality). The correction validates both subset inequalities
   on input and output, including zero-duration calls.

Actual result: 4 discounted-hit counterexamples, 4 rejected impossible-state
calls, 4 independent time-density quadratures, and 16 independent matrix/occupation
checks passed. `results/regression.json` preserves original outputs, corrected
outputs, source hashes, numerical errors, and runtime versions.

Reproduce from this directory:

```sh
python -m pip install -r requirements.txt
python regression_audit.py --output results/regression.json
```

The execution environment restored official `mpmath/mpmath` tag `1.3.0`, tree
`b5c04506ef0cd4a1f1213f8389ee21c9c3551582`, into a temporary dependency directory.
All 51 imported package source files matched the upstream Git blob SHA. The
recorded run used `PYTHONPATH=/tmp/hcsn_round10_deps` and Python 3.12. These
mathematical reference fixes do not establish an all-domain floating-point
certificate, native owner parity, or a trained network advantage.

## Completed: independent moving-boundary evidence

`brownian_reference.py` samples a true Brownian process with an upper firing
boundary. It samples each segment's first-hit time from the inverse Gaussian
law (Levy law at zero relative drift, with defective ever-hit mass when needed).
If a segment survives, the endpoint is sampled from the killed law by accepting
free Gaussian proposals with Brownian-bridge survival probability. It does not
replace survivors with an unconditional Gaussian or their mean.

At a hit, the process resets to an **absolute physical position** and holds there
until the actual hit time plus the fixed nonzero refractory duration. Boundary
motion continues during the hold. Release is never snapped to an observation
grid. The upper-boundary coordinate is the sign-reversed counterpart of the
lower-gap first-hit kernel: gap = boundary - position.

`finite_volume_reference.py` independently realizes the pinned v2 mathematical
contract using SciPy sparse matrix exponentiation. It has a reflecting lower
domain, upwind spatial rates, finite Erlang refractory phases, and physical
overlap remapping. A continuous boundary is approximated by left-held segments
and remapping at observation times. `NUMERICAL_SOURCE.json` pins the upstream
PyTorch source and explicitly records that PyTorch was unavailable here. This
run verifies the new SciPy realization against the independent Brownian law;
it does not claim execution of the upstream PyTorch or native owner entry point.

The registration was written before the experiment. Three prescribed boundary
trajectories used 40,000 independent paths each, with a separate 12,000-path
sampler calibration. The four joint resolutions were `(24 cells, 6 phases, 32
steps)`, `(48, 12, 64)`, `(96, 24, 128)`, and `(192, 48, 256)`. Boundary knots
were also included in the time grid.

| Trajectory | Brownian E[N] | Brownian P(N >= 1) | Finest count difference | Finest mean difference | Coarse to fine scaled difference |
|---|---:|---:|---:|---:|---:|
| Linear rise | 0.921075 | 0.752775 | 0.010978 | 0.014916 | 4.1102 to 0.6472 |
| Linear fall | 0.804625 | 0.668150 | 0.005385 | 0.009204 | 2.2474 to 0.3933 |
| Turning boundary | 1.282975 | 0.930450 | 0.015770 | 0.019917 | 4.7196 to 0.9804 |

All three finest resolutions met the registered final-metric tolerances plus
six Monte Carlo standard errors, and all three joint refinements reduced the
registered scaled difference. The 12 numerical runs' maximum mass error was
`4.58e-14`; maximum no-fire subset excess was `1.12e-16`. No state or survivor
mass was renormalized or clipped to achieve those results. Total measured
experiment wall time was 8.99 seconds in this environment.

The lower-domain coupling bounds on path-law discrepancy were `7.14e-10`,
`3.70e-6`, and `6.74e-19`. These probability bounds do **not** directly bound
unbounded moment errors. Space, time and Erlang stages were refined together;
this experiment does not separately certify each discretization error.

Additional full-distribution diagnostics are retained separately from the
original acceptance gate. At the finest registered grid, maximum first-hit CDF
differences across all observation times were `0.013245`, `0.006673`, and
`0.022740`. Terminal joint CDF differences for **no hit and final position <= x**
were `0.004802`, `0.002689`, and `0.009760`. These preserve the subnormalized
survivor law rather than comparing only its conditional mean.

The turning-boundary peak error motivated one explicit follow-up, leaving the
original registration unchanged. At `(384 cells, 96 phases, 512 steps)`, the
first-hit CDF difference fell to `0.012252`, the terminal no-hit position CDF
difference to `0.006537`, the event-count difference to `0.006923`, and mean
difference to `0.010564`. That run took 6.11 seconds. This is convergence
evidence with finite residual error, not an all-time exactness certificate.

Reproduce the independent runs in a fresh output directory:

```sh
python moving_audit.py --samples 40000 --output results/moving_new
python distribution_diagnostics.py results/moving_new
python refinement_followup.py results/moving_new
```

`results/moving_v1` contains the original registration, every resolution's state
and killed-state vectors, complete first-event/count histories, summary and
additional diagnostics. Each `*_samples.npz` stores every Monte Carlo path's
event count, first-event time (`inf` means no event), terminal position and
refractory indicator. The three sample archives total 1,617,391 bytes. JSON
records preserve 12 representative complete event/release traces per case.

The tested boundary paths are prescribed, with constant drift/noise. They are
not task-derived Bellman free boundaries. This work does not certify dynamic
boundary optimization, learned posterior sufficiency, production cost parity,
native recovery, whole-network gradients or a multimodal training advantage.
