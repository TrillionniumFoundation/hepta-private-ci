# CI and source audit follow-up

Captured at 2026-11-16T15:00:36.018711+00:00. The source tested here is tree `c2edb469712d59a01005c97be0009db02d7762b7`. The checkout retained head `a70540b51842034678171fc2278e7b3ecfcf022d` with the recorded 162-file storage overlay. The root agent reports the same complete tree for format commit `5fed9dcb99feb6c3037e61eec0cc91c0db22dae2` and ordinary merge tip `ca414120a713eaa0ecb9d5a75c21b9edf5c922fe`.

## Results

| Check                                      | Result                       | Exact scope                                                                                              |
| ------------------------------------------ | ---------------------------- | -------------------------------------------------------------------------------------------------------- |
| Original complete B4 suite                 | PASS                         | 1,331 tests: all original 1,315 plus 16 storage tests; 956.743 seconds                                   |
| Original caller CLI                        | PASS                         | 1,645 boundaries, 1,645 privileged inventory entries, 819 protected files, 7,507 Rust files              |
| Input stability                            | PASS                         | All 14,349 recorded source inputs unchanged before and after both source gates                           |
| Original blob-size gate                    | PASS after preserved failure | 1,376 changed files from baseline285 to the candidate tree; original 512,000-byte limit and allowlist    |
| Storage overlay formatting                 | PASS                         | Original `just fmt --check` on the 162 staged overlay paths                                              |
| CLI and test-client complete package tests | PASS                         | 666/666 tests, zero skipped; both complete packages, original test recipe, four threads and zero retries |
| Agentd native v7 original selection        | FAIL                         | 26 selected: 10 passed, 16 timed out, 1,584 filtered                                                     |
| Whole-tree formatter and Codespell         | PENDING                      | A separate complete checkout is being materialized; no sparse scan is described as a full scan           |

The caller CLI ran unchanged, without a parallel replacement or retries, and returned `PASS_HEPTA_CALLER_CLOSED_SET` after 1,830.188 seconds. Its complete proof is retained in the compressed evidence. The B4 and caller invocations, source inventory, original logs, and receipts all bind the same candidate tree.

## Lossless manifest storage

The inherited `CALLERS.toml` was 2,990,722 bytes. Removing optional TOML whitespace could not bring the same parsed object below the original blob limit: decoded string values alone occupied 2,341,711 bytes. The original size-gate failure is retained unchanged.

The replacement consists of a 571-byte index and a 452,429-byte gzip part under the existing protected `scripts` prefix. Unpacking yields the exact original SHA256 `e85c1782b94bd6cf1dd0ff3c10490eacc674b6148530ad9741e027e48d56477f`. The full parsed object, row order, 1,645 boundaries and 819 protected-file rows are preserved. The actual unpack and pack commands reproduced both source files exactly and refused existing output paths without overwriting them.

The loader bounds file reads and decompression, binds every part to fixed ordered local paths, hashes and lengths, and rejects missing or extra parts, duplicate or reordered paths, path traversal, static symbolic links, truncation, extra gzip members, trailing data, incorrect hashes or counts, and invalid schema. Native small TOML test fixtures remain supported.

The 154 B4 reader migrations contain 165 replaced read expressions. Recorded AST comparisons show that all remaining code, assertions, guard strings and original test names are identical, apart from removing unused `tomllib` imports. All 21 other verifier definitions and the existing schema and authority rules remain unchanged. Historical source capsules retain their fixed original byte readers. The storage directory remains covered by the existing engineering protection policy. Only canonical part names receive the original manifest CI scope; unexpected code under that directory retains full repository checks.

## Native v7 remains a blocker

The original Agentd command selected 26 tests with the existing 8 MiB stack, 60-second timeout, four threads and zero retries. It exited 100. All 7,749 recorded native inputs and controls remained unchanged.

All eight control tests passed. The previously failing deep read-only test passed in 35.460 seconds. One layout diagnostic also passed. Sixteen tests reached their original deadlines: three provider cases, three model-material cases, three evaluation-host cases, four training-operation cases and three panel cases. The timeout output does not establish one common stalled frame. The earlier v4, v5 and v6 failures remain part of the preserved history.

A separate single-provider debugger run finished with child exit zero. Its reported 20.805 seconds include about 1.202 seconds of debugger pauses. That diagnostic does not replace the failed original four-thread selection.

## Security change verification

The independent source review covers complete API-key masking and the diagnosed login diagnostic sinks, including the broadcast `account/login/completed` notification reaching `stream_turn`. The diagnostic copy does not replace protocol values. Request identity matching, queued notifications, failure branches, and required browser/device instructions are preserved. Matching login errors now retain bounded status information while omitting unbounded upstream error text.

ROG executed the original scoped formatting and Clippy fix commands without changing candidate inputs. Focused CLI tests passed 6/6, focused client tests passed 5/5, complete library tests passed 26/26, and complete package tests passed 666/666 with zero skipped. Every stage verified 7,751 native inputs plus 18 source/control inputs. The full package command was:

```text
just test --locked -p codex-cli -p codex-app-server-test-client --test-threads 4 --retries 0
```

The raw archive retains the earlier environment setup failure and its resolution, as well as all final invocations, logs, receipts and input bindings. The earlier independent source review recorded native tests as pending at its own capture; the completed native receipts in this follow-up supersede that execution status.

## Scope of publication

These results establish the stated source gates and the two tested Rust packages. They do not establish whole-repository native qualification. The sixteen Agentd timeouts, four original Windows admission cases, exact published-head hosted CI and CodeQL checks, and pending complete-tree static checks remain unresolved. No alert was dismissed by this audit, and this pack does not authorize main advancement or branch deletion.

Every evidence item is preserved as exact original bytes. Gzip uses a fixed timestamp and empty filename. Where an item requires multiple parts, concatenate the decompressed parts in manifest order, then verify the original length and SHA256 recorded in `ci-follow-up-manifest.json`. The existing security proof archive is copied byte-for-byte.
