# Tiny Cell evidence-sufficiency gate: archived Qwen outcomes, NOT a new model gain

Research-only extension of [`TrillionniumFoundation/hepta-private-ci` PR #1546](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1546). The original frozen Qwen2.5-0.5B-Instruct (revision `a338b55dd21219a5f4da42bc11a9313d1a27d4cc`) and Hepta Encoder, Reader, verifier, Rust NDU/FBSDE, Riccati, production serving, and `main` are **unchanged**. No new pretrained model call is made. Historical model calls and raw answers are preserved unchanged.

## Why this next control

Three independently externally pinned **COMPLETED** frozen-model archives show a sharp split between (1) retrieving/generating an exact TAG code from a supported fact and (2) refusing to use unsupported facts. The newly completed **200-call** token-length matched E/neutral-label placebo experiment ([run 38347023330](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38347023330), artifact 11790630289, ZIP SHA256 `6f10c884f949a8518294b1b320cb2d5374232edbe3bafc881826a96e1723e9b6`) found exact answers of **2/20 and 0/20** with E labels, **1/20 and 0/20** with equal-length neutral labels, versus **19/20 and 19/20** without a label field in two supported two-fact source orders. All three labeled/neutral/unlabeled single-decoy-only conditions had **0/20 required refusals and 20/20 unsupported TAG copies**; empty evidence had **20/20 correct refusals**. Equal **input-token count** does not imply equal token identities, CPU, or a causal semantic-label conclusion.

A candidate light Cell could decide **before inference** whether evidence is sufficient. But a hand-coded, frozen exact subject-match rule may already solve this narrow closed grammar. We must compare them explicitly rather than credit a learned Head for what a cheap fixed parser already achieves.

## Frozen protocol and provenance

| Archive | Task identities | Role | Original neural calls |
|---|---|---|---:|
| [Qwen lexical factorial 38333959891](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38333959891), artifact 11784676839, SHA256 `0fd2a2aa60c0c28bdd61a2566262558410bb66c6997355aa610fe98b89aabc19` | original numeric indices 60:80 | Training: clearance/TAG profile only | 320 total, 80 selected for training |
| [Qwen label/order 38338426544](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38338426544), artifact 11787041990, SHA256 `8da46b3965f8a6aa9919877c8165e6a2d06f3298921e645d91f7cddfcf9b8761` | indices 80:100 | Training: unlabeled representation only | 180 total, 100 selected for training |
| [Qwen equal-token placebo 38347023330](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38347023330), artifact 11790630289, SHA256 `6f10c884f949a8518294b1b320cb2d5374232edbe3bafc881826a96e1723e9b6` | indices 100:120 | **Evaluation only**, 20 exposed synthetic task identities and 200 condition calls | 200 |

Archive reader checks **external ZIP SHA256, every internal SHA256SUMS entry, exact generating commit and tree, raw answer seal, input-preflight seal, start/answer position census, Reader identity/model/revision, source original bytes, source-root digest and generated/inference token and CPU counters** before training/evaluation. No zip member is extracted or executed. Source identifiers remain bound to the original facts. The complete 320/180 archives remain intact; only the predeclared subsets contribute supervision.

The training Head sees **40 distinct questions** represented by **180 correlated training positions**, with a fixed six-number lexical stem: intercept, whether the queried device occurs in a trusted exact device→TAG fact, source count, other-fact count, presence of any TAG fact, and absence of evidence. It receives **no question ID, arm, gold TAG answer, archived Reader answer, or label field**. One **six-scalar linear logistic Head** is trained with deterministic full-batch SGD for **240 fixed updates** (question-macro weighting). A second Head trains after shuffling source-support labels with fixed RNG seed. No hyperparameter or threshold tuning on the 20 evaluation questions.

At evaluation the trained and shuffled Head weights are saved/frozen **before** decisions. All five actions—`always_call`, `never_call`, `frozen_exact_match`, `learned_head`, `shuffled_labels`—are written and SHA256-sealed before reading saved Reader text/target-code scores. The `frozen_exact_match` baseline has no training steps and uses the exact same observable fact/device matching as the input feature. The evaluation corpus was **already exposed** in the preceding label study; it is not an untouched independent task/domain confirmation. Intermediate relation grammar is shared across all cohorts.

## Actual local completed archive replay (Python 3.13; zero new Qwen calls)

All **three ZIP hashes**, all **60 original question identities**, full archived answer seals, internal SHA256 inventories, bound source spans and model identities were checked. **180 training source positions** and **200 evaluation source positions** were loaded, **1,000** frozen hypothetical decision cells were sealed, and all 13 focused tests passed. All model answers were generated **before** this analysis in authentic GitHub-hosted runs.

| Frozen decision rule | Would call Reader | Correct supported answers | Correct refusals on insufficient evidence | Aggregate correct (of 200 correlated conditions) |
|---|---:|---:|---:|---:|
| Always call archived Qwen | 200 | 41 | 20 | 61 |
| Always abstain | 0 | 0 | 80 | 80 |
| Fixed exact subject/source matcher | 120 | 41 | 80 | **121** |
| **Six-parameter trained Cell Head** | **120** | **41** | **80** | **121** |
| Shuffled-label Head | 200 | 41 | 20 | 61 |

The learned Head and frozen zero-training matcher **disagree on 0/200 actions**, and the trained Head has **zero incremental correct decisions**. Under the replay-only counterfactual, avoiding 80 prior Reader calls corresponds to **290,034,156,547 nanoseconds of original archived Qwen decoder CPU work**, but **actual decoder CPU saved in this retrospective experiment is exactly zero**: all 200 calls were already made. This number is not a future CPU saving guarantee, a model-FLOP estimate, or a per-question deadline. The cheap fixed matcher handles the same artificial grammar at lower training cost and is the appropriate winner. The Cell candidate **fails the incremental-value admission gate**; do not train it longer or invent more Cell replicas.

The 121/200 successful response-control *positions* share **20 synthetic numeric questions**, and 80 correctness gains include **externally imposed refusals**, not Qwen-generated refusals. This is **not** a 121/200 standalone Reader accuracy claim or genuine multi-hop/NDU improvement. Source-rule sufficiency in this synthetic grammar is not a human judgment of document support.

## What a subsequent worthwhile test needs

Move beyond identifier equality and closed synthetic grammar: fixed independent natural-language evidence / entity/time/permission ambiguities, strong Retriever + fixed Reader controls, independent sufficiency annotations and refusal judgments, and a computation-matched frozen comparator. A tiny Head may be considered only if it **improves safe utility over both the exact nonlearning rule and shuffled/frozen Head**, without leaking labels, changing the Reader, or sacrificing valid supported answers. Multi-Cell scaling, parameter sharing, NDU/FBSDE learned reasoning or 10T/100T model-equivalent capacity are **not established** here.

## Reproduce

Download the three exact GitHub Actions ZIP artifacts, retaining their published outer SHA256 values, and from the exact checked-out research SHA run:

```sh
export HEPTA_MEMORY_TESTED_COMMIT="$(git rev-parse HEAD)"
python scripts/memory_cell/system2_cell_support_gate.py \
  /path/to/qwen-lexical-320.zip \
  /path/to/qwen-tag-label-180.zip \
  /path/to/qwen-placebo-200.zip \
  /new/output-directory
```

Output includes frozen model weights, source/threshold plan, 1,000 action records, a prediction seal generated **before** scoring, complete paired outcomes, explicit zero additional model calls, and failure receipts. Existing blocking CI must pass; no default serving or production acceptance follows.
