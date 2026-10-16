#!/usr/bin/env python3
"""Independently bind a *sanitized* six-record physical Q24 study ZIP.

This does not reopen weights (they are intentionally absent from the archive),
authenticate the original runner, or authorize model admission / NDU.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import sys
import zipfile

ARMS = ("v2", "v3", "ssm", "min_gru")
STUDIES = (
    ("hepta-near-matched-trained/training-receipt.json",
     "hepta-near-matched-audit.json",
     (2048, 8192), "PRIVATE_PARAMETER_COUNT",
     "hepta.neuron.near-matched-physical-train.v1",
     "hepta.neuron.near-matched-physical-native-oracle.v1"),
    ("hepta-byte-matched-trained/training-receipt.json",
     "hepta-byte-matched-native-audit.json",
     (8192, 32768), "SERIALIZED_SAFETENSORS_BYTES",
     "hepta.neuron.byte-matched-physical-train.v1",
     "hepta.neuron.physical-byte-native-oracle.v1"),
)
FILES = frozenset([
    "hepta-near-matched-fixture.json",
    "hepta-physical-byte-plan.json",
    *(name for study in STUDIES for name in study[:2]),
])
MAX_ZIP = 2_000_000
MAX_MEMBER = 200_000


class Refused(ValueError):
    pass


def need(ok: bool, why: str):
    if not ok:
        raise Refused(why)


def read_json(raw: bytes) -> dict:
    need(1 <= len(raw) <= MAX_MEMBER, "missing/unbounded physical audit record")
    def unique(pairs):
        result = {}
        for name, value in pairs:
            need(name not in result, "duplicate JSON field")
            result[name] = value
        return result
    out = json.loads(raw, object_pairs_hook=unique,
                     parse_constant=lambda _: (_ for _ in ()).throw(Refused("nonfinite JSON")))
    need(type(out) is dict, "non-object evidence")
    return out


def strict_hex(value: object) -> bool:
    return type(value) is str and len(value) == 64 and all(
        letter in "0123456789abcdef" for letter in value
    )


def audit_zip(path: Path) -> dict:
    need(not path.is_symlink(), "symlinked evidence ZIP")
    st = path.stat()
    need(stat.S_ISREG(st.st_mode) and 100 <= st.st_size <= MAX_ZIP,
         "unbounded/nonregular ZIP")
    raw = path.read_bytes()
    after = path.stat()
    fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    need(all(getattr(st, key) == getattr(after, key) for key in fields),
         "ZIP changed during read")
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        infos = archive.infolist()
        need(len(infos) == len(FILES) and
             set(info.filename for info in infos) == FILES,
             "missing/duplicate/foreign archived evidence member")
        need(all(0 < info.file_size <= MAX_MEMBER and
                 0 < info.compress_size <= MAX_MEMBER and
                 not stat.S_ISLNK(info.external_attr >> 16)
                 for info in infos),
             "unbounded or linked member")
        blobs = {info.filename: archive.read(info) for info in infos}
    fixture = read_json(blobs["hepta-near-matched-fixture.json"])
    plan = read_json(blobs["hepta-physical-byte-plan.json"])
    need(fixture.get("source_kind") == "SYNTHETIC_ONLY" and
         fixture.get("authority") == "DENY_ALL" and
         fixture.get("real_encoder_executed") is False and
         strict_hex(fixture.get("trace_sha256")),
         "source fixture is not frozen synthetic/no-authority")
    need(plan.get("schema") == "hepta.neuron.byte-budget-physical-shape-preflight.v1" and
         plan.get("authority") == "DENY_ALL" and
         plan.get("predeclared_byte_caps") == [8192, 32768] and
         plan.get("genuine_learned_weights_measured") is False,
         "invalid byte-plan provenance or model claim")
    summary = []
    identities = set()
    for trained_path, native_path, caps, kind, train_schema, native_schema in STUDIES:
        original_bytes = blobs[trained_path]
        trained, native = read_json(original_bytes), read_json(blobs[native_path])
        need(trained.get("schema") == train_schema and
             native.get("schema") == native_schema and
             native.get("study_kind") == kind and
             trained.get("source_class") == "SYNTHETIC_FIXTURE_ONLY" and
             trained.get("authority") == native.get("authority") == "DENY_ALL" and
             trained.get("decision") == native.get("decision") == "NO_MODEL_PROMOTION",
             "study identity/authority mismatch")
        need(native.get("training_receipt_sha256") ==
             hashlib.sha256(original_bytes).hexdigest() and
             native.get("frozen_input_trace_sha256") == fixture["trace_sha256"] and
             trained.get("actual_train_input_sha256") == fixture.get("train_sha256"),
             "original trainer/native/fixture SHA binding broken")
        need(trained.get("physical_model_file_count") == 8 and
             native.get("physically_loaded_models") == 8 and
             native.get("actual_native_os_processes") == 16 and
             native.get("independent_integer_adapter_head_parity") is True,
             "eight physical candidates/sixteen processes not verified")
        for record in (trained, native):
            need(record.get("production_qualification") is False and
                 record.get("ndu_eligible") is False and
                 record.get("future_utility_verified") is False,
                 "forged NDU/production/future qualification")
        need(native.get("independent_temporal_model_parity") is False and
             native.get("original_selected_v1_a0_verified") is False,
             "forged temporal/A0 proof")
        rows, observed = trained.get("cells"), native.get("rows")
        need(type(rows) is list and type(observed) is list and
             len(rows) == len(observed) == 8,
             "incomplete candidate and native record census")
        expected = {(cap, arm) for cap in caps for arm in ARMS}
        pairs = set()
        seen_native = set()
        for row in rows:
            need(type(row) is dict, "bad physical model row")
            cap, arm, sha = row.get("cap"), row.get("arm"), row.get("weight_sha256")
            need(type(cap) is int and arm in ARMS and strict_hex(sha) and
                 (cap, arm) not in pairs and (kind, sha) not in identities,
                 "duplicate or malformed physical candidate")
            pairs.add((cap, arm))
            identities.add((kind, sha))
            need(row.get("optimizer_steps") == trained.get("candidate_training_step_count") == 8
                 and type(row.get("physical_bytes")) is int and row["physical_bytes"] > 0,
                 "wrong optimizer steps / physical weight byte census")
            if kind == "SERIALIZED_SAFETENSORS_BYTES":
                need(row.get("budget_kind") == kind and
                     row.get("physical_byte_ceiling") == cap and
                     row["physical_bytes"] <= cap and
                     (cap - row["physical_bytes"]) * 100 <= cap * 2,
                     "claimed model does not fit byte budget")
        for row in observed:
            need(type(row) is dict and
                 row.get("independent_integer_adapter_head_parity") is True and
                 row.get("production_qualification") is False and
                 row.get("ndu_eligible") is False and
                 row.get("independent_temporal_kernel_parity") is False and
                 row.get("verified_native_adapter_head_event_count") == 8,
                 "invalid native-Q24 row")
            key = (row.get("cap"), row.get("arm"))
            need(key not in seen_native and key in pairs, "unbound native candidate row")
            seen_native.add(key)
            linked = next(model for model in rows
                          if (model["cap"], model["arm"]) == key)
            need(row.get("physical_weight_sha256") == linked["weight_sha256"],
                 "native hash differs from physical model")
        need(pairs == seen_native == expected, "missing budget/arm slot")
        summary.append({"study_kind": kind, "trained_model_slots": len(rows),
                        "native_process_count": 16, "integer_parity": True})
    need(len(identities) == 16, "cross-study repeated physical model identity")
    return {
        "schema": "hepta.neuron.archived-byte-and-parameter-native-binding.v1",
        "zip_sha256": hashlib.sha256(raw).hexdigest(),
        "studies": summary, "independent_weight_sha_count": len(identities),
        "total_native_process_count": 32, "decision": "NO_MODEL_PROMOTION",
        "source_kind": "SYNTHETIC_ARCHIVED_RECEIPTS_ONLY",
        "raw_weight_bytes_reopened": False, "signed_runner_attested": False,
        "future_utility_verified": False, "ndu_eligible": False,
        "production_qualification": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zip", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = audit_zip(args.zip)
        with args.output.open("x", encoding="utf-8") as handle:
            json.dump(result, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
        return 0
    except (ValueError, OSError, zipfile.BadZipFile, KeyError, TypeError) as error:
        print("BLOCKED_ARCHIVED_Q24_EVIDENCE: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
