# Accounting cache development diagnostic

One corrected, predeclared execution completed with exit 0 and empty stderr. All three thread variables were `1` before NumPy import; the process reported one thread. This is a hand-fixture development diagnostic, not qualification.

The original benchmark is retained byte for byte in `original-benchmark.json`, including its null thread variables, 12 synthetic prefix stages and negative whole-update pairs 1, 4 and 5 (median paired saving −2.758%). The corrected protocol changes both environment and representativeness; neither the original negative result nor any difference between protocols is attributed to threading.

The corrected worker seeds the exact seven stage dictionaries and 35 total counters from the retained d1 shared ledger through public `record`, then adds only `search_train`. This represents post-shared state; it is not a chronological replay or timing of shared preparation. Each kind has five fixed paired runs of 256 admissions or supervised updates, with alternating old/new order, no warmup, retries, pair deletion or tuning.

| Kind | Pair | Order | Old CPU ms | New CPU ms | Old wall ms | New wall ms | CPU saving |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| ledger_only | 1 | old → new | 10.400037 | 8.567315 | 10.399998 | 8.567155 | +17.622% |
| ledger_only | 2 | new → old | 12.283403 | 10.502956 | 12.293742 | 10.503166 | +14.495% |
| ledger_only | 3 | old → new | 11.378747 | 9.347436 | 11.378589 | 9.377638 | +17.852% |
| ledger_only | 4 | new → old | 10.752033 | 12.304480 | 10.752196 | 12.304154 | -14.439% |
| ledger_only | 5 | old → new | 10.698449 | 9.035763 | 10.699093 | 9.036733 | +15.541% |
| full_update | 1 | old → new | 138.028329 | 140.449347 | 138.028671 | 140.458583 | -1.754% |
| full_update | 2 | new → old | 144.570808 | 123.177580 | 146.078596 | 123.177650 | +14.798% |
| full_update | 3 | old → new | 148.773682 | 185.347577 | 149.014073 | 185.348003 | -24.584% |
| full_update | 4 | new → old | 142.650782 | 129.481978 | 143.281873 | 129.530196 | +9.231% |
| full_update | 5 | old → new | 133.451690 | 127.951883 | 133.452218 | 127.953043 | +4.121% |

The predeclared median paired CPU saving was +15.541% for ledger-only (negative pair 4) and +4.121% for whole updates (negative pairs 1 and 3).

As an additional descriptive check, summed whole-update CPU was 707.475291 ms old versus 706.408365 ms new, a 0.151% saving. The mixed pairs and near-equal aggregate do not establish a stable whole-update speedup.

All ten pairs passed exact old/new ledger snapshot/digest, model parameter, Adam moment/step, loss and update-count comparisons. The full-update kind completed exactly 256 real gradient/Adam updates per variant; ledger-only is explicitly bookkeeping, with zero model updates. All 20 final variant receipts and ten pair records are retained.

No TRAIN, validation or held-out dataset was constructed; no shared preparation or qualification was run. These measurements establish local accounting equivalence and describe bounded timing observations. They do not establish whole-build speed, content utility benefit, the cause of the T7 slowdown, or qualification readiness.

`protocol.json` and `worker.py` were unchanged after review. `unit-tests.log` copies the separate 151-test source-check log. `manifest.json` and `SHA256SUMS` bind the retained artifacts.
