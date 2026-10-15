"""Fail-closed, *pre-forward* text and composed-image token budget checks.

Research only. The model's original frozen tokenizer is required and called
with truncation=False for every literal text input. Joint-image token overhead
is conservatively reserved, NOT counted by the model's actual processor.
This does not authenticate the media encoder or grant a model capability.
"""
from __future__ import annotations
from collections.abc import Mapping

MAX_CONTEXT_TOKENS = 8192
# The registered default image consumes roughly 280 model tokens. Reserve
# 128 more for control/prompt/special-token overhead instead of falsely
# claiming that a text-only tokenizer inspected the actual media tokens.
IMAGE_TOKEN_RESERVE = 280
CONSERVATIVE_OVERHEAD = 128


class NativeBudgetError(ValueError):
    pass


def require(condition, reason):
    if not condition:
        raise NativeBudgetError(reason)


def no_truncation_count(tokenizer, text, prefix):
    require(type(text) is str and 0 < len(text.encode("utf-8")) <= 32768,
            "missing/oversized original text input")
    require(type(prefix) is str and len(prefix.encode("utf-8")) <= 4096,
            "unknown hidden task prompt")
    tokens = tokenizer(prefix + text, truncation=False, add_special_tokens=True)
    require(isinstance(tokens, Mapping), "uninspectable pinned tokenizer output")
    ids = tokens.get("input_ids")
    require(type(ids) is list and len(ids) > 0 and
            all(type(token) is int and token >= 0 for token in ids),
            "original tokenizer did not expose complete flat token ids")
    return len(ids)


def original_native_input_preflight(model, plain, joint, image, choices):
    """Check exactly the prompt/image pairs physically sent to .encode().

    The underlying model/processor's actual image-patch/token count is NOT
    measured by this function; quota is a conservative default admission rule.
    """
    tokenizer = getattr(model, "tokenizer", None)
    prompts = getattr(model, "prompts", None)
    default_name = getattr(model, "default_prompt_name", None)
    require(callable(tokenizer) and isinstance(prompts, dict),
            "actual verified model tokenizer/prompts unavailable")
    require(default_name is None or (type(default_name) is str and default_name in prompts),
            "unknown implicit model prompt")
    prefix = prompts[default_name] if default_name is not None else ""
    require(type(plain) is list and 0 < len(plain) <= 256 and
            type(joint) is list and type(image) is list and type(choices) is list and
            len(plain) == len(joint) == len(image) and
            len(choices) == 4 * len(plain),
            "different source/candidate cardinalities")

    peak_plain = 0
    peak_joint_text = 0
    peak_choices = 0
    for txt, composed, image_only in zip(plain, joint, image):
        require(type(composed) is dict and set(composed) == {"text", "image"} and
                type(image_only) is dict and set(image_only) == {"image"} and
                type(composed["image"]) is str and
                composed["image"] == image_only["image"] and
                composed["text"] == txt and len(composed["image"]) <= 4096,
                "joint source image/text changed before encode")
        c = no_truncation_count(tokenizer, txt, prefix)
        require(c + CONSERVATIVE_OVERHEAD <= MAX_CONTEXT_TOKENS,
                "original plain text may silently truncate")
        peak_plain = max(peak_plain, c)
        # A tokenizer sees text only. Reserve non-text tokens plus additional
        # prompt/special-token headroom. Do not claim image token attestation.
        require(c + IMAGE_TOKEN_RESERVE + CONSERVATIVE_OVERHEAD <= MAX_CONTEXT_TOKENS,
                "joint text/image may silently truncate")
        peak_joint_text = max(peak_joint_text, c)
    for txt in choices:
        c = no_truncation_count(tokenizer, txt, prefix)
        require(c + CONSERVATIVE_OVERHEAD <= MAX_CONTEXT_TOKENS,
                "choice text may silently truncate")
        peak_choices = max(peak_choices, c)
    return {
        "registered_context_tokens": MAX_CONTEXT_TOKENS,
        "reserved_default_image_tokens": IMAGE_TOKEN_RESERVE,
        "reserved_misc_tokens": CONSERVATIVE_OVERHEAD,
        "maximum_plain_text_tokens": peak_plain,
        "maximum_joint_pre_media_tokens": peak_joint_text,
        "maximum_choice_tokens": peak_choices,
        "complete_text_tokenizer_truncation_disabled": True,
        "actual_model_image_token_count_attested": False,
        "original_model_internal_forward_count_attested": False,
        "production_accepted": False,
        "authority": "DENY_ALL",
    }
