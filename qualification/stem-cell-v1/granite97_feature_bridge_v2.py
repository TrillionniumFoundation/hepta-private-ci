"""Strict research-only Granite97 V9 physical export -> multimodal V1 Cell bridge.

No provider call, model forward, trained Head, source signature or authorization.
The input must be a previously produced SHA-pinned Granite97 token export AND an
independent physically replayed review. The bridge independently checks the
complete token IDs/mask, original source, Q24 bytes and exact reviewer receipt.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import time

from multimodal_stem_v1 import AdmissionError, FeatureEnvelope, admit_features

MODEL = "ibm-granite/granite-embedding-97m-multilingual-r2"
REVISION = "835ad14087e140460703cf0fae09f97d469d65c2"
MATERIAL = "9d39552804582ee18cd61992e012510feae4cddb492b3b74808f6f46f494b0d8"
EXPORT_SCHEMA = "hepta.stem.granite97-token-export.v5"
REVIEW_SCHEMA = "hepta.stem.granite97-independent-physical-review.v1"
Q24 = 1 << 24
INPUT_DOMAIN = b"hepta.stem.granite97.complete-token-input.v5\0"
ENCODER_DOMAIN = b"hepta.stem.granite97.frozen-model.v5\0"
ADAPTER = hashlib.sha256(b"hepta.granite97.rational8-adapter.v6\0").hexdigest()
REVIEW_FIELDS = frozenset("""schema source_sha256 input_digest export_sha256 material_sha256 encoder_digest feature_q24_sha256 producer_claimed_forwards producer_claimed_cpu_ns producer_claimed_wall_ns reviewer_encoder_forwards reviewer_encoder_cpu_ns reviewer_encoder_wall_ns exact_tensors model_replayed selected_model production_authorized authority""".split())
EXPORT_FIELDS = frozenset("""schema model_id revision material_digest encoder_digest tokenizer_digest normalizer_digest quantization_digest preprocessing_digest adapter_digest source_sha256 input_digest principal_id purpose_id generation authority_epoch input_ids attention_mask values_q24 width expires_at_ms encoder_forwards encoder_cpu_ns encoder_wall_ns""".split())

class BridgeError(ValueError):
    pass

def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def digest(value: object) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None or value == "0" * 64:
        raise BridgeError("invalid SHA256")
    return value

def bounded_int(value: object, low: int, high: int) -> int:
    if type(value) is not int or not low <= value <= high:
        raise BridgeError("invalid bounded integer")
    return value

def identifier(value: object) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9_.:-]{1,256}", value) is None:
        raise BridgeError("invalid identifier")
    return value

def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise BridgeError("duplicate JSON property")
        result[key] = value
    return result

def read_regular(path: str | Path, bound: int) -> bytes:
    path = Path(path)
    if path.is_symlink():
        raise BridgeError("symlink is not a source")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    fd = os.open(path, flags)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or not 0 < before.st_size <= bound:
            raise BridgeError("unsafe or oversized input")
        with os.fdopen(os.dup(fd), "rb") as f:
            data = f.read(bound + 1)
        after = os.fstat(fd)
        if len(data) != before.st_size or len(data) > bound or (before.st_ino,before.st_dev,before.st_size,before.st_mtime_ns) != (after.st_ino,after.st_dev,after.st_size,after.st_mtime_ns):
            raise BridgeError("input changed during bounded read")
        return data
    finally:
        os.close(fd)

def parse_json(raw: bytes) -> dict:
    obj = json.loads(raw, object_pairs_hook=_pairs,
                     parse_constant=lambda _: (_ for _ in ()).throw(BridgeError("nonfinite JSON")))
    if not isinstance(obj, dict):
        raise BridgeError("record must be an object")
    return obj

def complete_input_sha(source: bytes, ids: list[int], mask: list[int]) -> str:
    payload = bytearray(INPUT_DOMAIN)
    payload.extend(len(source).to_bytes(8, "big"))
    payload.extend(source)
    payload.extend(len(ids).to_bytes(4, "big"))
    for token in ids:
        payload.extend(token.to_bytes(4, "big"))
    payload.extend(bytes(mask))
    return sha(bytes(payload))

@dataclass(frozen=True)
class BridgeOutcome:
    envelope: FeatureEnvelope
    q24_blob: bytes
    replay: dict


def bridge(source: bytes, export_bytes: bytes, review_bytes: bytes, *, now_ms: int) -> BridgeOutcome:
    """Independent byte/contract review. Review's *physical* origin is external."""
    if not 1 <= len(source) <= 65536 or not 1 <= len(export_bytes) <= 2_500_000 or not 1 <= len(review_bytes) <= 65536:
        raise BridgeError("source/receipt limits")
    bounded_int(now_ms, 1, 2**64 - 1)
    exp, rev = parse_json(export_bytes), parse_json(review_bytes)
    if set(exp) != EXPORT_FIELDS:
        raise BridgeError("invalid export fields")
    if (exp["schema"], exp["model_id"], exp["revision"]) != (EXPORT_SCHEMA, MODEL, REVISION):
        raise BridgeError("incorrect pretrained identity")
    if digest(exp["material_digest"]) != MATERIAL or digest(exp["encoder_digest"]) != sha(ENCODER_DOMAIN + bytes.fromhex(MATERIAL)):
        raise BridgeError("model material not independently pinned")
    for name in ("tokenizer_digest", "normalizer_digest", "quantization_digest", "preprocessing_digest", "adapter_digest", "source_sha256", "input_digest"):
        digest(exp[name])
    if exp["adapter_digest"] != ADAPTER:
        raise BridgeError("unregistered representation adapter")
    if exp["source_sha256"] != sha(source):
        raise BridgeError("original source mismatch")
    principal, purpose = identifier(exp["principal_id"]), identifier(exp["purpose_id"])
    gen = bounded_int(exp["generation"], 1, 2**64 - 1)
    epoch = bounded_int(exp["authority_epoch"], 1, 2**64 - 1)
    expiry = bounded_int(exp["expires_at_ms"], now_ms + 1, 2**64 - 1)
    bounded_int(exp["width"], 384, 384)
    bounded_int(exp["encoder_forwards"], 1, 1)
    bounded_int(exp["encoder_cpu_ns"], 1, 2**64 - 1)
    bounded_int(exp["encoder_wall_ns"], 1, 2**64 - 1)
    ids, mask, values = exp["input_ids"], exp["attention_mask"], exp["values_q24"]
    if not isinstance(ids, list) or not 1 <= len(ids) <= 256 or not isinstance(mask, list) or len(mask) != len(ids):
        raise BridgeError("invalid token sequence")
    if any(type(v) is not int or not 0 <= v <= 1_000_000 for v in ids) or any(type(v) is not int or v != 1 for v in mask):
        raise BridgeError("invalid token or attention mask")
    if exp["input_digest"] != complete_input_sha(source, ids, mask):
        raise BridgeError("source-token binding mismatch")
    if not isinstance(values, list) or len(values) != len(ids) * 384 or any(type(v) is not int or abs(v) > 8 * Q24 for v in values):
        raise BridgeError("invalid Q24 tensor")
    numeric = b"".join(v.to_bytes(8, "big", signed=True) for v in values)
    feature_sha = sha(numeric)
    if (set(rev) != REVIEW_FIELDS or rev.get("schema") != REVIEW_SCHEMA or rev.get("export_sha256") != sha(export_bytes)
        or rev.get("source_sha256") != sha(source)
        or rev.get("input_digest") != exp["input_digest"]
        or rev.get("material_sha256") != MATERIAL
        or rev.get("encoder_digest") != exp["encoder_digest"]
        or rev.get("feature_q24_sha256") != feature_sha
        or rev.get("producer_claimed_forwards") != exp["encoder_forwards"]
        or rev.get("producer_claimed_cpu_ns") != exp["encoder_cpu_ns"]
        or rev.get("producer_claimed_wall_ns") != exp["encoder_wall_ns"]
        or rev.get("reviewer_encoder_forwards") != 1
        or rev.get("model_replayed") is not True
        or rev.get("authority") != "DENY_ALL"
        or rev.get("selected_model") is not False
        or rev.get("production_authorized") is not False):
        raise BridgeError("missing independent physical reviewer binding")
    for key in ("reviewer_encoder_cpu_ns", "reviewer_encoder_wall_ns", "exact_tensors"):
        bounded_int(rev.get(key), 1, 2**64 - 1)
    preprocessing_bound = sha(b"hepta.stem.granite97.input-normalizer-preproc.v2\0"
        + bytes.fromhex(exp["normalizer_digest"])
        + bytes.fromhex(exp["preprocessing_digest"])
        + bytes.fromhex(exp["input_digest"]))
    envelope = FeatureEnvelope(
        modality="text", original_sha256=sha(source), feature_sha256=feature_sha,
        encoder_sha256=exp["encoder_digest"], tokenizer_sha256=exp["tokenizer_digest"],
        preprocessor_sha256=preprocessing_bound, quantization_sha256=exp["quantization_digest"],
        projection_sha256=exp["adapter_digest"], principal=principal, purpose=purpose,
        generation=gen, epoch=epoch, slot_count=len(ids), width=384,
        timestamps=(), regions=(), source_kind="original", reviewed=True)
    key = admit_features(envelope, numeric)
    report = {
        "schema": "hepta.stem.granite97-feature-bridge.v2",
        "authority": "DENY_ALL", "production_authorized": False,
        "trained_cell_efficacy_established": False,
        "independent_model_issuer_signature_verified": False,
        "independent_reviewer_process_attested": False,
        "model_executed_in_this_bridge": False,
        "source_sha256": sha(source), "export_sha256": sha(export_bytes),
        "review_sha256": sha(review_bytes), "q24_blob_sha256": feature_sha,
        "material_sha256": MATERIAL, "complete_input_sha256": exp["input_digest"],
        "bound_preprocessor_sha256": preprocessing_bound,
        "feature_envelope_key": key, "feature_rows": len(ids), "width": 384,
        "producer_reported_forward_count": 1, "reviewer_reported_forward_count": 1,
        "producer_reported_cpu_ns": exp["encoder_cpu_ns"],
        "reviewer_reported_cpu_ns": rev["reviewer_encoder_cpu_ns"],
        "bridge_observed_forward_count": 0, "expiry_ms": expiry,
    }
    return BridgeOutcome(envelope, numeric, report)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", required=True)
    p.add_argument("--export", required=True)
    p.add_argument("--review", required=True)
    p.add_argument("--output", required=True)
    args = p.parse_args()
    result = bridge(read_regular(args.source, 65536),
                    read_regular(args.export, 2_500_000),
                    read_regular(args.review, 65536),
                    now_ms=time.time_ns() // 1_000_000)
    target = Path(args.output)
    if target.exists() or target.is_symlink():
        raise BridgeError("no overwrite")
    data = (json.dumps(result.replay, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
    with target.open("xb") as output:
        output.write(data)
        output.flush()
        os.fsync(output.fileno())

if __name__ == "__main__":
    main()
