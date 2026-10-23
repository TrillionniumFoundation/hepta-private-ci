# conditional_ce finite numerical repair

Base: #3601 `4e49a5aa5025807d289b8219d049125327d3fbdd`. Compared separately with #3602 `a0e53fedc2fe5ed275c804bdb4054fb059699ec6`; their overlapping implementations were not stacked. This source branch is independent of #3603. Final source SHA: `2c04e4a16c837f16bcb9087a3e8b513a2086ff53`; tree `049be22f80c3cbe081d2257d0d351b88362063fd`. Both remote source files were byte-verified and the exact source rerun passed all 62 v4 tests, scoped Ruff, compileall, formatting applicability and diff checks. The source worktree was clean.

## Reproduced defects and bounded change

Both candidates produce `-3.0685281944005467e307` for values `(-1e308,1e308)`, probabilities `(.5,.5)`, gamma `1e-308`, versus exact-binary Decimal reference `-4.3378083048302717e307`. At gamma `1e-320`, both produce infinity instead of `-4.999944335913415e295`. With values `(-1e300,1e300)` and gamma `1e-320`, both produce zero instead of `-4.999944335913415e279`. `baseline.txt` preserves both exact sources' outputs and 120-digit references.

The span and anchored differences overflow before tiny-gamma scaling. Separately, near-neutral anchor cancellation erases representable risk premia. The repair retains the ordinary float evaluation for regular inputs; overflowing spans, near-neutral dimensionless spans, and very small supported probabilities use Decimal exponential utility with exact binary inputs. Precision accounts for both scaled span and smallest positive probability. There is no mean shortcut, clipping to bounds, or rejection of previously finite supported outcomes. A private Decimal context prevents caller precision, rounding, exponent limits, or traps from changing this float API.

Independent review caught additional defects in an intermediate implementation: tiny positive mass was lost, sometimes returning a value above the support bound. A 90-case expanded matrix also found three existing ordinary-path rare-outcome cancellation failures. All were included in the repair and regressions. Original counterexamples and initial failing matrix remain alongside the final 90-case matrix with no failures. See `independent-review.md` for review chronology and final disposition.

Only `portfolio.py` and new `test_extreme_risk.py` change in the source PR. Existing tests are retained, including #3597's inverse-scale counterexample. The #3602-specific scaled-span approximately 10 regression is included without stacking that implementation.

## Validation and commands

Linux x86_64, Python 3.12.14, Ruff 0.15.13; Decimal is standard library, no new dependency, provider connection, model download, credentials, hardware claim, merge, or deployment. Commands from repository root:

```sh
python -m unittest discover -s experiments/multimodal_output_portfolio/v4 -v
/workspace/verification-3567/pyenv/bin/python -m ruff check experiments/multimodal_output_portfolio/v4/portfolio.py experiments/multimodal_output_portfolio/v4/test_extreme_risk.py
python -m compileall -q experiments/multimodal_output_portfolio/v4
/workspace/cargo/bin/just fmt
git diff --check
```

Full v4 suite: 62 passed. Scoped Ruff passed; compileall and whitespace checks passed. `just fmt` reported no changed Rust files requiring formatting. The default Python environment initially lacked Ruff; the existing verification environment supplied Ruff, without an installation or gate change. Independent review ran the ten new tests and a 90-case matrix against a direct, unanchored 2000-digit oracle. The committed regressions use a direct 1500-digit oracle, independently formulated from the production shifted algorithm. Recorded cases cover opposite extrema, subnormal gamma/probabilities, zero-mass extrema, both sides of scaled-span `1e-4`, translation, bounds, ordinary risk and near-neutral behavior.

## Deliberately unresolved boundaries

Probability mass semantics were already inconsistent: near-neutral evaluation normalizes tolerated near-unit mass, while ordinary and zero-risk evaluation use raw mass. This change preserves and explicitly tests those conventions. The Decimal overflow path selects the convention using its finite dimensionless span. It does not claim to unify that contract; global normalization would change existing policy semantics and needs separate approval/validation. Raw-mass ordinary CE need not satisfy normalized-law bounds.

These finite regression and boundary-matrix results are not an exhaustive error proof or correctly-rounded guarantee for every binary64 input. High-precision branches have additional CPU cost; no production performance qualification was run. Whole repository/Rust/native-runtime/platform/hardware tests are not part of this Python-only change. No scientific/model effectiveness or four-experiment acceptance conclusion follows. Preserve DRAFT / SHADOW_ONLY / DENY_ALL / HOLD_NO_GO. Dedicated hosted CI must be attributed to the new exact source, never transferred from #3601/#3602.
