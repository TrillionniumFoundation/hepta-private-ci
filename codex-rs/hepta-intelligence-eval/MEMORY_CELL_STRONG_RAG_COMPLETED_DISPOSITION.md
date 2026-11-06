# Completed 40 + 72 Qwen strong-RAG experiment: research disposition

**Status:** Actual original Qwen2.5-3B research reader inference completed; separate read-only GitHub Actions replay succeeded. This is **not** a new prospective/independent source population, an independent human semantic-entailment judgment, a trained parametric-memory improvement, or production acceptance. The eight test scenarios and eight calibration scenarios are previously exposed **authored development tasks**.

## Exact completed evidence and non-substitutable pins

- Successful GitHub Actions **run [38224780900](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38224780900)**, attempt 2, generated from **`6304b451268c73f3d1a605985226b102df841bbf`**. Completed on **2026-10-12**; `experiment-format`, `reader`, and separate `independent-replay` all concluded `success`.
- Actual 40 calibration and 72 test records, **artifact `11743043427`** (`memory-strong-rag-calibrated-reader`); complete ZIP SHA-256 **`7a99db30fb5b1202fcd43073d22589b84315046dd34044277cc46351f1cbece8`**, 43 authenticated ZIP members plus `SHA256SUMS`.
- Independent read-only replay, **artifact `11748040166`**; complete ZIP SHA-256 **`2445895a7d51e3173837471aa462cebede29eb3ec89653af3bd17e73b6114071`**, eight authenticated ZIP members plus `SHA256SUMS`.
- Additional checkpoint, artifact `11742491576`, is **not** used as a replacement for the completed original model-answer archive. Another model artifact for the same Actions run (`11738668038`) is smaller and must **not** be silently substituted for the completed artifact above.
- Original archived eight-question plan SHA-256 **`9840a25487af444914dca24c818d98ff798ebc1610ea8dfdd827187c31ad1897`**. Same licensed, frozen BF16/eager Qwen reader throughout; no optimizer or memory-weight training.

The paired scorer used actual completed generation text and the pinned original event JSON. The separate replay verified original source/text, citation queue, bounded procedure reexecution, model/run identity, frozen k, all attempts and paired effects. The replay is independent **execution of a verifier**, *not* independent human source adjudication or statistical independence.

## What the real model actually achieved

All entries are actual generated results on the **same 8 previously exposed development questions**.

| Frozen reader condition | Strict correct | Correct + full public cited event path | Complete input prompt tokens |
| --- | ---: | ---: | ---: |
| Calibrated `k=1` | 5/8 | 3/8 | 3,961 |
| Fixed Hybrid `k=4` | 3/8 | 1/8 | 10,806 |
| Hybrid `k=6` | 2/8 | 0/8 | 15,463 |
| Hybrid `k=4`, evidence order reversed | 3/8 | 1/8 | 10,806 |
| **Single-hop** | **4/8** | **4/8** | 4,575 |
| **Entity/time, complete path** | **8/8** | **4/8** | 5,752 |
| **Organized with explicit correction pruning** | **8/8** | **4/8** | 5,179 |
| Program-declared support set (diagnostic only) | 8/8 | 4/8 | 5,179 |
| Empty evidence | 0/8 | 0/8 | 1,630 |

**Paired effects with the same frozen reader:** complete-path vs single-hop: **4 wins, 0 losses, 4 ties**; organized vs complete-path: **0 wins, 0 losses, 8 ties**; calibrated k=1 vs fixed k=4: **2 wins, 0 losses, 6 ties**. These are descriptive fixed-question counts, *not* significance intervals. `organized` saves **573 prompt tokens** over complete-path retrieval across all eight questions (roughly 9.96% of that reader-only input), but yields **zero additional strict task successes**.

## Top-k calibration instability and citation limitations

The separate 8-question *calibration* correctly selected `k=1`: k=1, 2, 3 and 4 each answered **4/8**, so the registered cost tie-break favored k=1. However, leave-one-calibration-question-out reruns from the actual saved answers select **k=1 in seven folds and k=2 in one**, with one held-out comparison **losing** to k=4. This is *not* stable evidence that k=1 generalizes as a global policy. Its held-out-authored final test performance was 5/8, whereas entity/time and organized were 8/8.

The **8/8 task accuracy is not 8/8 citation-chain fidelity**: in both entity/time and organized arms, only **4/8 answers** cite all program-declared sources forming the full public query path. On these public controlled cases, all four composition/procedure successes can omit a necessary-to-demonstrate *first-hop citation*, even when the final identifier is correct. Formal event-path connectivity is **not** an independent semantic-entailment precision certificate. No ≥99% semantic precision or production qualification is established.

The original archived same-prompt consistency check found **39 paired identical prompts** and zero disagreements; this does not create new source families or experimental independence.

## Fail-closed, reproducible research disposition

[`strong_rag_promotion_receipt.py`](../../scripts/memory_cell/strong_rag_promotion_receipt.py) checks the complete outer ZIP SHA-256 and inner SHA256SUMS of **both** final artifacts, the generating commit, exact original scored/raw answer census, frozen k, leave-one-out folds, prompt token usage, citation chain counts and independent read-only replay. It emits a pinned machine-readable [`observed-strong-rag-disposition-38224780900.json`](../../scripts/memory_cell/data/observed-strong-rag-disposition-38224780900.json).

```bash
PYTHONPATH=scripts/memory_cell python3 scripts/memory_cell/strong_rag_promotion_receipt.py \
  ACTUAL_COMPLETED_READER_ARTIFACT.zip INDEPENDENT_REPLAY_ARTIFACT.zip \
  --out NEW_RESEARCH_DISPOSITION.json
python3 -m unittest discover -s scripts/memory_cell -p 'test_strong_rag_promotion_receipt.py' -v
```

The machine-readable disposition **does not authorize training, adoption, source signing or a production switch**. Flags remain `parametric_memory_training_qualified=false`, `graph_task_accuracy_superiority_on_this_development_set=false`, `calibrated_k_stable_under_loo=false`, `human_certified_citation_semantics=false`, `production_accepted=false`.

**Next experimental priority:** on genuinely new independent source families, freeze the same reader and a source-validated read policy, compare tuned strong RAG against the simpler full-path filter and the complete organizer, and measure complete cited chains, abstention, revocation and total lifecycle cost. Do not treat another rerun of these eight public authored questions as a new generalization sample. Qwen's research-use license and deployment ownership boundaries remain in force.
