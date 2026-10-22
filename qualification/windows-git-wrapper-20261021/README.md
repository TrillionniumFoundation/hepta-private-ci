# Windows Git wrapper lifecycle fixture

The original Windows shard 1 logs at heads `48177153ad04605338c3a9a8dbd17defee9981bc` and `52293403ea1e06465c41d24d39b54959bad40936` both fail the exited-wrapper case at the existing 10 second wrapper-exit assertion. Child PID and readiness have already succeeded. This is before the production 100 millisecond output timeout and descendant-cleanup assertion. The logs do not distinguish PowerShell path-provider polling from PowerShell host teardown; this packet makes no stronger diagnosis.

Tested source commit: `1022172082781366a85935043b951872afda9f5f`, parent `29f845b6a214472906416cc0626551c19a4ab54e`. The only source change is `codex-rs/git-utils/src/git_process_tests.rs`. Production `git_process.rs`, JobObject/process-group containment, manifests, and lockfiles are unchanged.

The Windows fixture now runs the same Rust test executable as both the real wrapper and its real descendant. The descendant explicitly inherits stdout/stderr, remains inside the original production containment, and holds the pipes after its wrapper exits. The exited-wrapper case checks a release acknowledgment and successful wrapper exit. Both original lifetimes, deadlines, `None` timeout output, and child-survival cleanup assertions remain. The original two Unix shell cases also remain; two additional Unix cases execute the shared Rust wrapper implementation locally.

## Actual validation

| Check | Observed result |
| --- | --- |
| `just fmt` | Exit 0 |
| `just test -p codex-git-utils --locked` on Linux | 42 passed, 0 skipped |
| Temporary cleanup-guard leak, same Rust-wrapper cases | Both compile and fail the original child-survived assertion; the existing local profile retries each once and both fail again |
| Production restoration | Original bytes restored in a `finally` block; clean worktree and unchanged source/lock hashes |
| Resource outcome | Two build jobs; no OOM or OOM-kill increments |

The negative control changes only the timeout/error arm to leak the process-tree cleanup guard. Direct child `kill_on_drop`, inherited pipes, readiness and release protocol, and all assertions remain. Its exit 100 is an expected runtime assertion failure, not a compilation failure. The fixture terminates only its own leaked descendants after observing survival. The mutation is not in the committed source.

These Linux runs qualify the actual replacement fixture and its cleanup oracle. They do not replace Windows or current-base CI. No Windows success, remote publication, approval, or merge is claimed here.

## Evidence

`baseline-failures.json` records the first exact failure context from each full original job log, with the full decoded-log byte count and SHA-256. The unchanged original fixture bytes are included once as `original-git_process_tests.rs`; both original heads have the same blob. Raw local test output is retained as lossless XZ. Run `python qualification/windows-git-wrapper-20261021/verify.py` from any directory to check all artifact hashes, decompressed logs, exact source hashes, runtime outcomes, and source restoration. The verifier also works under `python -O`.

`independent-review.json` is a separate agent's read-only source review. It is not a human approval or Windows runtime result.
