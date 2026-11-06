# Acceptance-boundary correction after independent internal review

The initial confidence adapter had three real implementation defects. They are
repaired in the current `confidence.py`; the original files have been preserved
byte-for-byte in `history/initial`, together with the independent review and its
counterexamples. The initial source is superseded, even though its reported
20-bank acceptance outcomes did not change after correction.

## Defects and repairs

| Defect | Initial failure | Corrected behavior |
| --- | --- | --- |
| Empty successor name | Q intervals treated `''` as a successor while risk-tilt construction treated it as terminal; the reported gain was about `.283109585` while the true gain was about `8.91e-10`, incorrectly passing a `.01` fee | Require nonempty string state/action identities and use `next_state is not None` consistently; the invalid graph is rejected. With a valid child name the same large-continuation example yields the tiny gain and rejects the paid update |
| Unvalidated candidate policy | `(2,-1)` for two action probabilities could be returned as an adopted policy with an alleged gain of 2 | Validate complete shared state/action coverage, finiteness, nonnegative weights and unit mass for both policies; malformed policies raise `ValueError` |
| Probability-mass tolerance and currency offset | A baseline row summing to `1-5e-13`, with both actions paying `1e12`, could produce a false gain `.5` even though the normalized true improvement was zero | Normalize accepted rows, center value mixtures and signed Q differences, and compute signed differences with exact rational normalization of the accepted binary floats; the example has zero gain and retains the `.01` spent fee |

The repairs do not establish outward-rounded floating-point confidence endpoints.
SciPy quantiles, exponential/logarithm calculations and value propagation remain
ordinary floating-point computations. The complete real-arithmetic proof and
its fixed-sample information contract have not changed.

## Actual verification and replay

The corrected source passed **11 behavioral tests**, including five added
regressions for these boundaries and common-offset invariance. The actual test
stdout/stderr, command, source hashes before/after the run and successful exit
are retained in `validation.corrected.json`. This is internal verification,
not external review or independent scientific replication.

`protocol.corrected.json` was written after repair and before the replay. It
preserves every sampling and comparison choice and locks the corrected source
hashes. `study.py` refuses a source mismatch, a changed historical input hash,
or an existing output path. The replay reads the same 20 historical banks,
with no new observations, model calls, task seeds, sample sizes, alpha budgets,
fees, policy fits or baseline substitutions.

| Quantity compared with the archived initial run | Corrected replay |
| --- | ---: |
| Paid decisions changed | 0 / 40 |
| Strong-baseline paid adoptions | 0 / 20 |
| Stochastic-baseline paid adoptions | 0 / 20 |
| Source banks / probability boxes changed | 0 / 20 each |
| Locally certified row counts changed | 0 / 40 |
| Probability coordinates changed by normalization | 204 |
| Maximum probability-coordinate drift | `1.1102230246251565e-16` |
| Maximum true returned-value drift | `5.551115123125783e-17` |
| Maximum gain-bound drift | `4.0657581468206416e-20` |
| Maximum baseline-Q endpoint drift | `2.7755575615628914e-16` |
| Maximum risk-tilt lower-bound drift | `8.326672684688674e-17` |

The full comparison is `correction_comparison.json`. All observed model/Q/tilt
coverage and returned gain checks still pass. The primary result remains
NO_GO: the strong baseline has no positive propagated root certificate in any
retained bank, and none of the small positive weak-baseline bounds covers the
fixed audit fee. Negative economic conclusions are preserved.

The accepted result SHA-256 is
`6e0638e3fe9b6003b42aee826dd40cc653e8ac25d87a712dabdd01642444d58d`.
The archived initial result SHA-256 is
`d7e4c8ba4d53a00f2af30329bc96875f7015d270d90b8674d6187f973c656dfb`.
The corrected and initial protocols, source identities and results are explicitly
linked, rather than making an old receipt attest a different implementation.
