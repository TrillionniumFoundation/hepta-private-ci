# Preserved first kernel audit

The original 10-test scalar/numerical audit passed; its RESULTS.json and EXECUTION.json remain unchanged. Exact source bytes corresponding to its recorded hashes are retained in source/.

A subsequent pre-registration review discovered a stricter numerical-causality issue: global adaptive uniformization choices could change an unchanged prefix when future or neighboring coefficients changed. CAUSALITY_DISCOVERY.json records an actual float32/float64 counterexample and identifies the old source. The defect was repaired before formal content training by a fixed rate/term/chunk contract with explicit domain rejection.

The controlling completed audit is ../kernel_validation002/REPORT.md. Both this first audit and the repair's cost/evidence remain preserved. A passing scalar propagation audit alone was not treated as proof of neural numerical noninterference.
