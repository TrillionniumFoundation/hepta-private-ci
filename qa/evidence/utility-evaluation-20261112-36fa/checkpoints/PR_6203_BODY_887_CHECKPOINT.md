## Problem and resulting behavior

A known failed metric could take precedence over missing applicable evaluation evidence. Both the independent evaluator and the trusted in-process compatibility comparator returned `Ineligible`, allowing the learning bridge to interpret an incomplete comparison as a completed `NoUpdate`.

The published fix makes missing applicable evidence take precedence while retaining known failed metrics. Complete negative and complete eligible comparisons retain their meanings. The learning-stage regression combines a known negative comparison with a missing future window and requires the original Training cut to remain at Evaluation without issuing a NoUpdate receipt. Disposition and failed metrics remain digest-bound, and current revalidation requires the current complete sealed decision.

**Draft / HOLD. Published source remains `e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd`, whose original exact-head qualification failed. A fixed-b298 successor is applied in the isolated native review checkout and is undergoing maintenance; it has no published source commit or qualifying test result yet.**

## Source identities and current work

| Identity | Exact value / status |
| --- | --- |
| Published source commit | `e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd` |
| Published source tree | `b607ff5f50812c5e0f932d7dae18d4c74f1269cb` |
| Ordered published parents | `19aa601fa09321f1b6d1b3ff3b4d422908004e48`, `726af8f4a345a2ffb148b971f3fa16c71436862d` |
| Frozen successor dependency | `b29869e856d08db1bfb066116a9c443376ccc57d` |
| Reviewed prepared tree | `a8c41e56f1f8685444022692d1a636ec61b44e70`: 14,851 files; 40 changes relative to b298, 146 relative to e8 |
| Latest immutable evidence checkpoint | [887 files at `bf81c936`](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/bf81c936fff69911ed1554c222e18ce3831b36f2/qa/evidence/utility-evaluation-20261112-36fa), individually matched by path and blob |
| Current native operation | Separate v2 prepublication continuation; original two-package `just fix` actually compiling from a new dedicated empty target. Formatting and terminal maintenance outcome remain pending. No behavior tests requested by this operation. |

The complete preparation packet binds all 40 postimages, their actual b298 preimages, nine new raw Git tree objects, and the complete final inventory. Two independent reviews reconstructed every tree node; reversing the 40 changes recovers the original b298 tree. GitHub independently created the same a8c41 tree. [Packet and reviews](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/bf81c936fff69911ed1554c222e18ce3831b36f2/qa/evidence/utility-evaluation-20261112-36fa/integrated-fixed-b298-prepared-v1).

Native application actually completed all 146 e8-to-a8 changes before the first maintenance attempt failed because its expected earlier /data build target was absent. That attempt executed **zero Cargo commands and zero tests**. The complete physical inventory was independently reconstructed: 3,440,077 bytes, SHA-256 `5cbe4f67b27b7c57d0bb8d3ec8d3fe6ac75d5b09578c23af7b6179f6546d4aab`; it matches both native after-application and final inventories. The independent retained e8 checkout remains exact and clean. [Actual failed result and application proof](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/bf81c936fff69911ed1554c222e18ce3831b36f2/qa/evidence/utility-evaluation-20261112-36fa/native-fixed-b298-prepublish-v1).

The separately identified v2 continuation does not repeat source application. It creates only `/data/hepta-utility-36fa-final-native-target-v1`, records that rebuild cost separately, runs the original scoped fix and formatting commands, and retains the original 7200/900-second budgets. At the 13:30 UTC observation, the original `cargo clippy --fix --tests --allow-dirty` command and actual dependency compilation were present in its log. This is an active operation, not a maintenance pass. HEAD still names e8 while the staged source is a8; no test result may be attributed to e8 or a future successor from this preparation. [Driver and actual launch input](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/bf81c936fff69911ed1554c222e18ce3831b36f2/qa/evidence/utility-evaluation-20261112-36fa/native-fixed-b298-prepublish-v2).

## What the successor preparation changes

- Preserves the e8 incomplete-evidence precedence fix and its regressions, together with the complete fixed-b298 original-owner implementation.
- Adds two composition guards: primary Eligible with an Ineligible retention member cannot become Qualified at the original panel or final model-material revalidation boundary. It is refused; it is not reclassified as aggregate NoUpdate, fraud or a payment decision. Complete primary-negative NoUpdate and existing Unknown refusals remain distinct.
- Corrects four observed fixture preconditions without changing authority or comparison requirements: task/source bijection and inclusive-expiry checks.
- Makes the existing legacy NextUse Trainer reference explicit for the conservative caller collector, preserving the same missing-owner error, readback arguments, await and evaluated branch.
- Boxes the large private panel-construction future and removes a forwarding future. The original construction body, 27 assertion macro calls and three Tokio attributes are preserved. This follows measured stack evidence; it has not yet been shown to resolve every prior overflow.
- Completes exact registration/protection for audited original callers. Final CALLERS contains **534 boundaries and 409 protected rows covering 338 paths**. The verifier, workflows, full source inputs, retries and gate budgets are unchanged. No wildcard or ignored test is added.

The v3.2 protection review compares every inherited row and QA function. Five inherited QA files change only nine EXPECTED tuple values; all 56 original functions remain byte/AST-identical. Three new source-mutation modules have 24 methods, actually passed in two separately identified preparation runs. Those runs do not establish the complete source gate. [Full manifest and independent reviews](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/bf81c936fff69911ed1554c222e18ce3831b36f2/qa/evidence/utility-evaluation-20261112-36fa/readback-boundary-preparation-v3.2).

## Original qualification on published e8: failed

| Original check | Actual result on e8 |
| --- | --- |
| Exact-head scoped maintenance | PASS: fix and formatting exited 0; complete source inventory unchanged and checkout clean. |
| Complete intelligence-eval library | **163 passed, 0 failed, 0 skipped**. Complete fresh XML and original output were independently checked, including four new regression methods. |
| Focused native `just test` | **FAIL**, exit 100, 1,213.627s, not a whole-command timeout. **100 actual cases: 76 passed, 24 failed, 0 skipped**: 17 stack-overflow SIGABRTs, three individual 60-second timeouts, four other failures. The mixed negative/missing-evidence learning-stage regression passed. |
| Subsequent all / ordinary / Root stages | **Not started** after the focused prerequisite failed. |
| Source closure | **FAIL**, exit 1, 181.765s, not a timeout. Original output: 357 methods; 343 explicit ok, 14 distinct errored methods, 28 error/subtest records. Stale `if owners` versus maintained `&& owners` expectations explain the observed errors; no PermissionError was present. |
| Caller self-test | PASS on the same unchanged source. |
| Full caller verifier | **FAIL**, exit 1, 1,696.925s, not a timeout. The actual unexpected Training-readback caller was `cell_q24_training_command_readback_service.rs`. |
| Independent old-comparator control | Four actual tests failed under the two reverted production comparators, with the four new regressions retained. Original `just test` exit 100. The wrapper's successful observation is not a passing suite. |
| GitHub CI observation | At the preserved 10:14–10:20 UTC observation, no passing checks/runs were returned for e8; the live base had advanced and the PR was conflicting. This is a timestamped observation, not a claim about current CI. |

**No e8 result transfers to a8 or to a future source commit.** The original full gates will run on a newly published frozen head after maintenance and exact native source alignment. The next original source runner is prepared with null final identifiers and original source-closure/self-test/full-caller budgets **600/300/4800 seconds**. [Preparation plan](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/bf81c936fff69911ed1554c222e18ce3831b36f2/qa/evidence/utility-evaluation-20261112-36fa/next-exact-source-gates-preparation).

## Actual diagnostics: complete records, bounded conclusions

The unchanged original v2 projection completed all **534 boundary rows: 519 passed, 15 failed, 0 Unknown**, and all **390 protected rows passed**. It exited 1 under the original 4800-second budget. Root reconstructed every large original file, reconciled 1,849 progress events against the complete 873,489-byte raw output, matched final JSON/report and full before/after source inventories, and checked every retained part path. Twelve failures exposed existing caller registrations; three exposed the Trainer receiver ambiguity. This is a failed scoped projection diagnostic, not a full gate on the successor. [Complete records and root review](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/bf81c936fff69911ed1554c222e18ce3831b36f2/qa/evidence/utility-evaluation-20261112-36fa/source-gates/desktop-all-boundaries-overlay-v1).

The explicit Trainer-reference diagnostic passed positions 281 and 313 but failed the original protected-body literal, so its actual overall exit remains 1. A separate diagnostic of position 468 passed with zero failed/Unknown rows. These are separate executions, with their full inputs and inventories preserved; they do not collectively become a full verifier pass. [Two-boundary run](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/bf81c936fff69911ed1554c222e18ce3831b36f2/qa/evidence/utility-evaluation-20261112-36fa/source-gates/desktop-next-use-trainer-type-v1) · [Separate Evaluation-boundary run](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/bf81c936fff69911ed1554c222e18ce3831b36f2/qa/evidence/utility-evaluation-20261112-36fa/source-gates/desktop-next-use-evaluation-readback-v1).

A separately identified exact-e8 new binary build completed successfully and executed **zero tests**. The original failed-run binary had subsequently become unavailable; a new binary is not represented as that original. On the new binary, GDB observed a panel fault in the guard page below the unchanged 8 MiB stack. Readonly disassembly found five relevant fixture/test frames allocating 8,164,824 bytes before smaller frames. This supports the narrowly prepared boxing change, not a claim that it fixes all 17 aborts.

The separate deep-case observation captured a 55-second stop with an active original Material/Training validation stack. It does not establish a measured bottleneck or deadlock. Existing fresh-read requirements, original 60-second testcase deadline and stack settings are retained. The debugger's initial precheck failure and a later wrapper status-literal failure remain preserved; neither debugger case is a Rust testcase pass. [Original diagnostics and independent reviews](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/bf81c936fff69911ed1554c222e18ce3831b36f2/qa/evidence/utility-evaluation-20261112-36fa/native-e8-new-diagnostics).

Under the inspected original deterministic provider and frozen strict-superiority plan, the fixture cannot construct the positive primary needed to reach the new positive-primary/negative-retention rejection. The new retention branches therefore remain **runtime-uncovered**. No synthetic qualification or altered objective/propensity is substituted. [Source-pinned feasibility report](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/bf81c936fff69911ed1554c222e18ce3831b36f2/qa/evidence/utility-evaluation-20261112-36fa/RETENTION_GUARD_REGRESSION_FEASIBILITY.md).

## Utility requirements still requiring implementation or real evidence

The [36-pin requirement coverage matrix](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/bf81c936fff69911ed1554c222e18ce3831b36f2/qa/evidence/utility-evaluation-20261112-36fa/UTILITY_REQUIREMENT_COVERAGE_A8C41.md) separates source mechanisms from acceptance. Its pins match the complete prepared inventory; root additionally read the NDU specification and seven critical implementation files.

- **External objective and authority:** objective, policy, observation and reward identities must come from actual authorized owners. A digest cannot establish who controls those semantics or confer permission to alter them.
- **Complete deployable comparison:** the bundle and matched fixed-expert contract exist. They do not establish the strongest deployable baseline, every runtime/tool/router setting, the real task distribution or all deployment costs.
- **Costs:** the current frozen scope is explicitly `TaskLedgersBeforeFinalHoldout`. It does not include the complete post-cut evaluation, publication, download, activation, serving and maintenance totals required for full net-utility acceptance.
- **Independence and identification:** declared distinct controllers, keys and deterministic support records do not establish real task-source, training-lineage, evaluator and operational independence. Unsupported changed-action comparisons remain refused/Unknown.
- **Ordinary continuation:** direct evaluated S/C receipts, original T/E custody and strict Root six-receipt authentication now exist. Ordinary Version/published-read still accepts the legacy TrainingNoUpdate prefix; candidate Selection/NextUse and some recovery routing remain refused, and the startup assembly lacks a registered product caller. This is an actual source gap, not merely an unexecuted test.
- **Real A → T → B → S/C → daemon + Root:** independently observed B outcomes, original final authorization, legally available and retrievable model bytes, actual new-consumer readback and both cold recoveries still require real authorized inputs. A receipt or content root alone cannot establish adoption or continuing availability.
- **Result semantics:** complete negative service is distinct from incomplete evidence and from reproducible objective fraud. The composition guards supply neither a public payment contract nor a fraud adjudication protocol.

**Complete real ordinary Adopt = 0. Complete real evaluated NoUpdate = 0. Complete real daemon + Root cold-recovery qualification = 0.**

## Evidence integrity and historical limits

The immutable [887-file checkpoint](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/bf81c936fff69911ed1554c222e18ce3831b36f2/qa/evidence/utility-evaluation-20261112-36fa) retains prior checkpoints and the complete previous PR body, all e8 failures, complete later diagnostics, prepared source packets, independent reviews and actual prepublication failure. Evidence-only commits remain separate from this source PR.

All 244 original b298 transport objects were verified and imported. The repository-wide historical fsck still **failed with exit 3**. A separate read-only check found zero missing among 16,245 unique objects required by the current e8/726/b298 snapshots; this supports working with those complete current snapshots and does not turn the historical fsck green.

Later missing tracked archives were restored only from independently checked original bytes, with complete source inventories and unchanged HEAD/index. Disappearance causes remain Unknown. Four observed surviving native stage gzips were recovered exactly. The original maintenance/eval stage gzips and earlier lost cloud artifacts remain **Unavailable**; preserved summaries are not reconstructed originals.

This PR creates no real task authority, payment, adoption or production permission. It remains draft and unmerged while the successor is prepared and its original gates are pending.
