# Complete setup target and both actual worker terminals

The original setup helper target completed naturally: 28 passed, zero failed,
zero filtered, no retry or flaky result. The one outer ignored entry is the
dedicated subprocess worker. Its parent actually launched that exact entry twice
using this test executable with --ignored --exact and --nocapture; the preserved
records contain two distinct real PIDs, completed waits, zero exit codes, and
the exact 186-byte stdout plus empty stderr from each process. Each child ran
one test successfully, ignored zero tests, and filtered the other 28 test entries
as intended. The worker was not treated as a skipped product test.

The raw job log, full original ZIP, complete member hashes, API terminal metadata,
two original JSON records, and each decoded stdout/stderr are preserved here.
The production implementation is unchanged from 9f971725; 02c24d1 added only this
terminal logging. Its preceding complete 9f target also passed and remains in
the parent evidence directory. Consumer CLI/exec-server and the complete platform
matrix remain independent gates.

The two raw stdout streams use lossless gzip so their original leading/trailing
blank lines remain byte-for-byte intact without text whitespace normalization.
