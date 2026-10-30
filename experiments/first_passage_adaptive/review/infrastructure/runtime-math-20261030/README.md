# Runtime reconstruction audit — 2026-10-30

This package records fresh evidence gathered after the transient workspace reset. Its base commit is `9b71cf4e65194593d5e0fb2a507026d21527a740`; `SOURCE_HASHES.json` identifies the exact reviewed worktree files. Final canonical formatting and exact-head CI are tracked separately by the parent review.

## Observed results

- The complete Matrix owner `cargo check --tests --locked --offline` succeeded after the missing `pkg-config` tool was installed. Both the initial environment failure and the successful retry are preserved.
- The subsequent scoped Matrix `just test` exited 101 while compiling dependencies because the filesystem filled. No test case executed. Its original ENOSPC log is retained, and this package does not claim a Matrix behavioral pass.
- Five controlled child-process cases exercised the actual repository code-mode `HostHarness`: successful endpoint and stderr ownership, early exit, oversized endpoint, endpoint timeout, and a full stderr pipe. Every child was reaped and the artificial secret stayed absent from diagnostic output. These are Linux process/pipe probes, not native Mac tests.
- The actual Bazel feature query loaded 12 rules successfully. Ordinary cognitive product harnesses expose the existing production capability; qualification targets have both required features; the explicit read-only targets have no capability feature and remain test-only. Rule loading is not full graph compilation or process execution.
- The fleet release publication control flow received an independent read-only source review. Its implementation and runtime tests belong to the parent change.

## Remaining boundaries

The Mac Intel code-mode endpoint startup cause is unresolved. The new code preserves the 10-second endpoint deadline and adds bounded failure cleanup and diagnostics. Cleanup may take up to a further one second to wait and 250 milliseconds to read at most 8192 stderr bytes. Only fixed markers, counts and status are reported; successful stderr ownership is retained. These observations do not prove that the original Mac failure is fixed.

Windows V8, platform-specific HTTP fixtures, bounded-read capabilities, and product lifecycle tests still require their exact-head owner CI. Previous local raw logs were lost in the reset and are not reproduced or represented as new evidence. The historical Bazel progress count **103 counts actions, not local tests**; it cannot establish local test concurrency.

The restored-file review preserves its initial reconstruction snapshot and separately records the later short-socket-root change by the native owner. `SOURCE_HASHES.json` contains the current snapshot. The Matrix raw-only bounds behavior in production was not weakened; its test migration covers discarded SDK metadata separately from retained raw bundled-event bytes.

## Retention and verification

The explicitly whitelisted raw evidence is in the deterministic archive described by `retained/manifest.json`. Every uploaded file is smaller than 256000 bytes. No build caches, compiled binaries or PID files are included. The original scratch evidence was kept; only staging copies under this package's `raw` directory were removed after verified fresh restoration.

From the repository root:

```sh
python3 experiments/first_passage_adaptive/retain_evidence.py check --manifest review/infrastructure/runtime-math-20261030/retained/manifest.json
python3 experiments/first_passage_adaptive/retain_evidence.py restore --manifest review/infrastructure/runtime-math-20261030/retained/manifest.json
python3 experiments/first_passage_adaptive/retain_evidence.py check --manifest review/infrastructure/runtime-math-20261030/retained/manifest.json --include-restored
```

`VERIFICATION.json` records the actual archive check, fresh restore, second idempotent restore and restored-file check. Restoring evidence does not run or retrain a scientific study.

The retained probe imports the repository module directly. To reproduce it in a different checkout, adapt the recorded absolute checkout path in `host_probe/src/main.rs` and `host_probe/probe.py`, then build its standalone Cargo manifest and run `probe.py`. The original source and log are retained verbatim, so this path adaptation is distinct from the as-run evidence. A native Mac owner run remains necessary to diagnose the original startup failure.
