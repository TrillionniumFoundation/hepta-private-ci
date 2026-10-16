"""Fail-closed, model-tokenizer-based budget gate for original Gemma2 E3.

This does NOT independently attest model-internal vision tokenization or actual
Transformer forward counts. Instead charge the maximum documented single-image
soft-token budget (1120) for every admitted original image. Do not permit
model.encode() to truncate text silently; no fake images or remote URLs.
"""
from __future__ import annotations

from pathlib import Path

CONTEXT = 8192
MAX_IMAGE_SOFT_TOKENS = 1120
FORBIDDEN_MARKERS = ("<|image|>", "<|audio|>", "<|video|>")
PREFLIGHT_VERSION = "hepta.e3.gemma2-conservative-token-preflight.v1"


class NativeBudgetError(ValueError):
    pass


def check(condition, message):
    if not condition:
        raise NativeBudgetError(message)



def bind_verified_native_context(owner):
    """Bind the *actual* frozen, source-checked Gemma2 runtime to 8192.

    The original model's text_config.max_position_embeddings can be much
    larger (262144), and its SentenceTransformer .max_seq_length may be None.
    Neither is evidence of a reviewed joint text+image 8192 context.
    SentenceTransformer exposes a writable max_seq_length property backed by
    its first Transformer module. This explicitly configures the *runtime*
    inference limit, never changes original checkpoint tensors or tokenizer.
    """
    manifest = getattr(owner, "manifest", None)
    digest = getattr(owner, "profile_digest", None)
    check(getattr(owner, "_verified_local_weights", None) is True and
          type(manifest) is dict and
          manifest.get("model_id") == "google/embeddinggemma-2" and
          manifest.get("revision") == "914f7f89142e33e77833254d9c9b90c3cef7303b" and
          manifest.get("profile") == "vision" and
          manifest.get("dimension") == 256 and
          manifest.get("precision") == "float32" and
          type(digest) is str and len(digest) == 64 and
          all(c in "0123456789abcdef" for c in digest),
          "reviewed exact Gemma2 runtime and SHA-bound context required")
    model = getattr(owner, "model", None)
    check(model is not None and
          callable(getattr(model, "tokenizer", None)) and
          type(getattr(model, "prompts", None)) is dict,
          "real sentence transformer processor/tokenizer absent")
    try:
        first = model[0]
        old = model.max_seq_length
    except (KeyError, IndexError, TypeError, AttributeError) as error:
        raise NativeBudgetError("source model has no inspectable sequence setter") from error
    # SentenceTransformer can expose a conservative default such as 512 or
    # 2048 even for this exact publisher model with documented 8192 context.
    # The default is NOT accepted for inference: the verified owner must
    # explicitly set and re-read both runtime/module limits at 8192 below.
    # Refuse nonintegral, tiny and unsupported oversized original limits.
    check(old is None or
          (type(old) is int and 128 <= old <= 262144),
          "unreviewed original native context metadata; expected None or 128..262144")
    try:
        model.max_seq_length = CONTEXT
        actual = model.max_seq_length
        module_limit = getattr(first, "max_seq_length", None)
    except (TypeError, AttributeError, ValueError) as error:
        raise NativeBudgetError("native context setter unavailable") from error
    check(type(actual) is int and actual == CONTEXT and
          type(module_limit) is int and module_limit == CONTEXT,
          "native model did not accept bounded 8192 token context")
    return {
        "schema": "hepta.e3.gemma2-pinned-runtime-context.v1",
        "original_sentence_transformer_max_seq_length": old,
        "effective_sentence_transformer_max_seq_length": actual,
        "underlying_transformer_max_seq_length": module_limit,
        "actual_context_bound_from_exact_reviewed_model": True,
        "image_token_count_physically_verified": False,
        "model_origin_independently_signed": False,
        "production_accepted": False,
    }

def validate_text(text, *, tokenizer, prefix, ceiling):
    check(type(text) is str and bool(text), "empty or invalid text")
    check(not any(marker in text for marker in FORBIDDEN_MARKERS),
          "unsupported interleaved modality marker in external source")
    check(type(prefix) is str and not any(m in prefix for m in FORBIDDEN_MARKERS),
          "invalid default model prompt")
    encoded = tokenizer(prefix + text, truncation=False, add_special_tokens=True)
    check(hasattr(encoded, "get"), "uninspectable original tokenizer result")
    ids = encoded.get("input_ids")
    check(type(ids) is list and bool(ids) and all(type(x) is int and x >= 0 for x in ids),
          "no complete original tokenizer ids")
    check(len(ids) <= ceiling, "text or joint image input would silently truncate")
    return len(ids)


def check_batch(model, rows):
    """Inspect all text and one-image combinations before any native encode.

    Exact native processor image token count remains unverified. Documented
    maximum 1120 is conservatively charged; if default config is unexpected,
    reject it instead of silently accepting a narrower context.
    """
    check(type(rows) is list and 1 <= len(rows) <= 8, "unbounded embedding input batch")
    max_seq = getattr(model, "max_seq_length", None)
    check(type(max_seq) is int and 128 <= max_seq <= CONTEXT,
          "native SentenceTransformer context ceiling absent or unreviewed")
    tokenizer = getattr(model, "tokenizer", None)
    check(callable(tokenizer), "original tokenizer missing")
    prompts = getattr(model, "prompts", None)
    default = getattr(model, "default_prompt_name", None)
    check(type(prompts) is dict and
          (default is None or type(default) is str and default in prompts),
          "unreviewed default tokenizer prompt")
    prefix = "" if default is None else prompts[default]
    checked = 0
    max_charged = 0
    for row in rows:
        if type(row) is str:
            text, image = row, None
        else:
            check(type(row) is dict and set(row) in (
                {"image"}, {"text", "image"}), "unsupported multimodal input schema")
            text, image = row.get("text"), row["image"]
            check(type(image) is str and image and "://" not in image
                  and not image.startswith("//"), "remote or invalid image path")
            path = Path(image)
            check(path.is_absolute() and ".." not in path.parts and
                  path.is_file() and not path.is_symlink() and
                  not any(parent.is_symlink() for parent in path.parents),
                  "uninspected or symlink-traversed native image is forbidden")
        media_cost = MAX_IMAGE_SOFT_TOKENS if image is not None else 0
        check(media_cost < max_seq, "native context smaller than image envelope")
        observed = (validate_text(text, tokenizer=tokenizer, prefix=prefix,
                                  ceiling=max_seq - media_cost)
                    if text is not None else 0)
        max_charged = max(max_charged, observed + media_cost)
        checked += 1
    return {
        "schema": PREFLIGHT_VERSION,
        "rows": checked,
        "max_conservative_context_tokens": max_charged,
        "context_limit": max_seq,
        "charged_image_soft_tokens_per_image": MAX_IMAGE_SOFT_TOKENS,
        "image_tokens_physically_verified": False,
        "untruncated_text_tokenizer_invoked": True,
        "production_accepted": False,
    }
