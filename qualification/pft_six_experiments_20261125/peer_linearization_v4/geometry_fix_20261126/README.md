# Numerical validity of peer normal equations

This additive research repair rejects impossible or numerically unresolved sufficient statistics before returning a peer update. It preserves the existing common-parent objective, envelope schema, global ridge application, deterministic roster order, and historical test/evidence files.

The parent source is [`f9b4cdb63261c5531ac255a4f7b270893c828323`](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/f9b4cdb63261c5531ac255a4f7b270893c828323), from draft PR [#7119](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/7119). The original `peer_linearization_v4/peer_equations.py` Git blob is `12a68dc3de4904a5a6bc5a331336f9070cac1410`. The code and tests belong under `qualification/pft_six_experiments_20261125/peer_linearization_v4/`.

## Confirmed parent defect

For a residual vector and its fixed linearized feature matrix, the sufficient statistics must form a positive semidefinite augmented Gram matrix:

```text
G = J.T @ J,  b = J.T @ r,  c = r.T @ r
K = [[G, b], [b.T, c]]
F(delta) = 0.5 * (c - 2 * delta.T @ b + delta.T @ G @ delta)
           + 0.5 * ridge * delta.T @ delta
```

The parent's geometry tolerance used an absolute scale floor of one. Two distinct, correctly hashed fixture contributions with zero Gram, moment `[1e-14, 0]`, zero residual energy, and one observation each passed that tolerance. With the single global ridge `1e-30`, the parent returned `delta=[2e16, 0]`, data objective `-400`, and regularized objective `-199.99999999999997`. A sum of squared residuals cannot have that negative value.

Root executed this unchanged parent counterexample once. The retained receipt `peer_parent_counterexample.json` has SHA256 `d068cf5488134e3688cce35b89b9847e6f6d096880434a10c32316cb66e29192`, wall time `0.002036531` seconds, and process CPU time `0.004289314` seconds. It performed no model evaluation or training. That failure record remains intact.

## Repair

Each contribution now receives a diagonal congruence check of the augmented Gram matrix. Negative diagonal entries are rejected. A zero diagonal requires the corresponding complete row and column to be zero. Positive diagonal entries supply square-root scales; every off-diagonal entry is divided first by the larger square root, then the smaller. This exposes cross-block inconsistencies even when feature energy and residual energy differ by many orders of magnitude.

The resulting correlation matrix is checked for finite values, Cauchy–Schwarz consistency, symmetry, positive semidefiniteness, and observation-count rank. The Gram principal block is checked even when the moment is zero. A nonzero moment must lie in the numerically resolved Gram range. Losing a nonzero value through normalization is an explicit numerical refusal.

After deterministic aggregation, the solver checks finite global statistics, a numerically resolvable positive definite regularized operator, and the solve residual. It evaluates the same objective with scaling, rejects negative or otherwise unresolved objective values, and refuses underflow that could turn a positive objective into a false zero. It neither clips eigenvalues nor projects the submitted statistics onto a different positive semidefinite matrix. Ridge remains the original value, applied exactly once.

## Observed verification

Root ran the two original tests and all eight new methods once on the original pocket4 numerical environment: Python `3.14.4`, NumPy `2.5.5`. The observed result was **10/10 passing**, with no model evaluation and no training. The recorded time is `2026-11-26T06:39:28.147262Z`; wall time was `0.167118337` seconds. Source checks before and after matched all `44/44` bound inputs.

The root-produced regression receipt has SHA256 `f34b1896e945d2c1f7182da80eb1527d1bd5a56b7e2c462849613bee82b0788f`. The retained `peer.stderr` is 1,673 bytes with SHA256 `7920cdb63578e8fb4ee82ab50905245b68569101d663970f796ab819a4bafdf3`. The scoped official `just fmt` step was a no-op and did not change tested source bytes.

The static implementer and the independent mathematical reviewer ran no additional tests or model calls. The coverage of the eight new methods is recorded in [TEST_COVERAGE.md](TEST_COVERAGE.md). Runtime duration is a regression receipt, not a speed comparison.

## Numerical scope and remaining limits

This repair deliberately refuses some mathematically valid problems when float64 cannot reliably preserve their geometry or objective. Such cases include meaningful coefficients lost during normalization, unresolved Gram ranges, poorly conditioned regularized systems, and cancellation too severe to establish a positive residual objective. In particular, the valid exact-power fixture with total `G=ridge=2^-1060`, `b=2^-500`, and `c=2^60` is refused for normalization underflow. Its exact solution is `delta=2^559`, with data and ridge objectives `2^57` each; returning zero would be incorrect.

The passing small-scale and large-scale controls establish behavior for the stated deterministic fixtures. They are not a guarantee that all finite inputs can be solved.

This change adds no new E1–E6 experiment, consumes no training budget, and leaves the exhausted historical `16/16` budget unchanged. It does not establish six-coordinate identifiability, independent cross-user adoption, a peer-aggregate nonlinear task improvement, or whole-system training speed. The prior smooth-derivative failure and existing research/production dispositions remain separate evidence.

The peer regression uses NumPy algebra. It does not qualify the unrelated shared-encoder OOD path on the workflow's Torch `2.10.0` CPU / pytest `9.0.2` environment.

