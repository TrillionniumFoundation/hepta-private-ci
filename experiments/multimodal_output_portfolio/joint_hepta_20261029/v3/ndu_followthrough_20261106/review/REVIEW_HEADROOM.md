# Independent limited review: known-law JAC headroom

**Disposition: the interval construction and the frozen one-episode fee conclusion are sound in their declared finite artifact model. No high-impact mathematical or numerical defect was found.** The conclusion must not be extended to arbitrary repeated deployment of one policy with a one-time audit fee.

Reviewed `headroom.py` SHA-256:
`64ce7d4d9100939a6d86793df7b6888044f559f668203edc69a9d5430090fc2f`.
Reviewed `headroom.json` SHA-256:
`4952e8f736caf1e5e46d0365ab519ff638faaba9bd3f8bbb01f49f3b62d49133`.
I read the implementation, receipt, completed HEADROOM.md, corrected protocol fee convention and retained baseline inputs. I independently evaluated the known-law Bellman recurrence and all 20 retained deterministic baselines at 110-digit Decimal precision, without importing `headroom.py` arithmetic, the original `optimal_policy`, or the original evaluator. Only the declared source model constructor supplies inputs. No bank, fit, observation, task draw or model call was added. No target source was changed.

## Mathematical reconstruction

1. The dyadic rounding code takes floor at the lower endpoint and ceiling at the upper endpoint on the `2^-80` grid. Integer division has the correct direction for negative numbers as well.
2. For `0<=x<=8`, the degree-40 exponential partial sum has nonnegative terms. After the first omitted term `x^41/41!`, every later term ratio is at most `x/42<1`, so the supplied geometric tail is an upper bound. Arithmetic intervals preserve the partial sum and first omitted term. For negative arguments, reciprocating the positive interval reverses endpoints correctly.
3. For the logarithm, `z=abs((x-1)/(x+1))<1`. Eighty retained odd-power terms end at `z^159/159`; the first omitted power is `z^161`. The bound `2*z^161/[161*(1-z^2)]` is valid. Using the upper interval power and upper interval square in the denominator is conservative; restoring the sign swaps endpoints where required.
4. Exact rational probability normalization matches the explicitly declared interpretation of the binary-float input artifact. Monotone real CE backups and maxima over action intervals enclose the true finite-model optimum. The same calculation restricted to a saved deterministic action gives its baseline interval. Since every saved baseline is feasible in the optimized class, intersecting the difference interval with nonnegative headroom is valid.
5. The frozen recursive objective mixes actions linearly outside the conditional CE. Thus a statewise Bellman maximum bounds every policy in this same finite sufficient-state/action class. It does not bound strategies with new observations/actions, changed rewards, a different horizon or a different objective.

In the independent high-precision recurrence the largest absolute exponential argument was only 2, within the implementation's restricted domain 8. The largest absolute atanh variable was approximately `.72291169915605037`. All independently computed values lie in their recorded rational intervals. The rational proof does not rely on the Decimal point checks; the point checks are an independent consistency test.

## Independent numerical results

| Quantity | Independent value, rounded for display |
| --- | ---: |
| Real artifact-model optimum | `0.2527472190501729667752398374073787911` |
| Largest retained-baseline headroom | `0.0011762869414375871542851260655652856` |
| Mean headroom over the 20 retained baselines | `0.0001764430412156380731427689098347928` |
| Sum of one headroom from each retained baseline | `0.0035288608243127614628553781966958569` |
| Largest one-episode gain minus `.01` | `-0.0088237130585624128457148739344347144` |
| Sum of those 20 one-shot gains minus one shared `.01` | `-0.0064711391756872385371446218033041431` |

Every independent optimum/baseline/headroom value is enclosed by the recorded rational endpoints. Exact rational summation reproduces the reported maximum, mean and total headroom upper bounds. Every one-episode upper bound and the stated 20-distinct-baseline aggregate upper bound are strictly below `1/100`. Source and input fingerprints match their receipts, and all **53 deterministic review assertions pass** in `REVIEW_HEADROOM.json`. These are not 53 scientific repetitions or external peer review.

The 17 zero *point* headrooms should retain that label. Their recorded interval upper bounds are small positive widths, not a numerical proof that each headroom is identically zero. This does not affect the fee obstruction.

## Fee, reuse and claim limits

The frozen endpoint compares one scored deployment's recursive utility improvement with an additional `.01` audit charge. Under that convention, even free access to the known-law optimum cannot cover the audit charge above any of the 20 strong baselines. More calibration solely to narrow the confidence intervals cannot rescue this endpoint. Additional nonnegative acquisition/engineering costs cannot reverse this particular negative ceiling.

The 20-episode statement is also valid **as explicitly defined in HEADROOM.md**: sum the 20 separately scored episode CE values, one from each distinct retained baseline, and subtract one shared fee. This is a deliberately favorable accounting diagnostic. It is not a joint entropic objective for a concatenated process, and it does not represent arbitrary reuse of the same best-improvable baseline.

For a fixed positive-headroom baseline with repeated deployment and a separately declared single audit fee, the relevant oracle ceiling is `M*Delta-.01`, not `Delta-.01`. At the present positive headroom, this expression becomes positive at `M=9` (about `.0005865824729382844`, before any additional costs). This is only a demonstration that the current result does **not** prove failure for every M; it is not evidence that a learned method attains the oracle, that these extra deployments occurred, or that actual complete-cost profit is positive. Any reuse-based study must freeze its deployment volume, tariff and all costs prospectively.

For clarity, add an explicit no-arbitrary-M sentence to HEADROOM.md. Its final “any new study needs a task or information contract” wording can include “or a separately frozen lifecycle/deployment-volume contract,” since changing reuse economics need not change the physical task. No current negative endpoint should be retroactively redefined.

Finally, the rational headroom calculation is separate from `confidence.py`. Its successful enclosure does not upgrade the confidence adapter's SciPy quantiles and floating propagation into formally outward-rounded confidence bounds. It also establishes no general NDU impossibility, independent real-tool benefit, or new RL originality.
