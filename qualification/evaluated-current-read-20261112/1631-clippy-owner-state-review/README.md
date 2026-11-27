# Original resident state ownership repair

This candidate is based on exact 1631e01fd086f79bef8bf19bd6fe5859565b7976, tree 55f93e74a4f5e3c570e1cd837cb9998998d1dadc. Its source-only combined tree is 72b02cdf6c3a4ca577e0a11935c7d5d8ecd1f0d1. No commit or ref is created by this evidence bundle.

## Observed failures

Original Linux Clippy job 131270677503 rejected 11 Tokio mutex guards held over await and four expect calls at 15 unique positions. All six affected files are byte-identical to fixed upstream a96d1b821d10ed3d9e99dd06c5141f9f242ae318. This provenance does not claim that upstream was independently compiled. CLIPPY_DIAGNOSTIC.json retains original excerpts, source blobs and the full-log binding.

The same head's separate Blob policy job 131270335481 failed during Fence setup before checkout or the checker. Its local_control_inventory_unavailable failure does not establish an invalid CALLERS pin.

## Changes

ResidentLane holds the original non-Clone state in one Box allocation. A short std::Mutex scope transfers that same Box into a private owning lease. The future retains the pointer rather than embedding the large resident state, and no storage mutex guard spans I/O. A second lease sees QueueFull. Normal return and cancellation restore the same allocation with every original failed flag and identity intact. Poison permanently refuses admission. An occupied return fences the slot without replacing its existing value. No channel cloning, constructor callback, signing surface, new grant, lint exception or checker exception is introduced.

The original owner and Root I/O order and await counts remain unchanged. The Candidate, Evaluation and Model failure flags still become true before their first operation and clear only at the original successful end. NoUpdate retains its original client cancellation and Root effect checks. Four private construction or fixture sites use the same slot. Execution-store fixtures propagate construction errors while retaining the original owner outcomes as a typed inner Result; all seven methods and 90 assertions remain.

Three Rust mechanics tests exercise cancellation with the original identity and failure fence, competing admission, conflicting return, and a poisoned storage mutex. The intentional panic occurs only in the poison test's joined thread. These cases do not qualify physical CURRENT, Root custody or scientific effects.

Eight existing protected-file rows track exact private ownership expressions with their original checks preserved. A ninth row protects the helper and its Box-backed storage. All 541 boundary IDs, their order and product caller sets are unchanged; protected-file rows increase from 389 to 390. All 56 existing QA files were statically scanned. Three exact markers change; rejection assertions and methods remain. The active allowlist has only the current CALLERS pin.

Three separate root-authored test repairs are included. The runtime expiry fixture retains a full preparation window, waits for actual wall-clock expiry with a bounded monotonic timeout, then performs its unchanged quarantine call and rejection assertions. The candidate evidence fixture adds an inclusive final-second positive control and compares original rejection and renewed acceptance at the same checked next second. The model proposal fixture distinguishes the original Ineligible NoUpdate binding error from the exact InsufficientEvidence evaluation error; both original dispositions and unchanged proposal-byte assertions remain. Production expiry and evaluation semantics are unchanged.

## Validation status

This candidate has not run formatting, source tests, full caller verification, Rust compilation or native tests. Prior-head results are not inherited. PATCH.diff reconstructs all original and final bytes. MANIFEST.json binds all 20 source/config postimages (378 additions, 127 deletions). CONTROL_FLOW.json records static checks only.

The original 1631 native job compiled and executed 1,733 ordinary cases: 1,697 passed and 36 failed, consisting of five ordinary failures and 31 stack overflows. The root's two ordinary fixture assertion repairs are included here; the other three failures and the stack overflows are addressed by separately reviewed candidates. Fresh JUnit was retained by CI, but Root execution and maintenance were not reached. The original 1631 caller-proof job 131269839839 completed successfully; that result applies only to its original source, not this candidate.
