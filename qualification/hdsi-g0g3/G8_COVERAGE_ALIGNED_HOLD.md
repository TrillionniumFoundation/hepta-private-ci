# G8 — Full-corpus TRAIN coverage and conservative Episode-NDU control

**DRAFT / RESEARCH_ONLY / SHADOW_ONLY / HOLD_NO_GO / DENY_ALL.** No main merge, model selection, Cell Split, signed FinalUse, production activation, stochastic FBSDE efficacy, multimodal generation, or self-evolution.

## Scope and source lineage

Additive child of G7 PR #2654 at source HEAD `b7c6cfb2e7d00191a31ce996c54faa70f335de9e`. The original 6 TRAIN / 4 HELD **historically public** LoCoMo conversation roots, original SHA-pinned MiniLM weights (`53aa5117…8d9db`), and frozen 24 source-first questions per root are unchanged. G8 corrects **TRAIN document coverage**: G7 trained its value policy against 256 selected utterances per TRAIN root, leaving only 55/144 questions with reachable annotated evidence, but then evaluated against full HELD transcripts. G8 uses every valid original utterance for **both** TRAIN and HELD; *all 144 TRAIN annotated supports exist in the candidate evidence bank*. It does not introduce a new publisher, prospective time window, semantic answer evaluator, or stronger Reader.

Source owner authenticates the historical ZIP and five model/data source SHA-256 digests and exports only the four original frozen Encoder files plus a complete `G8` packet containing public text, strictly bounded source identity, and TRAIN support addresses. No HELD gold, answer, evidence addresses, original QA JSON, arbitrary model code, model-loading instruction or external effect credential reaches the model runner. The independent reviewer independently reacquires exact publisher bytes **after** SHA-sealed predictions exist.

## Physical training and resource conservation

- Six independently isolated true CPU MiniLM root runs, with 2,759 completed six-layer Encoder sequence forwards and 175 real microbatches. Fully SHA-pinned BF16 safetensors are loaded as frozen FP32 tensors, with frozen WordPiece and at most 128 native tokens. Reordering by token length before batch inference reduces padding; predictions are restored to exact source-first input order.
- Per-root complete original TRAIN coverage and semantic rerank: 144 questions, BM25 77 Hit@5, frozen MiniLM RRF 86 Hit@5. This is a historical **TRAIN-fit** comparison, not task-generalization proof or Head training. The actual full-corpus BM25 Top-64 reaches original evidence in 119/144 training questions.
- Every TRAIN root publishes original BM25 and RRF Top-10 source addresses, bound to its actual full corpus, with external-original TRAIN evidence booleans. Assembly rejects forged model-work totals, swapped source groups, answer labels and out-of-support rankings. It freezes all 96 HELD actions **before** any original HELD gold is released.
- A separately paid original-model comparator invokes frozen MiniLM on the first eight HELD questions of each of four roots. The frozen policy itself pays no rerank calls. The comparator executes **1,147 additional actual model sequence forwards / 74 batches**, not counterfactual-free cached results. The model-worker time, CPU and resident memory are self-reported process observations, not host/energy attestation or complete lifecycle TCO.

## Registered utility and guarded admissibility

Registered finite utility *proxy* per submitted query: Hit@5 +10,000; miss −3,000; `STOP` = 0; marginal paid RRF rerank = 900 units. BM25 scan costs are common and counted exactly once, not a claimed zero total cost. This utility is neither user-specified answer correctness nor NDU preference identifiability.

A paid rerank is admissible only when the observed paired net gain exceeds its fee in **every TRAIN leave-one-original-root-out empirical contrast**, with at least four sufficiently supported roots. This is an intentionally conservative empirical robustness gate, **not a statistical confidence interval** or universal stability theorem. A learned STOP action is withheld under the six-root sample because the registered stop-support policy requires 20 independent source roots; lack of support is not evidence that the answer is wrong. BM25 remains always admissible. Full train bands yield:

| Lexical band | TRAIN cases | BM25 Hit@5 | RRF Hit@5 | Worst source-LOO net units | Rerank admitted |
|---|---:|---:|---:|---:|---|
| weak | 2 | 0 | 1 | unavailable | No |
| medium | 64 | 25 | 31 | −120 | No |
| strong | 78 | 52 | 54 | −900 | No |

One exact backwards recursive-utility solver and a **separate forward ordinary Bellman knapsack** must emit identical actions on the same immutable objective, horizon and per-root budget (at most eight neural reranks). No extra utility weights are permitted to favor NDU. The deployed-policy candidate is therefore all 96 `BM25`, **zero STOP and zero RERANK**; the paid fixed8 comparator is independent.

## Independently verified historical HELD outcome

| Arm | Evidence Hit@5 / 96 | Submitted | STOP | Paid reranks | Observed utility units |
|---|---:|---:|---:|---:|---:|
| Untrained full-corpus BM25 | 48 | 96 | 0 | 0 | 336,000 |
| Guarded G8 Episode NDU | **48** | 96 | 0 | 0 | 336,000 |
| Same-objective ordinary Bellman | **48** | 96 | 0 | 0 | 336,000 |
| Genuine 8-per-root frozen paid rerank | 48 | 96 | 0 | 32 | 307,200 |

The held paired rescues/harms for G8 NDU relative to BM25 are **0/0**; for the fixed8 paid control **2/2**. Compare this with the retained historical G7 26/96 and 54 STOP only as an architecture-level regression diagnosis, not an independent contemporary head-to-head trial. G8's apparent repair is fully reproducible by the **no-learning BM25 baseline** and does not demonstrate NDU-specific task lift. Furthermore, the 2,759 upfront TRAIN forwards are real, so there is no sound end-to-end compute-saving claim.

Original human evidence labels measure retrieval support; STOP is abstention, **never** a correct answer. No human answer entailment, independent future holdout, other publisher, hallucination reduction, true System 2 emergence, 421M equivalence, long-term retention or production resource envelope is established.

## Executable verification and boundaries

Research-only files: `g8_source.py`, `g8_policy.py`, `g8_root.py`, `g8_assemble.py`, `g8_paid.py`, `g8_review.py`, `g8_custody.py`, `test_g8.py` and `.github/workflows/hepta-hdsi-g8-original.yml`. No previous experiment, Rust Neuron/NDU, selected Stem, model Worker, memory/ledger, authority, FinalUse, deployment or `main` changes. The read-only workflow stages: source tests → authenticated source owner → six genuinely paid TRAIN roots → model-free profile/plan assembly → physically paid genuine fixed comparator → a **different-process late-label independent original source reviewer**. It never accesses HELD gold in an inference job, and never publishes raw individual predictions or the original archive as a PR attachment.

Local exact original experiments: **35/35 unit tests** each under normal Python, optimized `-O`, `-S`, and `-O -S`, zero skips with original source and model receipts provided; source-only **29/29** without Torch. Python compile, YAML parse and adversarial mutation cases pass. These are local checks; hosted exact-HEAD CI and `blocking-ci` must terminate independently. No claim may be promoted while they are queued/failed. Existing other-workstream Prettier, cargo-deny and Bazel failures are unwaived.

**Verdict:** safer coverage-aware fallback is demonstrated; learned NDU reasoning lift is **NO-GO**. The next useful experiment requires a frozen strong Reader and an actually new, independent source/time cohort where question correctness and full lifecycle compute are measured, rather than another adaptation to the historical LoCoMo answers.
