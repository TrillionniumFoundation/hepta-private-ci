# Actual-source v2 finite diagnostics on all original retained laws

This stage evaluates all 14,336 original priors and all 14,336 posteriors from
the 12 exposed arms, using the actual graded spatial generator and actual
MigrationBasis lift from #6189, source
`62f392a0ed953f2d04e9c62b4b243f5cceed2a98`. It uses none of the earlier
exploratory numeric arrays. Eight published product source files were read
through GitHub and matched the local executing bytes before this execution.

For each recorded positive gap (.001/.003/.02/.04/.08/.16), the independent
finite evaluator reads the candidate's actual nodes, positive rates, complete
matrix, reset ingredients and migration weights. A reversible spectral solve
evaluates single-hit M/H and integrated active occupation A of that same
finite generator, then explicitly integrates initial phase release times.
The maximum horizon is below the fixed .2 delay, so no second hit is possible.
R denotes ordinary refractory occupancy, M plus the unreleased initial phase
mass. It is not discounted refractory occupation. The latter is also retained
as discounted total mass-time minus A; this complement adds no independent
numerical evidence. The continuous F/G/A reference uses separate reflected
Brownian formulas and 64/128-point integration of the original continuous laws.

The four complete NPZ files preserve every arm/visit/update/position, original
line/model hash, episode ID, gap/reset and candidate/reference M/H/R/A. Each
contains 14,336 rows and is below 750,000 bytes. All four were read back without
pickle and compared exactly. Twelve executing source hashes and 43 input
hashes remained unchanged. SOURCE_SNAPSHOT.zip retains every executing source
byte; the final formatting receipt preserves normalized Python ASTs.

| Grid/law | Maximum absolute M error | Maximum relative M error, reference >=1e-12 |
| --- | ---: | ---: |
| 256 prior | 1.77841348e-5 | 0.00776904726 |
| 256 posterior | 1.34908271e-5 | 0.000473257514 |
| 512 prior | 4.45727954e-6 | 0.00194794890 |
| 512 posterior | 3.37957356e-6 | 0.000115705774 |

All M/H/R/A summaries are in the original SUMMARY. Across all original laws,
the 64/128 continuum quadrature differences are below 1.91e-14. The original
discrete event receipt differs from the new continuum M by up to 5.39112e-7;
matching an original receipt was never a continuum accuracy guarantee.

The retained eight actual-DDE experiments from #6183 are a separate execution.
Their M/H/A agree with these candidate kernels to maximum absolute differences
2.919e-12 / 3.064e-12 / 4.961e-13. Their original summary, raw NPZ and formatting
witness were independently matched to their published Git blobs at #6189.
Where executing byte hashes differ only by formatting, the source relation is
reported as a retained AST-equivalence witness, not identical bytes. The old
DDE archive did not retain R, so no independent DDE-R measurement is claimed.

The full new run took 31.6951 seconds wall / 20.7780 seconds CPU after imports
on a shared host, including guards, lift construction, references, full rows,
array write/readback and DDE comparisons. These are audit costs, not model
throughput. An earlier invocation failed with ENOSPC while creating its output
directory, before any numerical execution; its original stderr is retained.
The attached environment later became unavailable before publication. After
recovery, every original NPZ SHA256 was unchanged; those exact bytes were
uploaded without rerunning the finite experiment.

## Admission boundary

This is an exposed, post-failure development diagnostic. The relative reference
floor remains 1e-12. No new prospective finite gate, independent source,
relative rare-phase precision, time below .001, full all-visit DDE/filtered
trajectory, physical AD, neural training, C2 replay or adoption is qualified.
The isolated-phase 19.67% n512 relative error at .02 remains in the retained
separate experiment. Neither the full kernel arithmetic nor its read-only
verifier can grant production authority. Overall status is HOLD_NO_GO.

Read retained arithmetic only, with zero kernel/model executions:

```sh
python -B -m qualification.hcsn_finite_review.verify qualification/hcsn_finite_review/evidence/actual-v2-finite-attempt002
```

The exact execution command and source/input identities are retained in
EXECUTION.json and SUMMARY.json. The targeted workflow performs only the
read-only artifact verification; it does not repeat the finite or DDE study.
