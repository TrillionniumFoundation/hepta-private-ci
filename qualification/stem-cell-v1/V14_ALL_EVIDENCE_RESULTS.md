# V14 — source-only all-fact entity slots: benchmark false confidence exposed

**DRAFT · RESEARCH_ONLY · SHADOW · DENY_ALL · NO PRODUCTION PROMOTION, MAIN MERGE, NDU/FBSDE CLAIM OR MODEL SELECTION.**

## Scope, exact prior evidence, and caveat

Stacked on the original V13 Granite frozen-link study [PR #2443](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2443) at SHA `5eacb94f22cc3bdd262462535c2d28e7066f2422`. Original V10 pretrained Granite revision `835ad14087e140460703cf0fae09f97d469d65c2` and original V12 heldout sources are unchanged. This is a **cheap standard-library lexical-candidate discovery diagnostic using original source text, with ZERO additional Granite Encoder forward and ZERO SGD updates**. It does NOT demonstrate a trainable neural entity extractor or a new biological-style differentiated Cell.

The major difference from V13 is that the primary original-input inference path **is not handed a list of two facts at each relation hop, nor the original six relation-regex templates, nor gold support indices**. It ranks all words in each sentence by **source-group document frequency**, proposes two typed-UNLABELED word slots by surface order, builds a directed co-occurrence graph from ALL fact sentences, starts with the first matching query word and chooses answers by shortest reachable graph path. It assumes a two-alternative multiple-choice question, a maximum of six steps and readable surface strings. This is an intentionally fragile low-cost heuristic, **not a semantic proof**. Only the separate scripted-paraphrase GENERATOR and the independent heldout TRUTH reviewer use a known six-template synthetic grammar.

## Original SHA-bound input, blind chronology, and source groups

Read the exact public V10 source archive from [GitHub run #38820394598](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38820394598): original ZIP SHA256 `efee1e07fdb26cb9f3222a86244ad8a41062b0c647a3be762d76c688826995af`; exact public.json member `1b027fd2708068da25674415789906a575a00383abe5712255a432e8679e913c`; source-seal.json member `4de11a06a4d481696fe6efc3a6a1f8085806aeffc7f20a3d14fb07d4dc30d608`. Original held-label ZIP `b98fa92913d07e34a67c0e45c3e021308cd9a56ce5c64c02c31a243a35be28b4`, held-label member `31fc4230ce888e325c8b956af0f6bab5b17d8825d3a5e9b9f26a46e65974ea73`. These are synthetic generator labels, not human adjudications.

The source has 312 independent paired-world groups / 1,248 candidates, split into 72 TRAIN groups / 288 candidates and 120 known + 120 novel held groups / 960 candidates. The model proposal stage receives only public source/metadata; original held labels were opened only in **a separate postseal review process**. It seals all 3 perturbations × 4 strategy arms × 960 held predictions before ground truth is read. Original held source groups (not four correlated candidate rows nor model seeds) are the independent score unit.

Plan SHA256: `d4063bb8d257daad12cd2ffec57556b1f6ebc1704626fbdf758a8d79f21a2489`. Sealed predictions SHA256: `faa97a19b81d96913a1005b2cb1e1fb21fa288013bdb43339f89b551ba7da7cc`. Independent score rows SHA256: `21c991d68fd574bd1601f028e3f6296d81e8f80002805d8f252b1b2e0013d7f8`.

## Main results — two explicitly DIFFERENT access regimes

All values below are correct candidate answers out of the same 480 held candidate rows per role; **abstention counts as incorrect**, and zero correct on scripted paraphrases primarily means zero coverage, not 480 confidently wrong answers.

| Original phrase policy | Known held | Novel held | Known both-world paired /240 | Novel paired /240 |
| --- | ---: | ---: | ---: | ---: |
| Inductive, TRAIN-only source-group DF | **304/480 (63.33%)** | **364/480 (75.83%)** | 144 | 172 |
| TRANSDUCTIVE, all 312 groups' UNLABELED source DF | **470/480 (97.92%)** | **480/480 (100%)** | 230 | 240 |
| Reverse all directed slots (negative lesion) | 2/480 | 0/480 | 0 | 0 |
| Fixed lexical first candidate | 240/480 (50%) | 240/480 (50%) | 0 | 0 |

The transductive arm **reads every held source TEXT during DF construction**, but no held label; therefore it is INVALID as a future-source or time-prospective generalization claim. Its impressive 97.9–100% result demonstrates the limited, exploitable regularity of this generator, not neural reasoning. It uses **zero trainable parameters and no Granite model at evaluation**; the cheap exact grammar solver was already 100%/100% at this synthetic domain.

The inductive TRAIN-only case exposes the real zero-shot problem. Per-depth correct /96 candidates:

| Held cohort | Depth 2 | Depth 3 | Depth 4 | Depth 5 | Depth 6 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Known, TRAIN-only | 96 | 96 | 96 | **8** | **8** |
| Novel, TRAIN-only | 96 | 96 | 96 | **76** | **0** |
| Known, transductive | 96 | 96 | 96 | 94 | 88 |
| Novel, transductive | 96 | 96 | 96 | 96 | 96 |

TRAIN never contains 5–6-hop source relation classes, so the cheap lexical slot heuristic mistakes previously unseen words such as building/district for endpoint entities. Incorporating all unlabelled held public source text resolves many of these words' DF ranking ambiguities. That is **test-input transduction**, not proof of learned relational typing.

## Robustness: same facts, different meaning-preserving SURFACE realization

Every fact was also rendered into a scripted synonym/order-swapped sentence, without changing the original source graph or labels (e.g. “The coin belongs to Ada.” → “Ada owns the coin.”). These perturbations are **automatically scripted templates, NOT original human prose**, and were sealed with original predictions before postseal review.

| Transductive policy | Known /480 | Novel /480 | Abstentions known /480 | Abstentions novel /480 |
| --- | ---: | ---: | ---: | ---: |
| Original source wording | 470 | 480 | 8 | 0 |
| Sentence order (fact-list permutation only) | 470 | 480 | 8 | 0 |
| Meaning-preserving surface paraphrase | **0** | **0** | **478** | **480** |

The paraphrase collapse is **almost pure refusal/unresolved paths** rather than certain wrong answers. Fixed-first-answer still yields exactly 50% under the paraphrase, confirming task labels are unchanged. In contrast, reversing fact *list order* leaves results unchanged. Reversing relation SLOT direction causes 0 paired successes, so the direction really matters; this is not a simple class-prior or fixed-position classifier.

Exploratory source GROUP-level 95% paired bootstrap intervals for transductive-minus-inductive candidate accuracy are **+34.58 percentage points [26.67, 43.33]** (known) and **+24.17 [17.50, 31.25]** (novel). They are descriptive/posthoc repeated-data uncertainty, not preregistered general scientific superiority or independent external adjudication.

## Local physical validation and hosted handoff

Actual separate local source-only proposer CPU: about 0.34 seconds for all 12 policy/perturbation arms; original ZIP decoding, original historical pretrained Encoding, postseal bootstrap and full lifecycle are separate costs. 12 adversarial/behavior unit tests passed in ordinary Python `-S` and separately 12/12 with Python `-O -S`. Independently rerunning the full source and secret-file byte digests, complete 960-case group membership, label reconstruction from public synthetic semantics, path grounding and 24 score cells matched original held owner. **Exact GitHub hosted CI must still run on current SHA.**

Source owners and original v14 public campaign refuse missing/changed label-free fields; all DATA/JOIN digest checks are fail-closed. The dedicated V14 Actions job downloads original PUBLIC artifact to a label-blind Runner, seals results and uploads it, then a separate Runner obtains the original HELD truth for independent `python -S` review. It never uploads hidden targets into the proposer job and never calls Hugging Face or a training worker.

## Scientific decision and next engineering investment

**NO_GO** to claim a model win from this synthetic benchmark. No original V7 joint retention/natural learning pass, no original-human question/citation verification, no prospective calendar cohort, no actual learned typed entity proposer, no NDU/FBSDE value advantage, and no production/signed FinalUse result. Keep **DRAFT / DENY_ALL**.

Next invest in a natural-language source-first relation corpus with explicit human-checked entity/reference spans, candidate generation *without test-corpus vocabulary prepass*, semantically equivalent rewrites, new entity names and 2–6 hop compositional generalization. Test matched frozen Stem, cheap rule/string graph, V13 frozen cosine and typed/neural Cell head under **the same full lifecycle cost**, grouped whole-question correctness, and conservative negative-transfer/retention controls. Expand neural System2/FBSDE recursion only on verified causal gain.
