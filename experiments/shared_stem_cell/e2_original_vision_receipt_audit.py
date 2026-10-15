"""Read-only, producer-independent verification of a DINOv2 physical artifact ZIP.

Checks archived *claims and bytes*. A valid ZIP does not independently attest
pretrained model execution, publisher identity or real-task model quality.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import stat
import zipfile

MODEL = "facebook/dinov2-small"
REVISION = "150c8e7bb7cef2d30ec31b13a517af14840ee3f7"
WEIGHTS_SHA = "ae1e99fcefd534ed978cdeb8326f08030c96e28b7a81ffcbc98a857c84d14be1"
FILENAMES = {"features.jsonl", "receipt.json"}
HEX = set("0123456789abcdef")
MAX_ZIP = 2_000_000
MAX_UNCOMPRESSED = 4_000_000

class AuditError(ValueError):
    pass

def digest(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()

def is_hex(value):
    return type(value) is str and len(value) == 64 and not set(value).difference(HEX)

def canonical(data):
    return (json.dumps(data, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False) + "\n").encode()

def unique_keys(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            raise AuditError("duplicate JSON key")
        out[k] = v
    return out

def parse_json(blob):
    data = json.loads(blob, object_pairs_hook=unique_keys,
                      parse_constant=lambda _: (_ for _ in ()).throw(AuditError("nonfinite JSON")))
    if canonical(data) != blob:
        raise AuditError("noncanonical JSON bytes")
    return data

def audit_archive(archive: bytes, expected_zip_sha: str) -> dict:
    if not is_hex(expected_zip_sha) or not 0 < len(archive) <= MAX_ZIP or digest(archive) != expected_zip_sha:
        raise AuditError("archive bytes not SHA-pinned")
    with zipfile.ZipFile(io.BytesIO(archive)) as zf:
        infos = zf.infolist()
        if len(infos) != 2 or {i.filename for i in infos} != FILENAMES:
            raise AuditError("unexpected, missing or duplicate ZIP member")
        if any(i.is_dir() or i.file_size > MAX_UNCOMPRESSED or i.file_size <= 0 or
               stat.S_ISLNK(i.external_attr >> 16) or i.flag_bits & 1 for i in infos):
            raise AuditError("unsafe ZIP entry")
        if sum(i.file_size for i in infos) > MAX_UNCOMPRESSED:
            raise AuditError("ZIP aggregate expansion exceeds limit")
        feature_bytes = zf.read("features.jsonl")
        receipt = parse_json(zf.read("receipt.json"))
    needed = {"schema", "phase", "encoder_repo", "encoder_revision", "source_sha256",
              "output_sha256", "snapshot_file_sha256s", "image_count",
              "actual_model_forwards", "feature_width", "wall_ns",
              "checkpoint_locally_byte_verified", "publisher_authenticated", "labels_seen",
              "production_accepted", "authority"}
    if (type(receipt) is not dict or set(receipt) != needed or
        receipt["schema"] != "hepta.e2.dinov2-source-features.v1" or
        receipt["phase"] not in ("train", "future") or
        receipt["encoder_repo"] != MODEL or receipt["encoder_revision"] != REVISION or
        receipt["authority"] != "DENY_ALL" or
        receipt["production_accepted"] is not False or receipt["publisher_authenticated"] is not False or
        receipt["checkpoint_locally_byte_verified"] is not True or receipt["labels_seen"] is not False or
        receipt["feature_width"] != 384 or type(receipt["feature_width"]) is not int or
        type(receipt["wall_ns"]) is not int or receipt["wall_ns"] <= 0 or
        not is_hex(receipt["source_sha256"]) or not is_hex(receipt["output_sha256"])):
        raise AuditError("invalid or authority-claiming model receipt")
    weights = receipt["snapshot_file_sha256s"]
    if (type(weights) is not dict or set(weights) != {"model.safetensors", "config.json", "preprocessor_config.json"}
            or not all(is_hex(value) for value in weights.values()) or weights["model.safetensors"] != WEIGHTS_SHA):
        raise AuditError("unrecognized upstream checkpoint inventory")
    if digest(feature_bytes) != receipt["output_sha256"] or not feature_bytes.endswith(b"\n"):
        raise AuditError("bad source-feature artifact digest")
    lines = feature_bytes.splitlines()
    count = receipt["image_count"]
    if type(count) is not int or not 1 <= count <= 256 or len(lines) != count or \
       type(receipt["actual_model_forwards"]) is not int or receipt["actual_model_forwards"] != count:
        raise AuditError("missing physical forward count or row coverage")
    enc_id = digest(canonical([MODEL, REVISION, weights, "cls-first-token", "l2"]))
    expected_keys = {"case_id", "group_id", "scope", "observed_at", "split",
                     "condition", "image_sha256", "question", "source_sha256", "source"}
    seen = set()
    groups = set()
    norms = []
    for line in lines:
        row = parse_json(line + b"\n")
        if type(row) is not dict or set(row) != expected_keys or row["split"] != receipt["phase"]:
            raise AuditError("unapproved or target-bearing feature row")
        for key, maximum in (("case_id",128),("group_id",128),("scope",128),("question",2048)):
            if type(row[key]) is not str or not 1 <= len(row[key].encode()) <= maximum:
                raise AuditError("malformed case metadata")
        if (type(row["observed_at"]) is not int or not 0 <= row["observed_at"] < 2**63 or
            row["condition"] not in ("text_sufficient", "vision_required", "visual_evidence_swapped") or
            not is_hex(row["image_sha256"]) or not is_hex(row["source_sha256"])):
            raise AuditError("malformed physical image case")
        if row["case_id"] in seen:
            raise AuditError("duplicate case identifier")
        seen.add(row["case_id"])
        groups.add(row["group_id"])
        case_id = digest(canonical(["hepta.e2.image-case.v1",row["case_id"],row["group_id"],row["scope"],
                                     row["observed_at"],row["condition"],row["image_sha256"],row["question"]]))
        if row["source_sha256"] != case_id:
            raise AuditError("case provenance misbound")
        source = row["source"]
        if type(source) is not dict or set(source) != {"modality","input_sha256","encoder_sha256","values"} or \
            source["modality"] != "image" or source["input_sha256"] != row["image_sha256"] or \
            source["encoder_sha256"] != enc_id:
            raise AuditError("feature identity is not bound to original model or input")
        values = source["values"]
        if type(values) is not list or len(values) != 384 or any(type(x) not in (int,float) or not math.isfinite(x) or abs(x)>8 for x in values):
            raise AuditError("invalid feature width or value")
        norm = math.sqrt(math.fsum(x*x for x in values))
        if not 0.999 <= norm <= 1.001:
            raise AuditError("feature not unit normalized")
        norms.append(norm)
    if receipt["phase"] == "train" and len(groups) < 2:
        raise AuditError("train-source group count insufficient")
    return {"schema":"hepta.e2.original-vision-independent-audit.v1",
            "zip_sha256":expected_zip_sha, "model_revision":REVISION,
            "original_weights_sha256":WEIGHTS_SHA,"feature_bytes_sha256":receipt["output_sha256"],
            "cases":count,"declared_physical_forwards":count,
            "norm_min":min(norms), "norm_max":max(norms),
            "independent_archive_consistency":True,
            "physical_execution_independently_attested":False,
            "natural_image_task_success_measured":False,
            "production_accepted":False,"authority":"DENY_ALL"}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--archive",required=True)
    parser.add_argument("--archive-sha256",required=True)
    a=parser.parse_args()
    from pathlib import Path
    p=Path(a.archive)
    if p.is_symlink() or not p.is_file() or p.stat().st_size>MAX_ZIP:
        raise AuditError("unsafe archive path")
    print(json.dumps(audit_archive(p.read_bytes(),a.archive_sha256),sort_keys=True))

if __name__=='__main__':main()
