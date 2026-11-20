# Round 6: protocol normalizer borrow and actual Round 5 CI evidence

## Source change

The source commit is `7123198849d8967ac670975c1704926e00b72e69`, with sole parent `3bc225d0c1b2aaa1dc3fa77fb0bcbcfe5c55a37f` and tree `40b8ecb6202d5cccef107fe37f0dd14ca1f40ed1`.

Exactly one source byte changes in `codex-rs/exec-server-protocol/src/protocol.rs`, at original byte offset 8441, line 194, column 27:

```diff
-                .and_then(&normalize_temp_path)
+                .and_then(normalize_temp_path)
```

Before: Git blob `a0b3b4e2444869de7ee8735f4c87b53fbe7f0d79`, 50,039 bytes, SHA256 `0c9c204017938b99afdc51b6f5d4fe2ccc4705a8c3e57cf9cdb28bbd4f87c557`.

After: Git blob `56187ab174ec9998b3a0a4b74f06e734d3b111fb`, 50,038 bytes, SHA256 `7cfe90dd8836f5e95a6fe727722a9ef20dfe5e7edeeade63cf15f9e4b32bd681`.

This is the exact compiler suggestion from the actual Architecture source job `136170743872`. The normalizer captures `cwd` through an immutable shared borrow. Passing its copyable closure value to `Option::and_then` preserves the loop's use of the closure and its later call. The owned `path` argument belongs to each invocation and is distinct from the captured `cwd`. Environment-variable ordering, filtering, Unix relative-path fallback, deduplication, URI output and capability fields are unchanged.

Root and an independent peer verified the complete before/after file and inverse transformation. All other file bytes, all 35 original assertion macros, the complete test module and its 13 test markers remain unchanged. Four recorded forward/check/inverse text-patch operations actually exited zero; these operations are not Rust tests.

The complete source tree contains 59,326 leaves. The other 59,325 mode/type/OID entries, including all 5,361 existing QA leaves, remain unchanged. GitHub's actual parent-to-source comparison reports one commit ahead, zero behind and exactly this one changed file. This is a normal single-parent source commit, with no new historical branch coverage.

## Qualification boundaries

**The new protocol source has not yet received native, Rustfmt, Clippy or required-CI after-qualification in this evidence package.** The observations below belong to the previous published `3bc225d0` source/tree `54f55621e909c528acc8619c7d3140e31197fbde`; they do not qualify `71231988` or the later QA commit.

| Observed check on `3bc225d0` | Actual result and scope |
| --- | --- |
| Source formatting, Codespell, Rust formatting and Rust subworkflow required | Completed successfully in their recorded API steps. Old-head test counts are not assigned to this head. The Rust aggregate is not overall CI or Bellman required. |
| Architecture source `136170743872`, run `44701505514` | Failed strict Neuron all-target Clippy when the protocol dependency emitted `needless_borrows_for_generic_args`. The earlier legacy-Tick integration case and 17 selected runtime cases passed; 368 runtime cases were filtered out. Later native groups and the final whole-job unchanged-source check were not executed. Required `136179391545` failed. |
| Bellman exact source `136171750703`, run `44701505623` | Failed with 5 primary compiler/lint diagnostic occurrences. This includes a rustc dead-code diagnostic, so the complete set is not Clippy-specific. |
| Bellman deterministic merge `136171750596` | Failed with 96 primary diagnostic occurrences: 15 example-compilation and 81 lib-test-compilation occurrences. Production/shared/support files are among the reported paths; lib-test compilation does not prove a file is test-only. Required `136184614148` failed. |
| GNU Bazel job `136171750535` | Compilation completed and actual tests failed: 3 targets, 8 distinct cases. The main target summary has 465 passed (463 cached, 2 executed), 3 failed and 207 skipped. Seven later explicit uncached targets passed in separate commands. Target counts are not individual Rust-case counts and are not added into a fresh full-workspace pass. |

Bellman retains all 101 original diagnostic occurrences. Grouping by `(path, line, lint, message)` produces 99 groups; retaining column produces 101 locations. The two differences are the separate column-30 and column-49 `unwrap()` occurrences on each of lines 296 and 412 in `authority_host_peer_qualification.rs`. The 52 affected paths are diagnosis inputs, not an approved edit list. Neither Bellman lane reports the previous shadow-helper diagnostic, but its absence is not a complete successful Clippy result.

The exact-source lane starts from `3bc225d0`. The deterministic merge lane normally merges onto `0cee57ca617e0324e2df8e9447a2c075a6c76952`, records canonical object `16adb7d3ccc8bb2c3a71a1b4a17abb40a0c0cd00`, and checks the merged worktree initially bound to tree `54f55621`. It does not separately check out that object. GNU Bazel checks out actual PR synthetic `c198d6a2db92a85fcaceb356dc47cd68dea1fab5`, whose tree is also `54f55621`. Initial tree equality does not establish an unexecuted final unchanged-source gate.

The GNU failures remain separate from the lint failures. Two intelligence cases fail refusal/digest expectations. Two evidence and four agentd cases encounter checkpoint-parent safety requirements. The included read-only fixture review finds that the selected fixtures do not explicitly establish the existing private-parent permission prerequisite. The logs do not provide the actual directory mode, UID or process umask. Production permission checks have not been relaxed, and no checkpoint-fixture candidate is part of this source commit. The separate line-location addendum corrects one prose label without changing the frozen source evidence.

## Original-owner coordination and protected scope

The original integration owner retains its native qualification, current private `eced153251f815e9d6c3197ee4e392397862de8c` source and sole main/integration publication responsibility. All 53 relevant leaf entries (the 52 Bellman diagnostic paths plus protocol) have the same mode/type/OID in the independently bound `3bc225d0` and `eced1532` trees. This metadata equality does not transfer tests between complete commits and does not assign the other 52 source paths to this repair.

The rejected C2D stale-history/exclusive-lease production repair remains an absolute STOP. Its draft is not applied, compiled, replayed, delegated or included as source here. A precise denial-path-set intersection is `NOT_EVALUATED`, because this external reviewer does not possess a confirmed complete denied-path set. The separate unresolved native-copy key is not queried or replayed. Private automation prompts and signed transport URLs are excluded from the publication selection.

The last reviewed Round 5 protection snapshot contains 500 protected branch names, 533 historical/current pins and 1,409 descendant nodes. It is a historical input, not the fresh lease for this publication. A fresh complete reference map and monotonic union of the original owner's protection records are required before updating the owned fix ref. This package does not authorize any main update or branch deletion, and it does not claim that the requested whole-repository consolidation is complete.

## Git-object and evidence limitations

The local source construction uses a partial historical object store. Its original before-blob read and strict `write-tree` each returned 128; both original failures are retained. The exact official before blob was then imported into the owned store, while a different existing `environment_config.rs` blob remained unavailable locally. Metadata-only tree construction, complete leaf/Merkle verification and the actual `git diff --check` succeeded. No complete native checkout or local Rust execution is claimed.

The source request message ends with one LF. GitHub's JSON message readback omits exactly that terminal LF; `readback.message + "\n"` equals the frozen requested message. The source commit was created once, and its parent/tree/blob identities and actual one-file comparison were verified. The original failed direct-message-equality assertion is retained, with no claim about byte identity of the raw stored commit message. Frozen plans and source files were not altered to conceal this representation difference.

The root metadata-review attempt also retained its initial label-classification assertion: it recognized strict `write-tree` 128 but initially omitted the already-recorded missing-before-blob read from the expected nonzero-command set. The corrected record preserves both actual failures; it does not reclassify them as native test results.

The two approximately 1.9 MB source-construction leaf inventories are retained at their original sealed locations and identified in the explicit exclusion record instead of being copied again here. The original seal remains intact. The complete source file, forward/inverse patch, actual GitHub commit/tree/compare receipts and root/peer preservation records provide the published one-file evidence. A full Git clone can independently retrieve the two complete trees and compare their leaves.

## Evidence format and verification

The package contains **2 evidence groups, 146 exact archive members and 16,961,256 uncompressed member bytes**, stored in **13 independently gzipped fragments**. The main group has 141 members; the API-status addendum has 5. Its blocking-job original is reused by exact identity from the main group. These are storage/provenance counts, not test counts.

Each group is a deterministic tar/gzip stream divided into sequential 196,608-byte fragments. Each fragment is independently gzipped in the repository. `evidence-index.json` and each group's `members.json` record byte length, SHA256 and Git blob identity. Original source logs, original diagnostic blocks, API receipts and corrections remain distinct from derived summaries. Repeated appearances of identical originals in separate provenance groups are not independent tests or independent experimental evidence.

Run the copied, previously reviewed verifier with Python 3:

```sh
python3 qa/repository-consolidation/20261120/rust-union-c2d5-round6/verify_evidence.py
```

It verifies exact archive/member identities without extracting or executing archive members. It does not run Rust, native jobs, formatters, tests or CI, and a successful archive verification is not product qualification. Selection manifests explicitly identify what is included, reused or excluded; a reference to a historical seal does not imply that every member of that seal has been duplicated.
