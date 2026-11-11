# MEM8 follow-up checkpoint V16

**V7 and V8 source-only qualification passed, and draft source PR #5935 now contains the reviewed pure source c895. The original b054 native failures remain recorded. All ten adoption gates remain open.**

This checkpoint binds the complete retained b054 outcomes, the two source-only operations, their actual formatter postimages, the original scoped-fix failure, and the separately admitted five-case Windows qualification. Old native passes do not qualify c895. Source correctness checks, synthetic memory readers and recoverable archives do not establish retained-memory benefit or restored owner/effect custody.

## Current source and actual publication

- Source PR: [#5935](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5935), still draft.
- Actual pure head: `c89540598693697577cda8cba31cb07f6ce65317`.
- Complete source tree: `5a7c897a33e4eef48ea8f4bf52eaf48ea7c866ae`.
- Parent/pre-format head: `1c063ba9e934f060181d4fc17d724361ba2a37fd`; its tree is `4e702e173439f422a7d00917d3c94064e42d45aa`.
- The root updated the source branch with expected previous head `b0547d2f874c0aeb54dabd3491caa2bee49fcb0b`, then verified the actual ref and full raw PR response, including head, base, body and draft status.
- Base remains `96038ccf0660154fac143ba6cbe4be81e00813e8`. The subsequently observed merge `f0a379f3ae78e6cb01abcc6ac6458bacef23997b` has parents [96038, c895] and the same complete tree.
- The source-only and native qualification harness commits are separate children used for qualification; they are not part of the pure source ancestry.

The publication receipt preserves the first PR response's still-old merge field. The later merge readback is a separate observation; the earlier response was not rewritten.

[Actual source publication](v16/source-v8/SOURCE_PR_PUBLICATION.json) · [independent source-gate/materialization audit](v16/source-v8/ROOT_SOURCE_GATE_AUDIT.json) · [later merge identity](v16/source-v8/MERGE_IDENTITY.json)

The changes since b054 add an explicit stdio handle allowlist for non-elevated setup launches and an active ambient-pipe regression; place matched-response recording after the request predicates and add one real loopback regression; and incorporate the two actual Windows Clippy rewrites followed by their actual Rustfmt output. The original hook cases, captured-output LEAK policy, case deadlines and elevated outside-delete assertions remain. The setup change is a candidate repair for the observed captured-pipe LEAK. The owner of the original leaked writer remains unidentified, and a completed native LEAK repair has not yet been established.

[Reviewed source candidates and immutable packages](v16/reviewed-candidates/PUBLICATION.json) · [complete candidate-package byte audit](v16/reviewed-candidates/ROOT_ALL_MEMBER_AUDIT.json)

## V7 and V8 source-only qualification

Both operations were separate, original invocations with the unchanged 600-second source budget. Their full records were independently replayed; neither ran Rust/native tests or issued a model request.

| Original observation | V7 | V8 |
| --- | --- | --- |
| Run / job / attempt | 43042186271 / 130596614396 / 1 | 43046107709 / 130610340916 / 1 |
| Initial source | `63a4c2492848e9560750c32bebaacce2762bf2a2` | `1c063ba9e934f060181d4fc17d724361ba2a37fd` |
| Actual gate duration | 156.902353 seconds | 212.521569 seconds |
| Python regressions | 18 distinct PASS, 0 FAIL, 0 SKIP | 18 distinct PASS, 0 FAIL, 0 SKIP |
| Cumulative reviewed paths against 2ae | 114 | 116 |
| Complete final tree entries | 14,053 | 14,053 |
| Caller Rust inventory | 6,204 | 6,204 |
| Full original caller golden | Equal except the complete-tree-derived count 6200→6204 | Same strict equality |
| Thirteen retired names | Zero hits, no excluded paths | Zero hits, no excluded paths |
| Cargo and Bazel lock bytes | Unchanged | Unchanged |
| Actual formatter paths | Four | Two |
| Native/model execution | Zero | Zero |

The full 75,046-byte caller JSON comparison preserves array order and scalar types, rejects duplicate object keys and keeps `authorityGranted=false`. The derived file count is the only allowed difference. V8 independently retained all 114 prior formatted postimages and added the two Clippy paths. The root recomputed all complete base, initial and formatted Git trees.

V7's original ZIP is 7,028,444 bytes, SHA-256 `91fd0f97c45766886b4082ab5f417338aa5d878681792079067b44c97dd44024`. Its 377 ZIP members and 375 original inner records were checked. The original inner archive retains the six hidden source entries omitted from the artifact's loose-file view. Thirteen actual binary parts reconstruct its complete evidence package; a computed whole-package identity is not presented as a separately created Git object.

[Original V7 audit](v16/source-v7-original/canonical-original/OFFLINE_VERIFICATION.json) · [all V7 archive parts](v16/source-v7-original/ARCHIVE_PART_PUBLICATION.json) · [root full remote and offline replay](v16/root-v7-scoped-v8/ROOT_COMPLETE_REPLAY_AUDIT.json)

V8's original ZIP is 7,072,031 bytes, SHA-256 `52ef17f6debe6951b066d27adf00e98451c02359f1a50c3d7e03071e96051709`. The root independently replayed the original verifier and obtained the same complete result. The 1,429-byte formatter delta was also independently reconstructed from full pre/post bytes, applied forward to reproduce both postimages and reversed to recover both preimages. It changes only wrapping, indentation and an optional trailing comma around the already-reviewed method pointer and let-chain.

The original V8 checkout kept its initial HEAD/tree and had two staged formatter edits. **It was not clean after formatting.** The root separately created and read back the exact formatted tree as pure c895. Unchanged lock bytes are not a new claim that every c895 native or Bazel consumer has passed.

The complete V8 evidence package is 5,694,700 bytes, SHA-256 `69eb23b53ccc3b27639e1fd2b8923d60d9b0c09813d5ab689f82ee90c8f181cb`, stored as twelve actual binary parts. The root read all parts back at an immutable commit, reconstructed all 28 archive members, verified the 383-member original ZIP and 381-member original tar, and replayed the unchanged complete original verifier. The six hidden source entries remain in that original tar.

[Original V8 audit](v16/source-v8-original/canonical-original/OFFLINE_VERIFICATION.json) · [V8 postimages and verifier publication](v16/source-v8-original/PUBLICATION.json) · [root source-gate audit](v16/source-v8/ROOT_SOURCE_GATE_AUDIT.json) · [complete V8 remote replay](v16/source-v8-original/ROOT_COMPLETE_REPLAY_AUDIT.json)

## Original b054 scopes: final outcomes retained separately

All entries below belong to b054, tree `3f89ddeff13d0af85f4abe2690699107357f1038`. They are not c895 results.

| Original scope | Observed result |
| --- | --- |
| Private CI, run 43035589916 | 34 distinct selected PASS; repeated positives and counterfactual mutants kept separate |
| MEM, run 43035589682 | 35 integrity Python PASS; 14 synthetic reader processes; 0 CPU-contract tests and 0 native tests |
| Architecture source head, run 43035589987 | 136 Python PASS; 0 Rust/native tests; source-derived check not reached |
| Architecture separate base merge, same run | 136 Python PASS with the same case IDs |
| Architecture combined accounting | 272 Python executions / 136 distinct cases |
| Blocking, run 43035589938 | 37 terminal jobs: 23 success, 6 failure, 4 cancelled, 4 skipped |
| Windows-current, run 43035590081 | Cancelled; 124 completed of 167 cases: 122 strict PASS, 1 LEAK, 1 FAIL; 43 unfinished |

The Private scope includes the original signed-credit case and its clean before/after source receipts. Two extra positive-control executions and four counterfactual executions are preserved separately; the two expected mutant failures are evidence of the controls, not extra members of the 34 distinct PASS set.

[Private original audit](v16/private-ci/AUDIT.json) · [private independent replay](v16/private-ci/ROOT_REPLAY.json) · [private complete remote-byte audit](v16/private-ci/ROOT_REMOTE_ARCHIVE_AUDIT.json)

### MEM and Architecture prerequisites and evidence limits

The MEM CPU/native jobs failed during apt prerequisites after DNS failures for `azure.archive.ubuntu.com`. The Architecture source job failed during its apt prerequisite after DNS failures for `ports.ubuntu.com`. Those are prerequisite failures; unexecuted Rust or CPU suites are not counted as failed test cases or inherited passes. The completed integrity/source Python results retain their actual identities.

The separate Architecture base merge was `52c1eb3eba7e58a09f262bd2bfec5440fa3e3d41`, with the b054 tree. Its 136 Python IDs equal the source job's 136 IDs. Earlier 138-case or 526-Rust results are not transferred into this checkpoint.

The 14 synthetic reader processes retain request/response/context hashes and zero model calls. They exercise logical read exclusion; snapshot bytes still exist. These are not real-task benefit, an independent trust domain, or full original-owner cold recovery.

The root fully hashed, CRC-checked and read the original **125,271,736-byte Architecture ZIP**, SHA-256 `41e2d94ddefe3926649e8af46dcaf3551b35649d987ece4385ce80bbc2bfb61b`. Its source-tar member is separately 125,284,646 bytes, SHA-256 `ad8929b86f82639830dda8b7c0cc517d1be5089090aa176be7e0f944a8f902aa`; all 14,050 source entries were verified against the immutable Git tree. **That entire compressed ZIP wrapper and source tar are not duplicated in the Git evidence package.** The retained 158-member package contains the full source index and audit, the selected original small records, and four complete original ZIPs. Its verifier's scope is explicitly the retained evidence; it does not reconstruct the omitted 125 MB wrapper.

[MEM/Architecture original audit](v16/mem-architecture/AUDIT.json) · [retained-evidence replay](v16/mem-architecture/ROOT_OFFLINE_REPLAY.json) · [eight-part remote-byte audit](v16/mem-architecture/ROOT_REMOTE_ARCHIVE_AUDIT.json)

### Blocking: complete original job logs, unresolved failures

The retained package contains all 37 final job records, 16 complete original blocking-job logs, three parallel prerequisite logs, the exact merge binding and seven Bazel target records. Its two actual binary parts reconstruct an 82-member package. The original b054 Mac Intel full job log is present; the earlier 9bd2 Mac transport gap remains an earlier, separate boundary.

The six failed jobs cover Fence inventory setup before checkout; SDK apt/DNS prerequisites before its tests; Windows shard 2; Mac Intel tests; and the Windows/required aggregation failures. The original required NEEDS map retains its reported abandoned aggregate values without inventing why they differ from an individually successful job. The four cancelled jobs had no runner/step execution in their terminal metadata; cancellation cause remains unobserved.

Windows shard 2 retains the real elevated outside-delete assertion failure and two later shared-lock poisoning failures. Mac Intel retains two failed target assertions (code-mode backpressure and memory peer completion) and two target timeouts (evidence and supervisor paired-product). The memory trace reports zero completed peers where 16 were expected, but it does not uniquely identify a deadline, authority, discovery or transport cause.

FLAKY Windows shard 1/4 and Mac core-all outcomes retain their failed attempts. They are not zero-failure passes. Cached target results, fresh targets, testcases and repeated output are separate units. In particular, GNU's 417 passing target results are the main command's 416 PASS/167 skipped plus one PASS from a separate command; they are not 417 Rust testcase executions. The GNU/musl overlapping target rosters are not independent scientific replications.

**The eleven Bazel execution-artifact ZIPs are retained as metadata only; their ZIP bodies are not in this package.** The 16 complete job logs are sufficient for the recorded target/case audit, but do not constitute full execution-artifact recovery.

[Blocking original package](v16/blocking-b054/PUBLICATION.json) · [original scope summary](v16/blocking-b054/records/QUALIFICATION_SUMMARY.json) · [independent count replay](v16/blocking-b054/ROOT_OFFLINE_REPLAY.json) · [complete package-byte audit](v16/blocking-b054/ROOT_REMOTE_ARCHIVE_AUDIT.json)

### Windows-current: the original product boundary remains failed

Original job 130573423888 ended cancelled after 13 completed groups. Group 14 was interrupted during compilation, with no Nextest start or case terminal; groups 15–19 did not start. The 43 unfinished cases are nine from group 14 and 34 from the final five groups. There is no final source-after receipt. The observed timing is compatible with the configured 65-minute job budget, but the scheduler's cancellation reason remains UNKNOWN.

The captured-output case `elevated_non_tty_cmd_forwards_env_output_and_exit` again has a strict **LEAK** terminal, even though Nextest returned zero for that group. The later setup-handle candidate was not present in b054.

The elevated outside-delete case again refused Neither and deleted both outside files/directories in TargetOnly, ParentOnly and Both. Its all-false outside assertions failed. The ordinary control child separately reported verified removal of Backup/Restore privileges and the expected ordinary four-cell outcomes; that marker is not evidence about the elevated child's token. The three new hardlink helper tests are not part of this original 167-case selection.

The full original 108,419-byte ZIP, 152,322-byte decoded job log, all original outcomes and source-before identity were independently verified. Artifact upload success does not supply the missing source-after or process settlement.

[Original Windows-current report](v16/windows-current-b054/REPORT.md) · [case-level audit](v16/windows-current-b054/ORIGINAL_RESULT_AUDIT.json) · [original package publication](v16/windows-current-b054/PUBLICATION.json) · [root complete remote replay](v16/windows-current-b054/ROOT_REMOTE_ARCHIVE_AUDIT.json)

## Original Windows scoped fix: three exits zero, strict qualification failed

Run [43038376307](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43038376307), job 130583219316, used a separate harness on b054.

| Original command | Exit | Source result |
| --- | ---: | --- |
| `just fix --locked -p codex-hepta-neuron --features qualification-owned-file-read` | 0 | Clean |
| `just fix --locked -p codex-core` | 0 | Clean |
| `just fix --locked -p codex-windows-sandbox` | 0 | Two source rewrites; strict clean gate failed |

The third command's modifications were retained before the original failure was reported. The collector stayed partial/failed. This was not three clean passes and was not classified as a timeout. Tools and both locks remained bound to the original receipts.

The two rewrites replace zero-capture cancellation closures with the same method pointer and turn a nested optional manifest lookup into the equivalent short-circuit let-chain. Full-byte forward/reverse patch review found no assertion, privilege, timeout or threshold change. These actual postimages were incorporated into the later V8 input and then formatted by the actual V8 operation. That later source preparation does not rewrite the original scoped-fix outcome.

The 88,948-byte archive, SHA-256 `9185cbae1917ca04132ced407da13277fc2dc74c44ddbb266d5cfd10808dc23a`, retains 163 regular members, the complete original ZIP and full job log, phase intents/raw/receipts, tool and source identities, patches, postimages and an offline verifier. It excludes the signed download URL.

[Original qualification summary](v16/windows-scoped-fix-original/records/QUALIFICATION_SUMMARY.json) · [independent postimage peer](v16/windows-scoped-fix-original/records/MEM_CI_CLIPPY_POSTIMAGE_PEER.json) · [actual blob publication](v16/windows-scoped-fix-original/PUBLICATION.json) · [root replay](v16/root-v7-scoped-v8/ROOT_COMPLETE_REPLAY_AUDIT.json)

## New c895 qualification: admitted, not yet accepted

The separate five-case harness is `5529aeaace80458fb0b1ecae776f95de78c5f9c3`, tree `df8a39e57da777a0d59f597cc678230be49414cb`, parent c895. One push admitted original [run 43047914262](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43047914262), job 130616746852, attempt 1, at 15:23:39 UTC. At the recorded 15:27:12 observation, setup steps had succeeded and the execution step was in progress; no testcase conclusion was claimed.

| Serial native group | Exact active scope |
| --- | --- |
| `core_test_support --lib` | One matched-response recorder loopback case |
| `codex-core --test all` | The two unchanged subagent start/stop hook cases |
| `codex-windows-sandbox --lib` | The ambient-pipe exclusion regression and the original captured-output LEAK case |

The job keeps one 65-minute envelope, original capture/local profile/100 ms leak policy, one test thread and zero retries. It uses real setup/runner binaries built from the frozen source. Each original JUnit must bind to a fresh UUID, the raw log, actual command interval and complete expected case/binary set. A zero-exit LEAK cannot pass the independent raw gate.

A known failed native group stops later native groups. Independently authorized scoped lint may continue only after an acknowledged exit and stable source, tools, helpers and both locks. An unknown exit or any drift stops all later commands. Overall acceptance requires five actual PASS cases and all three scoped fixes clean. The failed-result field `native_case_count` counts only accepted cases; actual attempts, partial passes, failures and LEAK are taken from original per-group raw/JUnit.

[Actual admission](v16/native-five-preparation/ACTUAL_ADMISSION.json) · [final rendered-source peer](v16/native-five-preparation/FINAL_RENDERED_PEER.json)

The newly discovered regular c895 runs are blocking [43048568477](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43048568477), Private [43048568252](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43048568252), MEM [43048568457](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43048568457), Architecture [43048568183](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43048568183) and Windows-current [43048569129](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43048569129). They are separate original runs on the new source. This checkpoint assigns no old native result to them and does not claim a completed required-CI result.

## Recovery, publication and adoption boundaries

Before this checkpoint's publication, the root verified the V8 original package and source/native admission records at immutable staging `c3914cdcc26bf1133c64ff97365ddd96c0f43421`, then retained its complete replay audit at `fa750896e11020ae7cdc3b03971c9d4846887fd2`. These are immutable object observations. Advancing evidence PR #5889 to V16 is a separate expected-head update with its own actual ref and full PR-body readback; neither staging commit alone constitutes that publication. The source-PR CAS and the native-harness admission above are separate, actually observed actions.

A bounded, read-only H observation inspected one incomplete registry page and the exact original V4 destination. The original request key was not exposed by the page, and destination absence cannot rule out an earlier or late write. **Original V3 admission/terminal and V4 write settlement remain UNKNOWN.** No original process, upload chunk, commit/abort or model call was replayed.

[Identity-bound H observation](v16/original-h-readonly/SAFE_OBSERVATION.json)

All ten adoption gates remain open:

1. Working-state scientific benefit.
2. Binding to the original ordinary owner.
3. Provider runtime binding and original request settlement.
4. Benefit on unseen successor tasks from retained episodic experience.
5. Strong memory baselines and association attribution.
6. Source ownership, exposure and independent trust.
7. Deletion propagation and external-effect correctness.
8. Full original-owner/effect cold recovery.
9. Total cost and slow semantic/skill consolidation.
10. Complete final hosted CI on the adopted source.

The original provider turn remains UNKNOWN; neither Provider G nor a different-key model replay was executed. Source gates and synthetic reader verification issued zero model requests. No new actor experiment, merge or deployment is claimed. Original failed attempts, cached results, unexecuted scopes, H uncertainty and compressed-archive omissions remain explicit.

Earlier published evidence remains [V15](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/3cfe2ba630123c8d29da92fe2292f33ce88c7d6d/qualification/memory-cell-mem8-ci-followup/CHECKPOINT_REPAIR_V15.md). The owner/adoption ledger remains separately reviewable in draft [#5897](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5897). This source and evidence work does not close those scientific or custody gates.
