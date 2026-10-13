# LoCoMo frozen-Qwen: answerability and refusal-format attribution

**October 13, 2026 · Completed original Qwen model outputs · Read-only research.**

This report **does not rescore, overwrite, repair or promote** the original LoCoMo
16-question, 32-answer frozen Qwen2.5-3B study. It reconstructs exactly the
already-published normalized token-F1 first; a distinct, deliberately post-hoc
refusal-prefix calculation is presented **only as a diagnostic sensitivity**.
A leading refusal may be followed by contradictory or unsupported content;
its semantic validity has **not** been independently adjudicated.

## Independent input pins and real execution

| Original exact GitHub Actions source | Artifact ID | Entire ZIP SHA-256 |
| --- | ---: | --- |
| Published public LoCoMo questions/5,882 turns | 11728164433 | `51e18514c68f31220f4dcd072914f6e015aa9733b6c5b4a4d4e3b14dac25ec37` |
| Original frozen six-arm retrieval decisions | 11729394703 | `3fb1c3272314d31b42ece1c74aa0250e2ecb06c6060cb011071d4654fef6f097` |
| Original separately sealed evaluation targets | 11728856834 | `d09823324003ab431301e60fbbb280e216ca03b686e178d4f36fb6d492981978` |
| **Original 32 true Qwen generations** | 11763718022 | `7160ede72114b04135e544fb687a804dc0c4852834cf1695440a75b85214bf48` |
| **Completed separate hosted score** | 11766482516 | `5c36103c506367de2ba42ea242bc81b53ad9734f1417132ce2945d0473ed391e` |

The original model and scorer are from [Actions #38280267308](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38280267308), generating commit `96b5ec37b82f87d445740403e07e3705e9850955`, frozen model inventory `f9aa334d3a02cabececea367c283caf66ef9875132907ebc34dac1c8d3a7f225`. Exact original 32-row journal SHA-256: `b13f70b5b8ff0664d7a446b11b2a474702d61a50348534ca1b26cc295a0e9bb2`.

## Original metric versus post-hoc format sensitivity

| Evaluation subset | Lexical top-4 | Lexical top-8 | Implication |
| --- | ---: | ---: | --- |
| **Original registered mean F1 (all 16)** | **0.172082581** | **0.111481901** | Original k8−k4 = **−0.060600680** |
| **13 answerable tasks only: original token-F1** | 0.134870869 | 0.137208493 | k8 slightly higher on these 13, not independent superiority |
| **3 unanswerable: exact standalone refusal** | 1/3 | 0/3 | Registered metric treats additional refusal explanation as failure |
| **3 unanswerable: canonical refusal sentence is a prefix** | 3/3 | 3/3 | Does **not** certify that the trailing text is safe or entailed |
| **Post-hoc prefix-refusal sensitivity, all 16** | 0.297082581 | 0.298981901 | Sensitivity delta **+0.001899320**, not a substitute official score |

The original aggregate k8−k4 F1 delta decomposes *exactly* into **−1/16 = −0.0625** from the three unanswerable items and **+0.001899319968** from all 13 answerable items. One k4 abstention was an exact standalone refusal; the other five originally generated unanswerable outputs across both arms started with the canonical refusal but appended unreviewed explanation. This is a **scoring-format confound**, not evidence that the six responses are truthful or non-hallucinated.

## Retrieval-source coverage is not Reader sufficiency

The publisher's source-ID annotations are accessible *only to the post-generation auditor* and never influence the original frozen BM25 retrieval or Qwen prompts.

| Answerable queries, source-ID-based stratum | k4 count / mean F1 | k8 count / mean F1 |
| --- | --- | --- |
| All original publisher support IDs retrieved | 8 / 0.204134216 | 9 / 0.186801157 |
| None of the publisher support IDs retrieved | 5 / 0.024049514 | 4 / 0.025625000 |
| Explicitly unanswerable, scored separately | 3 / 0.333333333 | 3 / 0.000000000 |

On the same 16 paired questions, eight answerable items have all annotated IDs in **both** retrieved sets; four miss them in both; one first acquires all annotated IDs in k8; three are unanswerable. The *only* additional full-support case in k8 gains diagnostic F1 **+0.0689655**. The 8 already-covered cases show mean paired delta **−0.0026036**, and the four missing-both cases **−0.0044369**. Three unanswerable cases account for the larger registered aggregate difference. Input tokens still increase by **4,219** in k8.

**Critically, source-ID retrieval is not a human-certified sufficient evidence set.** Mean F1 of roughly 0.2 even when the annotated IDs were present cannot be attributed to reader model capacity alone: distractor packing, answer-expression mismatch, source granularity and publisher label quality remain possible. The next causal intervention is the **same frozen reader with publisher-support-only evidence** (annotation-accessing, diagnostic-only), then independently reviewed sufficient evidence when such review exists. A source-first human review packet has already been prepared but contains **zero authenticated independent decisions**.

## Fail-closed reproducibility and release posture

`locomo_refusal_attribution.py` checks each exact outer archive hash, all available inner manifests, original source population and 5,882 source texts, frozen retrieval order, original model identity/budget and every delivered UTF-8 excerpt; then re-scores 32 original answers with the unchanged registered scorer and compares the result to the separately completed hosted score **before** emitting the sensitivity. It rejects duplicate JSON keys, nonfinite tokens, missing attempts, edited answers, forged source excerpts and modified original ZIPs. The output contains **no copied answer text or publisher gold answers**.

```
PYTHONPATH=scripts/memory_cell python3 scripts/memory_cell/locomo_refusal_attribution.py \
  locomo-public-original.zip locomo-retrieval-original.zip \
  locomo-targets-original.zip locomo-qwen-32-original.zip \
  locomo-qwen-hosted-scoring.zip \
  --out observed-locomo-refusal-strata-38280267308.json
```

The pinned read-only CI job independently repeats these checks and byte-compares its result to the saved summary. Only **after** exact-source and original hosted-score verification, floating summary fields are rounded to **12 decimal places for cross-Python stable JSON serialization**. The registered original metric, model answer text, original receipts and all scientific decisions are never changed; strings, IDs, booleans and denominators remain exact. The post-hoc reviewer-label ZIP is not even opened by the auditor until the original source, frozen choices and generation receipts have been validated. These are **two previously exposed conversation-family proxies**, not independently verified future families. No statistical significance, human-certified semantic citation precision, general memory advantage, lifelong retention/recovery cost or production admission follows. `retrieval_policy_promotion_qualified=false`, `parameter_memory_qualified=false`, and `production_accepted=false`.
