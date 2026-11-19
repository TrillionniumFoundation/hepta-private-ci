# Original control and runtime drain native evidence

This is component evidence only. Complete ordinary positive, NoUpdate and
daemon-plus-Root cold-restart qualification counts remain **0 / 0 / 0**.

The actual UID-1000 run used immutable commit
`cbdcb09f191c86a6004ebf1222b4d2a8d6bf0738`, tree
`6a1cb85b6ca24bb5d005a39dfeb5ad402ad2373b`. It ran from
2026-11-12T06:11:47.778795Z to 06:14:50.661525Z and returned exit 0.
Original JUnit contains **6 tests, 0 skipped, 0 failures, 0 errors**:
accepted control connections must finish, failed connections prevent a receipt,
aborted control supervision cannot acknowledge join, cancellation cannot replace
an actual runtime drain, a real drain releases State, and capture commands reject
peer-chosen material. The command, tool versions and unchanged before/after Git
snapshots are in the original run record.

The native source commit was a real formatter postimage of remote `242fc75d`.
Its original raw commit was retrieved from the executor, independently hashed,
and restored as the identical Git object. Repeating the matching official
Rustfmt command locally produced the identical tree above. This reconstruction
preserves the actual source; it does not reconstruct or invent a test result.

The first invocation attempted `just test ... --no-run`. The repository wrapper
also supplies `--no-fail-fast`, and actual nextest 0.9.151 rejected that argument
combination before Rust compilation. Its original exit-2 record and output are
retained alongside the succeeding run. No retry changed a timeout or assertion.

The log files are losslessly gzip-compressed, with original and stored lengths
and SHA-256 values in `original-files.json`. The source-exit lifecycle was later
extended with the complete ordinary launcher, terminal Initial client and other
owners. Those later source trees require their own native qualification; this
six-test result does not cover them.

The separately recorded read-only execution probe ran `sudo -n id -u` and
observed 0. This establishes availability of actual UID-0 execution only. It is
not a Root test, a grant, a source admission or a cold-recovery result.
