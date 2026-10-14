# Fixed ModernBERT tokenizer-only preflight (research, nonauthorizing)

This is an additive research-only stage stacked on Draft #1995. It cannot authorize a model forward, select an Encoder or Cell Head, issue NDU, or permit release.

## Problem

The original 128 public AG News examples are represented as the **complete ordered Question + Options + State**. The real producer and independent reviewer run an exact `max_length=168`, `batch=8`, width-768 token profile, with no truncation. 64 rows × 168 token slots × 768 float32 dimensions = 8,257,536 features per Cell, below the 8,388,608 hard cap. If even one untruncated input is longer than 168 tokens, the model call must fail.

The previous research workflow downloaded the full ModernBERT model weights (approximately 599 MB) before detecting a length mismatch. The new stage fails first, before large weights are requested.

## Preflight execution

1. Validate the original public artifact ZIP SHA-256 and its historical publisher/model revision manifest.
2. Download **only** the immutable pinned `config.json`, `tokenizer.json`, `tokenizer_config.json`, and `special_tokens_map.json`; independently hash each against the historical publisher SHA-256. No `model.safetensors`, pickle, or remote code is requested.
3. Copy these four small files into a private, create-only local staging directory. Load the real *local fast tokenizer* without remote code.
4. Tokenize all 128 original joint strings with `truncation=False` and `padding=False`. Reject missing/malformed masks, incomplete rows, invalid token IDs, mismatched Scope/Cell identity, or any sequence longer than the frozen budget.
5. Keep only an ordered source/token-ID-stream digest, original source and tokenizer pins, aggregate token counts, and bounded padded-slot counters in a mode-0600 receipt. Raw text, raw token ID arrays, model weights, and full features are **not stored in this receipt**.
6. Only after the preflight succeeds, continue the original staged pretrained-weight acquisition, real Producer forward, independent second forward and safetensors/NumPy Head review.

The preflight runs with the same `TOKEN_CAPTURE_MAX_LENGTH` and `TOKEN_CAPTURE_BATCH` values as Producer and Reviewer. It preserves the no-truncation rule and all existing validations.

## Verification and limits

`python -m pytest -q -p no:cacheprovider tests/test_tokenizer_length_preflight_v1.py` executes 13 focused local checks, including no-weight acquisition, matching input source digests, full two-Cell roster, missing/forged tokenizer fields, overflow, unauthorized profile changes and publisher hash tampering. The full local research test set after this addition has **137 passed**. These test fixtures use an explicitly fake tokenizer. Therefore **the exact pretrained ModernBERT token lengths and physical model execution remain unverified until a hosted run completes**.

All research results retain `production_admission=BLOCKED`, `selection_authorized=false` and `pretrained_encoder_forward_verified=false`. Prospective no-change/NDU evaluation, signed source-use authorization, actual Worker/Q24, CAS/Final-use, generation fences, WAL/recovery and target-host 64–4096 Cell SLOs remain mandatory production blockers.
