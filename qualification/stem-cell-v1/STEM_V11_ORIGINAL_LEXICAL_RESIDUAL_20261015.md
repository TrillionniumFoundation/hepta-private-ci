# V11 original MiniLM lexical-anchored residual Head: retrospective weak-evidence result

**Scope:** Research SHADOW_ONLY / DENY_ALL. Stacked on V9 original pretrained MiniLM and V10 independent family census; preserves all existing research and production owners. No model selection, main merge, FinalUse, continuous Cell split/fusion, NDU enablement or live Worker change.

## What physically ran

The input is the exact V9 original 10-family LoCoMo source-only corpus, original 7,868×384 FP32 **frozen pretrained** MiniLM feature snapshot (`f1a66e34...`), the original V9 TRAIN-only weak publisher source labels and exact original V9 BM25 rankings. All weights/source/train/prediction identities are checked before use. The original Encoder executed **492 historical batches** in V9; V11 executes **ZERO new Encoder forwards**. We do not charge that work as free or present the V11 process measurement as total lifecycle cost.

A simple 31-parameter `4→5→1` residual Head adds a bounded (±0.4) score to a lexical BM25-rank anchor. Candidate universe is the source-first union of **BM25 Top-16 and frozen MiniLM cosine Top-16**; final evidence has **exactly Top-3** sources. Each Head trains for **300 actual Torch/Adam optimizer updates** using only the earlier six TRAIN families. Seeds 41/47/53 repeat training cases, not independent source groups. There are 906 TRAIN questions with a publisher positive inside the candidate union and 248 without one; the latter are explicitly excluded from supervised optimization, not silently labeled negative. The model output layer starts at zero to preserve the lexical anchor before training.

The scorer executes in a separate process **only after** the source-first plan, original rankings, Head SHA, full 829-question prediction file and physical training receipt are sealed; the independent auditor reopens the exact original publisher support annotations using its own counting function. Only sanitized aggregate research observations are committed. Private original source passages, per-question rankings, publisher targets, feature matrix and tensor weights are deliberately not published.

## All original 829 retrospective HELDOUT questions

| Arm | Publisher weak any-support Hit@3 | Difference vs BM25 |
| --- | ---: | ---: |
| Complete-source original BM25 | 372/829 | baseline |
| Frozen pretrained MiniLM cosine | 223/829 | −149 |
| 31-param residual, seed41 | 381/829 | +9 |
| 31-param residual, seed47 | 380/829 | +8 |
| 31-param residual, seed53 | 382/829 | +10 |

The fixed `safe_two` control preserves the original BM25's top two results, allowing a Head-selected third source; it has the same weak-support counts for every seed here. All three full residual arms were **not** uniformly better across families: seed41 conv-48 falls from 124 to 120; seed53 conv-48 falls to 122. Pair-level gains and losses for every group and arm are independently recounted in the public report. The apparent +8 to +10/829 is a **small retrospective descriptive gain**, not a significant, prospective, cost-normalized or end-to-end model victory. This heldout cohort was already used in V9 and is not an unopened prospective validation set; no post-hoc winner can be promoted from it.

## Actual experimental boundaries

- Three separate physical research executions returned exactly the same frozen-source Head tensor SHA for each seed and exactly the same immutable original 829-question predictions SHA `3dabcb167a676d124ae36ff271bb14de3d58b557b00fbbef5619030b857c8a9a`; actual wall/CPU process receipts differ and are not model-identity pins.
- 900 total actual Head updates, 31 trainable parameters each; the final run's full-process CPU includes cached-data loading, complete source-first BM25+cosine preprocessing and ranking, but excludes historical pretrained Encoder preparation. This is **not equal-compute** against BM25, strong RAG, 421M, Granite97 or EmbeddingGemma 2.
- Original manually reconstructed MiniLM FP32 reference does not yet have official Hugging Face tokenizer/operator parity. No independently authenticated source/model issuer, independent Reader citation entailment, human semantic correctness, future calendar windows, real multimodal necessity task, production fleet target host, signed FinalUse or V6 seed41 retention closure.
- Only four original source roots exist; question-level wins/losses are descriptive and may not be treated as 829 independent observations for significance.

## Reproduction

`stem_v11_lexical_residual.py` supports a label-blind `rank` process using the existing exact original V9 private source-only, train-only weak labels and frozen physically encoded vectors, then a separate `score` process using the exact original LoCoMo publisher material. `v11_independent_recount.py` requires the complete immutable original outputs and independently reconstructs family counts. Neither script fetches model weights from the network. Run into a fresh output directory; create-only files refuse silently overwriting prior evidence.

The public CI intentionally runs **source-only stdlib adversarial tests**, rather than pretending to have original private model tensors, label-scoring permissions or an authenticated host. `v11_public_no_go.py` validates the sanitized report and always refuses positive promotion/finality claims. `blocking-ci`, hosted exact-HEAD job, physical future task, independent human judging and separate admission must all pass before any production consideration. Keep DRAFT / DENY_ALL.
