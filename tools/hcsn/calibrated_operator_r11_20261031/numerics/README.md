# R11 full He–Xiong numerical training qualification

**The registered FP64 and mixed-precision fixtures pass. Native FP32 internal
arithmetic still fails.** This directory implements and differentiates the
complete financial Eq. (8), (9), (12), (A5), and (A7). It does not replace equity
or the rollover boundary with an isolated first-passage activation.

The final machine-readable result is `SUMMARY.json`. The complete final matrix
is the archive member `FINAL_RESULTS.json` in `EVIDENCE_ARCHIVE.json`; the same
index also preserves both failed development matrices. All byte chunks are
losslessly verified and below the repository file-size limit.

After freezing the kernel, a separate registered 128-point Latin-hypercube
stress also passed all 512 rows in each FP64/mixed32 mode, with no rejected
points. Its full results and limitations are in `STRESS_REPORT.md` and
`STRESS_SUMMARY.json`; it does not establish a uniform theorem for the box.

## Source identity

The inherited implementation is pinned to commit
`4f96f7a91895ba3aed12539d323b62f6705bbb36` in
[hepta-private-ci](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/4f96f7a91895ba3aed12539d323b62f6705bbb36/tools/hcsn/analytic).
`UPSTREAM_FILES.json` records Git blob identities and independently recomputed
SHA-256 values. Every fetched source was verified against its Git blob hash.
The original JAX report's 14/14 FP64 and 0/14 FP32 results are inherited evidence;
**JAX was not installed or rerun in this environment.**

The new implementation uses NumPy/SciPy and an explicit scalar forward-mode AD
algebra. The 80-digit reference separately evaluates the literal K/k expressions
from A5/A7, whereas the tested kernel uses stable regroupings. The reference
Jacobian uses symmetric differences at relative steps `1e-18` and `5e-19` in
80-digit arithmetic; the maximum scaled change under step halving is
`6.14e-36`. This is a numerical cross-check, not a proof of a uniform error bound.

The formula source is [He and Xiong (2012), Rollover Risk and Credit Risk](https://www.princeton.edu/~wxiong/papers/rollover.pdf).
Its financial interpretation is retained. A positive locally admissible boundary
is a necessary stopping check, not a global optimal-stopping verification theorem.

## What was repaired, including the failed attempts

The initial C2 blend of the inherited fourth-order Taylor evaluation and A7
passed the original 14 parameter cases. The added joint corner
`maturity=.01, liquidity=.0001` failed: the maximum scaled Jacobian error was
`8.53e-5`, above the frozen `2e-5` limit. This is preserved in
`DEVELOPMENT_AUDIT_01.json`, with `DEVELOPMENT_KERNEL_01.py.gz` and
`DEVELOPMENT_AUDIT_RUNNER_01.py.gz` restoring its exact source bytes.

The second attempt used an ODE-derived tenth-order Taylor evaluation. It reduced
the maximum error to `2.35e-5`, but still failed FP64 at the new join. It is
preserved as `DEVELOPMENT_AUDIT_02.json` with the corresponding `_02.py.gz` source
snapshots. `RESULTS.json` is a byte-identical historical alias of that second
failed matrix, not the final result.

The final repair addresses the underlying A7 cancellation. If `N(u)` is the A5
numerator and `N(z)=0`, then

`N(u)/(z-u) = -integral_0^1 N'(z-t*(z-u)) dt`.

Near this removable singularity, eight-point Gauss integration evaluates the
analytic derivative. Forward AD differentiates the complete calculation,
including the moving integration locations. No liquidity floor or denominator
epsilon is introduced. The stopping boundary still comes from Eq. (12).

The local equity evaluation uses the original ODE recurrence

`E^(n+2)(0) = (2*r/sigma²)*E^n(0) - 2*a*E^(n+1)(0) - (2/sigma²)*flow^n(0)`.

The flow derivatives include the complete Eq. (8) debt forcing. The first two
equity coefficients are exactly zero. The tenth-order approximation and A7 are
joined with a quintic C2 weight over half to all of
`min(.002, .02*sigma*sqrt(maturity), .05/(1+abs(a)+zt))`.
This C2 statement concerns the numerical join in log-distance. At the financial
default boundary, the zero-extended equity is C1, while the constant-extended
F/G risk fields remain non-C1. The implementation does not hide that derivative
jump or reinterpret it as a smooth-pasting put.

All three protocols were written before their corresponding matrix runs. The
final protocol keeps all previous states and gates and adds the new join probes.
The two failures were not deleted or relabeled as successful runs.

## Final measured matrix

There are 18 parameter cases: the original 14 and four maturity/liquidity joint
corners. Each mode has 432 registered records across log-distance, both old and
new numerical joins, fixed `V=100`, and fixed asset values just above the moving
boundary. Repeated state locations are retained; these are deterministic
numerical fixtures, not independent statistical samples.

| Internal/interface arithmetic | Cases passing every record | Maximum scaled value error | Maximum scaled Jacobian error |
| --- | ---: | ---: | ---: |
| FP64 | 18/18 | 1.322e-11 | 3.986e-8 |
| FP32 throughout, audit only | 0/18 | 1.629e-2 | 6.181e1 |
| FP32 input/output, FP64 complete kernel | 18/18 | 5.666e-8 | 6.884e-8 |

The denominator in these errors is `max(1, abs(reference))`; tiny values are
therefore assessed in absolute error, not relative tail accuracy. FP64 value
and Jacobian gates are `2e-8` and `2e-5`. The FP32 interface value gate is `8e-7`
and its Jacobian gate is `2e-5`; this is an explicit interface-precision contract,
not a claim that FP32 outputs satisfy FP64 absolute precision.

FP64 maximum absolute errors in `[boundary, equity, F, G, debt]` are
`[3.411e-13, 2.196e-11, 3.287e-14, 3.287e-14, 7.276e-12]`.
For the mixed interface they are
`[3.595e-6, 1.872e-5, 2.970e-8, 2.974e-8, 2.374e-4]`.
The debt value can be large in the short-maturity fixtures, so a small relative
FP32 rounding error need not be a small absolute monetary value error.

The full fixed-V Jacobian contains all nine parameter derivatives, including
the derivative of the endogenous boundary. A separate regression checks the
chain rule between fixed asset and fixed log-distance coordinates.

The mixed interface casts represented inputs into FP64, computes values and
tangents there, and returns FP32 values/tangents. The reference uses exactly the
same represented inputs. Its cast VJP error is `1.40e-7`; realized FP32 secants
at two finite step sizes have scaled errors `0.00144` and `0.00197`, below the
registered `0.01` quantized-secant gate. This uses the standard numerical AD
convention for a cast. It is not a mathematical derivative of the discontinuous
rounding map. No surrogate spike gradient is introduced.

## Proposed research training domain

| Parameter | Box inspected |
| --- | --- |
| r | [.04, .15] |
| delta | [.01, .2] |
| sigma | [.08, .8] |
| alpha | [0, 1] |
| tax | [0, .6] |
| liquidity = xi*k | [.0001, .1] |
| maturity | [.01, 20] |
| coupon | [.5, 10] |
| principal | [20, 100] |

The admitted API checks this box, finiteness, positive boundary, and resolvably
negative boundary cashflow. It does not assert every combination in the box has
been numerically qualified. State fixtures cover log-distance 0 through 2 and
the listed fixed assets. Other states, correlations and time-varying financial
coefficients require additional evidence.

Zero liquidity, liquidity `1e-8` or `1`, maturity `1e-6` or `1000`, and sigma
`1e-5` are explicitly rejected in all three modes: 18/18 rejection checks pass.
Some of these have meaningful mathematical limiting models; they are rejected
because this implementation has not qualified them, not because the original
financial model is necessarily undefined there. Internal FP32 remains excluded
from the proposed training use even inside the box.

## Actual 30-step full-kernel optimization

`TRAINING_FINAL_RESULTS.json` contains every parameter vector, actual AD
gradient, predicted output, accepted update and line-search attempt. It fits
all five financial outputs at three fixed asset states using sigma, liquidity
and maturity. The targets come from the independent high-precision formulas.
All other financial parameters remain at the inherited baseline.

| Mode | Initial loss | Final loss | Reduction | Accepted updates / invalid proposals |
| --- | ---: | ---: | ---: | ---: |
| FP64 | .0097795527 | .0000682389 | 99.3022% | 30 / 0 |
| Mixed32 | .0097795549 | .0000682388 | 99.3022% | 30 / 0 |

Both runs made 49 explicit line-search proposals; rejected proposals increased
the loss and were retained. These results show that the complete kernel can
participate in an actual optimization loop. They do not show a content-learning
advantage, statistical generalization, identifiability, or a globally optimal
parameter fit.

The separate R11 task controller uses finite CTMC parameters and a readout. The
separate R11 content study uses frozen-window first-passage gates. Neither is
silently identified with the full-HX optimization in this directory.

## Reproduction and evidence verification

Use Python with `requirements.txt`; recorded library versions are in the
summary. In this session mpmath is available through
`PYTHONPATH=/tmp/hcsn_round10_deps`. From the repository root:

```bash
python -B tools/hcsn/calibrated_operator_r11_20261031/numerics/audit.py --output /tmp/full-hx-new-matrix.json
python -B -m unittest discover -s tools/hcsn/calibrated_operator_r11_20261031/numerics -p 'test_kernel.py' -v
python -B tools/hcsn/calibrated_operator_r11_20261031/numerics/package_evidence.py
python -B tools/hcsn/calibrated_operator_r11_20261031/numerics/package_evidence.py --restore /tmp/full-hx-restored-evidence
```

The numerical audit and archive restore refuse to overwrite an existing output.
The archive verifier checks compressed hashes, decompressed chunk hashes,
offsets, whole-member hashes, and JSON parsing before any original large file
is removed. Four focused mathematical/interface regressions pass. No GPU,
deployment, energy, full recurrent network, or production-neuron claim is made.
