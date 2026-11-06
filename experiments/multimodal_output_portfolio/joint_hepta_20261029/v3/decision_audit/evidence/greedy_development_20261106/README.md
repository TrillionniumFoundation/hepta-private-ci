# Development greedy integration evidence

Source publication `f62034b45ca30573f17caa830ed21c9c641455ad` adds the 140-line `DevelopmentGreedy` adapter, 229-line focused controls and its scope document. A, C and the SD trainer remain unchanged. The adapter actually loads the externally pinned C checkpoint and completed-fit receipt inside the original runner's controller interval and scores legal public-View actions.

**This is a synthetic development mechanism, not a qualified strong baseline or a real independently labelled R2 controller fit.** All six scientific gates remain open.

## Both cold-process results

| Run | Existing synthetic checkpoint | Actual runner actions | Predictions | Terminal |
| --- | --- | --- | ---: | --- |
| Author's unpatched canary | 600-update shared C fixture | draft → text → stop | 18 (5, 6, 7) | delivered; semantic acceptance remains pending |
| Independent probe | Reused 160-update C fixture | perceive → text → draft → verify | 22 over 4 decisions | incomplete at horizon; no STOP delivery |

The second result is retained as incomplete. It was not retrained or relabelled to obtain a completed example. Both runs compare every recorded score against unchanged C prediction and preserve original runner events. These are different synthetic fixtures and not a paired quality comparison.

Six author controls pass, with zero errors/failures. Four additional independent probes pass: cold original-runner execution; cancellation during scoring; cancellation during final decision-trace write; and rejecting instance reuse after initial POLICY write failure. The reviewer reused the prior checkpoint and performed no new fit. These probe counts are not additional R2 samples.

Unknown/untrained and illegal action scores remain null. Incomplete legal coverage produces an explicit conservative STOP fallback, without a fabricated zero estimate. Strictly positive scores and canonical ACTIONS-order tie-breaking drive ordinary selection. Refine remains legal after a previous actual draft even when a later plan change invalidates the current image. Calls are bounded by seven predictions per decision and 32 decisions.

## Costs and write failures

C already predicts utility increment net of historical controller/action costs; D uses that value unchanged. Lazy loading, every selected/unselected/failed score and trace writes are charged by the original runner. Diagnostic timers are subsets and are never added again.

The author's six-control observed interval uses 2.716937743 s current-process CPU, 1.547164 s waited-child CPU and 3.045380354 s wall. The independent four-probe interval uses 0.155362431 s current-process CPU, 1.033761 s waited-child CPU and 0.444830083 s inclusive wall. These are separate executions; within either, nested fit/runner/controller/prediction periods are not additional costs. Startup, final receipt writes, energy, physical I/O and full authoring/publication costs are not completely measured. The deadline fault test explicitly shifts the runtime clock and is not physical performance data.

Trace-write failure or cancellation prevents action dispatch and permanently fences the policy instance. An in-memory row and the original runner cancellation record do not replace a missing durable decision file. SIGKILL, host failure, durable recovery and current-versus-historical cost calibration are not qualified.

## Retained evidence

`raw-evidence.tar.gz` preserves 341 original files, including the official six-case source/fit/capture/cold-run directory, the independent probes and raw runner/policy records, final source snapshots and the initial failed probe. That initial exit 1 came from a stale harness expectation after the fence fix was already effective; it is not recorded as an observed product regression. `PACKAGING_ATTEMPT1.json` separately retains a rejected stale-document hash during sealing; it did not trigger a test rerun.

`EVIDENCE_MANIFEST.json` enumerates original files; `ARCHIVE_MANIFEST.json` and `INDEX.json` bind the archive, with complete indexed-file readback. `REVIEW.json` binds the exact final source and scope. `AUTHOR_FROZEN.json` also retains a previously completed duplicate author packaging step (0.860518106 s wall, 0.644159819 s CPU); its raw data is covered by the canonical archive, so the duplicate compressed file is not republished. The publication readback's own failed setup and explicitly unknown cost are retained in `INDEX.json`.

No independent evaluator custody, new source-cluster cohort, semantic/CE improvement, actor-critic, planner, complete NDU or production adoption follows from these controls.
