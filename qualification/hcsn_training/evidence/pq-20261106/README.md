# HCSN PQ composition: retained qualification evidence

## Source identity

This evidence branch accompanies [source PR #5067](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5067), based on HCSN gap-closure commit `44e539313e0c54badb4b9b687425dd87ecba6e67`.

The first published source candidate is `bbe995c43e4eed4bb9c217b52447ba5a32ebb6ca`, tree `e74509e6a2a49bd004b79854b3a6dbc2fe581be0`. [review-stages.json](review-stages.json) identifies its 22 review commits. Imported authority code and dependency provenance are recorded in the source tree's `SOURCE_PROVENANCE.json`; the reviewed local source is explicitly distinguished from published upstream history.

**The first source candidate passed dedicated hosted acceptance.** [Run 42240138316](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42240138316) completed successfully on `bbe995c` / `e74509e6`. [ci-01-summary.json](ci-01-summary.json) binds the results and raw artifacts to that exact source.

The final source is now `a20ea6a862e501d8a4993195c7da1ac52ca9a7be`, tree `b8e8b66b957aaf1e5e1cd9db8bb479137cf9fceb`. It adds four precise entries to the independent no-bypass inventory after the broader check found a real omission introduced by this port. No Rust or Python implementation changed. The original 17 gate tests passed locally, followed by `just fmt`; no local tests were run after formatting. **Its dedicated [run 42253531173](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42253531173) is pending. Earlier results are not relabeled as final-head acceptance.**

## First hosted acceptance

| Scope on `bbe995c` | Observed result | Limit |
| --- | --- | --- |
| Strict Python | 69 passed, zero skips | CPU float64 pinned runtime |
| Neuron, artifact and contracts packages | 392 passed, one ignored process helper | The helper is driven by the passing kill/reopen matrix |
| Automation package | 120 passed, two ignored integration entry points | Exact-name wrappers execute both across all three backends |
| Original signed bridges | A, grid B and age B passed | Full state/weights/prediction replay; next training block starts detached |
| Classical real cancellation | All three backends passed | Signed Start/Cancel, lost replies, actual worker termination, cold owner recovery |
| PQ Agentd real cancellation | All three backends passed | Actual normal-build host with local signed trust services; no daemon/ingress deployment |
| Selected Agentd regressions | 23 passed, 169 filtered/ignored | Not the full Agentd suite |
| Ordinary Agentd library and scoped Clippy | Passed | Original warnings retained |
| Source unchanged gates | Both jobs passed | Exact source and raw artifact identities retained |
| ARM architecture source-head | Five native command groups passed | Separate from HCSN; required aggregator was still queued at snapshot |

The first broader repository run failed the independent no-bypass inventory gate because three new methods and the PQ signed wrapper had not been classified. The caller verifier itself passed. The original failure, minimal patch, 17-test pass and formatting output are retained in [ci-01-controls-raw.tgz](ci-01-controls-raw.tgz), with [member hashes](ci-01-controls-files.json) and a separate [independent semantic review](ci-01-independent-inventory-review.json). Other observed failures include Windows checkout path lengths, V8 toolchain DNS/cache errors and a cargo-deny failure whose cause remains unknown because the detailed log could not be read. The [cargo-deny static assessment](ci-01-cargo-deny-assessment.json), [retained input archive](ci-01-cargo-deny-raw.tgz) and [member hashes](ci-01-cargo-deny-files.json) preserve the exact checked scope. No all-repository green claim or blanket baseline attribution is made.

## Hosted raw data

[ci-source-42240138316/source-raw-filtered.zip](ci-source-42240138316/source-raw-filtered.zip) retains **669 of 672** original source artifact members byte-for-byte. Only three confirmed compiled ELF bridge executables are excluded from Git; their paths, sizes, SHA-256 and exact native-build receipts remain in [source-raw-provenance.json](ci-source-42240138316/source-raw-provenance.json) and the complete original member inventory. The filtered archive is not the complete original artifact.

[pq-host-raw-filtered.zip](pq-host-raw-filtered.zip) preserves **all 185** original Agentd artifact members; no compiled native executable was present. The [PQ audit](pq-host-audit.json) checks 159 retained-file hashes, exact source inventories, terminal/receipt/SQLite linkage and nonce/frontier state across the three backends. The [ARM archive](architecture-source-head-raw.zip) preserves the complete original architecture artifact. Original GitHub artifact identities, expiry dates and ZIP digests are retained.

The classical tests deliberately inject lost Start and Cancel replies; the PQ fixture retains the actual initial indeterminate replies and does not inject lost replies. Both confirm the original live worker incarnation is stopped. Neither proves optimizer entry in the cancelled worker.

## Local development record

[local-validation.json](local-validation.json) retains 40 separate observations and references 132 distinct evidence files. It distinguishes observed process exit codes, test results, execution scope, and the source identity actually recoverable from each record. Unknown historical source snapshots stay unknown; the published candidate is not retroactively assigned to earlier runs.

| Observation | Retained result | Boundary |
| --- | --- | --- |
| Contracts compile | Passed | Earlier development source |
| Contracts tests | 192 passed, 5 failed with Unix-socket EPERM | Passed later on the first hosted candidate; local failure preserved |
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

## Final-head hosted acceptance requirement

The dedicated workflow must run the exact source candidate through the strict 69-test Python suite with zero skips, the three original signed bridges including second training blocks, complete native authority and automation packages, three real classical cancellation/cold-recovery cases, Agentd host/PQ/protected-source regressions, ordinary non-test Agentd compilation, and three real PQ-host cancellation/cold-recovery cases. Native binary digests, source/tree identity, per-backend outcomes, retained raw outputs and unchanged-source checks must agree.

The new cancellation workload retains the original 64-step, 1,048,576-element and 24-KiB host-wire ceilings. Its B graphs explicitly use 8 spatial bins; existing default 32-bin graph and checkpoint encoding remains canonical. A preflight is a separate one-step proposal and does not prove optimizer entry in the cancelled process.

## Claim limits

The first PQ acceptance exercises normal-build Linux host registration with local ML-DSA trust fixtures. It does not boot the Agentd daemon, exercise the classical AuthBus ingress, establish independent key custody or deploy a production service. Existing-owner terminal reads and cold-owner construction have distinct trust requirements.

Numerical state restoration remains complete while each subsequent training block starts from a detached state. Spatial discretization, frozen step coefficients and endpoint deposition remain approximations. BP uses task-loss autograd gradients; NDU, credit receipts, eligibility and local plasticity do not substitute for those gradients.

No production adoption, scientific gain, energy result or desktop CUDA campaign result is asserted by this archive.
