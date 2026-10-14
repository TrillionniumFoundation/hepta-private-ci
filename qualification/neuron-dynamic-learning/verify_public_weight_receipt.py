"""Recompute public EmbeddingGemma 2 smoke ZIP identities, never origin/authority."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import stat
import struct
import zipfile

MODEL = "google/embeddinggemma-2"
REVISION = "914f7f89142e33e77833254d9c9b90c3cef7303b"
DOMAIN = b"hepta.infer.shared-feature-content.v2"
FILES = {"gemma2-snapshot-receipt.json", "gemma2-real-forward.json",
         "gemma2-environment.freeze"}
SOURCES = {"cell.a": "Classify a checked file-content digest.",
           "cell.b": "Classify a checked file-content digest.",
           "cell.c": "Classify an observed syntax error."}


class ReceiptError(ValueError):
    """Absent, replayed, tampered or overclaimed experimental evidence."""


def digest(values: list[int]) -> str:
    if (not isinstance(values, list) or len(values) != 256
            or any(type(n) is not int or abs(n) > 8 * (1 << 24) for n in values)):
        raise ReceiptError("not an admitted 256d signed Q24 vector")
    payload = DOMAIN + len(values).to_bytes(8, "big")
    payload += b"".join(struct.pack(">q", v) for v in values)
    return hashlib.sha256(payload).hexdigest()


def verify_zip(path: Path) -> dict:
    with zipfile.ZipFile(path) as archive:
        files = archive.infolist()
        if (len(files) != len(FILES) or {x.filename for x in files} != FILES
                or any(x.file_size < 1 or x.file_size > 512 * 1024
                       or x.compress_size < 1 or x.is_dir()
                       or stat.S_IFMT(x.external_attr >> 16) == stat.S_IFLNK
                       for x in files)):
            raise ReceiptError("unsafe or incomplete exact source archive")
        source = json.loads(archive.read("gemma2-snapshot-receipt.json"))
        result = json.loads(archive.read("gemma2-real-forward.json"))
        environment = archive.read("gemma2-environment.freeze").decode("utf-8")
    if (source.get("source") != MODEL or source.get("revision") != REVISION
            or source.get("production_promotion") != "DENY_ALL"
            or source.get("remote_metadata_is_not_independent_signature") is not True
            or source.get("actual_encoder_forward_executed") is not False
            or type(source.get("bytes_verified")) is not int
            or source["bytes_verified"] < 1_000_000_000
            or type(source.get("model_files")) is not int
            or source["model_files"] < 1):
        raise ReceiptError("source manifest violates closed evidence boundary")
    if (result.get("model_id") != MODEL or result.get("model_revision") != REVISION
            or result.get("evidence_type") != "local_weight_execution_unverified_origin"
            or result.get("physical_local_model_execution") is not True
            or result.get("physical_transformer_forward_calls") is not None
            or result.get("independently_authenticated_receipt") is not False
            or result.get("model_origin_independently_authenticated") is not False
            or result.get("production_promotion") != "DENY_ALL"
            or result.get("profile") != "text" or result.get("feature_dimension") != 256
            or result.get("cell_requests") != 3 or result.get("distinct_input_rows") != 2
            or result.get("sentence_transformer_encode_calls") != 1
            or result.get("text_token_budget_verified") is not True
            or result.get("multimodal_internal_token_budget_verified") is not False
            or type(result.get("measured_wall_micros")) is not int
            or result["measured_wall_micros"] <= 0):
        raise ReceiptError("model output or non-authorizing evidence claims inconsistent")
    rows = result.get("rows")
    if (not isinstance(rows, list) or len(rows) != 3
            or not isinstance(source.get("pipeline_digest"), str)
            or len(source["pipeline_digest"]) != 64):
        raise ReceiptError("incomplete output identity")
    installed = {item.split("==", 1)[0].lower(): item.split("==", 1)[1]
                 for item in environment.splitlines() if item.count("==") == 1}
    for package in ("torch", "sentence-transformers", "transformers", "safetensors"):
        if package not in installed or not installed[package]:
            raise ReceiptError("missing environment dependency")
    observed = {}
    for row in rows:
        cid = row.get("cell_id")
        if not isinstance(cid, str) or cid not in SOURCES or cid in observed:
            raise ReceiptError("unknown or repeated Cell")
        values = row.get("features_q24")
        if row.get("feature_digest") != digest(values):
            raise ReceiptError("recomputed Q24 content digest mismatch")
        if (row.get("input_digest") != hashlib.sha256(SOURCES[cid].encode()).hexdigest()
                or row.get("pipeline_digest") != source["pipeline_digest"]
                or row.get("authority") != "DENY_ALL"
                or row.get("scope_id") != "public.shadow"
                or row.get("principal_id") != "physical.cpu"
                or row.get("purpose_id") != "nonproduction.smoke"
                or row.get("generation") != 1 or row.get("authority_epoch") != 1
                or row.get("modality") != "text" or row.get("role") != "classification"
                or row.get("requires_new_neuron_profile") is not False):
            raise ReceiptError("source identity, scope or revocation generation mismatch")
        norm = math.sqrt(sum((float(n) / (1 << 24)) ** 2 for n in values))
        if not 0.995 <= norm <= 1.005:
            raise ReceiptError("model output not normalized")
        observed[cid] = (values, row.get("embedding_f32_digest"), row["feature_digest"])
    if (set(observed) != set(SOURCES)
            or observed["cell.a"] != observed["cell.b"]
            or observed["cell.a"][2] == observed["cell.c"][2]):
        raise ReceiptError("shared-identical-input or different-input control failed")
    return {
        "schema": "hepta.gemma2.public-archive-integrity-review.v1",
        "source_model": MODEL, "revision": REVISION,
        "archive_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "source_claimed_verified_model_bytes": source["bytes_verified"],
        "checked_cell_rows": 3, "unique_checked_outputs": 2,
        "matched_rust_q24_content_digests": 3,
        "shared_exact_input_reuse_verified": True,
        "distinct_input_digest_differentiation_verified": True,
        "model_forward_api_calls_claimed": 1,
        "physical_transformer_forward_calls_verified": None,
        "independent_weight_origin_attestation": False,
        "independent_model_execution_attestation": False,
        "independent_task_accuracy_evidence": False,
        "multimodal_forward_verified": False,
        "independent_future_window_learning_evidence": False,
        "production_promotion": "DENY_ALL",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    arguments = parser.parse_args()
    print(json.dumps(verify_zip(arguments.archive), sort_keys=True))
