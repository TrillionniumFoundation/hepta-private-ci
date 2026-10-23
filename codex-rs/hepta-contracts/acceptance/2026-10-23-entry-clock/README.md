# General lease time at the owner boundary

Source leaf `776251e2ca4d25f655b8e2818204256b04d6a247` moves the three original
verification samples after acquisition of the same owner/revocation mutex.
The original consumer and dispatch callbacks keep their existing lock lifetime.
No lease, binding, revocation or deadline policy changes.

The [publication manifest](publication.json) preserves sixteen original input,
command and log files with SHA-256 and lossless compression. `original-negative-02`
is the actual semantic negative: both old callbacks entered with a pre-lock
1000ms sample after the controlled clock reached expiry5000ms. The corrected
original lease scope passed all17 tests in13.393s (runner21.120s), with211 other
tests excluded by the explicit scope. Full contracts02 passed220/221; its one
remaining real-clock initialization exceeded the unchanged one-second horizon.
The earlier UnsafeStateDirectory fixture failure is also retained and is not
expiry evidence. Scoped fix/fmt followed the tests without a same-phase retest.

These Rust1.96 Linux results do not qualify a complete composed workspace,
native service or production recovery. The filenames in the manifest identify
each phase; a nonzero old-phase result remains a failure even when a later
targeted scope succeeds.
