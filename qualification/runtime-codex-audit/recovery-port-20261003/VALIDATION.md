# Source-preserving cognitive recovery and product-oracle repairs

## Separate failures and bounded source reuse

Context source `8b9f4b7b87dc95e3de9adcb40723eee84484717d` failed its product
recovery case while binding immutable SQLite file identity. Its cognitive store,
recovery guard, recovery helper, Agentd writer host and product-test blobs match
the corresponding pre-port runtime source. Dropping the final pool handle alone
schedules asynchronous SQLite cleanup; it is not a completed recovery handoff.

The consuming `CognitiveStore::close(self)` API from published source
`93a644126a056affa8ef42acc52a624529e98d59` awaits all pool connections closing
while the store retains its owner guard. It explicitly documents cloned-handle
quiescence. The memory exact-cut and Agentd product fixtures await it before
binding recovery-file identity. No path/descriptor, sidecar, current-cut, owner,
authority or fencing check is relaxed; the protected state/AuthBus files are
unchanged. This is a narrow hunk port, not a copy of the newer cognitive store
implementation or a merge of its unrelated schema changes.

A different HNMF source reached a later fixture mismatch: opening the new writer
legitimately appends a host-bound lease inside the complete state digest. The
published `cd9b64aca13b259c218c7a29d8182e98f57b7b03` fixture therefore checks
same profile/owner/schema, advanced state, a new generation database, unchanged
predecessor bytes and the exact lease ID/generation. The production recovery
method still authenticates the exact predecessor cut before writer creation.
Subsequent real semantic writes and revocation checks remain in the test.

The resulting Agentd product-test blob exactly matches
`8cf04ba10ecf8a1200f28e263b56c55206100675`, observed passing at cognitive
`2e0b23f9` in artifact 11245491051. That historical artifact's ZIP, TAR and 194
checksum entries were verified, including the exact test PASS within 226 Agentd
passes and 287 owner passes. Those results do not qualify this new runtime source.

## Reached product-oracle failure

Runtime `9e8baf49` Linux job 111150679017 passed 500 owner tests, 10+7 process
tests, both repaired memory groups (18+3), and both named plasticity/cutover cases.
Its newly reached daemon suite passed 14 tests, failed two and timed out once.
The cognitive write case's old SQL oracle incorrectly counted physical copied
rows for `revision_facts_v1` generations. Only the `read_kg_sqlite_evidence` helper
is ported from the qualified 2e0b source: all reads share one transaction, compact
generations count latest immutable occurrences, legacy generations count their
physical rows, and unknown storage modes reject. Receipt counts are still checked
against independently counted rows. Unrelated startup/profile tests are untouched.
Four SQLite regressions execute the helper's actual SQL; all fail against the
old helper and pass against the replacement, including duplicate-history,
legacy cross-memory counts, tampered receipts and unknown storage modes.

The two-agent startup failure still lacks its original cause in the truncated
stderr tail. The supervisord restart test timed out. Nineteen macOS supervisor
release-install PermissionDenied cases remain. None is declared fixed by this
change. The four earlier Darwin canonical-path fixture repairs did pass, raising
that library result from 476 to 480 passes.

## Verification boundary

The existing read-only matrix adds two separately nonzero diagnostic selections:
the exact current-cut memory recovery case and the Agentd product-writer case.
They remain outside the protected command inventory, preserve prior aggregate
failures, and explicitly reject zero tests. Their actual new-source Rust results
are pending hosted execution. No local Rust rebuild or shared-cache restoration
was attempted. Scoped formatting/Ruff and 75 Python recorder, deadline, artifact,
workflow, selector and SQL-oracle tests passed. An initial local command named a
nonexistent Python deadline module; the corrected invocation and final results
are retained. No production or independent qualification, activation or release
is inferred from fixture repairs or historical receipts.
