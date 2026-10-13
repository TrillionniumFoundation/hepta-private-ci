#!/usr/bin/env python3
"""Read-only, exact-byte mirror of the Rust shared Stem Worker binding V1.

The caller supplies raw identity and artifact digest CLAIMS, not signatures.
This module has no model-loading, Worker dispatch, policy selection, final-use
or production authority.
"""
import hashlib

from q24_bridge import MAX_ABS, MAX_FEATURES, Q24

DOMAIN_FEATURE = b"hepta.inference.stem-feature-vector.v1"
DOMAIN_REF = b"hepta.inference.stem-feature-ref.v1"
DOMAIN_WORKER = b"hepta.infer-worker.scoped-stem-input.v1"


def _stable_id(value):
    if (not isinstance(value, str) or not 1 <= len(value) <= 128
            or not value.isascii()
            or any(not (ch.isalnum() or ch in "._-:") for ch in value)):
        raise ValueError("Rust StableId V1 requires 1..128 ASCII bytes [a-zA-Z0-9._:-]")
    return value.encode("ascii")


def _u64(value, *, positive=False):
    if type(value) is not int or not int(bool(positive)) <= value < (1 << 64):
        raise ValueError("invalid Rust u64 protocol value")
    return value.to_bytes(8, "big")


def _digest(value):
    if (not isinstance(value, str) or len(value) != 64 or value == "0" * 64
            or any(x not in "0123456789abcdef" for x in value)):
        raise ValueError("nonzero canonical Digest32 hex required")
    return bytes.fromhex(value)


def feature_vector_digest_v1(q24):
    if not isinstance(q24, (list, tuple)) or not 1 <= len(q24) <= MAX_FEATURES:
        raise ValueError("feature vector exceeds bounded Neuron V1 envelope")
    raw = DOMAIN_FEATURE + len(q24).to_bytes(4, "big")
    for value in q24:
        if type(value) is not int or not -(MAX_ABS * Q24) <= value <= MAX_ABS * Q24:
            raise ValueError("invalid signed Q24 feature")
        raw += value.to_bytes(8, "big", signed=True)
    return hashlib.sha256(raw).hexdigest()


def stem_feature_ref_digest_v1(source):
    """Bind the *exact* Rust source ref fields, including Scope and Principal."""
    if not isinstance(source, dict):
        raise ValueError("expected explicit source ref")
    q24 = source["feature_vector_q24"]
    width = source["feature_width"]
    if type(width) is not int or width != len(q24):
        raise ValueError("feature width does not equal the actual signed Q24 bytes")
    feature_digest = feature_vector_digest_v1(q24)
    if source["feature_digest"] != feature_digest:
        raise ValueError("frozen feature digest does not match supplied Q24 bytes")

    raw = DOMAIN_REF
    for name in ("scope_id", "principal_id", "stem_model_id"):
        value = _stable_id(source[name])
        raw += len(value).to_bytes(4, "big") + value
    raw += _u64(source["stem_generation"], positive=True)
    raw += _u64(source["authority_epoch"], positive=True)
    raw += _u64(source["lease_expires_at_ms"])
    raw += width.to_bytes(4, "big")
    for name in (
        "stem_weights_digest", "tokenizer_digest", "preprocessor_digest",
        "projection_digest", "input_digest", "feature_digest",
    ):
        raw += _digest(source[name])
    return hashlib.sha256(raw).hexdigest()


def scoped_worker_input_digest_v1(source):
    """The value carried as WorkerRequest.input_digest on the Stem path.

    The digest protects against reusing an already-issued payload hash for
    another caller-declared Scope/Principal/lease. It NEVER authenticates
    who asserted the source or final-use grant.
    """
    ref_digest = stem_feature_ref_digest_v1(source)
    return hashlib.sha256(
        DOMAIN_WORKER + _digest(source["input_digest"]) + bytes.fromhex(ref_digest)
    ).hexdigest()


def qualification_only_receipt(source):
    """Produce no approval: copyable bytes remain untrusted evidence claims."""
    return {
        "schema": "hepta.shadow.stem-worker-binding-v1",
        "stem_feature_ref_digest": stem_feature_ref_digest_v1(source),
        "scoped_worker_input_digest": scoped_worker_input_digest_v1(source),
        "independent_final_use_verified": False,
        "loaded_stem_artifact_attested": False,
        "production_promotion_permitted": False,
    }
