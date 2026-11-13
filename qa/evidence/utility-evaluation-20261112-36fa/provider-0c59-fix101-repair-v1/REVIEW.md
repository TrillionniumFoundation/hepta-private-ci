# Actual fix101: four-file compiler repair proposal

This frozen proposal repairs the six compiler errors actually reported by maintenance job `1a1d3eccd3a-392-231`. It changes four test/support files and carries the actual `witness.rs` postimage unchanged. It has not been formatted, compiled, applied to native source, or executed. The original fix remains failed with exit 101; no successful lint, source qualification, native test result, or real task-chain completion is supplied by this proposal.

## Exact observed baseline

The native source remains at commit `0c59aaca0b4932507f068c723f73da2f96729b3d`, committed tree `4b1ef6a81f8fc49d4c267d9e47bc4b8127fc8d09`. Actual maintenance changed only `codex-rs/hepta-learning-ledger/src/witness.rs`; its actual physical tree is `4ed32552042fee522965ea54caf95bbebb31ad43` with 15,237 files. The producer reports unchanged Git metadata and all 24 original inputs unchanged.

The complete fix log is 128,490 bytes, SHA-256 `e5f44de8a9cec68f785de568e24a11be0d68f64a35a64b8ac3d0acc2558332e2`, Git blob `feaf209bf89bcbdc71cdb1787a49c3433745a9cb`. Native recovered it as the exact byte range 850 through 129340 of the actual complete supervisor stdout; its bytes and both hashes match the original recorder and ARTIFACTS. This is not described as a second native read of the log file.

The actual final postimage packet is 36,709 bytes, Git blob `786b5872a8064d18f6d391b82c7af3813541c0c1`. Its single before/after pair was decoded and each complete payload checked against size, SHA-256, and Git blob. The original `length < HEADER` guard is preserved. The actual change replaces the modulo predicate with the compiler-suggested `is_multiple_of` expression. Its 13,300-byte after image is blob `a45cfde5e0d6c17a8b9502f66c43979f26f6bc4d`; the repair does not edit it.

The complete actual final inventory was independently reconstructed from the already-verified 0c59 clean inventory, that one actual postimage row, and the original 5118 compact JSON / porcelain-strip rules. The resulting 5,629,749 bytes match all three producer identities: SHA-256 `b19022cb0957b760703a1193f20b0c2934738e68f7c0cf6956fab34468c41dfa`, blob `d7e2e31df4c8d463b643874bdcd11309a1df02f4`. All four error files equal their 0c59 bytes and their complete actual final inventory rows. The recovery is explicitly an exact recovered original, not another full native inventory read.

## Six errors and their minimal repairs

| Actual error | Repair | Preserved constraint |
| --- | --- | --- |
| E0364: `pub(super) use wire::encode_original_report` exceeds the child helper's visibility | Make the parent's import private: `use wire::encode_original_report` | The child helper stays `pub(super)`; its function body, callers, and encoding bounds are unchanged. The nested test module can still use its ancestor's private import. No production API visibility is widened. |
| E0277 in the Material-only fixture | Construct an explicit `CellStepInputV1` projection from the configured Source and retain the full same-type equality check | All eight shared fields match the original private Source-to-Cell projection: scope, source frontier, objective, NDU snapshot, monotonic time, deadline, observation bytes, and candidate masks. |
| E0277 in the Fresh Training/B input fixture | Use the same explicit full projection and keep the same equality guard | Original actual-D validation, full T and candidate signature equality, DENY_ALL checks, A history binding, actual three-cut replay, credentials, and model manifests remain byte-for-byte unchanged. |
| E0599 at the three `AgentdRootAuthorityPeer::clone` call sites | Build the existing public identity record from the already-held PID, boot ID, and process-start ticks | The production type remains non-Clone. No stream or pidfd is cloned. Existing pidfd acquisition, SO_PEERCRED checks, UID checks, original timeouts, lifetime limits, and negative attacks are unchanged. The original identity is retained rather than resampled from a potentially reused numeric PID. |

`CircuitTaskSourceInputV1` and `CellStepInputV1` have different meanings. The Source additionally holds `lease_duration_ms`; the Cell additionally holds the operation ID derived by the original dispatch. The repaired projection does not invent an operation ID or assert a new lease equality. It preserves the operation ID already held by the opaque original publication. The Source owner's original registry binding, request construction, lease bounds, and original publication revalidation remain unchanged. The guard checks complete Cell input content rather than a digest or selected subset of fields.

The two projections reproduce `CircuitTaskSourceInputV1::input` in exact original source blob `68cf423686f24d192d015b0c06e86eea530dfc81`; no private production method is made public. Cell input's existing same-type Eq/PartialEq contract is in blob `712fe850d16abeea3dc859827e0082bf3343c780`. The unchanged peer type and its pidfd/boot/start/UID checks are in `9d3d24bd5104be99372c8a55859360e792120605`.

## Preservation and proposed successor

Applying the recorded inverse substitutions restores all four complete before files byte-for-byte. There are no new or removed functions, tests, modules, production methods, callers, permissions, retries, budgets, or source deletions. The complete `witness.rs` after image is carried separately as an observed change, not credited as a manual compiler repair. No coordinator file is included.

A mode-aware Merkle reconstruction first reproduces the exact committed tree and then the actual one-file physical tree. Applying only the four proposed replacements to that actual baseline produces expected tree `1eacf738a9ee86fe6b7bf2ab5d20a45d63c066f1`. This tree is a computed proposal, not a native observation or a published source commit. File count and modes remain unchanged.

`SOURCE_PACKET.json` contains the complete four repair before/after images plus the complete carried actual witness pair. `REPAIR_DELTA.patch` contains only the four manual repairs. `SOURCE_MAP.json` has the five resulting full-file identities and labels each origin. `EXACT_INVENTORY_RECOVERY.json` records the recovery evidence, and `EXACT_INVERSE_REVIEW.json` records the byte-preservation checks.

Root has directed the possible successor to apply the reviewed repair and run one separately approved fmt-only operation under the original 900-second limit, followed by new-source qualification under the original gates. The original single fix attempt is not automatically repeated. This package does not dispatch or approve any of those operations.

## Outstanding evidence

Independent review and Root's exact engineering approval remain external to this package. Subsequent formatting, compilation, source closure, caller verification, native tests, real public three-UID operation, and useful independent A/B/C results remain unproven. The real completed task-chain count remains zero.
