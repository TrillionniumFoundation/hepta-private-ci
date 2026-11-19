# Independent small-norm exponential review

The reviewed final kernel is SHA256 `e1731b349de811177dc402ee0ee70f08a25289bb844837b679cabef2d63bdfb6`. Its FP64 predecessor is SHA256 `29eee2059064ac0994bc2fef8485784a0f1e5ebe369d23c74c2e1da3866cd9a4`; the independent FP64 results retain that predecessor's exact bytes. The FP32 extension changes the dtype-dependent cutoff and its documented bound. The FP64 polynomial and cutoff remain the same. The final source's ordinary regression suite separately exercises the FP64 cases again.

## Code and mathematical review

`Work.exponential` evaluates the degree-12 Taylor polynomial by Horner recurrence when the represented matrix 1-norm is at most 0.1 for FP64 or 0.6 for FP32. The loop starts from the identity and applies `I + A @ result / degree` for degree 12 down to 1. This produces exactly `sum(A**k/k!, k=0..12)` in exact arithmetic. Every matrix multiplication remains in the tensor graph. The detached norm chooses an algorithm; it does not detach the matrix supplied to that algorithm. The external work limit remains charged once per exponential, with separate polynomial/native counters. The pending release packets, reset distributions, active/content fields, and logical delay schedule are unchanged.

For any submultiplicative norm with `||A|| <= a`, the omitted polynomial tail obeys

`||R12(A)|| <= exp(a) a^13 / 13!`.

The corresponding first directional derivative and second mixed directional derivative are bounded respectively by

`exp(a) a^12 / 12! * ||E||`

and

`exp(a) a^11 / 11! * ||E|| ||F||`.

These follow by differentiating each noncommuting matrix power: there are `k` first-order insertion positions and `k(k-1)` ordered second-order insertion positions. They do not assume that A, E, and F commute.

| Nominal a | Value tail | First derivative coefficient | Second derivative coefficient |
| --- | ---: | ---: | ---: |
| 0.1 | 1.7747988221e-23 | 2.3072384687e-21 | 2.7686861624e-19 |
| 0.6 | 3.8217531107e-13 | 8.2804650732e-12 | 1.6560930146e-10 |

These bounds exclude floating-point roundoff. The implementation compares represented floating-point norms, so the real input norm and nominal decimal threshold need not be exactly identical. In particular, the retained FP32 cutoff input has norm 0.6000000238418579 and takes the small-norm path. The independently measured FP32 error is dominated by roundoff, not the degree-12 truncation bound. The native path remains outside the selected range; it has its own numerical behavior.

The retained upstream `compute_T8` excerpt and exact symbolic coefficient audit provide a separate causal explanation for the previous failure. The transcribed polynomial differs from degree-8 Taylor at powers 5 through 8. Squaring the extra `x3` denominator factor makes the exact coefficients agree. This algebraic diagnosis is not itself a floating-point implementation qualification. The reviewed patch uses the independently checkable degree-12 recurrence rather than modifying or rebuilding the installed Torch package.

## Independent numerical checks

Both reviews use a nonnormal 3 by 3 A and independent directions B and C with nonzero pairwise commutators. The exact represented inputs are converted to 80-decimal mpmath values. Values use a 3 by 3 matrix exponential; first derivatives use the upper-right block of a 6 by 6 exponential; second mixed derivatives sum both orderings of a 9 by 9 block exponential. Thus the reference does not differentiate the production recurrence or rely on a commutative scalar reduction. Each review freezes its roster, source snapshot, tolerances, runner, and resource limits before one bounded execution. No dataset rows, model training calls, or optimizer steps are used.

| Review | Nominal matrix 1-norms | Maximum value error | Maximum gradient error | Maximum Hessian error |
| --- | --- | ---: | ---: | ---: |
| FP64 predecessor | 0.034, 0.099999, 0.1, 0.100001 | 3.3306690739e-16 | 1.3877787808e-17 | 1.3010426070e-18 |
| Final FP32 | 0.0512, 0.5, 0.6, 0.600001 | 9.4098084102e-08 | 1.3077977208e-08 | 7.9287091817e-10 |

All four declared points pass in each review. The final FP32 case above the cutoff takes the native path; its error is included in the maxima. Full child FP32 cost is 10.712104901 seconds wall, 10.1357 seconds CPU, and 220896 KiB peak RSS. Source hashes are unchanged before/after execution. Exact inputs, high-precision outputs, individual errors, branch counters, and process receipts are retained in `attempt001/RESULT.json` and `attempt001/COST.json`.

## Scope and remaining limits

No blocking mathematical or code finding remains in this bounded review. It verifies values and the selected branch's first/second derivatives at the declared matrices. It does not prove exact global smoothness of a finite-precision conditional algorithm at its cutoff, certify every matrix/backend/device, or establish end-to-end training quality. The original 0.61 gamma gate and the complete network/changing-law suite are separate retained regression gates owned by the patch author; their final-source results must accompany this review. Logical event times and delay schedules remain nondifferentiable by the operator's existing contract.

The historical 831 training artifacts remain attached to their original frozen implementation. Neither the zero-age work reduction nor this numerical repair reclassifies that historical HCSN result as competitive with the ordinary gate, and neither establishes a new fair-budget training result for the modified kernel.
