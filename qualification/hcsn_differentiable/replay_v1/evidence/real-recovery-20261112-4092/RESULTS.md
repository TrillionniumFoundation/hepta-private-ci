# Six real checkpoint continuations — 2026-11-12

## Observed result

The unchanged PR #6130 diagnostic source at `5cb83d9c76beedf4c1c917e4bf561f5f26261ce7` completed on configured host `desktop`. Its durable job is `1a1ce749808-2564-1688`, with idempotency key `hcsn-real-checkpoint-replay-4092-6130-attempt001`. The authoritative native terminal reports `succeeded`, exit code 0, no cancellation or timeout, complete durable stdout and stderr, and no truncation. The raw stdout reports six completed diagnostics and 26 actual optimizer calls. The raw stderr is empty.

`SUMMARY.json` is the exact 53,740-byte native result, SHA-256 `c8dcd62b2391a730c5d21ecd6dfa4b4b1ad0e4d71ae9c23fbaafa29f2502eeb5`. The frozen execution plan SHA-256 is `cfa808f0547e8bf412009294451c54e9b479f981723cd936fcae9a957aab59b9`. The native output root is `/home/qian-qi/hcsn-real-recovery-20261112-4092/attempt001`.

| Original fit | Origin epoch | Origin logical updates | Reference/resumed state equality | Actual calls |
| --- | ---: | ---: | --- | ---: |
| hcsn-s101-lr0.001 | 116 | 1,392 | full model, Adam, RNG and cursor | 4 |
| hcsn-s101-lr0.003 | 76 | 912 | full model, Adam, RNG and cursor | 4 |
| hcsn-s211-lr0.001 | 126 | 1,512 | full model, Adam, RNG and cursor | 4 |
| hcsn-s211-lr0.003 | 50 | 600 | full model, Adam, RNG and cursor | 4 |
| hcsn-s307-lr0.001 | 127 | 1,524 | full model, Adam, RNG and cursor | 4 |
| hcsn-s307-lr0.003 | 72 | 864 | full model, Adam, RNG and cursor | 4 |

For each original checkpoint the reference process makes two updates, a separate producer makes one update and publishes a real state, and a fresh resume process loads that state and makes the second update. Both the resulting complete states and the batch/loss/gradient receipts agree. The six origins were selected and SHA-bound before execution; no synthetic or different checkpoint was substituted.

The missing-Adam control makes one additional update and is detected. A separate process makes one additional update and exits with code 73 after serializing and fsyncing a private temporary, before canonical publication. The crash is rejected as a published checkpoint. These two controls bring the real optimizer-call total from 24 to 26. The orchestrator's measured outer wall interval is 908.8070661991369 seconds. Per-worker intervals overlap and must not be summed as elapsed wall time.

## Separate audit and evidence retention

At this evidence commit, the independent audit and raw archive are **UNKNOWN / PENDING COLLECTION** after transport timeouts. Their successful completion is not claimed. The producing diagnostic summary and native terminal above were obtained before this interruption. See `COLLECTION-STATUS.json` for the retained dispatch outcomes.

The read-only auditor was frozen in commit `d8bcfac912c3cc24faeadf3bb234d1df5107f088`, file SHA-256 `1174ad3615ebfaa27c21f308f7f2cce16fad6ddada8e0c416c8653bc04e9a48e`, before its native invocation. It checks decoded original and produced state bytes, actual Adam step increments, the original input commitments, raw stdout/stderr and child exit receipts, and the serialized crash temporary. Its result and native observation are collected separately from the producing diagnostic; no further optimizer calls are authorized by this auditor.

Native dispatch/read errors are retained alongside successful receipts. A transport timeout is not a failed training outcome. The initial source deployment was reconciled to its original succeeded job with the same key and `retried_launch=false`. An uncertain execution is never retried under a fresh key.

## Scientific boundary

This is real checkpoint restoration and short continuation evidence for the original `run-source-v8` model. It contributes **zero independent complete training replays**, zero independent task sources, and no qualification of the newer joint nodal/DDE training operator. It does not establish sufficient training, a quality advantage, independent source generalization, device energy, or Cell adoption.

The original C2 job `1a1c74f3308-be2a-75` remains UNKNOWN. Its missing controller terminal and original negative or interrupted artifacts are preserved; this successor neither restarts that job nor repairs its old publication history. Full C2 training must use a separately source-bound new execution and the frozen six-parent roster, complete cost accounting and unchanged stopping requirements.

Status remains **Draft / HOLD_NO_GO**.
