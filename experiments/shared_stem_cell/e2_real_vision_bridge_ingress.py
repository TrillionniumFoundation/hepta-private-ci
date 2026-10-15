"""Independently assemble source-pinned *real* vision / paired-text bridge records.

A verified physical image feature receipt is mandatory. Only TRAIN receives text
anchors. FUTURE remains image-source-only; semantic answers never enter bridge.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import json
import os
from e2_real_vision_features import Rejected, checked_file, digest, canonical, sha, _unique, SCHEMA

ALIGNMENT_INPUT = "hepta.stem-alignment.v1"


def _jsonl(raw: bytes, maximum=256):
    if not raw or len(raw) > 16_000_000 or not raw.endswith(b"\n"):
        raise Rejected("empty or oversized JSONL")
    lines = raw.splitlines()
    if not 1 <= len(lines) <= maximum:
        raise Rejected("bad row count")
    return [json.loads(x, object_pairs_hook=_unique,
                       parse_constant=lambda _: (_ for _ in ()).throw(Rejected("nonfinite"))) for x in lines]


def produce(image_data: bytes, image_receipt: dict, *, phase: str,
            anchors: bytes | None = None) -> list[dict]:
    if phase not in ("train", "future"):
        raise Rejected("unrecognized phase")
    if type(image_receipt) is not dict or image_receipt.get("schema") != SCHEMA or image_receipt.get("phase") != phase:
        raise Rejected("vision receipt identity mismatch")
    if (image_receipt.get("checkpoint_locally_byte_verified") is not True or
        image_receipt.get("labels_seen") is not False or
        image_receipt.get("production_accepted") is not False or
        image_receipt.get("authority") != "DENY_ALL" or
        image_receipt.get("output_sha256") != sha(image_data)):
        raise Rejected("physical source receipt or output digest invalid")
    images = _jsonl(image_data)
    if image_receipt.get("actual_model_forwards") != len(images) or image_receipt.get("image_count") != len(images):
        raise Rejected("missing actual-model forwards")
    by_case = {}
    for row in images:
        expected = {"case_id", "group_id", "scope", "observed_at", "split", "condition",
                    "image_sha256", "question", "source_sha256", "source"}
        if type(row) is not dict or set(row) != expected or row["split"] != phase:
            raise Rejected("bad vision source record")
        if type(row["source"]) is not dict or set(row["source"]) != {"modality", "input_sha256", "encoder_sha256", "values"}:
            raise Rejected("bad source feature")
        feature = row["source"]
        if feature["modality"] != "image" or feature["input_sha256"] != row["image_sha256"]:
            raise Rejected("source/feature mismatch")
        digest(feature["encoder_sha256"])
        if type(feature["values"]) is not list or len(feature["values"]) != 384:
            raise Rejected("bad vision feature width")
        for val in feature["values"]:
            import math
            if type(val) not in (int, float) or not math.isfinite(val) or abs(val) > 8:
                raise Rejected("bad vision feature value")
        if type(row["case_id"]) is not str or row["case_id"] in by_case:
            raise Rejected("duplicate vision case")
        by_case[row["case_id"]] = row
    if phase == "future":
        if anchors is not None:
            raise Rejected("future target texts forbidden")
        return [{k: row[k] for k in ("case_id", "group_id", "scope", "observed_at", "split")}
                | {"source": row["source"]} for row in images]
    if anchors is None:
        raise Rejected("TRAIN requires independent train-only text anchors")
    text = _jsonl(anchors)
    lookup = {}
    for row in text:
        if type(row) is not dict or set(row) != {"case_id", "group_id", "scope", "observed_at", "source_sha256", "target_text"}:
            raise Rejected("bad training text anchor")
        if type(row["case_id"]) is not str or row["case_id"] in lookup:
            raise Rejected("duplicate training anchor")
        if type(row["target_text"]) is not str or not 1 <= len(row["target_text"].encode()) <= 8192:
            raise Rejected("invalid training text")
        lookup[row["case_id"]] = row
    if set(lookup) != set(by_case):
        raise Rejected("missing or additional train anchor")
    result = []
    for row in images:
        anchor = lookup[row["case_id"]]
        if any(anchor[k] != row[k] for k in ("case_id", "group_id", "scope", "observed_at", "source_sha256")):
            raise Rejected("cross-source training text join")
        result.append({k: row[k] for k in ("case_id", "group_id", "scope", "observed_at", "split")}
                      | {"source": row["source"], "target_text": anchor["target_text"]})
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--phase", required=True, choices=("train", "future"))
    p.add_argument("--vision", type=Path, required=True)
    p.add_argument("--vision-sha256", required=True)
    p.add_argument("--receipt", type=Path, required=True)
    p.add_argument("--receipt-sha256", required=True)
    p.add_argument("--train-text", type=Path)
    p.add_argument("--train-text-sha256")
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    image_data = checked_file(a.vision, a.vision_sha256, 16_000_000)
    receipt_raw = checked_file(a.receipt, a.receipt_sha256, 200_000)
    receipt = json.loads(receipt_raw, object_pairs_hook=_unique)
    if a.phase == "future" and (a.train_text is not None or a.train_text_sha256 is not None):
        raise Rejected("future must not access target text")
    if a.phase == "train" and (a.train_text is None or a.train_text_sha256 is None):
        raise Rejected("train text missing")
    anchors = checked_file(a.train_text, a.train_text_sha256, 16_000_000) if a.phase == "train" else None
    rows = produce(image_data, receipt, phase=a.phase, anchors=anchors)
    payload = b"".join(canonical(r) for r in rows)
    with a.output.open("xb") as out:
        out.write(payload)
        out.flush()
        os.fsync(out.fileno())
    print(json.dumps({"schema": ALIGNMENT_INPUT, "phase": a.phase, "rows": len(rows),
                      "output_sha256": sha(payload), "production_accepted": False,
                      "authority": "DENY_ALL"}, sort_keys=True))

if __name__ == "__main__":
    main()
