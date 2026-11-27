# Complete original Windows core gate

The exact 35e source produced three failed attempts among eleven attempts.
GitHub marked the job successful after Bazel retries; the retained complete
decoded job log is classified FAIL_FLAKY. No retry success closes this gate.

The common followup combines the actual Windows private-state fixes with
guardian outcome and persisted-history diagnostics. The paginated-resume
fixture preserves its ten-second completion-witness wait and reports the
remaining owners on failure. No completion fence or production policy changes.

The marker fixture releases its exact first recorded probe. Its ordered
buffer cannot advance when a shared semaphore instead wakes a later probe.
The existing 256-way concurrency, exact order, real filesystem result and
five-second bounds remain unchanged.

The original full core target still runs all declared shards, with the same
60-minute job budget and no cached test results. A complete raw-log check now
rejects FLAKY, failed attempts, second-or-later attempts, missing PASSED summary,
and a cached-only summary. The raw log is uploaded on failure as well.
The common followup needs its own actual Windows result.
