# Original source-only and Windows terminal evidence

This continuation preserves original work against source `2ae5215beaf8d7b7df111a090b82134beae2683d`, tree `12159640adcf073b51f3837e75575e11f5c20233`. It changes no product source or acceptance gate.

## Source-only records

The first archive contains the original caller-scanner failure and the complete subsequent scan of a one-line dirty candidate. The original source failed on the unguarded test-helper declaration. Adding the helper's lexical `#[cfg(test)]` produced a complete scanner pass over 6,190 Rust files within the admitted deadline. The candidate was uncommitted; no native tests or model requests ran.

The second archive contains the four-path formatter execution and both failed verification drivers. `just fmt` completed successfully. The original driver then failed because `rg` was unavailable. Its separately identified continuation failed an incorrect assertion that expected three repository-wide references: the actual output contains three memory references and five independent Agentd counter references. Neither driver reached a complete caller scan. These failures are retained and are not replaced by the earlier one-line candidate's pass.

## Original interrupted Windows current CI

The original Windows current job ended cancelled under its existing workflow budget. Thirteen completed groups contain 124 distinct executed cases: 115 ordinary passes, eight failures, and one `LEAK`. All thirteen Nextest run IDs are distinct and retries are zero. The next group stopped during compilation and has no test execution summary. There is no source-after receipt. This is a partial original run, not full Windows qualification.

## Independent readback

The root fetched all three archives and both manifests in full from immutable staging commit `ce99fa1c550338462fc47519381ea39b29db9e03`. Complete byte lengths, SHA256 hashes, Git object IDs, all 94 safe regular archive members, and member manifests match. The original Windows ZIP's 20 members were independently checked for CRC and byte equality by the reviewed offline verifier. That verifier was replayed once; no archived driver, native test, actor, or model request was executed.

The complete audit is in `root-readback-v11/ROOT_READBACK_AUDIT.json`. Its replay script consumes the complete GitHub `fetch_file` base64 receipts named `READBACK_A.json`, `READBACK_B.json`, `READBACK_W.json`, `READBACK_M.json`, and `READBACK_WM.json`, obtained from the immutable staging paths under this directory. Extract the Windows archive into `extracted/W` before replay. The downloads are ordinary evidence files, not runtime inputs.

The proposed integrated repairs remain separate. Their native qualification has not occurred at this checkpoint. All original source-head failures, the original provider outcome `UNKNOWN`, and the scientific and original-owner acceptance boundaries remain unchanged.
