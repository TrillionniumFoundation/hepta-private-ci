# MemoryCell: completed frozen-reader strong-RAG trial — audited disposition

**Audited 2026-10-13 against the actual October 12, 2026 run.** This is an
**independently replayable read-only analysis of already generated model
answers**, not a training result, production approval, independent prospective
benchmark or human-signed semantic citation verdict.

## Exact generating source and experiment receipts

- Source commit: [`6304b451268c73f3d1a605985226b102df841bbf`](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/6304b451268c73f3d1a605985226b102df841bbf).
- Completed [GitHub Actions run **#38224780900**](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38224780900), second attempt: actual `reader` success **and** separate `independent-replay` success.
- Pinned original observations + plan: [artifact `11669174727`](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38063870516/artifacts/11669174727), ZIP SHA-256 `23e9d44b8d2dbe756c7c33031e18853c83326458a37925d4d368881145bf142b`, original plan SHA-256 `9840a25487af444914dca24c818d98ff798ebc1610ea8dfdd827187c31ad1897`.
- **40 calibration + 72 evaluation actual model outputs**: [artifact `11743043427`](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38224780900/artifacts/11743043427), ZIP SHA-256 `7a99db30fb5b1202fcd43073d22589b84315046dd34044277cc46351f1cbece8`.
- Separate-process independent result replay: [artifact `11748040166`](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38224780900/artifacts/11748040166), ZIP SHA-256 `2445895a7d51e3173837471aa462cebede29eb3ec89653af3bd17e73b6114071`.
- All three outer SHA-256 values and their complete **35 / 43 / 8 inner manifest members** have been checked again. Source identity, raw/scored row correspondence, frozen reader inventory, original evidence bytes, strict grammar, citations, per-arm cost totals and selected-k objective were independently recomputed by `strong_rag_actual_disposition.py`. **No new language-model inference** was performed during the audit.
- The separate original verifier also re-executed the constrained program worker and recomputed citation-chain and paired-effect receipts. This is *not* a second independent human semantic judge or an independent source-family sample.

## Predeclared actual-model outcomes

Eight explicitly authored, previously exposed test tasks, exactly one frozen Qwen2.5-3B-Instruct revision (research-only BF16/eager), same input and output budgets and identical tools in every arm. All 40/40 calibration and 72/72 test calls completed successfully. "Strict" means an acceptable narrow identifier and real constrained procedure-verification outcome; **it does not mean fully supported citations**.

| Actual evaluation arm | Strict success | Complete input tokens | Reader seconds | Correct with all program-declared sources cited |
| --- | ---: | ---: | ---: | ---: |
| Calibrated Hybrid `k=1` | 5/8 | 3,961 | 62.51 | 3/8 |
| Hybrid `k=4` | 3/8 | 10,806 | 136.04 | 1/8 |
| Hybrid `k=6` | 2/8 | 15,463 | 194.10 | 0/8 |
| Hybrid `k=4`, reversed order | 3/8 | 10,806 | 135.83 | 1/8 |
| `single_hop` | 4/8 | 4,575 | 66.04 | 4/8 |
| Full-path `entity_time` | **8/8** | 5,752 | 79.20 | **4/8** |
| Corrected `organized` | **8/8** | **5,179** | **73.52** | **4/8** |
| `program_support` (authored ceiling) | **8/8** | 5,179 | 73.11 | **4/8** |
| Empty evidence | 0/8 | 1,630 | 36.14 | 0/8 |

Input tokens are from the **complete prompt**, not evidence text alone; reader seconds are sums of model-generation receipt times, **not** end-to-end ingestion, index maintenance, production latency or infrastructure billing. The full experiment consumed **45,749 calibration input tokens + 63,351 evaluation input tokens = 109,100 input tokens**, with corresponding model-generation time around **1,460 seconds** (excluding model download/loading, host waiting and other lifecycle costs). The validation source remains the original previously exposed authored population.

## Task attribution and resource choice

1. **Full-path traversal adds four correct answers over single hop** (4 paired wins, no losses). It explains the modeled two-hop composition and procedure tasks on this tiny controlled population; no general-language reasoning capability follows.
2. **Revision-aware full organization adds zero task successes over full-path `entity_time`** (8 ties). It removes **573 input tokens** (about **9.96%** of the full-path arm) across eight calls. This is an incremental prompt-cost observation, not proven extra task ability, and ignores extra writer/index maintenance cost.
3. The actual reader-calibrated Hybrid k=1 adds two correct answers over k=4, but still loses three to the full-path filter. It was selected because k=1/2/3/4 each had **4/8 calibration successes**, and k=1 consumed the fewest calibration tokens. Leave-one-question-out selection chose k=1 in seven folds and k=2 in one; **the top-k calibration is not insensitive to individual questions**. Its original support coverage was only 3/8 evaluation tasks, versus 8/8 for entity/time.
4. Hybrid k=6 was worse than k=4 on one paired task; reversing k=4 presentation changed no strict task outcomes. More evidence or reordering the same evidence is not a substitute for correct source structure.
5. **All nine arms generated real answers; 39 matched ordered-evidence pairs were prompt-token identical and yielded identical generated tokens and answers**, so the observed effects cannot be credited to those repeated identical prompts randomly changing output.
6. In the 8/8 task-success full-path and organized arms, only **4/8** correct outputs cite all **program-declared** support events (especially missed first-hop citations in two-hop tasks). This is not a human-certified sufficiency standard and cannot be turned into a "99% semantic citation precision" claim. Answer correctness, declared citation-chain completeness and semantic source entailment are three different metrics.

## Research disposition: **NO-GO for parameter-memory promotion or production**

The result verifies a **specific frozen-reader advantage of cheap deterministic path selection over calibrated top-k retrieval** in this controlled population. It does **not** establish that any trainable parameter head, experience-specific parameter memory, graph algorithm beyond simple full-path filtering, SYSTEM2 planner or Cell Split learned an additional capability. No optimizer ran, no independently sampled future source family is present, no independently adjudicated citation entailment is available, and no deployed withdrawal/recovery/cost window was measured. Neither an 8/8 authored task result nor a successful Actions workflow can meet a prospective 99% acceptance standard.

**Next allowed experiment:** freeze the original full-path entity/time baseline **including complete token and lifecycle costs**, recruit genuinely new independent real-source families with pre-task splits and reviewed source chains, and evaluate a distinct learned Cell policy against that baseline under the same reader and budget. Require independent semantic citation-chain review, prospective task success and noninferior revocation/recovery behavior **before** considering parameter-memory adoption. Do not copy a new 421M reader per Cell or credit model-family changes as a learned Cell gain based on these data.

### Reproduce the disposition without an inference dependency

```bash
python3 scripts/memory_cell/strong_rag_actual_disposition.py \
  ORIGINAL_INPUT_ARCHIVE.zip COMPLETED_MODEL_ARTIFACT.zip INDEPENDENT_REPLAY_ARTIFACT.zip \
  --output /tmp/strong-rag-disposition.json
python3 -m unittest discover -s scripts/memory_cell -p test_strong_rag_actual_disposition.py -v
```

All outputs are read-only research evidence, `production_accepted=false`. The
current PR HEAD and its required `blocking-ci` must be checked separately;
a successfully replayed **historical** generating commit is not a current-HEAD
CI approval.
