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
