"""Bind the authentic N256 new export to roster, engineering, and stream plans.

This module is deliberately stdlib-only.  It reads and hashes originals; it never
imports the numerical candidate, NumPy, SciPy, Torch, or any optimizer.
"""

from __future__ import annotations

import argparse
import ast
import base64
import hashlib
import json
import resource
import struct
import time
import zipfile
from fractions import Fraction
from io import BytesIO
from pathlib import Path
from typing import Any

IDENTITY = "hcsn-n256-input-lineage-admission-20261113-c06d-001"
EXPECTED_INPUT = {
    "metadata": "88e84dd3aea396d34c7e2dd08d31f2e30bf694c20516dccde57e6dd1b0c2a3c6",
    "state": "360b4bf446e853209c58cdb3faded74d9114d872cfb9c730b220d14cef670f9c",
    "phase": "790fabee8825dbd4361f157f56d78641430fe50b9134cd2cb7b02b51b93fe548",
    "npz_b64": "926191319021c51421dd15d76c66c3b5c6d2efef0f28af3f76c893065a49dbeb",
    "npz": "c98a3339504c908081dbf77d2235a18de96da06b1ebda7b1c0f9192af1570eb8",
}
EXPECTED_BUNDLE = "17086fb6ba83211e8626c7ac9c22183f6c9c9a7dc615772b5a32d2c14ecb8e95"
EXPECTED_ROSTER = "e289c20d6595cb6d92dd3e2585bc7cb40fb0d5a408725c5edc14a9fb7f328fe2"
EXPECTED_COORDINATES = 18_225_028
EXPECTED_CAPSULES = 14
EXPECTED_PACKETS = 185
EXPECTED_SEGMENTS = 45

REL = {
    "metadata": "qualification/hcsn_n256_new_export/evidence/attempt001/METADATA.json",
    "state": "qualification/hcsn_n256_new_export/evidence/attempt001/N256_STATE.json",
    "phase": "qualification/hcsn_n256_new_export/evidence/attempt001/N256_PHASE.json",
    "npz_b64": "qualification/hcsn_n256_new_export/evidence/attempt001/N256_STATE.npz.b64",
    "export_receipt": "qualification/hcsn_n256_new_export/evidence/attempt001/RECEIPT.json",
    "export_audit": "qualification/hcsn_n256_new_export/evidence/attempt001/AUDIT.json",
    "roster_readback": "qualification/hcsn_currentstate_n256_roster/evidence/source-266dfe6/attempt001/INPUT_READBACK.json",
    "roster_summary": "qualification/hcsn_currentstate_n256_roster/evidence/source-266dfe6/attempt001/SUMMARY.json",
    "roster_audit": "qualification/hcsn_currentstate_n256_roster/evidence/source-266dfe6/AUDIT.json",
    "engineering": "qualification/hcsn_currentstate_n256_engineering/evidence/source-8b0d340/attempt001/AUDIT.json",
    "streaming": "qualification/hcsn_currentstate_n256_streaming_intent/evidence/source-f2a83b0/attempt002/PLAN.json",
    "streaming_audit": "qualification/hcsn_currentstate_n256_streaming_intent/evidence/source-f2a83b0/FINAL_AUDIT.json",
}
SOURCE_FILES = ("__init__.py", "verify.py", "review.py", "test_verify.py", "README.md", "REQUEST.json")


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_sha(path: Path) -> str:
    return sha256(path.read_bytes())


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def read_npy(raw: bytes) -> tuple[tuple[int, ...], bytes]:
    require(raw.startswith(b"\x93NUMPY"), "NPY magic")
    major = raw[6]
    require(major in (1, 2, 3), "NPY version")
    width = 2 if major == 1 else 4
    header_len = int.from_bytes(raw[8 : 8 + width], "little")
    offset = 8 + width + header_len
    header = ast.literal_eval(raw[8 + width : offset].decode("latin1").strip())
    shape = tuple(int(value) for value in header["shape"])
    require(header["descr"] == "<f8", "NPY dtype")
    require(header["fortran_order"] is False, "NPY order")
    count = 1
    for value in shape:
        count *= value
    payload = raw[offset:]
    require(len(payload) == 8 * count, "NPY payload length")
    return shape, payload


def payload_hex(payload: bytes) -> list[str]:
    return [float.hex(value[0]) for value in struct.iter_unpack("<d", payload)]


def verify_source_freeze(root: Path) -> dict[str, str]:
    package = root / "qualification/hcsn_currentstate_n256_admission"
    freeze = load_json(package / "SOURCE_FREEZE.json")
    require(freeze["identity"] == IDENTITY, "source-freeze identity")
    observed = {name: file_sha(package / name) for name in SOURCE_FILES}
    require(observed == freeze["source_sha256"], "source-freeze hashes")
    return observed


def verify(root: Path) -> dict[str, Any]:
    paths = {name: root / rel for name, rel in REL.items()}
    observed_input = {name: file_sha(paths[name]) for name in ("metadata", "state", "phase", "npz_b64")}
    encoded = paths["npz_b64"].read_text().strip()
    decoded = base64.b64decode(encoded, validate=True)
    observed_input["npz"] = sha256(decoded)
    require(observed_input == EXPECTED_INPUT, "authentic export hashes")
    require(sha256(canonical(observed_input)) == EXPECTED_BUNDLE, "input bundle")

    state = load_json(paths["state"])
    phase = load_json(paths["phase"])
    metadata = load_json(paths["metadata"])
    receipt = load_json(paths["export_receipt"])
    export_audit = load_json(paths["export_audit"])
    require(metadata["historical_N256_export_present"] is False, "historical export remains absent")
    require(metadata["dynamic_execution_allowed"] is False, "dynamic execution remains disallowed")
    require(metadata["largegrid_qualification"] is False, "large-grid HOLD")
    require(metadata["global_HOLD"] is True and metadata["all_closed"] is False, "global HOLD")
    require(receipt["new_export_only"] is True, "new-export-only receipt")
    require(receipt["historical_N256_missing_statement_preserved"] is True, "historical negative preserved")
    require(export_audit["coordinate_byte_comparisons"] == 1542, "export audit denominator")
    require(export_audit["audit_DDE_model_optimizer_calls"] == [0, 0, 0], "export zero calls")

    members: dict[str, dict[str, Any]] = {}
    with zipfile.ZipFile(BytesIO(decoded)) as archive:
        require(set(archive.namelist()) == {"nodes.npy", "active.npy", "content.npy"}, "NPZ members")
        for name in sorted(archive.namelist()):
            raw = archive.read(name)
            shape, payload = read_npy(raw)
            members[name] = {"shape": list(shape), "payload_sha256": sha256(payload), "hex": payload_hex(payload)}

    require(members["nodes.npy"]["shape"] == [257], "node shape")
    require(members["active.npy"]["shape"] == [257], "active shape")
    require(members["content.npy"]["shape"] == [257, 4], "content shape")
    require(members["nodes.npy"]["hex"] == state["nodes_fp64_hex"], "node bytes")
    require(members["active.npy"]["hex"] == state["active_probability_fp64_hex"], "active bytes")
    require(members["content.npy"]["hex"] == state["signed_content_fp64_hex_row_major"], "content bytes")
    require(sum(len(value["hex"]) for value in members.values()) == 1542, "coordinate count")

    require(phase["packet_count"] == 8 and len(phase["packets"]) == 8, "phase packet count")
    previous = Fraction(0)
    for packet in phase["packets"]:
        start, end = Fraction(packet["start"]), Fraction(packet["end"])
        require(start == previous and end > start, "phase support chain")
        require(len(packet["signed_content"]) == 4, "phase signed content")
        previous = end
    require(previous == Fraction(1, 5), "phase support terminus")

    roster_readback = load_json(paths["roster_readback"])
    roster = load_json(paths["roster_summary"])
    roster_audit = load_json(paths["roster_audit"])
    require(roster_readback["sha256"] == EXPECTED_INPUT, "roster readback input")
    require(roster["input_sha256"] == EXPECTED_INPUT, "roster input")
    require(roster["input_bundle_sha256"] == EXPECTED_BUNDLE, "roster bundle")
    require(roster["coordinate_identity_sha256"] == EXPECTED_ROSTER, "roster identity")
    require(roster["fp64_coordinate_denominator"] == EXPECTED_COORDINATES, "roster denominator")
    require((roster["capsules"], roster["packet_tuples"], roster["transition_segments"]) == (EXPECTED_CAPSULES, EXPECTED_PACKETS, EXPECTED_SEGMENTS), "roster counts")
    require(roster["dynamic_runs"] == roster["matrix_exponentials"] == roster["oracle_calls"] == 0, "roster zero execution")
    require(roster["historical_N256_export_present"] is False and roster["new_export_only"] is True, "roster historical hold")
    require(roster_audit["input_sha256"] == EXPECTED_INPUT, "roster audit input")
    require(roster_audit["status"] == "PASS" and roster_audit["largegrid_qualification"] is False, "roster audit HOLD")

    engineering = load_json(paths["engineering"])
    require(engineering["input_sha256"] == EXPECTED_INPUT, "engineering input")
    require(engineering["input_bundle_sha256"] == EXPECTED_BUNDLE, "engineering bundle")
    require(engineering["roster_identity"] == EXPECTED_ROSTER, "engineering roster")
    require(engineering["status"] == "RED_RESOURCE_CAP_HOLD", "engineering RED preserved")
    require(engineering["dynamic_resource_safe"] is False, "engineering resource HOLD")
    require(engineering["historical_N256_export_present"] is False and engineering["new_export_only"] is True, "engineering historical hold")
    require(engineering["dynamic_runs"] == engineering["matrix_exponentials"] == engineering["oracle_numeric_calls"] == 0, "engineering zero execution")

    streaming = load_json(paths["streaming"])
    streaming_audit = load_json(paths["streaming_audit"])
    require(streaming["input_bundle_sha256"] == EXPECTED_BUNDLE, "streaming bundle")
    require(streaming["roster_identity"] == EXPECTED_ROSTER, "streaming roster")
    require(streaming["conceptual_fp64_coordinates"] == EXPECTED_COORDINATES, "streaming denominator")
    require(streaming["status"] == "PASS_STREAM_STORAGE_HOLD_DYNAMIC", "streaming HOLD")
    require(all(value == 0 for value in streaming["execution_counts"].values()), "streaming zero execution")
    require(streaming_audit["status"] == "PASS_ZERO_EXECUTION_REVIEW_HOLD_DYNAMIC", "stream review HOLD")
    require(streaming_audit["dynamic_runs"] == streaming_audit["matrix_exponentials"] == 0, "stream review zero execution")

    source_sha = verify_source_freeze(root)
    original_sha = {name: file_sha(path) for name, path in paths.items()}
    return {
        "schema": "hcsn-n256-input-lineage-admission-report-v1",
        "identity": IDENTITY,
        "status": "PASS_AUTHENTIC_NEW_EXPORT_LINEAGE_HOLD_DYNAMIC",
        "closed_gate": "authentic_new_export_input_lineage",
        "historical_N256_export_recovered": False,
        "historical_N256_missing_statement_preserved": True,
        "new_export_only": True,
        "input_sha256": observed_input,
        "input_bundle_sha256": EXPECTED_BUNDLE,
        "roster_identity": EXPECTED_ROSTER,
        "fp64_coordinate_denominator": EXPECTED_COORDINATES,
        "capsules": EXPECTED_CAPSULES,
        "packet_tuples": EXPECTED_PACKETS,
        "transition_segments": EXPECTED_SEGMENTS,
        "decoded_coordinates_checked": 1542,
        "phase_supports_checked": 8,
        "source_sha256": source_sha,
        "original_sha256": original_sha,
        "execution_counts": {
            "dynamic_runs": 0,
            "matrix_exponentials": 0,
            "oracle_numeric_calls": 0,
            "serializer_numeric_calls": 0,
            "torch_calls": 0,
            "backward_calls": 0,
            "optimizer_steps": 0,
            "training_runs": 0,
        },
        "preserved_results": {
            "engineering": "RED_RESOURCE_CAP_HOLD",
            "streaming": "PASS_STREAM_STORAGE_HOLD_DYNAMIC",
        },
        "remaining_gates": [
            "N256 numerical candidate implementation",
            "independent numerical oracle implementation",
            "expm workspace and actual RSS profile",
            "canonical serializer and cold-loader execution",
            "host and ancestor-cgroup allocation",
            "concurrency and calendar reservation",
            "warm/cold byte equality on actual N256 state",
        ],
        "largegrid_qualification": False,
        "global_HOLD": True,
        "all_closed": False,
    }


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    wall0, cpu0 = time.perf_counter_ns(), time.process_time_ns()
    report = verify(args.root)
    costs = {
        "schema": "hcsn-n256-input-lineage-admission-cost-v1",
        "identity": IDENTITY,
        "wall_ns": time.perf_counter_ns() - wall0,
        "cpu_ns": time.process_time_ns() - cpu0,
        "ru_maxrss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "stdlib_verifier_runs": 1,
        **report["execution_counts"],
    }
    args.output.mkdir(parents=True, exist_ok=False)
    write_json(args.output / "REPORT.json", report)
    write_json(args.output / "COSTS.json", costs)
    receipt = {
        "schema": "hcsn-n256-input-lineage-admission-receipt-v1",
        "identity": IDENTITY,
        "exit_code": 0,
        "report_sha256": file_sha(args.output / "REPORT.json"),
        "costs_sha256": file_sha(args.output / "COSTS.json"),
        "historical_N256_export_recovered": False,
        "new_export_only": True,
        "largegrid_qualification": False,
        "global_HOLD": True,
        "all_closed": False,
    }
    write_json(args.output / "RECEIPT.json", receipt)
    print(json.dumps({"status": report["status"], "report_sha256": receipt["report_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
