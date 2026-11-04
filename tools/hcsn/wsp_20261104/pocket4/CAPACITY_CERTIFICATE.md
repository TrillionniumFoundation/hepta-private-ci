# Finite-row certificate for the frozen Current100k value readout

This certificate concerns one exact, already viewed, 54-row input/target array.
It is not an out-of-sample, market-return, policy-value, or NDU guarantee. It
neither changes the frozen prospective protocol nor approves any model.

## Statement and definitions

Let the feature matrix be \(X\in\mathbb R^{n\times d}\), the target vector in USD
be \(y\), and the readout be \(p=100(Xw+b\mathbf1)\). Assume the **joint** Euclidean
constraint \(\|(w,b)\|_2\leq 0.1\). The stated decimal radius is the mathematical
premise; a runtime that permits a tolerance above it must use that larger radius
when applying this certificate.

All standard deviations here are population standard deviations of the finite
array, with **ddof = 0**:

\[
 s(v)=\frac{\|Cv\|_2}{\sqrt n},\qquad
 C=I-\frac{\mathbf1\mathbf1^T}{n}.
\]

Because \(C\mathbf1=0\), the intercept cancels. The joint constraint implies
\(\|w\|_2\leq0.1\), even if the entire norm cannot be spent on weights in an
actual fitted head. Thus relaxing the allocation to weights is conservative:

\[
 s(p)=\frac{100\|CXw\|_2}{\sqrt n}
 \leq\frac{100(0.1)\sigma_{\max}(CX)}{\sqrt n}.
\]

Orthogonal projection cannot increase norm, and the reverse triangle inequality
applies to the centered vectors. Neither target nor prediction needs zero mean:

\[
 \operatorname{RMSE}(p,y)
 =\frac{\|p-y\|_2}{\sqrt n}
 \geq\frac{\|C(p-y)\|_2}{\sqrt n}
 \geq |s(y)-s(p)|
 \geq \max(0,s(y)-B),
\]

where \(B\) is the preceding prediction-standard-deviation upper bound. The
factor 100 is the original readout-to-USD conversion, applied once. Targets in
the private fixture are already in USD.

## Clipping

For any scalar vector \(v\), finite-array variance has the pairwise identity

\[
 s(v)^2=\frac{1}{2n^2}\sum_{i,j}(v_i-v_j)^2.
\]

If \(f\) is a fixed scalar 1-Lipschitz map, each squared difference after the
map is no greater. Hence \(s(f(v))\leq s(v)\). In particular, clipping to
\([-15,15]\) cannot increase prediction standard deviation. Applying the same
reverse-triangle argument to the clipped vector gives the same lower RMSE
bound. No assumption about the clipped mean is used.

## Avoiding an uncertified floating SVD

The original float64 SVD gave \(\sigma_{\max}(CX)\approx0.26033355736648495\),
leading to the numerical bound 22.910840118209617 USD. A floating SVD value alone
is not a rigorously outward-rounded upper bound, so the public reproduction
does not rely on it for its certified result.

Every stored F32/F64 value is first represented as an exact integer divided by
a power of two. With a common denominator, centering is performed with integer
arithmetic: \(CX=A/D\), where \(A=nQ-\mathbf1\mathbf1^TQ\). The code forms
\(G=(CX)(CX)^T\) using arbitrary-precision integer multiplication and the exact
denominator. Since \(G\) is positive semidefinite,

\[
 \lambda_{\max}(G)^{16}\leq\operatorname{tr}(G^{16}),\qquad
 \sigma_{\max}(CX)\leq\operatorname{tr}(G^{16})^{1/32}.
\]

The target variance is also an exact rational. Root bounds use integer
comparisons on a 24-digit decimal grid; the prediction bound is rounded upward
and target standard deviation downward before subtraction. The reported
decimal inequalities therefore include rounding direction, rather than
treating ordinary float output as an exact proof.

| Aggregate | Certified value in USD, except the singular-value bound |
|---|---:|
| Rows / feature width | 54 / 768 |
| Singular-value upper bound | 0.260333558963440829305536 |
| Target standard-deviation lower bound | 23.265109217360431916085369 |
| Prediction standard-deviation upper bound | 0.354269101323993336674334 |
| **RMSE lower bound, raw or clipped** | **22.910840116036438579411035** |

This impossibility statement applies to the exact stored finite arrays and
the stated affine-head class and norm constraint. Changing representation,
output scaling, norm budget, evaluation rows, targets, or architecture requires
a new certificate. It does not show that a new representation will generalize.
It also does not prove that the features contain no predictive information:
information can be present at a small amplitude while the permitted readout
norm prevents its use. The verified obstruction is the combination of these
finite features, this scaling, and this norm budget, not a universal diagnosis
that the encoder is defective or must be retrained.

## Declared radius, admission tolerance, and scope

Inspection of the actual source distinguishes three contracts:

- `financial_value_train.py` projects the joint weight/bias norm to 0.1 during
  training, then rejects a final computed norm above 0.100001. The financial
  forward predictor applies the same 0.100001 threshold using an FP32 norm.
- `current100k_study.py` checks nonconstant fitted heads with an FP64 norm
  against 0.100001. Constant baselines are explicitly exempt from this norm
  rejection; their prediction variance is zero regardless of intercept size.
- The frozen weight-shadow loader verifies hash, shape, dtype, and finite
  tensors. It does not impose a universal norm cap on every possible shadow
  head. The certificate must not be generalized to arbitrary shadow artifacts.

Accordingly, a second certificate uses the tolerance envelope **r = 0.100001**:

| Tolerance-envelope aggregate | Certified USD bound |
|---|---:|
| Prediction standard-deviation upper bound | 0.354272644015006576607701 |
| **RMSE lower bound, raw or clipped** | **22.910836573345425339477668** |

This second theorem assumes the true Euclidean norm is at most that radius.
A floating norm check alone is not a formal guarantee about every possible
accepted artifact. `head_norm_scope_verification.json` separately checks the
private fixture's parent and three exact-fit heads with exact rational sums of
squares, both in stored F64 form and after the native gate's F32 conversion.
All eight representations satisfy the 0.100001 envelope. Some lie a few
rounding units above the nominal 0.1 radius, which is why the operational
certificate is reported separately.

The source hashes and qualified admission contracts are recorded in
`norm_admission_scope.json`. Neither this inspection nor the certificate changes
any live admission code or frozen head.

## Reproduction and privacy

`finite_readout_capacity_certificate.py` reads only a caller-supplied, hash-pinned
private fixture and emits aggregate values. The fixture must not be committed.
`private_input_manifest.json` describes its shape, provenance hashes, sorting,
and unit conversion without disclosing weights, features, labels, command IDs,
account identifiers, or source machine paths.

```sh
python finite_readout_capacity_certificate.py \
  --fixture /secure/path/native-gate-fixture.safetensors \
  --fixture-sha256 205bb2d9d1329c5a4ee134ce12146c29e842da80a8662a8e3533e0b85a4bd90a \
  --radius 0.1 --output-scale 100 \
  --output /new/path/finite_capacity_certificate.json

python -m unittest discover -s . -p test_finite_readout_capacity_certificate.py -v
```

Use `--radius 0.100001` and a new output filename to reproduce
`finite_capacity_certificate_operational.json`.

The actual certificate was computed with Python and NumPy 2.3.5 in about 0.41
seconds. Five synthetic tests cover exact integer-root enclosure, large
near-perfect powers, feature/target translation invariance, constant-feature
degeneracy, and clipping variance. No accelerator or gradient computation is
needed. These checks validate the numerical certificate, not future efficacy.
