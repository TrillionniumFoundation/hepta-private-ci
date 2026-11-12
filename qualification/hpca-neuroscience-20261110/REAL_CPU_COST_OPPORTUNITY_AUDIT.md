# HPCA real CPU LoRA — paired opportunity and execution-order audit

**Decision: HOLD_NO_GO / DENY_ALL.** This is a new *read-only reanalysis* of the **same eight already completed actual-model runs** in #5861, alongside the probability audit #5870. It does not perform a new training run, infer independent efficacy, verify a real owner, or authorize a model version.

## Source of truth and exact reproduction

- Raw archived bytes: `real_cpu_clock_v1_RESULT.json`, SHA-256 `caf20e60f0e0dc09b78b9c5433727dd028a2b6627c945d8dee7b54c238a66615`.
- Code identity of the actual training execution: `native_lora_clock.py` SHA-256 `0b6f2cb893ee1909adcd88fe4381560ad337a0fe59dd886548b665bc95c0d084`. That script and the raw archive are **unchanged** by this PR.
- Run `python3 -m unittest -v test_cost_opportunity_audit.py` from this directory and `python3 cost_opportunity_audit.py > /tmp/hpca-cost-opportunity.json`. Python standard library only; no model/GPU/external provider used.
- Exact code and sealed archive bytes are checked; every archived logical training step is matched to the published schedule and source event. The tests **do not certify physical source custody**, training provenance, or independent evaluator identity.

## Observed original run (not an independent replication)

Each training pair shared the same 12 ordered examples, equal **total** input tokens, 12 optimizer steps, and 829,440 declared parameter-element updates. **Within parameter groups**, exposure differed as prescribed by the schedule:

| Training seed | Uniform early / late tokens | Heterogeneous early / late tokens | Uniform early / late steps | Heterogeneous early / late steps |
| --- | --- | --- | --- | --- |
| 11 | 124 / 120 | 180 / 64 | 6 / 6 | 9 / 3 |
| 17 | 140 / 128 | 206 / 62 | 6 / 6 | 9 / 3 |
| 23 | 125 / 135 | 188 / 72 | 6 / 6 | 9 / 3 |
| 29 | 135 / 134 | 207 / 62 | 6 / 6 | 9 / 3 |

This per-group allocation is part of the clock-policy **treatment**, not an error in the aggregate-token equality assertion. It prevents interpreting the result as a comparison with group-wise matched information or a different learning rule at an identical per-group opportunity. A separate fixed-rate/coverage control would be needed to isolate cadence from exposure.

**Run-order confound:** All four seeds executed `uniform` *before* `heterogeneous`. The original source uses the fixed `for arm in ("uniform", "heterogeneous")` order. Consequently host cache, temperature, disk state and temporal load cannot be ruled out as explanations for cost differences. On the archived per-arm receipts, summed wall times are **9.914990192 s uniform** vs **10.154832913 s heterogeneous**, and summed process CPU times are **34.658762908 s** vs **35.631212609 s**. These are within-run observations, not arm causal cost effects. The single observed **1,003,520 physical read bytes** belong to seed 11 uniform; all later arms report zero physical read bytes. This is consistent with, but **does not prove**, a cold-first run/cache effect; page-cache reads and the full host cost are not accounted for by this metric.

These process CPU totals must not be added to elapsed wall time as if distinct work. Disk I/O counters, energy, total model acquisition, inference/failed requests, host idle power and independent owner costs are not a matched complete-cost contract. **No normalized net utility or production speedup** is established.

## Next pre-registered actual experiment

Counterbalance execution order by seed with equal allocation to `U→H` and `H→U`, or randomize order before running; ensure the model-creation, cache reset/warmup, source stream, training/evaluation opportunity, adapter persistence, host quota and measurement lifecycle are pinned. Report per-group source occurrence counts and token exposures, grouped gradients/optimizer updates, measured full resource costs and failures; compare matched rate/coverage and normal-gradient controls. Never edit original receipt data to mimic a counterbalanced run.

A genuinely independent evaluator must hold future B tasks unavailable during A and model selection, followed by authorized **NoUpdate/Adopt**, a different real C effect, old/OOD retention and original Owner cold recovery. Add the full Core×NDU 2×2 and dense/sparse delayed ACT/CTRL arms. All current gates remain **HOLD_NO_GO**; this audit is a clarification of the scientific/cost qualification blocker, not a new pass.
