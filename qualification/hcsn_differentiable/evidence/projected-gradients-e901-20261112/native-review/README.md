# Independent arithmetic review of the retained native arrays

The nine-visit projected-gradient population at source `5a1db6f9da54d877e1660c4c964df0e227745719` is consistent with its predeclared absolute-plus-relative and finite-difference step-stability gates. The separate review agent recomputed the retained arrays without rerunning the model or tests. This is a same-session arithmetic/source/archive review, not an external-custody attestation or a new training replay.

[INDEPENDENT_ARRAY_REVIEW.json](INDEPENDENT_ARRAY_REVIEW.json) contains the complete checks and parameter-level summaries. The retained pure function [review_retained_arrays.js](review_retained_arrays.js) accepts the original report object, original trace text, all 13 frozen source files as a path-to-text object, and a SHA256(text) callback. It recomputes the array, identity and scope checks without executing model/project code; archive transport/CRC verification is recorded separately in the review JSON. [native-report.original.json](native-report.original.json) and [fixture-trace.original.jsonl](fixture-trace.original.jsonl) preserve the original uncompressed member bytes from [NATIVE.zip](../NATIVE.zip).

## Recomputed results

| Quantity | Result |
| --- | ---: |
| Retained visits | 9 |
| Update indices / model identities | 0, 1, 2 / 3 |
| Visits per update | 3 |
| Partial-derivative coordinates | 675 |
| Maximum absolute AD / fine-FD difference | 1.268078309024645e-9 |
| Maximum combined-tolerance ratio | 4.8071145460457015e-5 |
| Maximum coarse/fine step-stability ratio | 1.3440735655454074e-4 |
| Coordinates failing either declared gate | 0 |
| Maximum baseline recorded-event replay error | 0 |

The combined-tolerance ratio is `abs(AD-FD_fine)/(1e-7 + 5e-4*max(abs(AD),abs(FD_fine)))`. The stability ratio uses the analogous coarse/fine expression. Both ratios must be at most 1. The source tolerance was not changed after observing these values.

The review verified the complete 41,189-byte ZIP SHA256, all 12 members' sizes/CRC32/SHA256, all 13 source-file hashes against the exact GitHub source, the auditor hash, and both the trace's full digest and its retained prefix digest. Its original ZIP SHA256 is `882510d2d4fe504b1ea252d00d0d469e8ea938a49a1ba1d8371c1aeebb353faa`. The original native report is 195,415 bytes with SHA256 `d0b0b06d34eb76905bd8fc6a558a49444f58e692a78247de38b945e9700634a3`; the original trace is 19,119 bytes with SHA256 `c71bedb120f2df5fbf999d8cf22f4adcb15cd0d0e439d79532e334b688262b1a`.

The producer records 9 new tests and 14 existing trace regressions passing. Publication of that producer result and archive does not supply a missing durable-supervisor terminal receipt. The separate GitHub Actions execution remains separately identified in [the CI receipt](../actions-43127659504/README.md).

## Ordinary relative error and small derivatives

The maximum defined ordinary relative error is **0.03731269450024406**, approximately **3.7313%**. At that coordinate, AD is 3.030734690517579e-14, fine FD is 3.148202612835168e-14, and their absolute difference is 1.1746792231758875e-15. This tiny derivative passes through the absolute part of the combined gate. Reporting only the maximum absolute error would hide the distinct relative-error scale.

There are **246 undefined ordinary relative ratios**, retained as null because the fine-FD reference is zero. Of these, 48 have nonzero AD; their largest absolute AD is 1.5994349866791954e-16. Null is not a zero relative error. This check therefore supplies no relative rare-tail gradient certificate.

## Populations and scientific limits

This nine-visit audit holds each recorded prior fixed and covers 10 probability coordinates plus five readouts per visit, differentiated with respect to five physical parameters. It does not qualify the general content-mass Jacobian, raw-to-physical parameterization, filtering, full task loss/BPTT, continuum fidelity, first-passage behavior, real-task benefit, energy or adoption.

The same raw native report also contains a **separate existing eight-visit continuum regression fixture**. Its status remains **HOLD** and its recorded `maximum_scaled_value_error` is 0.3218712487251427. Its unit-test pass checks that the HOLD is preserved. Those eight visits are not merged into the nine-visit projected-gradient population, and its scaled value error is not a derivative-error or delay-time metric. This fixture is also distinct from the previously archived real 32-cell, two-update task-loss evidence.

Scientific admission and full numerical admission remain **HOLD_NO_GO**. This work adds **0 independently admitted full C2 training replays**. The older CI receipt's pending-native-arithmetic statement records its preparation time; this later review closes that arithmetic check for the native archive. The independent CI ZIP-copy request remains a separate operation.
