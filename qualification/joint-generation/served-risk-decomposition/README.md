# Saved served-risk channel decomposition

This is a posthoc, aggregate-only analysis of the already completed 12-cell
C/E × S/A/N × two-seed reports. It performs **no model evaluation, training,
gradient calculation, original dataset read or TEST read**. The originating
experiment's complete-budget failure and six failed quality components remain
unchanged. This does not rescue a failed experiment.

## New finding

For E-N versus C-N, the image channel is positive in both seeds, but the class-mass
channel is negative and larger in magnitude. All six original primary components
are retained below; positive rho2 is better.

| Seed | Left minus right | Class-mass component | Image-MSE component | Total rho2 difference |
|---|---|---:|---:|---:|
| 41011 | E-N − C-N | −0.00305644 | +0.00011399 | −0.00294245 |
| 41023 | E-N − C-N | −0.00627848 | +0.00073035 | −0.00554813 |
| 41011 | E-N − E-S | +0.00607024 | −0.00121017 | +0.00486007 |
| 41023 | E-N − E-S | −0.01488818 | +0.00149926 | −0.01338892 |
| 41011 | E-N − E-A | −0.00527452 | −0.00130690 | −0.00658142 |
| 41023 | E-N − E-A | −0.01573908 | +0.00094564 | −0.01479344 |

The E-N−C-N class component is negative at **both noise levels in both seeds**.
Its image component is negative at sigma 1/16 but positive at sigma 3/16 in both
seeds; the overall image improvement is therefore not uniform across noise.
These facts do not support simply increasing the image-anchor weight as a remedy.
They locate the observed score difference, not its optimizer/training cause.

In the fixed right-reference true-class-mass bins, p<0.5 contributes positively to
the E-N−C-N class difference in both seeds, while p≥0.9 contributes negatively.
This is **not proof of a hard-example or confidence-training mechanism**: bins
condition on one model's outcome, may exhibit regression to the mean, and use the
known target label. They are not deployable confidence/router features. Every
fixed bin, including empty ones, appears in `RESULT.json`; none was selected later.

## Exact finite-law identity

The original source emits one AA image shared by all ten class outcomes. Set
`p = expected_accuracy`, the actual correct-class u53 mass, and
`q = exp(-expected_mse / 0.04)`. Its unchanged scoring formula is

```
R(p,m) = -0.5 * log1p(p * expm1(-2 * exp(-m/0.04)))
```

For a paired left/right request, average the two replacement orders:

```
P = [(R(pL,mR)-R(pR,mR)) + (R(pL,mL)-R(pR,mL))] / 2
M = [(R(pR,mL)-R(pR,mR)) + (R(pL,mL)-R(pL,mR))] / 2
P + M = R(pL,mL) - R(pR,mR)
```

The mixed combinations are algebraic bookkeeping, **not feasible hybrid models,
causal interventions, or newly evaluated policies**. The single-image condition is
required; substituting expected MSE for a multi-image law would be invalid.
Original fixed-outcome/scoring source hashes are recorded in `PROVENANCE.json`.

## Fixed scope and validation

- All 12 reports, 765 sources × two original variants each, exact input SHA binds.
- The original 14 paired contrasts, without seed pooling or sign filtering.
- Both fixed noise levels and their equal-weight total.
- Right-arm true-class-mass bins [0,.5), [.5,.9), [.9,.99), [.99,1].
- Each request is decomposed first. All sources have exactly two variants, so
  the complete-panel request mean equals the original equal-source mean.
- Bin `mean` is a conditional request mean; `contribution_to_stratum_mean`
  retains original request weight and sums across bins to the stratum mean.
- All saved request utility/rho2 metrics reconstruct within 1e-12; pairing,
  coverage, equal-source overall metrics and bin conservation are checked.
- Eight standard-library literal tests pass, including endpoints, sign reversal,
  channel-only cases, malformed inputs and full 12-report literal coverage.

Only the original source-bound, trusted report bytes are qualified here. This is
not a hostile-JSON security validator: positive-p NLL values and overall reference
metrics lack separate finite-value checks, although all per-request primary
metrics used for the decomposition are explicitly finite. The manifest selects
and hashes reports; constants are bound by frozen code and plan together rather
than revalidated from every manifest field. These limits do not alter the finite
saved-input result and should not be advertised as broader parser qualification.

## Reproduce without private inputs

```sh
python3 -I -B -W error qualification/joint-generation/served-risk-decomposition/test_decompose.py
```

To analyze separately authorized local reports, supply a JSON manifest with
`input_reports: [{"cell":[41011,"C","S"],"path":"...","sha256":"..."}, ...]`
and all 12 exact cells, then run `decompose.py manifest.json output.json`.
Private report files/paths, request rows, source IDs, model weights and datasets
are deliberately absent from this publication.

## Paid work and interpretation

Complete waited tests cost **0.477565 CPU seconds**; saved-report arithmetic cost
**1.187243 CPU seconds**, **1.192782 wall seconds**, maximum RSS **94,976 KiB**.
Total child CPU: **1.664808 seconds**. Supervisor observed prefix: **0.010217206
seconds**; its final tail and source/review/publication work remain additional,
unmeasured, and not zero. Both children used CPU0 and the original shared lock,
with 15 CPU seconds / 90 wall seconds / 512 MiB caps. All receipts are in
`COST.json`; no original scientific cost is erased or reaccepted.

This reused-DEV decomposition is descriptive, not independent confirmation or a
new equal-complete-budget win. It is separate from the FIT-only saved-Adam
mechanism investigation and provides no basis to rerun the failed endpoint
hypothesis or launch gradient projection.
