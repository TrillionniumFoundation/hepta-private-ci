# Ledger-cache r2 build: shared CPU cap exceeded

Actual exit **1**, source `d0b99c25a26739c52e5695433625ac1b966f25a4`,
execution/freeze commit `382c9967c22acaf185e86c121a6f39c2a8f48c1f`.
The exact command and selected Codex Cloud environment are in `execution.json`.

Original error: `BudgetExceeded: shared:shared_preparation_complete actual CPU
12.274880402s exceeds frozen cap 10.000000000s`.

The shared build consumed 3,611,371,737 declared operator units, the same
inventory as t7 and the separate shared diagnostic. It completed the fixed data,
decoder/base preparation, calibration, native compilation and base exports.
The unchanged actual-CPU guard then stopped the build. Zero candidates completed;
no selection, selected-model critic, residual training, standalone export or
formal evaluation occurred. The r2 formal test remains unconstructed/unopened.

The completed shared metadata, all three bases, calibration samples, compilation
receipt, partial ledger, original traceback, phase telemetry and console are
retained. The new failure-persistence path therefore closed the previous missing
receipt problem. It did not close the resource-budget problem or benefit gates.

The separate protocol-first cache diagnostic retained exact receipts and
parameter/Adam/loss equality. Its five paired actual-update timings were mixed:
median paired saving 4.12%, two pairs slower, aggregate saving only 0.15%.
That local measurement did not establish whole-build acceleration. This actual
build overran, and it is not replaced by a faster debug execution or retried with
the same source to obtain a favorable outcome. No cap, price, data, base-training
schedule, objective or benefit threshold was changed.

Before this freeze, **151 independent source tests passed**, exit 0, 4.708s.
These tests do not open the experimental test fold. The previously trained
affine standalone RGB/reload smoke remains in t6, with its limited scope.

First-goal status remains open: prior complete TRAIN/validation builds showed
positive content/NDU means, while complete effective-control CPU-net benefit
failed. The current run cannot supply a new contrast. The next justified work is
cost diagnosis from this retained complete receipt; a future build requires a
concrete prospective repair. Synchronous AV generation, long interactions,
device testing and production qualification have not run.

Read-only retained-cost decomposition (seconds): compilation 2.001719994;
27 raw calibration preparations 0.132664318; native generation plus ledger
0.041622454; real output encoding plus ledger 0.565822119; three base exports
0.097223605. These disjoint recorded pieces total 2.839052490, leaving
9.435827912 unpartitioned across data, decoder/base training, validation,
calibration protocol and other shared logic. The stored service medians cannot
be multiplied into an actual total. The same pieces in d1 total 0.880654088
against its 4.001949343 shared CPU; these different debug/build times do not
identify a cause. All three base files and the native library match d1 bytes.

Shared process/main-thread CPU was about 10.659 seconds, with one thread before
and after. Observed GC totaled 10.579ms; throttle/OOM/major-fault deltas were
zero. None establishes an explanation or a cloud-quota denial. The next single
diagnostic adds high-level disjoint CPU spans and full calibration receipts;
it is not a second qualification attempt and cannot replace this failure.
