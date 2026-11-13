# Hepta utility evaluation: actual repair and formatting evidence

This is a fixed evidence window ending at **2026-11-13 09:29:50 UTC**. It closes the failed original maintenance attempt and the separately reviewed four-source repair plus original formatting run. It also retains explicitly unexecuted Root-custody proposals. Later source registration and execution are outside this window.

**Real qualified task chains: 0. Qualification: false.** No current-source compilation, source-gate pass, ordinary test pass, Root test pass, deployment, model adoption or process-cold recovery is inferred from these commits.

## What actually ran

| Operation | Original job | Actual result | Meaning |
| --- | --- | --- | --- |
| Isolated source materialization | `1a1d3cdda18-392-1e2` | Supervisor exit 0; complete original source `0c59aaca0b4932507f068c723f73da2f96729b3d` | Earlier source preparation only. |
| Original scoped maintenance | `1a1d3eccd3a-392-231` | Supervisor exit 1; `just fix` return 101; its formatter never ran | The original single fix attempt remains consumed and failed. Its one actual witness change is retained. |
| Four exact compiler repairs plus original formatter | `1a1d41eb3ef-392-2b2` | Supervisor exit 0; only `just fmt --base c0f78493f815780f68b9bf5e390a21314d79311f` ran, with the original 900-second budget | Four reviewed files were applied, followed by 62 actual formatter transitions. Tests dispatched: 0. The producer result remains `APPLIED_AND_FORMATTED_REVIEW_REQUIRED`. |

The formatter's success does not turn the earlier fix into a lint pass. The four compiler repairs have full before/after byte review but have not yet been compiled in this source version.

The actual physical source contains **15,237 files**. It moved from failed-fix tree `4ed32552042fee522965ea54caf95bbebb31ad43` through four-repair tree `1eacf738a9ee86fe6b7bf2ab5d20a45d63c066f1` to actual formatted tree **`f905b18e6b05de1582024548179725a05d932536`**. Its 5,634,549-byte complete inventory has SHA256 `bc6b9d59143004236665bb9446e2c45d1ac77cd7aaba14ba7cee8f4ea76d003f`.

The original isolated HEAD and index remain at the earlier `0c59` source; this is a recorded dirty physical source, not a clean final candidate. Relative to that HEAD, the full delta is the 62 formatted paths plus the preserved actual witness change.

## Original receipts and independent closure

- [Complete original runtime archive](provider-0c59-fix101-apply-fmt-runtime-v1/PLACEMENT.json), [producer RESULT](provider-0c59-fix101-apply-fmt-runtime-v1/RESULT.json), and [authoritative normal](provider-0c59-fix101-apply-fmt-runtime-v1/MAIN_STATUS_02.original.json).
- [Root independent runtime closure](post307-root-review-v1/ROOT_ACTUAL_FMT_RUNTIME_CLOSURE_REVIEW.json): all 51 original read SDKs independently decoded, 41 complete binary paths checked, stdout 0 through 1,450 bytes and empty stderr reconstructed against the authoritative terminal.
- [Root complete source review](post307-root-review-v1/ROOT_ACTUAL_FMT_SOURCE_REVIEW.json): all four actual application transitions equal the approved repair; every byte of all 124 formatter before/after file bodies is checked; the complete mode-aware 15,237-file Merkle tree is independently recomputed.
- [Independent formatter semantic review](provider-0c59-fmt62-semantic-peer-v1/REVIEW.json): no non-formatting authority, assertion or semantic change identified across all 62 actual transitions. This is a concrete static review, not a Rust compiler or behavioral result.
- [Exact complete-inventory reconstruction](provider-0c59-fix101-apply-fmt-v1/exact-inventory-recovery/RECOVERY_REVIEW.json): all raw, gzip and bounded-part identities equal the original producer's observations. The status text is deterministically reconstructed from the unchanged index and observed complete transitions using the original serializer. It is not a second native full-inventory read.
- [Actual source-object availability](provider-0c59-actual-fmt-source-v1/SOURCE_AVAILABILITY_REVIEW.json): the 62 observed formatter postimages were individually created and fully read back as Git blobs, and the preserved witness was fully read back. The actual Git tree reconstructed from those bytes is `f905b18e...`.

The original records report all 39 inputs unchanged, all 41 read-only commands returning zero, four identical raw Git states, identical complete raw Git metadata before and after, and the retained cooperative source lease. Root independently checks their full bytes and the original SDK linkage. Process-guard observations are point samples; the source lease is cooperative and is not a claim of system-wide exclusion.

The producer lists 217 retained native artifacts. This archive does **not** claim each native path was separately downloaded. In particular, the 555,136-byte HEAD working patch remains retained on the original host with its recorded identity. Actual apply/formatter packages and the exactly reconstructed final transition and inventory are preserved through bounded lossless parts. Original failures, local verifier corrections and their provenance remain in the associated records.

## Root custody candidates remain unexecuted

The separately frozen production, mechanism-test and cold-entry layers retain one original Initial publication operation. They consume the original Prepared once, preserve same-operation readback on uncertainty, use only the original recovery, and pass the consumed original Ready through the existing task factory. Retirement retains the factory's actual task, Cell and Source.

The cold entry reopens the concrete original Current and existing journal. Its mechanism cases retain other fixture owners in the same process. It is not evidence of a real Root process restart, independent authority acquisition, daemon/Source/Cell cold recovery, or a real authorized task chain. A five-second fixture shutdown timeout remains an error with terminal state unknown; Drop cancellation alone does not prove a joined worker.

The actual-format rebase is a nine-path proposal: three existing paths and six new paths, with candidate tree `a0bd2241a3a005b68a4682a339d2be016fa3fa72` and 15,243 files. Its [Root byte review](post307-root-review-v1/ROOT_COORDINATOR_F905_BYTE_REVIEW.json) and [independent review](coordinator-f905-independent-peer-v1/REVIEW.json) do not authorize application. A separate [metadata-getter naming layer](coordinator-original-metadata-getters-v1/REVIEW.json) is preserved as a candidate; it changes only new APIs and their new mechanism callers, keeping original production function bodies unchanged.

The newly added public methods currently have mechanism callers and exports but no actual non-test Root-host startup/recovery caller. The normal host integration remains an explicit open item. The existing 39 Root workflow parents and nine proposed additional ignored cases must be fully registered and actually selected under the original exact-JUnit checks. Neither compilation nor an ignored skip will count as a pass.

## Next engineering boundary

The [new-source route-B plan](post-f905-new-candidate-hold-v1/PLAN.HOLD.md) remains HOLD. It preserves the original clean `cc57c7198db6293ccca562253c42fffbe2a04633` donor, the original materializer and its sole-parent predicate, and prepares a fresh isolated candidate. The old `0c59/f905` worktree and its records are retained. Final source map, candidate commit, complete inventories, transport sizes and exact typed requests must be frozen before any further execution.

A new changed-source maintenance attempt needs its own concrete single-attempt contract and original budgets. It cannot reuse the already consumed fix authorization. After actual maintenance, source protections and QA must match the actual resulting bytes, followed by the original final-format, canonical-source, full source-gate and native workflows. Existing guards, permissions, methods, attack assertions, filters and budgets are not waived.

Engineering review JSON, including fields named Root approval, is coordination evidence. It is not a Hepta runtime Root grant or an authorization from a missing Model, Selector, Version, Training or FinalUse owner.

## Utility semantics and remaining goal

Complete evidence and all hard constraints are required before Adopt or complete NoUpdate/Ineligible. Missing outcome, cost, provenance, independence, availability or original authority remains InsufficientEvidence/Unknown. A known failure is retained as a failure; it does not by itself establish complete NoUpdate or Objective Fraud.

The remaining real-world chain is still:

**Authorized real A → original Training owner → independent B → Adopt or complete NoUpdate → actual new consumer C → daemon and Root process-cold recovery.**

Source-code blob availability does not establish model-material availability, lawful authorization, independent evaluation, actual consumer use or full frozen-contract cost accounting. Those require their own original owners and observations.

The preceding published evidence window remains available at [30717b6b](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/30717b6b66f1a825c6e3113f26ec9732f5aae8c7/qa/evidence/utility-evaluation-20261112-36fa/README.md). This increment preserves every earlier non-README evidence file.
