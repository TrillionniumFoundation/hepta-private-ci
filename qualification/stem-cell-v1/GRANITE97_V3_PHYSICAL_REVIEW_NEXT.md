# Granite97 → FeatureSequence V3: independent physical replay

Status: **RESEARCH ONLY / SHADOW_ONLY / DENY_ALL / NO MODEL PROMOTION**.

This staged child of [producer PR #2388](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2388) and [native V3 import PR #2389](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2389) adds a separately implemented physical reviewer. It does **not** redefine V1/V2/V3 ABI, replace the native Worker, or issue a capability. Source-only unit tests **do not run** Granite97.

## Physically necessary prerequisites

1. Obtain the five real model files only from `ibm-granite/granite-embedding-97m-multilingual-r2` at immutable upstream SHA `835ad14087e140460703cf0fae09f97d469d65c2`: `config.json`, `model.safetensors`, `tokenizer.json`, `tokenizer_config.json`, `special_tokens_map.json`. Create a compatible local `material.json` with per-file sizes and SHA256, and independently lock the domain-separated `material_digest`. Do not derive the expected model lock from the export that is being reviewed.
2. A separate source/permission owner admits the **complete** UTF8 input bytes and locks its SHA256. It includes the question and all ordered options; no future answers, hidden truth or labels enter model input.
3. Execute Python with exact Transformers `4.57.1`, PyTorch CPU and safetensors, record package/device identity. Set `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1`. No external model or input fetch is performed by these scripts.
4. Freeze principal, purpose, generation, authority epoch, token ceiling (at most 256), source bytes and short TTL *before* producer/reviewer execution. Reviewer reads the actual wall clock and rejects backdated caller clocks.

## One source, physically executed twice

With an independent source lock, model-material lock and approved physical host:

```bash
set -euo pipefail
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
NOW_MS=$(python3 -c 'import time; print(time.time_ns() // 1000000)')
EXPIRES_MS=$((NOW_MS + 180000))
python3 qualification/stem-cell-v1/granite97_v3_export.py \
  --model-root "$MODEL_ROOT" --source "$SOURCE_FILE" \
  --source-sha256 "$SOURCE_SHA" \
  --expected-material-sha256 "$MODEL_MATERIAL_SHA" \
  --principal-id 'research:principal-a' --purpose-id 'stem-reasoning' \
  --generation 7 --authority-epoch 2 --max-tokens 192 \
  --expires-at-ms "$EXPIRES_MS" --output "$WORK/producer-create-only.json"

python3 qualification/stem-cell-v1/granite97_v3_independent_review.py \
  --model-root "$MODEL_ROOT" --source "$SOURCE_FILE" \
  --source-sha256 "$SOURCE_SHA" \
  --expected-material-sha256 "$MODEL_MATERIAL_SHA" \
  --principal-id 'research:principal-a' --purpose-id 'stem-reasoning' \
  --generation 7 --authority-epoch 2 --max-tokens 192 \
  --now-ms "$(python3 -c 'import time; print(time.time_ns() // 1000000)')" \
  --maximum-expiry-ms "$EXPIRES_MS" \
  --export "$WORK/producer-create-only.json" \
  --output "$WORK/independent-review-create-only.json"
```

`$WORK` must be new/private. Both processes use exclusive-create for receipts, never overwrite an existing one. The reviewer independently verifies five material hashes, every original safetensors tensor, tokenizer IDs and mask, exact source identity, preprocessing/quantization/adapter profiles, all 384-D Q24 token values, and a second **real frozen CPU forward**. It records independently observed work and the original export-file hash, separately from producer-claimed timing.

The outer material digest is SHA256 over bytes `hepta.stem.granite97.material.v5\x00` followed by each sorted filename as `u32_be(name_length) + name + u64_be(actual_size) + raw_sha256(file)`. Do not confuse it with `model.safetensors` SHA256 or upstream Git revision.

## Source-only tests and next true gate

```bash
python3 -m unittest discover -s qualification/stem-cell-v1 \
  -p 'test_granite97_v3_independent_review.py' -v
python3 -O -m unittest discover -s qualification/stem-cell-v1 \
  -p 'test_granite97_v3_independent_review.py' -v
```

These test the Python/Rust SHA256 golden, source/identity/expiry/metadata/mask/shape guards, duplicate JSON, numeric bounds, material tamper/symlinks and runtime/tokenizer profile drift. They do **not** load model weights. Physical execution requires an independently approved source and pinned model snapshot.

Once actual physical two-process receipts exist, execute the original Rust V3 importer + multi-Cell Reader on the create-only exported token bytes. Count all work (including independent review forward, tokenizer, setup, RSS, CPU/wall and restoration), compare original source scoped reuse at 64/256/1024/4096 Cells, and score prospective source-disjoint natural tasks against cheap BM25, pooled and replicated-model controls at equal lifecycle budgets.

Matching two actual forwards is still **not** cryptographic execution attestation, signed source ownership, independently verified human quality, a successful learning campaign, model selection, or permission to deploy. The original Rust V3 importer stays `AuthorityPosture::DENY_ALL`. No main merge, auto-split, state mutation or external effects may be inferred.
