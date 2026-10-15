# V12 — Original pretrained Reader check on EVERY material Head-vs-cheap evidence disagreement

**2026-10-15 · RESEARCH ONLY / DRAFT / DENY_ALL · no main merge · no model selection · no FinalUse.**

## Why this exact study

The existing V11 physical **31-parameter residual reranker** modestly improved retrospective publisher weak-source Hit@3 versus original BM25 (381/380/382 of 829 versus 372). However V11 included a **fixed, cheap Top-2-preserving third-slot control** with identical aggregate source hits, and no full Reader answer/citation benefit had been established. A changed ordered ranking is not necessarily a new evidence set. This V12 tests every original residual-vs-cheap Head final **source membership** difference, not a selected success sample.

## Actual immutable source and model

- Previous original V11 sealed 829-question source-first ranking bytes SHA-256 `3dabcb167a676d124ae36ff271bb14de3d58b557b00fbbef5619030b857c8a9a`; original V9 source-only file SHA-256 `1cb2d1d7194137cdea48ef8a13e8002c6612a9c98a1ffa71e28e7263c61bf84c`.
- Original V11 orders: seed41 **68/829** changed ordered Top-3, only **3/829** changed the final set; seed47 **7/829** changed order, **0/829** changed set; seed53 **46/829** changed order, **1/829** changed set. The seed53 membership change repeats one seed41 question. Only **3 unique questions in 3 historic conversation roots**, just **4 seed-contrast events**. They are not independent future windows, and repeated seeds do not increase root count.
- Precommitted source-only candidate derivation reads neither original answer nor publisher gold. For each seed-case disagreement, uses identical source inventory, same literal question, original source IDs, fixed one Reader/tokenizer/system prompt/greedy decoding, at most 18 new tokens. Three arms per seed-case: original BM25, cheap fixed Top-2, learned residual. Duplicate exact same Reader prompts across the two seeds are deduplicated: **12 arm-case route selections, 8 unique physical Reader requests**.
- GitHub original artifact `11586991191`: entire ZIP SHA `07b357cbb3362f484ac4dc1872ab7e28e8a46daaf338f2636fed8d40fbcee76af`; original BF16 30-layer Llama-family Reader weights SHA `5af571cbf074e6d21a03528d2330792e532ca608f24ac70a143f6b369968ab8c`; original BPE `9ca9acddb6525a194ec8ac7a87f24fbba7232a9a15ffa1af0c1224fcd888e47c` and config `8eb740e8bbe4cff95ea7b4588d17a2432deb16e8075bc5828ff7ba9be94d982a`. Uses a **candidate manual PyTorch FP32** operator and candidate ByteLevel tokenizer, with original weights but **official Hugging Face tokenizer/model parity NOT verified**. Prior archived-host numeric SHA differs from current implementation although Top-5 IDs agree; do not assert cross-host bitwise parity.

## Executed, rather than simulated

The isolated analysis CPU, **not** the user's dot, performed two separate full original-weight execution processes. Each completed **8/8** generated raw original answers, 142 genuine model forward calls (prefill plus decoding), with **1,057 input tokens** and **135 generated tokens** in the first run. The second run's original token IDs, texts and source choices were exact-byte identical for **all 8** requests (wall/CPU time deliberately excluded from deterministic identity). First run **20.921 CPU seconds / 10.847 wall seconds**; second **21.762 CPU / 11.287 wall seconds**, not matched against retrieval+training cost.

Original source-first plan SHA `44eaf822dd8e64f83f93d8bb50244873fdf4388a0bd30473f73b4c85e85dc4a8`. Original first answer file SHA `caaf96907622dbcc805cc23eacf59a01946cab5107167bb4a13f4162020e6b3d`. These private data, as well as the original questions/dialogues, publisher answers/labels, and model weights are **NOT** committed to the public repository. Public report records only sanitized aggregates and SHA digests.

## Independent post-answer weak reference test

After all 8 answers were sealed, a **separate score process** opened the original LoCoMo publisher annotations (original dataset SHA `79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4`). Literal publisher-evidence reference intersection in the final 3 evidence IDs was **0/12 route selections**, across all 4 seed-case comparisons. This is only **publisher weak source annotation**, not independently adjudicated factual correctness or hallucination evidence.

Residual versus fixed cheap control produced different raw Reader output text for **3/4 seed-case contrasts**. One changed answer event is repeated across two seeds on the same underlying question; only 3 distinct question roots were selected. Four source-set changes were at unequal natural Reader input lengths (e.g. 130 vs 132 tokens), so there is **no equal-total-token / compute-controlled causal outcome claim**. No citation entailment judgment or independent human review was obtained.

The appropriate scientific interpretation is **NO-GO / not identified**: tiny retrospective weak-source gain over BM25 cannot be attributed specifically to the trained residual Head when the cheap fixed control ties on aggregate scores; all physically material route differences omitted publisher annotated source evidence in this selected cohort. Differences in raw answer bytes are not proof of useful learning. V6 seed41 paired-world retention remains failed; V7 source-disjoint relation transfer and multimodal gains remain unqualified.

## Verification and controls

The library-free audit `v12_public_audit.py` asserts the exact negative report contents: all arm and source family denominators, original model hashes, original Reader calls, no gold hits, no future calendar windows, no official HF parity, no cost match, no semantic QA and no production authority. `test_v12_disagreement_audit.py` has **24/24** locally executed stdlib tests in normal Python **and** `python -O`. The dedicated read-only Actions job runs **source-only contract tests** and a sanitized report audit. Those hosted tests do **NOT** rerun original Reader or independently authenticate private evidence; source-only PASS must not be mislabeled as pretrained physical PASS.

The original local data-plane code `v12_reader_runtime.py`, `v12_reader_disagreement.py`, and `v12_build_public_report.py` is included in the separate downloadable user research bundle for reproduction with original authorized materials. It records create-only source plans, model results and postseal judgments. Any interrupted, missing or duplicated answer must fail rather than producing a success-shaped receipt. It does not implement original durable per-attempt starts or independent reviewer signing and cannot authorize production.

**Next gate:** compare V12's best low-cost control against any learned new Head on *new independent natural source roots and future windows*, with a stronger Reader and independent semantic/citation reviewer, before reopening native Stem promotion, Cell fission or NDU/FBSDE claims. Do not pay extra training/Reader cost for pure ordering changes without demonstrated incremental utility.
