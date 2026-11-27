# Saved TRAIN calibration receipt diagnostic

Administrative R&D only. No data construction, model execution, new timing measurement, training or qualification retry.
Only the saved training selection receipt, shared-preparation telemetry and unchanged source were read. The t2 archive was not modified.

Seed 11 is persistently expensive across all three repeats, not one rejected outlier:

| Seed | Repeat 0 row median (ns) | Repeat 1 | Repeat 2 | All 216 rows median | Output fraction of service CPU |
|---|---:|---:|---:|---:|---:|
| 11 | 809584.312500 | 763512.875000 | 476919.484375 | 763512.875000 | 76.69% |
| 23 | 88759.968750 | 65740.437500 | 67682.500000 | 67682.500000 | 83.99% |
| 47 | 349512.296875 | 193856.437500 | 126907.531250 | 193856.437500 | 82.32% |

All 648 raw row values, 18 batch receipts and nine repeats are retained in CSV and JSON, including every high value.
Each request has the same 19,236 declared operator units. The output-byte arrays are identical across repeats within each seed.
Generation and output component timings both vary. These component boundaries combine multiple operations; they do not identify a primitive or process-level cause.

TRAIN-only future service reservation is 1.180859688s = 1,152 rows × sum(seed row medians)/1e9. Preparation adds 0.015670796s using the existing one-future-measure rule (observed maximum).
The following original admission totals already exceed the 10s cap before adding any new gradient step or guard; all saved residual-round counts are zero:

| Arm | Spent before residual (s) | Tail reserve (s) | Changed-model reserve (s) | Sum before new step (s) |
|---|---:|---:|---:|---:|
| supervised | 9.064886319 | 1.213814558 | 0.169594405 | 10.448295281 |
| anchor | 9.078810464 | 1.215637883 | 0.188507141 | 10.482955488 |
| additive | 9.077756469 | 1.233355815 | 0.323272445 | 10.634384729 |
| ndu | 9.044589131 | 1.212849086 | 0.156818381 | 10.414256598 |

Shared-phase telemetry: process CPU 3.064979435s, wall 3.738248684s; GC total 12.020419ms over 22 pauses, maximum 4.007123ms.
The endpoint snapshots show one process thread. Container throttling and OOM-event deltas are zero. Container counters are not process-causality evidence and phase-wide GC events cannot be localized to a particular calibration batch.

This establishes repeat-persistent TRAIN cost variation and conservative admission, not its cause. It does not support deleting outliers, substituting future validation timings, relaxing reserves or repeating a confirmation for a favorable wave.
No new concrete compute-reuse repair is identified: native/output/ledger costs are not separated finely enough to show repeated work. A future optimization would first need source-level reuse with an independent equivalence/cost argument. No new measurement or confirmation is proposed by this report.

Source, input-file hashes, exact administrative command, UTC and process/child CPU accounting are in ADMIN.json. No formal result or held-out input was opened.

A subsequent source-only hypothesis supplied after extraction is evaluated in [CODEC_REUSE.md](CODEC_REUSE.md): a decoder-bound local finite-code codec table. Its repeated-work basis is supported; no implementation, speed or scientific-benefit claim is made. The earlier absence of an identified primitive-level timing cause remains unchanged.
