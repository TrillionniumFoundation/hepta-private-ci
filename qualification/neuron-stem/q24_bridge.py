"""Research-only checked float -> signed Q24 feature encoding.

Mirrors the Neuron feature-width/range envelope, not the Rust owner's signed
receipt or exact canonical runtime tick serialization. No clipping, hidden
dimension loss, or implicit authority.
"""
import hashlib
import math

Q24 = 1 << 24
MAX_FEATURES = 512
MAX_ABS = 8


def quantize_q24(features):
    if not isinstance(features, (list, tuple)) or not 1 <= len(features) <= MAX_FEATURES:
        raise ValueError("feature dimensions outside Neuron V1 input envelope")
    result = []
    for value in features:
        if type(value) not in (int, float) or not math.isfinite(value) or abs(value) > MAX_ABS:
            raise ValueError("out-of-range/non-finite feature (never silently clip)")
        fixed = round(value * Q24)  # Python round: nearest, ties-to-even
        if not -MAX_ABS * Q24 <= fixed <= MAX_ABS * Q24:
            raise ValueError("Q24 out of envelope")
        result.append(int(fixed))
    return result


def shadow_feature_bytes(q24):
    if not isinstance(q24, (list, tuple)) or not 1 <= len(q24) <= MAX_FEATURES:
        raise ValueError("wrong feature width")
    raw = b"hepta.shadow.neuron-feature-q24.v1"
    raw += len(q24).to_bytes(4, "big")
    for item in q24:
        if type(item) is not int or not -MAX_ABS * Q24 <= item <= MAX_ABS * Q24:
            raise ValueError("invalid signed Q24 item")
        raw += item.to_bytes(8, "big", signed=True)
    return raw


def rust_stem_feature_vector_digest_v1(features):
    """Exact cross-language digest of Rust StemFeatureRefV1's Q24 vector.

    This is only a content-binding digest, NOT a Rust or NDU signature.
    """
    q24 = quantize_q24(features)
    raw = b"hepta.inference.stem-feature-vector.v1"
    raw += len(q24).to_bytes(4, "big")
    for value in q24:
        raw += value.to_bytes(8, "big", signed=True)
    return hashlib.sha256(raw).hexdigest()


def rust_stem_encoder_pipeline_digest_v1(
    model_id, generation, feature_width, stem_weights_sha256,
    tokenizer_sha256, preprocessor_sha256, projection_sha256,
):
    """Cross-language model+tokenizer+preprocessor+projection+dimension identity.

    Inputs are model-artifact digest *claims*; the product owner still has to
    verify each actual artifact and its current authority/generation.
    """
    # Match the exact Rust codex_hepta_types::StableId V1 grammar.
    # Reject identifiers which Python could hash but Rust cannot construct.
    if (not isinstance(model_id, str) or not 1 <= len(model_id) <= 128
            or not model_id.isascii()
            or any(not (ch.isascii() and (ch.isalnum() or ch in "._-:"))
                   for ch in model_id)):
        raise ValueError("model ID must satisfy Rust StableId V1 (ASCII, <=128 bytes)")
    encoded_id = model_id.encode("ascii")
    if type(generation) is not int or not 1 <= generation <= (1 << 64) - 1:
        raise ValueError("generation must fit positive Rust u64")
    if type(feature_width) is not int or not 1 <= feature_width <= MAX_FEATURES:
        raise ValueError("invalid Stem feature width")
    raw = b"hepta.inference.stem-encoder-pipeline.v1"
    raw += len(encoded_id).to_bytes(4, "big") + encoded_id
    raw += generation.to_bytes(8, "big")
    raw += feature_width.to_bytes(4, "big")
    for candidate in (stem_weights_sha256, tokenizer_sha256,
                      preprocessor_sha256, projection_sha256):
        if (not isinstance(candidate, str) or len(candidate) != 64
                or any(ch not in "0123456789abcdef" for ch in candidate)
                or candidate == "0" * 64):
            raise ValueError("nonzero canonical 64-character artifact digest required")
        raw += bytes.fromhex(candidate)
    return hashlib.sha256(raw).hexdigest()


def shadow_feature_digest(features):
    q24 = quantize_q24(features)
    return {
        "feature_width": len(q24),
        "feature_vector_q24": q24,
        "research_only_feature_sha256": hashlib.sha256(shadow_feature_bytes(q24)).hexdigest(),
        "rust_stem_feature_vector_digest_v1": rust_stem_feature_vector_digest_v1(features),
        "rust_owner_authenticated": False,
        "production_receipt_verified": False,
        "authority": "DENY_ALL",
    }
