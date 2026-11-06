# MemoryCell — independent offline reconstruction of the LoCoMo frozen source-only control

**Research-only, 2026-10-12. Generating source `fcc24ad653700ad5f47f09350cf7815242dc5de8`.** This is an independently scripted *local replay of an already published source-only artifact*. It is **not** the hosted `retrieve`/`select`/`evaluate` jobs succeeding, a pretrained model result, independent future observations, authenticated user data, or production admission.

## Fixed input boundaries

Source family proxy: LoCoMo's ten published conversations, original LoCoMo SHA-256 `79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4`. Exact GitHub Actions run [38206328621](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38206328621), original public-only artifact **11728164433**, selection-only targets **11728632417**, held-out evaluation targets **11728856834**. Its `publish` job completed successfully and verified the source bytes, split and independent target artifact partitions; the actual `retrieve` job remained queued at the time of this replay.

The public artifact is separately checked for its *exact* population SHA-256 `f53ee0986825f30ec4503b1698639e230832d1c05351c689cb55ebdc4f01d6de` and original histories SHA-256 `b42a90e01df2eb8d2da8a77e6218dc1124b7c19005f52d23ef8c1acd0aeed5cc`. It contains **5,882 original source turns**. There are **80 preselected questions** from **10 published source-family proxies**, split 48 train / 16 selection / 16 evaluation across 6/2/2 families. The original two-corpus admission gate remains closed.

The separate `locomo_frozen_offline_replay_20261012.py` implements the original six-arm BM25/recency retrieval contract as an external replay (not a new learned or stronger hybrid baseline): lexical and recency k={2,4,8}, identical tokenization, IDF, length normalization, stable ID tie-break and original observation-time parsing. It revalidates the population, every source census, root-group isolation and bytes, and recomputes the entire **480-row** journal before any scoring. A changed decision is rejected even if an attacker updates a receipt SHA.

Three actual subprocesses were executed in this order:

1. `retrieve PUBLIC_ZIP DECISION_DIRECTORY`: no private targets supplied or opened; fsync a 480-row canonical JSONL plus its SHA-256 receipt.
2. `select PUBLIC_ZIP DECISION_DIRECTORY SELECTION_TARGET_ZIP FROZEN_POLICY`: only the 16 selection-family labels are opened **after** the entire 480-row journal is saved and revalidated. Freeze policy by most fully covered eligible source IDs, then fewer original bytes, then arm name. The frozen winner is **lexical_k8**.
3. `evaluate PUBLIC_ZIP DECISION_DIRECTORY FROZEN_POLICY EVALUATION_TARGET_ZIP REPORT`: only now are 16 held-out evaluation-family targets opened, and *all* six arms are scored using the already-frozen decisions. Missing/unresolved/unanswerable annotations are explicit unknowns, not silently scored as failures or successes.

## Observed coverage and byte cost

| Fixed source-only arm | Selection support fully covered (10 eligible, 6 unknown) | Held-out support fully covered (13 eligible, 3 unknown) | Held-out original source bytes |
| --- | ---: | ---: | ---: |
| lexical k=2 | 1/10 | 4/13 | 4,681 |
| lexical k=4 | 2/10 | **8/13** | **8,636** |
| **lexical k=8 (frozen choice)** | **4/10** | **9/13** | **17,085** |
| recent k=2 | 0/10 | 0/13 | 4,776 |
| recent k=4 | 0/10 | 0/13 | 10,128 |
| recent k=8 | 0/10 | 0/13 | 18,936 |

The evaluation selection covers **4/7** eligible source annotations in one published family and **5/6** in the other. The missing-outcome descriptive bounds for the frozen choice are **9/16–12/16** across all planned queries (56.25%–75.00%); these are **not** statistical confidence intervals. Top-8 buys one additional covered source set relative to top-4, at **8,449 additional source bytes** (about 97.8% more). Both should remain on the retrieval cost/coverage frontier for a future *same-reader* study. These bytes are **not** tokenizer tokens or full deployed lifecycle cost.

## Machine-auditable receipt and limits

The accompanying receipt JSON records the original three artifact ZIP SHA-256 values, exact public/history/decision/policy/report digests, complete selection and held-out per-family metrics, and the explicit `model_answers_generated=0`, `external_independent_future_families=0`, and `production_accepted=false`. A separate ZIP contains the exact independently executable script, full decision journal, frozen policy, evaluation report and a complete SHA256SUMS manifest; **no original target labels are included**. Ten local audit assertions pass, including decision-tamper rejection and exact manifest census.

**Mandatory interpretation:** This is annotated *source-ID* coverage, not answer accuracy, citation entailment, necessary or sufficient context, trained-memory effect, independent human adjudication, statistical superiority, an authenticated future source family, or production qualification. Published LoCoMo histories can still be exposed in pretraining. The GitHub-hosted selection/evaluation run must be separately inspected; no green status or artifact is invented. The completed nine-arm Qwen authored-event experiment already showed **zero incremental correctness over full-path filtering**, so any future memory-learning claim must beat simpler, same-reader, cost-matched controls on fresh independently sourced tasks.