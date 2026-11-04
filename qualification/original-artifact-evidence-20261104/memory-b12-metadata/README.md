# Exact original Memory metadata transport failure

The unchanged source b12f9b216d91bb760582a9df0d569f7e051a1016 failed `cargo metadata --all-features --format-version 1` while downloading the crates.io typewit index entry: curl HTTP/2 framing error [16]. The committed Bazel lock check and both original formatter commands had passed. Native and Bazel product qualification did not run.

Read-only verifier 6f837273982b8295f3a48a5582763b48d1351117 / run 41757623872 / job 126337368713 independently checked original artifact 13288493715, its complete ZIP digest/CRC, all 9203 exact Git inputs, before/after equality, and all original command/output hashes. VERIFIED_COMPACT.json is the log-emitted compact report; its verified_report_sha256 names the separate complete report, not this compact JSON file. The 2267-byte original metadata log here was reconstructed from the read-only log export and independently matched to the original recorded SHA256 before this commit.

The unrelated reader review is attached as exact existing blob a6149564f9268a3ca0f9746dbf1e1f70449c6355. It is static review, not native product qualification. The original 13 reader controls subsequently passed in the failed generation job. After the concrete transport cause was established, only that failed job was retried through GitHub's native rerun endpoint, with the exact same product source and commands. This evidence does not imply that the retry or downstream gates have passed.

All original artifacts and negative results remain retained. Product refs are not moved by this evidence checkpoint.
