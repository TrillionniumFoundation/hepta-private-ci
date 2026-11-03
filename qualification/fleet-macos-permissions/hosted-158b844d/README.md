# Fleet 158b844d current-source evidence

The original macOS artifact is preserved as `macos.zip`, with independent exact-Git
input and JUnit verification in `MACOS_VERIFIED.json`. It proves 42 original/current
Fleet tests with zero skips on macOS 15.8.2 ARM64, uid 501. Exact production helpers
were compiled and executed with Rust 1.95 and 1.96; both publish a sealed directory,
while the old readonly-rename counterexample still returns EACCES.

`local-linux.tar.gz` preserves the original 42-test Linux run, fresh JUnit and full
receipt. All inputs equal the already verified macOS Git inputs. This local run
used uid 0 and establishes functionality only, not unprivileged permission checks.
The hosted Linux job was still pending at this checkpoint. No full CI, injected
kernel-failure, automatic crash-recovery or paired-host acceptance is claimed.

These files are an evidence checkpoint, not a production branch update. The
source remains 158b844db94a99c7fcf7386efe6a207fdeb24db7.
