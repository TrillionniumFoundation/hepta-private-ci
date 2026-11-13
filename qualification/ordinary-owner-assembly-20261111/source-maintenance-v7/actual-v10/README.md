# Actual v10 maintenance and exact source successor

The original v10 launch key `af52-future-202-maintenance-v10` was reconciled with its exact unchanged request after execution access returned. The runtime returned one actual operator PTY ACK with `reused=false`: `dpty-05bb4dba0c216a294706b6b255103129dd0aa7728657a341bbc0c747d9b766a0`. The earlier NOT_FOUND/no-ACK response remains preserved in invocation; it is superseded by the observed ACK and complete terminal result, not discarded.

## Actual result

The executed source was `ac0037168295c898d8b2572d2274f4328dd08aef`, tree `d83c3cfc71304aa9e6381045efc96446eaf1a32b`, 202-file manifest `378cde8a6caa50aebb8992128cd250e437844537`.

**Maintenance failed.** The complete [RESULT](original-records/RESULT.json) records:

| Step | Actual outcome |
| --- | --- |
| fmt-before | exit 0 |
| fix-eleven-crates | exit 101; 203.554 seconds |
| fmt-after | exit 0 |
| binaries check | not run |
| total | 227.537 seconds; outer exit 1 |

No step timed out; completion_unknown is false; capture_error is null. The exact 3,144-byte [terminal](execution/TERMINAL.txt) and [original read payload](execution/TERMINAL_TOOL.json) are complete. The read-only donor remained at head `3c8dabe46598599e91b2b8b80081e09069ff9426`, tree `6fe2c2426f22383416697016445cf444aafdd2ff`, clean before and after. Both scope observations have empty outside-fixed-path and untracked lists.

The full 77,473-byte [original fix log](original-records/fix-eleven-crates.log) contains three E0432 failures in the old root_authority_session_lifecycle_tests source: it imports OriginalConsumerFailure, OriginalRootSessionJoinObservation and OriginalRootWorkerTermination through parent-module reexports that Clippy removed as unused in product builds. Warnings are retained in full; this is not a clean Clippy or native qualification result.

## Source transfer and minimal repair

The run captured four formatted files, then fourteen final source postimages after fix/fmt. Every native copy was read with its immutable file version, size and SHA256, retained as an exact Git blob and read back. Original stage manifests, patches, scope observations, all execution records and logs are preserved under original-records.

[ROOT_EXACT_TRANSFER](transfer/ROOT_EXACT_TRANSFER.json) verifies all 23 original full-index hunks forward and backward against the actual 202 input and captured native output. It also applies those same exact hunks, with unique string anchors and reverse replay, to the current 205-file source at `4c88f446fa47e35d8260886ce4b54658f349ca2b`.

Thirteen resulting files are identical to the actual native postimages. The sole source-prefix difference is root_authority_session.rs: its later cfg(test) lifecycle support-module declaration is retained exactly. This adapted postimage is `cf847deb9c9b835e976fba0a81c52139a7778d75`; it is explicitly distinguished from native 202 postimage `b04f96d7020eea414dacabc98e002bdc805d6a65`.

The [test-only repair](repair/TEST_IMPORT_PROPOSAL.json) changes only three imports to the existing private lifecycle child module. It retains all five old test bodies, assertions, waits, timeouts and normal-pause child declaration. The [independent visibility/replay review](repair/TEST_IMPORT_PEER_REVIEW.json) and Root's exact replay confirm no product visibility expansion, no restored unused parent reexport, and no modifications to the two new recording components or their support module.

The resulting [205-file source manifest](../FINAL_SOURCE_MANIFEST.json) is `091d00310a6bd34e9d060ca43f188aeac7f61d89` (59,789 B, SHA256 `f6f52aeaf8d584b7ebdd238b61405b80a14045bae71bc1da0a5878de8c563cbd`). It contains 14 actual source transfers plus the one three-import test repair. **This source successor has not yet completed maintenance or qualification.** Its current CALLERS blob is still `0f0b4c835de967f90263ae9041865f5ac431615e`; literal and explicitly documented semantic adaptation to these actual new postimages is in progress. No original full checker is claimed on stale metadata.

## Qualification state

The earlier [final-205 checkpoint](../final-205/README.md) preserves the preceding completed metadata/static-review work and its then-current execution blocker. The observed v10 ACK and failure here supersede only that old live status. Historical source claims and failures remain pinned to their original commits.

Original checker `7a6709691c372504ca11b5d2a74e14ba819fca8f`, typed helper `e23bb8aa42241b429ef5dbce5a4660853b66eb2f` and native harness `096b5b69c1295560f3a6c9e0da51e2708a0c996c` remain unchanged. The 500 ms business deadline remains anchored to original request_started_ns without renewal or rearm. Seven-package/Root17 qualification, zero retries, 27,000-second original overall and 3,600-second full-caller budgets remain required.

The separate nine-command additional runner remains unbound. The [same-source fixture checklist](extra-gates/SAME_SOURCE_FIXTURE_BINDING_CHECKLIST.json) requires actual final-source build, executable and evidence bindings; an old target path is insufficient. No extra gate or original qualification has run against this source successor.

Business acceptance is still **0 ordinary complete / 0 positive adoption / 0 genuine NoUpdate-or-rollback**, with independent C and actual daemon/Root OS restart unaccepted. PR #6006 remains Draft at its original source; no main merge or Chain installation/ref update is performed.
