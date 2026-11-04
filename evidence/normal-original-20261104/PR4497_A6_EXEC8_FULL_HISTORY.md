<!-- musl-helper-source-20261103-begin -->
## Latest follow-up — ctor block fix verified by all eight original Exec controls; Core remains open

Current H [a6d8ce20bf8f5b6991d2dc5ef7313812944db060](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/a6d8ce20bf8f5b6991d2dc5ef7313812944db060), tree `1da8b039da9ccf72b2290af6af74dc6315a819b3`, is a sole child of H103. Actual prospective M `3795641fafad34e3a3735bb74c2f1d2377b0b1f6` has ordered parents [B `3a81000aae08c658276958d678874aca4db5eedd`, current H] and the identical tree; it is preserved on `test/hepta-musl-helper-exec2-ctor-merge-20261104`. This source publication carries `[skip ci]`. The separately bound original Exec selections have now completed on this head and its actual merge, as recorded below.

Only one line in `codex-rs/exec-server/tests/common/mod.rs` changes: the unchanged dispatch call is again the tail expression of a block initializer, as required by pinned ctor0.6.3's `$block:block` matcher. The call still executes once and returns the same guard; the static terminator, attributes, cfgs, dispatcher, tests, features and budgets remain. Exact file: 1,729 bytes, SHA-256 `fb2759919c1376c03e17047080ad45b5377b3de007a9f0cf02e1bdb36be661b2`, blob `f85ca57fec2901540cd16d8b772dd450a133df65`. Rustfmt1.96, independent source/macro review, an independent reconstruction from original remote bytes, full remote readback, sole-parent/tree and the single-line delta all pass. The exact macro archive checksum matches Cargo.lock and the actual compiler diagnostic. Independent review receipt: SHA-256 `155b6d1e316b1256227ebc390de5ba155f7c171690e359d4efb675a060c2ad91`.

[Exec2 ctor-fix run 41757104132](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41757104132) completed its sole push attempt 1 with **eight actual native passes, zero failures and zero ignored/measured entries across all four successful jobs**. No-PR harness S `53b52f2f430f15bff33a0c2731a806cf34cc27e7`, tree `ff3c3b266611135a9b453ba221c1373d7414f88d`, is a sole child of current H and adds only `.github/workflows/hepta-pinned-musl-helper-exec2-ctor.yml` (71,534 bytes; SHA-256 `7e50c27b09c9f8f53a884d58c49de4cfce8c3118b94f3b5ff71acf9a5ff549c1`). Full remote bytes, the one-file tree delta, and reversing every source/harness identity substitution back to the original reviewed Exec2 workflow all pass. Independent binding review is SHA-256 `68dc64152c2bfeb52effa9521e51d3fa9d9bc3812ebb7d4f9c152bfc5688c0fd`. All four H/M × GNU/musl lanes passed the original two named selections each. Full official ZIP bytes/SHA-256/CRC, source identities, actual test names, BEP run/shard/attempt 1 with both cache flags false, original 300-second deadlines, metadata pre/post and configured helper/test ELF/runfiles records are independently verified. Each discovery target records one pass and three filtered entries; each filesystem target records one pass and 115 filtered entries. Filtered entries are not counted as passes, and these are exact selections rather than complete target suites. The final per-case/ABI index is 46,894 bytes, SHA-256 `9707151fbd46761730658a33ca9dd25abf5e55426da7a64f4ec390f84128bb52`; root separately reconciled all four official artifacts and jobs with that index. GNU records the original GNU dynamic interpreter, while the musl test/helper records have no PT_INTERP and the exact musl configured target. The packages contain CI ELF observations, not independently downloaded ELF bytes. The prior 132 passes remain results of H103/its actual M; they are not relabeled as new-source executions. Core continuation run41753694294 has completed as a build-only H103 cache producer with both jobs failed and zero native admission. Its preserved evidence and cache increments are being fully audited before choosing the next build-only step. A later consumer must bind the actual final H/M and complete its own build.

The exact older normal140 and Exec compilation-failure records are now preserved in [immutable evidence commit 4d8cedecf25a90d00ff3e5a0111206823371aead](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/4d8cedecf25a90d00ff3e5a0111206823371aead/evidence/normal-original-20261104), branch `archive/hepta-normal-original-evidence-20261104`. All 125 files / 5,106,896 bytes were read back in full and matched their Git blobs; the complete tree delta contains only this evidence directory. Its two packages preserve 12 official original ZIPs and 528 original ZIP members. The data-only reader verifies all chunks, packages, member identities and CRCs without extraction, network, artifact-code or native execution. The original failures remain visible, source/workflow files are unchanged and the archive created zero automatic runs.

### Retained H103 helper repair and original outcomes

Published source [103e4bcb3a6fbce57943a0c7c339d1d48808ce69](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/103e4bcb3a6fbce57943a0c7c339d1d48808ce69), tree `73d6f50dd52b5e30b536758335dbc82385f63ab3`, is one fast-forward child of `32401b2aff9b3cd976ccb10d928595c3b9d3568d`. Actual prospective merge `68c36639d609033334785b347273899f5abab500` has ordered parents [base `3a81000aae08c658276958d678874aca4db5eedd`, new head] and the same tree. Local `dc9a4640b881ebedb538a7a739d32ff34cf330d1` is tree-equivalent, not the published commit identity.

The prior head's [completed normal run 41731949797](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41731949797) recorded **136 native passes and four failures**, with no retries. Both original Exec selections passed on GNU but failed on both musl source/merge lanes before reaching their namespace/PATH assertions: the child emitted `Unrecognized option: 'listen'` and closed stdout before its listen URL. These failures remain retained. Source inspection of pinned Rust 1.96 supports the startup diagnosis: its glibc-only constructor initializes argument storage early; the musl test constructor sees arguments before normal Rust initialization. The failed artifacts do not contain a child exec-path trace, so that causal diagnosis is source-based.

Exactly five test/build files change. The original six private dispatch functions and constructor body move unchanged into a shared module. A test-only, same-target Bazel binary and Cargo example enter that dispatcher from ordinary `main`. Musl selects that declared helper through the existing runfile contract, with fail-closed explicit paths and a process-lifetime private sandbox alias. GNU/Windows retain the original self-test executable route. Production sources, original test bodies/assertions, features and deadlines are unchanged.

Formatting, clean frozen-source checks, two independent static reviews, and full remote readback of all five files (15,601 bytes) pass. The remote full tree matches the frozen candidate. This source publication carries `[skip ci]`; it does not assert compilation or native success. The dedicated normal harness now binds this head and actual merge, proves both Exec roots select the same-platform helper, and retains the original selections and budgets. For musl Cargo/nextest exact selections, explicitly build `cargo build -p codex-exec-server --example codex-exec-server-test-helper` from the same source with the same target/profile/target directory first; `--all-targets` can build the example as a libtest and is not helper readiness.

[Normal run 41746794500](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41746794500) completed its sole push attempt 1 with **132 actual native passes, zero native failures, and eight Exec entries not executed**; the workflow conclusion is failure. No-PR harness S `bb813345a214c52767ac544230d6a475d51e8509`, tree `6f87a639895f98ecbd0510be82430d4ecfecc1c5`, is a sole child of H103 and adds only the 115,861-byte workflow, SHA-256 `9dcf16372805fa13840875e396da579f16236c6f32524465eca4425d2a4bfe24`. All eight original evidence ZIPs were downloaded and verified against official size/SHA-256, every member CRC, exact source/tree/harness, complete original native names/counts and BEP records. Four feature lanes passed six entries each (24); four remaining lanes passed Infer 25 plus Supervisord 2 each (108). Infer records 153 filtered entries per lane; filtered entries are not counted as passes. Original runner/parser, jobs=2, 60-minute jobs, exact selectors, native 300/900-second deadlines and one uncached attempt remain.

All four remaining lanes stopped at the metadata-only helper precheck with `KeyError: 'value'`. Both aquery commands in each lane completed successfully; no cquery, helper invocation or original Exec native command followed. The reader incorrectly indexed the required presence of a proto3 string value that Bazel legally omits when empty. The pinned Bazel schema and the eight original aquery records support a narrow decoder repair: omitted value becomes the empty string, while types, nonempty unique keys, exact nonempty BAZEL_PACKAGE, ordinary-bin target/profile and runfile requirements remain strict. Eleven pure reader controls and re-reading all eight original aquery records pass; this is static evidence, not Exec success. The independently reviewed [Exec2-only follow-up run 41752326136](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41752326136) completed its sole push attempt 1 with all four jobs failed and **zero native executions**. Harness S `b88960bf89ee23f67cb5174a10048dce5a64a70e`, tree `28a1a00edddf2ddf66dc85e8d5ef55ef7807ec00`, adds only `.github/workflows/hepta-pinned-musl-helper-exec2.yml` (71,509 bytes; SHA-256 `75e8b1e97765a2b6b9b46c7cd7d3b48dc3fe2f70a32b0bd25a39ebb683b7cd70`), with full remote byte equality, sole H103 parent and one-file delta verified. All four original official ZIPs are independently verified. All four metadata prechecks passed the actual aquery/cquery proof. Each of the eight selected entries then ended with BEP `BUILD_FAILURE` / code 1, with no `testResult`, `testSummary` or original libtest log: pinned ctor 0.6.3 rejected the bare static initializer (`no rules expected dispatch`, `tests/common/mod.rs:22`). All four postchecks lacked the helper ELF as a consequence of failed compilation. The eight entries are blocked-before-native, not eight native test failures; the original failed outcomes are preserved without rerun. The completed boundary audit is SHA-256 `b50a3a31245429006e14957e05d0fb76bdeddf536d9fdd35c59f839a9312f91d`. The one-line block initializer correction is now published as current A6 above, with a separately bound new run. Helper metadata remains bounded to 300 seconds per phase, including 45 seconds to stop only its owned client, and requires post-native configured output/ELF matching. The original terminal audit is SHA-256 `485fbbc63eb26b72cb163c515acc3e6dae7f329bf04af84a75cbada10e73971a`; the eight-graph reparse is `9074791e1ccb9d8c7c60d71faf7f47bf92cd76df0d99ad6e939b6a4fab70b063`.

[Core build-only producer 41737096331](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41737096331), bound to H324, completed with **both jobs failed and zero native tests**. Both builds reached the bounded client deadline, exited 8 / INTERRUPTED, and did not complete the original target. Isolated shutdown, source retention, partial-cache packing and upload succeeded. All four small before/final evidence ZIPs match official size/SHA-256 and every member CRC; all before-evidence bytes are preserved in the final evidence. GNU retained 37,478 cache files; musl retained 26,283. These are partial build data, not successful tests.

[Core consumer 41745450692](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41745450692) completed its sole push attempt 1 with **four failed/incomplete own builds and zero native executions**. S `894bd349f7c985ec40d3b94894d5e7570404a5da`, tree `b62494b38f5055c79e3252aaac87398e1f0c04f5`, adds only the fully verified 77,622-byte workflow, SHA-256 `51368ae051666a1212ff36dbe6b16d10e31e49a5cdb27cae51ab74beb50d518d`. All four lanes passed immutable producer/artifact binding and complete ZIP/member verification before installing only isolated ac/cas data. Each own build then reached its bounded deadline, exited 8 / INTERRUPTED, and did not produce a completed target or admit the original Core4 tests. The raw logs contain interruption failures rather than a compiler diagnostic. Shutdown and final source checks passed. All eight small before/final evidence ZIPs now pass official size/SHA-256 and CRC verification; all 18 before-build members in each lane are byte-identical in its final evidence.

The raw build summaries prove the imported partial cache was used: H/M GNU recorded 7,730 / 7,743 disk-cache hits and H/M musl 4,548 / 4,559. The consumer did not export its additional compiled progress, so an unchanged consumer repeat would lose that progress. The two-lane H103 GNU/musl [build-only continuation run 41753694294](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41753694294) is now running on its sole push attempt 1. S `c3ea43bcbe275f4674ab7ba92f66a90214b8e67b`, tree `0b8e993502be92b45906a2dd20f5b791470ca531`, is a sole child of H103 adding only `.github/workflows/hepta-pinned-core-cache-continue.yml` (108,634 bytes, SHA-256 `6a868fc6669de94432029589461dd1b366f048f2e996e7f453b63e6508ec184d`). Complete remote bytes, parent/tree, one-file delta, exact existing trigger scope and an independent replay of the new import-contract checks against both original GNU/musl receipt sets all pass. It restores the same verified original producer cache, retains the original target/configuration and jobs=2, and attempts to preserve newly built ac/cas after isolated shutdown. It retains the original maximum 48-minute build phase and 60-minute job budget. The shared post-build reserve is 600 seconds; packing is bounded by min(360 seconds, remaining time minus 240 seconds for transfer). Slow shutdown/identity/upload steps reduce packing time; complete cache transfer is not promised. Insufficient time or incomplete compilation remains explicit FAIL with zero native passes. A future consumer must still complete its own exact-source full target before the original complete four response-header entries, once and uncached. Original timeout900, assertions, V8 dependencies and features remain; no test-timeout override is introduced. **The selected 16 Core entries have not passed.**

**Draft/HOLD remains.** The preceding 136 PASS / 4 FAIL and all earlier failures remain preserved. No merge, production activation or Library deletion occurred. Whole-system qualification, PQ-128 and installed business confirmation remain unclosed. `whole_system_qualified=false`, `pq_128_qualified=false`, `production_activation=false`.
<!-- musl-helper-source-20261103-end -->

<!-- normal-projection-receipt-20261103-begin -->
## Current source: generation-cut repair verified; musl Exec startup remains open — 2026-11-03

H `32401b2aff9b3cd976ccb10d928595c3b9d3568d` is a [skip ci] child of `51782f433497e69301b9fbed2395fda771a1cbae`, with complete tree `7d7b390d6e00f7acbd50893bd8b488538272f01f`. Actual M `d674db1adb923833bd320485aabd8b801fadc087` has the same tree and ordered parents [B `3a81000aae08c658276958d678874aca4db5eedd`, H]. Canonical ref, full commit/tree/parent identities, the one-file delta, and the complete remote source bytes were verified.

The original lifecycle integration helper counted legacy copied graph rows, while the existing migration 0014 and writer publish `revision_facts_v1` cuts. The helper now requires the exact compact-storage witness and counts the latest selected immutable revision for every memory in the same scope at or before the receipt's generation, then applies the existing verified/active requirements. Original trigger fact/source identity, current pointer, exact counts, all returned digests, tool-output comparisons and restart equality remain. Four call sites add stage context; count failures include scope/generation and observed/expected numbers. Production writer, schema, features, test names and deadlines are unchanged.

Only `codex-rs/hepta-agentd/tests/cognitive_product_e2e.rs` changed: 58 additions / 22 deletions, 99,128 bytes, SHA-256 `c8a36d1a4731619de8cfdbcc7bfa675a5c1012c6fe4d5d97ada2d86beec5714b`, Git blob `c8ff0a8d7497c4742d539e5bab9a43b7099d80dd`. Local frozen commit `be284b9eebd2466278b8674a812985e2a820a39f` has the identical complete tree. Original `just fmt` and whitespace checks passed. Sixteen lightweight SQL controls cover fresh writes, corrections, tombstones, multiple memories/sources, future cuts, other scopes, inactive/unverified revisions, missing/wrong witnesses, current pointers and visible count disagreement. Independent static review also matched both count predicates to the migration's exact invariants. These are static/SQL checks, not a new native result.

[Run 41731949797](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41731949797) completed on attempt 1 with **136 actual PASS / 4 actual FAIL / 0 ignored, from 140 selected native entries**; overall workflow failure is retained. All four feature/profile lanes pass their original six entries, including the generation-cut product lifecycle. Each also passes seven configured roots and nine actual Rustc actions.

| Source/platform | Feature6 | Remaining29 | Feature artifact | Remaining artifact |
|---|---:|---:|---:|---:|
| H/GNU | 6 PASS | 29 PASS | 13279050716 | 13276683697 |
| H/musl | 6 PASS | 27 PASS / 2 FAIL | 13278581528 | 13278392709 |
| actual M/GNU | 6 PASS | 29 PASS | 13277019317 | 13279121315 |
| actual M/musl | 6 PASS | 27 PASS / 2 FAIL | 13278540923 | 13276914130 |

Remaining29 totals 112 PASS / 4 FAIL: all original Infer25 and full Supervisord2 pass. Both GNU Exec cases pass. Both musl lanes fail the original discovery/filesystem cases at child startup: `Unrecognized option: 'listen'`, then `exec-server stdout closed before emitting listen URL`. Original native exit101 and Bazel exit3 are preserved; namespace/PATH behavior has not yet been reached. The original logs have no execve pathname trace, so child-path diagnosis remains a source-based inference.

All eight official ZIP sizes/SHA/CRC, exact native names/counts, single uncached BEP attempts, original 300/900s configured timeouts, clean source-before/after and ELF identity records were verified. Full writer and Supervisord retain filtered=0; Infer shows153 filtered. ELF bytes are not in these ZIPs. Root independently crosschecked the four remaining29 raw artifacts: 8489B receipt SHA `32d9ffbca9ea0972bdc591f0f627600e873c9a6d2f5f87809fed48d0eaa12d9f`.

Source-bound no-PR harness S `766edc7c0e6a977d561d796ba5b225899f288486` adds only the 74705B normal-projection workflow, SHA `1a5b5cccb9ba06a9baad2eaf065e3a55d5acab6ff9d67d482aa19c313a689138`. Original jobs=2, 60-minute jobs, native deadlines, filters and single uncached attempts remain. The earlier 817 Robrix/IPC/operator28 evidence is outside this140-entry denominator.
[Core build-only producer 41737096331](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41737096331) is in progress on two H lanes, GNU/musl. S `5449c700023295a45e8d04dbecdbe911d8df0a70` is a sole child of H, adding only the 52501B cache-producer workflow (SHA `b4186bf321f72a6e70e9cccb9f826b4b908d9a4047af45396bd2616064735e96`), fully read back. It keeps the original Core target/profile/toolchain/runfiles/jobs=2 and 60-minute jobs, with an isolated output base/cache, bounded 48-minute build phase, owned-server shutdown and small-evidence upload before bounded full-member archive verification. Partial compilation remains a failed build and transfers data only. This producer requests zero native tests; Core's original four entries remain pending a complete consumer-source build and their own native results.

Historical 517/785 remains **20 PASS / 4 FAIL** below. The four new musl Exec startup failures remain open for a source fix and new source-bound validation. `whole_system_qualified=false`, `pq_128_qualified=false`, `production_activation=false`. No merge or Library deletion.
<!-- normal-projection-receipt-20261103-end -->

<!-- normal-feature-parity-20261103-begin -->
## Prior source: verified Cargo/Bazel feature parity and retained native failures — 2026-11-03

H `51782f433497e69301b9fbed2395fda771a1cbae`, tree `4beb6d9655e929164af45c0abba961f04a0c5f80`, is a [skip ci] child of `11236566d4dd96deee06be586c503bb5d86ce4b6`. The actual merge `785478805f64bf9b708eb0abafd8213eab67471a` has this same tree and ordered parents [B `3a81000aae08c658276958d678874aca4db5eedd`, H]. Raw ref, commit, exact two-file delta and merge ancestry/tree were read back.

The macro now forwards its existing `crate_features` to the generated binary and three integration-test rule paths. Agentd's ordinary Bazel macro explicitly selects its existing Cargo default closure, `default` plus `production-cognitive-write`. The four explicit manual qualification rules remain byte-for-byte unchanged. No runtime writer logic, Cargo feature definition, deadline, assertion or retry policy was changed.

The complete caller audit covered 232 tracked BUILD/Starlark files and 197 macro calls, with no parse errors, alias or dynamic keyword forwarding. The two prior nonempty-feature callers and Agentd have no build script, so this fix does not change build-script rules. Final formatting, whitespace and AST checks passed. The exact local source draft was `26212aa93bef74b2f23ff406da982bf1ab53a77f`, tree `821a0f6f6bb8e0775b6b42cae5fc1d3dc56f1a2f`; the canonical tree preserves the concurrent 24-file PQ role evidence addition. Its only root difference from that local draft is the unchanged external evidence directory.

**The feature configuration fix is verified in all four lanes; the selected native suite retains four real product-test failures.** [Run 41724890159](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41724890159), attempt 1, is complete with all four jobs failed. Each GNU/musl H/actual-M lane independently proves seven requested Rustc roots (nine actual actions including target/exec library variants) with the intended default/production or production/qualification feature closure.

Each lane executed the six original native entries once: default fail-closed **1 PASS**, default writer recovery **1 PASS**, qualification unit **3 PASS**, and the local Agentd cognitive lifecycle **1 FAIL**. Across four lanes: **20 passed, 4 failed, 0 ignored**. All four failures are the original `real_agentd_remember_recall_correct_and_forget_revalidate_physical_sends` case reporting `current projection rows did not match their generation receipt`. BEP records show test-process exit 101 and outer Bazel exit 3; this is an actual native failure. All 16 target executions have one uncached run/shard/attempt and a matching summary, with no rerun.

All four artifact ZIPs match their official sizes and SHA-256 digests, pass CRC checks, and contain 48 members each. Full raw native logs, actual Rustc argument/parameter-file bindings, source identity and clean before/after state, native/BEP outcomes, and runner-recorded ELF identities were independently read. Executable bytes are not included, so the audit does not claim independent ELF rehashing. The complete four-lane audit receipt is 25,316 bytes, SHA-256 `f2864c66b920fff95a96f45169e0dc30ecc1ca491dddc83c1a0b57ea4e35a24b`.

Source review identifies a concrete evidence-query mismatch: migration 0014 and the writer use `revision_facts_v1` generation cuts, while this integration helper still counts legacy `kg_nodes`/`kg_edges` copies. The subsequent narrow helper repair is published as H `32401b2a`, preserving exact current-generation, fact/source, node/edge count and digest assertions; its separate source-bound validation is documented above.

Separate no-PR harness `c45d7a50064f1b453c5bb894954d72d1c0606363` is a sole child of H, adding only `.github/workflows/hepta-pinned-normal-feature-parity.yml`, blob `7dd7b1ea1b0e513b68ee4a799a137d1c0a39793d` (35,407 bytes; SHA-256 `29ab97f2bc8c82b0c233ecf06200c81720bb106579a6ba676c9d8383ecebc9fc`). Original 60-minute jobs and native deadlines were unchanged. The prior local GNU dependency read-timeout remains recorded: 74.232 seconds, exit 1, zero Rustc actions and zero tests. No merge or production activation was performed.

<!-- normal-feature-parity-20261103-end -->

<!-- normal-final-20261103-begin -->
## Published fixture repair and final normal verification — 2026-11-03

The source pinned by the fixture verification run is `817e91bbf184a36e7546b5ea8ba16d9042269d30`, full tree `ce7d4cebb6e88618ca28628318e99eb0edb58453`, a sole child of `f5be46914c1a6516049871680c68108a7279adf7`. The actual GitHub merge ref is `2acb1024920e9dde820aa337cd6f677fa0afd397`, with the same tree and ordered parents [B `3a81000aae08c658276958d678874aca4db5eedd`, H `817e91bbf184a36e7546b5ea8ba16d9042269d30`]. These raw refs, trees and parents were independently read even while the PR metadata endpoint still showed the preceding head.

The one-file fake-bwrap fixture now resolves the already declared real binary before callers prepend the fixture directory to PATH, then forwards its complete argument vector through a sibling symlink. Existing argument logging, one-shot failure simulation and command validation remain. Production PID-1 checks and namespace requirements are unchanged. The exact file is blob `38d18aabb33dd4ee077dec13e28682fc1d99405b`, 1,434 bytes, SHA-256 `8b2789089041722b022f6af94c836a64da42a4c5ea7877f925a5078af1bc29c8`. Independent source review, original formatting and shell syntax passed; functional verification remains pending because that run did not reach the Supervisord scenario.

### Earlier normal run: native outcomes and workflow outcomes remain distinct

[Run 41685510936](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41685510936) tested frozen f28af9b/a809cc5, not the newer repairs. All four complete artifact ZIPs have been read back: official sizes/SHA-256, ZIP CRCs, member bytes, source/harness identities and single-attempt BEP records agree. Across its four GNU/musl head/merge lanes, the original Robrix 2, normal IPC 1 and operator 25 account for 112 native passes, zero native failures or ignored cases.

The actual workflow remains **3 successful jobs / 1 failed job**, overall failure. M/GNU job `126090069425` failed its old log reader when OpenSSH stderr interrupted one libtest status line; its original native summary is 25/0/0 and BEP is PASSED. That reader failed before recording the operator ELF identity. This missing identity is retained, not reconstructed. Eleven other runner-computed ELF identity records were verified; the ZIPs do not contain those executables for an independent binary rehash.

### Final normal scope

[Normal run 41703059992](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41703059992) finished with **all four jobs cancelled**, not qualified. Full-artifact verification confirms **28 original native passes in every lane, 112 total**: Robrix 2 + IPC 1 + operator 25, with no native failures or ignored cases. IPC retains 238 filtered cases per lane. All four Core targets remained in V8 dependency compilation, with no Core testResult/testSummary, native exit, result or original-test log. Later Infer, Exec and Supervisord steps were skipped. No Core assertion failure or later native result is inferred from these cancellations. Its separate harness S `1c4eeae8fcee707eabab52bc22a6ac27630b56db` is a direct child of H and adds only `.github/workflows/hepta-pinned-normal-final.yml` (blob `672e962196d0520249902e46513aff18fbd5ef24`; SHA-256 `d7e10d0d6e4ba5f8d561544aa4da4ad387cbef76e9460d95571bfc7bb3bcf358`). All 88 original workflow event sources remain unchanged; neither the dedicated harness branch nor the actual-merge retention branch matches an existing push workflow. No PR was opened for either branch.

The four artifact ZIPs match official sizes/SHA-256 and CRCs. Independent readback verified source H/M/tree, clean before/after state, workflow and runner bytes, all 12 original native logs with unique names/counts, and 12 single-attempt PASSED BEP result/summary pairs. All run/shard/attempt and summary run/attempt counts are 1; no retry or cached test pass was observed. Twelve ELF identities remain runner records because the ZIPs contain no executable bytes. The four dependency import records bind the prior verified AWS artifact; these evidence ZIPs do not contain that 145 MB archive. Audit receipt: 121,564 bytes, SHA-256 `19d65e88acba2b244e8d7d43c08fe6ebfeeb67d6eed0a3436bef61c12c2996df`.

Each of the four GNU/musl head/actual-merge lanes retained the original 60-minute job limit and was configured to execute eight ordinary targets: Robrix 2, IPC 1, operator 25, Core response headers 4, the 22 original isolated Infer cases plus three parser controls, two namespace positive cases, and Supervisord 2 registered entries representing **one** five-agent product scenario. Total selected entries per lane: 61. No ignored model workload or pressure campaign is selected. The reader retains native exit/BEP/single-attempt/unique-exact-name/count checks, rejects guard early returns, and records ELF identity before interpreting status lines.

The original local frozen Infer run remains a retained **23 PASS / 2 FAIL**, with its original automatic retries and missing-CLI errors. On the same frozen local source `491c06d1c52a4afd8a9e47c7bafa62d6278e35c1` / tree `85d539e3cecf0b0c009697a3b3c6e936d3a61033`, the previously planned CLI recovery built the actual CLI and passed both exact missing-CLI cases (2 passed, 175 filtered/skipped). The additional shared-parent validation then completed naturally once: **25 passed, 0 failed, 0 ignored, 152 filtered, zero retries** in 2.388785 seconds, bound to the actual 177-case registry. All 25 unique names and the original native summary were read back. Test ELF `f708ef8be0c5860ce8dc2113b88a7117d077c29a5e1ea9f865ab5ff7f56e7ed5`, CLI ELF `a979f71c50dd75386ad7b8d23475bb4693df76ded36205ca84c3a6c15c760d0e` and clean source identities matched before/after. Original admission uncertainty and permanent locks remain recorded. This closes the local missing-CLI/shared-parent check on that frozen source; it is not a whole-package run or native qualification of the later 817 or 517 heads. Shared-parent result receipt: 5,303 bytes, SHA-256 `d019b980db4896dc1377f68c77beb0f84db14a44ebed22fe9ca4107f907ea148`; original stdout: 3,214 bytes, SHA-256 `4952b7659096eb61c6b601a17bc732262fb3206540b44c18fd82ed4f4b11253d`.

**Draft/HOLD remains.** The manual Agentd qualification-feature closure has source verification but still needs actual configured/runtime evidence; the default Cargo/Bazel feature-parity implementation is now published at 517 and still needs configured/runtime validation. Broader Core, platform, installed business, PQ-128 and whole-system qualification gaps remain unclosed. `whole_system_qualified=false`, `pq_128_qualified=false`, `production_activation=false`.
<!-- normal-final-20261103-end -->

---

<!-- pq-role-88cdc9c-begin -->
## PQ FinalUse authority keys — implementation and selected native verification complete

Published production change: [88cdc9c942dff6789efcb854d1e1eb0310fcc18e](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/88cdc9c942dff6789efcb854d1e1eb0310fcc18e). Exact validated descendant: `f5be46914c1a6516049871680c68108a7279adf7`, tree `6562cf35ff131944dfb95015d5615af2ab3b8477`. Later exec-server fixture commit `817e91bb` is preserved; the earlier f5 results are not assigned to that different source.

`UnixFinalUseAuthorizer::from_pq_config` checks canonical pinned ML-DSA public keys across issuer, revocation, external clock and external frontier roles before any remote request or local authority-directory creation. Different labels, sockets or supplied identifiers cannot make a reused key independent. Both rings retain their existing one-to-eight-key bound; valid separate future rotation keys remain allowed. This is configuration-time checking. Distinct keys do not establish independent custody.

The production change is three files, +174 lines: startup check, **one new test function** containing six role-pair collisions plus future-rotation/pin cases, and the existing FinalUse document. The constructor and persistence formats, original timeouts and per-use hot path are otherwise unchanged.

### Actual validation and retained failure

| Observation | Source-bound result |
| --- | --- |
| Initial frozen `f28af9b` plus the exact patch | **Exit 101; zero tests executed.** Sparse checkout omitted tracked `docs/modules/MODULES.json`, required by the existing compile-time include. Full original logs and source identity remain retained. |
| Fully materialized f5 before/after | All **11,221 tracked paths** exist; sparse=false; clean worktree; all three role-patch byte hashes unchanged. |
| `just fix --locked -p codex-hepta-infer-worker-host -- -D warnings` | **Exit 0**, no source changes. |
| `just fmt` plus the actual package-wide Cargo fmt check | **Exit 0**, clean source; supported formatting checked. Stable Rustfmt's four warnings about the ignored nightly-only `imports_granularity` option remain in the logs. |
| `just test --locked -p codex-hepta-infer-worker-host --lib -E 'test(final_use_authorizer::)'` | **11 passed, 167 reported skipped, exit 0**; original local profile; no observed retry/flaky lines. |

The added `configured_pq_roles_require_separate_canonical_keys_before_any_effect` function is **one of those 11 passes**, not an additional twelfth test. Durable job: `1a1a2dc9749-96a-7538`; Nextest run: `4a0af584-feb7-4104-bcd8-00b12af13606`. Complete command environment and raw warnings, including the transitive sqlx-sqlite warning, are retained.

[Immutable evidence directory](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/11236566d4dd96deee06be586c503bb5d86ce4b6/evidence/pq-role-key-separation-20261103): 24 exact files including full original/final logs, command requests, all 11 actual test names, before/after source manifests, summary and per-file SHA-256 manifest. The original `88cdc9c` hosted Cell-host job cancellation and dependent skip also remain non-passes.

**DRAFT / HOLD.** This is selected component verification, not whole-package or final composed deployment qualification. Explicit `ml_dsa65_v2` ordinary consumers are wired to PQ authority; untagged classical compatibility remains. Governance/release/recovery coverage, independent custody, whole-state rollback, migration, WAN and whole-system PQ-128 remain unqualified.
<!-- pq-role-88cdc9c-end -->

## Published Infer source checkpoint — 2026-11-03 18:47 UTC

Current H `f5be46914c1a6516049871680c68108a7279adf7`, B `3a81000aae08c658276958d678874aca4db5eedd`, actual merge `23e529c0bf6a293d12289dd6da229a6d037d41c2`, complete tree `6562cf35ff131944dfb95015d5615af2ab3b8477`. Ordered merge parents and tree were read back. Parent `34e86b6` and concurrent PQ parent `88cdc9c` are preserved.

Seven Infer test-only blobs match frozen local `491c06d1c52a4afd8a9e47c7bafa62d6278e35c1` exactly: 262 additions and no deletions. The original 22 affected fixtures run in fresh copies of the same test ELF; original bodies, assertions, deadlines and 16 existing ignored cases are unchanged. A parent returns only after one exact child test genuinely passes. Three parser controls cover false-pass cases.

The first local selected nextest run remains **23 passed / 2 failed**. Both failed home-binding fixtures lacked the real `codex` executable; the local nextest profile automatically retried them, and those original attempts remain failures. No follow-up success is claimed. The same-source CLI prerequisite build, two exact cases with retries explicitly zero, and one shared-parent execution of the selected 25 are pending. The combined head contains additional concurrent changes and is not assigned the frozen local registry or results.

The separate normal matrix at f28 has completed as recorded below, including its retained merge/GNU reader failure and missing operator ELF identity. Final combined-source normal controls are being prepared. Draft, whole-system and production holds remain unchanged.

## Current source checkpoint — 2026-11-03 18:24 UTC

Current H is `34e86b6558fa992717769046aedd0e4829e7fb72`, B `3a81000aae08c658276958d678874aca4db5eedd`, actual merge `0adbe92319722983eb166830cf2e2682645c2fae`, tree `823b67d9bf459ce47addfe234486248692cf36f9`. The actual merge's ordered parents and complete tree were read back.

This adds the explicit Cargo qualification feature closure to the four hand-written, test-only Agentd qualification rules: both `production-cognitive-write` and `qualification-cognitive-write`. Two independent static reviews reproduced the exact single-file blob `c3470b96a50d029ec00bfb9cca95e9696b72ff16` (9,681 bytes; SHA-256 `950140ab1ed11e4fa661edd304abfa149aa10977efb58c077b96024446b9c5c9`). Default macro configuration and all authority/epoch/lease/fence code are unchanged. The correct production-profile unavailable-store case is distinct from the old read-only case; an excluded test is not reported as a pass. Actual cfg and runtime qualification remain pending: the prior aquery stopped at a fixed AWS-LC download timeout, exit 1 with zero Rustc actions.

The concurrent parent `88cdc9c942dff6789efcb854d1e1eb0310fcc18e` and all three of its PQ authority role-key changes are preserved. This new source commit uses `[skip ci]` and had zero automatic runs on readback. Results from the earlier f28 normal matrix and local frozen Infer candidate are not transferred to this combined head. The PR remains Draft; no merge, production activation, whole-system or PQ-128 qualification is promoted.

## Normal Bazel checkpoint completed — 2026-11-03 18:08 UTC

The scoped [run 41685510936](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41685510936) finished on its first attempt. It binds H `f28af9b7700a61fbbcdcc121521cb879297d5e31`, B `3a81000aae08c658276958d678874aca4db5eedd`, actual merge `a809cc504d56048cf73b8c042c5f9a40939c38e6`, and tree `0d2e7a13950b07b127e24d83ae984f0157dae22a`; this checkpoint does not qualify later Core/Supervisord commits.

| Source / platform | Original native results | Job conclusion |
| --- | --- | --- |
| Head / GNU | Robrix 2/2, normal IPC 1/1, operator 25/25 | success |
| Head / musl | Robrix 2/2, normal IPC 1/1, operator 25/25 | success |
| Actual merge / musl | Robrix 2/2, normal IPC 1/1, operator 25/25 | success |
| Actual merge / GNU | Robrix 2/2, normal IPC 1/1, operator 25/25 | **failure retained: result reader** |

The last lane's original operator log reports 25 passed, 0 failed, 0 ignored, 0 filtered, Bazel exit 0, BEP PASSED, run/shard/attempt 1. OpenSSH output split one libtest status line, so the reader's end-anchored expression recognized 24 names and failed. That job and the overall run remain failures. Its operator ELF identity was not captured because the reader asserted before cquery; no missing hash is inferred. The other three jobs passed their original reader and identity checks. Artifact ZIP byte verification remains a separate pending evidence step.

A revised reader is prepared, not dispatched against this old source. It recognizes exact test-name prefixes, retains exact unique registry/running count/success totals and zero-ignore requirements, and captures the actual ELF before log assertions. Its Python heredocs parse, both observed passing native logs pass the corrected parser, and the historical original 14-pass/11-fail log still fails. Existing native budgets, selectors, source checks and single-attempt requirements are unchanged. No old run was retried or relabeled.

## Current follow-up — terminal event test sequencing and supervisor fixture path

Current head: `5f03b5fc6ae25d7906c4e9601e74bb9c1df5d727`; base: `3a81000aae08c658276958d678874aca4db5eedd`; actual prospective merge: `f2cbe6184eef0685a2561e8af6c420f233cc0b21`. Head and merge share tree `f78299a4a5cc90bdf40b4623fc3de74e31c61245`. Status remains **Draft / HOLD**.

- `ff9d8147fc09ee36fab70cd181bfdc0e6fd247d8` updates only the common Core test event helper. It waits for the exact event's terminalization owner within the original per-event deadline. Production terminalizing fences and the raw event delivery API are unchanged. The complete original `responses_headers` Cargo target executed **4 passed, 0 skipped**, with the exact four original names, no network-skip marker, and unchanged source before/after. The tested local commit `187eadc420282d58b0266ddd9c86c89c517f2bbb` and this canonical Core commit have identical tree `9ec1214c144d04b474b12e4384f672aef8bf2339`. Validation receipt SHA-256: `da2051017e573da3e5d5bd68f2f96ef3e804f713703a12c8c424aa791c066eb3`. Broader Core and hosted qualification remain open.
- `5f03b5fc6ae25d7906c4e9601e74bb9c1df5d727` changes one supervisor product-test fixture line to the existing Cargo/Bazel executable resolver. The generated release wrapper receives a resolved absolute executable path that remains valid after a child changes working directory. Existing arguments, wrapper checks, assertions, and budgets are unchanged. Independent source review, `just fmt`, and diff checks passed; the product/fleet test has **not** been executed for this fix.

These source commits use `[skip ci]`. The already-running [normal four-lane run 41685510936](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41685510936) is deliberately bound to the earlier `f28af9b...` source checkpoint and its actual merge, not to the later Core/supervisor changes. All four lanes passed checkout, source-identity, and fixed-dependency checks. The checkpoint has now completed; see the current result table above, including the retained merge/GNU reader failure.

---

## Earlier source checkpoint — SSH fixture execution and Robrix runfile resolution

Current candidate: `f28af9b7700a61fbbcdcc121521cb879297d5e31`; base: `3a81000aae08c658276958d678874aca4db5eedd`; actual prospective merge: `a809cc504d56048cf73b8c042c5f9a40939c38e6`. Head and merge have tree `0d2e7a13950b07b127e24d83ae984f0157dae22a`. Both source commits used `[skip ci]`; qualification remains **Draft / HOLD**.

- `5d0a113c0fae758e21ceba08051b6c6f90e6e9b4` keeps the original operator test binary and all 25 tests, wraps the original public target, and marks only its TestRunner action `no-remote-exec`. Remote execution remains first for eligible actions; the wrapper explicitly retains an empty skip filter. The original Cargo target and original public Bazel target each executed **25 passed, 0 failed, 0 ignored, 0 filtered** against the exact two-file candidate. Those local observations are tied to the tested local source and file hashes, not represented as executions of the later canonical commit. Hosted validation of the published source remains pending.
- `f28af9b7700a61fbbcdcc121521cb879297d5e31` resolves the declared Robrix manifest runfile to its physical leaf before the unchanged strict reader checks the complete sibling set. The fixture bytes, original two test bodies, strict non-file rejection, and byte comparisons are unchanged. Exact file SHA-256: `ebf5456b966c23ea59b9d056befb48f3d435a1310d957ef947ad1929b029b9c8`. The original Cargo two-test invocation completed naturally with **2 passed, 0 skipped** against that exact formatted source (1,194.023 seconds including compilation). The source hash was unchanged. This is a local candidate observation; the new hosted head/merge verification remains pending.

### Completed prior normal control run

[Run 41671935494](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41671935494) completed naturally on all four lanes: old head `5ee64a5e4840ae3de1ecac6ab7772e5657a7f629` and its actual prospective merge, each on GNU and musl.

| Original target | Head/GNU | Head/musl | Merge/GNU | Merge/musl |
| --- | --- | --- | --- | --- |
| Robrix complete two-test target | 0 passed / 2 failed | 0 passed / 2 failed | 0 passed / 2 failed | 0 passed / 2 failed |
| Normal IPC payload-and-EOF exact control | 1 passed | 1 passed | 1 passed | 1 passed |

All source/dependency checks passed. Each original target had one attempt. The Robrix failures are the same strict non-file assertion on a declared runfile symlink; they remain retained as failures. The four artifact archives and their members were hash-verified. This run contains no operator tests and does not qualify the full native suite.

[Run 41685510936](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41685510936) has been launched on the separate no-PR harness `8b18749afa0456ab71f44ac7ee1e26ac701dc1a2`, covering the new head and actual merge on GNU and musl. Each lane executes the original Robrix 2, normal IPC 1, and original operator 25 tests. Its source-bound workflow SHA-256 is `358ac2e3df4890e9abb5da4ac663e8e62655a13c8100707f9b2554e3712cd073`; execution has now completed as recorded in the current result table above. Existing full-system, installed-path confirmation, CPU/PQ, migration, and long-duration qualification holds remain open; these focused controls do not replace required checks.

---

## Earlier follow-up record

## Latest normal Bazel observation — IPC passes; Robrix failure retained

[Run 41671935494](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41671935494) binds head `5ee64a5e4840ae3de1ecac6ab7772e5657a7f629`, actual merge `eabab0b8f1d7abd3a983f8f80c95fdd57c2369aa`, and separate harness `0202997ae105a6cbb0f97c9cd18654dc364d96cc`.

The completed head/GNU and prospective-merge/musl lanes each report:

| Original target | Actual result |
| --- | --- |
| Complete Robrix target | **FAIL: 0 passed, 2 failed, 0 ignored/filtered.** Runfile lookup now succeeds, but the original strict directory reader rejects symlink leaves as non-files. |
| Exact normal IPC positive control | **PASS: 1 passed, 0 failed/ignored, 238 filtered.** This is the selected normal control, not the whole six-test native suite. |

Original artifacts `13252436167` and `13251677828` were independently downloaded and verified: complete ZIP size/digest, member hashes, exact runner, fixed dependency bytes, unchanged source before/after, original logs, and one BEP attempt per target. Robrix has native libtest exit 101 and Bazel exit 3; this is not a reader false failure. The other two lanes remain pending.

A manifest-leaf canonicalization repair is being prepared. Its purpose is to resolve the real fixture directory while retaining the original complete directory-set, file-type and byte assertions. The independent SSH fixture repair has passed the original Cargo 25 and original local Bazel 25; its source publication and actual hosted verification remain separate pending steps.

**Draft/HOLD remains. Original failed jobs, budgets, and required qualification gates are not waived.**

---

## Earlier follow-up — native C fixtures published

Published source is `5ee64a5e4840ae3de1ecac6ab7772e5657a7f629`, direct child of `dc69725d957c79d8737eb5fbedfe6f213252317a`. Its complete tree `088ab1b7809149d56af239ff167f42e55167d434` equals the frozen local candidate `94be7a4958f12e1004201a37e7591fb807bb533a`; the local and published commit identities are distinct. The current prospective merge is `eabab0b8f1d7abd3a983f8f80c95fdd57c2369aa` and has not been tested by this follow-up.

The four-file change declares the two existing C fixtures as Bazel build/runfile inputs and copies those built artifacts into each test's owned temporary directory. Cargo retains its original compiler path and flags. Fixture C bytes, original test assertions and timeouts are unchanged. A same-CPU GNU transition preserves the original dynamic-loader behavior for GNU and musl Rust test configurations. The manually declared qualification library and test binary now carry the same explicit Bazel-package marker as the ordinary macro-generated target.

| Observed check | Actual result |
| --- | --- |
| Both C fixture targets, pinned Bazel 9.3.0 | PASS; 664 actions; 118.465 s |
| x86_64 GNU and musl configuration binding | PASS; both use the same x86_64 GNU fixture configuration |
| aarch64 GNU configuration binding | PASS; same-architecture GNU selection; configuration analysis only |
| x86_64 fixture ELF inspection | GNU dynamic executable and shared object; not an ARM runtime result |
| Formatting, source extraction identity, preserved assertions | PASS |
| Original normal IPC exact test | Pending; no six-test-suite pass is claimed |
| Original Robrix Bazel two-test target | Still pending; earlier Cargo 2/2 pass and dependency-fetch failure remain separately recorded |

The locked AWS-LC archive was independently retrieved and verified in [download-only run 41664243615](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41664243615) at harness commit `4a78bf9314197ef5a8ea97f67134fdac6795589f`. The original 145,542,555-byte size and SHA-256 passed. Transfer to the local builder timed out before test execution; that is not a Bazel pass. The separate [normal Bazel run 41671935494](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41671935494) is now running at harness `0202997ae105a6cbb0f97c9cd18654dc364d96cc`. Its four lanes bind this published head and actual prospective merge, each on GNU and musl, and execute only the two original Robrix tests and the one normal IPC positive control. The tested head/merge source and the additional harness commit remain separately recorded; results are pending.

This publication uses `[skip ci]`. A readback found zero new automatic workflow runs for this source head. Existing required checks, prior failures, Draft/HOLD status, service budgets and pressure qualification requirements remain open as documented below.

---

## Earlier follow-up — Robrix runfile repair published; Bazel verification open

Published source: [dc69725d957c79d8737eb5fbedfe6f213252317a](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/dc69725d957c79d8737eb5fbedfe6f213252317a), tree `50ac1994fd97ad9e235eb8f1cbea0e62fb026263`, a single child of evidence head `2f0ad551`. The complete tree equals local candidate `8ec68c8360975e83ecb33dfc458ca737dbd2cd53`; these are distinct commit identities.

The two Robrix projection tests failed in Bazel because their tracked fixture directory was unavailable at the compile-time source path. This change declares the five existing fixture files as test data and resolves the manifest using the shared Cargo/Bazel resource helper. Complete directory and exact-byte validation, original test bodies, and all fixture bytes remain intact. The change is exactly two files, 8 insertions and 3 deletions.

Validation:
- `just fmt`: passed on the frozen final source.
- `just test -p codex-hepta-supervisor --test robrix_control_projection`: **2 passed, 0 skipped**, frozen-source run `61ed1185-cb9e-4c2d-9123-a4c217ec6ad5`, 2026-11-03 14:13:08.627–14:13:15.204 UTC.
- Original Bazel target `//codex-rs/hepta-supervisor:hepta-supervisor-robrix_control_projection-test`: **not qualified**. The initial run exited during pinned AWS-LC/LLVM archive acquisition before test execution. Exact pinned archive recovery and the same target's validation remain open.
- Remote readback confirms the complete tree, sole parent, both source blobs, and a one-commit fast-forward. The commit carries `[skip ci]`; no original required check is represented as passing.

**Draft/HOLD remains.** The retained V5 failure, other CI failures, whole-system PQ qualification and production activation remain separate unclosed gates.

---

## Retained V5 observation — business gate remains HOLD

Evidence head: [2f0ad551f63be3acc0580997f5867597f3b1cef4](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/2f0ad551f63be3acc0580997f5867597f3b1cef4), tree `de7e7a72fa5210394f98891852ff0dcc22268a62`. This adds exactly 35 evidence files, with no execution-source changes.

The V5 observations below tested [a7c523f366de3aaf9bce923be885ad275d0ecc22](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/a7c523f366de3aaf9bce923be885ad275d0ecc22), tree `070d61d7525d55938aa2d6ddcdbf666a138b3125`; actual tested merge `f561bfafef1171db955a886227de698e49609913`. Installed V5 binds Chain `12fe5f2c1f19704fe7eb635dede6839ed8b1e91e`, tree `c44112da731e3f958e55eb024e5762d6723ea2c9`. Evidence commits do not transfer runtime observations to new code.

**Draft; whole-system qualification and production activation remain false.**

### Problem, change and resulting behavior

Protected ordinary Cell and initial consumers explicitly configured as `ml_dsa65_v2` use canonical PQ authority. Material, CURRENT/selector and immutable FinalUse must agree on profile, with the original protected clock and startup deadline. Untagged compatibility remains classical; malformed explicit profiles fail closed. Experimental PQ schema 3 is refused without erasing its nonce/claim journal; canonical PQ uses schema 4. This is not automatic migration.

The latest production repair addresses TaskFlow writer contention. A mutation could read a deferred SQLite snapshot and immediately return `Unavailable` while another connection held the writer reservation. Write paths now acquire `BEGIN IMMEDIATE` before reading the state they extend. Ordinary readers retain read transactions. WAL/FULL, five connections, the five-second busy timeout, original provider-effect assertion, retries and business budgets are unchanged.

Both new integration controls hold an independent writer. The same pinned mutation must wait while ordinary reads remain available, then succeed after release; exact replay does not append. The support module is declared in Bazel. All four original effect lanes retain the complete package command; the required inventory increases from 134 to 136.

Only V5 was rebound to the current Chain source. All 42 execution-source rows were verified against an exact clean checkout. Historical V1–V4 and legacy pair pins remain distinct.

### Verified component observations

[Run 41634290628](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41634290628) and [immutable evidence](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/2f0ad551f63be3acc0580997f5867597f3b1cef4/evidence/pq-full-followup-20261103/README.md):

| Scope | Actual result |
| --- | --- |
| Original production code plus both new writer controls | Both fail on both retained attempts: `writer returned before release: Ok(Err(Unavailable))`. |
| Fixed complete AutomationStore package, local and all four hosted x64/ARM source/merge lanes | 136 passed, zero skipped, no observed retries. Original concurrent provider-effect case and both new controls pass. |
| Six exact HTTP owner/recovery controls per effect lane | Six pass. Each selector filters 238 other cases; this is not whole-Agentd zero-skip evidence. |
| Four Cell-host-v2 lanes | Per lane: material 23, real CLI 3, arg0 owner 7, original owner/FinalUse 42, contracts 195, plus one each for initial material, protected clock, startup budget and native Codex PQ turn/start. Overlapping selections are not summed. |
| Two Windows ledger lanes | Each: six witness and 11 evaluated-shadow passes; original floors six and seven. These selected results do not qualify protected Unix PQ host on Windows. |
| Four PQ policy-renewal lanes | Original jobs succeed. FinalUse component-observation run `41634290700` is skipped, not passed. |
| Production-patch build, strict scoped `just fix`, formatting and whitespace | Original checks pass. For the evidence-only follow-up, `just fmt` finds no changed paths owned by that formatter; `git diff --check` passes. |

All six Cell/Windows ZIP lengths and official SHA-256 digests match. All 53 Cell command receipts and four Windows records have verified log bytes, actual counts and source identities. Codex build bindings are checked, but its executable is absent from these ZIPs and was not independently downloaded.

[Production-repair evidence](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/a7c523f366de3aaf9bce923be885ad275d0ecc22/evidence/pq-effect-owner-20261103/native-validation.json) retains 35 original records, including failures. Rust execution used the six-file effect patch before V5 rebinding; all five Rust/Bazel files remain byte-identical in a7c523f. Workflow/V5 source controls and actual verifier evidence are separately bound.

### Installed V5 — terminal business failure

[Job 125929166343](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41634290628/job/125929166343) completed with failure at 2026-11-03 13:15 UTC. Original artifact `13233273505`: 41,009,316 bytes, SHA-256 `cd46b5985d874fc9a292a41270a8b33e257bbd418537fbc76cf6c93a92a3082e`; both verified from downloaded bytes.

| Original stage | Observed result |
| --- | --- |
| Artifact / execution-source / diversity controls | 17 / 51 / 32 passed |
| Original / protected installed handoff | 14 / 8 passed, zero skipped |
| Current PQ startup | 14 passed |
| Current History import/recovery | 15 passed; child fixture excluded from direct counting |
| Current growth CLI | 3 plus 4 passed |
| Fixed-host / reader controls | 20 / 98 passed; original reader minimum 86 |
| Five named native test processes | All five exit 0 |
| Independent final business gate | **Failed: `CONFIRMATION_TARGET`** |

All 17 command receipts match complete logs and clean before/after source identities. No provisioning or host errors are recorded. The native child returns 1 because its independent business gate fails.

Baseline confirmation takes **2.809602982 s**. Under pressure all seven blocks are submitted by **1.879015810 s**, but only one independently replayed History page is accepted. A second response arrives; its replay ends with `PUBLIC_REQUEST_DEADLINE`. No transaction confirms in the original four-second window, and full state equality is false. The accepted replay takes 75.877 ms caller-thread CPU / 1.302 s wall time; the failed replay takes 30.568 ms / 499.335 ms. Caller-thread CPU excludes separately owned workers. These observations do not establish that a particular optimization repairs the gate.

Three installed archives preserve all 114 non-executable original members, including nine SQLite snapshots. Three omitted binaries have explicit lengths and hashes; Cell and PQ Node gzip images were independently decompressed and hashed. The 489,017,776-byte Hepta daemon remains bound by original import/producer/installation records but was not separately downloaded.

### Historical pair remains a separate failed source configuration

Four legacy lanes bind Chain `c16507147b65285ea94dead22d3b93c5db7295af` or actual merge `d1b8ae970bb5e014b6feaa49030823e1d8228c90`, not current installed V5.

All seven blocks submit in each pressure lane, but History advances through only 3 / 2 / 4 / 4 pages for x64 source / x64 merge / ARM source / ARM merge. All confirm zero transactions and retain `CONFIRMATION_TARGET`. Baselines confirm in 1.209–1.379 s. Invariants/accounting close and verification-error lists are empty; full state equality stays false. No environmental waiver or isolated instruction-level cause is established.

Four lossless pair payload archives retain current-run non-executable records. Their manifests explicitly identify omitted executables and unrelated older Windows diagnostics in the x64-source artifact. Complete original pair ZIP preservation is not claimed.

### Integrity and remaining qualification

[Delivery manifest](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/2f0ad551f63be3acc0580997f5867597f3b1cef4/evidence/pq-full-followup-20261103/delivery-manifest.json) binds the other 34 files by size and SHA-256. All three committed readers ran successfully and reproduce observations without launching workloads. Published parent/tree, all 35 blob identities and manifest bytes were read back.

The writer controls establish their own defect and repair. They do not explain the historical 2d750610 x64-merge 133/134 failure, whose original log lacks the error value. Diagnostic-only b446 already passed 134/134 before the production repair; that pass does not explain the historical failure. [Earlier source-specific failures and evidence remain retained](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/b446a3f0745e0f7fa9ace98749aeb3e2f845807f/evidence/pq-4497-composition-20261103/followup-2).

[Chain #683](https://github.com/TrillionniumFoundation/Trillionnium-Chain/pull/683) retains complete Node x64 897 passed / 0 failed / 22 ignored and ARM 895 / 2 / 22 on 12fe5f2. Both ARM failures are `PUBLIC_MUTATION_CPU_BUDGET`. Component passes here do not close those failures.

Installed business confirmation, all-state migration/anti-rollback, complete authorization/governance/release/recovery roots, independent deployment/WAN evidence, proof PQ-128 and the complete neural-work quantum-cost argument remain unqualified.

`whole_system_qualified=false`, `pq_128_qualified=false`, `production_activation=false`.
