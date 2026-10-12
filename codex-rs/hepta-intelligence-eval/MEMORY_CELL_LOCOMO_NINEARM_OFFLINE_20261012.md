# MemoryCell: independently replayed nine-arm LoCoMo source-only retrieval

**12 October 2026 · Research diagnostic · NO model answers generated · Not independent future observation · NOT production admission.**

## Original publication and source boundaries

The original public LoCoMo ten-family proxy population was published by immutable source commit `fcc24ad653700ad5f47f09350cf7815242dc5de8` in [Actions #38206328621](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38206328621). Its `publish`, `retrieve`, `select` and `evaluate` jobs all succeeded, but that generating source predated the three fusion arms: **the hosted output contained only 480 six-arm decisions**, not 720 nine-arm decisions. It produced no reader responses. The published corpus may have appeared in pretraining, and its families are conversation proxies, not externally authenticated people or future histories.

A new **independent local, model-free replay** reused the six downloaded *original* source and result ZIPs, checking each complete SHA-256 pin. It reconstructs all 480 originally published lexical/recency decisions **exactly**, then applies the later, fixed equal-weight rank-reciprocal-fusion rule (`1/(60+BM25 rank)+1/(60+recency rank)`) to the **same frozen 80 source-only questions** for three additional k values (2, 4, 8). This gives **720 deterministic original-source decisions** without using any QA target to choose evidence or parameters. It compares the old six-arm selection and evaluation numbers against the original hosted receipts.

Role isolation was enforced physically: the `retrieve` process had only original public histories and old frozen decisions; `select` was later given the **16 selection-family targets only**; finally, after freezing the policy to disk, `evaluate` was separately given the **16 evaluation-family targets** and old published result. The ten published families remained partitioned 6 train, 2 policy selection and 2 evaluation, with 48/16/16 preselected questions. Original 5,882 historical source turns and question/source census were preserved.

### True source-ID support coverage and cost

All scores here are exact *published annotated source-ID set coverage*, **not generated Reader correctness or semantic source sufficiency**. Three unavailable/unanswerable outcomes on the evaluation side remain unknown rather than negatives; denominators for eligible evaluation questions are 13 and selection 10.

| Source-only arm | Selection covered / 10 | Held-out covered / 13 | Held-out delivered source bytes |
| --- | ---: | ---: | ---: |
| BM25 lexical k=2 | 1 | 4 | 4,681 |
| BM25 lexical k=4 | 2 | **8** | **8,636** |
| **BM25 lexical k=8 — selection-frozen winner** | **4** | **9** | 17,085 |
| Recency k=2 / k=4 / k=8 | 0 / 0 / 0 | 0 / 0 / 0 | 4,776 / 10,128 / 18,936 |
| Equal-weight RRF k=2 | 0 | 0 | 4,449 |
| Equal-weight RRF k=4 | 0 | 1 | 8,834 |
| Equal-weight RRF k=8 | 1 | **3** | 17,990 |

The original *selection-only* task-success proxy picks lexical k=8 again when the fusion arms are added. Its held-out 9/13 is one annotated support set above lexical k=4's 8/13, but requires **8,449 additional source bytes** (roughly 97.8% more). Both belong on the cost/coverage frontier; an arbitrary best-k selected by the held-out test would be leakage. Fixed RRF is **not** a stronger control in this particular corpus: RRF k=8 covers 3/13 versus lexical k=8's 9/13, despite more selected bytes. Do not extrapolate this to dense-hybrid or learned retrievers, and do not confuse source-ID coverage with sufficient context.

The selection-frozen lexical k=8 has missing-outcome bounds **9/16–12/16** across all planned held-out questions (56.25–75%), not an independent-source confidence interval. Per-family coverage is **4/7** and **5/6**. Only two published evaluation-family proxies are observed; family-level variance, genuine future windows, independent participant authenticity, human-certified sufficiency, semantic citation entailment, p95 reader cost, indexing/retention/recovery TCO and production qualification all remain unknown.

### Reproduce the exact staged experiment

`locomo_ninearm_source_replay.py` contains all six immutable ZIP outer SHA pins, bounded safe ZIP handling and inner-manifest checks, original source/population digests, reference 480-row reproduction, and independently computed 720-row journal and score. `test_locomo_ninearm_source_replay.py` runs ten tamper/leakage/cost/decision tests on the six original artifacts. The new read-only research GitHub Actions workflow stages originals and target ZIPs **in separate steps**, so evaluation labels are not present during retrieval or policy selection. Each stage runs as a distinct Python process with write-once output; the published JSON summary is byte-compared against the committed result. No model weights, model calls, learned policy or saved adapter are involved.

Exact ZIP IDs and outer SHA pins are declared in the source; original published decisions SHA-256 `0c80477394abadce7cfd192404ac2531c571e14a9dabdefb371633c1ae3aec89`. Independently recomputed 720-row journal SHA-256: `d3c09d944f5bfc855056d109fa0cc379a9a2dc11a3e628556af0448f8be82197`. All ten local regression tests passed, including rejection after forged policy/journal content and when evaluation targets are exposed to an earlier role. The result is an **offline replay from original published inputs**, not a completed hosted nine-arm run; the separate, newer original-hosted nine-arm run must be verified on its own source hash.

### Scientific disposition

**NO-GO for promoting fixed RRF, complex MemoryCell organization or a parameter head on this result alone.** The completed four-run 40+72 Qwen controlled-event study showed no incremental organizer task or complete citation-chain gain against simple full-path filtering. The current LoCoMo retrieval study exposes a useful *source-only* lexical k4-versus-k8 cost frontier. The genuine next experiment is a frozen **same-reader**, same-token-budget answer/citation comparison on the label-separated LoCoMo cohort, with independently assembled sufficient-evidence review and failure bounds; until then no production or parametric-memory acceptance is established.

## Post-policy UTF-8 source-byte frontier (no Reader claims)

A separate, stdlib-only `locomo_budget_frontier.py` audit reads the
**existing immutable aggregate** from the independent original-source
nine-arm replay. It verifies all nine 16-question selection and 16-question
evaluation denominators, both source-family-proxy subtotals, unknown or
unanswerable questions, per-arm delivered UTF-8 bytes and all-planned
support bounds before describing the held-out **post-hoc** budget frontier.

The original **selection-only** policy stays `lexical_k8`; no held-out score
is used to choose a new arm. The already preregistered `lexical_k4`
comparison carries **8/13** annotated held-out source-set coverage using
**8,636** selected source bytes. The selection-frozen `lexical_k8` covers
**9/13** and uses **17,085** bytes. The aggregate net difference is **one
extra source-set match for 8,449 extra selected bytes** over 16 planned
evaluation questions, with three outcomes remaining unknown/unanswerable.
These are **not** the final Reader input tokens, p95 latency, source-span
entailment or citation accuracy.

The descriptive, held-out-derived Pareto set includes one degenerate
zero-coverage smallest-byte control (fusion k=2); it must **not** be
interpreted as a recommendation. Neither that post-hoc set nor this
aggregate comparison constitutes an independent selection or a production
budget optimization. The next valid experiment must run the *same frozen
Reader* on both pre-existing lexical k4/k8 conditions with an identical
prompt/generation budget and an independently reviewed sufficient-evidence
control, preserving failure and citation denominators. Its absence is
explicit; `production_accepted=false`.
