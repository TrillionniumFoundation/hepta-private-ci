## Problem and changes

The previous source's native CI exposed two independently reviewable defects: the mocked response helpers recorded requests before the semantic matcher accepted them, and non-elevated Windows setup launches could inherit ambient pipe handles. This draft retains all original failures and adds exact-source repairs and qualification evidence.

Current pure source: `c89540598693697577cda8cba31cb07f6ce65317`; complete tree: `5a7c897a33e4eef48ea8f4bf52eaf48ea7c866ae`. It descends from the previous published source `b0547d2f874c0aeb54dabd3491caa2bee49fcb0b`. The V7, V8 and five-case qualification harness commits are separate from the pure source history.

The latest increment changes seven source paths; the complete reviewed overlay against `2ae5215beaf8d7b7df111a090b82134beae2683d` contains 116 paths.

- Record a mocked response request only after POST, path and semantic matchers accept it. The SSE helper shares that path, preserving its one-response limit. A real TCP loopback regression covers wrong method, path and body, the accepted request and the exhausted one-response limit for both helpers.
- Launch the two non-elevated Windows setup paths with an explicit three-handle NUL allowlist. Preserve the caller token, environment, working directory, path conversion/search contract and original foreground/background scheduling. A native pipe fixture compares ambient inheritance with isolated inheritance using an owned child/job and its original bounded budget.
- Retain the two actual Clippy postimages from the original scoped-fix job: equivalent cancellation method pointers and a short-circuit let-chain. The clean-source gate correctly rejected those original rewrites.
- Apply only the exact formatter output of the successful V7/V8 source operations. All 114 previously formatted paths remain byte-identical through V8.

The new pipe mechanism does not itself prove that the original captured-pipe LEAK is repaired. The original hook timeouts and elevated outside-root deletion failure remain separately recorded until their required native evidence exists.

## Completed exact-source qualification

| Original operation | Actual result |
| --- | --- |
| V7 [run 43042186271](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43042186271), job 130596614396, attempt 1 | Passed in 156.902353 seconds of the original 600-second budget; 18 Python cases; 114 reviewed paths; complete 6,204-file caller scan |
| V8 [run 43046107709](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43046107709), job 130610340916, attempt 1 | Passed in 212.521569 seconds of the original 600-second budget; 18 Python cases; 116 reviewed paths; complete 6,204-file caller scan |

Both original operations retained the complete 75,046-byte golden caller JSON, allowing only the Rust-file count derived from the complete source tree (6200 to 6204). They retained `authorityGranted=false`, zero hits for all thirteen retired names, unchanged Cargo/Bazel locks, and exact before/after bytes and all three Merkle trees. Neither operation ran Rust/native cases or called a model.

The original source checkouts kept their original HEAD/tree and staged formatter output. Their staged edits are not a clean-after claim. The independently reviewed output was materialized in the exact pure source above. V8 changes only the layout of its two new Clippy postimages.

The V7 original ZIP is 7,028,444 bytes; V8 is 7,072,031 bytes, SHA-256 `52ef17f6debe6951b066d27adf00e98451c02359f1a50c3d7e03071e96051709`. Original inner tar files retain the six hidden source members omitted by the expanded ZIP layer's upload setting. Full original record verification uses those original tar bytes; no source gate was rerun to fill that packaging gap.

## Original b054 results remain bound to b054

These observations do not qualify c895.

- Private CI: 34 distinct selected passes; positive repetitions and expected-failing mutants remain separate.
- MEM: 35 Python cases passed and the synthetic fresh-reader mechanism ran. CPU and native phases did not start their tests because package prerequisites failed with DNS errors.
- Architecture: each of the source-head and separate merge-head jobs ran the same 136 Python cases. That is 272 executions / 136 distinct cases, with no Rust tests executed before the prerequisite failure.
- Blocking CI: 37 terminal jobs — 23 success, 6 failure, 4 cancelled and 4 skipped. Full original failures include Fence inventory unavailability, the elevated delete boundary, Mac assertion/timeouts and a prerequisite DNS failure. A successful lint/build target is not a native testcase pass.
- Windows-current: [run 43035590081](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43035590081) ended cancelled after 124 of 167 distinct cases: 122 strict PASS, one LEAK and one FAIL. Forty-three cases did not finish; final source-after and the scheduler's cancellation cause are unobserved.
- Scoped lint: [run 43038376307](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43038376307) returned zero for all three commands. Neuron and core remained clean; Windows sandbox rewrote two files and the unchanged strict source guard failed. The overall job remains FAIL.

The new ordinary-host delete control verified its isolated child token before resume. The real elevated child still deleted outside files and directories in TargetOnly, ParentOnly and Both cells. These are separate outcomes; the ordinary control does not establish elevated isolation.

## Current native qualification

A separate frozen [five-case run 43047914262](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43047914262), attempt 1, was admitted once from harness `5529aeaace80458fb0b1ecae776f95de78c5f9c3`, using this exact c895 source. It selects:

1. The new matched-response loopback regression.
2. The original subagent start and stop integration cases.
3. The new Windows pipe-inheritance regression and original elevated non-TTY LEAK case.

The single 65-minute job also retains three independently assessed scoped fixes for core_test_support, codex-core and codex-windows-sandbox. Original capture, local profile, 100ms LEAK policy, case budgets, zero retries and exact filters remain. Unknown exit or source/tool/helper/lock drift stops later commands. A known native failure stops later native groups; only settled clean integrity permits independent lint. Success requires all five actual cases and all three clean lint phases.

At this publication, the original run is in progress. Native acceptance requires its actual raw/JUnit and identity receipts. Ordinary required CI on this new source is a separate scope.

## Adoption boundary

All ten adoption gates remain open. Source-only proof and archived bytes do not establish retained-memory benefit, original-owner binding, independent trust, deletion propagation, full owner/effect cold recovery or total-cost qualification.

The original provider request remains UNKNOWN and is not replayed under a new key. Provider G remains ignored, no new real model generation is authorized by this change, and original H unknown effects remain explicit. All existing assertions, authority boundaries, deadlines and adoption thresholds are retained.

Evidence and owner checkpoints are tracked in draft PRs [#5889](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5889) and [#5897](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5897). This PR remains draft.
