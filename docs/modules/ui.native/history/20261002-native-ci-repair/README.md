# Native CI repair and evidence boundary

Published repair source: `d07b6de08d6f3bcab1b7367f695be8b439ddb732`, tree
`848365cf8a3ed6781c4942805044c550e6b842a7`. Exact qualification base:
`978c1923eda66373e9dce4fe0efa890bc60ac404`. The source object is verified against
the complete local code-commit tree before updating these navigation anchors.

## Historical hosted failure

[Run 36971395569, attempt 1](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/36971395569)
completed **failure** for candidate `2e0b6557e41f3d71f58ead867ef753120337a6dd`,
with frozen implementation `2b59c1c5f877432a557185efd77331ae1143ae42`. Identity, Linux storage and both macOS
subjects passed. Both Linux subjects failed application tests; both Windows
subjects failed formatting. The aggregate failed closed. See
[the exact job/artifact record](historical-run.json).

Linux daemon stderr reports: “Failed to get AppArmor confinement information of
socket peer: Protocol not available.” Its anonymous TCP fixture cannot supply
the peer labels required by the runner's mediation. The repair uses a private
Unix session bus and EXTERNAL authentication. It does not disable AppArmor,
change product authentication, skip CI tests or weaken protocol assertions.

Windows reported “The filename or extension is too long. (os error 206)” in
`app_format`, before Clippy. The new formatter reconstructs the same complete
Cargo target/edition set, then invokes check-only rustfmt in bounded batches.
The original and new inventories match exactly: 443 targets; three local batches.
Regression tests cover dependency-workspace cycles, target/edition retention,
Windows quoting/UTF-16 bounds, overlong-target rejection and failure propagation.

## Local diagnostics and limits

[The diagnostic binding](diagnostic-binding.json) includes byte counts and hashes
for every entry in [the retained logs](retained-logs.zip). Tests ran before final
mechanical formatting; this is not execution of a final hosted candidate.

- 160 native library tests passed. Four D-Bus runtime tests were excluded only
  from this local invocation because AF_UNIX creation is denied, including under
  authorized escalated execution. Four existing ignored tests remained ignored.
  Both modified D-Bus fixtures compiled; their runtime outcome awaits Linux CI.
- Strict native Clippy with warnings denied passed. Test/dev debug symbols were
  disabled for disk-bounded local validation; no storage performance claim is made.
- Five formatting regressions, 16 workflow tests and 10 native-platform guards passed.
- `just fmt` succeeded using writable caches after the initial default-cache
  failure. Its 54 unrelated baseline formatting changes were restored. The final
  complete batched formatting check and both new Python file format checks passed.
- An initial compile-only invocation was rejected by nextest's incompatible flags;
  the normal scoped test command then compiled and executed successfully.

[The frozen inventory](implementation-inventory.json) contains 455 exact Git
blobs across 33 selection paths, digest `2ecc6b41c827d247c241a92d562b7964d2231bc372a607083d224938e2ef47d6`. The previous
current inventory and local diagnostic object are preserved unchanged in history.
Only the storage budget source anchors move; every compiled budget limit remains.

Fresh six-platform head/ordered-merge execution, release storage, unsigned package,
installed lifecycle and strict same-run aggregation remain required. Physical OS,
accessibility, signing and independent acceptance remain open. Production,
deployment and release flags remain false; older successful subjects are not reused.

## Metadata-only validation

[Metadata checks](metadata-checks.json) passed 267 native Python cases with one
Windows-only NTFS skip, seven projection tests, four module-registry tests, the
native v6 map adapter and the structural source guard. Projection regeneration
was reproducible and produced no changes. Historical nested records and all
storage-budget semantics were compared with the source commit and preserved
exactly. These checks observed an uncommitted metadata continuation on the
published repair source; they are not final hosted-candidate qualification.
