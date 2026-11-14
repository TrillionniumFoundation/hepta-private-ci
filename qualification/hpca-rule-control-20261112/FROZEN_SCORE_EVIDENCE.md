# HPCA frozen grammar control: post-freeze content score — 2026-11-12

**Verdict: HOLD_NO_GO / DENY_ALL.** This is a read-only **post-hoc development score**, not an independent prospective B evaluator, general-purpose capability claim or production update.

## What was actually executed

- Parent research-only comparator: [#6194](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6194), exact pre-audit HEAD `13c5f14213cb925c3c7d4471b4c6c8352619f4f1`; its original rule run previously generated all 64 content predictions without evaluation labels. No preexisting source, model or candidate was rewritten.
- Immutable rule output: `qualification/hpca-rule-control-20261112/ORIGINAL_STDOUT.json` at `13c5f14213cb925c3c7d4471b4c6c8352619f4f1`; full UTF-8 text SHA-256 `f2a01301f9ddc1f827e9e3dc53428410329a09cfdc101587d0b960ec8b00b449`.
- Frozen development truth: `qualification/hpca_routed_content_v1/EVAL_LABELS.json` at the archived [#6172 evidence HEAD](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/65d688af66f3797a4d6a61a8f4adf6a5a06b7689); full UTF-8 SHA-256 `7eb030572f8dccc0b9728966dc29307efed00d4424104e02aea916851018bdb1`, matching the frozen `PLAN.json` data digest.
- Original rule prediction-map SHA-256: `514a42afa42e95078a5236fe26171b5f475dbd0a8533e35e2f49fe493e9ccf72`, independently recomputed from sorted canonical JSON and matched to the original unscored stdout. Rule output declares `evaluation_labels_loaded=false`, 0 model forwards, 0 optimizer updates, 64/64 **training** agreement.
- **New native scoring execution:** configured HeptaRuntime `ai395`, durable process job `1a1ceb4711e-2564-17e4`, `/usr/bin/python3 -c <scoring source>`, 100% CPUQuota, 536,870,912-byte MemoryMax, 20-s deadline. Durable terminal status **succeeded**, exit 0, stdout **357/357** bytes, stderr **0/0** bytes, no timeout, no cancellation. This is a new scorer of already-generated predictions, **not a model generation/training run**. The executable source is transcribed in [score_frozen_content.py](score_frozen_content.py); the source file adds a terminal newline not material to Python semantics.
- [FROZEN_SCORE_NATIVE_ORIGINAL.log](FROZEN_SCORE_NATIVE_ORIGINAL.log) preserves the exact emitted one-line stdout; [FROZEN_SCORE_NATIVE_STDOUT.json](FROZEN_SCORE_NATIVE_STDOUT.json) is a **reformatted**, not byte-identical, JSON representation of it. No model inference or hidden data custody was conferred by this scoring process.

## Observed result (64 distinct development questions; invalid responses count incorrect)

| Fixed candidate | Correct / 64 | Interpretation |
| --- | ---: | --- |
| Frozen explicit grammar rule, zero neural updates | **64 / 64** | color: 32/32; shape: 32/32 |
| Original frozen model, no update | 32 / 64 | 50%; output from #6172 native summary |
| Routed trained private head; seeds 11,17,23,29 | 27,32,24,37 / 64 | mean 30/64, below frozen base |
| Shuffled same-information route; seeds 11,17,23,29 | 29,32,24,33 / 64 | mean 29.5/64 |
| No eligibility; seeds 11,17,23,29 | 32,32,32,32 / 64 | unchanged base |
| Scalar-projection arm; seeds 11,17,23,29 | 24,32,24,32 / 64 | changes information; separate ablation |

The rule is 32/64 above the unchanged base, and 27/64 above the best of the four observed routed seeds. These are **descriptive same-task differences**, not paired prospective confidence bounds. The four training seeds reuse the **same 64 content questions**; they are not 256 independent examples. The reported base/seed numbers are read from the frozen #6172 `SUMMARY.json`, independently audited there, and were **not re-inferred in this new scorer**. Neither test task labels nor rule predictions were altered.

## Mechanism inference and cost boundary

This development panel encodes a complete color/shape fact in every prompt and asks literal equality; a strict deterministic grammar is a formidable task-specific control. A routed-gradient improvement over a weak or invalid neural baseline therefore cannot demonstrate that biological-style local credit, heterogeneous clocks, or NDU are needed for this task. The grammar is intentionally **unsupported** on the 32-task retention panel and untested on independent, source-disjoint, real-world semantic OOD tasks. No claim of full model replacement follows.

The original rule-execution process in #6194 recorded 0 model/optimizer calls, roughly 0.007912s user + 0.003956s system CPU, 20,792 KiB peak RSS. This new scorer's **own CPU/wall measurements were not recorded** (only its terminal status and complete stdout). #6172's pretrained-base, 64 model feature prefills, 4,096 manual SGD slots, 1,632 generations and cold checkpoint reads incur substantially different work; queue, prior model pretraining, data creation, energy, retention and Owner lifecycle are excluded. There is **no all-in cost-matched utility trial here**, and the grammar's richer explicit pattern prior must be accounted for.

This score is **post-hoc**, with researcher-visible labels, and can be independently recalculated from pinned files; it is **not** independently held future B. Frozen 16 candidates precede this scoring, but that chronology does not retroactively seal the evaluator. The #6172 original base retention competency gate failed (8 correct / 14 valid / 32); do not claim retention or OOD acceptance. No new native ACT/Cell/Agentd integration, owner-approved Adopt/NoUpdate, next-task use, cold owner recovery, or NDU×core 2×2 was executed.

## Original HPCA parent and unresolved gates

Original [#5739](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5739) still has HEAD `15daf24ef21e9d038919fef53b82e3a6fb70358d`. Versus first real micro-run source `f07f41f9a396f7096211b9cc984543b773ce719b` there are **two later documentation-only commits** adding `EVIDENCE.md`; the original nine tests / 16 seeds were not rerun as native training evidence. The later exact-head [micro workflow 42824577472](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42824577472) succeeded, but the same-head [blocking-ci 42824577715](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42824577715) failed (canonical metadata gate, cargo-deny and multiple Bazel lanes). Broad CI is not green, and those unrelated failures are not waived by this qualification.

**Remaining independent release gates:** held-out original external evaluator; fair source-, opportunity- and cost-matched, per-family direct-gradient/contextual/NDU Core×Controller 2×2; dense/sparse delayed effects; MEM fact/episode/procedure/recovery, deletion non-resurrection; real PERC/ACT retention and OOD; Agentd's authorized A→learning→frozen independent B→NoUpdate or Adopt→different next task→cold owner restart. All remain **HOLD_NO_GO**. No main merge, production weight adoption, autonomous release, or deployment.
