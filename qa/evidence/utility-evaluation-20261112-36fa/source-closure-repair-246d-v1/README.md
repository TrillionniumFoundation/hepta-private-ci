# Exact 246d source-closure diagnosis and five-file repair proposal

This directory preserves a reviewable proposal based on actual source commit
`246d8cb614770252ee42029a5c014f2a4904176a`, tree
`d5646a6ddeb98790b7a86aa5b4fe1bc95fbb3087`. It does not activate source, publish
a commit, or grant authority. There are still **zero demonstrated real authorized
A → independent B → new consumer C task chains**.

## Actual failure remains a failure

The original source-closure command exited **1**, without a timeout. The complete
118,496-byte raw log has SHA256
`f51a3e278d6e5072b0c13b94c2279eaa890419e8445af5e12eb9021565ecb29f`
and Git blob `f84b983ace7dfd3dbe8de0a3972274d0f8a930e3`.

The unmodified runner records 486 passed and 6 failed entries. Independent parsing
of the full unittest output finds **488 explicit OK methods, four failed methods,
492 total methods, and six failure entries**; one failed method has three failed
subtests. Neither the recorder nor its original JSON is changed to reconcile the
different counting conventions. The original full caller gate subsequently
passed on 246d, but the overall source job remains failed because closure failed.
That later result is not a run of this repaired proposal.

## Four causes and the exact repair

| Failure | Source-backed cause | Repair and retained constraint |
| --- | --- | --- |
| Observer function inventory | The protected NextUse owner now includes the private `require_profile` method, while the QA exact expected set omitted it. | Add that one actual function to the exact set. The original per-function ordered-marker mutation loop now also reaches its existing protection. All previous markers and attacks remain. |
| Selection readback operation | The actual function uses `if context.evaluated.is_some() { … } else { OPERATION }`; two mutation strings still referred to old `match` arms. | Move the two original attacks to the exact actual legacy fallback and evaluated condition. Add one same-length mutation of the actual evaluated operation domain. The original mutation helper, purpose/action/context checks, and method remain. |
| Three Training readonly adapters | The original matcher gives identifiers a word-boundary suffix. Its old `recover_original` and `::recover_` entries do not match the full `recover_original_custody` identifier. | Append the complete actual identifier to only protected rows 386, 387 and 388. No existing forbidden marker is removed. The original Training QA is byte-for-byte unchanged, including all seven attacks over all three paths. |
| Root workflow inventory | The workflow already includes the new UID-0 late-B-loss issuer case, but the exact QA issuer list still had six entries. | Append the one actual full test name to that list. Preserve the original six names in order, uniqueness and subset checks, and exact `7 + len(ROOT_CASES) + len(ROOT_ISSUER_CASES)` equality. |

The Training issue is a real gap in a static source protection. The synthetic
`Host::recover_original_custody()` insertion is not compiled and does not show
that an attacker acquired runtime authority. The actual API takes original
custody, configuration, dataset and cancellation, and binds recovered origin;
its independent closed caller boundary remains empty. This repair protects the
specific complete identifier and does not claim to forbid every possible
`recover_` prefix. Independent analysis is preserved in blobs
`edb5d3f56e224d95ab86f71ed0c2495aaa347993` and
`86b27d8511396f485f605f71d13ea97c926e1cec`.

## Preserved scope

The five changed paths are `CALLERS.toml`, the exact SHA256 allowlist, and the
Observer, Selection-readback and Root source-closure QA files. There are no Rust,
workflow, verifier or typed-helper changes. All **569 boundaries and 422 protected
rows** remain, with no caller or authority-field changes. The only protected-row
changes are the three additive complete identifiers. The allowlist keeps all old
bytes and adds only the new CALLERS SHA256.

Across the three changed QA files, all 25 test methods remain. Only the body of
the one Selection method changes; the Observer and Root changes are constants.
Removing the explicitly recorded additions and reversing the two Selection
marker migrations restores all three complete original files and ASTs exactly.
The complete-definition comparison, including helper methods, is recorded in
`REPAIR_REVIEW.json` and the independent peer report
`c108a5c9f20bf057c404e3f01416ba2e5b78dac7`.

## Actual scoped diagnostic

The four original failing methods, with their original class setup, were run
once locally against 32 exact required source files and the five candidate
overlays. All four methods passed: unittest reported **4 tests in 3.835 seconds**;
the wrapper elapsed 4.019 seconds, returned 0, and did not time out. Complete
before/after hashes of these 32 inputs are equal. The actual raw log is 1,035
bytes, SHA256 `eb1caa8c657d1e5fcb1021c0d9e9590abdc272c64ebb5f32457026b3e009c5d2`,
Git blob `067ccf85f126f04812d26d9daf16a09799231d1d`.

This is a **partial-source mechanism diagnostic**, not a full-source collector,
the full unittest gate, a full caller gate on repaired source, native Rust
qualification, or a real task chain. The complete gate entrypoints, their
600/300/4800-second budgets, and the original assertions are unchanged. The
original preparation manifest retains its preparation-time
`PREPARED_NOT_ACTIVATED_NOT_YET_TESTED` status; the later diagnostic has a separate
RESULT and raw log rather than rewriting that historical snapshot.

## Two packets, one source delta

`REPAIR_PACKET.json` preserves the original review-proposal schema.
`NONRUST_APPLY_PACKET.json` is a separately named derivation using the original
`hepta-reviewed-nonrust-source-apply-v1` application schema. Its clean
`source_identity`, complete base-inventory identity, physical tree and expected
leaf count are explicit. All five `changes` objects and every preimage,
postimage, mode and base64 string are JSON-equal between packets. No application
driver was weakened to accept the proposal schema.

The expected complete 15,188-file candidate tree is
`b7b357c07b5539769a068c6b9b009629f5612d1e`. It is a computed proposal tree, not an
activated or qualified source identity. Native-schema compatibility was also
independently reviewed in `3ab3a2f9b3423c1fdaf69a8e0f9fff85874ad3b3`.

For either packet, decode each listed ASCII base64 part separately, concatenate
decoded bytes in numbered order, verify the gzip bytes/SHA256/Git identity, then
gunzip and verify the original JSON bytes/SHA256/Git identity. Each encoded part
is below 500 KB. The full packet Git object is independently created and read
back as well; small parts provide the complete repository evidence reconstruction.

The initial derived parser draft used redundant FQN labels and is retained with
an `initial-fqn-labels` name. `RAW_FAILURE_INDEX.json` is the corrected derived
index. Neither parser version changes the original raw bytes or gate verdict.
