# Source-only GitHub recovery — strict ledger (2026-11-03)

## Delivery policy

Preserve **source, build/test scripts, source-selection scripts, reproducibility/provenance manifests and small necessary fixtures**. Do **not** require uploads of whole historical experimental ZIP/TARs, model weights, large event traces, AV/media collections, CAD meshes, generated PDFs, repeated logs, caches or binary checkpoints. Original archive identities remain recorded by SHA-256; any scientific validation that requires unavailable data is explicitly **not** certified by source recovery.

## Confirmed GitHub source preservation

| Workstream | Original source/manifest entries covered | Remote repository and branch | Evidence |
|---|---:|---|---|
| NBO 2026-10-28 reader + observation-source selection | 508 | `TrillionniumFoundation/NBO` / `recovery/dot-20261103-oct28-baseline` | Source-only tar Git blob `774310f0889a5b0814db27271da9e2a9192e65c7`, sidecar inventory, README; commit `d1db933e2bbf4ba99619656e852529e23e1845a9` |
| NBO R99 staged protocol + CI | 2 | `TrillionniumFoundation/NBO` / `recovery/r99-local-worktree-20261103` | 2-file remote diff; commit `0c91e6cd602d822778ceb9b8b650ef776b8d0146` |
| Hepta weight runtime worktree | 30 | `TrillionniumFoundation/hepta-runtime` / `recovery/weight-runtime-worktree-20261103` | 30 Git blobs in remote tree; commit `4b1605065e53ff70d7214f47e76124f735b435d6` |
| HCSN R2 | 185 | `TrillionniumFoundation/hepta-private-ci` / `recovery/library-unpushed-20261103` | Source-only Git blob `f65e5290f176add2c98c94ff1f06a419167c9d6c`, sidecar Git blob `e0d39e4578e2b7ee7406d192463bb01bd32a4b37` |
| HCSN Addressed | 121 | Same as HCSN R2 | Source Git blob `d5089e3de1e43aa97500f4f985ca3c4ea293d42e`, sidecar `3c0b01bdf894a5757349124cc8a14572b4682f16` |
| HCSN V9 | 33 | Same as HCSN R2 | Source Git blob `2308ad1d355091541253bb0e9cdaf1792caef326`, sidecar `77ff07c53970d48198853bf7b8437d39a1e3633d` |
| RAZR-SLIDE R12 | 133 | `TrillionniumFoundation/RAZR-SLIDE` / `recovery/library-unpushed-20261103` | Source Git blob `9e212f99ed178ddcc307a0fda400755de62b856e`, sidecar `824d9d043021dcf5195319d7d137fbe20bdf19a7` |
| NDU natural-joint part1/part2 | 41 | `TrillionniumFoundation/NDU` / `recovery/library-unpushed-20261103` | Source Git blob `e36c3d3089f67383ed40dc5fd412086c8767d708`, sidecar `fd956770f42b9a9b4adaef46f050821d7f2fa0dd` |
| REA 6.8.0 real-tool fixtures | 39 | `TrillionniumFoundation/hepta-runtime` / `recovery/rea-6-8-0-library-20261103` | Source Git blob `31711323e0268b198f33a6b308621c2b13f69e19`, sidecar `bb8532935005fc3b3fb602ce3feef37bae70b7c2` |
| NHO STOC R46 | 269 exact source/manifest matches | `TrillionniumFoundation/ICLR-2027` / `stoc2027-nho-r46` | Local original ZIP Git Blob SHA matched all 269 remote paths; branch `aaf09e0e87f2df63eb878ab9d40ce1977c5da959` |
| Deep Q-Operator STOC R39 | 141 exact matches | `TrillionniumFoundation/ICLR-2027` / `stoc2027-deepq-r39` | Local original ZIP Git Blob SHA matched all 141 remote paths; branch `35bd8dd50eb44aeb1b26fbd32e5c26042413f3f6` |
| theta second-queue GTF/SMS/FPA/OMD | 72 exact matches | `TrillionniumFoundation/theta-theory` / `revision/queue2-focused-2026-11-02` | Local original ZIP Git Blob SHA matched all 72 remote paths; branch `854cb256bfb7ea0f346cb89776626fc652823dc1` |

## Independent package checks

Across **seven local source-only bundles**, all **1,060** selected member SHA-256 checks passed, **488 Python modules** passed AST syntax parsing, and **81 JSON files** passed parsing; zero failures in these bounded checks. These are **file/member checks, not counts of distinct source files across all project histories**. The detailed machine-readable report is `source_only_bundle_validation_20261103.json`. Bundle builder scripts are included beside the Git recovery directories where staged.

## Remaining mandatory gates before deleting ChatGPT Library

- [ ] Finish a complete paginated audit of **all** Library files/folders, not just recent or first returned pages; identify every code/reproducibility artifact hidden in compound ZIP/TARs, and distinguish duplicates from unique revisions.
- [ ] Ensure every required non-duplicate source and reproducibility manifest is present on a reachable GitHub branch with the same Git blob SHA (or recorded exact match by file SHA-256). Do not conflate a reference manifest with actual code presence.
- [ ] Complete the desktop/other-host active worktree inventory, including older or detached Git revisions, and verify their commits and modifications are already preserved; exclude generated artifacts and empty/deleted checkouts. Recently inspected HIA/NDU and Chain HEADs already exist on remote, but that is **not** a complete workspace proof.
- [ ] Resolve provenance/identity ambiguity for any unmatched source archives; unresolved code sources are release HOLDs, not grounds to delete the original Library files.
- [ ] Confirm any Library-only files the user wants to keep outside GitHub are separately backed up or explicitly excluded from the deletion request; the instruction to clear Library is conditional on code and manifest coverage, not permission to guess that every file is expendable.

**Deletion status: HOLD. No Library file or folder should be deleted unless all above mandatory source-coverage gates are met and evidenced.**

Source-only Git delivery closure is distinct from scientific experimental reproducibility or production/adoption qualification. Missing raw data is not a Git upload blocker under the user's current scope, but remains an external replay prerequisite where scientifically relevant.
