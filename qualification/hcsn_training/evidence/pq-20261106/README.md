# HCSN PQ composition: retained qualification evidence

## Source identity

This evidence branch accompanies [source PR #5067](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5067), based on HCSN gap-closure commit `44e539313e0c54badb4b9b687425dd87ecba6e67`.

The first published source candidate is `bbe995c43e4eed4bb9c217b52447ba5a32ebb6ca`, tree `e74509e6a2a49bd004b79854b3a6dbc2fe581be0`. [review-stages.json](review-stages.json) identifies its 22 review commits. Imported authority code and dependency provenance are recorded in the source tree's `SOURCE_PROVENANCE.json`; the reviewed local source is explicitly distinguished from published upstream history.

**Exact-source hosted acceptance is pending.** Dedicated [run 42240138316](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42240138316) was created for that candidate. A queued job, source declaration, successful compile, or one-step numerical preflight does not establish real cancellation or production readiness.

## Local development record

[local-validation.json](local-validation.json) retains 40 separate observations and references 132 distinct evidence files. It distinguishes observed process exit codes, test results, execution scope, and the source identity actually recoverable from each record. Unknown historical source snapshots stay unknown; the published candidate is not retroactively assigned to earlier runs.

| Observation | Retained result | Boundary |
| --- | --- | --- |
| Contracts compile | Passed | Earlier development source |
| Contracts tests | 192 passed, 5 failed with Unix-socket EPERM | Full hosted authority suite still required |
| Automation tests | 120 passed, 2 ignored | Ignored real-worker fixtures are invoked separately |
| Strict Python suite | 64 passed, zero skips | Before the five added spatial tests |
| Spatial tests | Four completed successfully | Two later five-test starts exited 137 with empty logs; no fifth-test pass |
| Old cancellation attempt 01 | All three backends failed during preparation | No worker cancellation acceptance |
| Old cancellation attempt 02 | A passed; both B cases failed | One B produced outputs before cancellation; the other completed first |
| Final extended workloads | A, grid B and final 79-event age B passed one-step admission preflight | No local full cancellation pass for these workloads |
| Caller audit | 51 boundaries, 25 protected entries / 24 unique paths; 11 exact source pins | Unchanged checker and all 45 baseline boundaries retained |
| Caller negative probes | 14 passed; 10 typed-checker tests and self-test passed | Includes imported aliases and qualified instance calls |
| Dependency lock and formatting | Real Bazel lock regeneration and final formatting completed | No post-format local test result claimed |

Overlapping test suites are not added into an aggregate test count. The earlier 39-event age preflight remains separate from the final 79-event workload. Both failed and successful local artifacts remain available.

## Raw archive and verification

[local-raw.tgz](local-raw.tgz) preserves 489 regular files, totaling 8,373,205 uncompressed bytes, including full local cancellation directories, SQLite/WAL bytes, worker outputs, logs, compiler artifact records, local supervisor cases, reviewed source snapshots, and the validation inventory. Every regular file was read back from the archive and checked against its SHA-256.

Archive SHA-256:

```text
bc1652742befe0b2fa4c2ce5813841402e26fe494f396a0ade509e804a8b87e1
```

[local-files.json](local-files.json) is the complete file inventory. One Unix socket is recorded by path and mode only; a live socket is not a serializable file artifact. The archive does not contain the compiled native executable: the compiler artifact record and executable SHA identify it. Archive ownership and timestamps are normalized; regular-file bytes are preserved. The short archive path avoids adding more long evidence paths to ordinary repository checkout.

## Required hosted acceptance

The dedicated workflow must run the exact source candidate through the strict 69-test Python suite with zero skips, the three original signed bridges including second training blocks, complete native authority and automation packages, three real classical cancellation/cold-recovery cases, Agentd host/PQ/protected-source regressions, ordinary non-test Agentd compilation, and three real PQ-host cancellation/cold-recovery cases. Native binary digests, source/tree identity, per-backend outcomes, retained raw outputs and unchanged-source checks must agree.

The new cancellation workload retains the original 64-step, 1,048,576-element and 24-KiB host-wire ceilings. Its B graphs explicitly use 8 spatial bins; existing default 32-bin graph and checkpoint encoding remains canonical. A preflight is a separate one-step proposal and does not prove optimizer entry in the cancelled process.

## Claim limits

The PQ acceptance exercises normal-build Linux host registration with local ML-DSA trust fixtures. It does not boot the Agentd daemon, exercise the classical AuthBus ingress, establish independent key custody or deploy a production service. Existing-owner terminal reads and cold-owner construction have distinct trust requirements.

Numerical state restoration remains complete while each subsequent training block starts from a detached state. Spatial discretization, frozen step coefficients and endpoint deposition remain approximations. BP uses task-loss autograd gradients; NDU, credit receipts, eligibility and local plasticity do not substitute for those gradients.

No production adoption, scientific gain, energy result or desktop CUDA campaign result is asserted by this archive.
