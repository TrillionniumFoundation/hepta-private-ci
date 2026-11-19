# Joint RMCP and SQLite candidate

## Purpose and scope

The joint E1–E6 source still resolved the older RMCP and SQLite graphs identified by the dependency audit. Their individual upgrade proposals had separate qualification runs. This candidate combines those exact reviewed changes on the actual joint baseline and generates one Cargo/Bazel graph. It also carries the two narrowly scoped Mac fixture corrections and the already verified Fence action pin. It does not inherit a business pass from the earlier proposal runs.

The baseline is `be0e66c975433446a25e3e613294a2c64e9926f9`. [SOURCE_INPUTS.json](SOURCE_INPUTS.json) binds all 75 changed source files by Git blob, SHA256, size and import source. The 75-file list covers runtime, dependency and workflow inputs. The separate exact archive pin and qualification records are described below; other runtime source remains the baseline bytes. The dependency import stage is `8018be4e7f0029109a7576f1c409fb626b80ab8d`; the following stage adds the four authored Rust adaptations. These review stages preserve the upstream vendor bytes while allowing the repository formatter to process the authored changes.

| Component | Exact reviewed source | What is retained |
| --- | --- | --- |
| RMCP | #6676, `d496f05efcea465ada7f43e8cd3ee2e200944e10` | RMCP 3.9.0, typed discovery-error handling, issuer/source/URL rejection and no-contact assertions |
| Final OAuth test formatting | #6676 latest `bdd8dea7d5c9d69040e5e037f2f269c727263cf2` | Our actual `just fmt` postimage equals its exact blob `ee24fe4bb6e7a16daf527fbac2cabd2c678f6b4d` |
| SQLite | #6677, `af59210d1e66268bd45cd5643b96bfa5610e39e4` | One libsqlite3-sys 0.40.0 link, rusqlite 0.43.0, SQLx upstream source bytes with only the declared sys version-bound backport, and the existing Matrix manifest adjustment |
| Mac fixture paths | #6708, `9aaac03f5f6bcad3ff14ffe2ecfb11aa4299f16f` | Canonical temporary directory/reopen paths in two test files; production NOFOLLOW admission and all original assertions remain |
| Fence | #6713, `88f2e59b86ad42520a8b183043c1d83e937738b9` | One existing workflow action pin to v0.13.1; audit, permissions, checker and global blob limit remain unchanged |

Patches are imported by exact blob identity, not by merging unrelated branch claims. This source does not alter native owner authority, Windows admission, task contracts, model outputs, prior source freezes or the E2 NoUpdate decision.

## Actual lock generation

The first original `just bazel-lock-update` failed because the inherited repository-content cache contained partial external trees without BUILD files. Its original logs are retained. No shared cache entry was removed or rewritten. A second attempt used a separate output root, repository cache, repository-content cache and disk cache.

On the combined source, the actual commands then completed:

| Command | Exit | Waited wall seconds |
| --- | ---: | ---: |
| `just bazel-lock-update` | 0 | 122.248449 |
| `just bazel-lock-check` | 0 | 1.168680 |
| Locked Cargo metadata, complete graph | 0 | 53.500337 |

The resolved graph has exactly one SQLite link, libsqlite3-sys 0.40.0, with bundled features and no sqlcipher feature. RMCP resolves to 3.9.0. Bindgen 0.73.2 resolves its actual syn edge to 2.0.119.

| Committed file | SHA256 |
| --- | --- |
| `codex-rs/Cargo.toml` | `68ca181620e3d21c7751ea7865dde86f7dc190c3ae75f3a505fd9368996be2d9` |
| `codex-rs/Cargo.lock` | `dab5a95131e1b9c9b75144f6309d3a5686c2b82a5aee6a830d31bbeebfc8faf7` |
| `MODULE.bazel.lock` | `d240b972292c4101a01eceb1281dd15cdc43c77979711281bcaa5d0c680580c1` |

The generated postimages are committed together. Any later CI-generated lock drift is a new candidate input, and must be reviewed and bound before a whole-candidate pass is claimed.

## Formatting and retained scope failure

The actual repository `just fmt --base 8018be4e…` completed with exit 0. The four authored Rust changes pass a scoped diff check. The formatter changed one OAuth assertion layout, and that resulting file exactly matches the latest hosted formatting commit in #6676.

The full baseline-to-candidate `git diff --check` returned exit 2 for three existing upstream documentation trailing spaces in SQLx `src/connection/deserialize.rs`. Those exact imported upstream bytes remain intact. Both the full-scope failure and authored-scope success are retained. This report does not turn the full-scope warning into a pass.

## Fresh chrono audit: still blocked

The original scanners from #6624 at `cb9c97166d8c882594287712ee606cd6e2ddb2e2` were reused unchanged against this new Cargo lock.

The actual graph contains **1,523 packages and 193 source-less roots**. **121 roots still reach chrono 0.4.45**, comprising 28 direct roots and 93 indirect-only roots. Direct importers comprise 28 local crates, seven registry crates and one vendored crate. The required-zero check returns exit 2. The previous proposal's package count is not reused.

[chrono/chrono-joint.json](chrono/chrono-joint.json) and [chrono/chrono-joint-reachability.json](chrono/chrono-joint-reachability.json) include the actual lock hash and reachability witnesses. RUSTSEC-2026-0543 is not ignored, and chrono retirement is not closed. No deny policy exception is added. Windows' previously observed production admission failure also remains unresolved by this source.

## Original evidence and prospective qualification

[PREFLIGHT_ORIGINALS.tar.xz](PREFLIGHT_ORIGINALS.tar.xz) retains 95 original files plus its index, including all before/after locks, the 8.4 MB complete Cargo metadata, current graph scans, cache failure, formatter failure/success, original runtime exits and source-import records. Every member was reopened and byte-compared before upload.

- Archive: 787,256 bytes; SHA256 `5bf67c7fb0b67459ad0b0be7ffd7146ed8829dda07a6acda1932ab3bef701c7b`.
- Original index: SHA256 `8524bf349e686bd778e0067e1523a3370a69031eb0065a37a11af861074d1593`.
- Source-input index: SHA256 `f1c71df70e214b4bad123bfb84d9fd8e5cbf2420b53e16d9e62edb22393bf162`.

The existing exact-path/SHA256 blob-policy mechanism admits only this retained archive. The 512000-byte default limit and original checker/tests remain unchanged.

The imported RMCP and SQLite qualification workflows each check out the exact new PR head. Their original scopes compile real product consumers and run MCP, SQLx and Matrix package tests, with source-bound artifacts and test-result caching disabled. Those new runs must be inspected separately; earlier proposal counts are historical context only. The two Mac fixture files require actual Mac validation and do not gain it from Linux compilation.

The 112-call E4 run remains bound to source `18de3463…` and its original archive in #6714. No model call, training step, native adoption, full cost closure or learning gain is claimed for this new dependency source.


The frozen-source re-materialization and original blob policy also passed: all 75 input hashes were checked in a clean independent worktree at `2b3642214ba5ff4aaac27de13322a354a69507e7`, followed by all seven original policy tests and the original changed-blob check against actual PR base `80cb4dc2…`. The exact freeze, commands and original outputs are retained under `candidate-gates/`. The following publication commit adds only these records and this clarification; runtime/dependency/workflow bytes remain that frozen source.
