# R16: explicit compensated FP32 financial operator

This is an additive numerical stage. It does not edit the R11 financial model,
R14 task confirmation, or the R15 controller evidence. The validated candidate
uses **two FP32 words for every financial scalar and every tangent component**.
It is an extended-significand algorithm, not ordinary one-word FP32, FP64
financial arithmetic, or a renamed mixed-precision kernel.

## What passed, and what remains open

Both financial tolerances remain exactly the inherited ones: scaled value error
at most `8e-7` and scaled Jacobian error at most `2e-5`, with denominator
`max(1, abs(reference))`. Each row includes all five outputs (boundary, equity,
F, G, debt) and all ten derivative columns (nine parameters and the state).

| Implementation / evidence | Passing rows | Passing complete cases | Max value error | Max Jacobian error |
|---|---:|---:|---:|---:|
| Original ordinary FP32 | 136 / 432 | 0 / 18 | 0.0162873 | 61.8149 |
| New ordinary FP32 algebra, attempt 1 | 344 / 432 | 0 / 18 | 1.35219e-5 | 0.00325252 |
| Compensated candidate, development matrix | 432 / 432 | 18 / 18 | 5.66508e-8 | 9.43964e-7 |
| Frozen compensated candidate, independent V1 | 512 / 512 | 128 / 128 | 5.71866e-8 | 7.18919e-6 |

The ordinary-FP32 attempt also regressed two previously passing rows; both are
retained in `ATTEMPT01_REVIEW.json`. It is not admitted. The compensated candidate
passed 701 separate primitive diagnostics and all five original financial
failure witnesses before the full development matrix. The original 432 rows
contain 419 unique inputs, 13 duplicates, and only two asset-default rows;
these counts must not be represented as independent confirmation.

V1 was frozen before evaluation: a PCG64 seed-2026110107 Latin hypercube with
128 distinct parameter tuples, log-scaled liquidity/maturity, four prescribed
states per tuple, and independently defined financial validity. All 128 tuples
were independently valid; there were no rejections or guard mismatches. All
512 state tuples are unique. Observed branches comprise 36 asset-default,
128 near-boundary Taylor, 128 Taylor/A7 blend, and 220 raw-A7 evaluations.
There are 34 parameter tuples in the small-B-denominator region and 76 in the
small-A-denominator region. Maturity ranges from 0.0101574 to 19.0612.

This establishes the stated finite numerical validation for the compensated
candidate. **Ordinary FP32 qualification remains open.** It does not prove
uniform accuracy over the box, global differentiability across default,
training utility, network-scale correctness, hardware throughput, or a GPU or
energy advantage. Exact alpha/tax endpoints and an exact boundary state for
every tuple are not part of this holdout. Separate independent invariants check
boundary identities, default recovery, nominal homogeneity and coordinate-chain
derivatives. Any retuning after this V1 holdout requires a new candidate and a
new independent validation set; V1 becomes regression evidence for that change.

## Arithmetic and financial definitions

`compensated_kernel.py` loads a private copy of the frozen R11 full financial
formulas and replaces their arithmetic/elementary primitives. It preserves the
boundary, debt, F/G, equity equations, the existing divided-difference quadrature,
tenth-order local Taylor evaluation and C2 blend, and the actual default branch.
`stable_kernel.py` is the separate, unsuccessful one-word development attempt;
its integral/complement rearrangements are not silently substituted into the
validated compensated candidate.

`float32_pair.py` uses TwoSum, a Dekker product, corrected division, and
range-reduced elementary functions, with float32 high and low words throughout
financial evaluation. Fixed mathematical and quadrature coefficients may be
prepared using higher precision before they become float32 pairs. Cephes
normal-CDF coefficients come from the identified official SciPy source;
provenance and its BSD-3-Clause license are included. Financial outputs and
Jacobian columns are rounded to single FP32 words. Numerical AD differentiates
the underlying mathematical functions, not the discontinuous rounding map.

The pair representation has roughly 44–48 effective significand bits in
well-scaled normal arithmetic, with no general range guarantee. The independent
review retains two generic primitive counterexamples: `sqrt(0)` produces NaN,
and the splitter can overflow for `1e35 * 1e-10` although the product is finite.
These limit generic-library claims; they were not removed from evidence or used
to retune the frozen candidate. This is a specialized financial prototype.

The independent oracle evaluates literal A5/A7 formulas at 80 decimal digits,
then forms symmetric parameter/state differences at two halved steps. The
maximum V1 step-halving discrepancy is 4.7788e-59 against a 1e-12 gate.
The unchanged archived oracle converts round-trip decimal strings of FP32 words
represented as Python floats; it does not reconstruct exact binary rationals.
The primitive audit independently uses exact binary high/low word values.

## Complete CPU cost, including derivatives

The local Python measurement uses identical quantized inputs in all modes:
the 18 original parameter cases at log distances 0.001 and 0.1 and asset 100.
Every evaluation builds the differentiated boundary and returns all five
outputs and all ten Jacobian columns. Each condition receives a complete
54-evaluation warmup, followed by one measured batch, with one numerical thread.
All 54 requested evaluations completed finitely in every mode. No failed or
nonfinite evaluation is counted as comparable completed work.

| Local Python mode | Complete boundary + state | Boundary reused across 3 states |
|---|---:|---:|
| Original FP64 | 2.339 ms / state | 2.358 ms / state |
| Original one-word FP32, numerically unqualified | 2.562 ms / state | 1.965 ms / state |
| Compensated FP32 | 219.005 ms / state | 175.510 ms / state |

The compensated Python implementation costs about **93.65 times** the original
FP64 implementation and **85.49 times** the original one-word FP32 implementation
in this complete-evaluation measurement. It has no measured CPU speed advantage.
The separate reuse measurement includes one boundary construction per three
states. Imports and fixed-constant preparation are excluded. One fixed-order
local batch is descriptive cost evidence, not a latency distribution or a
production benchmark. A compiled follow-up must compare all precision modes
under the same compiled implementation method and receive fresh validation.

## Reproduction and artifact seals

The bundle stores large JSON evidence losslessly as gzip. Materialize a new
isolated directory rather than modifying any frozen source:

```bash
python prepare_workspace.py --destination /tmp/hepta-r16-reproduction
cd /tmp/hepta-r16-reproduction
python -B make_holdout_cases.py --output /tmp/reproduced-r16-cases.json
python -B audit_primitives.py --output /tmp/reproduced-r16-primitives.json
python -B audit_development.py --kernel compensated_kernel --output /tmp/reproduced-r16-development.json
python -B audit_holdout.py --output /tmp/reproduced-r16-holdout.json.gz --summary /tmp/reproduced-r16-holdout-summary.json
python -B audit_cost.py --output /tmp/reproduced-r16-cpu-cost.json
```

Required Python packages are NumPy, SciPy, mpmath and threadpoolctl. Exact local
versions are recorded in the CPU receipt. If mpmath lives in a separate installed
environment, the primitive and holdout auditors accept `--oracle-pythonpath`.
All output paths are create-only. The materializer verifies every bundled hash
and every decompressed hash before creating the new directory. Independent
validation checks candidate/protocol/manifest seals before and after execution.

`BUNDLE_MANIFEST.json` identifies all artifacts, source hashes, and compressed
evidence. `ALL_ATTEMPTS.json` retains failed ordinary-FP32 development alongside
the successful compensated finite validation. `R16_COVERAGE_V1.json` is observed
coverage, not a post-hoc gate change. Its first JSON serialization failed on a
NumPy integer; the partial text is retained separately, and no numerical source
or evaluation was changed. Existing large-model, scientific-task, and ordinary
FP32 blockers are not closed by the numerical receipts in this directory.
