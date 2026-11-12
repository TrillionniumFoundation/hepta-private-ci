## Problem and resulting behavior

A known failed metric could take precedence over missing applicable evidence, turning an incomplete evaluation into an `Ineligible` comparison and permitting a completed `NoUpdate`. This change gives missing applicable evidence precedence while retaining known failed metrics. Complete eligible and complete negative comparisons keep their existing meanings.

The learning-stage regression combines a known negative comparison with a missing future window. It requires the original Training cut to remain at Evaluation and prevents a NoUpdate receipt. Disposition and failed metrics stay digest-bound, and current revalidation requires the current complete sealed decision.

**Draft / HOLD. Published source remains `c0f78493f815780f68b9bf5e390a21314d79311f`, tree `313ee34febc8ccc54c611ab56286e289518c63cb`. Its evaluator library and full caller gate passed; its focused native and source-closure gates failed. The independently materialized 86dd successor completed dependencies, then its actual fix returned 101 and a separate final index audit left the overall RESULT Unknown. Fmt did not run. The one-line 9c4 repair is prepared and unexecuted. No merge, production activation, adoption or complete net-utility result is claimed.**

## Published changes

- Preserve incomplete-evidence precedence and four evaluator regressions while integrating the fixed-b298 original-owner implementation.
- Refuse an eligible primary with a negative retention member at both original-panel and current-material boundaries. This refusal remains distinct from complete primary-negative NoUpdate, missing-evidence refusal, fraud and payment.
- Correct fixture task/source bijection and inclusive-expiry preconditions without weakening authority or comparisons.
- Make the legacy NextUse Trainer reference explicit to the conservative caller collector while preserving missing-owner errors, readback arguments and the evaluated branch.
- Box an oversized private panel-construction future and remove a forwarding future. The actual c0f failures demonstrate that this did not resolve all stack overflows.
- Preserve the original caller registration and protection: 534 boundary rows and 409 protected rows over 338 paths.

Original ordered parents are `e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd`, then `b29869e856d08db1bfb066116a9c443376ccc57d`. The canonical commit and all 14,851 source leaves were independently verified. [Publication and native alignment](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/048da67876989cfa016f4c126651c78a768b4be0/qa/evidence/utility-evaluation-20261112-36fa/published-c0f/ROOT_PUBLICATION_AND_ALIGNMENT_REVIEW.json).

Evidence checkpoint: **2,049 files**, observed **2026-11-12 19:24:00 UTC**, preserving all 1,741 prior paths and their archived status narratives.

## Actual exact-source validation

| Gate | Actual result |
| --- | --- |
| Original fix / fmt | Exit 0 / 0; no source diff |
| Complete evaluator library | **163/163 PASS**, including all four incomplete-evidence regressions |
| Focused native | **81 PASS / 28 FAIL**, 109 cases; exit 100, 960.6167 seconds, no overall timeout/output cap |
| All / ordinary / Root native | **Not started** after focused failure |
| Source closure | **FAILED**, original 600-second deadline; exit 124, 602.9541 seconds; explicit functional failures preceded timeout |
| Caller self-test | Original command exit 0 |
| Full caller | **PASS**, exit 0, 4477.5591 seconds within the original 4800-second budget; 534 boundaries / 534 IDs / 409 protected rows / 338 paths / 6,597 Rust files |
| Whole source-gate job | **FAILED**, exit 1; caller PASS does not override source-closure failure |

Actual native job: `1a1d0137095-2564-1b21`. Actual source-gate job: `1a1d01a6652-2564-1b2d`. Earlier, partial or preparation results do not transfer to the successor source.

The 28 focused failures comprise **24 stack overflows, two actual 60-second per-test timeouts, one InvalidBinding and one OwnerUnavailable**. One preserved ELF stopped at its first SIGSEGV: the caller had used 7,251,104 bytes of the original 8 MiB stack before a 2,284,152-byte reserve. Four caller-local reserves explain 7,242,272 bytes. Unavailable CFI is not invented, and that one chain does not diagnose every failed test.

The source-closure output had 344 partial cases: 337 OK, five failures, one error and one unfinished case, without a final suite summary. Its partial output and the separate 220-second caller diagnostic are not qualification substitutes. The diagnostic identified repeated type-name scans; the proposed conservative literal prechecks retain the original source set and verdict logic.

[Evaluator XML](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/048da67876989cfa016f4c126651c78a768b4be0/qa/evidence/utility-evaluation-20261112-36fa/native-c0f-exact-validation-v1/eval-lib.xml) · [complete native terminal evidence](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/048da67876989cfa016f4c126651c78a768b4be0/qa/evidence/utility-evaluation-20261112-36fa/native-c0f-terminal-complete/) · [original caller record](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/048da67876989cfa016f4c126651c78a768b4be0/qa/evidence/utility-evaluation-20261112-36fa/source-gates/c0f78493-v1/verify/verify.json) · [source-gate terminal review](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/048da67876989cfa016f4c126651c78a768b4be0/qa/evidence/utility-evaluation-20261112-36fa/source-gates/c0f78493-v1/ROOT_TERMINAL_ADDENDUM_REVIEW.json) · [first-signal diagnosis](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/048da67876989cfa016f4c126651c78a768b4be0/qa/evidence/utility-evaluation-20261112-36fa/native-c0f-first-signal-diagnostic/).

The original full caller raw output was recovered byte-exactly against independent original full-file size/hash/Git identity and observed fixed-version prefix/tail reads. This is recovery, not a new full native read or gate run. The source-closure forwarded stdout and complete helper compiler JSONL remain incompletely recovered. Full provenance and limits remain in the [evidence README](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/048da67876989cfa016f4c126651c78a768b4be0/qa/evidence/utility-evaluation-20261112-36fa/README.md).

At **18:19:17 UTC**, exact c0f hosted-CI reads returned zero check runs, check suites and workflow runs, and pending combined status with zero entries. This time-specific observation establishes no CI pass. [Original responses](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/048da67876989cfa016f4c126651c78a768b4be0/qa/evidence/utility-evaluation-20261112-36fa/hosted-ci/c0f-20261112-1819/OBSERVATION.json).

## Successor preparation and actual dependency work

Prepared commit **`86dd56a930277e0d1aef3e475e35c2b5d60b43b7`**, tree `383ab85c39ef9d848252ef5c25922d13d9fae6c6`, has 15,188 leaves and ordered parents c0f then fixed a96. It contains the 59-file ordinary evaluated NoUpdate preparation, three reviewed Rust increments, structural non-Rust registration, an explicit Root case and two conservative literal checks before the original regexes. Its ten new ordinary tests have not completed compilation or run. It is not the published source branch.

Unique materialization job `1a1d0c6996e-2564-1bc8` actually ran at **17:20:41–17:22:17 UTC** with normal complete exit 0. It created an independent repository at `/home/qian-qi/hepta-utility-36fa-maintenance-86dd-v1`, read back **16,618 raw objects**, validated **ten full snapshots** and materialized all **15,188 physical leaves**, without alternates or a shared object store.

Its full physical inventory is **5,611,182 bytes**, SHA256 `bca1a7399820966d3167a26f89355898a9ea9a7169938ffa27e7dd9576fc1711`. All 34 Git commands and all five final audits passed. Root matched the full original 69,974-byte RESULT, complete terminal and all 40 small evidence paths. This is materialization success, not maintenance, testing, whole-history fsck or task-chain qualification. [Original RESULT](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/048da67876989cfa016f4c126651c78a768b4be0/qa/evidence/utility-evaluation-20261112-36fa/fresh-materialization-86dd-v2/run/RESULT.json) · [Root review](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/048da67876989cfa016f4c126651c78a768b4be0/qa/evidence/utility-evaluation-20261112-36fa/fresh-materialization-86dd-v2/ROOT_ACTUAL_ORIGINAL_READBACK_REVIEW.json).

The earlier materialization failure, read-only probe size-ceiling failure and old review directory's missing tracked archive remain preserved. The old directory's missing-file cause remains Unknown. The original a96 audits were subsequently recovered exactly, including raw/gzip hashes and all 52 encoded parts; this recovers prior output and retains the partial-read provenance gaps. [Materialization failures](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/048da67876989cfa016f4c126651c78a768b4be0/qa/evidence/utility-evaluation-20261112-36fa/fresh-materialization-86dd-v1/) · [a96 recovery scope](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/048da67876989cfa016f4c126651c78a768b4be0/qa/evidence/utility-evaluation-20261112-36fa/native-a96-canonical-validation-v1/recovery/RECOVERY_MANIFEST.json).

### Dependency preparation v1: known failure

Unique job `1a1d0e66ad6-2564-1bdd` actually ran at **17:55:26–17:55:36 UTC**, ending with **FAILED_PREPARATION / normal exit 1**, complete durable output and no timeout. Its concurrency preflight rejected an observed same-user build before any download, UV command, new depot creation, Cargo build or maintenance.

The complete source inventory, Git state and all 23 fixed inputs remained unchanged. Root verified all 44 placement paths and the complete fixed-version RESULT. This is a known preparation failure, not Unknown execution and not an unsuccessful dependency installation. [Original RESULT](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/048da67876989cfa016f4c126651c78a768b4be0/qa/evidence/utility-evaluation-20261112-36fa/runtime-restoration-86dd-v1/run/RESULT.json) · [Root actual failure review](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/048da67876989cfa016f4c126651c78a768b4be0/qa/evidence/utility-evaluation-20261112-36fa/runtime-restoration-86dd-v1/ROOT_ACTUAL_FAILURE_REVIEW.json).

The **17:59:36 UTC** read-only diagnostic observed a stable Cargo process under the distinct source directory and exact cgroup of job `1a1d0e549d0-2564-1bdc`; four prior rustc PID references had disappeared. It does not establish identity continuity since the original 17:55 preflight or termination of the whole foreign job.

The reviewed successor only narrows the **material-preparation** process check for that exact observed foreign job, requiring stable current identity and distinct source paths. Other, changed, overlapping or unknown matching processes remain blocking. Original maintenance/test concurrency checks and all gate deadlines remain unchanged. No foreign process was controlled, and its arguments/environment/source contents were not read.

### Dependency preparation v2: actual complete success

The distinct job `1a1d0fcb212-2564-1bf4`, key `hepta-utility-36fa-runtime-materials-restore-86dd-v2`, was admitted at **18:19:44.018 UTC** and actually ran from **18:19:46.221347 to 18:20:30.092085 UTC**. Its normal complete supervisor terminal has exit **0**, durable 3,368-byte stdout, empty stderr, and no timeout, cancellation or truncation.

All **six fixed downloads** matched their exact byte counts and SHA256 values. All **six original preparation commands** had observed complete exit-zero terminals, including named offline installation of `ruff==0.15.13`, both original frozen/offline sync checks and the original UV-run Ruff version command. The three final audits verified the unchanged full source inventory, all 23 immutable inputs and 16 material/tool identities. Actual CODEX_REPO_ROOT and PYTHONPATH were both observed as null; no missing field was filled with an invented null.

The actual process-preparation observation had empty observed, allowed, blocking and unknown arrays. **The prepared foreign-job exception was not exercised by this operation.** This does not establish the foreign job's complete lifecycle or relax maintenance's current global concurrency check.

Root independently checked the complete **21,366-byte RESULT**, **21,724-byte ENVIRONMENT_READY**, original same-job supervisor and exact admitted launcher. After a control-cache loss, the two existing files were reread at their previously observed immutable versions; both complete byte sequences, hashes and EOF matched. The recovery reads are retained as recovery reads, and no operation was reexecuted. The earlier configuration write and synchronous file-info transport timeouts also remain recorded; a complete durable file-info observation established the actual approved configuration identity before the unique launch.

The six original command raw logs and all 39 small original records have since been fully retained. Root matched the three original multi-file reads, individual byte/hash identities and the complete 3,368-byte supervisor output; this closes the earlier review's pending-log retrieval without changing that historical review. [Full-originals addendum](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/048da67876989cfa016f4c126651c78a768b4be0/qa/evidence/utility-evaluation-20261112-36fa/runtime-restoration-86dd-v2/ROOT_FULL_ORIGINALS_AND_MAINTENANCE_START_REVIEW.json).

This is **actual dependency-preparation success**. Cargo, maintenance, tests, source-ref updates and real task-chain qualification were not performed by this operation.

[Original RESULT](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/048da67876989cfa016f4c126651c78a768b4be0/qa/evidence/utility-evaluation-20261112-36fa/runtime-restoration-86dd-v2/run/RESULT.json) · [actual environment](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/048da67876989cfa016f4c126651c78a768b4be0/qa/evidence/utility-evaluation-20261112-36fa/runtime-restoration-86dd-v2/run/ENVIRONMENT_READY.json) · [normal supervisor](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/048da67876989cfa016f4c126651c78a768b4be0/qa/evidence/utility-evaluation-20261112-36fa/runtime-restoration-86dd-v2/run/SUPERVISOR_TERMINAL.tool-result.json) · [Root complete actual review](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/048da67876989cfa016f4c126651c78a768b4be0/qa/evidence/utility-evaluation-20261112-36fa/runtime-restoration-86dd-v2/ROOT_ACTUAL_COMPLETE_REVIEW.json) · [configuration transport provenance](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/048da67876989cfa016f4c126651c78a768b4be0/qa/evidence/utility-evaluation-20261112-36fa/runtime-restoration-86dd-v2/config-observation/).

The exact maintenance configuration was **Root approved**, Git blob `88e0e1c333b6f6f3e792977d9b8033128f3767ff` (8,286 bytes), binding the actual restored tools and three original proofs. It preserves the original commands, global concurrency guard and complete source/postimage recording. The Root-selected **32 GiB** target free-space prerequisite was part of the actual live preflight; it is not a historical frozen contract. The later failed maintenance result is reported separately below. [Final configuration review](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/048da67876989cfa016f4c126651c78a768b4be0/qa/evidence/utility-evaluation-20261112-36fa/maintenance-preparation/v3/ROOT_FINAL_EXECUTION_REVIEW.json).


## Actual maintenance failure and exact index diagnosis

The unique maintenance job `1a1d10d8ad0-2564-1bff` was admitted at **18:38:08.080 UTC** and ended with a normal, complete supervisor **exit 1 at 18:49:07.733 UTC**. The original scoped fix returned **101**, without timeout or output-limit truncation. Its complete **116,897-byte raw log** contains one compiler error: `E0425`, the existing `recovered_peer` helper was not exported through `training_ports` for the evaluated-version recovery test. **Fmt did not run; no test command was dispatched.**

The complete post-fix source inventory still has all **15,188 leaves**, the same tree and the same `bca1a739...` inventory identity; its exact transition packet has **zero source postimages**. The final raw Git-state audit separately failed because the index SHA256 changed. The original overall RESULT therefore remains **Unknown**, alongside the known compiler failure. Neither result is reclassified as a pass.

All original raw fix output and all **118,168 bytes of supervisor stdout** have been retained. Root independently matched the two fixed-version fix reads and all nine original supervisor-output intervals, including their hexadecimal and text representations. [Original RESULT](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/048da67876989cfa016f4c126651c78a768b4be0/qa/evidence/utility-evaluation-20261112-36fa/fresh-maintenance-86dd-v1/run/RESULT.json) · [fix terminal](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/048da67876989cfa016f4c126651c78a768b4be0/qa/evidence/utility-evaluation-20261112-36fa/fresh-maintenance-86dd-v1/run/fix.terminal.json) · [Root complete failure and index review](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/048da67876989cfa016f4c126651c78a768b4be0/qa/evidence/utility-evaluation-20261112-36fa/fresh-maintenance-86dd-v1/ROOT_MAINTENANCE_FAILURE_AND_INDEX_REVIEW.json).

A separate authorized read-only retention job, `1a1d1241e8b-2564-1c0b`, copied the actual final index without running Git or changing source. Its full **2,072,488 bytes**, SHA256 `b19fab7a860a4281331096bd6a9c2ab5b6b9ef95ff8411e9f757cd1373380f15`, were retrieved through eleven fixed-version chunks. One offline candidate cleared only the nine standard stat-cache fields and recomputed the trailing checksum. It exactly recovered the independently recorded original index SHA256 `111345e57b5b7276c8fdb4e91302c7bafb6d7c8ca905f83dd1a6c72a28154a16`, at the same length. All **15,188 modes, object IDs, paths, stages, flags, padding and the complete TREE extension** are unchanged. Root independently compared these bytes. This is exact recovery of the original index, **not a new native read of its historical bytes**.

The actual writer and native Git version were not directly observed. The original archive `git diff` ran between the equal post-fix state and the changed final index; official Git documentation describes stat refresh as its default behavior. That supports an inference, not a fabricated writer observation. The narrow successor control sets `diff.autoRefreshIndex=false` only for archive diff and retains the strict raw Git-state equality gate. The old Unknown is retained.

## Prepared one-line compiler repair

New canonical preparation **`9c4a11f61d30e9cc352bf44d56c98909d202a55d`**, tree **`ee42ec7e6289e0ccdbe03a5af0b39216a5a6dab7`**, has the single parent 86dd. It adds only `pub(crate) use super::super::connection::recovered_peer;` in the existing test-only original training-ports module. The underlying recovered connection, original owner binding, recovered origin and assertions are unchanged. All **15,188 leaf modes and object identities** were independently compared; exactly that one source blob changed.

Root verified the complete six-object import packet, including the canonical commit hash. The predicted post-advance inventory is **5,611,182 bytes**, SHA256 `c006da7852740c7c24961a4748744eb1270f25c8d8fe95c2fc873d4dc279d79d`. This is a prediction until matched by an actual forward source transition. At this checkpoint, the new source transition and successor maintenance have **not run**, and the published source branch remains c0f. Existing actual materialization and dependency proofs remain pinned to 86dd; a new source-advance proof must connect them to 9c4 without relabeling historical execution.

[Canonical repair review](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/048da67876989cfa016f4c126651c78a768b4be0/qa/evidence/utility-evaluation-20261112-36fa/preparation/recovered-peer-increment-v1/ROOT_CANONICAL_REVIEW.json) · [complete source-advance packet](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/048da67876989cfa016f4c126651c78a768b4be0/qa/evidence/utility-evaluation-20261112-36fa/preparation/recovered-peer-increment-v1/SOURCE_ADVANCE_PACKET.json) · [minimal source diff](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/048da67876989cfa016f4c126651c78a768b4be0/qa/evidence/utility-evaluation-20261112-36fa/preparation/recovered-peer-increment-v1/ONE_LINE.patch).

### Remaining source work

The successor wrapper must retain the actual restored tools and environment, require the separately observed forward source transition, and disable only archive diff's automatic stat-cache refresh. Original commands remain:

- `just fix -p codex-hepta-intelligence-eval -p codex-hepta-agentd`: **7200 seconds**.
- After complete successful fix, `just fmt --base c0f78493f815780f68b9bf5e390a21314d79311f`: **900 seconds**.

Failed or Unknown fix does not start fmt. The wrapper retains complete source inventories and changed postimages, binds actual tools/V8/UV environment, and preserves the original global concurrency prerequisite. Its v3 HOLD parser format change establishes no restoration success. [Reviewed maintenance history](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/048da67876989cfa016f4c126651c78a768b4be0/qa/evidence/utility-evaluation-20261112-36fa/maintenance-preparation/).

**Ten new protected rows, 39 existing protected updates, adversarial QA and final blob-size allowances remain incomplete pending actual formatted bytes.** The conditional complete-collector membership proposal preserves the original ignored-path semantics and attack assertions; it cannot replace an unmatched actual preimage. No stack limit, per-test deadline, gate budget, collector coverage or verdict is relaxed.

## Utility and authority boundaries

Real authorized ordinary Adopt, evaluated NoUpdate and daemon-plus-Root cold-recovery qualifications each remain **zero**. The required A → original training T → independent B → Adopt or complete NoUpdate → new C → daemon and Root cold recovery needs authentic owners/outcomes, retrievable authorized model material and actual consumer readback.

A matched expert does not establish the strongest deployable baseline. The frozen cost scope remains `TaskLedgersBeforeFinalHoldout`; complete post-cut evaluation, download, activation, serving and maintenance costs are not established. Different keys/controllers or separate reviewers do not establish independent task sources, training lineage, judges and operations. Unsupported action-changing comparisons remain Unknown.

Missing original Model, Selector, Version or FinalUse owners remain closed; an applicable NoUpdate path still needs the original Model owner. Content roots identify bytes without proving continuous availability, lawful authorization or actual adoption. No objective, observation standard, permission or reward contract may be rewritten to manufacture improvement.

[Current independently matched evidence checkpoint](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/048da67876989cfa016f4c126651c78a768b4be0/qa/evidence/utility-evaluation-20261112-36fa/) · [full status and retained limits](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/048da67876989cfa016f4c126651c78a768b4be0/qa/evidence/utility-evaluation-20261112-36fa/README.md) · [unchanged previous PR body](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/048da67876989cfa016f4c126651c78a768b4be0/qa/evidence/utility-evaluation-20261112-36fa/checkpoints/PR6203_1741FILES_BEFORE_RUNTIME_RESTORATION.md).
