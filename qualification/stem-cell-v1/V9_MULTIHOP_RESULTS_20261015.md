# V9 controlled 2–6-hop relation graph: negative neural-transfer result

**RESEARCH_ONLY / SHADOW / DENY_ALL / NO MAIN MERGE / NO MODEL PROMOTION.**

Stacked on V8 PR #2370 exact parent `4ceb4ffd3c40f315cf641c6873a099921e85776f`. Original V7 PR #2352 training, security/authority, native runtime, production model selector and failed joint admission remain unchanged.

## Registered source and method

The four-row paired-world generator includes **312 distinct synthetic source groups and 1,248 candidate rows**: train-role 72 groups/288 rows (2–4 hops), known-vocabulary heldout 120 groups/480 rows (2–6 hops), new-vocabulary heldout 120 groups/480 rows (2–6 hops). V9 does **not** fit on any of these data. Each group has two counterfactual ownership worlds and two candidate answers; swapping worlds changes each candidate's truth without changing its total word inventory. The new lexicon is disjoint across all entity types; **source-disjoint does not mean prospective-time or natural-language-disjoint**.

Separate job-facing steps: source creates public JSON and answer-owner JSON; blind proposer consumes public facts/question/candidate only; postseal reviewer rederives truth via an independently coded graph parser, checks grounded proof transitions, source hashes, completeness and pairwise scores. Hashes do not authenticate outside actors.

## Executed locally: cheap exact nulls

| Method | 1,248 rows correct | Both-world pairs correct /624 | Abstain |
| --- | ---: | ---: | ---: |
| Bounded proof-carrying full graph | **1,248** | **624** | 0 |
| Fixed two-hop-only graph | 288 | 144 | 960 |
| Constant FALSE | 624 | 0 | 0 |

**1,536** successful proof receipts were independently replayed (1,248 full + 288 two-hop). Predictor counted **0** SGD updates, **0** pretrained model calls; local predictor compute CPU across all three controls was **0.053768 seconds**, excluding source materialization, reviewer and other lifecycle work. This narrow, deliberately machine-readable grammar has a straightforward algorithmic solution; the 100% score is **not emergent neural reasoning**.

Public source SHA256: `2ff72082d18b62c622f1108f07fbe8424bd9602d95bc2a64734fb95ed02305e9`.
Sealed exact symbolic prediction SHA256: `69854bc292476b7bfd0fdda22b46b56dc253736b22d628fa2531ebdaa0c17ebd`.

## Actual frozen V8 neural checkpoint re-forward

**Twelve existing synthetic-trained Torch models** (seeds 41/47/53 × Base/FactBridge/Wide/Endpoint) were loaded from locally retained V8 safetensors, physically forwarded on all **1,248** new tasks, and postseal-scored from **14,976** raw per-case probabilities. No V9 model fit or heldout checkpoint selection. The original synthetic lexical vector generator and seed 619 were reused for 2-hop grammar; added entity types use deterministic new dimensions. **These are synthetic feature vectors, NOT real Granite97M outputs**. SHA256 of each of the twelve original trained model files is pinned in `v9_frozen_v8_readout.py`; scorer independently requires the complete inventory digest.

| Trained V8 arm across three model seeds | Held correct /2,880 | Held both-world correct /1,440 |
| --- | ---: | ---: |
| Base | 1,452 (50.42%) | 156 (10.83%) |
| FactBridge | 1,435 (49.83%) | 194 (13.47%) |
| Endpoint | 1,446 (50.21%) | 185 (12.85%) |
| Wide Head | 1,433 (49.76%) | 113 (7.85%) |
| Cheap typed graph (one copy of held sets) | **960/960 (100%)** | **480/480 (100%)** |

The **same 240 heldout source groups** were evaluated by each of three training seeds; the 2,880 neural outputs are repeated results **not 2,880 independent cases**. No trained neural arm wins generalization. Differences in paired scores do not establish an architecture winner, matched full-life-cycle cost, NDU benefit or FBSDE efficacy.

Selected frozen-forward timer: **2.084384 s CPU**, scoped to 12 checkpoint loads/Reader forwards; synthetic bank materialization, process import, model fitting and independent scoring are excluded. No pretrained Encoder or model decoder invocation in V9. Frozen probability digest: `ce6dad844f297cab30e30da485216a2ae56df9c53f963589da9a88f6178a6b37`. Independent scoring digest: `7be238e07abf82055a0a69436d80ccd30c17627e0fce171c1f5f78f5685d24a9`.

## Implementation / local validation

Research-only additions: `v9_typed_graph.py`, `v9_source_panels.py`, `v9_blind_benchmark.py`, `v9_independent_review.py`, the original-weight readout and independent scorer, source tamper tests, and an exact-HEAD four-job source-only CI workflow. **36/36 local tests passed in ordinary mode and 36/36 independently under `python -O`**, no skips. All core source GitHub blobs are separately byte-checked against local tested material.

The dedicated workflow must run on the new exact commit; no queued workflow is reported as PASS. Archived weights/raw per-case probabilities are in the separate downloadable experiment bundle, **not committed to public GitHub**.

**No-go:** original V7 joint relation/natural/retention qualification still fails; original feedback/fresh gates remain closed. No real Granite feature learning, natural MultiRC heldout improvement, future-source/time evidence, multimodal reasoning, FBSDE stochastic global solver, selected Stem, FinalUse or production qualification. A rule-based solution to this tiny grammar is not evidence that a general neural world model has learned the same operations.

**Next:** physically use the original pinned `group_encoder.FrozenTokenEncoder` Granite 97M revision `835ad14087e140460703cf0fae09f97d469d65c2` to construct disjoint natural-language and longer-hop source cohorts; compare source-sealed trained Reader/transition Core to the cheap parser, ordinary matched-budget planner and NDU control; independently score complete questions, retained tasks, compute/cost and ground-truth citations. Only after causal gains are demonstrated should a globally consistent FBSDE continuation-field layer be added.
