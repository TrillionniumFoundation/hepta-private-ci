## Problem

The ordinary Candidate route has real E/D/T/B owners, but an independently evaluated negative Candidate cannot use the strict TrainingNoUpdate continuation. Its Source joins, retained publication, original Selector evidence and original C evidence need to agree on the same evaluated prefix. A signed receipt alone must not replace live original-owner readback or provide publication authority.

## Changes

- Bring the existing original Model/Artifact and readback stack onto the common source at `c1e4fab7fa13e705d1ebf32b87e3a758f33d7e60`.
- Add explicit Dataset v3 joins from signed Decision fields to the original NDU Source, output, policy, publication, canonical candidates and selected action. Apply the same exact Source checks to independent B. V1/V2 policy freezes remain separate.
- Add an explicit V2 signed-experience intake that preserves the Observer's independently signed measurement digest. Keep V1's publication-support rule and both profiles' signatures, observation window, Source and durable ledger checks.
- Add evaluated-retention publication and recovery using the actual trained Candidate, independent negative B, original Artifact selection, CURRENT, Control intent and exact FinalUse grant. Retain the same finite original Trainer and Evaluator clients through the private consuming publication continuation.
- Add original evaluated S and C receipt mechanisms. S rereads original T/B and Cell CURRENT. C rereads original T/B/S, then observes the actual Source and Cell before journaling and signing. The read-only S host consumes the actual owner and retains its shared Cell and finite clients. Recovery stays read-only; a missing recovered C journal cannot claim or sign.
- Authenticate the exact E/D/T/B[/S[/C] negative-Candidate prefix at Root, including pairwise T/B/S/C actor/controller separation. Preserve the existing TrainingNoUpdate and Model bounds.
- Preserve both caller inventories and authority checks. Repair observed typed-receiver ambiguity with concrete UFCS calls, migrate source checks to extracted private helpers, and retain deletion, conjunction-flip, uncalled-closure, consuming-self and visibility-widening attacks.
- Repair the observed Rust 1.96 test compilation issues and integrate reviewed maintenance postimages. Cargo.lock and the caller verifier are unchanged. One existing private read-only Trainer caller is registered after the actual full-index failure below; no authority predicate is relaxed.

## Exact source and observed validation

Current PR/source commit: `a96d1b821d10ed3d9e99dd06c5141f9f242ae318`  
Source tree: `f96bebefbc1e7d8187efadb62f88d524cdd18451`  
Parent: `90fd0f22cfdfd6c839ef5ba9c694e9189c51e947` (the frozen 161-file failure-evidence snapshot).

This commit adds exactly 19 reviewed paths: 14 Rust production/test postimages and five caller/source-QA files. It introduces an explicit opaque evaluated four/five-cut read profile and consumes the actual original Source/Cell transport in remote S attestation/readback. Legacy TrainingNoUpdate, Version and completion-readiness profiles remain strict. Five-cut serving reads an already completed C result; this commit does not yet provide the remote C receipt/command consumer or ordinary Candidate dispatch.

All 14 complete postimages passed actual isolated Rust 1.96 formatting. The scoped source/mutation run passed **82 tests**, including four demonstrated branch-local uncalled-closure attacks. Exactly one existing caller set gains the real remote S caller; seven boundaries and three protected rows are added (541 boundaries / 389 protected rows). All other caller sets, authority/source rules and prior forbidden markers remain. The allowlist adds only this exact new CALLERS SHA. Parent reads, actual uploaded blobs, published-path blob reads and the one-commit/19-path GitHub comparison independently agree. Native validation of a96 has **not run**.

The seven-file native fixture/diagnostic repair remains at `4ab34bbd3ca803213b6eecbaba81af719630f5d0`, tree `f947d38de96534b3882fba023e51ecd0476c809d`. Actual complete-source maintenance on 4ab passed cleanly. The first diagnostic's unknown start acknowledgements were retained; same-key reconciliation later established a preflight `FileNotFoundError` for the just-built own target, before Rust or tests. Its cause is unknown. A separately recorded v2 admission created only that missing empty own target, preserved the source, tool pins and budgets, and completed the original three-case diagnostic. **All three cases ran once and none passed: Panel stack overflow, C evidence failure before withdrawal, and Deep cold-readback timeout.** The original `just test` command exited 100; the collector did not time out. This diagnostic cannot validate the later a96 source.

The 521 repair registers one existing private read-only Trainer service in its exact caller set and existing source-QA expectation. It changes no Rust or verifier bytes. All other caller sets, 534 boundaries and 386 protected-file entries remain unchanged.

The seven-file native repair preserves inclusive signed-evidence expiry, freezes fixture Candidate order before Cell admission, splits complete provider scenarios into bounded cases, and moves three shared Panel child futures to the heap. Original 8 MiB stack, 60-second case limits, signatures, owner reads and refusal assertions remain. C evidence failure reporting and flushed Deep S/C stage markers are diagnostic changes; they do not claim those two failures are fixed.

Actual isolated Rust 1.96 formatting exited zero for all seven complete postimages. Independent parent-blob, local-byte and uploaded-blob checks agree; GitHub compare is exactly one commit and seven modified test files. The original-binary GDB diagnostic reproduced the Panel failure: SIGSEGV during initial admission/CognitiveStore polling, then Rust's stack-overflow handler and natural SIGABRT. Its source and binary stayed identical. This does not establish a defect in flume. The subsequent 4ab diagnostic still overflowed, so the three future changes are not a sufficient repair.

| Check | Actual observation | Scope |
|---|---|---|
| Full source closure on cc22 | **397 passed / 0 failed**, exit 0, no timeout; original command elapsed 255.525 s | Complete source gate; clean identical 14,842-path inventory before/after |
| Rust 1.96 formatting on cc22 | **Exit 0**, unchanged source | Formatting |
| Scoped maintenance on cc22 | **Exit 0**, zero automatic postimages and empty patch; clean identical source and Cargo.lock | `just fix -p codex-hepta-agentd --locked --offline`; not native test execution |
| Scoped repair regression | **66 passed / 0 failed**, including 188 ordered-marker attacks | Selected source preflight; not the full gate |
| Focused native on cc22 | **Failed: 109 run, 78 passed, 29 failed, 2 timed out**; original command exit 100 | 24 failures are confirmed stack overflows; five are explicit failures. Fresh JUnit contains each of S3/C4/intake2 exactly once: intake2 passed, S3+C4 failed. |
| Clean maintenance on 4ab | **Exit 0**, zero postimages / zero patch; actual 14,995-path inventory unchanged | Actual `just fmt` and scoped `just fix`; test execution is separate |
| Three-case diagnostic on 4ab | **0 passed / 2 failed / 1 timed out**, each expected case once; original command exit 100 | Actual Panel SIGABRT/stack overflow at 2.462 s; C evidence failure at 8.647 s before withdrawal; Deep cold read hit the original 60 s case limit. Collector `timed_out=false`; source unchanged. |
| New evaluated-read source checks on a96 | **82 passed / 0 failed** | Scoped source/mutation suite against actual formatted bytes; native and final full gates remain unrun |
| Final five-crate native | **Not started** | Held until the actual focused failures are repaired and the required named cases pass |
| Final protected Root native | **Not started** | Original 32 ignored-test parents, actual UID0 and protected bind |
| Final full caller | **Not started** | Waits for native repair integration; original self-test 300 s / verify 4800 s budgets and exact workflow bytes remain |
| Previous full caller on 8faf | **Exit 1**, no timeout or controller kill, unchanged clean source | Missing declaration for the existing original Trainer read-only service; failed original retained |
| Full-index single-boundary repair check | **Exit 0**, 6,595 Rust files; original failure reproduced, exact three callers accepted, three unregistered caller forms rejected | Exact cc22 source with one in-memory caller declaration delta; clean identical 14,842-file source and Git metadata. This is not a complete fullcaller pass. |

The complete cc22 source log is 89,504 bytes, SHA256 `9c0957c52f00b32ed36b9ec7144df744e763f918c2e37340966ac923092d2034`. The clean maintenance log is 69,896 bytes, SHA256 `f36972fca43ae85dfb8286b9130e2a151fdb18dea2ec5fe16ec26001722af5bc`.

The earlier 8faf full source run actually failed: 381 passed and 16 failed or errored. The before-repair regression reproduced all 16 failures; the concrete C Trainer UFCS repair and four stale QA migrations precede the new full-source pass. Its original failed logs are retained. Likewise, earlier maintenance runs that exited zero with dirty postimages remain dirty-source observations.

Native mechanism tests use explicitly identified fixture credentials and custody. Neither source checks nor those tests establish ordinary deployment qualification.


Both own prior target caches were absent while the exact cc22 source, Cargo.lock, helper and tool pins were unchanged. Cold preparation v2 then failed before target creation, checkout or Rust execution because the V8 archive, verified minutes earlier, was missing; the cause remains unknown. The first bounded download from the crate's default Deno origin returned HTTP 404 and is retained as a failure. The sandbox variant was then verified against OpenAI's actual release 361445880 and assets 493388485 / 493388480. A single download from that exact published origin exited zero and recovered the original 29,366,352-byte archive, SHA256 `a35c75d1f26e6a983885a45b33490a4ebe54f05050568b32b89cfb421b30b583`; the original binding pin also matches. Complete source, lock and original binding metadata remained unchanged before/after recovery. Preparation v3 used a new empty own target and these restored exact bytes. Actual `just fmt` exited zero without changes, then scoped `just fix` ran from 12:37:30.736 to 12:49:03.069 UTC and exited zero with no postimages. Its 115,892-byte original log has SHA256 `f0f433ba913eb2a122094434d252a22ab9a2abda6cc20dc2103616a8f2665bf4`. The complete 14,995-path 4ab inventory was identical before/after, SHA256 `b5c9da7805bb23c3534a2ff2d0aa9505499e95fd710ec19c15991544dc3ca21b`; Cargo.lock is unchanged. The subsequent v2 diagnostic completed at 14:00:20 UTC with the same clean source inventory. No dependency, lock, 8 MiB stack, 60 s case limit, 500 ms evidence bound or source check was relaxed.

The C failure's actual diagnostic is `OwnerUnavailable("original learning evidence owner")` after 501.905628 ms, with the original server returning `Transport(DeadlineElapsed)`, before the test withdrew publication. The Deep trace reached fixture completion at 19.609 s, S at 23.878 s, ordinary C at 25.030 s, C attestation at 38.264 s, hot readback at 50.758 s and cold readback start at 50.886 s; nextest timed it out at 60.010 s. These are failures requiring repair, not withdrawal or cold-recovery passes. The actual execution log is 52,952 bytes, SHA256 `3a513e94ed2f5b3c36c4efaa2e5ea04d4678bcee897df8aaf0e71b7000cb58da`; the fresh 4,539-byte JUnit SHA256 is `11884390fb9f68b6521030101f7bbb40e6e2b626eb4f3222aa68043f738e79e5`. Root independently checked these complete files against the recorded digests. Append-only publication of these newer records is pending.
## Preserved evidence

The frozen 93-file package in `b29869e8` records its own earlier sources and observations. It is not rewritten to claim later outcomes:

[Progress and limits](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/b29869e856d08db1bfb066116a9c443376ccc57d/qualification/learn-evaluated-retention-037c/README.md) · [Machine-readable records](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/b29869e856d08db1bfb066116a9c443376ccc57d/qualification/learn-evaluated-retention-037c/PROGRESS.json) · [Artifact index](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/b29869e856d08db1bfb066116a9c443376ccc57d/qualification/learn-evaluated-retention-037c/ARTIFACTS.json)

The separately frozen 153-file follow-up package is published in `639f894e`. It preserves the failed 8faf gates, repair/format records and actual cc22 source/maintenance results. Its native state was frozen before the final focused failure; that historical pending state is not a native pass.

[cc22 evidence and limits](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/639f894e088cdc5b30b65ed3732dcaa0a2fbe004/qualification/learn-evaluated-retention-037c-cc22/README.md) · [Execution records](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/639f894e088cdc5b30b65ed3732dcaa0a2fbe004/qualification/learn-evaluated-retention-037c-cc22/PROGRESS.json) · [Artifact index](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/639f894e088cdc5b30b65ed3732dcaa0a2fbe004/qualification/learn-evaluated-retention-037c-cc22/ARTIFACTS.json)

The third frozen package is published in `90fd0f22`: 161 files, independently compared as additions only, with the complete failed native log/JUnit, original GDB records, scoped caller proof, withdrawn provider v1 and adopted v2, and actual seven-file formatting/publication evidence. Its local-freeze metadata describes the moment before publication and before new native validation. Neither earlier evidence package is changed.

[Native failures and repair limits](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/90fd0f22cfdfd6c839ef5ba9c694e9189c51e947/qualification/learn-native-failures-037c-cc22/README.md) · [Exact execution and repair records](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/90fd0f22cfdfd6c839ef5ba9c694e9189c51e947/qualification/learn-native-failures-037c-cc22/PROGRESS.json) · [Artifact index](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/90fd0f22cfdfd6c839ef5ba9c694e9189c51e947/qualification/learn-native-failures-037c-cc22/ARTIFACTS.json)

The complete failed native log is 183,732 bytes, SHA256 `4e0f58f42e4abb056868ddfb2c041d8caa9e543c5694de1de8dad15a36d529e1`; its JUnit SHA256 is `ea7c874639254904e3491e4c6abc3f187cd3ce11bbd4cf05ddc49314c4b492fd`. The outer command did not time out; two individual nextest cases did hit their original 60-second limit. These originals and the reviewed repair provenance are retained in the third package above.

The first ten published stages were checked against complete local Git trees. Later integration commits replace only independently hash-verified blobs on their exact parent trees. Independent GitHub compare confirms the final b298→cc22 repair is exactly two commits and eight reviewed paths. No later partial local overlay is presented as a locally materialized complete tree.

## Qualification and remaining implementation

**HOLD / Draft. Ordinary Adopt = 0; ordinary evaluated NoUpdate = 0; full daemon + Root cold recovery = 0; multigeneration = 0.**

The new S/C receipt mechanisms and original read-only S host do not yet close Candidate Selection/NextUse effect dispatch. That path still needs the evaluated Version/command continuation, actual role-host producers and the ordinary launcher/resident handoff.

The ordinary launcher also lacks the actual Q24 A PublishedTask/CURRENT capability producer. The existing Joint generation bootstrap cannot supply it; public descriptors or JSON cannot reconstruct its sealed owners. The existing Root issuer is real, but the deployment must supply the exact-purpose authorization and separately bound purpose lease required by the V3 resident profile.

Same-process publication and original-intent recovery are mechanism evidence. Full ordinary NoUpdate plus daemon/Root cold recovery remains the next qualification target. Positive Adopt and multigeneration remain gated on that closure.

## Follow-up checkpoints outside this PR

The PR head remains `a96d1b821d10ed3d9e99dd06c5141f9f242ae318`. The following work is preserved on separate branches. It has not been integrated into this PR or qualified.

- [Common Candidate checkpoint](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/9ed05677bf8b30eecc2af22d08001a45080cb440): the first coherent 105-file source/QA assembly (98 Rust and 7 QA), its complete original input bundle and source/guard provenance. This source tree contains remote C, S/C commands, Current, Root continuation, Version V3 and the five-file diagnostic repair. The later Version V4, Root progress/post-read and Training transaction layers are being combined in a new assembly. A separately labelled Current recovery plan is preserved as a new identity; the original plan was subsequently recovered and is being used for final integration.
- [Version and Root input checkpoint](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/807896d0b8b3dfb89b912f12f3ffeb9373f38550): exact frozen formatter inputs, patches, provenance and validated recovery tools. Actual isolated Rust 1.96 formatting of the later Version 12, Root 3 and Training 9 files returned zero.
- [Training source and guard checkpoint](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/34bbe04044ae724fcf8f7bd8596e2ef1a6463563): all nine complete actual Rust postimages, the original final caller delta and three QA files, the original 18-test scoped PASS log and its exact result. That PASS covers its recorded source set; it does not validate the later assembled cohort.
- [Runtime observations](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/df5fe6ef879491224359f63d075a33bc41e0067d): exact diagnostic requests, original failure output, complete archive-restoration result, actual persistent process observations and the clean maintenance result.

The primary execution environment became unavailable and later recovered. Six key frozen assembly, manifest, caller and proposal files were reread after recovery; every SHA256 exactly matches its original. The original Version/Root/Training outputs and final guard inputs are intact. Final assembly and row-level caller/QA integration are continuing from those original inputs; historical failed reads and recovery attempts remain separate.

### Four-case diagnostic: exact 00378 source

The diagnostic source is `00378c2e33ede95f4a93bf96f6d87b3bd415d337`, a separate five-test-file child of 4ab. Its first request failed before checkout, fmt, fix or native because the original V8 archive path was missing; **zero cases executed**. The complete 1,887-byte failure output is retained. A read-only check found the original completed download at the exact 29,366,352-byte / `a35c75d1…b30b583` pin. A create-only copy then restored that original path. Its complete 3,094-byte terminal result has now been read and independently checked, SHA256 `562efbdc2657f9c1998933fb5d7165bc62bcf6b567574b7c3af5ca35a91f46d8`: actual exit 0, full source inventory identical before/after, original binding/environment unchanged, no download. The reason for the original disappearance remains unknown.

The v2 request also executed **zero cases**. It exited 1 at the original target-directory/owner/symlink admission assertion before checkout, fmt, fix or native. Its full 1,486-byte terminal SHA256 is `d2166e4b3f7a92081acfcbad62159ab06c8b3324e208bb33dec9e834d47e4914`; that conjunction alone did not identify which condition failed.

The v3 request first records the exact target state and validates its original parent and ownership. It actually observed the target absent, then created only that original empty task-owned target; it removed no existing data and changed no existing metadata. Both bundled maintenance/diagnostic drivers, source/tool/environment pins and the original target path remain unchanged. The four named cases retain 8 MiB stacks, 60-second case limits, two threads, zero retries, and the original 128-frame / four-connection / 500 ms evidence / 300 s session bounds.

**Actual v3 maintenance is clean:** `just fmt` exited 0; `just fix -p codex-hepta-agentd --locked --offline` ran from 16:41:48.034916 to 16:53:12.602534 UTC and exited 0, with zero postimages and an empty patch. All 14,995 source files are identical before/after, inventory SHA256 `8883c1997c9248a93d1ff75284f6e31f66730e0d0a10adda07ffb5361ebc10fe`; Cargo.lock is unchanged. The exact maintenance result was read and checked in full. The persistent job has now begun compiling test helpers. **The four-case terminal native result has not yet been observed.**

This diagnostic validates only its exact source if it passes. Full source/caller/native gates on the combined cohort remain unrun. Ordinary evaluated NoUpdate, ordinary Adopt, full daemon plus Root cold recovery and multigeneration qualification remain **0**.
