# V13 — Source-first ordinary lexical controls before additional Cell training

**Status: RESEARCH / DRAFT / SHADOW_ONLY / DENY_ALL. No model selection, original Reader gain, main merge or FinalUse.**

## Question

V9 original 6,914-scalar MiniLM Head routes underperformed original full-source BM25, and V11's 31-scalar residual produced 380–382/829 historical weak Hit@3, matching an equally effective fixed Top-2-preserving low-cost control. V12 found only four learned-Head-vs-cheap-control evidence membership changes and zero original publisher witness hits in their actual Reader-dispatched routes. Before funding additional Head adaptation, does a completely **untrained** lexical alternative recover additional original publisher-supported passages under the same final three-evidence-slot budget?

## Executed original experiment

SHA-bound original LoCoMo `locomo.json` (`79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4`). Ten conversation source roots, **5,882** source turns and **1,986** complete original questions. Six TRAIN roots have 1,157 questions; four historically held roots have **829** questions, seven lacking a usable single-source publisher reference. These four roots are **not** new calendar windows or 829 independent statistical units.

Three distinct source stages: `prepare` strips original answers/evidence and emits a create-only source-only corpus and the entire frozen retrieval-arm configuration; `rank` accepts only source-only files (no corpus/gold argument), executes all six registered retrieval arms over the *complete* family source universe and seals complete 1,986-question Top-32 ID routes; `score` checks the original corpus digest, opens publisher weak evidence labels **only after rank completion** and creates postseal aggregate counts. Source-only rankings and original question/answer bodies are private and excluded from commits. A separately implemented reviewer independently recounts all 1,986 route entries and 829 original held cases, reconstructs the original **BM25 Top-3** from source text and checks the original family-level **76 / 124 / 91 / 81** Hit@3 benchmark without importing the producer scoring implementation.

The frozen, **preselected** candidate is `phrase_char`: **0.7** normalized BM25 + **0.1** weighted consecutive query-term phrase coverage + **0.2** within-word Unicode NFKC character-trigram TF-IDF cosine. The original BM25 retrieval uses the same `k1=1.2`, `b=0.75`, lexical tokenizer, source rendering and ID tie-break as the frozen V9 baseline. Other arms are BM25, word phrase, query-term coverage, BM25+char and char-only; their observed held outcomes are **diagnostic** and cannot replace the preselected candidate.

## Physical and independent observations

| Retrieval arm | TRAIN publisher weak any Hit@3 / 1,157 | Historical HELD weak any Hit@3 / 829 | HELD any Hit@16 | HELD any Hit@32 |
|---|---:|---:|---:|---:|
| Original complete-source BM25 | 506 | 372 | 515 | 575 |
| BM25 + phrase | 507 | 371 | 515 | 578 |
| BM25 + query coverage | 515 | 374 | 516 | 579 |
| BM25 + character similarity | 526 | 377 | 527 | 587 |
| **Preselected** BM25 + phrase + character | **542** | **383** | **528** | **587** |
| Character-only diagnostic | 532 | 384 | 569 | 631 |

The selected candidate is **+11/829** publisher-weak Hit@3 over BM25 on a historical held cohort. Per **independent** root: `conv-47 +3`, `conv-48 -1`, `conv-49 +2`, `conv-50 +7`. This is **not** uniformly non-regressing and is not a causal natural-language Reader benefit. Char-only is **384/829** but was not the primary; choosing it after seeing held results is prohibited.

Source-only physical CPU process observations on **the same 1,986 public questions** with independently identical BM25 Top-32 SHA for every run:

| Profile | Two separate CPU-second observations | Peak process RSS KiB (two runs) |
|---|---|---|
| Optimized **BM25 only** | 1.977; 1.924 | 132,704; 132,740 |
| Full **six-arm research census** | 13.032; 13.470 | 139,028; 139,044 |

The full six-arm process consumed about **6.79×** the BM25-only CPU time under these specific CPU runs. **This is not** a measurement of the cost of an optimized deployment of only the primary arm, nor a full equal-lifecycle training/inference/caching comparison against V11's learned Head. Two repeats do not establish a p95 or hardware-independent speedup. No pretrained Encoder/Reader or optimizer executed in V13.

## Verification and scientific decision

- Original label-owner source, ranked route, model/version and output digests are explicitly recorded. The independent reviewer confirms all 1,986 original question identities, no duplicate/foreign passages, every fixed arm, four nonindependent root denominators, original BM25 372/829 and all gains/losses. Independent reviewer observation: `COUNTS_CONSISTENT_NOT_MODEL_SUPERIORITY`.
- **47/47** Python standard-library adversarial tests pass in normal and `python -O` modes. They exercise gold/answer smuggling, duplicate question/source IDs, fake model calls or promotions, wrong source/material SHA, missing evidence, altered family totals, source-only no-go and exact BM25 route parity. The remote CI uses these source-only tests and a pinned negative public receipt; it **does not rerun** original LoCoMo ranking or human Reader assessment.
- Prior failing preliminary run with Python tuple/list noncanonical frozen plan and the TRAIN+HELD unknown-count confusion were preserved as failed attempts; neither was counted as completed physical model work. The repaired final code and original sealed rank both use the same frozen source/plan identity.
- **Conclusion: HOLD/NO-GO.** There is a positive retrospective *weak evidence retrieval proxy* for the preselected lexical blend, but only four correlated old source families, one root regression, no original Reader semantic correctness or citation entailment, no new future windows, and no fair full-cost Head-vs-cheap comparison. This does not qualify training another Cell, selecting a Stem, claiming System2, or enabling production. The V6 seed41 cross-fact retention blocker remains open.

Next scientific experiment: independently scored complete original Reader answers on fresh, source-disjoint questions selected **before** external truth and a matched total-cost comparison between a tuned cheap lexical floor and actual trained Head; preserve token budgets, source scope and per-root uncertainty. Only if that clears, allocate new Encoder gradients, Meta Network or NDU/FBSDE experiments.

## Private original-source reproduction

Restore the independently SHA-verified original `locomo.json` under your own private input directory and keep original media/dialogue and publisher answers outside public repository artifacts. Use distinct commands/processes, not a combined in-memory script:

```sh
export PYTHONPATH=qualification/stem-cell-v1
python qualification/stem-cell-v1/stem_v13_cheap_retrieval.py prepare \
  --original PRIVATE/locomo.json --source PRIVATE/source-only.json --plan PRIVATE/plan.json
python qualification/stem-cell-v1/stem_v13_cheap_retrieval.py rank \
  --source PRIVATE/source-only.json --plan PRIVATE/plan.json --output PRIVATE/routes.json
python qualification/stem-cell-v1/stem_v13_cheap_retrieval.py score \
  --original PRIVATE/locomo.json --source PRIVATE/source-only.json \
  --plan PRIVATE/plan.json --rank PRIVATE/routes.json --output PRIVATE/report.json
python qualification/stem-cell-v1/v13_independent_reviewer.py \
  --original PRIVATE/locomo.json --source PRIVATE/source-only.json \
  --plan PRIVATE/plan.json --routes PRIVATE/routes.json \
  --report PRIVATE/report.json --output PRIVATE/review.json
python qualification/stem-cell-v1/v13_public_gate.py \
  --report PRIVATE/report.json --review PRIVATE/review.json
```

The scripts exclusively create outputs, refusing to overwrite previous results. Do not upload the `PRIVATE` directory (raw dialogue, sources, question text and/or publisher labels), unredacted routes, or any original model weights. The public result and independent digest-only review were extracted only after completion.
