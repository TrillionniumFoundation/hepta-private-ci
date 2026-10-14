# Compact 384D Stem frontier: mmBERT-small vs Granite Embedding 97M R2

**SHADOW ONLY — DENY_ALL.** This is an additive E1/E2 research arm stacked
on the existing Neuron Stem qualification suite, not a new production
model registry, inference owner, signed NDU receipt or deployed shared Encoder.
Historical Jina/ModernBERT/mmBERT reports are not reinterpreted or overwritten.

## Why this separate arm exists

The older generic HF trial in this repository trained an additional
384→organ-width projection without including it in the "Head parameter" ceiling.
That experiment remains useful as an organ-projection study but does **not**
prove that a Cell used only 2K/8K/16K independently trainable parameters.

This compact comparison trains **only** the actual Cell Head; the Encoder is
fully frozen, there is no trainable shared or private projection, and the full
Head parameter count is checked against the ceiling before training.

| Model | Official repository | Frozen output | Readout | License |
| --- | --- | --- | --- | --- |
| mmBERT-small | jhu-clsp/mmBERT-small | 384D | attention-mask mean pooling, then L2 (research classifier readout) | MIT |
| Granite Embedding 97M Multilingual R2 | ibm-granite/granite-embedding-97m-multilingual-r2 | 384D | **CLS pooling**, then L2 (published embedding readout) | Apache-2.0 |

IBM's public Granite R2 model card explicitly specifies CLS pooling in its
Hugging Face Transformers usage example. Applying naïve mean pooling would
not evaluate its published representation. The mmBERT readout is a **research
choice**, not a claim that it was trained as a sentence embedding model.

These two families have different tokenizers and pretraining objectives:
identical original strings and a 512-token limit do **not** guarantee equal
tokenized sequence lengths or equal FLOPs. Truncation is rejected by default
and diagnostic truncation is reported as not cross-model comparable.

## Execution (only with reviewed local safetensors and approved data)

Both models must already be cached locally at their **separately verified**
immutable, lowercase 40-hex Git commit SHA. The runner uses
'local_files_only=True', 'trust_remote_code=False' and
'use_safetensors=True'. It will not fetch missing model files or load
PyTorch pickle checkpoints. Use an isolated, approved runtime with
'torch', 'transformers', 'psutil', and appropriate pinned dependencies.
Do not run code from an unreviewed model revision.

Given a JSONL with the existing qualification suite's 'train',
'calibration', 'test', 'future', 'ood' partitions and 'scope_id':

    export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
    python3 qualification/neuron-stem/compact_stem_trial.py \
      --model mmbert-small --revision VERIFIED_MMBERT_40_HEX_SHA \
      --dataset /approved/task.jsonl --task-id decision-v1 --scope-id cell-scope-1 \
      --head film --budget 2048 --shots 32 --steps 100 \
      --seed 20261014 --max-tokens 512 \
      --output /evidence/mmbert-compact.jsonl

    python3 qualification/neuron-stem/compact_stem_trial.py \
      --model granite-97m-multilingual-r2 --revision VERIFIED_GRANITE_40_HEX_SHA \
      --dataset /approved/task.jsonl --task-id decision-v1 --scope-id cell-scope-1 \
      --head film --budget 2048 --shots 32 --steps 100 \
      --seed 20261014 --max-tokens 512 \
      --output /evidence/granite-compact.jsonl

For each model, the outputs are:
- '.jsonl': **trained** Head predictions, measured research forward/Head time;
- '.jsonl.frozen-head.jsonl': **same-initialization frozen** Head ablation;
- '.jsonl.manifest.json': model ID/revision, scope, pooler, exact trainable
  Head parameters, training-case and minibatch-index digests, Q24 identity,
  truncated-case count, non-authenticated artifact warnings and DENY_ALL.

Each is create-only. Predictions are post-training for held-out partitions.
Training uses training labels only; calibration labels tune temperatures;
test/future/OOD labels are never used to update parameters. This is NOT
live prequential prediction-before-outcome or a prospective future study.

## Paired evidence gates

1. Use **byte-identical approved dataset**, chosen Scope, task, train source
   groups, seed, optimizer, Head architecture, complete trainable parameter
   budget, token cap and measurement host for both Encoder candidates.
2. Audit the same task case IDs and training minibatch-index digest.
   Record true model-specific token counts, truncation, parameter counts,
   process RSS, warm/cold timing, and the cost of all encoding; no shared
   backend-batch or production microbatch claim follows from per-row calls.
3. Obtain **independently produced no-change** predictions (not the frozen
   Head) and separately compare each trained arm to *both* no-change and the
   matched frozen Head using the existing independent statistical evaluator
   and adequate future source groups. Mere improvement over a random frozen
   Head does not qualify Cell learning.
4. Enforce language/task regression, OOD false acceptance, future utility
   and resource hard gates. A credible winner requires independent future
   outcomes and signed NDU plus real native inference/authorization receipts.
5. Keep production selection, model upgrade, CNS route, artifact CAS,
   generation fence, checkpoint mutation and Final-use exclusively with
   independent existing owner/gates. No research result carries that power.

The existing Q24 bridge rejects nonfinite/out-of-bounds values, applies
nearest-even rounding, and retains research-only feature digests. It is
**not** a signed 'NeuronFeatureReceiptV1'. Original hidden dimension 384
fits the <=512 Neuron V1 feature-width envelope but does not imply that a
production Worker implements this Encoder or these Head weights.

## Model-free CI / readiness

    PYTHONPATH=qualification/neuron-stem python3 -m unittest \
      discover -s qualification/neuron-stem -p 'test_compact_stem_trial.py' -v

Tests verify whitelist/pinned versions, scope/group isolation, pooling,
Q24 width, invalid features, and complete parameter budgeting. Tensor tests
skip if optional PyTorch is not installed on the lightweight CI runner.
The preexisting qualification workflow watches 'qualification/neuron-stem/**'
and discovers the added tests.

**Unverified:** external model weight and tokenizer bytes on the target host;
actual mmBERT vs Granite inference; comparable future task utility; source
family independence; signed NDU; production worker; 64/256/1024/4096
resource and failure-recovery receipts; exact-head CI. None is replaced by a
fixture, a digest-only declaration or the published retrieval leaderboard.
