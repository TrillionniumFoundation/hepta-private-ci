# MemoryCell: completed LoCoMo Reader + hosted score, exact-source reconciliation

**October 13, 2026 · Actual pretrained Qwen output · Research-only NO-GO**

The original [Actions run #38280267308](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38280267308) is **completed / success** (not merely reader-complete). Both the original `reader` and the separate `score` job passed. The generating source commit is `96b5ec37b82f87d445740403e07e3705e9850955`. This statement is grounded in the original host artifacts, not a rerun, a new score based on simulated answers, or an independent future-task sample.

## Immutable source and result identities

| Original artifact | GitHub artifact ID | Exact ZIP SHA-256 |
| --- | ---: | --- |
| Actual 32 original Qwen generations | `11763718022` | `7160ede72114b04135e544fb687a804dc0c4852834cf1695440a75b85214bf48` |
| Frozen public LoCoMo source and evaluation questions | `11728164433` | `51e18514c68f31220f4dcd072914f6e015aa9733b6c5b4a4d4e3b14dac25ec37` |
| Frozen, label-blind original retrieval | `11729394703` | `3fb1c3272314d31b42ece1c74aa0250e2ecb06c6060cb011071d4654fef6f097` |
| Separately sealed original evaluation labels | `11728856834` | `d09823324003ab431301e60fbbb280e216ca03b686e178d4f36fb6d492981978` |
| **Hosted score after generation** | `11766482516` | `5c36103c506367de2ba42ea242bc81b53ad9734f1417132ce2945d0473ed391e` |

The completed original journal's SHA-256 is `b13f70b5b8ff0664d7a446b11b2a474702d61a50348534ca1b26cc295a0e9bb2`. The original reader model-inventory identity is `f9aa334d3a02cabececea367c283caf66ef9875132907ebc34dac1c8d3a7f225`. Both original and hosted-scoring ZIPs have complete SHA256SUMS manifests (13 and 4 verified members respectively). The hosted scorer preserved the exact source files included in the original generation artifact; no original answer text was modified.

The independent model-free checker validated all 32 real original question/arm executions, 5,882 unique original history documents, original nested retrieval decisions, original selected source IDs, complete delivered UTF-8 evidence, source-root digests and immutable Reader settings **before opening** the externally pinned evaluation target ZIP. Its exact task and token-cost reconstruction agrees with the separate hosted scorer, including all 16 paired F1 comparisons.

## Actual matched Reader quality and cost

| Same frozen pretrained Reader, two public family proxies | Lexical top-4 | Lexical top-8 |
| --- | ---: | ---: |
| Real successful model calls | 16/16 | 16/16 |
| Diagnostic answers with original reference | 16/16 | 16/16 |
| Mean answer token-F1 | **0.172082581** | 0.111481901 |
| Strict normalized exact match | 1/16 | 0/16 |
| Complete prompt input tokens | **6,254** | 10,473 |
| Generated tokens | 705 | 824 |
| Sum of original generation seconds | 247.738 | 310.821 |
| Emitted structural citation labels | 11 | 15 |
| Answers referencing undelivered labels | 0 | 0 |

**The precommitted 16-question k8-minus-k4 comparison:** **3 wins, 7 losses, 6 ties**; mean paired token-F1 delta **−0.060600680031889904**. The eight-source arm consumed **4,219 more prompt tokens** (+67.46% against k4). The official matched-pair cost receipt independently confirms 16 complete pairs and an average **263.6875 extra prompt tokens per question**. Its observed average generation-time difference is about +3.943 seconds per paired question; these are heterogeneous host observations, not a controlled system latency or billing estimate.

**Interpretation:** adding four more retrieved sources did not rescue the reader on this fixed published LoCoMo development subset; it increased the observed prompt budget and worsened diagnostic answer F1. This is a descriptive research counterexample to assuming “larger k always helps,” not proof that k4 is globally optimal or that another learned/parametric memory system is better.

## Reproducibility and explicit non-promotion

The original canonical scorer is `scripts/memory_cell/locomo_frozen_reader_pair.py score`, whose SHA-pinned source copy in the score artifact matches the actual generator source. It checks the unmodified 32-answer journal and original public retrieval first; labels are opened only afterward. An additional standalone read-only replay plus hosted-score reconciliation and **eight tamper/metric regression tests** were run against the five pinned original ZIP archives. Those companion source/test files are supplied as downloadable artifacts with this analysis; no model weights or answer text are added to this repository. The JSON [`locomo-pair-hosted-vs-offline-38280267308.json`](../../scripts/memory_cell/data/locomo-pair-hosted-vs-offline-38280267308.json) records only source pins, paired metrics, and non-promotion decisions.

These are 16 previously published questions from only **two source-family proxies**; no independent family-adjusted statistical superiority, blinded sufficient-evidence review, verified citation entailment precision, prospective retention, real revocation/recovery TCO or production admission follows. The official scorer also records that a source citation label alone is **not** evidence that the cited text semantically supports the claim.

**Disposition:** no escalation of MemoryCell training or serving based on these observations. Next substantive experiment must compare the same frozen Reader against independently assembled and verified sufficient evidence and meaningful simple retrieval/filter controls on genuinely new source families, then assess answer quality, complete citations, total cost and failures before considering parametric memory.
