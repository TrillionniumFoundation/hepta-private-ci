# Windows detached-session process qualification

The original target runs six integration cases on native Windows MSVC. Its detached-session case starts an owned child, disconnects, resumes the same session, verifies that the child remains open, and terminates it. The following observations refer to this one target.

| Original job | Detached-session case | Complete target | Time for all six cases |
| --- | --- | --- | --- |
| [#7005](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45110023804/job/137481302886) | passed | 6/6 | 0.72 s |
| [#7009](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45115542852/job/137503935193) | passed | 6/6 | 2.40 s |
| [#7013](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45120356546/job/137513221713) | passed | 6/6 | 1.23 s |
| [c6a3ed9c](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45125165932/job/137528575116) | failed | 5/6 | 5.86 s |

The c6a case reported `timed out waiting for exec-server websocket event`. Its original five receive sites use the same five-second helper and select a successful response with the expected request ID. A matching JSON-RPC error is filtered out, as are unrelated notifications. The archived timeout therefore leaves both the operation and the triggering event unidentified. Eight directly relevant files have identical Git blob IDs on all four commits. The observed durations apply to whole test executables.

The fixture closes the old socket and connects the new socket as separate client operations. The server releases the old session after its request dispatcher and handler finish cleanup. The registry rejects a resume while the old connection still owns the session. The production recovery client classifies this rejection as retriable, and its own dedicated acceptance test exercises the rejection. These code paths establish a possible ordering for the test. A stage and matching error from an observed failure would be needed to attribute the archived timeout to that ordering.

The [single-target diagnostic job](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45130133727/job/137543502354) schedules three original invocations followed by three invocations with test-only error context. Each invocation runs the full six-case roster once on the same host. A failed invocation retains its original exit status and contributes to the final job status. The diagnostic changes five failure messages and logs an already-received matching error in each predicate. The predicate, five-second clock, child command, cleanup, assertions and production code retain their original semantics. The target runs outside the surrounding full shard, and successive invocations share a runner and build cache. The diagnostic run measures neither failure incidence under shard load nor the full Windows qualification.

All six invocations passed with Bazel exit 0. The original six-case executables took 1.16, 0.62 and 0.66 seconds. The contextual executables took 0.72, 0.63 and 0.66 seconds. The repeats did not reproduce the archived failure. The precise operation and cause for c6a remain unresolved. The 10,706-byte raw [diagnostic ZIP](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45130133727/artifacts/14797934164) and the four exact original target logs accompany the verifier.

Recompute with Python 3 by running `python readback.py` in this directory. For independent replay directly against the original full-shard artifacts, use the two arguments below. Put the four original raw testlog ZIP archives in one directory under the names `7005.zip`, `7009.zip`, `7013.zip` and `c6a.zip`. Pass the diagnostic ZIP as the second argument. The verifier reads Bazel's target-level XML, each Rust case result, the retained invocation status, and the actual diagnostic patch.

```sh
python readback.py /path/to/original-windows-zips /path/to/windows-exec-resume.zip
```
