# Hepta optimal shared Stem — original three-backbone qualification v1

**Research-only. DRAFT / SHADOW_ONLY / HOLD_NO_GO / DENY_ALL / NO MAIN / NO FINALUSE / NO CELL SPLIT.**

## What this adds (no production code changes)

A *physically executable* original-source comparative experiment rather than a new model leaderboard. The producer uses the exact original public PolyAI BANKING77 author revision `57ec275d8078af65b7731c2a98be812d844a6d6b` and train/test SHA256 from independent Hepta V4, with its 4-intent, 64-TRAIN / 32-HELDOUT subset. All candidate models get the same **96 original case identities**, the same **128-token limit**, controlled **masked-mean + L2** 384D output, and four separate rank-8 **6,914-scalar gated Cell Heads** (27,656 trained scalars total). Every model receives 100 full-batch Adam updates at identical seed/lr and train exposure. Frozen same-initialization Head and a supervised train-class-centroid cheap control are evaluated without HELD labels in the producer. Parameter count is matched across models, but model compute is *not* equal merely because Head steps match.

### Source-first custody and real execution

- `MODEL_MATERIALS.json`: full HF Git revisions for IBM Granite Small English R2 (47M), Granite Multilingual R2 (97M), JHU mmBERT Small (~140M), safetensors byte SHA-256, fixed float32/128-token preprocessing, and unresolved controls. mmBERT's safetensors digest is confirmed on the model file page at the pinned revision; the physical download is **still required to verify the actual complete bytes** before model load. Incorrect revision/digest fails, never silently picks `main` or pickle `.bin`.
- `stem_candidate_v1.py prepare`: independently checks raw publisher CSV SHA, deduplicates normalized text, source-hash sorts 16 TRAIN and 8 HELD cases per intent, shuffles output IDs without their class groups, and emits the complete frozen train/unlabelled heldout JSON. Original publisher labels are available in the source-owner preparer, but NOT exported for HELD. This is process/workflow isolation, not a cryptographic proof of label secrecy.
- `stem_candidate_v1.py infer`: downloads only SHA-pinned material, verifies the *actual* safetensors bytes, loads with `trust_remote_code=False`, executes real original CPU Encoder forward batches once per input, trains the four per-Cell Heads, seals all 32 HELD probability distributions and observed process cost (CPU/wall/RSS/forward counts, model load and feature-forward time separately) with explicit absent energy and p99. It does NOT perform 4,096 learned-Cell work, production batching, signed receipts or target-host power measurement.
- `stem_review_v1.py`: distinct stdlib-only implementation. It reobtains original publisher source/labels on a separate Actions runner **after** the complete prelabel model files and SHA sidecars exist, reconstructs the cohort independently, checks all 3×32×3 score distributions, source/weights/Head/cost identity and adversarial tampering, recomputes original 4-class accuracy/Brier and paired exact McNemar descriptives. **No candidate is promoted** even if historical scores are favorable.
- `.github/workflows/hepta-stem-optimal-original-v1.yml`: read-only, exact HEAD, source-tests first, followed by one source-owner, three separate actual original model runners, and an independent late-label scoring job; never runs untrusted fork model-host jobs. Original publisher plaintext and model weights are not committed and only sanitized reviewer aggregates are publicly uploadable beyond ephemeral Actions attachments.

### Scientific meaning and nonclaims

1. This experiment compares **controlled frozen mean-pooled representation quality** rather than each model's optimal official embedding API. Granite may perform better under its own sentence-transformer pooling; that needs an independently registered paired arm before proclaiming an optimal model. mmBERT's MLM pretraining is not equivalent to a sentence embedding objective.
2. Exact four-class original BANKING77 historical samples (and label-conditioned case sampling in a source-owner) are a **small single-source canary**, not future source/time-disjoint efficacy. n=32 nominal exact paired tests are descriptive, and multiple-model/arm selection demands multiplicity correction in a larger pre-registered study.
3. Three candidate Encoders do **not** replace original 421M baseline, production `no-change` behavior, ModernBERT-base, EmbeddingGemma2, multimodal necessity controls, true NDU/future task utility or loss of old-task skill. They are explicit unresolved slots, not presumed worse models. The centroid diagnostic is not a full prior production no-change measurement.
4. Same optimizer steps and scalar count is not equal lifecycle cost: all encoder preprocessing/forward, CPU/energy, cache effectiveness, training, retention, 64/256/1024/4096 fleets, concurrency, p95/p99 and WAL/crash recovery must be compared on the actual target host.
5. SHA checking binds material bytes but does not prove independent model issuer signatures, hardware attestation, independent human task judgement, authority to call tools, or signed FinalUse. The only allowed result is **HOLD_NO_GO / DENY_ALL**.

## Measured *in this authoring environment* (not the hosted original experiment)

The stdlib and adversarial suite plus a physically computed **synthetic-feature** PyTorch 4×6,914 gated-Head forward/backprop has been executed in a separate CPU environment: **17/17 ordinary** and **17/17 `python -O`** test methods passed. No real HF model weights/public original publisher text could be downloaded from that isolated local environment; no original comparative accuracy, total CPU/RSS/p99 or model winner is claimed from those local tests. Workflow exact-HEAD original physical jobs must complete before claims of new original pretrained evidence.

## Dependencies and order

1. Freeze/source owner → actual original two source file SHAs, candidate model Git revisions and safetensors bytes; failure stops.
2. Three independent original physical Encoders → source-first 384D Q24-compatibility **not asserted** (this experiment uses native float32), four fully allocated per-Cell Heads, 100 real optimizer steps, complete case output seals.
3. Separate reviewer reopens independent original labels only after all predictions/sidecar seals and verifies exact source roster, cost/weight fingerprints and paired metrics.
4. A subsequent qualified study must add fixed real Reader/no-change, time/source-disjoint windows, retention, per-source independent human correctness/NDU and truly matched 421M per-resident/replicated lifecycle; then target-host scaling and production signed CAS/CNS/FinalUse.

Reproduce local conformance:

```sh
cd qualification/stem-optimal-v1
python -m unittest -v test_stem_candidate_v1
python -O -m unittest -v test_stem_candidate_v1
python -m py_compile stem_candidate_v1.py stem_review_v1.py test_stem_candidate_v1.py
```

The original-model Action is intentionally allowed to **fail closed** on missing HF files, incompatible upstream loaders, incorrect mmBERT weight material, or CI resource budgets. Do not recast workflow creation or source-only green as an original physical pass.
