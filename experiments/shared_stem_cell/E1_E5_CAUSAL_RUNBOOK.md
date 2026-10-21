# Hepta E1–E5 causal Stem/Cell experiment spine — SHADOW ONLY

**Authority:** `DENY_ALL`. Stacked on the multimodal research contract branch, not on `main`. No selected Stem, production inference path, Q24 journal, Head/CAS/FinalUse owner, NDU Selector or `blocking-ci` requirement changes.

## Why this exists

The existing repo already has separate, more mature studies. Reuse them rather than invent a second Laya/Granite/Gemma or Whisper model loader:

- #1897: Granite 97M R2/`mmBERT-small` exact-revision local-safetensors strict 384D Head-only frontier. Granite uses **CLS + L2**, mmBERT uses **masked-mean + L2** as a declared research readout, **not** its official sentence-embedding API.
- #1775: actual local pretrained EmbeddingGemma 2 CPU text forwards, official MRL `truncate_dim=256`, multimodal and frozen Laya experimental contracts. Its old incomplete public val2 cases, changed historical Head weights and unfinished exact-HEAD CI cannot be silently reinterpreted as an accepted paired result.
- #1885: `multimodal_alignment.py` train-only frozen paired-feature bridge, source-disjoint future predictions, independent geometric scorer, non-authorizing fan-out and 9,744-parameter baseline Head.
- #1838: frozen Whisper audio experiment; #1794: physical host/trace inventory and read-only fault gates; #1697: evidence-vs-Reader crossed-rank control.

This new *additive* suite creates a single matched **three-Encoder E1/E2, E3/E4 media, E5 resource, Reader capability** evaluation contract with visible missing-gate results. It is not a claim that previously separate PRs have merged, that any physical pretrained snapshot is installed here, or that E1–E5 have passed.

## Experiment matrix

| Stage | Exact research arm | Separation / blocker |
| --- | --- | --- |
| E1 | Granite 97M, mmBERT-small, EmbeddingGemma 2 **text 256D** over identical canonical state/question/two choices/evidence | Same original input identity and independent language/source/time groups; no-change and frozen Head, model-specific token counts/weights, whole-lifecycle cost **externally required** |
| E2 | trainable anchored residual (zero initial update), from-zero Head, frozen same-init, direct question/evidence cosine; Head ceilings 2048/8192/16384 including *all* parameters | Real PyTorch/AdamW CPU updates, frozen input and initial Head digests, sealed predictions before held-out truth; no hidden trainable projection or held-out seed search |
| E3 | Real DINOv2+bridge vs EmbeddingGemma 2 native image, OCR-only, unaligned (from established modality producers) | E3 evaluation only accepts all declared arms for every image case, distinct source group and external truth; no pixel/vision competence claimed on geometry fixtures |
| E4 | Real Whisper/bridge vs transcript-only/unaligned/native audio; video temporal, order-blind and frame-reversal controls | True opposing-label forward/reverse pair identities and distinct time/site groups required; reversing file names alone is not reasoning |
| E5 | Head-only CPU physically executed at 64/256/1024/4096 cells, plus **separate mandatory** native target-worker 4-profile evidence | The Head probe **loads no Encoder**, performs no trained policy, signs no receipts, reports no GPU/power/network/WAL or full p99. Native full-journey outcomes remain missing until independent owner verification |
| Reader isolation | none / ordinary retrieval / independently reviewed sufficient evidence / premise removed | Exactly same Reader identity/budget and complete case coverage; if sufficient evidence still fails, no retrieval/Stem causal-credit claim |

The study's **binary classification** schema is deliberately narrower than general Neuron inference. Multi-choice, spatial grounding, generative Reader quality, fine-grained audio/video causality and SYSTEM2/FBSDE are distinct future registrations and must never be inferred from this study.

## Physical E1 input producer (only with approved weights)

`e1_e5_text_producer.py` accepts an operator-pinned, create-only manifest with three complete local safetensors snapshots: `ibm-granite/granite-embedding-97m-multilingual-r2`, `jhu-clsp/mmBERT-small`, `google/embeddinggemma-2` (text-only). It verifies **all three** file inventories and immutable 40-character upstream revisions before any Encoder runs, disables online fetch and remote code, refuses silent token truncation, and requires license approval. It uses the repo's stock-HF `execution.LocalEncoder` complete tensor verification for Granite/mmBERT; Gemma is loaded through the official pinned SentenceTransformer interface with the **Classification, SearchQuery, Document** prompts and native 256D MRL. An API call is never mislabeled as the unknown count of internal physical Gemma transformer forwards.

The label-free `requests.json` has one row per `case_id`:

```json
{"case_id":"c1","scope":"scope-A","state":"state text","question":"Does the patch fix the fault?","options":["no","yes"],"evidence":"original evidence text","input_sha256":"SHA256 of execution.canonical([\"hepta.stem.e1-e5.typed-input.v1\", scope, state, question, options, evidence])"}
```

All model vectors are read from **full state+question+ordered choices+evidence** joint input. Query/evidence vectors are separately encoded for the cosine control. The `input_sha256` is computed from the exact canonical byte representation, not the JSON representation shown in the example. No labels, gold answers or future feedback are passed into the physical producer. `features.json` and three per-model weight/runtime receipts are create-only; the operator must bind their exact digests into the Head plan. A self-supplied SHA, even after re-hashing, is **not independent model-origin attestation**.

```
PYTHONPATH=experiments/shared_stem_cell python3 experiments/shared_stem_cell/e1_e5_text_producer.py \
  --manifest /approved/e1/producer-plan.json --manifest-sha256 REAL_PLAN_SHA256 \
  --output-dir /sealed/e1/features
```

The producer manifest requires `schema=hepta.stem-e1-e5.text-producer.v1`, SHA-pinned `requests: {path,sha256}`, and `models` with keys `granite97`, `mmbert_small`, `embeddinggemma2_text`. Each model entry requires `{source,snapshot,revision,files,weights_sha256,maximum_tokens,license_approved}`. Weight inventories must include *every* file under each local model directory. `weights_sha256` is an externally attested complete bundle identity and must not be confused with per-file SHA256. Do not use unreviewed downloaded model source code, pickle or dynamic `trust_remote_code`.

## E1/E2 training and independently opened future truth

All four physical input documents are *separately* SHA-bound by `plan.json`: `cases.json`, `features.json`, `train_labels.json`, `nochange.json`. The plan schema is `hepta.stem-e1-e5.trial.v1` with complete three-model `models` identities, `head_budgets=[2048,8192,16384]`, `steps`, `seed` and the four file references. Case identity requires `case_id,group_id,split,observed_at,cell_id,scope,generation,language,modality,input_sha256,state` with exactly 64 bounded state floats. Splits: `train,calibration,test,future1,future2,future3,ood`; all seven are mandatory, train/source groups are disjoint from evaluation, and real future times must be chronological. Languages are `en,zh,code`. **Only TRAIN labels** exist in the runner's input; even calibration truth is inaccessible during this trial. The no-change probabilities must come from an independent existing baseline producer on identical cases.

```
PYTHONPATH=experiments/shared_stem_cell python3 experiments/shared_stem_cell/e1_e5_trial.py \
  --plan /approved/e1/plan.json --plan-sha256 REAL_PLAN_SHA256 \
  --output /sealed/e1/predictions.json
```

The E1/E2 training plan is capped at **64 Cell identities / 2,048 cases**; E5 is a separately bounded scale replay and does not imply 4,096 learned Heads. This trains all **three models × three parameter ceilings × two Head initialization variants × active Cell keys**, reuses frozen feature tensors, measures update CPU/wall and parameter snapshots, and seals `nochange`, `frozen`, `learned` and `train-only-threshold cosine` predictions for every non-training case. All Cell gradients stop at the feature input. The zero-initialized anchored residual preserves no-change at the first step exactly. A from-zero Head is a separately labeled control. `feature_forward_in_this_runner=0` means the Encoder ran in an external earlier phase, **not** that encoding is free.

Only after this file's exact digest is frozen, release the separately owned `targets.json` (all nontrain cases; case/input/label/outcome owner reference). The **separate evaluator source** does not import the trainer. It hard-rejects omitted/relabelled arms, changed original inputs, mismatched baseline, duplicate fields, NaN, future-label leakage and altered sealed predictions. It computes accuracy, two-class normalized Brier, ECE, source-group Bonferroni-corrected paired future accuracy bounds, and language slices. These are diagnostic rather than authenticated independent NDU.

```
PYTHONPATH=experiments/shared_stem_cell python3 experiments/shared_stem_cell/e1_e5_review.py \
  --plan /approved/e1/plan.json --plan-sha256 REAL_PLAN_SHA256 \
  --predictions /sealed/e1/predictions.json --predictions-sha256 SEALED_PRED_SHA256 \
  --targets /approved/external/targets.json --targets-sha256 EXTERNAL_TRUTH_SHA256 \
  --reader /sealed/reader-four-arm.json --reader-sha256 READER_SHA256 \
  --media /sealed/media-all-arms.json --media-sha256 MEDIA_SHA256 \
  --video-pairs /sealed/video-opposites.json --video-pairs-sha256 PAIRS_SHA256 \
  --resources /sealed/native-target-host.json --resources-sha256 RESOURCE_SHA256 \
  --output /sealed/e1/independent-review.json
```

Reader/media/native arguments are optional **only to produce an explicit MISSING diagnostic**; absence never becomes a green gate. Four Reader arms must keep exactly one Reader identity and token budget and all held-out/future/OOD case identities. E3 image arms: `ocr_only,unaligned,bridge,gemma_native`; E4 audio: `transcript_only,unaligned,bridge,gemma_native`; video: `order_blind,temporal,reversed`. These are externally measured **predictions**, not outputs invented by the scorer. The optional video-pairs file requires truly opposite-label independent forward/reverse cases within one split. Real media formats/consent/decoder/temporal budget must be independently verified by the specialized producers (#1885/#1775/#1838).

## E5 physically executed **Head-only** preliminary scale

```
for n in 64 256 1024 4096; do
  PYTHONPATH=experiments/shared_stem_cell python3 experiments/shared_stem_cell/e1_e5_head_scale.py \
    --plan /approved/e1/plan.json --plan-sha256 REAL_PLAN_SHA256 \
    --cells "$n" --active-fraction 0.1 --reuse 0.5 --head-budget 2048 \
    --output "/sealed/e5/head-only-$n.json"
done
```

This really runs CPU Torch forwards with independent untrained Cell Heads using already materialized features. It records actual requests, unique cached input keys, wall/CPU and head latency, and the runtime environment. It **does not** run 4096 independently trained learners, execute the frozen Encoder, measure backend microbatch/queue, authenticate a worker, exercise durable crash/reopen, or provide target-host GPU/power receipts. These are explicitly separate mandatory native E5 gates. Every profile declares `production_promotion_permitted=false`.

## Required independent decision/effect authority

Before any Stem/Cell promotion, existing owner services must separately establish exact-source `blocking-ci`, independently verified upstream model and data origin, genuinely matched real Laya/no-change comparisons, trained-vs-frozen *future* utility, Source/Scope/Generation fences, 64–4096 *native physical* target-host profiles (queue, p95/p99, RSS, CPU, GPU, power, throughput, crash/reopen), Q24 Worker/Neuron Tick and checkpoint/witness, Reader sufficiency, safety/OOD retention, and genuinely independent signed NDU/Future1–3 outcomes. The `e1_e5_review.py` output is always `DENY_ALL` and reports unauthenticated claims as such. **No no-change, teacher, shared Stem or media result may be made up or relabeled from another model/commit.**

## Verification actually available at authoring

Local Python 3.13 / Torch 2.10 CPU: 24 distinct synthetic/adversarial contract tests passed; the four E5 scale sizes executed only small Head-only fixture probes. There are **zero new real Granite/mmBERT/Gemma weights installed in that local run**, zero genuine multimodal holdout scores, zero Reader independent reviews, zero native 4096 target worker evidence and zero signed NDU outcome. This is not model selection or true E1–E5 experiment completion. Exact-current-HEAD GitHub Actions, full `blocking-ci` and independent origin checks must be inspected **after** the new commit and may be queued, failing or incomplete; historical success cannot be inherited.
