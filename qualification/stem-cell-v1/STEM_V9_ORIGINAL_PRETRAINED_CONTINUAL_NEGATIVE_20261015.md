# V9: original pretrained shared-Encoder continual learning, negative full-source retrieval result

2026-10-15 · `TrillionniumFoundation/hepta-private-ci` · **DRAFT / SHADOW_ONLY / DENY_ALL**. This is an additive research experiment stacked on #2364/V8, **not** a V6 production repair, model promotion, or main merge.

## Exact research question

Does learning a 6,914-parameter gated private Head on a **single, real, frozen pretrained MiniLM Encoder** make source selection more useful than complete-source BM25 or frozen cosine, and can continuation on new conversation roots retain performance on earlier training roots?

The primary observation is **NO** for the first question. The second has a narrower descriptive TRAIN-only result: fixed-budget replay preserves old training accuracy much better than new-only learning, but none of the learned Heads beats a cheap retrieval floor on separate conversation roots. No positive model-selection or full-task reasoning claim is supported.

## Material, source isolation, scope

- Original archived pretrained six-layer BF16 MiniLM material: GitHub Actions artifact `11586991191`, outer ZIP SHA-256 `07b357cbb3362f484ac4dc1872ab7e28e8a46daaf338f2636fed8d40fbcee76af`; Encoder safetensors SHA `53aa51172d142c89d9012cce15ae4d6cc0ca6895895114379cacb4fab128d9db`, original WordPiece tokenizer SHA `be50c3628f2bf5bb5e3a7f17b1f74611b2561a3a27eeab05e5aa30f411572037`.
- Original complete public LoCoMo 10-family JSON SHA `79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4`. **5,882 full original dialogue turns + 1,986 full original QA questions**, no dropped evaluation questions. All original text is kept private.
- **Old TRAIN:** conv-26/30/41 (497 original questions); **New TRAIN:** conv-42/43/44 (660); **HELDOUT:** conv-47/48/49/50 (829). Among the 1,157 TRAIN questions, 1,154 have directly matched published weak evidence IDs; exact source-bound pair sampling yields 494 old + 660 new TRAIN questions. HELDOUT has 822 directly usable publisher annotations and 7 unknown/incomplete annotations; all 829 remain in the denominator.
- PREPARE serializes a source-only snapshot, excluding publisher answers/evidence. Only the six TRAIN roots have a separate TRAIN-label packet. Encoder and Head training consume these, not heldout annotations. A **separate process** opens withheld publisher annotations only after the 829-question × 14-arm original prediction file has been fsynced and sealed create-only. This is logical data isolation, **not an OS sandbox** or an authenticated independent source owner.
- Physically executed **492 genuine full six-layer MiniLM batched forward calls** over **7,868 source/query sequences / 225,366 actual token positions** using FP32 Torch reference compute on the original checkpoint. Encoder/input preparation wall time **77.171 seconds**, not complete lifecycle wall time. No silent truncation; original WordPiece material verified by SHA.
- CPU readout uses `q ⊙ d × 384` as a frozen 384D interaction, then the same **6,914 physically trainable** 384→8→384 gated residual design as V7. Head is **not** the original V6 42,562-parameter FactBridge and cannot by itself close its retention gate. Manual BERT reference is **not officially validated against Hugging Face tokenizer/operator**; earlier cross-environment exact numeric SHA discrepancy remains unresolved.

## Predeclared training and controls

For seeds 41, 47, 53, each Head learns old weak publisher support vs its complete-source BM25 hard negative: 240 Adam updates × 64 examples. Then each arm continues with the same 240 update cap: `frozen` (0 actual continuation), `new_only` (240 new-only updates, learning rate .001), `low_lr` (240 new-only updates, lr .0002), `equal_budget_replay` (240 updates, half old/half new). Actual old/new exposures recorded per arm; equal steps do **not** equal equal learning data or equal total lifecycle compute. All heads have 6,914 parameters and no base Encoder training. Baselines are full-source exact-protocol BM25 and frozen MiniLM cosine, with identical delivered Top-3 evidence slots.

Training selection and labels never read the four heldout roots; no hyperparameter was selected after observing heldout scores. Head fitting uses the **publisher-weak source reference proxy**, not independently human-verified semantic correctness. Source families are the independent sampling units; repeating questions or seeds does not create hundreds of independent domains.

## Observed original heldout Top-3 weak-evidence outcomes

| Arm | Any published support in Top-3 / 829 | Important qualification |
| --- | ---: | --- |
| **Full-source BM25 (no fitted Head)** | **372** | Cheap lexical floor, not a strong semantic human task benchmark |
| Frozen pretrained MiniLM cosine | **223** | Actual frozen pretrained dense full-source ranker |
| Seed41 frozen / new / low lr / replay | 26 / 15 / 11 / 17 | All below full BM25 |
| Seed47 frozen / new / low lr / replay | 78 / 35 / 36 / 50 | Seed47 is descriptive, not selected winner |
| Seed53 frozen / new / low lr / replay | 9 / 6 / 2 / 6 | Strong learned-Head generalization failure |

These include 822 with one-or-more valid literal publisher source IDs and **7 unavailable/ambiguous** annotation cases counted in the 829 denominator. No full natural Reader answer was generated; semantic correctness, citation entailment and reader answer utility are **unknown**. This BM25 renderer/pooling/protocol differs from old #2085 numbers; do **not** combine numerators or call either a replicated effect.

## Actual old/new TRAIN-only forgetting diagnostic

All 12 physical Head tensor SHA values were reproduced. Before/after panels use the *same labelled original TRAIN pairs* used by the optimiser (old 988 binary examples, new 1,320). This is **training fit/retention**, not source-independent generalization.

| Seed | Frozen old/new correct | New-only after old/new | Low-LR after old/new | Replay after old/new |
| --- | --- | --- | --- | --- |
| 41 | 955 / 732 | 790 / 1,133 | 861 / 880 | **957 / 1,044** |
| 47 | 941 / 733 | 785 / 1,136 | 858 / 854 | **953 / 1,028** |
| 53 | 921 / 710 | 720 / 1,066 | 759 / 813 | **937 / 1,024** |

Replay preserved or improved *old training* correct counts in all seeds, while new-only loses substantial old fitting ability. But the replay arm's heldout **6–50/829** weak source hits still fails, and the original V6 three-seed retention gate is not re-executed. This is not independently sufficient old-task retention or reader value. `retention_repair_verified=false` remains correct.

## Independent verification and file boundaries

- Producer source SHA `6d43bfdbd5613f885bc7722506eb847f3997a141f2464ea3cfa27c15396e97e6` is pinned in the independent audit. Private original prediction file SHA `df05ec7906d58834cf7856a0dce4dc77f6b639c0a7c910c88d49cb191f1cd01c`, precommit SHA `81413c6ea25d8e2b51872778c939634237e505d6fa3528d8ba7ee2216a3c66c5`.
- A separate file/tensor audit validates complete 10-family source/QA roster, six TRAIN-only weak labels, model/input pins, all 14 final-arm source-ID triplets for 829 cases, complete training work accounting, and no production/future claims.
- Actually retrained and independently re-forwarded **all 12** physical private Heads; all 12 raw head SHA match, **9,948/9,948** delivered source rankings match exactly. Independently recomputed 56 root-arm weak publisher counts. `v9_train_retention_replay.py` separately measures original TRAIN-only before/after accuracy and BCE with all 12 SHA checks.
- **38 source-only/negative-adversarial tests** passed locally both with ordinary Python and `python -O`. Hosted read-only CI is independent, not assumed to have completed on a new HEAD.
- PUBLIC Git tree: source, tests, fixed contract and read-only workflow, source/weight digests and **sanitized aggregates only**. The **actual model tensor bytes, original LoCoMo dialogues/questions, source-per-question ranking, publisher gold, Head optimizer state, and private frozen-feature matrices** remain outside the public tree. Read-only CI must not download these or assert pretrained task execution.

## Interpretation, next experiment and production gate

1. **Keep BM25 as a strong floor** rather than deploying any of these trained readout Heads. Dense cosine 223/829 also has no source-retrieval win in this protocol.
2. Next causal candidate should combine complete-source lexical retrieval with a *bounded* cross-feature reranker, test genuine source-held-out relevance and separately prove Reader sufficiency before evaluating Cell separation, graph reasoning or NDU. Freeze candidate-pool, training and work budgets before opening independent labels; this result cannot justify tuning on these now exposed four roots.
3. Additional tests should compare a truly pinned Granite97 Stem and an exact-identity 421M control at matched total cost, and judge real multimodal questions with independent necessity labels; these have not been run in this V9 study.
4. The actual V6/PR #2352 primary retention failure, `blocking-ci`, authentic source/model authority, real prospective windows, target-host 4096 Cell p99/WAL/crash recovery, and signed FinalUse remain hard blockers. No main merge, no selected Stem, no automatic Cell split/fusion, no NDU activation, no production effect.

**Status: DRAFT / SHADOW_ONLY / DENY_ALL / NO MODEL WINNER / NO MAIN MERGE.**
