# Generated Cargo and Bazel dependency graph

The final complete Cargo workspace now passes Rust 1.96 dependency resolution
and a second `--locked --offline` metadata check: 193 workspace members and
1,527 packages. Cargo generated the lock with SHA-256
`907aef79c029c035694df1b1242e6284f5f8244a1d8b88cbe25c918251fb49ed`.
The subsequent original Bazel update and check both passed and reproduced
the exact Bazel lock recorded below.

The original `just bazel-lock-update` completed successfully on the combined
Rust source with Bazel 9.3.0. The original `just bazel-lock-check` then completed
successfully and left every dependency input, including the generated lock,
unchanged. The complete generated `MODULE.bazel.lock` is 1,791,651 bytes with
SHA-256 `54b7e89cd40e0f6e524e7ba495fdde5a0c346bec94cb8c26afdd54fcc4402d77`.

## Exact source and commands

The independent native worktree used commit
`4c7d6453a0afbc9982ba733382d12d03a6a26347`, tree
`4cbcfadd9275928410cd2d78a07421883cbf3595`. It is the active source snapshot of
repository commit `ee793e80723fe27bc7024e853f7e1e2173fea275`, including the
combined HCSN, Learning and Memory Cargo graph and the `tokio/process` feature.
The existing native compiler worktree was left untouched.

| Command                  | Durable job            | Exit | Duration  |
| ------------------------ | ---------------------- | ---- | --------- |
| `just bazel-lock-update` | `1a1e04d4102-392-2a33` | 0    | 160.088 s |
| `just bazel-lock-check`  | `1a1e051306f-392-2a44` | 0    | 2.014 s   |

The successful update records 240 dependency inputs: Cargo manifests, the
complete Cargo lock, root Bazel configuration and the tracked `bazel/` files.
All 239 inputs other than the generated output matched repository commit
`f201405a428de6197a633862a30a1fd373886034` by SHA-256. The complete Cargo lock
remained `3b6f931b2e16d4f366195b5394741d0d56f700f1ab6d6a3643e438b9321a47a0`.

Bazel 9.3.0 was installed in the task's private tools directory from the
official release URL. Its SHA-256 matches the official checksum:
`d302d22ed77ee5658b87857249baa579db84300ecebe0a1e9a357b5b20f80eb8`.
The installation request, terminal status and original logs are included.

## Complete Cargo workspace follow-up

The initial Cargo lock was generated for the HCSN source before Memory was
merged. A subsequent complete workspace check found that it lacked the
existing `codex-hepta-ndu` manifest's new path dependency on
`codex-hepta-neuron`. The independent worktree ran the real Cargo resolver
against the complete combined workspace. The resulting 422,511-byte lock
changes only that package's dependency list; no package version, source or
other dependency changes. An independent Mac Cargo run produced the same
complete lock hash.

All four stages of job `1a1e0593df2-392-2a6b` completed successfully:

| Command                                                | Exit | Duration |
| ------------------------------------------------------ | ---- | -------- |
| `cargo metadata --format-version=1`                    | 0    | 15.262 s |
| `cargo metadata --locked --offline --format-version=1` | 0    | 1.283 s  |
| `just bazel-lock-update`                               | 0    | 4.338 s  |
| `just bazel-lock-check`                                | 0    | 0.459 s  |

The successful metadata commands include all workspace members and dependencies.
The generated Cargo lock was not edited by hand. The new Bazel output is
byte-identical to the earlier `54b7e89c...` output; its original update and
error-mode check were still rerun with the final Cargo input. All other
dependency input bytes remained unchanged. The complete follow-up commands,
source hashes, original logs, full Cargo lock and structural comparison are
included. The earlier receipts remain bound to their original `3b6f931b...`
Cargo input.

## Earlier attempts and retained warnings

The first attempt exited 37 because the native-only sparse checkout omitted
`bazel/modules/BUILD.bazel`. No dependency input changed. The next recovery
attempt exited before Bazel because the installed Git does not accept
`sparse-checkout add --no-cone`. The final recovery used the existing non-cone
configuration and restored `/bazel/` from the same commit. Its exact tree,
`c1619508a4a91e5f22ccf613485c9f7b1bec0717`, also matches the public baseline
and repository source binding. Both failed attempts remain in the evidence.

The successful commands retained Bazel's direct dependency version warnings
for `platforms`, `apple_support` and `rules_cc`, and its existing crate
annotation suggestions. No direct dependency check, checksum, gate or
annotation was disabled to obtain success.

## Result and qualification boundary

The generated JSON changes five nodes in the crate facts: `ctutils` moves from
0.4.6 to 0.4.8, `module-lattice` moves from 0.2.3 to 0.2.4, and the unused
`der` 0.8.3 fact is removed. Registry hashes and the module extension records
do not change. The full structural comparison and exact generated patch are
included. The lock was produced by Bazel; no lock content was assembled by
hand.

This evidence establishes dependency resolution and the original lock
freshness check for the declared source graph. Native compilation, test and
platform results have their own exact source receipts.

## Read the complete evidence

`MANIFEST.json` binds each original byte stream and each gzip container by
length and SHA-256. Containers use gzip timestamp zero. Decompress any file
to recover the exact original request, response, log, lock or patch; verify
the original hash from the manifest before using it. The logs are complete,
including failed attempts and warnings.
