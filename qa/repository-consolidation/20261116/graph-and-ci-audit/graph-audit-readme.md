# Repository graph and merge audit

This package records the complete branch inventory, graph classification and 32 reviewed ordinary merges through candidate 23a7b1bceda59d792762833920e0e16ed2b8ea5f, whose source tree is 751e50a0172e467176be68a1331519c8ea171307.

The initial remote snapshot contains 7,294 branch names and a closed graph of 76,776 commits. A later snapshot preserves the same names and records two independently advanced HIA refs. The augmented audit graph has 76,814 commits and 81,285 parent edges because its roots also include the unreferenced candidate. Actual root lists, source snapshots and their hashes are retained separately. The augmented graph does not claim that main or any remote ref was updated.

At this candidate, 1,727 original non-HIA branch tips are ancestors, 5,503 remain pending review or merge, 63 new HIA branch names are protected, and main remains a separate ref. This is complete graph inventory with explicit review status. It does not claim completed source review or successful CI for every remaining branch.

## Original observations and corrections

The archive preserves the original size-policy failure for six retained assets, the original evidence identities, the subsequent lossless part receipts, ordinary merge previews and conflict stages, server parent/tree readbacks, and the reverted malformed intermediate claimed-state patch. The earlier path classifier and its corrected version are both retained. The corrected classifier treats every path outside evidence/ and qualification/ as needing source or policy review and separately identifies executable files inside evidence folders.

The 32 reviewed ordinary merges preserve each incoming tip as an original parent. The archive distinguishes their exact trees, specific conflict resolutions, source invariants and pending candidates. The Windows aggregate preview and the 25 later compact Rust previews remain unresolved review records; they are not represented as admitted merges.

## Lossless archive format

The graph-audit-manifest.json file lists every original member and each ordered gzip volume. Each gzip file is at most 500,000 bytes. Decompress the volumes in manifest order and concatenate their uncompressed bytes to reconstruct graph-and-merge-audit.tar. The volumes are independent gzip streams; each uncompressed slice is a section of the one tar archive.

Before reading or extracting the archive, verify each compressed size and SHA-256, each uncompressed slice size, offset and SHA-256, and the complete tar size and SHA-256 from the manifest. Then verify each regular tar member against its listed size and SHA-256. The package was restored and verified against all original member identities during creation.

Restore the large uncompressed archive and member files only in a new directory outside the repository checkout. The compressed volumes and small manifest satisfy the existing blob-size policy. No source policy limit or broad spelling/format exemption is changed. The archive contains audit data; it does not execute or replay historical source, actors, workflows, evidence collectors or failed experiments.

The GitHub object receipt records immutable blob creation and byte readback only. Publishing a commit, moving a ref, completing required native checks and deleting branches are distinct operations controlled by the root task.
