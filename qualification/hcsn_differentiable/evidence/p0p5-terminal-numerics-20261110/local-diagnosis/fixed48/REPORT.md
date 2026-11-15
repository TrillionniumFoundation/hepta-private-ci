# Fixed48 short-time scalar diagnostic: saved results and limits

**All 48 predeclared scalar cases executed once.** There were two infrastructure launch attempts: the first exited 127 before Python because `/usr/bin/time` was absent; the second used the authorized standard-library `wait4` wrapper. The mathematical program, roster and 120 s / 256 MiB envelope did not change. No scalar case was retried.

This is a local FP64 mechanism diagnostic. Training-domain and scientific admission remain **HOLD**. It does not evaluate an HCSN model, posterior, E data, or a numerical oracle, and it does not assign shares of the 12 observed perpetual-value pressure failures.

## Scope and source

The frozen mathematical manifest is `8b7015a93d3da6f158b11e330b3dc7e5af5d01a4521585e5f7578a7e1842e966`. The original source, roster, authorization transcriptions, each case, journal, stdout/stderr, both infrastructure attempts, original execution ZIP and external final receipts are included unchanged. [SUMMARY.json](SUMMARY.json) binds the copied files and archive identities; [COSTS.json](COSTS.json) separates nested measurements. The original analytic note and source capsule are retained under `original-archives/`.

The active toy uses a free Gaussian kernel, drift 0 and sigma 0.35, uniform source `[0, Delta]`, and target `[Delta, 2 Delta]`. The widths are 4.8/128 and 4.8/256. Orders 16/32/64 use the original operator Gauss-node function, extracted as standalone source without importing Torch or the operator. The closed-form uniform-source probability and finite Gauss sum are both evaluated in FP64; “exact” in the raw field names refers to the analytic integral, not exact machine arithmetic.

## All twelve fixed pressure-dt rows

Relative difference is `(Gauss - closed form) / closed form`. These are local one-step adjacent-cell probabilities, not the original value/resolvent test or a numerical qualification gate.

| Active cells | Gauss order | h | h / h_star | Signed relative difference (%) | Resolution |
|---:|---:|---:|---:|---:|---|
| 128 | 16 | 1e-07 | 0.310169031 | -58.16658811 | above engineering scale |
| 128 | 16 | 8e-07 | 2.48135225 | +7.53952014 | above engineering scale |
| 128 | 32 | 1e-07 | 4.65433353 | +0.9282056441 | above engineering scale |
| 128 | 32 | 8e-07 | 37.2346682 | -0.01324266468 | above engineering scale |
| 128 | 64 | 1e-07 | 72.1466378 | +0.002918593222 | above engineering scale |
| 128 | 64 | 8e-07 | 577.173103 | -6.812948778e-08 | above engineering scale |
| 256 | 16 | 1e-07 | 1.24067612 | +6.453779155 | above engineering scale |
| 256 | 16 | 8e-07 | 9.92540898 | -0.7975855509 | above engineering scale |
| 256 | 32 | 1e-07 | 18.6173341 | +0.1354797523 | above engineering scale |
| 256 | 32 | 8e-07 | 148.938673 | -0.0001402580933 | above engineering scale |
| 256 | 64 | 1e-07 | 288.586551 | -8.500975854e-06 | above engineering scale |
| 256 | 64 | 8e-07 | 2308.69241 | -2.995065086e-13 | inconclusive at engineering scale |

For the nominal 256-cell/order-32 geometry, the differences are **+0.1354797523%** at 1e-7 and **-0.0001402580933%** at 8e-7. Their h/h_star values are about 18.6173 and 148.939, so these two local cases are not in the declared h much smaller than h_star regime. They neither explain nor bound the coupled, nonzero-drift, phase/tail, infinite-repeat value errors. Increasing quadrature order reduced these two local differences; no network fix, training benefit or hardware benefit was tested.

The 42 active cases include all five h_star factors for each width/order. Six smallest-step Gauss sums underflowed while the analytic probability was positive; the saved log Mills bounds distinguish this from a mathematical zero. Twenty-nine differences exceed the declared engineering roundoff scale and seven are inconclusive at that scale. These are resolution categories, not 42 pass/fail qualifications. The ULP scale is not a certified function-error bound. The symmetry-based nearest-node distance used for h_star and the right-edge subtraction in the probability can differ in final FP64 bits; the frozen implementation is retained.

## Isolated phase transport

The four cases start from the same physical uniform remaining-time law `[0.1875, 0.2]`, use phase width 0.0125 and 16 phases, and ask for release by time 0.1. That physical law has zero release probability at this time. The projected phase-only binomial-chain results are:

| h / phase width | Projected release probability | Same initial uniform physical CDF | Projected waiting-time variance |
|---:|---:|---:|---:|
| 0.5 | 1.52587890625e-05 | 0.0 | 0.00125 |
| 0.25 | 0.00200295620739 | 0.0 | 0.001875 |
| 0.125 | 0.00465459576805 | 0.0 | 0.0021875 |
| 0.0625 | 0.00634401538561 | 0.0 | 0.00234375 |

All four projected means are 0.2, compared with 0.19375 for that initial physical uniform law. At fixed phase width, the h-to-zero isolated-chain limit has Erlang variance 0.0025. This illustrates re-projection broadening in the isolated phase transport; no coupled reset/active process or actual event count was evaluated.

## Returning-tail information loss

The two hypothetical laws are `4.8 + shift + Exp(rate=1)` with shift 0 or 1. Both project to tail coefficient 1. For drift -0.12, sigma 0.35 and discount 0.15, their analytic first-hit Laplace moments are respectively **0.008362287694218247** and **0.003515177193925358**, a ratio **0.42036071018649357**. Reconstruction from the same coefficient gives the former moment in both cases. No actual posterior tail was read; this demonstrates the information a single tail coefficient cannot retain.

## Execution and costs

The successful complete launcher took 0.158260071999 s wall and 0.141118 s wait4 CPU. Its nested complete worker took 0.085170285005 s wall and 0.066413 s CPU. **Do not add these nested totals.** The conservative sum of the three process peak RSS values was 39,845,888 B, below 256 MiB.

The external wrapper recorded a 0.186481808996 s wall prefix and 0.061094741 s own CPU prefix; its final receipt/exit tail is not measured. The external timeout command exited 0. Complete first-attempt OS wall/CPU and exact complete all-attempt costs remain unknown. The original launcher text anticipated a GNU-time record; the preserved second infrastructure receipt explicitly replaces it with wait4. A separate external packaging receipt reports only this read-only evidence assembly, not a second scalar execution.

## Evidence finality

The original execution ZIP is retained byte for byte, together with its external `ARCHIVE-RECEIPT.json` and complete-launcher `RESULT.json`. The new handoff ZIP adds the original pre-launch failure, authorized replacement source, source capsule, this summary and provenance checks. Its own external packaging receipt binds the completed archive SHA. All cases, including underflows and inconclusive results, remain in the raw journal. Research admission stays HOLD.
