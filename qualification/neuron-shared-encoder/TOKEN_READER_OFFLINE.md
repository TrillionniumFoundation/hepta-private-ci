# Pinned real-token E2 probe (shadow only)

This continuation to [Token Reader V1](TOKEN_READER_V1.md) makes actual local
pretrained model-forward calls and passes **the exact same frozen token tensor**
to pooled and token-query Heads. It is not a production encoder, inference
worker, model selection, NDU, authority or trusted performance receipt.

The supported controls are `mmbert-joint`, `granite-joint` and
`modernbert-joint` using the existing `OfflineEncoder` with pinned
`model.safetensors`/tokenizer/full-bundle SHA256. Laya's special option marker
encoding is deliberately **not** emulated here. Compare actual Laya teacher
and different Encoder families in their existing E1 qualification trials.

## Reproduction (only when operator-approved assets already exist locally)

From `qualification/neuron-shared-encoder`:

```sh
python -m neuron_shared_encoder.token_reader_offline \
  --kind modernbert-joint \
  --checkpoint-dir /approved/read-only/modernbert \
  --weights-sha256 "$WEIGHTS_SHA256" \
  --bundle-sha256 "$BUNDLE_SHA256" \
  --tokenizer-sha256 "$TOKENIZER_SHA256" \
  --dataset /approved/private/data.jsonl \
  --dataset-sha256 "$DATASET_SHA256" \
  --purpose local-frozen-token-e2 \
  --generation 1 --authority-epoch 1 \
  --max-length 64 --encoder-batch 8 \
  --rank 8 --head-budget 16384 \
  --steps 20 --head-batch 16 --seeds 11 23 47 \
  --output /approved/private/new-token-e2-evidence.json
```

These environment variables are placeholders: **no hashes or model weights are
supplied by this repository**. There is no model download, synthetic fallback,
`trust_remote_code` or pickle feature serialization. Missing assets, mismatched
SHA256, oversize inputs, non-finite hidden states and truncated context fail
closed. The non-Laya input is an unambiguous ordered canonical JSON string of
question/options/state; this is a new declared preprocessor and should **not**
be compared as an identical tokenizer/input format to historic E1 runs.

The study prevalidates a single principal/purpose/organ/Cell, source-disjoint
chronological train/validation/future/OOD windows and per-row option-index
labels **before loading the checkpoint**. It observes PyTorch module-forward
attempts, completed batches and rows; it measures tokenizer, model-forward and
Head fit+evaluation wall time separately. A single pooled feature cache floor
and actual shared token-snapshot bytes are reported, but cached pooled-head
service execution, CPU/GPU kernels, per-request p99, optimizer peak RSS,
physical cross-Cell sharing and energy are **not** measured.

All returned model-evidence fields remain self-attested. Dataset and checkpoint
endpoint rehashes are not trusted signatures or proof of exact bytes consumed
mid-run. The code does **not** receive/use external approvals, independent
future-time outcomes or selected no-change artifacts. The result always states
`production_admission=BLOCKED` and `selection_authorized=false`.

Run synthetic interface/adversarial regressions (no real Encoder weights):

```sh
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  python -m pytest -q tests/test_token_reader_offline.py tests/test_token_reader_v1.py
python -m compileall -q neuron_shared_encoder/token_reader_offline.py \
  tests/test_token_reader_offline.py
```

**Next real gate:** provision approved pinned local weights and a genuine
source-group-disjoint dataset, execute this command with full independent input
provenance and inspect the frozen E1/teacher baseline and per-task negative
transfer. No numerical scientific win is claimed by the synthetic tests.
