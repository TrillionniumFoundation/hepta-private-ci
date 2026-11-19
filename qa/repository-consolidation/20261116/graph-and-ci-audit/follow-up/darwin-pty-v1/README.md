# Darwin fixture and Mac PTY validation

This evidence records two distinct native scopes and the final hosted status of
7e04259b85ee2d3c31182c6b4be8b6a3ace29fc0.

## Agentd fixture repair

Four test fixture files normalize canonical roots or use a short temporary path
on macOS. Production checks, test assertions, stack settings, time limits, and
retry counts are unchanged. The native source was
3d6d17adfa92757085a371d67cd269e043d8dbed plus exactly these four files.

The original 22 hosted failure names were selected with the original package
command, four test threads, and zero retries under an owned symlink temporary
directory on Linux. All 22 passed in 22.151 seconds; the complete invocation
including compilation took 108.960 seconds. All 7,777 source and control inputs
remained unchanged. The other 1,596 tests were not selected.

The earlier failures remain intact: attempt 1 stopped during preflight, attempt
2 failed during compilation with no tests executed because disk space was
exhausted, and attempt 3 executed 22 tests with 21 passes and one canonical root
failure. The fourth fixture repair fixed a second independent test store before
its original NDU assertions; every assertion was retained.

Linux does not execute the macOS short path branch. These results do not replace
the original hosted Mac qualification.

## Unmodified PTY package on a native Mac

The original dropped output receiver test passed, followed by all 30 tests in
the original PTY package. The focused run took 0.139 seconds and the full package
test phase took 1.606 seconds. All 12,014 transferred source inputs remained
unchanged. The source manifest records the exact commit and the three unrelated
Agentd fixture files present during transfer.

The original two second test deadline and child alarm remain unchanged. No
production or test code was changed for this reproduction. A separate standard
library experiment is included as a diagnostic only. Passing on this configured
Mac does not establish the cause of the original hosted timeout or erase that
failure.

## Final hosted status at the old head

All 211 checks completed: 165 succeeded, 23 failed, 10 were cancelled, and 13 were
skipped. The Rust CodeQL analysis job succeeded, while the CodeQL check failed
with 21 annotations: 10 critical and 11 high. These annotations are a subset of
the results. The new Rust analysis contains 193 results and the Python analysis
contains four. Full reconciliation of the new analysis is still pending; no
alerts were dismissed or suppressed.

Later OAuth diagnostics and the subsequent combined candidate were not scanned
by this old run.

## Evidence format

Each part sequence is an ordered segment of one deterministic gzip stream.
Concatenate all parts in the order recorded in the corresponding JSON archive
record, verify each part and the complete stream, then decompress the tar
archive. The archive records include original member lengths and SHA256 values.
Decompression and every member hash were verified after transfer.
Each repository artifact is no larger than 500,000 bytes.

The original source manifests, command lines, raw logs, prior failures, source
changes, blob receipts, and final hosted API responses are preserved. The
summary files distinguish their executed source from later combined candidates.
