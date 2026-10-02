# Windows registrar diagnostics and evidence boundary

Published diagnostic source: `bdedf9e7cd3ddb0bb6457704940910cadb4cef1a`, tree
`645f0284b37f58f5efff49f4edb459f6876a486e`. Its full tree matches local source commit
`04510d857e54191adb87a36af55e9c5b25a91053`. Exact qualification base remains
`978c1923eda66373e9dce4fe0efa890bc60ac404`.

[Run 36979217316](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/36979217316)
ran candidate `a21960e9fe2f2a9dc8cc465d2936098b0a86a307`, with frozen implementation
`d07b6de08d6f3bcab1b7367f695be8b439ddb732`. Linux head/merge, macOS head/merge and storage passed for that
old candidate. Windows formatting and lint passed; three registrar fixture tests
failed at registration with `E_FAIL (0x80004005)`, before their negative-control
assertions. The exact failing COM operation or synthetic comparison was lost.
The [diagnostic binding](diagnostic-binding.json) and [retained logs](retained-logs.zip)
preserve the Windows-head source, formatting, lint and test records byte-for-byte.
The [completed job snapshot](historical-run-jobs.json) records both Windows
subjects and the aggregate as failed; successful prior subjects are historical.

Current source labels COM operations and persisted identity/target mismatches
while preserving HRESULT and excluding path/identity values. It deliberately
makes no semantic repair: exact target and identity checks, Unicode handling,
reparse-point rejection and every existing fixture remain in place. The new
regression checks that a large sensitive-looking source error cannot enter the
bounded diagnostic. It is cross-compiled, not locally executed on Windows.

- Strict `x86_64-pc-windows-gnu` Clippy for `hepta-native-platform --all-targets`
  passed with warnings denied and dev debug symbols disabled.
- Complete native formatting passed for 443 Cargo targets in three batches.
- Required `just fmt` was attempted; unrelated Bazel/Python formatters could not
  write default caches on the read-only home. No unrelated source files changed.
- Windows runtime and exact new-candidate qualification are pending.

[Frozen inventory](implementation-inventory.json): 455 exact Git blobs over
33 selection paths; digest `16892416cf63bf5102d1f401dd54d2f1b409ef9a149a835f5be99f56c76bc767`. Seven current anchors point to
this source. Previous inventories, diagnostics and all compiled storage budget
semantics are preserved. Production, deployment and release flags stay false.

## Metadata validation

[Local metadata checks](metadata-checks.json) passed 267 native Python cases with
one Windows-only NTFS skip, seven projection tests, four registry tests, the
native v6 map adapter and the structural source guard. Projection verification
made no generated-file changes. Historical records and storage-budget semantics
were compared with the published source and preserved exactly. These checks
observed the uncommitted metadata continuation and do not qualify a hosted head.
