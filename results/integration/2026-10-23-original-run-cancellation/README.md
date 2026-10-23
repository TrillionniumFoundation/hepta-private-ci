# Original Run cancellation candidate: source and static evidence

Source commit: `df9f564dc086e722ee1f6125a2f7a5b6d1801c6b`.
Source tree: `9363a0af547df790c3883e615c7a90c62cebdad3`.
Parent: checkpoint source `9e1521d2ac6d171a0c307e2ae5a3b7a1ee6cacd0`.

The original worker incorrectly compared a Running generation with its daemon
spawn generation. This candidate retains the original Run identity, validates
exact revisions, consumes the original Cancelling transition once, and uses the
existing AppServer interrupt and correlated terminal event. Missing, mixed or
indeterminate state remains quarantined; it does not create a new RunCancel
authority, scheduler, ledger or guessed terminal observation.

## Actual validation boundary

- Four Rust source files: official Rust 1.95 rustfmt and independent source review.
- Eight Rust regression tests are authored and **not yet executed**.
- The new normal-PR workflow runs the complete original worker library through
  `just test --locked --cargo-profile dev-small --build-jobs 1 --test-threads 1
  -p codex-hepta-infer-worker-host --lib --no-tests fail` and requires all eight
  exact test names in fresh JUnit. It preserves the original workspace and locks.
- Its 38 synthetic parser/command-boundary checks pass in ordinary and optimized
  Python; ten Bash blocks and four embedded Python programs pass syntax checks.
  These are checker tests, not worker execution. The gate's actual nextest pin is
  0.9.103; the local memory run's 0.9.149 is only a separately labeled format input.
- Full source publication readback covers all 9,255 leaves, including unchanged
  file modes/blobs. No GitHub CI or native guest success is claimed here.

## Complete retained records

`raw-evidence.tar.gz` contains all 24 frozen Rust-candidate evidence entries and
all 34 final CI evidence entries, their full frozen entry records, the independent
CI review, the exact five-source publication entries, and root readback. Both
earlier and later independent Python result records are retained with their round
identities. `manifest.json` lists every member byte count, SHA-256 and Git blob.
The archive was fully decoded and compared to every original member before
publication. No dependency cache or compilation binary is bundled.

Extract into an empty review directory to inspect the original report paths:

```sh
python3 -m tarfile -e raw-evidence.tar.gz extracted
```

Production signing/permission inputs, Desktop post-send cancellation,
cross-crash durable RunCancel, complete Agentd/worker execution and native guest
lifecycle remain separate gates. The 500 ms observation tick is not a hard
physical-cancellation deadline.
