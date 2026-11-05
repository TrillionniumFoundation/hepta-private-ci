# 40-module recovery: immutable first full-suite checkpoint

## Source and outcome

Executed source: `f5813506b49eb05efad00f203b9362195875892c`; tree: `00d62de1c2f6ac8a229d23ce9d8e1b9f34b333df`.

The original seven-package command finished with exit **100**: **1,219 tests run, 1,217 passed, 1 failed, 1 timed out, 78 skipped**. The original profile's retry is retained. Both failed cases are in the controlled real-process `paired_process_product` target. This checkpoint is **NOT_CLEAN**.

All **69** named required cases passed cleanly, but the audit correctly rejects the overall suite because of the other failures. The seven original strict navigation/status/registry/document/custody/CI-feedback/metadata checks each exited zero. None of these results establishes production acceptance; all 40 module production flags remain false.

The runtime's authoritative final record confirms job `1a1ac0f4d64-fc05-51fb` failed with exit 100, complete durable output, no cancellation and no outer job timeout. The test timeout is an inner Nextest case result.

## Complete original evidence

`native/run1-checkpoint.tar.gz` contains 104 files, including its `MANIFEST.json`. The manifest binds the remaining 103 files by exact byte length and SHA-256. The archive includes original command receipts and logs, raw native JUnit and Cargo metadata, the source-bound 69-case audit, environment preparation records, source transition records, and exact intermediate native commit objects/patches. No original failed attempt is replaced by a later run.

Archive SHA-256: `15e6b5e5c97f94c162f7c0a89938b276d4e2d4c4583f1ecb4e78d363e4bd12e1`; bytes: 355709.

Original suite log SHA-256: `9e8c56e0b87006458848eb9624b691ff21451cca0f8b21bfc7faea5941458043`.

Raw JUnit SHA-256: `01a496eef41379e022cb756d146af778ad47fe915ba679741f66e75002a2fd42`.

The reporting-only JUnit configuration did not change selection, timeouts, retries or assertions. The full seven packages were agent-protocol, agentd, infer-worker-host, runtime, contracts, learning-ledger and supervisor; the 69-case list was an outcome audit, not an execution filter.

## Earlier matched native source regressions

| Stage | Exact native commit | Result |
| --- | --- | --- |
| Memory-only preparation | f33819baa603965ce4a8e3f6c1ffef12b5e64cb4 | Build preparation exit101; stale relocated CMake cache. Not behavioral RED. |
| Combined preparation | a3a987d0337efa8707d7f04d0b28a8f8f65b7eb9 | Build preparation exit101; missing multiarch OpenSSL include. Not behavioral RED. |
| Memory and ledger RED | a3a987d0337efa8707d7f04d0b28a8f8f65b7eb9 | 4 failed, 0 passed, 757 skipped; exit100. |
| Matched memory and ledger GREEN | 6d63f3f2444e194a46330780e2b1f67adfe4f289 | 4 passed, 759 skipped; exit0. |
| Handoff RED | 4fbf4f101e1bd0faf3267d7ae20e937822183346 | 2 failed, 0 passed, 108 skipped; exit100. |
| Handoff GREEN | c1f586bc8d18e4e3d3e469137fb12b4cbfa02963 | 3 passed, 108 skipped; exit0, including actual Unix fork. |
| Witness and ledger GREEN | c1f586bc8d18e4e3d3e469137fb12b4cbfa02963 | 5 passed, 121 skipped; exit0. |

These are separate execution identities. Their results are not transferred to canonical commits merely because a tree or selected file set matches. The native complete seven-package experiment above separately executed canonical f581.

## Boundaries and next candidate

The source repairs cover SQLite final-use revalidation after callbacks, historical authenticated Decision/Outcome append reconciliation, witness recovery synchronization, and acquiring-process ownership of handoff locks. The complete suite exposed an outdated Drain response in a controlled child and a five-pair timeout. Their subsequent diagnostic/fix experiments are separate records, not replacements for this checkpoint.

Real provider/authority activation, default daemon D/O lifecycle, physical interruption qualification, Windows full qualification, external effects and final production acceptance remain open. PR #4869 remains a draft. No main merge or activation is part of this evidence publication.
