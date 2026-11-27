# V7 original source-gate evidence

This package retains the complete original GitHub Actions ZIP, decoded full job log, API metadata, the runtime-bound offline verifier, its initial extraction rejection and corrected canonical-archive verification, and independent formatter review.

The original invocation is run 43042186271, job 130596614396, attempt 1, harness 3eadb20253ada96fc26cd1c129ba68c42a18a876. It tested pure source 63a4c2492848e9560750c32bebaacce2762bf2a2 / initial tree 7592d3546c460ba1a2f543167be27eeba973c2b7. The actual formatter produced tree 31fd2be8145d593bf8e470fa598597ab9b23e117.

The complete original ZIP is 7,028,444 bytes, SHA-256 91fd0f97c45766886b4082ab5f417338aa5d878681792079067b44c97dd44024. It contains 377 regular members. Its nested `mem8-source-gates-v7/mem8-source-gates-v7-records.tar.xz` contains all 375 original source records and their manifest. The upload's direct expanded layer excludes six `.github` source members because the original workflow sets `include-hidden-files: false`; these exact files remain in the original nested tar. No bytes are reconstructed from another source and no CI invocation was repeated.

To repeat the offline audit, safely unpack the original ZIP, verify its SHA and CRC, then unpack the nested tar into `records/` beside its original `ARCHIVE_INFO.json` and original tar file. Run the included `verify_source_records_v7.py` with that parent directory as its sole argument. The verifier reads evidence and writes only its verification report and format-only patch; it never runs repository code. The canonical successful execution and the initial direct-ZIP missing-file rejection are both retained here.

The original 600-second gate finished in 156.902353 seconds. All three complete Merkle trees were recomputed; 114 cumulative source paths and 14,053 complete final entries were verified. The retained 109 prior postimages are unchanged. Thirteen old case names have zero full-tree hits; all 18 exact Python regressions passed. The complete caller golden is equal except for its tree-derived Rust-file count of 6,204; its 160 boundaries and all other fields remain intact. Cargo.lock and MODULE.bazel.lock are unchanged. Four actual Rust formatting changes were independently reviewed and replayed.

This is source-only qualification. There is no native project test execution, provider call, original-owner restoration, or scored memory benefit in this packet. The original source HEAD/tree stayed unchanged while formatter changes were staged; this is not a clean final checkout claim. Source ref updates are outside this review.

Signed artifact download URLs, credentials, private owner state and raw provider context are not included. The decoded job log is kept byte-for-byte as returned by the GitHub log endpoint. All packaged members are listed in FILE_MANIFEST.json.
