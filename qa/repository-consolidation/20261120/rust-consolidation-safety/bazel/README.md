# Bazel library root qualification

The four source changes are inherited unchanged from commit `4a5de714ce95889fca83abd3da33cbd74aaac748`, tree `f289a1e9c1112d6afae4d9423e7f18c0c7be128a`.

Read [final-qualification.json](final-qualification.json) for the final outcome. Eight explicitly listed Linux CI test targets passed on an identical complete source tree. The overall Linux and SDK jobs failed elsewhere. Five Windows-cross targets were skipped and are not counted as passing. Native provider queries passed before and after the change; both native library build attempts were cancelled and incomplete.

[ci-source-qualification.json](ci-source-qualification.json) preserves the earlier observation, made before the second owned native build was cancelled. [native-build-v2-terminal.json](native-build-v2-terminal.json) and the final qualification record establish its terminal cancelled state. Neither native build is a compilation PASS.

[ci-tree-objects.json](ci-tree-objects.json) and [ci-source-bindings.json](ci-source-bindings.json) preserve the checkout and Git tree proof. [four-file-source-record.json](four-file-source-record.json) preserves exact before/after source bytes and hashes. [root-query-and-census-proof.json](root-query-and-census-proof.json) records the 200-member Cargo workspace and the native CrateInfo queries.

## Complete logs

All ten complete log streams are stored as deterministic gzip files under [publication-logs/](publication-logs/). [publication-logs/index.json](publication-logs/index.json) records their original native paths, raw and compressed byte sizes, SHA256 values, Git blob identities, and successful byte-for-byte decompression and repeated-compression checks.

For each index entry, the published file is `publication-logs/` followed by the basename of its `gzip.path`. Standard gzip decompression reconstructs the exact raw bytes. Native paths in the evidence are provenance, not repository-relative links. Raw logs were retained unchanged; compression preserves their original whitespace.

The 8 Linux target PASS results qualify only the corrected crate roots and listed targets. They do not qualify the entire Rust branch union, whole CI, or branch retirement.
