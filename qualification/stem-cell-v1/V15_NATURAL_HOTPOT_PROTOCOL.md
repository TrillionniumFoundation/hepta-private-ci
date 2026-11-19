# V15 — Original human-written HotpotQA multi-hop evidence qualification

**DRAFT · SHADOW_ONLY · DENY_ALL · NO MAIN MERGE · NO MODEL PROMOTION**

## Why this source

V12 has completed all Hosted real-Granite nine-arm Reader training and independent heldout scoring on synthetic ownership/storage text. Base, FactBridge, Endpoint achieved **1,431 / 1,456 / 1,453 out of 2,880** repeated-seed case predictions, all near 50%. V13 real Granite entity-link cosine proved useful when the next-hop candidates were supplied by grammar; V14 near-perfect unlabeled-held-corpus lexical graph was **transductive** and collapsed under semantics-preserving paraphrases. None demonstrates general human-language reasoning or warrants a deeper NDU/FBSDE recursion claim.

V15 moves to the established [HotpotQA](https://hotpotqa.github.io/) natural question benchmark rather than another synthetic template set. Its official dev distractor file has **7,405 human-written multi-hop questions**, 10 Wikipedia paragraph contexts per question, and sentence-level human supporting-fact IDs. The benchmark is distributed under **CC BY-SA 4.0**; no benchmark paragraphs, private source-derived file or answer label is committed to public Git.

Official public source URL: https://curtis.ml.cmu.edu/datasets/hotpot/hotpot_dev_distractor_v1.json

Original fixed raw SHA256: 4e9ecb5c8d3b719f624d66b60f8d56bf227f03914f5f0753d6fa1b359d7104ea (from the Hugging Face public dataset metadata). Acquisition **MUST fail closed** if this particular source is unreachable or the bytes change. Never silently relabel a mirror as the original.

## Frozen, equal-budget citation choices

For every original public question, each method emits exactly **Top-2 and Top-5** evidence citations, drawn only from its supplied distractor Wikipedia sentences:

- **bm25**: current-question-only sentence lexical scorer. Local IDF uses the currently supplied 10 paragraphs, not the entire future held population.
- **title_link**: discovers literal links from one public sentence to another public article title, then proposes a second citation from that article. This is not a trained typed entity slot or a proof of semantic relation correctness.
- **scrambled_link**: changes the public title link target without changing the lexical score or Top-K; negative graph-lesion control.
- **hash_random**: deterministic SHA256 random citation control from the same full source pool.

No pretrained Granite forward, no SGD step, no model generation and no final answer production occur in this study. The objective is **support-sentence precision, recall, F1 and exact citation match on genuine existing human questions**, not answer accuracy.

## Four-stage physical qualification

1. **Source contract:** 13 fixture/adversarial tests normally and 13 tests with Python -O -S. No ML packages installed.
2. **Original source owner:** download official pinned dev distractor dataset, verify full raw SHA/7,405 cases, publish only question/article/sentence tuples separately from restricted answer/support labels. Every gold fact must refer to a real supplied original sentence.
3. **Blind proposer:** never mount restricted labels. Freeze each arm and Top-K once, produce create-only, SHA-bound predictions on all 7,405 public questions. No global held-corpus vocabulary cache or hidden-source indicators.
4. **Independent postseal review:** only after proposals exist, mount original hidden gold; independently validate each citation against the public original context, score full source denominator at each budget, report both bridge and comparison question types and difficulty. Answer-string occurrence in a selected citation is explicitly **not** a final answer prediction.

These are **job-level** controls, not cryptographic isolation from authorized GitHub artifact readers. Upstream labels are from public benchmark dev data, not genuine future-time data or unpublished external independent adjudication. Question/article overlap further limits confidence interpretation.

## Existing local evidence / strict no-go

The four original executable Python files pass **13/13 local tests** normally and **13/13 under Python -O -S**, including modified secret, forged article/sentence citation, budget overflow/duplicate, source SHA mutation and hidden answer-field injection. The tested files are byte-identical to remote Git blobs. Source dataset retrieval and full human citation outcomes cannot be called PASS until the exact-head four-stage GitHub Actions run has completed and its original receipts are independently reviewed.

**DENY_ALL forever in this study.** Original V7 three-way retention+natural+relation qualification remains failed. No trained Stem, Cell promotion, FinalUse authority, human multi-hop question-solving claim, NDU optimizer win, world model or FBSDE global solver is delivered here.

The next decision is whether a source-bound typed mention/variable linker on a separately frozen TRAIN cohort can actually outperform these same-budget cheap controls, on a held human task population, including costs and old-task retention, before allocating expensive System2 resources.
