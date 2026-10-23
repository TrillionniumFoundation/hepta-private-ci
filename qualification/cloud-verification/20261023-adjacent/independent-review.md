# Independent review: adjacent recovery coverage

Base HEAD: `3d38cc6e786179661d213e815c9b4f0761b2664a`.
Reviewed `git diff --binary HEAD` SHA-256: `2a7dae68cea62c0f68281af6a77c29978ef5767c3f19236d90067864499a25a0`.
UTC: 2026-10-23T16:19:30.869243+00:00.
Scope: exactly two test files, 149 added lines; no production source changes. Per-file hashes are in independent-review-source-manifest.json.

## Decision

No blocking defect found. These tests exercise existing product store behavior and preserve precise fail-closed expectations. No newly reproduced product defect or justification for changing production implementation was found. Publishing test-only coverage is appropriate, subject to parent validation/remote verification. The assertions do not establish production Runtime, hardware or power-loss acceptance.

## Nonce recovery matrix

`hepta-contracts/src/final_use_nonce_tests.rs:340` mutates three actual 40-byte frames after closing the real local authority. Every case reopens twice and requires the on-disk bytes to remain unchanged.

- Dropping the first, middle or last full frame leaves a structurally valid but different nonce set; the independent trusted frontier must reject it as AntiRollbackViolation.
- Duplicating a current-epoch frame is rejected by read_claims' BTreeSet insertion check as InvalidTrust. The case named duplicate_middle copies the middle frame to the end, which correctly tests duplicate membership rather than ordering.
- A zero nonce and partial final frame must fail parsing as InvalidTrust; a changed nonzero nonce yields a structurally valid different set and must fail the trusted frontier comparison as AntiRollbackViolation.
- Rotating whole frames is correctly accepted because the active record format stores epoch + nonce, not a sequence number. `frontier_for_state` hashes the canonical BTreeSet. The positive path then rejects all three consumed grants as AlreadyClaimed, so allowing reorder does not refund authorization. This is a set-membership/replay contract, not ordered-log integrity.

The exact offsets (0/40/80, tail nonce bytes 88..120, byte100 corruption, truncation119) match the active 40-byte format and three-record fixture. Expected errors follow the actual parser-before-frontier ordering. No broad is_err replacement or permission relaxation was introduced.

## Durable generation recovery

`hepta-operations/src/durable_store_tests.rs:404` now closes the actual SQLite pool and reopens the store after the generation-2 adoption transaction. Full operation equality checks that generation, fence, state and remaining recorded fields persist, rather than checking only a selected generation field. Existing later assertions now run against the reopened store: stale observer generation is rejected, same-generation adoption is idempotent, and current-generation terminal observation completes.

The added renew_claim assertion at lines416–421 is valid but has a narrower evidentiary meaning than a generation-only fence test: the outbox is already Acknowledged (line401), and require_current_lease rejects any state other than Leased before checking owner generation/fence. Therefore this assertion proves an old claim cannot renew that recovered acknowledged dispatch; it would still pass if only the generation comparison were removed. Do not describe this one assertion as independently isolating the generation or fence comparison. The persisted full-row equality and stale observer StaleGeneration assertions establish their separate properties.

## Final follow-up: isolated lease-generation/fence checks

The final diff also extends `expired_safe_lease_can_be_taken_over_by_higher_generation` at durable_store_tests.rs:139. Both real SQLx pools now explicitly `close().await` before reopening; this resolves the initial review observation that merely dropping handles does not establish completed pool closure.

The fixture reuses the current valid generation-2 claim. One copy changes only owner_generation to 1; a second changes only fence to the predecessor fence. Each must return exact StaleLease. The unmodified current claim then successfully renews. This positive control is critical: expiry, non-Leased state, worker mismatch or mutation caused by either negative attempt would also make the final renewal fail. The original one-second lease remains unchanged. Thus the final fixture separately exercises persisted generation and fence rejection in an otherwise valid Leased state, overcoming the acknowledged-outbox ambiguity noted above. No product validation, time limit or error predicate was relaxed.

## Still unproven

- The new cases do not start competing OS processes, exercise simultaneous lock acquisition, kill the SQLite owner mid-transaction, or measure delayed disk durability. They run close/reopen within one process.
- Existing FinalUse killed-owner/StateLocked tests elsewhere are distinct prior coverage, not newly re-executed or expanded by this two-test run.
- The trusted frontier fixture is an in-memory test implementation surviving a local authority reopen. It is not an independent production service with demonstrated crash durability/custody.
- No malicious mutation racing the read/check, same-process memory loss, lost physical acknowledgement, remote observer identity, actual external effect or power-cut guarantee follows from this matrix.
- The acknowledged-outbox assertion alone still does not isolate generation/fence checks, but the new otherwise-valid Leased-row negative/positive controls now cover that distinct property. Cross-process SQLite ownership and abrupt process termination remain outside these in-process tests.

## Checks and evidence attribution

Independent reviewer inspected the complete final two-file diff, the active read_claims/frontier implementation, require_current_lease, renewal updates, pool close implementation, adoption and surrounding recovery assertions. `git diff --check` passed. No Cargo process was started by this reviewer. The supplied focused-tests.log records the earlier parent run: 2 passed, 232 filtered out. That log predates the final isolated lease checks and explicit pool close, so it is not final-source qualification. The parent is creating an exact source commit and running all three scoped crates against it; report that completed SHA/result separately. No execution is reattributed to this reviewer. Pending hosted CI remains pending.

Final parent-supplied validation checkpoint: all-tests.log records 250 passed / 1 skipped across the three scoped crates; clippy.log finishes successfully. The parent will still perform exact-commit verification before publishing. These remain parent executions, not independent reviewer executions.
