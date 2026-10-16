# V7.5: Source-bound nine-candidate Torch → NumPy numerical closeout

**Status:** `DRAFT` / `SHADOW_ONLY` / `DENY_ALL` / `NO_MAIN_MERGE` / no Cell Split or NDU/model promotion.

**Base:** `TrillionniumFoundation/hepta-private-ci` PR #2383 V7.4, starting commit `a7ef707fc65daf11758b3f058f715467998b4e86`, which is descended from the original frozen V6 #2338. The experiment does not edit the frozen V6 checkpoint, existing V7.4 trainer, current model selector, production Neuron/Q24, Worker/CNS/CAS/FinalUse, NDU authority, or the main branch.

## Problem closed by this research implementation

The existing V7.4 independent review verifies all 9 candidate Torch-ZIP checkpoint *tensor values*, sampler/gradient work receipts, and original 128 binding TRAIN scores recomputed from recorded probabilities. But it does **not** prove that a candidate's recorded probabilities were *actually generated from its checkpoint and recorded Encoder features*. A malicious or erroneous producer could record a valid checkpoint and separately invent probabilities that score well.

V7.5 creates a **separately sealed, no-target feature → Torch-logit → independently executed NumPy-logit chain**, checks all 128 original binding TRAIN source identities, and independently compares the per-case rebuilt probabilities to the already-saved V7.4 old-task panel. Inputs are actual original TokenBank features **only when a source-pinned real Encoder/TokenBank is present**. Model weights, numeric input tensors, raw source text, or private test labels are never committed to Git. All nine arms must complete; a partial set is not a pass.

## Concrete files and execution

1. `bridge_candidate_v75.py`: write-once eight shared minibatch NPZ feature records, 16 original source cases each, each with **exactly six** bounded named FP32/Boolean arrays, model/tokenizer/preprocessing digests, original case IDs/group SHAs, per-array raw-byte SHA and per-batch archive SHA. No explicit labels/target tensors appear in the emitted files. Each candidate's separately executed frozen **PyTorch** Reader returns two-class logits and binds them to the model checkpoint SHA and feature archive SHA. All 3 seeds × 3 arms must produce 9 complete 8-batch prelabel manifests. Input features are shared physically across arms; repeated Predictor logits/NumPy verification are additional, separately charged work.
2. `bridge_candidate_v75_review.py`: executable separate-process reviewer. Uses the existing independently authored Torch-free NumPy V7.3 BridgeReader, strict CPU FP32 checkpoint decoder, bounded NPZ parser, presealed source/model/logit identities and original 128-row paired-world label evaluator. For each of nine actual candidates it verifies **8/8 batches**, recomputes 128 predictions, checks no argmax flips and absolute logits deviation ≤0.002; then requires its recomputed positive probabilities to match the **previously saved V7.4 candidate panel** within 0.001. The original old-task label scoring occurs *after* prelabel file verification. Accepting numeric consistency is explicitly **not** accepting scientific generalization.
3. `bridge_candidate_v75_cli.py`: production-ineligible research orchestrator. Before any output directory exists it verifies original immutable V4/V5/V6 archive ancestry and the exact 97M Granite material, then **all nine real V7.4 train-result receipts**. It obtains an exact historical TokenBank cache if genuinely provided and byte-identical or performs a **new measured pretrained Encoder encoding**; a silently substituted cache is forbidden. For all three original frozen V6 warmups, a separate NumPy forward on the *real* source features must reproduce all 128 historical TRAIN probabilities to within 0.001 with **zero** class flips before any new candidate prediction seals. It then seals the eight shared feature batches and each real newly trained V7.4 checkpoint's Torch logits. `completed.json` is written last and denies selection, split or effect authority.
4. `test_bridge_candidate_v75.py`: 14 adversarial tests including **authentic historical V6 frozen FP32 model checkpoint tensors** from the user-held original 20,928,479-byte evidence archive, original 128 source/case IDs, a distinct Torch math executor and an independent NumPy executor. Their input tokens are **explicitly synthetic**, not real Granite97 features. Tests reject missing nine model slots, forged/rehashed Torch logits, stale/swapped actual model checkpoint, target injection, changed group/case IDs, missing/extra batches, synthetic-token promotion, and a real CLI attempt when the 97M model is absent.
5. `run_v75_real_weight_synthetic_probe.py` / `V75_REAL_WEIGHTS_SYNTHETIC_INPUT_20261015.json`: an **actually executed** nine-slot mechanism result using 3 real historical *V6 warmup* checkpoints repeated across `joint/protect_old/protect_old_guarded` slots. **None is an actual newly trained V7.4 or V7.5 model**. Input tensors are seeded random synthetic FP32 samples with original source identities, so its scores against original task labels **are not semantic accuracy or retained skills**. Report only weight binding and Torch-vs-NumPy deviations.

The feature source builder consumes the original TRAIN source material, whose labels are inherently available to that builder. **We do not claim strong label-isolation of the process.** The generated NPZ/manifest/logit artifacts omit explicit targets; separate logit sealing precedes independent old-task scoring. These tests do not imply an independent model issuer or independently authenticated computational host. Synthetic fixtures remain visibly marked `synthetic_test_only` and the full actual nine-arm reviewer refuses that origin.

## Actual 2026-10-15 observations

- Three exact original V6 Bridge checkpoint SHA/22 named FP32 tensors/42,562 parameters each, independently decoded and run using a separate Torch reference.
- Eight shared feature batches × nine logical slots = **1,152 repeated synthetic case predictions** on 128 original identity records. Real new V7.4/V7.5 optimization steps: **zero**.
- Maximum across nine original-weight/synthetic-token Torch-versus-NumPy logit checks: **9.119510650634766e-06**. The numeric mechanism passes the preregistered 0.002 tolerance, including exact predicted-class agreement.
- Strict real CLI negative test with the original exact V4/V5/V6 archives and nonexistent Granite files fails **before creating an output directory**: `original public pretrained Granite97 material absent: deny V7.5`.
- Local standard test suite combines source, original archive, old/new gradient, replay and NumPy tests: run normal and under `python -O` on the exact source. Python compilation must pass. No test showing source authentication or model task quality may be substituted by this mechanism.

## Reproduce with original material when physically available

With **completed true original V7.4 nine-arm output** and verified Granite97 material, run the producer once from a private, new destination (no original model bytes committed):

```bash
python qualification/stem-cell-v1/bridge_candidate_v75_cli.py \
  --v4 /sealed/original/hepta_token_evidence_ndu_v4_20261015.zip \
  --v5 /sealed/original/hepta_binding_learning_v5_20261015.zip \
  --v6 /sealed/original/hepta_bridge_learning_v6_20261015.zip \
  --snapshot /sealed/original-granite97 \
  --run /sealed/true-portable-v74-nine-candidates \
  --output /sealed/new-v75-prelabel

# In a separate NumPy reviewer process; no Encoder needed here:
python qualification/stem-cell-v1/bridge_candidate_v75_review.py \
  --v4 /sealed/original/hepta_token_evidence_ndu_v4_20261015.zip \
  --v5 /sealed/original/hepta_binding_learning_v5_20261015.zip \
  --v6 /sealed/original/hepta_bridge_learning_v6_20261015.zip \
  --features /sealed/new-v75-prelabel/features \
  --v74-run /sealed/true-portable-v74-nine-candidates \
  --predictions /sealed/new-v75-prelabel/predictions \
  --report /sealed/new-v75-independent-numeric-review.json
```

A supplied `--cache /sealed/original-v5-tokenbank` requires **byte-identical original V5 cached metadata and tensor ZIP**. When absent, genuine reencoding is a *new* physical experimental run and its new Encoder work must be reported separately. This process does not use the old absolute paths as authority.

## Still BLOCKED and prohibited claims

The original Granite97 194,889,568-byte BF16 `model.safetensors` and original TokenBank data are **not present** in this authoring container. The public model endpoint was verified but container DNS/network and gated-download attempts could not retrieve the weight file. No nine-arm *new* pretrained V7.4 continued-training campaign was performed. No real encoded-source prediction or longitudinal future test occurred. The numerical receipt is not a proof of better learning, emergence, 10T/100T equivalent parameter capability, multimodal generation, System2/NDU policy value, or permission for model/Cell promotion. `main` remains unchanged; `DRAFT / SHADOW_ONLY / DENY_ALL` continues.
