## Problem and changes

Native CI on the previous source exposed two test fixtures that still called the V1 subagent namespace while the session exposed V2 `collaboration`. Once the response recorder correctly rejected unmatched requests, both fixtures recorded zero child requests. Separately, the pinned Fence v0.10 action failed before checkout with `local_control_inventory_unavailable`, preventing the original blob policy checks from running.

Current pure source: `d0f6507e08f7f5c5855f5164d07c049a34d1a6d9`; complete tree: `658fa040046285116b1fd81b94ff8c96444072ad`. It descends from the previous published source `c89540598693697577cda8cba31cb07f6ce65317` through pure V9 `408226fc670bfa8c1736e2b264750b549237b7c4`. All qualification harness commits remain outside this pure source ancestry. The new increment changes two paths; the cumulative reviewed overlay against `2ae5215beaf8d7b7df111a090b82134beae2683d` contains 118 paths.

- Update the two existing spawned-child fixtures to the V2 namespace already exposed by the session. Distinguish the child's `agent_message` request from the parent's function-call continuation. Preserve all assertions, the original 2-second wait and 10ms polling interval, one-response mock limit and production runtime behavior. The neighboring comment now describes the actual asynchronous child request.
- Pin the independently reviewed Fence v0.13 complete action at `c7675fea986c29f1d655753a7a61fd6b4141be8f`. This changes one workflow line, including its matching version comment. Audit mode, permissions, 30-minute limit, original policy steps, 512000-byte threshold and allowlist remain unchanged.
- Retain the preceding matched-response recorder repair, explicit three-handle setup inheritance allowlist, two actual Clippy postimages and exact V7/V8 formatter output. All 117 actual V9 postimages remain byte-identical through V10.

The Fence release contains broader upstream changes; the review does not describe it as a diagnostic-only patch or a complete release security audit. The historical v0.10 failure subreason remains UNKNOWN. The elevated outside-root deletion failure remains open.

## Completed source-only qualification

| Original operation | Exact outcome |
| --- | --- |
| V9 [run 43054829731](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43054829731), job 130641359569, attempt 1 | 211.376484 / 600 seconds; 18 Python PASS; 117 overlay paths; all 6,204 Rust files; zero formatter changes; clean before/after |
| V10 [run 43060276203](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43060276203), job 130660630288, attempt 1 | 235.941709 / 600 seconds; 18 Python PASS; 118 overlay paths; all 6,204 Rust files; zero formatter changes; clean before/after |

Both full original ZIPs and canonical inner archives were independently verified and the unchanged offline readers replayed in separate directories. V10's original ZIP is 7,243,400 bytes, SHA-256 `bb1cca9742144cc0c1bfe7bf3d5f7081ab651ea8fedd6a51041f2fe5fc8361ff`; its original inner archive contains all 387 canonical members. Expanded ZIP upload omissions do not replace the canonical source records.

The full 75,046-byte golden caller JSON is retained. Its sole permitted difference remains the Rust-file count derived from the complete tree, 6200 to 6204. `authorityGranted=false`, all thirteen retired-name zero-hit checks, unchanged Cargo/Bazel locks, all postimages and all three Merkle trees were verified. These operations ran no native project cases or model calls. Because V10 produced no formatter edits, the exact pure commit above is also the verified formatted source; no synthetic formatter commit was added.

## Fence action qualification

The separate original [run 43055103354](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43055103354), job 130642329146, attempt 1, completed all fourteen steps successfully on the c895 anchor. The retained bytes include all seven actual action files, the complete 2,203,880-byte executable and its bundle provenance, original ZIP, full job log, exact source snapshots, seven Python policy passes and the final Action post report.

The post report is audit-mode `healthy`, with network verification and preserved sudo/container controls. It explicitly reports `protection_available=false` and `ready_observation_only`; this is not block-mode enforcement. The isolated changed-file check covered one added harness workflow, not this full PR. Source snapshots bracket the original checks and precede post hooks; the later full raw log and terminal API supply the post outcome. Full required CI on this new source must establish the actual PR-range policy result.

## Native evidence and remaining lint

The original c895 [five-case run 43047914262](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43047914262), job 130616746852, attempt 1, recorded five actual native PASS, zero FAIL, zero LEAK and zero SKIP. Three fresh JUnit UUIDs, raw logs, exact source, both locks, actual tools and two real helper bindings agree before/after each native phase. The passed cases are the matched-response loopback, original subagent start and stop, setup pipe inheritance, and original elevated non-TTY output case.

That whole job remains unqualified. The first `core_test_support` scoped fix passed cleanly. The following `codex-core` fix was interrupted near the original job limit with an UNKNOWN command exit and missing phase-after receipts. The Windows sandbox fix did not start. A later clean collection snapshot does not manufacture either missing result. The original job ended cancelled; no retry or budget extension was used.

Two new, separate operations are bound to the exact V10 pure source:

- Two original V2 fixture cases plus an independently assessed clean `codex-core` fix: [run 43061843610](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43061843610), harness `ca9ab8c0d07d1a236ef3c4b76a22f0a131d409ae`, admitted once. Original exact filters, default capture, 100ms LEAK policy, one test thread, zero retries and the single 65-minute job remain.
- Real helper build followed only by `just fix --locked -p codex-windows-sandbox`: harness `23d9f41532e5e6310ca791a5b849ab1cff7466eb`, admitted once on its own branch with the same 65-minute job bound. This operation runs no native tests and does not assume that the previous five cases passed.

At this source publication both operations are pending. Their actual terminal receipts must settle their own scopes. An unknown exit, any source rewrite, or source/tool/helper/lock drift remains a failure; neither operation replays the old interrupted core phase as if it had settled.

## Original c895 hosted results

These results remain attached to c895 and do not qualify the new V10 source.

| Original scope | Retained result |
| --- | --- |
| Private CI | 34 distinct selected PASS; two repeated positive controls and four mutant executions, including two expected failures, remain separate |
| MEM | 35 Python PASS and the synthetic fresh-reader mechanism; CPU/native tests did not start after prerequisite DNS failures |
| Architecture | Each of the source and separate merge lanes has 136 receipt-indexed Python cases plus eight raw-only preflight cases: 144 per lane, 288 executions / 144 distinct cases; no native tests before apt failure |
| Blocking CI | [run 43048568477](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43048568477): all 37 jobs terminal, 20 success / 9 failure / 4 cancelled / 4 skipped; seventeen complete original job logs retained |
| Windows-current | [run 43048569129](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43048569129): cancelled after 139 of 167 distinct cases, 138 PASS / 1 FAIL / 0 LEAK; 28 cases lack terminal results and final source-after is absent |

The Mac blocking lane has 402 strict passing targets, three FLAKY, four FAILED, three TIMEOUT and 172 SKIPPED. Its displayed "405 pass" includes the three FLAKY targets. The displayed core-all bodies cover seven of the sixteen reported failed attempts; absent bodies are not reconstructed. Cargo-deny's complete raw remains unavailable, and eleven original Bazel artifact ZIPs are indexed as metadata-only. Cancellation causes remain UNKNOWN where original metadata does not establish them.

The elevated delete case still deletes outside files and directories in TargetOnly, ParentOnly and Both cells. Its successful ordinary-token control does not prove elevated isolation. Mac memory and code-mode failures remain open; static cleanup observations and incomplete logs do not establish a unique root cause.

The same eight raw-only Architecture cases were also recovered from b054: its historical total is 288 executions / 144 distinct cases, not the earlier receipt-only 272 / 136. The original receipts and explicit accounting addenda are preserved.

## Adoption boundary

All ten adoption gates remain open. Source checks, scoped native passes and recoverable archives do not establish retained-memory benefit, original-owner binding, independent trust, deletion propagation, full owner/effect cold recovery or total-cost qualification.

The original provider request remains UNKNOWN and is not replayed under a new key. Provider G remains ignored; no new real model generation is authorized by this change. Original H unknown effects remain explicit. Assertions, authority boundaries, case deadlines, retry policy, source exposure requirements and adoption thresholds are unchanged.

Evidence and owner checkpoints remain in draft PRs [#5889](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5889) and [#5897](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5897). This source PR remains draft. New ordinary CI results must be reported against this exact V10 head.
