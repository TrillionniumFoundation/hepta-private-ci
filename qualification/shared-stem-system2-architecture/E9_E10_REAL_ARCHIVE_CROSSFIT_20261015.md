# E9/E10 — Real archived dual-Stem crossfit and independent Pareto NO-GO

**2026-10-15 | Research-only, Draft / DENY_ALL.** This additive child is stacked on [#2101](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2101), itself a continuation of [#2082](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2082), [#2065](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2065), and [#1923](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1923). Existing inference Worker, NDU owner, selected model, native Q24/Q32, original FinalUse, blocking CI, objective, signing and effect authority remain unchanged.

## Motivation and exact original physical source

E7's 128-row AG News retrospective panel found Granite97-only **122/128**, whereas three fixed confidence-gated second-Encoder routes scored 118/128, 112/128, and 102/128 and increased the archived time proxy. An impossible hindsight oracle that knows each original label could select between the two fixed pretrained classifiers for **126/128**, but this is not an inference-capable policy.

Two existing, successfully executed, SHA-pinned GitHub Actions ZIPs are reused:

- Real Granite Embedding 97M/mmBERT-small pretrained model predictions from Actions artifact **11908591037**, SHA-256 **d8e2af397d7ea862245fae0337588ab491dd70e8a8a9a42879e4a7f2d4be3afa**.
- The historical independently archived original source panel and labels, artifact **11886761368**, SHA-256 **e5d945c655112139fce51b989023abd5111c9e7ab28d9bd4e8a771b86dd95f9d**.

Original successful Encoder runs are historical. **No new pretrained Encoder weights are downloaded and no new Encoder forward pass occurs in E9/E10.** The second Encoder calls in this analysis are counterfactual switches between existing completed predictions; the time sums are original per-model meter **proxies**, NOT physically measured on-demand conditional-serving latency.

## E9 — Train-only policy selection, source-group-disjoint within one original corpus

1. **Prelabel source-only seal:** code loads *only* the exact physical pretrained ZIP; labels are unavailable. It freezes the original five candidate policies, every original input/group digest, both model probabilities and observed original per-case model time columns. Exact group-digest hashing with the frozen salt "hepta-e9-folds-20261015-v1:" deterministically partitions 128 distinct group IDs into exactly four 32-row folds. No label is used to split.
2. **Train-only extraction:** only after the source-only seal is written create-only, a separate process downloads the original historical labeled ZIP. For fold k it writes exactly 96 other-group labels and **no labels for its own 32 held-out groups**. It removes the original label ZIP before fitting policies. This is a programmatic per-process source barrier, **not cryptographic isolation between malicious same-host processes**.
3. **Four independent fits:** one per fold, accepting only its own 96-row training-only manifest, picks among frozen: Granite-only, mmBERT-only, and confidence thresholds 0.75, 0.90, 0.98. The fixed order is maximum TRAIN correctness, then minimum TRAIN Brier, then minimum TRAIN original-meter proxy cost, then original arm order. There is no learned Encoder, Head SGD, outcome-defined private reward, or post-hoc threshold addition. Choices are sealed **before** held-out labels are scored.
4. **After-seal score:** the source panel labels are reacquired only after all four fold choices are sealed. Each test group is scored with a policy selected without its own label; the evaluator reconstructs each 96-row training manifest from the original historic label ZIP and verifies the declared train source SHA, all five training scores, and the exact selected argmin policy. A forged fitted winner is rejected.
5. **Second independent score:** the separate e9_independent_review.py does *not import the first fit/proposer/scorer*. It opens both original SHA-pinned ZIPs and independently derives all original probabilities/labels, each fold's train source hash, train five-arm ranking, and held-out score. If any raw input, prediction, training decision or aggregate score disagrees, it fails closed.

**Completed real archived 4-fold result, local Python 3.13:**

| Fold | Original TRAIN groups | Held-out groups | Chosen fixed route |
| --- | ---: | ---: | --- |
| 0 | 96 | 32 | Granite-only |
| 1 | 96 | 32 | Granite-only |
| 2 | 96 | 32 | Granite-only |
| 3 | 96 | 32 | Granite-only |

Across all 128 out-of-fold original cases, crossfit = Granite baseline exactly: **122/128 = 95.3125%**, Brier **0.03988751591276781**, original archived per-case meter proxy sum **5,700.054211 ms**, hypothetical extra mmBERT calls **0**. Independent second original-ZIP reviewer confirmed both the original source/label identity and all four fit choices. This is a **negative incremental-learning result** for choosing among these fixed policies on one old AG News family; it is NOT independent future observation-time, source-family OOD or natural multimodal/system-level reasoning efficacy.

The original source-only prelabel SHA-256 is **7175432a8694e984542949719cf37d4da12544c6cd6054f1356b4ad36790c8e5**; exact original after-seal primary score SHA-256 is **29bf756ee78d9c4a467151560683a3f9ae9a39e6e9fea7431a977472304f3e44**. Committed immutable aggregate-only scores are in observations/E9_ORIGINAL_4FOLD_CROSSFIT_LOCAL_20261015.json and observations/E9_INDEPENDENT_ORIGINAL_TWO_ZIP_LOCAL_20261015.json. Only outputs from the original local executed files are reported; the hosted research job must reproduce them on its own.

## E10 — Exact paired effect and Pareto cost comparison

e10_paired_pareto.py consumes BOTH prior E7 independent historical aggregate audit summaries, rejects any count, source, cost, constraint or claim disagreement, and computes:

- exact two-sided paired McNemar values from original improved/lost counts with exact integer binomial sums, not asymptotic p-values;
- preregistered **four-hypothesis Holm familywise adjustment** using exact rational arithmetic;
- per-policy accuracy, Brier and **archived single-model meter proxy** Pareto comparisons.

| Retrospective arm | Recovered / lost relative to Granite | Correctness change | Extra archived meter proxy | Brier |
| --- | ---: | ---: | ---: | --- |
| mmBERT-only | 4 / 53 | −49 | +3,000.959 ms | worse |
| threshold <0.75 | 3 / 7 | −4 | +1,032.731 ms | worse |
| threshold <0.90 | 3 / 13 | −10 | +1,717.323 ms | worse |
| threshold <0.98 | 3 / 23 | −20 | +4,161.587 ms | worse |

On this *fixed retrospective panel and these registered three metrics only*, Granite-only strictly dominates every alternative in accuracy, Brier and historical proxy cost. Therefore under the restricted defined objective of accuracy minus any **nonnegative** cost penalty on the recorded proxy, these four candidates cannot win on this cohort.

Exact paired McNemar two-sided unadjusted → Holm adjusted:

- mmBERT-only: 106481/18014398509481984 → 106481/4503599627370496
- threshold <0.98: 369/4194304 → 1107/4194304
- threshold <0.90: 697/32768 → 697/16384
- threshold <0.75: 11/32 → 11/32

These p-values are **exploratory within a single retrospective AG News family** and cannot be used to assert iid future observations or real-world improvement. The label-oracle 126/128 is retrospective and cannot be presented as a deployable policy. E10 returns **NO_GO_FOR_PROMOTION**, not a model selection.

## Test and hosted sequencing

The two new test modules contain **21 tests**, independently completed locally with both exact original ZIPs under normal Python 3.13 and under Python -O: **21/21 each**. Negative tests include forgery of score, trained fold selection, leaked held-out label, source/group identity, original model probability, noncanonical seals, wrong threshold/arm roster, unknown/future/prod claims, cost/count manipulation, exact binomial and Holm. A synthetic control positively selects mmBERT-only when its training evidence genuinely beats Granite, proving the learned policy gate is not hard-coded to the negative outcome.

Dedicated read-only Actions workflow: .github/workflows/hepta-e9-e10-physical-crossfit-review.yml.

Execution order is explicit: pin current source → fetch only physical ZIP → prelabel seal → fetch original labels → extract four train-only manifests → remove historical ZIP → four separately sealed fits → only then re-fetch historical ZIP → independent original-source postseal E9 score and second algorithm → exact E10 Pareto → normal and -O tests → retain failed evidence. The hosted workflow does **not** grant a model selector, access to production original authorities, a full stochastic FBSDE theorem, or final-use permission.

Independent quality gates left open: completed exact source/merge blocking CI; authenticated future-time independent-source labels; Reader sufficient-evidence; actual physical conditional Stem calls and full-life-cycle RAM/p95/p99/energy; 64/256/1024/4096 native Cell shared fanout; genuine additional modality/cross-event tasks; old-task retention/OOD; independently accepted NDU and full globally consistent nonlinear stochastic FBSDE with error/cost certificates, budgeted against **cheap Bellman/Critic**, plus Decoder/Verifier resource cost.

**All production and efficacy claims remain false:** production_accepted=false; stochastic_ndu_qualified=false; system2_real_net_utility_gain=false; stem_selected=false; DENY_ALL.
