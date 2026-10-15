# Original CPython upstream method execution: evidence, not autonomous repair

Research-only continuation of PR #2234, October 15, 2026. Remain Draft / DENY_ALL. No production merge or gate waiver.

## Immutable source identities

Original six-project Git source ZIP SHA-256:
a4c7b9868461c11558546bd582796255cbca682c938a1704d62cd93a556406b4

Independent binary reopen ZIP SHA-256:
59dee0a84099f6fb101dbfd5420c569f10c44a2d8a7b67c984e381edf4db9d36

Original CPython Lib/http/client.py SHA-256:
8486d3c54d5ab5a8468703239287e60127d7f2159f5ae6652b33a456a3716444

Original CPython Lib/test/test_httplib.py SHA-256:
347061ba9071babdcabcc74d4d1c2581a567f9d788864e3c4d958c2c3c009907

Pinned independent test worker SHA-256:
1c183ce9e378796bd102f627d77059ac387e2cb6564ea908751155fa54fbb887

A bounded, no-network Python 3.13 child runs the original HTTP implementation, original FakeSocket helper AST and 14 unmodified original upstream unittest methods. It does NOT run the full CPython test suite. All Git source and original test text are independently SHA-checked. The unmodified original method ASTs are imported into minimal test class shells without changing assertion bodies. Memory/CPU/time/file-output limits are imposed on every fresh process.

## Measured five-phase original test outcome

| Frozen phase | Original method invocations | Passed | Failed |
| --- | ---: | ---: | --- |
| Original baseline | 14 | 14 | 0 |
| Controlled synthetic incorrect header | 14 | 13 | 1: HeaderTests.test_putheader |
| Controlled synthetic send-byte corruption | 14 | 13 | 1: BasicTest.test_send |
| Fresh original after header fault | 14 | 14 | 0 |
| Fresh original after send fault | 14 | 14 | 0 |

Total: 70 original method invocations over 14 distinct selected upstream tests, 2/2 deliberate behavioral faults detected, and 2/2 clean-process resets successful. The injected faults are synthetic behavior modifications of genuine code, NOT discovered real-world CPython bugs; removing them is NOT autonomous agent recovery or program repair.

Five raw original worker receipts are retained create-only, then reopened by a separate source-only independent scoring process. That process independently regenerates original test method digests, checks all original statuses and rejects omitted, reordered, fabricated, additional, rehashed, or symlinked result records. The exact canonical result JSON SHA-256 is:
dc17462c33dbdf2ccef89f8d46fd2f93cefa6dd0d2374b0c8e9d3729b3da8892

Actual local source-backed checks: 29/29 ordinary and 29/29 Python -O unit tests passed with zero skips; original run versus independent score JSON matched byte-for-byte. Exact-HEAD hosted checks must independently complete.

## Strict remaining scientific admission

Prior mechanical source retrieval on the twelve already exposed cross-file questions is not natural-language Reader or real program repair. The executable upstream selected-method harness is now a common evaluator. Any frozen strong RAG, organized evidence graph, trained reading policy or parameter-memory agent must have the SAME original source and test-tool permissions, evidence budgets, reader/model identity, instruction/prompt, timeout, and diagnostic privileges. New independent future-source tasks, sealed candidate edits, independently checked semantic/behavioral success, matched total work and complete lifecycle TCO remain required.

Negative capability claims remain explicit: pretrained_model_calls=0; independent_future_task_families=0; real_program_bug_repair_success=null; learned_memory_task_gain=null; complete_lifecycle_tco=null; production_qualified=false. No promotion, FinalUse or production merge; blocking-ci, Architecture, owner/revocation and independent evaluator requirements unchanged.

## Reproduce on an isolated Python 3.13 host

Set PYTHONPATH=scripts/memory_cell, MEMORY_REAL_SOURCE_ZIP to the SHA-pinned original ZIP, and MEMORY_REOPEN_ZIP to the independently reopened ZIP. Run both ordinary and -O test_memory_original_upstream_replay.py discoveries in scripts/memory_cell. Invoke memory_original_upstream_replay.py with mode run, both source ZIP paths, a create-only journals directory and output JSON file. Invoke the same module with mode score and the exact existing journals directory but a fresh output path. Confirm the two scored reports are byte-identical and have the published SHA-256. The new read-only GitHub Actions workflow contains these exact subprocess commands and retains the five raw receipts even if subsequent checks fail.
