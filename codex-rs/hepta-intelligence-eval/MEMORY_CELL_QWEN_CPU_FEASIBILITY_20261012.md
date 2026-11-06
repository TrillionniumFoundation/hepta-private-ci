# Qwen frozen-reader CPU feasibility gate — observed October 12, 2026

**Scope-specific disposition: BLOCK the old monolithic 180-minute CPU execution on this measured host.** Subsequent SHA-pinned **sharded CPU** 40-calibration + 72-evaluation executions already completed successfully. This original resource failure is an engineering negative observation, not a global ban on CPU runs, proof of model incapacity, or production admission.

## Exact real observations

- The successful format prerequisite on source `02c12b4aff0d589d10e5ed25d22b05d794ca96a0` was followed by reader job `114395537174` in [run 38111452963](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38111452963).
- GitHub workflow run conclusion: failure; reader job: cancelled at its 180-minute timeout; independent-replay: skipped.
- Original partial artifact: `11696974258`, `memory-strong-rag-calibrated-reader`, ZIP SHA-256 `129351221d56c9668c57e33f8dec79a6443c0252675752085538375b12ca25a8`.
- Source manifest identifies generating commit `02c12b4aff0d589d10e5ed25d22b05d794ca96a0`, frozen input plan SHA-256 `9840a25487af444914dca24c818d98ff798ebc1610ea8dfdd827187c31ad1897`.
- Original completed setup: dependencies and source/index replay; Qwen `qwen-3b` reader staging; entry to actual `calibrate` command at 2026-10-11 06:16:16 UTC. The job was cancelled at approximately 2026-10-11 09:14:47 UTC.
- The raw-answer JSONL contains **four** successful recorded model calls, the first four top-k conditions for one calibration question, out of a planned **40 calibration calls**. No final 72-arm-test calls or independent full replay occurred.

| Calibration condition | Full prompt tokens | Recorded actual answer generation seconds | Stored output |
| --- | ---: | ---: | --- |
| k1 | 504 | 923.308 | `site_ [E1]` |
| k2 | 787 | 1,457.513 | `mode_[E2]` |
| k3 | 1,076 | 2,045.598 | `site_f5750294 [E2]` |
| k4 | 1,370 | 2,641.516 | `site_f5750294[E2]` |

Sum of the four original model seconds: approximately **7,067.9 seconds (117.8 minutes)**. The first recorded attempts already show incomplete or underspecified answers; do not treat a journal status of `succeeded` as strict task correctness.

## Engineering decision, with superseding completed CPU evidence

The original monolithic job's 180-minute limit was reached before completing
its first five-k calibration question. **That exact job layout and observed host
are unqualified**; merely enlarging the timeout or ignoring missing attempts
would not repair it. The four partial responses do not establish model task
accuracy or a hardware-independent inference-speed estimate.

### Later successful, separate sharded Qwen CPU runs

This report originally predated two *distinct source-pinned* sharded CPU
runs that later completed the very same 40 calibration and 72 evaluation
model calls with separate read-only replay:

- [Actions #38148514657](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38148514657), generating source
  `8250698244417eb14994518af05fa6f79e783066`: overall workflow **success**.
- [Actions #38146546731](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38146546731), generating source
  `eba9af092cca1c2875552ffaea2219678143a73c`: overall workflow **success**.
- [Actions #38114667490](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38114667490), generating source
  `c24fad24b65984a6255a8854c6714c141911ff79`: model generation and
  separate read-only replay passed, but the *overall* workflow failed its
  unrelated formatting job.

The exact outer ZIP identities, inner manifests, original reader/prompt
SHA consistency, 40/72 raw-answer censuses and cross-run discrepancies
were independently checked in
[MEMORY_CELL_STRONG_RAG_THREE_RUN_REPLICATION_20261012.md](MEMORY_CELL_STRONG_RAG_THREE_RUN_REPLICATION_20261012.md).
All three chose top-k=1; full-path entity/time and organized each achieved
8/8 original task answers and 4/8 complete program-declared citation chains.
The organizer had **zero additional task successes or complete chains**;
it saved 573 input tokens across eight reads. These are the same eight
authored, exposed questions, not new independent families or independent
semantic citation review.

**Do not repeat the old monolithic CPU job** solely to recreate an already
completed sharded experiment. Any new CPU/GPU runtime must separately
measure and publish capacity, generation parity, source/model/citation
identity, complete attempts and resource costs. Original reader failures
and variation across hosts remain first-class evidence; sharded research
success is not the same as a production-qualifying latency SLO.

Keep partial raw records and failure denominators, pin and independently verify all artifacts, and preserve no-test-label-before-full-journal rules. No trained/parametric gain, independent citation-entailment review, future-source superiority, lifecycle ROI, or production qualification has been established.
