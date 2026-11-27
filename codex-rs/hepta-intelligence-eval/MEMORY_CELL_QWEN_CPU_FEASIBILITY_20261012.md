# Qwen frozen-reader CPU feasibility gate — observed October 12, 2026

**Disposition: BLOCK the 40-calibration + 72-evaluation CPU-only workflow pending a qualified compute environment.** This is an audited runtime/engineering disposition, not model accuracy, reader-equivalence or production admission.

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

## Engineering decision

The CPU workflow's 180-minute job boundary was reached before even finishing its first 5-k calibration question. With all 40 calibration calls and 72 final test calls pending, merely increasing a single-job timeout or repeatedly queuing more CPU-only runs is not justified. These four observations are insufficient for a measured full-run duration or a confident hardware-independent extrapolation; they are sufficient to **reject the present CPU-only execution budget**.

Only resume the full experimental specification when an authorized execution runner (e.g. GPU or other provisioned accelerated inference) demonstrates a measured frozen-model throughput sufficient for the separate calibration and nine-arm evaluation phases, and demonstrates parity of exact input construction, output decode, source/plan/model pins, budget, citation and procedure semantics. A different model family or changing prompts to fit a budget cannot be credited as MemoryCell gains.

Keep partial raw records and failure denominators, pin and independently verify all artifacts, and preserve no-test-label-before-full-journal rules. No trained/parametric gain, independent citation-entailment review, future-source superiority, lifecycle ROI, or production qualification has been established.
