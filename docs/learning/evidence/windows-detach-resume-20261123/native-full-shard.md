# Windows detached-session full-shard readback

The original detached-session test failed twice on separate executions of the native Windows shard. Both five-second errors used the same message for initialization, process start, resumed initialization, process read and termination. The retained output gives no location within those five operations.

| Full shard | Native test result, all six cases | Rust executable | Native Bazel action |
| --- | --- | ---: | ---: |
| [Original c6a](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45125165932/job/137528575116) | detached-session timed out, five passed | 5.86 s | not extracted |
| [Original c12](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45138928408/job/137573328593) | detached-session timed out, five passed | 6.32 s | 6.392 s |
| [Original #7021](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45139490724/job/137575118379) | six passed | 0.68 s | 0.746 s |
| [Diagnostic, one full shard](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45143783875/job/137587947219) | six passed | 1.59 s | 1.821 s |

The diagnostic used the c12 prospective-merge tree and added context to those five waits in the test. Each matching JSON-RPC error could write its code and operation in test output. The production handlers, ownership registry, baseline five-second wait, request ordering, selected action IDs, assertions, cleanup, retry budget and other shard tests ran with their original definitions. Earlier isolated invocations had passed 36/36 cases. This run selected the full 171-target Windows shard. Its uncached local target executed all six cases and exited zero. The observed run produced no failure context that attributes the archived timeouts to an operation or an error code. The previous failures remain unresolved.

Bazel reported 122 passed targets, two failed targets and 47 skipped targets in this run. The two failed targets retained four separately named native Windows failures regarding sandbox and restricted-token behavior. This evidence does not establish an application fix.

The supporting [compressed records](native-full-shard.zip) retain the unmodified target-level Rust text and the three original compact Bazel TestRunner protobuf records for c12, #7021 and this diagnostic, source identities, direct artifact IDs, prior SHA-256 digests and the original four sibling case failures. The 22,412-byte packet has SHA-256 `b20ab03f669f47250810da42fbf5c0b691a245c6206e9ecf557f3b92903a2dc8`. The tables use whole-test-executable and whole-action elapsed time. The target language's local five-second receive deadline is independent of Bazel's 300-second target timeout.

[Diagnostic test-only source](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/8f98ae64f8a4734fd5da5e13eed0c75f8f13fbbe) · [Raw complete shard test logs](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45143783875/artifacts/14803929380) · [Compact Bazel action stream](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45143783875/artifacts/14804731372)
