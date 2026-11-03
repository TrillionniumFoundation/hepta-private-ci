# Fleet 158b844d current-source evidence

`macos.zip` and `linux.zip` preserve both original hosted artifacts. Their separate
verification receipts check archive digests/CRC, 84 exact Git inputs before and
after execution, production-function extraction, and fresh JUnit. Both original
Fleet library suites passed 42 tests with zero skips, including all five original
failures and the new interrupted-publication rejection.

The macOS 15.8.2 ARM64 runner used uid 501; Linux used uid 1001. Both official
Rust 1.95 and 1.96 compiled and executed the exact current publication helper,
which left a sealed 0555 directory. The old readonly-rename sequence still fails
with EACCES on macOS as an explicit preserved counterexample.

`local-linux.tar.gz` separately retains another original 42-test Linux run and
the original scoped Clippy command. Both exit zero with unchanged source. This
local run used uid 0 and establishes functionality only; unprivileged permission
evidence comes from the hosted jobs above.

No full platform CI, injected kernel-failure, automatic crash-recovery or paired-
host acceptance is claimed. These are evidence checkpoints; the tested production
head remains 158b844db94a99c7fcf7386efe6a207fdeb24db7.
