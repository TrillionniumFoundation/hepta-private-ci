# Killed nodal spatial generator: a separate repair primitive

The existing Q P R HCSN repeatedly reconstructs a uniform spatial density.
The strict all-visit study in #6073 rejected 14,336/14,336 positions at its
unchanged 1% continuation-value gate. This new research primitive retains a
nodal distribution under one fixed generator. It does not change that result
or replace the original operator, checkpoint or training traces.

For nodes x_i=i*h on [0,L], the downward/upward rates are
sigma^2/(2*h^2)-mu/(2*h) and sigma^2/(2*h^2)+mu/(2*h).
The diagonal is minus their sum. The two endpoints are distinct absorbing
states. Both rates must be nonnegative; otherwise the grid is rejected.
These rates match the drift and local infinitesimal second moment at interior
nodes. This is a spatially discretized process, not the original diffusion.
With row masses the transition is exp(t*Q), so composing times evolves the
same finite process without intermediate density reconstruction. The API
uses SciPy's matrix exponential, with no clipping or renormalization.

The discounted lower-hit transform solves
(q*I-Q_interior)*phi=down*e_1, with phi(0)=1 and phi(L)=0.
An independent continuous finite-interval BVP reference is
exp(-mu*x/sigma^2)*sinh(kappa*(L-x)/sigma^2)/sinh(kappa*L/sigma^2),
where kappa=sqrt(mu^2+2*q*sigma^2). The implementation uses stable exponential
differences. The implicit linear-system derivatives with respect to mu,
sigma and q are checked against two central-FD steps. These are derivatives
of the discrete solve, not Torch AD or full network gradients. Two-sided
partials are refused at a zero-rate edge of the feasible domain.

## Actual local probe

The retained RESULT contains all reference/discrete values for 36 synthetic
combinations: drift -0.4/0/+0.4, discount .01/.3/2, 16/32/64/128 intervals,
L=2 and sigma=.6. Across these nine fixed physical combinations, each
grid doubling reduces maximum absolute transform error to less than .3 of
the preceding error. At 128 intervals, the maximum absolute error is
4.2076805424839936e-5. These are absolute discounted first-hit-transform
errors on a finite interval; they are not the old perpetual continuation
metric, relative rare-tail bounds or a replacement for its 1% gate.

For 24 intervals and the six-gap irregular schedule
.001,.003,.02,.04,.08,.16, maximum row total variation between composed and
single transitions is 2.3680974444838937e-15 across the three drift signs.
The largest row-mass residual is 3.9968028886505635e-15. Seven tests passed,
including local generator moments, signed content and probability transport,
finite-domain refinement, two-step FD partials, zero-drift continuous
sensitivity, input rejection, and an explicit upper-tail semantic mismatch.

An independent same-session reviewer checked the BVP and implicit derivatives
and found an initially accepted huge finite discount producing NaN. The
published version restricts the research domain and rejects that counterexample.
This review is not external scientific replication. Raw final test output,
probe output, and source/format identities are retained under
evidence/spatial-generator-20261112. Tests precede final formatting; formatting
preserves the Python AST. Hosted checks on the new SHA remain separate.

## Deliberate limits and next integration gate

The upper endpoint kills paths. It is **not a returning exponential tail**.
The included test demonstrates a nonzero mismatch to the half-line hit law.
Content conservation includes both cemetery states and does not imply active
memory retention. There is no reset, deterministic refractory phase, filtering,
network training, optimal control, complete cost comparison or energy claim.
The research input box is L in [.001,8], |mu|<=2, sigma in [.05,2], q in
[.001,4], time in [0,2], with 4..512 intervals; tests qualify only the recorded
fixtures, not every combination in that box. More intervals change actual
state bytes, so this result is not an equal-budget superiority claim.

The next full candidate must integrate a returning-tail/truncation treatment,
exact-age release/reset flux, and probability plus signed content in one
shared operator, then repeat unchanged-threshold whole-visit and gradient
qualification. Original C2 independent full-training replay count stays zero.
Status: research only, HOLD_NO_GO for replacement, merge or adoption.

Reproduce from this source:

```bash
python -B -m unittest qualification.hcsn_boundary_audit.test_spatial_generator -v
python -B -m qualification.hcsn_boundary_audit.probe_spatial_generator --output NEW.json
```

Runtime used locally: Python 3.12.14, NumPy 2.3.5, SciPy 1.17.0.
SciPy matrix-exponential implementation reference:
https://docs.scipy.org/doc/scipy/reference/generated/scipy.linalg.expm.html
