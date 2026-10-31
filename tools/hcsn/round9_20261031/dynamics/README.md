# Continuous event integral repairs

Three actual integration failures are repaired in the Round 8 scalar event
implementation. The changes improve evaluated probabilities, repeated-event
counts, and gradients; they do not weaken the existing resolution gates.

The comparison baseline is commit
`333fb9b036b80cf5d892aed222a1aac7aad80e53`. The delivery incorporates the two
metadata corrections in `resolution_audit.py` from
`00b94d54a9b85f285298d1a964777bdecfa85385`. Those corrections are upstream work,
not a new algorithm here. `source_manifest.json` records original blob SHAs;
`upstream_integration.json` identifies the later import and prior work.

## Results and their scope

All differences below compare binary64 calculations with independently
implemented continuous references. Agreement at machine precision is not an
interval-certified error bound: reference quadrature and roundoff still matter.

| Fixed qualification | Before repair | Final result |
| --- | --- | --- |
| Two affine segments, 16 narrow transition fixtures | Maximum probability difference `3.9881847075e-5`; the integrator could report about `1e-15` | Maximum difference `1.1102230246e-16` against a second-maximum density integral |
| Three derivative step sizes for those transitions | Maximum derivative difference `0.3988085017` | `2.7755575616e-10` |
| Renewal, five noise scales from `.05` to `1e-5` | Internal quadrature rejects `sigma=1e-4` and `1e-5` despite admitted outer inputs | All five evaluate; maximum count difference `4.4408920985e-16` |
| Five renewal parameter derivatives | Smallest two noise cases unavailable | Maximum difference `8.1931617046e-10` against independent finite differences |
| Seven recovery means from `.5` to `5e-7` | Maximum count difference `1.61874101896`; recovery gradient can incorrectly be zero | Maximum count difference `1.7763568394e-15`, gradient difference `2.8273827724e-11` |
| Physical clock factors `.01, .1, 1, 10, 100` | New covariance check | Count, first-hit probability, discounted value, and transformed gradients agree within `4.4408920985e-16` |
| Recovery split into `1..64` physical intervals | Existing semigroup extended across seven partitions | Maximum probability difference `2.6645352591e-15` |
| Behavioral regressions | Existing 11 tests | All 15 existing and new tests pass |

The probability, noise, and derivative protocol was fixed in `protocol.json`
before changing the tested production algorithms. A later recovery-scale sweep
found a separate unresolved layer. Its fixed cases and tolerances are in
`recovery_scale.PROTOCOL`; both the original and intermediate failures were
recorded before adding recovery knots. No tolerance was relaxed to admit a
failure.

### 1. Follow the second segment's transition

`two_segment_first_hit` formerly placed quadrature panels only around the first
segment's endpoint distribution. For the fixed first segment `(1, 0, .5)` and
second segment `(epsilon, (1+.5*z)/epsilon, .5)`, a crossing near an existing
panel endpoint can be missed entirely. The cases include `z=0 +/- 1e-4` and
`z=+/-1 +/- 1e-4`, at `epsilon=1e-8` and `1e-10`.

The repaired integral uses the standardized first-endpoint coordinate and
places additional panel boundaries at the second crossing and offsets measured
in its own noise scale. Negative relative drift also gets knots for its
near-boundary decay scale. It integrates the positive killed density; there is
no probability clipping or renormalization. The two omitted Gaussian tails
are separately bounded by the requested `tail_tolerance`.

The reference exchanges the order of integration: it averages the closed
first-segment killed-endpoint CDF against the second-segment Brownian maximum
density. It does not call either tested first-hit function. This finite-noise
reference avoids treating a zero-noise limit as the exact target.

The need for second-leg crossing knots was already documented in the separate
`experiments/hcsn_hx_unified_v3/P0_SECOND_LEG_TRANSITION_GATE.md` work at commit
`946ec0ed3c58c021f38c231cbb2a9d389422c68c`. This delivery integrates the idea into
the different Round 8 scalar kernel, with counterexamples inside its stated
dimensionless domain and an independent density reference. It does not claim
that the general idea originates here.

### 2. A first-passage coordinate for low-noise renewal

For positive drift, let `d` be the accumulated active distance and use

\[
z=\frac{d-\mu t}{\sigma\sqrt t},\qquad
c=\sqrt{\sigma^2z^2+4\mu d}.
\]

Solve the quadratic for `sqrt(t)` using its stable positive root. The hitting
density times the Jacobian becomes

\[
f_\tau(t)\left|\frac{dt}{dz}\right|
=\phi(z)\left(1+\frac{\sigma z}{c}\right).
\]

For event `n`, convolve this density with the Erlang CDF of shape
`phases*(n-1)` at the remaining time. This retains an order-one integration
width as noise decreases, instead of differentiating an increasingly narrow
hit CDF in recovery-time coordinates. Gap, reset-gap, drift, noise, and recovery
mean derivatives are differentiated analytically under this integral. The
Erlang CDF is zero at the moving lower limit, so its boundary term is zero.

Since the density factor lies in `[0,2]`, cutting the standard coordinate at
`+/-12` contributes at most `4*Phi(-12)` per included probability term. The
new `integral_truncation_upper_bound` reports this separately from the existing
renewal-count tail bound. Neither bound certifies a derivative tail.

The independent reference integrates the inverse-Gaussian density in log time
against the Erlang CDF. Its transform, cutoff bound, and numerical derivative
path differ from the tested implementation. At `sigma=1e-5` the count is
`2.3801330530031177`; the deterministic-active-time limit is
`2.380133053040952`. Across the last three noise scales the observed count
difference shrinks approximately quadratically. This is a fixed-fixture limit
check, not a uniform small-noise theorem.

Nonpositive drift retains the original recovery-time algorithm. The repair
does not claim that every scale of that fallback is qualified.

### 3. Follow fast recovery too

Changing only the hit-time coordinate leaves a different narrow layer when
the recovery CDF approaches a step. An intermediate implementation gave
`dcount/dmean` almost zero at recovery mean `5e-6`, while the independent value
is approximately `-3.18366490385634`.

The final integral also maps fixed Erlang quantiles into the first-passage
coordinate and uses them as panel boundaries. This resolves both sides of the
convolution without altering the probability law. Splitting an integral at
parameter-dependent internal knots does not add derivative terms: adjacent
panel boundary contributions cancel.

The new reference integrates in `x = recovery_rate * recovery_time`. The Gamma
density then has a fixed scale; it is convolved with a closed first-hit CDF.
Its recovery-mean derivative uses the first-hit density directly, not a finite
difference or the tested normal-coordinate derivative. Forty-eight renewal
terms have a common count-tail bound `2.3490835751e-13` for these fixtures.

At recovery mean `5e-7`, the original code returns count `0.9955580343296851`
and zero recovery gradient. The final code returns count `2.6142990532851265`
and gradient `-3.18371252948985`, agreeing with the independent reference to
about `9e-16` and `2.6e-11`, respectively. The intermediate failure is retained
and reconstructible from `evidence/low_noise_stage.patch` applied to the
original `renewal.py`.

## Spatial refinement remains a separate qualification

The existing fixed protocols were rerun with explicit current source hashes.
They establish the following numerical evidence at their registered regular
parameter groups; they do not establish all-domain continuous convergence.

| Quantity family | Discretization | Finest intervals | Maximum absolute difference | Last observed order |
| --- | --- | --- | --- | --- |
| First-hit probability, discounted value, and four derivatives | Upwind | 640 | `0.002542187438` | `0.96329..1.01910` |
| Same six quantities | Fitted | 640 | `0.000031531708` | `1.99918..2.00053` |
| Repeated count and four derivatives | Fitted | 576 | `0.000109499155` | `1.99970..2.00008` |
| Repeated count and four derivatives | Upwind | 576 | `0.005311137927` | `0.98624..0.99780` |
| Same upwind protocol, one additional refinement | Upwind | 1152 | `0.002664338575` | approximately `0.993..0.999` |

The upwind-576 row **fails** its unchanged `.005` threshold. Its complete
failed result remains in `final_renewal_resolution.json`; the 1152 extension
references that file by hash, and passes the original threshold. The fitted
576 result passes independently. No original failure is replaced.

Every registered low-noise CTMC grid from 15 through 255 still fails the
unchanged local-variance gate. Integral repairs do not remove artificial
diffusion from those chains. Nonlinear moving boundaries, coupled neurons,
shared noise, hard-event pathwise gradients, and a uniform derivative-tail
certificate remain outside this delivery.

## Evidence index

Authoritative final records are:

- `evidence/final_repair.json`: two-segment and low-noise renewal comparisons.
- `evidence/recovery_scale_verified.json`: fast-recovery values and gradients.
- `evidence/final_clock.json`: physical units and recovery partitions.
- `evidence/spatial_resolution_verified.json`: first-hit/value spatial refinement.
- `evidence/final_renewal_resolution.json`: repeated-count refinement, including the expected upwind-576 failure.
- `evidence/final_renewal_extension.json`: unchanged-threshold upwind-1152 continuation.
- `evidence/final_tests.json`: command, runtime, current hashes, and all 15 passing tests.

`before_repair.json`, `recovery_original_failure.json`, and
`recovery_normal_only_failure.json` are negative controls. The other replay and
intermediate verification files retain their own exact source hashes and
reflect the earlier integration stages; their presence is not an additional
claim about the final source. Evidence writers create files exclusively and
refuse to overwrite an existing result.

## Reproduction and review stages

Run from the repository root with NumPy and SciPy available. The recorded
runtime is Python 3.12.14, NumPy 2.3.5, and SciPy 1.17.0.

```bash
python -m unittest tools.hcsn.round8_20261031.event_dynamics.test_event_dynamics tools.hcsn.round9_20261031.dynamics.test_dynamics_repair -q
python -m tools.hcsn.round9_20261031.dynamics.audit --output /tmp/hcsn-r9-recheck/repair.json
python -m tools.hcsn.round9_20261031.dynamics.recovery_scale --output /tmp/hcsn-r9-recheck/recovery.json
python -m tools.hcsn.round9_20261031.dynamics.clock_scaling --output /tmp/hcsn-r9-recheck/clock.json
python -m tools.hcsn.round8_20261031.event_dynamics.resolution_audit --output /tmp/hcsn-r9-recheck/spatial.json
python -m tools.hcsn.round8_20261031.event_dynamics.renewal_resolution --output /tmp/hcsn-r9-recheck/renewal.json
python -m tools.hcsn.round8_20261031.event_dynamics.renewal_resolution_extension --baseline /tmp/hcsn-r9-recheck/renewal.json --output /tmp/hcsn-r9-recheck/extension.json
```

The renewal-resolution command intentionally exits with status 1 for the
recorded upwind-576 threshold failure; the extension is the next separate
command. Use a new output directory for a later run.

The production diff separates naturally into two small review stages: the
two-segment composition repair in `event_kernel.py`, then the renewal
coordinate and recovery-quantile repair in `renewal.py`. Independent reference
programs, frozen protocols, and generated evidence form a separate validation
stage. No remote write or production owner modification was performed by this
lane.
