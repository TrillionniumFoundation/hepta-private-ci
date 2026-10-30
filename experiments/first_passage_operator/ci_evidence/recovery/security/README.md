# Fresh security graph verification after environment recovery

This evidence was produced in the restored 2026-10-30 workspace. It does not reuse runtime verdicts from the lost workspace.

- `audit-01.json` records the exact original cargo-deny 0.19.0 command and its successful exit. Advisories, bans, licenses, and sources all passed. The repository policy hash is unchanged. Existing nonblocking duplicate/yanked/license/source warnings are counted in `INDEX.json`; they were not hidden or converted into exceptions.
- `metadata-receipt.json` records successful all-feature `--locked` dependency resolution with an unchanged root lock.
- `BASELINE_RETENTION.json` and the complete resolver archive record why the previous shared versions conflict with the new Matrix, Ruma, and crypto requirements. Tokio was narrowed to 1.53.3. `LOCK_DELTA.json` compares the frozen input and output graph, and `before-Cargo.lock` preserves the input.
- `zip-feature-contract.json` verifies actual Cargo graphs for the explicit BZIP2 C backend and the independent upstream-default Rust backend control. All ZIP formats remain enabled. This graph check is separate from actual archive extraction tests.
- Original failing audit evidence and its remote source provenance are retained separately from the fresh passing audit.

Native consumer tests, native Windows tests, full CI, and standalone vendor compatibility tests are separate gates. A dependency audit pass does not claim those tests passed.

## Reconstructing archived logs

For an entry in `INDEX.json` under `archives`, concatenate its `parts` in the listed order and decompress the resulting gzip bytes. The index records every part hash, the combined gzip hash, and the original uncompressed hash and byte count. Every round trip was independently checked before recording the index. Each stored part is at most 400,000 bytes.
