# Combined-parameter boundary admission

Baseline: `hepta-private-ci` PR #4330 at
`1dd990bedee8a525093c1dd4008b2f00c2c5ff1c`. This is a new source revision;
the earlier analytic/JAX source manifests continue to describe that prior
revision. The current revision is identified by `results.json/source_sha256`.

Consequently, the legacy `verify_evidence.py` and `next/verify_delivery.py`
cannot pass unchanged against this new working tree: they compare the modified
analytic paths with historical digests and should report source drift. Replay
those historical manifests at the baseline commit; use the new challenge and
its source hashes for this revision. The existing `next/ridge/freeze.json`
binds its compiled table and runtime sources, not the two analytic files
changed here, and those frozen table/runtime files were left unchanged.

## Finding and correction

The earlier tests reproduced the full He–Xiong equations and checked primarily
one-parameter changes. They did not establish that every combination in the
declared JAX numeric box was a valid limited-liability solution.

A counterexample inside that box is
`r=.04, delta=.01, sigma=.08, alpha=1, tax=0, liquidity=.1,
maturity=.01, coupon=.5, principal=20`.
Equation (12) gives `V_b=22.2477116291049`, but the candidate equity at
`x=log(V/V_b)=.1` is `-26.3685742093`. The float64 implementation,
60-digit literal A5/A7 evaluation, and independent Green integral agree.
This is not a floating-point cancellation error.

At a smooth-pasting boundary the original equity ODE implies

\[
E_{xx}(0)=-2[\delta V_b-(1-\pi)C+(\alpha V_b-P)/m]/\sigma^2.
\]

A positive bracket gives negative equity just inside the continuation region.
The new admission check rejects such candidates and rejects an unresolved
near-zero sign. It does not clip the value, alter the ODE, or pretend that
smooth pasting alone proves optimal stopping. `HXBoundaryCandidate` preserves
the previous candidate formulas for explicit audits. `HXModel`, the JAX
boundary, and the JAX host parameter validator apply the admission check.
The raw-to-box transform remains only a numeric-box transform; it cannot
guarantee admission of arbitrary learned financial parameters.

## Replay and evidence

Run from `tools/hcsn` with NumPy, SciPy and mpmath installed:

```bash
python third/analytic/run_challenge.py
```

With CPU JAX installed, also run the boundary admission and parameter-gradient
checks:

```bash
JAX_PLATFORMS=cpu python third/analytic/run_challenge.py --with-jax
```

The SciPy run writes `scipy_results.json`. The complete JAX run writes
`results.json`. Neither command overwrites the historical validation JSONs.
Each output includes its source hashes and hashes of the unchanged historical
evidence. The test covers all 512 corners of the former nine-parameter box
and 200 interior combinations from seed `301026`.

The completed SciPy challenge admits 686 combinations, rejects 24 candidates
with negative equity, and rejects two without a positive boundary. All 24
negative-equity cases agree with independently reconstructed boundaries and
equity: maximum boundary discrepancy is below `3.5e-12`, and maximum equity
discrepancy is below `6.3e-11`.

The original 26 parameter cases, five free-boundary BVP cases, four debt-PDE
refinement tests, limit tests, nine parameter finite-difference tests and
Taylor-overlap tests also pass when replayed after the correction. The debt
PDE refinement orders remain approximately two.

The complete CPU JAX challenge also checks the same 712 admission decisions
and all nine baseline boundary-parameter gradients. Its first run exposed an
additional cancellation error near `B(-z_tilde)`: the maximum JAX-versus-NumPy
boundary difference was `5.74e-7`, above the unchanged `2e-7` limit. That
failure is preserved as `development_failure_jax_boundary.json`.

Both implementations now use the existing eight-point derivative-integral
evaluation over a slightly wider near-pole neighborhood, with factored
exponents. After this correction the maximum boundary difference is below
`1.4e-9`, and the scaled parameter-gradient error is below `4.7e-9`.
Five affected combinations additionally compare boundary and equity with
90-digit literal formulas; their largest equity discrepancy is below
`3.5e-8`. The completed `results.json` is the evidence for the revised sources;
the earlier SciPy and failed-JAX records retain their own source hashes.

## Scope

This closes the observed false admission of negative-equity boundary
candidates. The new condition is necessary, not a proof that every admitted
parameter has globally optimal nonnegative equity. The 712-point challenge
is adversarial evidence, not a theorem over the entire numeric box. Fixed
compiled neural templates remain fixed financial templates; this work does
not claim that arbitrary financial parameters are safely trainable.
