# Independent review of original retained training-trace labels

All six label exports agree with an independent reconstruction from the original manifest order, Python random seed, effective batch size 32, microbatch size 8, and original observed capture counts. This reconstruction did not import the producer scan code, Torch, a model, or a numerical oracle. It also binds each trace SHA and full footer to the earlier original42 archival summary, and each report/plan/source hash to the actual v8 terminal evidence.

The reviewed six exports contain 2,066 retained record slots and 16,492 valid sample-position-layer states. A record slot can contain multiple batch samples; these counts are not interchangeable and neither counts individual probability-grid coordinates. Every retained row has update_index 0, with epoch 1 and main phase derived from the exact input order and source. The raw rows do not literally contain epoch or phase. There are zero retained post-main-update rows.

| Fit | Retained record slots | Retained valid sample states | Reconstructed seen valid states | Retained fraction |
|---|---:|---:|---:|---:|
| hcsn-s101-lr0.001 | 346 | 2750 | 4166205 | 0.066007% |
| hcsn-s101-lr0.003 | 346 | 2750 | 4237601 | 0.064895% |
| hcsn-s211-lr0.001 | 343 | 2744 | 4185984 | 0.065552% |
| hcsn-s211-lr0.003 | 343 | 2744 | 4205328 | 0.065251% |
| hcsn-s307-lr0.001 | 344 | 2752 | 4168073 | 0.066026% |
| hcsn-s307-lr0.003 | 344 | 2752 | 4188216 | 0.065708% |

The row-level comparison verifies sequential retained positions, capture number, layer, exact episode order, batch_indices and their valid-sample counts. The independent seeded reconstruction also exactly reproduces all six footer seen-record counts, capture counts, dropped-record counts and excluded padding. The stopping cause is the byte budget, and all six footers say truncated. The fractions above are retained samples divided by a source/manifest/capture-count reconstruction of seen sample states. They do not mean the discarded probability arrays exist or were numerically checked.

This review reads the exact 39,664 B exported labels package and source, the original terminal report/plan and archive-summary JSON, the fixed data manifest, and local byte-matching v8 source. It does not independently reread the roughly 32 MiB probability trace of each fit; the row export and its original scanner remain the source of raw row fields, with full-trace SHA and prefix/footer commitments bound to earlier originals. Thus the result is an independent label/count and provenance reconciliation, not a second probability-array audit.

The independent subprocess took 0.16206473300189828 s complete child wall and 0.15611399999999998 s waited child CPU. Original scan cost remains separate: its reported main interval was 6.744620158104226 s and own process CPU sample 6.795673823 s before final serialization. Neither value is promoted to a complete original child exit measurement. No energy measurement exists.

These original retained traces cannot support a claim of recorded post-update coverage or whole-training numerical qualification. Fresh best/last checkpoint exports in the separate numerical audit are supplemental states at those checkpoints and do not repair or extend the original training trace. Whole-training numerical admission and scientific benefit remain HOLD.
