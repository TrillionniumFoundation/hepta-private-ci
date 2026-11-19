# Windows ordinary-history caller manifest reconciliation — r3

## Scope

Candidate `e3443eb41426a1dc496793e1fa5fc19c98f1eb74` and incoming ordinary Windows frontier `6cfa2345cc26e271d443d32e3fff669f7492d1bc` are reconciled against the root integration source after workspace formatting. No HIA ref is merged, moved, or deleted by this work. The original caller verifier and bounded manifest packer remain unchanged.

## Retained proof

The candidate has 1,645 boundaries and 820 unique protected files. Incoming declares 1,630 boundaries and 1,232 protected-file rows, but those rows cover only 816 unique paths. Its repeated rows were consolidated by retaining the exact union of all required, forbidden, global-order, and function-order clauses. A dictionary overwrite would silently lose constraints and was not used.

The final manifest has 1,652 boundaries and 826 unique protected files. It preserves every boundary ID and protected path from either input, all seven false authority flags, the same source roots, and the same ignored-path fragments. Thirty changed common boundary definitions were reviewed alongside all 21 candidate-only and six incoming-only definitions. Eight obsolete caller paths were removed where the joint source delegates through separately closed source-aware ports; no inactive old port was given a new caller.

One further boundary closes an already existing frozen-paired owner-borrow helper. That helper has different plan, receipt, and provider types from the incoming product paired helper. Renaming only the private frozen-paired function and its exact call/test references separates their previously identical bare function names. Each now has its own exact caller list and guarded source definition. The incoming product helper and its historical mutation markers are unchanged.

The Bao PQ current-head confirmation was already present in incoming production source but omitted from both input manifests. Its existing `final_use_host.rs` caller is now explicitly enumerated. The implementation is unchanged: one lease mutex spans the original clock read, authentication-profile dispatch, signed confirmation, and lease publication; an older head cannot replace a newer lease, and only the same epoch/revision may retain a longer lease. Its complete function and the existing Agentd PQ `authenticate_feed` function are separately pinned. This repairs an input declaration omission without creating a new production call.

## Guard migrations

Reviewed guard rebasing follows actual retained implementations, including composed Agentd startup, boxed original state slots and leases, source-aware training/receipt dispatch, one absolute IPC deadline across Windows authentication and framing, final pre-spawn native freshness, stable physical CURRENT reads and cursor restoration, complete holdout replay and permanent uncertainty fencing, and the synchronous original-owner paired release. Failed older whole-function sequences were replaced only at explicitly reviewed functions, with complete lexical bodies pinned. Original valid wrapper clauses stay on their original wrapper. All 119 protected-file decisions are recorded with old and new clauses.

Eight source edits use each actual non-StageOwners receiver type explicitly. The first two were: `CellQ24PreparedLearningV1::require_initial(self.prepared.as_ref(), initial, scope)` and `SelectionData::original_selection(&data.selection)`. The full per-file ambiguity census additionally identified three HistoricalTrust/IndependentB require_initial calls and three SelectionData original_selection calls. They now use the same exact existing types explicitly. The previous method spellings were conservatively ambiguous to the verifier because privileged StageOwners methods share the same names. The exact receiver, arguments, refusal behavior, and privilege caller lists are preserved. Neither StageOwners allowlist was widened.

All eleven source files have a reversible spelling-only proof against their pre-edit SHA256 values. The patch changes no function bodies beyond the explicit receiver spelling and private function name, no visibility, no test assertion, and no actual production caller.

## Storage and verification

The reviewed expanded TOML is 3,467,818 bytes, SHA256 `860b25f898ef8784b1e13032dd1cce22111807bba746284a6f4558f0b01dcc48`. The original packer creates an 858-byte root index and two gzip parts of 249,557 and 326,115 bytes; every stored blob is below 512,000 bytes. Original loader roundtrip reproduces the exact reviewed JSON data.

`just fmt --base MERGE_HEAD` and the narrow source `git diff --check` pass. All 826 protected-file checks and all 1,652 boundary definition/caller marker checks pass. The exact closed-caller scan over all 8,923 indexed Rust source files passes every one of the 1,652 boundaries, with zero failures and zero source drift during the scan. The complete result, every source SHA256, and the source-drift check are recorded in `boundary-r3-final-audit.json` and `delivery-r3.json`. Native Windows execution is not asserted by this source proof.

## Artifacts

- `package-r3/` contains the exact three repository postimages.
- `resolved-callers-r3-postimages.tar.gz` contains those same three files.
- `manifest-reconciled.json` is the complete expanded reviewed manifest.
- `protected-resolution-decisions.json` and `boundary-resolution-decisions.json` retain all explicit migrations.
- `source-disambiguation-r3.patch` and `source-disambiguation-r3.json` hold the exact eleven-file patch, before/after hashes, and spelling-only proof.
- `delivery-r3.json` records manifest and repository-blob hashes plus verification status.
