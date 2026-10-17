# P5 — class-balanced original Reader and frozen exact-answer grammar

**DRAFT · RESEARCH_ONLY · SHADOW_ONLY · DENY_ALL · NO MAIN MERGE · NO MODEL PROMOTION**

This is an additive experimental child of [P4 #2547](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2547). Its exact parent P4 original pretrained Qwen3 experiment completed: 48 TRAIN + 56 seven-policy + 16 matched-cap calls (120 original physical calls), and the separate publisher scorer successfully ran. **The outcome was negative**, not an NDU win: all 8 held answers were marked incorrect in the original frozen scorer. Every P4 TRAIN answer was similarly recorded incorrect. In authentic TRAIN-only outputs, Qwen3 frequently emitted literal \`<1>\`, \`<2>\`, \`<3>\` while the old whole-string parser admitted only bare digit / \`FINAL=digit\`. The original P4 held cohort contained 7 Sci/Tech and 1 Business task. **Do not re-score P4 as a prospective success by changing its evaluator afterward.** Retain its exact original artifacts and failure claims.

P5 changes the *future experiment's* source-selection rule, parser and protocol version, preregistered before its new physical runs. It does not modify P4 history or reuse any historical model result.

## Fixed identity and method

- Real Qwen3-0.6B, \`Qwen/Qwen3-0.6B@16706fc57485378d4ffaf54139b29ccc66ae08fa\`. Check model SHA256 \`f47f71177f32bcd101b7573ec9171e6a57f4f4d31148d38e382306f42996874b\`, tokenizer SHA256 \`aeb13307a71acd8fe81861d94ad54ab689df773318809eed3cbe794b4492dae4\` *before* model deserialization, and again after sealing.
- Original \`szhuggingface/ag_news@98c532231d96ae10e176a909192ecac548949288\`, original train and held publisher Parquets checked by independently pinned SHA256. This is **historically public source data**, not fresh/future independently held out data.
- Original-source owner deterministically selects the *first index* for each **4 original publisher class × 2 input lengths × 2 original index parities**, separately on TRAIN and official TEST. Each split has exactly **16** records; each publisher class contributes **4**, each length bucket contributes **8**, each bucket/parity has 4. Selection is based on publisher labels in the source-owner stage **before any model outputs**. Gold class labels for held tasks remain absent from the Reader's public packet. This is label-stratified measurement, not an unbiased IID estimate or proof of independent source families.
- Whole-string output grammar is fixed from **prior original TRAIN-only observations**: a class digit \`0\`–\`3\`, \`<digit>\`, or either preceded by \`FINAL=\` or \`FINAL:\` (case-insensitive, optional surrounding whitespace). No substring search, multiple guesses, text explanation, trailing injection, or internal thought is accepted. Prior P2–P4 frozen scores remain unchanged.
- Protocol version \`hepta.ndu-merton.p5.original-balanced-and-declared-parser.v1\`; publisher profile \`hepta.ndu-merton.p5.class-balanced-agnews-source.v1\`; new runtime profile is byte/runtime digest-bound and rejects old P4 receipts.

## Physical experiment, fixed costs and limits

The existing P1 portfolio has seven arms: direct; fixed reasoning; greedy; mean-neutral Bellman; fixed empirical risk; bounded NDU-discrete risk; and identical-profile ordinary reference (its optimization choices must match NDU exactly under the same objective and observations). No new authority or full continuous FBSDE solver is implied.

The P5 physical corpus, if it completes, consists of **48** separately paid original TRAIN \`model.generate\` calls (3 actions × 16 tasks), **112** separately paid chosen-policy calls (7 policies × 16 held tasks), and **32** additional physically paid, source-bound equal-generation-cap comparisons (thinking on versus off, maximum 96 tokens for both, task-position-alternating). **Total 192 original forward/generation calls**; none may be skipped or replaced by an archival prediction. Existing \`reason\` budget remains 96 generated tokens, so unfinished thinking is an *incorrect* answer, not a hidden success. The output cap and random seed profile are unchanged relative to P4; the new experiment targets output and source representativeness, not larger thinking horizons.

Count **all** actual model input/output tokens, partial and incomplete thoughts, CPU/wall time, model loading, TRAIN/calibration effort, every serving policy and the extra matched-contrast 32 calls. No double-charge of shared calibration in a single service-cost estimand; separate speculative amortization from observed cold-start cost. Do not convert utility tariffs to dollars or physical energy without original independently observed units.

## Owner-independent dataset reconstruction

Read-only GitHub Actions stages: P5 source job downloads and byte-verifies the original train/test Parquets, writes TRAIN+label-blind held source separately from source-owner held labels; original Reader worker consumes **only** the public packet and seals the policy and original model traces; postseal reviewer downloads held labels **after** the physical attempt is completed. The postseal reviewer **also re-downloads original publisher Parquet bytes and independently re-executes the preregistered source-selection rule**, then performs byte-for-byte comparison of the three stage packets before scoring. A missing original source, class stratum, label, journal event or physical model completion fails closed; no mock result may substitute.

The authentic host is a self-metered GitHub Actions CPU runner, not an independently attested hardware meter. The separate Python reviewer is independently implemented but is not a signed third-party human auditor. A synthetic local unit test, green source workflow, or recreated old P4 model output does **not** establish P5 physical results.

## Reproduction and falsification

From repo root, source-only mechanical/anti-leakage tests:

\`\`\`sh
export PYTHONPATH=experiments/ndu_tree_fbsde_gates/merton/token_portfolio_p1:experiments/ndu_tree_fbsde_gates/merton/physical_online_p2
python3 -W error::ResourceWarning -m unittest discover -s experiments/ndu_tree_fbsde_gates/merton/physical_online_p2 -p 'test_*.py' -v
python3 -O -W error::ResourceWarning -m unittest discover -s experiments/ndu_tree_fbsde_gates/merton/physical_online_p2 -p 'test_*.py' -v
\`\`\`

Observe the exact-HEAD hosted original model and postseal reviewer, and independently recount its **raw** answer IDs, label lineage, trace/cost census and per-policy external task scores. If no supported policy strictly improves externally scored task outcomes per full service cost against fixed / ordinary same-objective controls, record **NO_GO** and retain \`DENY_ALL\`. Nothing in this P5 profile proves P1-style NDU portfolio value or any improvement in world-model training; the sample is still only one historical public dataset family and one model/seed profile. Larger thinking budget, truly independent future data and a causal training/learning claim are **separate later experiments**.
