# Independent review of the d1d follow-up

This review compares the proposed CURRENT against the actual CURRENT blob in the previously verified d1d Git object store. It also reviews the small helper correction and `followup_blob_gate.py`. It does not execute a new blob gate, Cargo, native tests, model inference or training, and does not update any repository reference.

## CURRENT and source identity

E1, E2, E3, E4, Chain, the complete #6709 metrics integration and all ten qualification flags are unchanged by value. All ten flags remain false. Every previously existing nested history field is preserved, apart from the explicitly expected observation timestamps, previous-checkpoint pointers, previous CURRENT locator/hash and interpretation paragraph. The old CURRENT's exact bytes remain hash-bound; new E5/E6/CI observations are separate additions.

The new fields distinguish independent E6 d035 component success from its failed Root mechanism parent and unexecuted ordinary NoUpdate. They retain the next marker-only validation as incomplete at this snapshot. Neither new C/cold D, FinalUse nor settlement is claimed. The older d1d prospective merge f8aba45 runtime results are separately identified and are not evidence that the new helper has passed lint. Native6 accurately records actual formatting success, dependency-blocked just-fix and no executed Rust tests. The E5 v2 measurements distinguish fifteen byte/full-template input views from complete target coverage, SFT bounds and training admission; target-related values remain null and every full-representation/training flag remains false.

The actual helper bytes match e69d4ccd. Comparison with the d1d blob reproduces the exact new bytes using only the declared io::Result return, `?` propagation, direct tempdir result and six original test-call unwrap changes. No assertion or product guard change is included. An initially ambiguous Markdown E3 sentence was corrected before this final review: new SmolLM2 material is incomplete, while the original T2 history remains intact.

This is a consistency and history-preservation review, not an independent replay of every upstream CI or E6 claim. The reviewed file hashes and detailed comparison counts are in the companion JSON. A later change to those files requires a new identity check.

## Object-preparation controller

I did not find a material gate relaxation or false-success path in the reviewed controller. It pins the previous preparation script and actual passing result; imports exactly 158 retained objects by their Git OIDs, byte lengths and SHA256; checks d1d's exact tree; permits only a direct child of that commit; reconstructs the complete new tree from the changed-file manifest and requires equality with the actual Git commit API; and requires the full incremental Git difference to match that manifest. Additions/modifications are supported; deletions and type changes are refused.

The new head must still reference the original checker and allowlist Git blobs and SHA256 values. The invoked checker retains the 512000-byte limit and 120-second subprocess timeout. A passing status requires its actual exit zero and unchanged HEAD/config/index/packed-refs/refs in the new isolated bare repository. The previous controller, its object store and remote references are not mutated by this preparation. Missing objects, tree differences, parent differences or an unexpected changed-path set fail before a passing receipt can be produced.

This review establishes only that the reviewed preparation preserves the intended original gate. It does not claim the not-yet-supplied final successor has passed it, does not make the whole preparation a 120-second physical owner, and does not expand what a blob-size check proves about project correctness.
