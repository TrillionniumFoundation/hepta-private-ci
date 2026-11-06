# MemoryCell frozen-Qwen CPU throughput blocker (2026-10-12)

This is a **read-only** failure analysis, not a new model run, change of frozen controls, independent semantic adjudication, or production approval.

## Primary evidence

- Original Actions run: https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38111452963
- Generating commit: `02c12b4aff0d589d10e5ed25d22b05d794ca96a0`.
- Reader archive artifact: `11696974258`; its 25 archived files were verified against the archive's complete `SHA256SUMS` manifest, with zero missing or mismatched records.
- `experiment-format`: success; its log says **42 tests passed**.
- Qwen pretrained model actually staged and loaded. Reader generated four answers and durably journaled each before the workflow was cancelled; independent replay was skipped.
- Original plan SHA-256: `9840a25487af444914dca24c818d98ff798ebc1610ea8dfdd827187c31ad1897`. Original calibration plan SHA-256 in this cancelled run: `205c9a46b3776a7e8f3063b8eb63cf7a0f5cd4647a1947b6e90d2b2e0d570e45`.

## Observed reader throughput, not estimated scores

| Task | Arm | Complete input tokens | Generated tokens | Receipt.seconds | Status |
| --- | --- | ---: | ---: | ---: | --- |
| controlled_4b61ce33 | k1 | 504 | 7 | 923.308 | succeeded |
| controlled_4b61ce33 | k2 | 787 | 6 | 1457.513 | succeeded |
| controlled_4b61ce33 | k3 | 1076 | 14 | 2045.598 | succeeded |
| controlled_4b61ce33 | k4 | 1370 | 13 | 2641.516 | succeeded |

Total observed inference is **7067.934 seconds (117.80 minutes) for 4/40 required calibration calls**, with no fifth calibration arm or final evaluation call recorded. The observed elapsed times become longer with larger delivered prompts. The workflow reader budget is 180 minutes; therefore a complete same-reader 40-calibration + 72-evaluation protocol is **not viable at the observed CPU throughput** within that budget. This is an observed resource bottleneck, not a claim that Qwen or retrieval is incorrect.

The 4 partial records have no complete task census or post-journal calibration labels. They cannot select a top-k winner, produce held-out success rates, demonstrate graph/parametric gains or satisfy the independent replay. Never drop the unfinished arms from the denominator or count cancellation as successful calibration.

## Next qualifying execution requirements

1. Move the **unchanged frozen research reader and identical prompt/decoder/source contracts** to an adequately provisioned, authorized compute environment, or separately qualify a performance-only optimization by checking token-identical outputs against the same original examples. Do **not** substitute a different model, smaller context, smaller test census or unverified teacher and call it the same experiment.
2. Preserve original raw JSONL after each generation, and support authenticated, per-task resumability with exact model/plan/policy SHA and output digests. A resumed calculation must never pretend partial answers were a complete calibration, and the frozen top-k policy must still be chosen only after all 40 records.
3. Enforce a short initial measured-throughput/resource preflight before committing to the full 112 model calls. Abort or re-provision when the projected complete run exceeds the actual job budget, retain the failed record and CPU-hours as experimental costs.
4. Preserve the separate 9-arm 72-call test, independent replay, citation-chain scoring and full PR `blocking-ci` gates. No production promotion or stage-three parametric-memory qualification from an incomplete run.

**Current disposition:** 40-call calibration **incomplete (4/40 recorded)**; final nine-arm evaluation **0/72**; independent replay **not performed**; statistical superiority **not established**; production acceptance **false**.
