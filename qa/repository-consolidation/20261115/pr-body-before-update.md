## 2026-11-15 audit checkpoint — work in progress

Current head: [a5ca2bae54d0](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/a5ca2bae54d0bca65e72f1920f8157f44b5a4fb8); exact tree `ef85add3bd3d565d4e002cab2b662d461bb1ef9f`.

This checkpoint removes only the inherited BuildBuddy `VISIBILITY=PUBLIC` and incorrect upstream `REPO_URL` overrides, with original CI evidence. GitHub currently reports this repository as public; that is separate from BuildBuddy invocation access. Historical invocation permissions were not changed or anonymously verified. Remote services and test gates remain enabled.

The preceding Memory/ACT/inference checkpoint remains included. Learning, Native Memory, HCSN, Control-WAL and UI integration are being audited locally and on native hosts; their newer changes are not in this published checkpoint. CI for this head must be assessed separately from earlier scoped tests.

Full convergence is **not complete**. Main is unchanged, no branch has been deleted in this pass, and the 26 newly added HIA branches remain excluded.

---

## Current status — 2026-11-14 18:05 UTC

**Consolidation is not complete. No original branches have been deleted, and main is unchanged.** Public review HEAD remains `a537df7c041851b47a2d9255952e34eb91c6dfce`, tree `b3a4e8b21214cd487f9785bc983ff4446b2d9452`; main remains `732e934ba496d90fbe042b8d41d479ef901643e5`. Private audit, repairs and graph preparation below are not yet published ancestors of this PR.

### Public checkpoint and actual CI

The seven ordinary commits since `91d312b739bb2ead8a47920edf4f4113f4fbf40d` contain 27 reviewed paths: CMSG platform typing, the normal-main Cargo/Bazel test helper, musl O_PATH directory cleanup and the four-path E0/format component. No cab5/26a experimental ancestor was imported. Component GNU tests and actual Bazel target discovery passed; Bazel discovery is not a compile claim. Composition receipt `5f42c26ada0ee927a2bcdad233918778729407364aadbbbcee6456148596143d`, exact net-delta receipt `16baaacd1d1d0c8acb109ba5085b78a2ee460b587937148138f86e4342e6cd07`.

Required blocking CI run `43614046949` is **failed**, not pending or green: GNU passed; musl and both macOS variants failed. Windows shards/fan-in, Clippy, release and repository-build jobs passed. Required fan-in job `132514586613` failed. Architecture run `43614046913` and codespell passed. Those jobs execute the PR merge tree equivalent to the public tree; none validates the larger private composition.

E0 run `43614046934` remains a real semantic failure: 2 of 768 finite features lie outside [-8,8], with min -16.257877349853516 and max 16.055374145507812. No clamp or threshold weakening was applied, and accepted/production stays false.

### Private repairs and validation

- The two musl fixtures now use an independent statx birth-time oracle and actual raw O_PATH opening. Production code is unchanged. Normal gates passed; combined GNU/musl owning validation is still running. The first GNU exec run preserved all 116 cases: 114 passed and 2 failed before the tested operation because the auditor's long temporary socket path exceeded SUN_LEN. Only those two original cases will be rerun with a short independent TMPDIR after the current controller finishes. GNU agentd also returned nonzero and its exact failure is being classified; no result is concealed or relabeled.
- Intel drain preview now classifies NotConnected as an unacknowledged `Ok(false)`, preserving continued polling and every strict response/identity/generation check. Root independently verified the inverse restores the original source and all three socket tests remain byte-identical. Two new error-classification tests await normal owning validation. This does not claim to fix the separate ARM failure. Peer `deac04513fc9c26524d66a753101d202c4642722daeba90994eacd610401b878`.
- The new memory precreation helper had a verified restrictive-umask defect: the exact old helper created mode 0000; the repair creates mode 0600 using only the newly created descriptor. Existing files are untouched. Both original WAL/SHM and existing-file tests retain their identities/assertions; a child-isolated umask regression was added. Actual helper negative/control runs are preserved; full store/SQLx owning validation remains pending. Peer `35cdd6fd701ee4b1fe1e7301d1a8890f5ec1b81e896fb828bced0ad28a21f901`.
- Infer lifecycle, shared manifest and Neuron validation-view repairs remain private. Actual compile failures were preserved and fixed narrowly: four RuntimeConfig/ShadowConfig mismatches and one test-only AdapterStatus import. Normal default/experimental fix, format/check and diff check now pass. The five-path normal autofix was independently reviewed: only two final-use clones are removed; other changes are import/layout formatting. Frozen child `d0eba345958b4ecdada38acb5960919571e9f374` is now in non-fixing strict and owning validation. Peer `a80a7bbd7175589d09711fd64c5f86b6a9da9b00a9c0a3d7a49f5aeaea9af0f3`.
- HCSN moving-boundary union passed all 63 unchanged original methods after the negative-drift cancellation repair. Torch BP passed 32 original methods plus one new finite-gradient regression, with the old NaN-gradient counterexample retained. Fixed/local/compiled original suites passed 9+4+5 methods after a real Cython build; a controller summary-parser error is preserved and corrected by rereading the same immutable logs, without rerunning tests.
- The latest bond finite-return repair passed 85 preserved original methods plus 4 new methods (89 total). The old code fails the 8 new subcases; optimized Python passes the 4 new methods. P1 sign-flip accumulation guards passed 15 original plus 2 new methods, preserving the old 3 failing subcases and exact finite formulas/enumeration/Holm rules. An additional 57 unchanged numerical methods and all 5 distributional replay methods passed. These overlapping suite counts must not be summed as unique coverage or scientific/production qualification.
- Source review now has exact path/OID ledgers for the HCSN production variants, with predecessor variants and selected postimages separately recorded. New 44-variant ledger `412182b03d61536f062839f2ed1f451bdc29a15a7dac2d97f911dd80caea4726` supplements the prior 33 and earlier/peer reviews. The remaining 337-delta documentation, test and data disposition is still being joined; metadata-only entries are not marked semantically approved.

### Graph coverage and remaining gates

Private head `3682e70e2c9ba0f5811b0fcfe88bf9ca32bea723` covers 1,306 frozen unique tips / 1,382 names. These are graph counts, not full audit approval. Its complete tree has 37,629 paths / 33,888 blobs with no missing tree objects; historical/conflict object hydration continues. The 646-attempt retry finished with 168 true conflicts and 478 infrastructure/missing-object cases; no new merge success. Original failure records remain. All 27 selected HCSN original heads were freshly previewed against 3682: every preview has real content conflicts and zero missing objects. Exact, reviewed per-path resolutions are required.

Before final merge and ancestry-qualified branch deletion: finish semantic conflict admission, complete normal owning and required combined CI, resolve outstanding E0/macOS/runtime findings, take a fresh live branch inventory and verify every deleted tip remains reachable. There is no blanket ours/theirs resolution, force push, history rewrite or test-budget weakening.

---
## Historical checkpoint: 91d312b


The review branch now points to `91d312b739bb2ead8a47920edf4f4113f4fbf40d` (tree `7950b4d5a51edd8023db0815bcca29d794b24838`). This is an ordinary fast-forward from `d226b94e4679322e6a60e515d8f493cb9005c4e0`. The remote `main` remains `732e934ba496d90fbe042b8d41d479ef901643e5`; no original branches have been deleted.

### Changes in this checkpoint

- Assemble the reviewed source-volume, vendor-format/provenance, file-descriptor test-isolation, and musl compatibility fixes through ordinary parent-preserving merges. Preserve the existing large-blob threshold and the original test assertions and numeric limits.
- Apply the normal formatter's single blank-line change to `MODULE.bazel`; the module lockfile is unchanged.
- Verify the exact combined postimages against every component. The net change from the previous public head contains 2,800 paths: 72 added, 2,370 removed, and 358 modified. Source-volume replacement and provenance are included in the reviewed component evidence.
- Resolve every newly reachable Git object for this increment: 635 object rows, zero missing. The final tree contains 16,565 paths.

### Verification and remaining qualification

- The normal final-head command `just fmt --check --base 732e934ba496d90fbe042b8d41d479ef901643e5` passed with exit 0 in 420.719 seconds, with no stdout/stderr, tracked-file drift, index drift, or head change.
- Exact component tree identities, ancestry, frozen branch coverage, and remote before/after refs were verified. The original checkout remains clean and unchanged.
- Musl compilation and native execution of the revised file-descriptor tests are **not yet qualified**. Required GitHub checks are being evaluated for this exact new head; this checkpoint does not claim that they all pass.
- A separate six-package validation on the older `32bfdeca218f7e7e5f633234b0f6d838963d2916` source completed with 1,398 passes and three timeouts out of 1,401 executed tests. Those results do not qualify this head. The three failures are being compared against current source without increasing test time budgets.

The original frozen inventory contains 7,174 branch names at 6,787 unique tips. This public head contains 578 of those names at 519 tips. Additional family `1657238edcc0793bc353c931f9ca445ef992315c` and its review fixes remain private pending completed audit and final composition; they are not included in these public coverage counts.

Evidence identities: final-head format receipt SHA256 `c5fe5b08750a5d5bb584d06b47c504749b1501ec120e620df5874a782a21dded`; exact composition preflight `7c932f89eaaf0e7618c3f8d97a8dc433b5fb85c4b8984f9dc32c3a896074ad74`; successful public update receipt `f3ede6b88b64af3d5d57b9260960498c3b64bf97375b37d8b41ef800503e6b60`.

The sections below retain earlier checkpoint history. Their older head-specific results are not assertions about the current head.

---

## Current convergence checkpoint — 2026-11-14 10:03 UTC

This PR consolidates reviewed branch histories and repairs defects found during the repository audit. The requested outcome remains one retained branch, `main`. **The full audit, validation and branch convergence remain incomplete.**

### Published source and branch accounting

The integration branch and GitHub PR API both identify **d226b94e4679322e6a60e515d8f493cb9005c4e0**, tree **4e28353051a86b17f4e12b69ae4a2d6a2378aee2**. Native Git performed an ordinary fast-forward from **83e1c6fc47bfc7277100534cd0994a547028cb11**. Main remains **732e934ba496d90fbe042b8d41d479ef901643e5**. The original working checkout remains clean at f4e83e693982aca41c35fed5549deb6b8653beb0.

An independent ancestry walk against the frozen inventory confirms **519 distinct tips / 578 branch names contained**, out of **6,787 tips / 7,174 names**. This repair increment adds zero frozen tips. **6,268 tips / 6,596 names remain outside the published ancestry.** A fresh remote inventory is required before final cleanup. **No source branch has been deleted; main has not been merged.**

The seven ordinary component merges retain their histories. All new-history objects are readable, with zero missing objects. The exact net delta from 83e is **205 paths: 9 added, 180 removed from their former tree locations, and 16 modified**. All 180 removed paths remain byte-for-byte in the two verified source-custody containers; their original Git history remains reachable.

### What this increment changes

| Change | Result and validation boundary |
| --- | --- |
| Linux musl Bazel selection | Selects the actual `@rules_rs//rs/platforms:x86_64-unknown-linux-musl` target after configuration arguments. The old nominal musl lane actually built GNU. All 31 offline wrapper tests and 18 actual workflow-argument controls passed; real musl compilation/testing is pending on this head. GNU arguments are unchanged. |
| macOS Bazel launcher PATH | Removes exactly one leading `.:` prefix injected by Bazel when `BAZEL_TEST=1`, preserving every original caller PATH entry. All 22 Linux and 14 macOS fixture processes passed; 28 actual earlier CI spawn-input bindings were inspected. The Windows launcher is unchanged. Real macOS Bazel CI remains pending. |
| Preserved source data | Two inert gzip/USTAR containers preserve 180 historical sources plus five original control files: 185 members / 2,520,140 bytes. Every member was independently rechecked against original Git objects and modes. No recovered source was executed or research/runtime qualification inferred. |
| Required custody checks | Adds the guarded verification block to the existing required repo-checks job. Sixteen reader tests passed with zero skips, both actual containers verified, and 31 companion documents verified. Existing permissions, required fan-in and budgets are unchanged. |
| DNS fixture determinism | Uses per-test resolver fixtures with an equivalent test-only type alias; production resolution and original two-second budgets are unchanged. At the pre-alias repair source, three complete owning suites passed 895/895 tests with three existing skips, zero retries and exact inventory. Final alias lint/fix and normal formatting passed; no full-suite pass at the combined tree is claimed. |
| Matrix timeout diagnostics | Adds bounded phase/timing observations while retaining all seven assertions, five await sites, 10,000 iterations and original budgets. The original timeout remains unresolved pending the six-package validation. |
| Vendored endpoint formatting | Reformats the same two imports and updates patch provenance; endpoint behavior is unchanged. |

The exact published tree passed normal `just fmt --base 83e1c6fc47bfc7277100534cd0994a547028cb11`, its `--check` counterpart, and `git diff --check`, with a clean tree before and after every step. **This validates the integration delta; a full-main formatting pass is not claimed.** Separate full-main work has 297 vendor-format paths under review and one more mixed-patch source-data collection requiring byte-preserving container treatment.

### Actual CI status and outstanding failures

At the previous public head 83e, every Architecture job passed, including Architecture required. **CI required failed**: Windows shard 4 and both macOS Bazel jobs failed. GNU Linux passed. The earlier nominal musl success is not accepted as musl validation because it used GNU.

Outstanding original failures remain recorded: Windows multi-agent communication logs, macOS agent drain/qualification, Intel supervisor and transport deadlines, the memory lifecycle assertion, and E0 Q24 out-of-range rejection. Tests that only passed on retry remain flaky. No budgets, assertions, exit-status semantics or required checks were relaxed to hide these results. New d226 workflow results are pending.

A fresh six-package native run at **32bfdeca218f7e7e5f633234b0f6d838963d2916**, tree **a2dbbdc5e0d36feec688bd99c6642ebed260dff5**, completed normal scoped fix, normal formatting, format check and diff check with zero source changes. The host rebooted during test-helper compilation. That run is interrupted; **test suites had not started**. Recovery preserves original state/logs, verifies the source and cached inputs, resumes helper preparation, and retains the normal test driver, zero retries and fresh JUnit attribution.

### F16 and remaining audit

The native-memory family can add 278 tips / 289 names but is not in this publication. Its 1,247-path integration has 43 conflicts. The product owner read all 141 net product changes and produced private resolutions for 35 product conflicts, retaining current transaction, cancellation, recovery, dependency and authority checks. Final composition, formatting, compilation and tests remain.

All 400 root QA/text inputs were checked against original Git identities; 77 Python files parsed and 237 JSON/JSONL inputs passed strict structure checks. These are static checks, not scientific qualification. Two historical archive verifiers lost their assert guards under optimized Python: eight original false acceptances were reproduced, revised guards reject those corruptions in both modes, and a portable 28-invocation regression passed. Five NumPy readers need checks before allocation; two probes need binding to verified bytes or a final identity recheck. Private repair fixtures pass; original model/training suites have not been claimed as passing.

New workflow drafts preserve bounded PR mechanism checks and require explicit manual opt-in for real checkpoint downloads, training or model execution. Operator acceptance of model terms defaults false. Skipped model work is not qualification. Review and adoption remain pending.

Security work is incomplete: the 83e lockfile reconciliation retained 32 medium/low advisory range hits across nine packages. Range membership is not proof of reachability. Dependency upgrades and owning validation remain required; alerts have not been dismissed merely because they fall outside a repaired path.

### Retained verification identities

- Frozen inventory SHA256: `22a611db9bfb6899e82179d93e4c343b4f991ff8f011bfd4c00ac0e9723d9d62`.
- v17 assembly receipt SHA256: `372cc6c2d26a2714382419f6127e004979d06904b06bb3bf17eb6464e314baee`.
- Exact-tree normal-format receipt SHA256: `a0a7f7de2e3098f1d0fd9823d38c297dd41a615b1453656cba452cfcacd2197e`.
- All 205 postimages/modes/deletions ledger SHA256: `83c2f6a31c1abcb8af35e77a437f05ecb975a8052d4f725991ed66bc4af73cac`.
- Publication and remote-ref readback receipt SHA256: `b3d2a2431b00b0765640cec93bd828f046cce06fca03938130ba3697444b922b`.

The prior checkpoint text and raw receipts remain retained. Final main merge and branch retirement wait for complete ancestry coverage, resolved findings, required checks and fresh remote-tip reconciliation.

<details>
<summary>Historical PR checkpoints and original evidence (through 03ec884b)</summary>

## Current convergence checkpoint — 2026-11-14

This PR consolidates reviewed branch histories and repairs the source, dependency and CI defects found during the repository audit. The final goal is one retained branch, main. **The full audit and branch convergence remain incomplete.**

### Published state

The integration branch and this PR now point to **03ec884b593e870e8c07f53815e62a387bd50170**, tree **e6058539061236f7282b01da37fa3f0afd8735ee**. The update was an ordinary fast-forward from 2bd5f01eec66707bccee6fff9cf59b04e56f4462. Main remains 732e934ba496d90fbe042b8d41d479ef901643e5.

An independent ancestry walk against the frozen inventory confirms **447 distinct tips / 504 branch names contained**, out of **6,787 tips / 7,174 names**. The remaining **6,340 tips / 6,670 names** are outside this published ancestry. All source branches are retained. The observed main protection requires **CI required** and **Architecture required**, with strict up-to-date checks; protections remain unchanged.

### What this increment changes

- Merge the reviewed first117 branch group using ordinary parent-preserving merges and explicit semantic resolutions.
- Repair active source/receipt bindings, Python error exits, Windows SID lifetime contracts, scoped authorization and login behavior, and the queue fixture's authorization/claim ordering.
- Update dependency locks through their normal package managers; add the missing context-compiler property-test dependency and retain the original property tests.
- Repair the SDK's Zod conversion against its installed major version, preserving conformance failures as separate evidence.
- Preserve original historical workflows and source containers with exact source bytes and Git modes, while giving current research and native-SDK entry points explicit qualification boundaries.

### Validation and limits

At this exact published head:

- **20 owning Rust packages: 8,918 executed tests passed, zero executed failures.** Nextest separately reports **174 skipped tests under the unchanged original configuration**; these are not executed passes. The original JUnit SHA-256 is b8a1c366f2a82413a50b669eb3c693e2f935f784ad8212f6af596810dae9a964. The command uses the ordinary just test wrapper, locked dependencies, zero retries and four test threads.
- **Default control-UI unit profile: 33 tests passed**, including the five original RoomScreen IME cases. This does not establish native OS input, pixel rendering or package deployment qualification.
- The normal Bazel lock update/check, formatting and whitespace checks passed for the published source/lock repair stack.
- **Native-SDK control-UI unit profile: 64 tests passed**, including the same five original RoomScreen IME cases, with zero skipped cases in its original Nextest summary. The original JUnit SHA-256 is 56acf58d40b5cacdeb3176a39a809476cd76de52415821769a91d03302d09365. The staged inputs, including the two original native resource manifests, are bound to this source. A report-name bookkeeping correction was verified against the original fresh JUnit without rerunning or relabeling tests. This remains a unit-profile result; native OS/IBus input, pixels, packaging and deployment are not qualified.
- **Native lifecycle example build passed** using the original locked Cargo build. The example was not executed.
- The **full-workspace ordinary just test invocation is running** at this frozen source, with the original configuration and zero retries. Scoped fix/fmt completed in an independent candidate; its source changes and the owner-lifecycle repair remain private until reviewed and validated. A successful fix command is not being reported as strict Clippy success.
- The standalone Servo owning invocation exited during dependency retrieval after SSL/network errors. Its four tests did not run. The pinned revision and original source remain unchanged; no result is being relabeled as a pass.
- **Architecture required passed on this exact head**, check 132310211894, completed 2026-11-14T03:08:39Z. The exact **CI required** check has no final result in the current observation. Actual component failures, including the GNU owner-lock lint and contract/caller source guards, remain visible. Repairs are being tested in independent candidates; no CI protection or test assertion has been relaxed.
- The standalone optional E0 research job preserves its actual rejection of input outside the fixed Q24 domain. It is outside the observed required workflow closure. Earlier 2bd/7e Windows, macOS, capacity and CodeQL observations remain historical and do not qualify 03ec.

Earlier exact-source checks in this published repair stack remain separately scoped: 620 Python test executions across 33 successful invocations; 89 browser Node tests; 11 fake-CDP control tests; and the SDK's 47 tests/type checking. The SDK conformance gate preserves its known transport and reviewer failures rather than reporting universal protocol success. These are not a whole-repository or real-model acceptance result.

### Remaining audit

Later cumulative sources, compact-engine owner-fence repairs, Neuron history reconciliation, research-reader snapshot repairs and additional workflow fixes remain isolated review candidates. They have not been silently adopted into this PR. Historical experiment artifacts currently returning HTTP 404 remain unavailable unless an exact pinned-hash copy can be verified. The four workflows depending on those missing archives are part of the later candidate review and are absent from this published head; they are not being described as current required-check blockers.

Branch removal will follow final semantic integration, required validation, fresh remote inventory and proof that every retained source tip is an ancestor of the final branch. No forced ref update, protection bypass, blanket conflict choice or branch deletion is part of this checkpoint.

<details>
<summary>Earlier checkpoints and their original results</summary>

## Historical published checkpoint — 2026-11-13 22:30 UTC


Published head: `2bd5f01eec66707bccee6fff9cf59b04e56f4462`  
Tree: `1528f51bade8b6d9160c2faa6b6d634c870ba91e`  
Main remains `732e934ba496d90fbe042b8d41d479ef901643e5`.

**This PR is unmerged. Full repository audit, branch convergence and validation remain incomplete.** The integration ref advanced by an ordinary fast-forward push, without forcing refs or changing branch protection.

### Changes in this candidate

- Preserve the independent evidence history with a real two-parent merge, then relocate its 166 original files with exact bytes and Git modes. All historical failures and incomplete qualification evidence remain recorded.
- Repair 23 fallible test-helper accesses, retain queue child stderr, and correct the two workflow formatting failures.
- Split memory unit tests into four deterministic Bazel shards and disable automatic retries for that target. Each action retains its 300-second timeout; the aggregate maximum action allowance changes from 300 to 1,200 seconds. This is not a proven timeout fix.
- Split the existing 23 workspace-write approval scenarios into two disjoint 12/11-case tests, preserving every scenario and assertion. Each nextest watchdog remains 60 seconds; the five prior group-test watchdogs become six. Add phase/elapsed diagnostics.
- Add app-server startup phase and child-state diagnostics without changing waits, deadlines or assertions.
- Replace the scheduled model-data branch/PR writer with read-only repository permissions and a reviewable change artifact. The existing schedule and automation guard remain; the current repository-variable value is unknown, so this is not a claim that the old writer was currently running.

### Validation at this exact head

Native validation v4 is running against the clean head/tree above. Format check, diff check, normal Bazel lock check, helper preparation and pre-test helper verification have passed. The ordinary eight-package `just test --locked --retries 0 --test-threads 4` run is in progress. A separate memory-package invocation and the lifecycle-example build follow; full-workspace tests are conditional on the earlier stages passing. No final native or remote CI success is claimed.

The 7e results below are retained as historical evidence, not relabeled as results for this candidate. Newly prepared memory failure-message diagnostics and first117 repair/archive previews are not included in this head.

### Actual branch accounting

Native ancestry against the frozen inventory confirms **336 distinct tips / 393 branch names** contained out of **6,787 tips / 7,174 names**. **6,781 frozen names remain uncovered.** Private cumulative experiments are excluded from these published counts. No branch from the frozen inventory has been deleted.

The push also reported 157 default-branch Dependabot alerts (3 critical, 69 high, 70 moderate, 15 low). Those are GitHub's default-branch totals, not verified candidate vulnerability counts; exact alert and lockfile comparison is in progress.

---

## Historical validation at 7e — 2026-11-13 21:47 UTC

Published head remains `7e8d50174fdff2b0c930f0d4cc9ea84f3080b124`, tree `b10a4544323a8c1b1aa30e9c818cc2582af54449`. Main remains `732e934ba496d90fbe042b8d41d479ef901643e5`. **This PR remains blocked and unmerged; the full audit and convergence are not complete.**

### Exact-head native results

- The ordinary owning-package `just test --locked --retries 0 --test-threads 4` invocation completed with **7,538 executed cases: 7,532 passed and 6 failed**. The original JUnit SHA-256 is `e656d6de2b5ab6917b697c9600f023eed531c598a15fbfb4a68f4ec4caf8505b`. Its report contains no skipped testcase entries, while nextest's original summary separately reports **163 skipped tests**; these omitted cases must not be described as executed passes or as zero overall skips.
- Five failures were app-server startup/handshake/address waits. The sixth was the workspace-write approval matrix's existing 60-second aggregate watchdog. Original failures and complete logs are retained; a common resource cause has **not** been established.
- The native lifecycle example **compiled successfully from the project directory with the repository-pinned Rust 1.96.0**, taking 125.45 seconds. It was not executed. The first validation-driver invocation used the repository root and selected default Rust 1.95.0, failing the dependency MSRV check before compilation; that original result is retained separately. No MSRV bypass, dependency change or source change was used.
- Source head/tree/clean status, prepared helper identities, and the official V8 archive/binding identities remained unchanged across the native test run. Format, diff and Bazel lock checks passed. Full-workspace execution remains deferred after the owning-package failures.

### CI and next candidate

The [CI run](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43499333017) still contains failures. The newly completed Mac Intel job reports **18 failed targets, including 3 timeouts**, plus 3 separate FLAKY targets. A running child without a ready endpoint is not evidence of a crash, and these observations alone do not establish overload.

The private next candidate contains reviewed Clippy-helper, retained-stderr and formatting corrections, plus the original unrelated evidence branch merged with both real parents and its 166 files relocated with exact bytes/modes preserved. Historical FAILED/TIMEOUT results remain failures; the archives confer no product or scientific qualification. Memory unit tests are proposed as four deterministic Bazel shards with automatic retries disabled: each action remains at 300 seconds, while the maximum cumulative action allowance changes from 300 to 1,200 seconds. This is an execution-structure change, not a proven fix or passing result. These private changes have not been published or validated as a complete candidate.

### Branch accounting

The published head contains **335 distinct frozen tips / 392 frozen branch names** out of **6,787 tips / 7,174 names**. **6,782 frozen names remain uncovered.** Larger private merge experiments and audit previews are not counted as adopted work. No branch from the frozen inventory has been deleted.

---

## Previous checkpoint, retained as historical context

Published head: `7e8d50174fdff2b0c930f0d4cc9ea84f3080b124`  
Tree: `b10a4544323a8c1b1aa30e9c818cc2582af54449`

This checkpoint integrates **27 further frozen branch tips / 28 branch names** through ordinary history-preserving merges, applies reviewed source and fixture corrections, and makes remaining failures more diagnosable. **Full repository audit and single-main convergence remain in progress.** Main is still `732e934ba496d90fbe042b8d41d479ef901643e5`; this PR has not been merged and no branches from the frozen inventory have been retired.

### Changes since e24

- Integrate the reviewed A–G groups: source-custody and research-readiness tools that retain HOLD/SHADOW_ONLY boundaries; durable automation/learning owner checks; the native lifecycle qualification example; and the rustls lower-bound alignment with the already locked version. The lifecycle example still requires compilation and has not been executed.
- Integrate H/I/J with explicit module/test organization repairs. The operation-host correction keeps **every destination error with an absent observed receipt quarantined**: an error label alone cannot prove an effect did not commit. The real-owner regression preserves the current limitation that a later original receipt cannot release immutable quarantine. This is a conservative correctness boundary with an availability cost, not completed late-receipt recovery. The I/J receipt-sequencing APIs do not establish external authentication, durability, or execution authority.
- Repair the Guardian test's event-versus-state publication race, restore the original normal RPC timeout after the Neuron fault-injection phase, and decouple the circuit feedback fixture's logical event clock from actual SQLite I/O. Original effect/replay assertions remain.
- Correct the Windows fixture's second-resolution lease quantization. For fractional mint times, rounding up extends the former encoded expiry by one second; this is an explicit fixture timing correction.
- Preserve all 128 MCP matrix combinations as independently discovered cases instead of two 64-case aggregate tests. Case bodies are unchanged; each case now receives the existing per-test watchdog. The aggregate test lifecycle therefore changes.
- Add bounded failure context for exec-server, user-message recording, issuer, plain-host and Wine failures, without claiming their unresolved causes are fixed. Correct the CLI codespell comment.

### Validation and evidence boundaries

- Candidate format check and diff check: **passed**.
- Normal `just bazel-lock-update` and `just bazel-lock-check`: **passed**, with `MODULE.bazel.lock` unchanged. The initial failed attempt used incomplete global external-dependency cache entries; its original logs remain preserved. Recovery reused this task's existing isolated cache configuration without changing source or trust settings.
- Current native validation: **in progress** on this exact source. The affected eight owning packages run through ordinary `just test`, zero retries and four test threads. The native lifecycle example will be compiled separately; the complete workspace suite follows only if owning tests and that build pass.
- The previous `4e8d0f1c` run remains **8,039 passed / 8,048 run, 9 failed**. Those are historical results, not results for this head. Seven original JUnit reports were retained; the earlier CLI result has original logs but no recovered JUnit.
- All 29,036 entries in the reused native build cache were verified against the relocated copy, including file SHA-256, metadata and symlinks. The original lookup path is preserved. No running Rust job was killed, and the unrelated concurrent build was left untouched.
- Required remote CI and Architecture checks must pass on the candidate before main integration. Scoped lint fixing and final formatting are still pending. No protection bypass is requested.

### Actual branch coverage

The frozen inventory contains **7,174 branch names / 6,787 distinct tips**. This published head contains **392 names / 335 tips** in its real ancestry, up from e24's 364 names / 308 tips. **6,782 names / 6,452 tips remain uncovered.**

Separate cumulative merge experiments are isolated, have not been adopted, and are not counted as coverage here. Their static review has already found compile/linkage defects, misleading evidence-validation claims, scheduled writers targeting old branches, and archival build-discovery problems. Clean Git merges alone do not qualify them for main. Branch retirement will require verified main containment, fresh tip checks, and resolution of open PR head/base dependencies.

<details>
<summary>Previous checkpoint and original validation history (historical, not current-head qualification)</summary>

## Historical audit checkpoint — 2026-11-13

Published head: `e24ecbc2a43839b935009d3ce29ceb6c9f818be1`  
Tree: `44b819197c559432d4bbc2e2f7c983d466b43ba8`

This increment repairs reviewed CI fixtures, improves failure diagnostics, and preserves three further historical workflow branches through ordinary merges. **The full single-main convergence is still in progress.** Main remains `732e934ba496d90fbe042b8d41d479ef901643e5`; neither protected-main integration nor final branch retirement has happened.

### What this increment changes

- Apply the actual Rust formatter and Ruff output from the failed checks. The Python formatting preserves its AST.
- Give the PR41 handoff verifier an explicit retained-handoff mode for repository-wide integration, while preserving the exact default scope, immutable bundle files, path validation, clean-source checks, and negative tests.
- Pin the original ordinary-daemon evidence archive by its exact bytes and SHA256 in the existing blob policy. The historical source and HOLD outcome are unchanged.
- Repair Windows fixture ownership and cold-reopen ordering using the original control port and checked shutdown; retain the deliberately unavailable legacy-sandbox refusal and protected-path assertions.
- Correct the executor-skills full-read fixture, the exact-clock doctor fallback fixture, and the fork-history snapshot ordering without weakening their original assertions.
- Keep websocket heartbeats serviced while the Noise failure-budget fixture waits for validation counts. Preserve the eight-failure limit, original deadlines, strict Reset checks, and checked completion reason.
- Add bounded child-startup/forwarding diagnostics and initial HTTP phase diagnostics. The two unresolved core hangs now write fixed phase markers directly to stderr so process termination does not discard libtest-captured progress.
- Preserve the storage-maintenance, trusted-desktop-probe request, and policy-evidence workflow histories with their original trigger/source restrictions. No maintenance action or probe was dispatched. One trailing blank line in the policy workflow was removed after the original whitespace check failed; parsed YAML is identical.

### Exact-source validation

The native validation source is separately frozen at `4e8d0f1cf7c151bd6bf060da1a1f15ac861a40c1`, tree `7f22cd04a69dffeffa1bb155fe396d780a5ee1ca`. The published child adds only 58 diagnostic lines in two existing core tests. Native results for the parent are not reported as tests of that child.

On the frozen native parent, scoped format checking, Git whitespace checking, handoff self-tests, and the actual main-to-head retained-handoff check passed. All eight helper packages were freshly prepared and verified from this exact clean source, with the original paired V8 hashes checked. The complete CLI package `just test` command exited 0; the remaining owning packages are running through the repository recipe with locked dependencies and zero retries. Full-workspace validation and final scoped fix/format remain pending.

The normal Bazel lock-update and lock-check recipes passed on the exact doctor dependency repair `cf7e9356`; the lockfile bytes stayed unchanged. That scoped result does not replace the final candidate's required checks.

The original macOS Intel run ended with nine FAILED and four TIMEOUT targets. The new diagnostics do not prove those failures resolved. The possible terminalizer failed-closed wait path is documented, but the old log does not identify the actual phase of the two 900-second hangs; no production fence or watchdog budget was changed.

### Whole-repository convergence status

The latest frozen inventory contains 7,174 branch names, 6,787 distinct tips, and 4,342 open PRs. Git ancestry of the native parent covers 364 names / 308 distinct tips from that inventory; 6,810 frozen names remain outside it. The published diagnostic child adds no frozen branch tip. Thousands of branch dependencies and source conflicts remain under review.

No additional branch was deleted in this increment. Remaining retirement requires actual containment in protected main, fresh expected SHAs, and handling dependent PR bases. The real `CI required` and `Architecture required` checks remain required, with no administrator bypass. Historical FAIL, HOLD, UNKNOWN, shadow-only, and non-promotion boundaries are retained.

<details>
<summary>Historical work log and earlier exact-source evidence</summary>

## Why

The repository has thousands of divergent branch tips and deeply stacked pull requests. The frozen inventory contains 7,185 refs, 6,768 distinct tips, 2,481 maximal unmerged heads and 4,324 open PRs. A recent large tree alone does not retain all valid work.

This PR makes one reviewed convergence concrete. It starts from #6284, preserves the frozen main history, and combines additional source fixes using ordinary merge previews and explicit conflict resolutions. At the initial ab5 stage its ancestry covered 360 of the initial refs, including main; the recovery checkpoint adds the reviewed histories described below. The remaining branches are still under review; this PR does not claim completion of the single-main task.

Current integration checkpoint: `d28b7223aa4cea5aca6fb76c3a2dff2b0b3906f2`, tree `9333f8eed70bfc55eaf7522f1896107f51447aa4`. Following the eighteen-head and six-documentation rounds, six further policy/history heads are preserved by real ordered two-parent merges at `39dfa6b4`. Reviewed workflow resolutions preserve manual-main read-only availability checks and useful incoming observations; archived learning evidence keeps its original source scope. The latest single-parent commit corrects only the start-paused setup of two Guardian deadline fixtures, preserving every original assertion and budget. It has not yet passed native regression.

Native evidence remains tied to frozen `0427bface`: preparation/Bazel/helpers passed; Agentd109, rolling-drain1, Evaluator168, Neuron240, Automation85 and Matrix migration1 passed. Core completed117 passed and2 failed because exact paused deadlines exceeded their expectations by1ms. Original failures and reports are retained. The six previously unstarted owning scopes continue diagnostically on the same unchanged0427 source in job `1a1d5684620-392-803`; full-workspace validation and final fix/fmt are deferred to the repaired candidate. These historical results do not qualify later source. Main remains `732e934ba496d90fbe042b8d41d479ef901643e5`. Real required checks, remaining branch review and retirement are still pending; the single-main task is incomplete.

## Changes

- Keep incomplete evidence distinct from a completed negative evaluation. Preserve observed metrics, return the typed insufficient-evidence error and do not issue an Evaluation/NoUpdate receipt or advance the Training cut.
- Repair the observed candidate CI blockers: exact CALLERS and immutable-archive pins, private ledger fixtures, an actual durable cognitive store for the ready-recipient fixture, and the Windows test for deliberately unavailable legacy isolation. Existing refusal behavior remains.
- Align exact-version Bazel cryptographic optimization with Cargo. Pin the independently reviewed complete Fence v0.13.0 Action while preserving its existing permissions, inputs and failure policy.
- Preserve the reviewed design document and historical heads. Six additional heads were proven to yield an identical tree through normal merges; overlapping evaluation assertions retain the stronger current fixture and every relevant incoming assertion.
- Merge runtime fixes for capability-discovery recovery, removal of unused mutable Neuron-owner accessors, and context/sequence/clock/capacity validation before inference.
- Merge six CI fixes covering conservative path scope, invalid-path rejection, stable Git fixtures, ambiguous source-group rejection, V8 build/test discovery and a checksum-preserving zlib mirror fallback.
- Apply the actual native formatter output. Four test-only unwraps become Option::map comparisons with Some, preserving failure for a missing anchor and the original expected values.

The six finalization postimages match the native-machine SHA256 manifest. The two Python formatter changes preserve their complete parsed AST. No lockfile, Cargo manifest, Bazel dependency input or protected-check policy changes during finalization.

## Historical validation and its exact scope

| Source / stage | Actual result |
| --- | --- |
| fdd7d65b evaluator library | 166 passed, 0 skipped |
| fdd7d65b Agentd learning-evaluation selection | 7 passed, 1,305 skipped |
| a41a4aed Agentd ledger/history/Initial-progress selection | 13 passed, 1,300 skipped |
| dcb5d3a5 Neuron library, first run | 232 passed, 8 failed because actual helper metadata was absent; original log retained |
| Same dcb5d3a5, supported helper preparation and bounded follow-up | Actual helper built and verified before/after; only the original 8 failures rerun, 8 passed, 232 skipped, zero retries, source unchanged |
| dcb5d3a5 Agentd Neuron-owner selection | 1 passed, 1,312 skipped |
| dcb5d3a5 exec capability-recovery selection | 2 passed, 2 skipped |
| Nine CI postimages before final whitespace formatting | 126 ordinary Python tests passed: 50 scope/dependency, 20 research-unit and 56 required Bazel discovery, including 8 V8 detector tests |
| ab5fcda6 normal Bazel lock recipes, including the new external patch | lock-update and lock-check both exit 0; lock unchanged, SHA256 783b3ad329fa53bd4a0e48be6907d38259fa2880d61bd1994b863d7f78bbca57 |
| ab5fcda6 workspace / derived projections / development docs / whole main-to-head blob gate | All four passed on a clean unchanged source snapshot |
| ab5fcda6 complete CALLERS verification | exit 0 after 709.116 seconds on unchanged clean source |
| Native finalization | Four-package scoped just fix, scoped just fmt and diff-check exit 0; six-file patch retained with exact postimage hashes |

Rust tests used the repository's `just test` recipe, locked dependencies and zero retries. The Windows-only exec test compiled on Linux but ran zero tests (43 skipped, exit 4); this is not Windows validation. The original failed shared-cache Bazel attempt and original eight Neuron failures remain in the audit evidence.

The automatic Clippy fix attempted an invalid re-export removal in Agentd, diagnosed four E0432 errors, rolled those suggestions back and returned to the original diagnostics. No such suggestion remains in the six-file output. A separate read-only `just clippy -p codex-hepta-agentd --locked --profile dev-small` confirmation completed with exit 0 after 401.283 seconds on the exact final postimages. It reported no error diagnostics; existing Agentd lib/lib-test warning counts remain 70/98 (including 68 duplicates in the latter). The six postimage hashes and complete diff were unchanged before/after. The transient E0432 diagnostics did not recur without automatic fixes.

No Rust tests were rerun after fix/fmt. The current candidate and prospective main merge still require the real `CI required` and `Architecture required` checks. Older #6284 successful release/clippy/cargo-deny jobs are historical context only. Normal protected merge conditions will be respected without administrator bypass.

## Earlier exact-source CI failures and repair work

The `Architecture required` check completed successfully on `5378a62d` at 2026-11-13 05:16:42 UTC (run 43367036937). The blocking CI run 43367036765 has failed Linux GNU/musl, Windows shards 2–4 and macOS ARM test jobs; the macOS Intel job has since completed with further failed and timed-out targets. Its full original log is retained and the new observations are being diagnosed separately. Successful release, Clippy and format jobs do not satisfy the required aggregate by themselves.

Original full job logs and the final failed/FLAKY target summaries are retained. Linux failures include three fixtures that still expected incomplete evidence to complete Evaluation/NoUpdate, and one durable file lock release lifecycle failure. Windows failures include test reads through separately opened handles of locked files, a CRLF-altered byte fixture, canonical path prefix differences, and obsolete expectations that the deliberately retired legacy sandbox can perform operations. macOS has additional canonical temporary-root, native process and executor test failures. These are not being dismissed as general CI instability.

The isolated four-file repair of the Linux evidence fixtures and durable held-file guard, now published in `a039abd5`, was tested through the repository recipe with locked dependencies and zero retries: evaluator library 168/168 passed; Agentd evaluation/proposal selection 24/24 passed (1,289 skipped). The input tree is `0658c9319850b434bf8ee9cd40c6a1427cbcc178`, patch SHA256 `3a1c05f34fd9e8761cfeb295ece4c97ade9826817297e209c568223ecd89307d`. Scoped fix completed with an invalid automatic suggestion rolled back and no source change. The retained-source Clippy confirmation completed with exit 0 and no errors after 403.664 seconds. Scoped fmt and diff-check completed successfully; the final 14,369-byte patch SHA256 is `370e5e290a76e38232227394207d4e4bd01a6b979b84e29a4173b562fb6a9cc8`. Two test files received only formatter line wrapping; production lock code and Q24 fixture bytes were unchanged. Final tree and all four postimage SHA256 values were independently verified before publication. No tests ran after fix/fmt. These scoped native results do not satisfy the prospective main merge's required CI.

Platform repair candidates are being reviewed separately. Their original assertions and refusal boundaries are retained; no protected check, sandbox admission, retry policy or test skip is being weakened to obtain a merge. Native Windows/macOS confirmation remains required.

## Retained boundaries and follow-up

Source convergence does not activate deployment, validate a research benefit or grant promotion/production authority. HOLD, NO-GO, UNKNOWN, incomplete evidence and ordinary-learning acceptance limits remain explicit. Historical evidence outcomes are not rewritten.

Only 37 non-main refs have been retired: their exact tips were already ancestors of unchanged main and no open PR depended on their names. Further retirement requires actual main containment, fresh expected SHAs and dependent-PR handling. Other writers continue to create or move refs.

The contents and histories from #6289 are retained here. That draft was closed as superseded, not merged; its obsolete CI run was explicitly cancelled after verifying the exact owned source identity, with original failure logs retained.


## Historical execution interruption — 2026-11-13 06:04 UTC

The shared execution environment became unavailable after an exec-server transport disconnection. This is a runtime outage, not an approval rejection. A fresh GitHub read confirms main remains `732e934ba496d90fbe042b8d41d479ef901643e5`, this PR remains open/unmerged, and the published integration branch remains the staged `a039abd5` checkpoint.

Before the interruption, 53 reviewed platform files were assembled and each complete postimage was checked. The local-only clean native-input commit is `daed63b1e862a79c2abce435f6c2ecdf1562a8a0`, tree `892b4950f1f5e0510324eb4f70df7a812ffe89d5`. It has not been published to GitHub or transferred to the native operator host. The 191,852-byte patch SHA256 is `44ab877b20dbb8972d430ab6709c1976c28be1424cb67d20cae191111a0cdec3`; the 49,898-byte bundle SHA256 is `e7dc9f1fd946a0d207f1223ad036fb4785314cbb899692a196f328fe10fabdaa`, requiring the existing `5378a62d` commit. No native tests, Clippy or formatter have run on this combined input. Its source assembly and review receipts are in `audit/ci/final5378/platform-combined-assembly/` in the interrupted workspace.

The platform input includes exact legacy-admission refusal expectations and corresponding current CI selector names; locked-file test observations; canonical temporary paths; exact sha2 Cargo/Bazel optimization; capability-aware executor-skill tests; and bounded diagnostics for two unresolved macOS failures. Guardian now waits for the matching normal finish owner before reusing a review session, including the interrupt/drain path, under the original deadlines; five deterministic tests were added. The zsh startup fixture is an isolated source delta from `1a715025`: that head's wider 80-file merge remains unresolved and is not counted as merged. The reviewed normal automation merge from `2e138bbe` still requires preservation of its parent history on final publication.

Local full-CALLERS verification session `73021` and equal-tree preview session `92495` were running when the environment disconnected; their final states are unknown and neither is reported as passed. The last independently read branch-scan records cover six heads: two normal merges change the tree, four lack required promisor objects, and no equal-tree candidate was confirmed. Missing objects are not classified as merge conflicts. No additional branch was deleted.

Resume from verified source hashes and original process identities; do not restart an uncertain job. Native validation still needs normal Bazel lock update/check, helpers prepared from the exact clean source commit, project tests and the complete repository test recipe, then scoped fix/format. A subsequent unskipped published head must pass both protected checks before main can merge. Full branch/source reconciliation and safe ref retirement remain incomplete.


## Recovered and published input — 2026-11-13

The temporary workspace was empty after recovery. The 04:49 evidence archive was restored and all 2,146 manifest entries were checked by length and SHA256. The unpublished `daed63b1` input was not recovered and is not treated as tested or byte-identical to the reconstruction. The retained zsh, drain-diagnostic and CodeMode diagnostic patches reproduce their original exact hashes; other reconstructed components have new hashes and fresh source reviews.

The new 57-file patch is 233,270 bytes, SHA256 `4ef03d7f0619a2af997334908d009cee7274fbc9fb86b429c0f5aca891ec411e`. Every complete postimage was checked. All four GitHub commit trees and ordered parents were read back before advancing the integration ref with an expected-head check.

| Published commit | Preserved incoming head | Change |
| --- | --- | --- |
| `7627c38fa0e5d0597a0b08ba1b2801598ffbcf0a` | `2e138bbe60fa638c8400f066559661faf1633445` | 53 reviewed platform files and ordinary automation path merge |
| `313d145cf36517e2507c2945cdb304303adf1b05` | `610519f9e21b2357d7c687112d6ab543b33df193` | Bounded TUI fixture retry of only the exact typed NotIdle response |
| `aa706d4af7173e0def0e69fae63334db99613fe5` | `f7929e84a61323285dbf481da714e3261186e807` | Two-hop redirect timeout fixture plus decreasing-budget assertion |
| `0427bfacef8879be06a82a152f51355325eaf506` | `50c382e3e71229b0bb127129abd3d52ca6ee0e0c` | Two original fake-driver/remote transcript regression tests |

Seven guarded legacy Windows PowerShell/TTY expectations were statically inconsistent with the existing unconditional admission refusal. They now require the typed refusal and unchanged marker/home state. Original availability guards, mutex placement, ignore attributes and elevated positive coverage remain. This does not qualify legacy isolation or replace the historical HOLD outcome.

The shared-cursor fixture readers were checked against their actual runtime topology: affected running-owner tests use a current-thread Tokio runtime, the journal owner stays on that runtime, and the observer has no await. An acknowledgement alone was not accepted as synchronization proof. Revisit this reasoning if an owner moves to another thread.

Intel failures remain unresolved. The Agentd timeout has two cases without terminal lines; the 19 named failures matching ARM do not explain that timeout. Memory requested all 16 peers and completed 4; missing original coverage diagnostics prevent attributing the other 12 to a particular cause. Exec forwarding, supervisor mutation and Core admission-fence cleanup also require further diagnosis. Budgets and ownership fences remain unchanged.

A fresh clone observed 7,168 refs at 11:40 UTC. That inventory is not a deletion lease. No additional ref has been retired beyond the previous 37. Large Memory/Learning branch reconciliation, complete protected validation, main integration and final one-branch retirement remain incomplete.


## Exact-source native preparation update — 2026-11-13

The published `0427bfacef8879be06a82a152f51355325eaf506` / `21c03749c29d7a9013f09cfd3f738d140bc73cfd` input has now completed a full clean native preparation. The first three preparation attempts stopped on concrete Git-cache gaps before any Bazel/helper/test execution. The original five thin-pack bases and sixty missing historical evidence blobs were recovered from GitHub and checked against their original Git object hashes before normal import/restore. No historical evidence was regenerated or treated as current qualification.

Preparation job `1a1d4f7607d-392-67b` finished successfully. All 15,505 tracked entries / 14,954 unique blobs are present, every one of the 57 frozen file postimages matches, and the working tree is clean. Normal `just bazel-lock-update` (13.20 seconds) and `just bazel-lock-check` (1.26 seconds) both exited 0. `MODULE.bazel.lock` remained unchanged (`sha256:783b3ad329fa53bd4a0e48be6907d38259fa2880d61bd1994b863d7f78bbca57`). The original checks and warnings were retained.

Fresh helper job `1a1d4faaa30-392-689`, bound to this exact source, finished failed/exit 1 after CLI, exec, app-server and exec-server helpers compiled. Code-mode-host's default denoland V8 150.4.0 archive returned 404. The existing repository paired-artifact resolver was then used in independent job `1a1d519e9c9-392-725`; it retrieved the official OpenAI checksum manifest but correctly rejected an archive SHA256 mismatch before starting the child. The source remains clean. The official release asset size and digest matched the original manifest. An independent quarantined re-download then matched both original archive and binding hashes, and unchanged resolver-v2 job `1a1d523a6bc-392-754` passed. The cause of the first mismatched download was not established. Fresh helper-v2 job `1a1d524f6ad-392-75c` subsequently succeeded with all eight packages / ten pinned executables verified; source remained clean and both V8 hashes remained unchanged. Ordinary test driver `1a1d531b0ec-392-792` is now running the original thirteen owning scopes followed by full `just test`, stopping on a failure. Scoped fix/fmt have not started. No checksum, dependency version or required gate was weakened.

A separate read-only native branch snapshot has 7,169 refs; 6,839 are not ancestors of the exact `0427bface` candidate, comprising 6,507 distinct tips covered by 2,465 maximal heads. This graph count is a scheduling proof, not source approval or a deletion lease. Seven sequential ordinary `git merge-tree --write-tree` previews all returned the unchanged `21c03749` source tree; they remain local previews and have not advanced any ref.

No main merge or additional branch deletion has occurred; the required checks remain mandatory, and this PR still does not claim completion of the all-branches/single-main task.


## Eighteen-head source reconciliation — 2026-11-13

The integration ref advanced from `0427bface` to `42dbcba8` after independent tree/ordered-parent API readbacks. Main was unchanged and no further branch was deleted. Seven previously proven equal-tree histories and one duplicate snapshot history add no source delta. Every incoming head is retained as a real merge parent; an ordinary merge preview preceded each source decision.

The twelve-file delta preserves five reviewed historical/read-only export, storage-inventory, dependency-proposal and original-log workflows; adds four existing-style Clippy target-selection regression tests (all four passed locally with a mock query, not a native Windows execution claim); and adds the CLI-library snapshot whose bytes exactly match both existing binary snapshots. The WinAPI opaque argument type is aligned inside the existing private attribute-list wrapper; pointer casts and containment behavior remain unchanged, and Windows validation is still required.

Two semantic conflicts were resolved explicitly even though Git's textual merges were clean:

- The old HOS2 cleanup removed `mut` from a join handle now borrowed as `&mut` by the current SQLite-blocking timeout assertion. The normal incoming tree was computed, then that single obsolete cleanup was repaired. All current authority-revocation and no-retirement assertions remain.
- The incoming typed automatic-restart events removed existing `RestartQueued` and budget-exhaustion fault reporting expected by current callers/tests. The reconciled implementation emits the typed events additively and preserves the complete `TickReport`/`DriverFault`, backoff, persistent-budget and no-further-spawn behavior. Five assertions were added to the existing owning/recovery tests, and a second source reviewer verified that every original line remains in order. Extra observations still occupy the original bounded event history and may evict old observations sooner; no unbounded-history guarantee is added.

One extra blank line at the end of the historical dependency-proposal workflow was removed after the original whitespace check correctly failed; the failure and resumed preview chain were retained. The final twelve-file patch is 45,927 bytes, SHA256 `cf0bd82b263e8b5aac2441fca30bd02a1a1426b3d7955ffc0bc13732bff108a9`.

This is a source-reviewed incremental checkpoint, not a validated full convergence. The new source still needs its owning/native tests, full repository validation, scoped fix/fmt and both real required checks. Memory, Learning, remaining branch/source reconciliation and eventual one-branch retirement continue.

## Six documentation histories after `42dbcba8`

The ordinary merge chain preserves all six incoming tips. The duplicated durable-owner update becomes an exact equal-tree ordinary merge. Five net paths are retained:

- The cached cargo-deny report is explicitly scoped to its original `f8c9419d` source and cached database. Its historical findings and no-ignore policy are preserved; its Rust1.95 statement is not presented as current integration policy.
- The shared-Stem/NDU research record retains all shadow-only, owner, budget and DENY_ALL boundaries. Lost math escapes (one tab, three carriage returns and a split nu coefficient), display delimiters and whitespace are repaired without claiming mathematical or operational qualification.
- Lane A's stale durable-owner table cell now matches its existing implementation document and migrations0011/0012; exact-candidate execution and all external activation/acceptance gates remain open.
- The dated2026-11-09 framework recovery checkpoint is preserved unchanged, including37 prior library failures, unavailable source bytes and HOLD. It supplies no runtime implementation or validation for this candidate.
- One `inference.control` index digest now equals the already-present5847-byte design document. Every other row and claim field is unchanged.

Complete five-file patch: 75725 bytes, SHA256 `c7f339c2d8ae2c1f2a3264a0cffe8b76c2de2cab9b01c9d8ff11fead6494c212`. Initial Markdown whitespace failure was retained and narrowly corrected. No workflow, qualification experiment or behavioral test was run for this documentation-only increment. The previous eighteen-head publication has separately passed a normal fetch and replay of all actual remote ordered parent merges, with all twelve exact postimages verified.


## Six policy/history heads and exact-clock fixture correction

Six ordinary merges were reviewed against their actual predecessors, with explicit semantic resolutions where old workflows would replace current interfaces. Fleet and desktop availability keep manual dispatch on main, exact runner selection, bounded reason validation and `permissions: {}`. Incoming concurrency and read-only git/python/cargo/gh observations are retained. Obsolete automatic installation, process termination, detached service startup and cross-host recovery are retained in commit history without reactivation. A duplicate `pretty_assertions::assert_eq` import is resolved to the existing single binding with all assertions unchanged.

The `ordinary-daemon-learning-20261109` evidence is preserved byte-for-byte. The two archives were inspected without extracting or executing their scripts:43 safe regular members,36 manifest payload identities, original logs and the163-case JUnit were cross-checked. Their original5530f84e source, historical failures and HOLD scope remain explicit; none is attributed to current integration. The eight-file merge patch is2,685,253 bytes, SHA256 `5a0a2f1b5dd96524c5752d487f7c19b776557cb77eed64778061e0d155ba3ef4`.

The two failed Guardian fixtures used late `time::pause()` after runtime setup. Source review of the actual pinned Tokio1.53.3 timer/clock shows that this retains a fractional offset from the millisecond timer origin. Both fixtures now use `#[tokio::test(start_paused = true)]`; the two late pauses are removed. All original equality assertions,1s/5s budgets, explicit advances and owner fences remain unchanged. No production code changes. Repair patch1,668 bytes, SHA256 `1f5e2f93ee1358207c537a361d705ac019575e257dbceac3f69db83e6b696c61`; postimage SHA256 `bf4538832cffad6859c9ecd2e88997c42848cd331b0dec5b92ba62b30aabd976`. Original2 failures are not rewritten as passes; repaired-source native regression is pending.


</details>


</details>

</details>


</details>
