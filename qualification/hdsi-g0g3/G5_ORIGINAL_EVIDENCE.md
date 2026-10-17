# HDSI G5 — Real LoCoMo evidence learning under frozen shared MiniLM

**Research-only / DRAFT / SHADOW_ONLY / HOLD_NO_GO / DENY_ALL / NO MAIN MERGE / NO MODEL PROMOTION / NO CELL SPLIT / NO FINALUSE.**

This is a **stacked research child** of G0–G3 PR #2617 (baseline `3fa5cd504e4829c1c045ef29b9e44d64e028d334`). It adds files under `qualification/hdsi-g0g3/g5*`, three sanitized local original-evidence JSONs, and one dedicated read-only Actions workflow. The original G0–G3 branch and its queued genuine Granite97 job remain unchanged. No native Rust Neuron/NDU, Model Worker, CNS, CAS, signed effect use, source-ledger, selected Stem, reviewer/CI rule or protected main files are touched.

## Frozen original material and scientific question

**Question:** Does 6,144-scalar, 100-update, rank-8 Cell parameter learning with a single shared frozen six-layer original MiniLM improve source-root-held original human **evidence retrieval**, compared with frozen cosine, BM25, wrong-label controls and zero-feature lesions?

- Source: historical publicly published LoCoMo original data from archived GitHub Actions `11586991191`, archive SHA256 `07b357cbb3362f4afa4dc1872ab7e28e8a46daaf338f2636fed8d40fbcee76af`.
- Original publisher JSON SHA256: `79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4`.
- Original six-layer 384D MiniLM safetensors SHA256: `53aa51172d142c89d9012cce15ae4d6cc0ca6895895114379cacb4fab128d9db`.
- Tokenizer/vocab/config are independently hash-verified before loading. The batched FP32 calculation is an explicit local original BERT reference, **not issuer-attested Hugging Face tokenizer/operator parity**; the separate scalar vs batched numerical test uses genuine weight tensors.
- Frozen original TRAIN roots: `conv-26, conv-30, conv-41, conv-42, conv-43, conv-44`; HELD roots: `conv-47, conv-48, conv-49, conv-50`. These are historically public groups, **not prospective, independent publisher families, or calendar-future cohorts**.
- Within each root, choose 256 utterances by SHA ordering **without consulting QA labels** and 24 authentic publisher questions by independent question SHA ordering; 144 TRAIN / 96 HELD questions, entire source roots separated. The 256-doc cap is a registered resource scenario, not a theoretically optimal retrieval index. Its evidence-coverage ceiling is a primary measured outcome.

`g5_original_evidence.py prepare` creates a sealed packet with original TRAIN-only human supporting `dia_id`s; the HELD packet carries only question text/ID/hash with **no answer or evidence keys**. `g5_batched_encoder.py` accepts only the four SHA-pinned Encoder material files; a separate model Worker process refuses the original raw `locomo.json` and `reader` directory. Our current full physical replay actually used this label-free, no-raw-answers model-only directory. The independent scorer reopens the pinned raw original dataset only **after** 96 complete rankings are sealed, reconstructs all source/question selections without importing the producer, and rejects forged cost/model/identity fields and rank omissions.

## Measured original local physical execution (2026-10-17)

- **2,799** genuine completed six-layer Encoder sequence forwards, **180** physical batched 16-input model calls, **75,726** token positions, and **2,800** logical feature borrows; one exact within-root input was reused under scoped current-use checks. These are counted sequences, not 2,799 independent model loads or 2,799 model *batches*.
- Each arm reuses the same frozen real 384D feature tensors. Two separate actual FP32 low-rank `384×8`/`384×8` Heads, **6,144 independent scalars each**, receive **100 genuine AdamW optimization steps each** (one original TRAIN-evidence supervision, one frozen-seed/same-budget wrong supervision). TRAIN questions with any available publisher evidence in the fixed candidate bank: **55/144**. Both Head parameter digests change from the identical initial SHA.
- Fresh rerun with raw original QA labels **absent** from the model input directory yields **identical 96-question ranking matrices and both final Head weight digests** as the archived-material baseline. The original real source is still read by the separate offline `prepare` authority; a model worker does not receive or consult HELD answers.
- Whole-process local CPU/wall **35.14 / 35.13 seconds**, report-local peak RSS about **445 MB**, nested Head fitting ≈ **2.05 seconds**. These are **unauthenticated authoring-host observations** with no target-host p95/p99/energy, NPU/GPU benefit or complete end-to-end production serving TCO; `None` remains unknown rather than zero.
- Normal and Python `-O` tests: **21 methods per mode, all successful** when original weight/material path is supplied. Without model files, 20/21 source/adversarial tests PASS per mode, and the one genuine full-model numerical test explicitly skips. A separate actual-original six-layer batch-to-scalar test passed with nonzero-length real LoCoMo inputs and floating tolerance `1e-5`.

## Independent original-publisher annotated evidence score

The independent standard-library scorer reopened publisher `qa[].evidence`, recomputed each selected question/source by identity, revalidated the complete held sorted rank set for **all six arms** (every 256 candidate IDs, no duplicates), and counted strict source `dia_id` match. It does **not** score generated answer correctness or citation entailment.

| Fixed 256 utterance candidates per root | Any original evidence Hit@5 / 96 | All supports Hit@5 / 96 |
| --- | ---: | ---: |
| BM25, no training | **9** | 4 |
| Frozen MiniLM cosine, no training | **12** | 7 |
| Real original-data trained rank-8 Head | **2** | 2 |
| Same-budget wrong-target rank-8 Head | **1** | 1 |
| Original trained Head, other-question feature | **2** | 2 |
| Original trained Head, all-zero features | **0** | 0 |

Only **31/96** held questions have at least one original human evidence `dia_id` in the frozen 256-document bank, and only **16/96** have all supports inside. These are hard information-availability ceilings; unavailable source evidence is **not silently dropped from the denominator**. Rank-8 vs frozen cosine at Hit@5: **1 rescue / 11 harms / 84 ties**. There are only four correlated source roots, so nominal per-question paired statistics are descriptive. The true HEAD train loss nearly reaches zero on supervised TRAIN features; this does not compensate for the original held outcome.

## Matched-budget caveat and strong cheap full-corpus ablation

After the above P0 panel was independently scored, a separately costed, zero-model-forward **full original publisher transcript BM25** diagnostic checked all **2,447** existing dialogue utterances across the same four HELD roots (including beyond the neural 256-document bank). Same 96 SHA-selected genuine questions; 58,728 actual BM25 document-question comparisons; **48/96** any-support Hit@5, **36/96** all-support Hit@5; 96/96 have at least one original support within the *full* source population. Standalone un-attested local scoring wall ≈ **0.11 seconds**, excluding corpus setup, data read, indexing for serving and whole-service overhead. No data-derived document choice or answer/label is used by the lexical ranking policy.

**Do not misrepresent the 48/96 as an equal-candidate-budget neural comparison:** it uses an expanded input document universe, and 0.11 sec is only retrospective in-memory CPU scoring. It is useful as a distinct coverage ablation: expanding cheap candidate *recall* dominates investing in this failing 6,144-weight Head; optimize real evidence inclusion first, then verify semantic ranking with the same fixed candidate universe, followed by genuinely correct source-verified answer generation.

## Reproduction / GitHub exact-head gate

Three committed sanitized original-local outputs:

- `G5_LOCAL_SOURCE_AND_COST_20261017.json`: model/label-free source plan digests, actual completed model forwards, Head weight hashes, measured scopes and truthful negative claims.
- `G5_LOCAL_ORIGINAL_REVIEW_20261017.json`: separate original publisher human evidence reviewer aggregates; **no raw human questions, evidence strings, model weights or individual query rankings committed**.
- `G5_LOCAL_FULL_CORPUS_BM25_20261017.json`: separate source-first full-publisher cheap coverage comparison.

Commands (requiring a **locally byte-verified** archived source/model bundle):

```bash
cd qualification/hdsi-g0g3
python -m unittest -q test_g5_original_evidence
python -O -m unittest -q test_g5_original_evidence
python g5_original_evidence.py prepare --locomo /original/locomo.json --output /private/public.json
# Only four validated Encoder files in /model-only/encoder; no raw locomo.json.
python g5_original_evidence.py infer --root /model-only --source /private/public.json --output /private/prelabel.json
python g5_independent_review.py --original /original/locomo.json --source /private/public.json --run /private/prelabel.json --output /private/late-review.json
python g5_full_corpus_cheap.py --original /original/locomo.json --output /private/cheap-review.json
```

The separate read-only `.github/workflows/hepta-hdsi-g5-original.yml` runs source/adversarial tests against exact source HEAD, then on a **same-repository branch push only** reacquires the historical artifact by strict outer ZIP SHA, stages only source-owned model files + label-free input, executes actual original 6-layer neural forwards and exact HEAD training on a distinct runner, seals prelabel outputs, and independently re-downloads and rechecks source/gold before postseal review on a third runner. Cross-run original bytes, a missing expired historical artifact, incompatible original-model tokenizer, or an untrusted redirect **fail closed**. Existing protected global `blocking-ci`, Architecture, selected artifacts and independent release boundaries are never waived; workflow submission or PR source-only green cannot stand in for an actual successful physical job.

## Decision

**HOLD_NO_GO / DENY_ALL** on Cell Head specialization and automatic Cell Split. No natural answer correctness, NDU-specific improvement over ordinary Bellman, System 2 reasoning emergence, multimodal generation, cross-host exact operator parity, 421M equal-cost alternative, future task generalization, safe effect execution or production model promotion has been established.

Next scientific priority **for an independently reviewed follow-up** is a matched-source full-corpus BM25 vs cosine retrieval panel (then a genuinely trainable question-conditioned token/evidence Reader), rather than spending more trainable Heads on source-inaccessible examples. Preserve all negative arms and old-task retention gates before considering NDU-guided extra reasoning computation or topology proposals.
