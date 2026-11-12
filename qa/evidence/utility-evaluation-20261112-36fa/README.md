# Hepta utility evidence: actual maintenance and remaining qualification

Checkpoint observation: **2026-11-12 21:01:19 UTC**. This checkpoint retains **2,268 evidence files**. All 2,138 previous paths are retained; only this current README is updated. Its previous exact bytes and the previous exact PR body are archived in `checkpoints/README_2138FILES_BEFORE_V5_COMPLETION.md` and `checkpoints/PR6203_2138FILES_BEFORE_V5_COMPLETION.md`. Multiple paths for identical original bytes are aliases, not independent observations.

**Draft / HOLD. The published PR #6203 source remains `c0f78493f815780f68b9bf5e390a21314d79311f`, tree `313ee34febc8ccc54c611ab56286e289518c63cb`; its focused and source-closure gates failed. In the actual maintenance repository, the reviewed 9c4 compiler repair is now applied, the original scoped fix and formatter both succeeded, and all 43 actual Rust formatting changes have been reviewed. The final protected-row/QA integration, required final format and exact-source qualification are still pending. Real authorized task-chain qualified outcomes remain zero.**

## Current actual source and maintenance

| Observation | Actual result |
| --- | --- |
| Native HEAD / committed tree | `9c4a11f61d30e9cc352bf44d56c98909d202a55d` / `ee42ec7e6289e0ccdbe03a5af0b39216a5a6dab7` |
| Actual working physical tree | `65b898bad23cd58c7f6fd53fafe618f9cf9562dc`; 15,188 physical leaves; 43 changed Rust files; dirty status preserved |
| Full physical inventory | 5,614,211 bytes; SHA256 `3f28f2ea4b78a0b3faa41024bd1664c2201ad21cb3c3f3465cb40192b034f58f` |
| Original V5 maintenance | Job `1a1d16f37be-2564-1c4a`; normal exit 0 at **20:27:30.671 UTC**; complete durable 80,922-byte stdout, no timeout or truncation |
| Original scoped fix | `just fix -p codex-hepta-intelligence-eval -p codex-hepta-agentd`; original 7,200-second limit; exit 0; no timeout/output cap; zero source postimages |
| Original scoped format | `just fmt --base c0f78493f815780f68b9bf5e390a21314d79311f`; original 900-second limit; exit 0; no timeout/output cap; 43 Rust postimages |
| Final V5 audits | Complete source/Git audit and all 17 original inputs verified; raw Git metadata unchanged; no source ref update; zero tests |

The complete original RESULT is 15,927 bytes, Git blob `28fd9e0970a977881971a3e5c2ddaf73f69a58a0`. Both complete stage terminals and the original supervisor terminal are retained. The 79,195-byte fix log was recovered exactly from its original stdout interval and matches the original recorder's hash. The two execution-result JSON files were recovered by the original serializer from the retained terminal fields; their identities match the original artifact index. These are explicit byte recoveries, not new executions or fabricated original reads.

[Actual RESULT](maintenance-v5/RESULT.json) · [original normal supervisor](maintenance-v5/OBSERVED_STATUS_03.original.json) · [fix terminal](maintenance-v5/fix.terminal.json) · [fmt terminal](maintenance-v5/fmt.terminal.json) · [complete stdout](maintenance-v5/COMPLETE_STDOUT.log) · [exact log recovery](maintenance-v5/EXACT_LOG_AND_COMMAND_RECOVERY.json) · [Root actual review](maintenance-v5/ROOT_ACTUAL_MAINTENANCE_REVIEW.json).

The full original inventory was independently recovered using the exact pre-format inventory, all 43 actual before/after rows and the original inventory serializer. Its raw identity, deterministic gzip identity and all five original encoded-part identities match. This recovery is not a new native physical read. The actual working physical tree is different from HEAD's committed tree, and the dirty status is not erased to obtain a convenient identity. [Inventory recovery and complete encoded parts](maintenance-v5/inventory-exact-recovery/).

## Actual Rust review and shared-lock capture

The independent static review checked all **43 × 2** actual raw byte sequences and their length/SHA256/Git identities. Import paths, aliases, visibility and attributes match; module path/name/attribute bindings match. All executable literals, macro calls and **122 assertion invocations** retain their token contents and order. Remaining changes are formatting: import/module ordering, optional commas, 15 individually reviewed single-tail-expression blocks and nested generic type layout. No non-format semantic delta was identified. This is static source review, not a compiler/runtime proof or a transferred test PASS.

[Complete static review](actual-fmt43-review/REVIEW.md) · [per-file pins and classification](actual-fmt43-review/SEMANTIC_REVIEW.json) · [provenance and availability](actual-fmt43-review/PLACEMENT.json). The raw 1,236,802-byte transition JSON is recovered from the lossless [original gzip companion](maintenance-v5/fmt.after.postimages.json.gz.part-001.b64); its computed raw Git identity is not represented as a separately uploaded object.

The unique read-only handoff job **`1a1d1880477-2564-1c56`** ran **20:51:56.509657–20:52:05.270030 UTC** and reached normal **exit 0 at 20:52:05.301 UTC**. The complete 22,007-byte original RESULT reports `CAPTURED_ACTUAL_POSTFMT_REVIEW_REQUIRED`, all **73 requested paths**, the same full 3f28 inventory before and after, and verified complete source/Git/lock and original-input audits. It performed no source write, extractor or test. Its shared lock refers to the actual task-owned coordination inode; this proves coordination of cooperating task operations, not machine-wide exclusion or historical ownership.

The original normal supervisor, complete RESULT and 455-byte stdout have been recovered and checked. At this checkpoint, transfer of the original 626,888-byte compressed 73-file packet is still incomplete: three fixed-version chunk reads returned MCP timeouts. The original timeout records remain preserved; only missing blocks will be read at the same version. The collector was not rerun. The packet is not yet claimed as fully copied off-host, and the extractor has not run. [Root normal/result review with this retrieval limit](postformat-capture-v5/ROOT_NORMAL_AND_RESULT_REVIEW.json).

[Actual capture RESULT](postformat-capture-v5/launch/RESULT.json) · [original normal supervisor](postformat-capture-v5/launch/STATUS_01.original.json) · [complete capture stdout](postformat-capture-v5/launch/COMPLETE_STDOUT.log) · [exact launch review](postformat-capture-v5/root/EXACT_LAUNCH_REVIEW.json).

## Preserved failed attempts and their meaning

| Attempt | Preserved outcome |
| --- | --- |
| Original 86dd maintenance, `1a1d10d8ad0-2564-1bff` | Fix 101 with test-only `recovered_peer` E0425; no fmt or tests. A separate raw-index audit failure leaves the original overall RESULT **Unknown**. |
| Exact index diagnosis | Only nine standard stat-cache fields differ; all 15,188 object IDs, modes, paths, stages, flags, padding and TREE extension match. Actual writer/version were not directly observed; the old Unknown remains. |
| 9c4 source advance, `1a1d1490a3b-2564-1c26` | Normal exit 0; actual single test-port re-export applied; all source/Git/input audits verified. No Cargo, formatter, tests or remote ref update in that operation. |
| Maintenance V4, `1a1d15cdf42-2564-1c3a` | Normal exit 1 / `FAILED_PRECONDITION`, before fix/fmt. Recovered original RESULT identifies the unchanged active/unknown same-UID Cargo/formatter guard. Both final conservation audits verified. |
| V4 process identity | The historical PID array was not written before the guard raised. The specific PID and active-versus-unreadable cause remain **Unknown**. A later empty-array observation does not reconstruct that history. |
| V5 control change | New output/config paths and one original process-array retention write before the same check. No process guard, stack limit, command selection, timeout or audit was relaxed. |
| Transport timeouts | Original SDK timeout records remain separate. Later complete original readbacks resolve current retrieval; they do not rewrite earlier observations or imply repeated execution. |

[Original 86dd failure/index review](fresh-maintenance-86dd-v1/ROOT_MAINTENANCE_FAILURE_AND_INDEX_REVIEW.json) · [complete source-advance proof](source-advance-9c4-v1/actual/RESULT.json) · [complete V4 failure](maintenance-v4/RESULT.json) · [Root V4 recovery review](maintenance-v4/ROOT_DETAILED_RECOVERY_REVIEW.json) · [exact V5 control diff](maintenance-preparation/v5/DRIVER_V4_TO_V5.diff).

The actual 86dd independent materialization and dependency restoration remain historical seeds, connected to 9c4 by the actual strict source advance. Their complete originals are retained. The restoration used six pinned downloads and six original preparation commands; its proposed foreign-job exception was not exercised. None of these preparation successes is a mechanism test or task-utility result. Earlier materialization/restoration failures, object-history limitations and exact large-audit recovery provenance remain in the [previous complete checkpoint narrative](checkpoints/README_2138FILES_BEFORE_V5_COMPLETION.md) and all unchanged evidence paths.

## Published c0f qualification, which does not transfer

| Original c0f gate | Actual result |
| --- | --- |
| Scoped fix / fmt | Exit 0 / 0, no source diff |
| Full evaluator library | **163/163 PASS**, including four incomplete-evidence regressions |
| Focused native | **81 PASS / 28 FAIL**, 109 cases; exit 100; 960.6167 seconds; no whole-command timeout/output cap |
| All / ordinary / Root | Not started after focused failure |
| Source closure | **FAILED**, original 600-second limit; exit 124; 602.9541 seconds; incomplete summary |
| Caller self-test / full caller | Exit 0 / **PASS**, full caller 4477.5591 seconds within original 4800-second limit |
| Whole source-gate job | **FAILED**, exit 1 |

Focused failures comprise 24 stack overflows, two actual 60-second per-test timeouts, one InvalidBinding and one OwnerUnavailable. The first-SIGSEGV evidence explains one concrete stack deficit, not every failure. At the historical **18:19:17 UTC** observation, hosted CI had zero check runs, check suites and workflow runs, and pending combined status with zero entries; this is not hosted CI success or a current observation of another SHA.

[Complete native originals](native-c0f-terminal-complete/) · [source-gate originals](source-gates/c0f78493-v1/) · [first-signal diagnostic](native-c0f-first-signal-diagnostic/) · [hosted observation](hosted-ci/c0f-20261112-1819/OBSERVATION.json).

## Required final integration and exact-source gates

The sole non-Rust writer must derive 39 existing protection updates, ten new rows and the associated QA/allowlist changes from actual formatted files. The read-only extractor remains separately bound to actual source identity, original maintenance and shared-capture evidence; preparation is not permission to invent source pins or a result.

After those last code edits, the repository's original AGENTS order requires **one separately recorded `just fmt --base c0f78493f815780f68b9bf5e390a21314d79311f` with the unchanged 900-second limit**. Do not repeat fix. Review actual postimages before freezing the final canonical source. If protected source changes, resynchronize its exact guards; do not freeze stale markers. The unchanged formatter selects Rust and Python under scripts/.github; it does not automatically format QA, CALLERS.toml or the blob-size allowance text.

The final source then needs its own original complete evaluator, helper build/verification, focused, all/ordinary/Root and independent source-closure/caller results. The complete evaluator command remains unfiltered; **163 is the c0f historical count, not a target, ceiling or equality check for the final source**. Counts and required cases must come from fresh JUnit plus the final source inventory. Preserve original 8 MiB stack, retry zero, all existing nextest overrides and every original command/suite deadline. Failure or missing terminal stops dependent stages under the original policy.

Native tracked/nonignored snapshots and complete physical inventories are different scopes. Native JUnit writes are retained honestly. Source gates use their own independent read-only final-source clone. No old PASS qualifies 86dd, 9c4 or a future successor. [Corrected V2 plan](exact-source-qualification-plan-v2/PLAN.json) · [exact final format order](exact-source-qualification-plan-v2/FORMAT_ORDER.md) · [original gate commands and limits](exact-source-qualification-plan-v2/HANDOFF.md).

## Utility and authority limits

External user/task objectives, outcome observations, permissions and public reward contracts stay outside the learner's discretion. Adopt, complete NoUpdate, InsufficientEvidence/Unknown and reproducible Objective Fraud retain distinct meanings. Missing original Model, Selector, Version or FinalUse owners remain closed; NoUpdate does not bypass an applicable Model-owner requirement. Privacy, authorization and required tasks cannot be compensated by average quality.

Real authorized **A → original training T → independent B → Adopt or complete NoUpdate → new C → daemon and Root cold recovery** qualified outcomes remain **0**. A matched expert is not proof of the strongest deployable baseline. Frozen cost scope remains `TaskLedgersBeforeFinalHoldout`; complete post-cut evaluation, download, activation, serving and maintenance cost closure is unestablished. Different keys/controllers/agents do not establish independence of task sources, training lineage, judges or operational control. Unsupported action-dependent identification stays Unknown. Content roots identify bytes; they do not independently prove ongoing availability, authorization or actual consumer use.

No merge, production activation, adoption, payment/fraud determination or completed net-utility improvement is claimed.
