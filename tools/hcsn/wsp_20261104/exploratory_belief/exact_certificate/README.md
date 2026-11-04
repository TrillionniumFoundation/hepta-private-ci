# fit71: exact finite IEEE box infeasibility certificates

Both original stored sparse witnesses certify infeasibility after exact rational evaluation and a conservative correction for their nonzero stationarity residuals. No LP was solved, no candidate was generated, and no training or holdout evaluation was run.

## Result

| Margin | Stored positive weights | Exact-residual L1 (approx.) | b^T y (approx.) | Conservative upper bound |
|---:|---:|---:|---:|---:|
| 0.0 | 99 | 6.960648465696216e-15 | -0.0005149002502291977 | <= -0.0005149002502248292241130588 |
| 0.001 | 99 | 8.253362694807751e-15 | -0.001487468919283083 | <= -0.001487468919277903441097118 |

The last column is rounded upward using Decimal ROUND_CEILING; it remains strictly negative. Exact numerators and denominators, all 147 residual coordinates, exact weight norms, and interval displays are in `exact_certificate.json`.

The original box radius is the exact binary64 value `0x1.4154cc0052c50p-1` (approximately 0.6276000738520313). There are 1,185 oracle inequalities plus 294 explicit box inequalities, with 147 real unknowns. Eleven oracle-tie rows are excluded under the original tolerance. Missing support weights are exactly zero; the retained weights are not renormalized.

## Proof

Let the saved coefficient system be A delta <= b, with explicit box constraints |delta_j| <= rho. For the saved nonnegative witness y, define r=A^T y and c=b^T y. Any feasible delta would satisfy

    -rho * sum_j |r_j| <= r^T delta = y^T A delta <= y^T b = c.

The exact calculation gives c + rho * sum_j |r_j| < 0 in both cases, which is a contradiction. The proof does not require A^T y to vanish. Every multiply and sum in this check uses Fraction.from_float, and every dot product is independently recomputed by aligned integer arithmetic on dyadic float ratios.

## Exact negative bounds

Margin 0.0:

`-98635292182535146631315962931187947145147164852009 / 191561942608236107294793378393788647952342390272950272`

Margin 0.001:

`-284942435746248726048631892949793166556534907789489 / 191561942608236107294793378393788647952342390272950272`

## Provenance and scope

The pinned original `construct()` is extracted from its AST; optimizer helpers and the main program are never executed or imported. It reconstructs the finite binary64 coefficients from the pinned TRAIN fixture. The resulting coefficients are frozen in `fit71_ieee_box_evidence.npz`, and this certificate is exact for those serialized values. The original source did not supply a separately archived A,b matrix; equality to its mathematical real-arithmetic construction is not asserted.

The three source-file SHA-256 values and every evidence array's SHA-256, shape, and dtype are recorded in JSON. Source reconstruction reproduced every stored evidence array bit for bit in this runtime (NumPy 2.3.5), including the original stored radius. The source folder remains unchanged.

This proves infeasibility for these two finite coefficient systems and this closed componentwise box, with features, belief, and fixed STOP/SUBMIT scores frozen. It also rules out any smaller domain contained in this exact box. It does not prove unrestricted-head, changed-belief, continuous-law, or global-model impossibility, nor any holdout claim. The rounded binary64 radius is the domain definition; it is not identified with an unrounded real Euclidean norm.

## Reproduction

Requirements: Python >=3.10 and NumPy. The recorded generation runtime uses NumPy 2.3.5. A future platform can verify the saved coefficients without rerunning NumPy coefficient construction.

```bash
python exact_box_certificate.py verify
python exact_box_certificate.py verify --source-dir /absolute/path/to/original-study
python exact_box_certificate.py build --source-dir /absolute/path/to/original-study
```

`verify` checks the generator hash, NPZ hash, every numeric array hash, exact sparse-weight reconstruction, all exact certificate values, the independent integer dot products, and cancellation/subnormal arithmetic checks. Supplying `--source-dir` additionally checks the three pinned original hashes and reproduces every numeric array. `build` overwrites only this certificate directory's generated outputs.
