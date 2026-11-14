# Independent source-only review: one-history content memo

Decision: PASS_SOURCE_ONLY_FOR_ONE_FIXED_SAVED128_WORK_QUALIFICATION, subject to parent execution admission. This is not an execution result, a performance conclusion, production approval, or strict256 budget certification.

Candidate: `strict-history-content-memo-candidate-v1`.
Final FREEZE SHA256: `4b0653dddd7465e9740e4d723ee492db89a9587320b287bc082c4b8adcc68828`.

All five frozen files were independently hash-checked. Original `actor.py` and `stages.py` hashes match their pinned identities. The INPUTS manifest is the same 392-file manifest as the prior saved128 review. RUN_ONCE was absent at admission. This review read source and saved JSON reference metadata; it did not import or execute the candidate, original history, model, or tests, and did not decode arrays. Only this external review directory was written.

## Semantics and freshness

The exact original bytes_get AST is compiled with only its sha dependency changed. The exact original history AST is compiled without transformation. The previous equality helper is not used. Boundary SHA, canonicalization, JSON reads and all original state/ref checks continue to use the original helpers.

Original bytes_get validates the reference, checks the path's symlink status, freshly opens the path, reads expected_length + 1 bytes, records actual logical bytes/read calls, and rejects wrong length before invoking sha. This complete sequence remains intact. Memoization cannot return old file bytes, skip a read, or bypass a reference comparison.

ContentMemo accepts exact builtin bytes only. Its key is the newly read immutable byte string, not a path, timestamp, expected SHA, or old file metadata. Python dictionary lookup requires exact byte equality after hashing, so a dictionary hash collision does not equate different content. A cache hit returns a digest previously computed from exactly equal bytes, after which the unchanged reader still compares it to the current expected digest. A wrong expected digest therefore rejects even on a hit. Same-size mutations become distinct byte keys. The original trusted-local filesystem and SHA identity assumptions are retained; there is no new adversarial filesystem or race guarantee.

## Scope and bounds

Every history_call creates a new memo. The final revision snapshots its statistics and clears all cached keys in a finally block, including ordinary validation refusals and propagated exceptions. This prevents exec-created function/global reference cycles from retaining cached key payloads while awaiting garbage collection. The statistics report pre-clear occupancy, not post-return retained memory. The file sequence also clears its cache on successful completion; the separate capacity fixture remains a bounded object until process exit.

At most 16 distinct byte strings of length at most 4096 are admitted, with no eviction. Retained key payload is therefore at most 65,536 bytes, plus bounded dictionary, digest-string and object overhead. Larger inputs are always hashed and never admitted. This is a per-memo payload bound, not a whole-interpreter RSS bound. Original per-read limits and the 256 MiB process address-space limit remain.

## Prospective coverage and independently derived ledgers

The frozen nine history calls comprise original/memo complete128, a second memo complete128 for scope reset, and both implementations at wrong boundary 0, 64 and 128. Metadata-only reconstruction independently agrees with the frozen full-walk expectation:

- Full128 original: 256 fresh reads, 1,680,512 logical payload bytes; 256 payload SHA computations over 1,680,512 bytes.
- Full128 memo: the same reads/bytes; 174 payload SHA computations over 1,612,780 bytes; 82 hits; 16 retained entries totaling 13,216 bytes before clearing.
- Tail64 memo: 128 reads, 840,256 logical payload bytes; 80 SHA computations over 800,608 bytes; 48 hits; 16 entries/13,216 bytes before clearing.
- Wrong boundary 128: one walk counter, zero visited leaves and zero payload reads in each mode.

These are predictions from saved reference metadata, not proof that the candidate has run or that declared SHA aliases necessarily contain identical bytes. The frozen execution must validate actual bytes and satisfy the prescribed counts.

The temporary-file sequence genuinely changes only new RUN_ONCE files. It covers identical content at another path, wrong expected SHA on a hit, same-path same-length mutation with stale reference, a new correct reference, restoration, appended and truncated bytes, and symlink refusal. Four cases accept and five reject per mode. Length mismatches reject before SHA, and the symlink case rejects before a payload read. Each mode must record eight fresh reads totaling 88 bytes and six digest attempts. Original performs six SHA computations over 66 bytes; memo performs two over 22 bytes and records four hits. A hit itself is not evidence of admission: the wrong-reference hit must still reject.

Successful total WORK, including both temporary-file sequences, is independently predicted as:

- history_walks: 9.
- history_leaves_validated: 768.
- payload_read_calls: 1552.
- payload_bytes_read: 10,083,248.

The separate capacity/type fixture has 21 calls, 20 SHA computations, 81,922 hashed bytes, one hit, 16 entries and 65,536 retained key bytes. Bytearray is rejected before counters change. It does not contribute to payload-read WORK.

## Cost and interpretation

The proposed per-full-walk reduction is 82/256 payload SHA invocations, or 32.03125%, and 67,732/1,680,512 hashed payload bytes, about 4.03%. All logical payload reads remain. Dictionary content hashing, equality checks, allocation, compilation and memory have real costs not represented by the SHA counters. Reference creation, qualification checks and input barriers also invoke hashing outside the scoped payload counters. No total-program SHA count or CPU improvement follows from these numbers.

There is no per-case timing measurement or timing winner selection. The one repeated memo history is a fixed state-isolation qualification, not a repetition added to search for a favorable timing result. Wait4 CPU is retained only as invocation cost.

The wrapper retains exclusive RUN_ONCE creation, one pinned CPU, child 4 CPU seconds / 45 wall seconds, outer 6 CPU seconds / 60 wall seconds, 256 MiB address space and 2 MiB per-file limits. The worker owns the shared benchmark lock. Its release alone does not prove outer-wrapper termination; both terminal states need separate verification. Whole-child wait4 plus outer prefix still leaves a nonzero unknown outer tail and additional preparation/review/history cost. Per-process limits do not prove a strict complete-subtree budget.

Caught failures preserve their exception and completed test records. In-progress local observations may not have been appended, and a hard kill may leave no RESULT. The final PLAN now states this limitation accurately. No retry or outcome-driven cache-size change is admitted.

A successful later result would support only this fixed, trusted-local saved128 work-count qualification and separately reviewed future integration. It cannot release HOLD_NEW_TRAIN, overcome data-access denials, certify natural-data benefit, establish guaranteed256 completion, or authorize deployment or training.
