# Matrix crypto migration evidence

The complete code candidate is d5a4f5b0f7794bbb93f3539032473ec3a7f2bb4c, based on the independently validated AWS backport 7b142f8478c711409e4a585a5c62c1ef0dff9ebb. Draft source stages are #5398, #5399, #5400 and #5401. This archive adds evidence only.

## Actual validation

| Scope | Result |
| --- | --- |
| Four-package default suite | 289 passed; two external phases ignored by default |
| Original SDK 0.18 producer | One selected test passed; two other tests filtered |
| SDK 0.19.1 / vodozemac 0.11.2 consumer | One selected test passed on a frozen fixture copy |
| Full-features locked metadata | Passed with 21 unrelated baseline edges retained |
| Required Bazel lock generation | Passed |
| Exact CI cargo-deny 0.19.0 | Exit 0; input hashes unchanged; policy unchanged |
| Scoped just fix | Exit 0; no files changed |
| Final official format | Only layout and import ordering changed |

The two external phase names were each executed explicitly in separate processes. Their results are reported separately from the 289 default-suite passes; no duplicated unique-test total is asserted.

The old producer retains the 0.18 product version graph and adds one separately audited test-only direct crypto dependency. Its lock is not described as byte-identical to the original. The original execution source, lock delta, failure attempts and frozen artifact are preserved.

The consumer reopened the existing encrypted account with the same human passphrase, physical store directory and production five-second startup limit. It decrypted old Olm Normal-ratchet and Megolm ciphertext from saved sessions. Identity, session, custom state and the listed outbox fields were compared. Inbox coverage proves old-event deduplication and cursor continuation, not a full inbox payload comparison.

Schema readback from independent inspection copies records crypto 17 to 19, state 15 to 16, event cache 14 to 18 and media 2 to 2. The event cache may be cleared upstream. No reverse migration or safe reopening by the old binary is claimed; rollback requires an independent consistent pre-upgrade backup. All stored accounts and tokens here are synthetic fixture data.

## Evidence identity and failures

SUMMARY.json identifies the final code, lock hashes, scoped results and canonical receipts. ARTIFACTS.json binds every retained raw artifact to both its original and stored bytes. Individual raw files are gzip-compressed; frozen fixture archives and official crate archives retain their original bytes.

The native wrapper for the successful four-package test and successful cargo-deny command later exited 1 because its report-extraction regex was malformed. That error is retained in the original native stdout, stderr, exit record and stdin. The receipt was reconstructed from hash-verified durable records without repeating either command. Earlier resolver, producer compilation and thread-bundle API compilation failures also remain.

The pre-minimization file named MATRIX_FINAL_GRAPH_REVIEW.json is historical and contains rejected Windows edge drift. The canonical final record is MATRIX_MINIMAL_GRAPH_VERIFIED.json: strict locked metadata resolves all 18 Windows edges plus bindgen/syn and two prost/itertools edges exactly as the baseline.

Runtime validation preceded the two reviewed comment/metadata corrections and layout-only formatting. Those differences and their before/after source hashes are retained. No tests ran after fix or formatting.

This dependency repair does not alter Control owner admission or scientific qualification. Research stages remain HOLD.

## Blob policy supplement

The original evidence commit fa28c0a22fe83519655cdbe528cc496fcf67828a failed the real blob-size check: 289 changed files were inspected and six exceeded 512,000 bytes. Archive paths have no exemption. The original command, stdout, stderr and native execution identity are retained under blob-policy; MANIFEST.json binds their bytes.

The follow-up adds six exact SHA-256 and repository-path pins for the immutable original audit log, resolver metadata and official Starlark archive. The default limit and policy implementation are unchanged. The original SUMMARY.json and ARTIFACTS.json describe the first evidence commit; blob-policy/MANIFEST.json is the separate failure-and-pin supplement. Final-head policy results are retained in the native job and the pull request description.
