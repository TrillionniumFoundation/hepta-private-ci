"""Independent stdlib audit of retained N256 export bytes and exact totals."""

import argparse
import ast
import base64
from fractions import Fraction as F
import hashlib
import json
from pathlib import Path
import struct
import zipfile


EXPECTED_IDENTITY = "hcsn-n256-new-export-20261112-c06d-attempt001"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read_json(path):
    return json.loads(path.read_text())


def read_npy(raw):
    if raw[:6] != b"\x93NUMPY" or raw[6:8] != b"\x01\x00":
        raise ValueError("expected canonical NumPy v1 array")
    header_len = struct.unpack("<H", raw[8:10])[0]
    header = ast.literal_eval(raw[10 : 10 + header_len].decode("latin1"))
    if header["descr"] != "<f8" or header["fortran_order"] is not False:
        raise ValueError("expected little-endian row-major FP64")
    payload = raw[10 + header_len :]
    count = 1
    for width in header["shape"]:
        count *= width
    if len(payload) != 8 * count:
        raise ValueError("NPY payload length differs")
    values = struct.unpack(f"<{count}d", payload)
    return list(header["shape"]), [value.hex() for value in values], payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    base = args.artifact
    metadata = read_json(base / "METADATA.json")
    state = read_json(base / "N256_STATE.json")
    phase = read_json(base / "N256_PHASE.json")
    costs = read_json(base / "COSTS.json")
    receipt = read_json(base / "RECEIPT.json")
    if not all(
        x["identity"] == EXPECTED_IDENTITY
        for x in (metadata, state, phase, costs, receipt)
    ):
        raise ValueError("attempt identity differs")
    if not (
        metadata["new_export"] is True
        and metadata["historical_N256_export_present"] is False
        and metadata["global_HOLD"] is True
        and metadata["all_closed"] is False
        and metadata["largegrid_qualification"] is False
        and metadata["dynamic_execution_allowed"] is False
    ):
        raise ValueError("scope boundary differs")

    encoded = (base / "N256_STATE.npz.b64").read_text()
    npz_raw = base64.b64decode(encoded, validate=True)
    if (
        sha(npz_raw) != metadata["npz"]["sha256"]
        or len(npz_raw) != metadata["npz"]["bytes"]
    ):
        raise ValueError("decoded NPZ identity differs")
    if sha(encoded.encode()) != metadata["npz"]["base64_sha256"]:
        raise ValueError("retained base64 identity differs")
    original_npz = base / "N256_STATE.npz"
    if original_npz.exists() and original_npz.read_bytes() != npz_raw:
        raise ValueError("local NPZ and retained base64 differ")

    expected = {
        "nodes.npy": ([257], state["nodes_fp64_hex"]),
        "active.npy": ([257], state["active_probability_fp64_hex"]),
        "content.npy": ([257, 4], state["signed_content_fp64_hex_row_major"]),
    }
    decoded = {}
    # Audit the exact decoded bytes without trusting a filesystem rewrite.
    from io import BytesIO

    with zipfile.ZipFile(BytesIO(npz_raw)) as archive:
        if sorted(archive.namelist()) != sorted(expected):
            raise ValueError("NPZ member roster differs")
        for name, (shape, hex_values) in expected.items():
            actual_shape, actual_hex, payload = read_npy(archive.read(name))
            if actual_shape != shape or actual_hex != hex_values:
                raise ValueError(f"{name} coordinate bytes differ")
            decoded[name] = {
                "shape": actual_shape,
                "coordinates": len(actual_hex),
                "payload_sha256": sha(payload),
            }

    source_root = base.parents[2] / "hcsn_currentstate_scale_spec"
    selected = read_json(source_root / "inputs/SELECTED_ORIGINAL_LAW.json")
    source_probability = [
        F(str(value)) for value in selected["state"]["probability"][0]
    ]
    source_content = [
        [F(str(value)) for value in row] for row in selected["state"]["content_mass"][0]
    ]
    active = [F(value) for value in state["active_probability_exact"]]
    marked = [[F(value) for value in row] for row in state["signed_content_exact"]]
    packets = phase["packets"]
    if len(packets) != 8 or phase["packet_count"] != 8:
        raise ValueError("phase denominator differs")
    for index, packet in enumerate(packets):
        if F(packet["start"]) != F(index, 40) or F(packet["end"]) != F(index + 1, 40):
            raise ValueError("phase support differs")
        if len(packet["signed_content"]) != 4:
            raise ValueError("phase signed channel count differs")
    output_mass = sum(active) + sum(F(packet["mass"]) for packet in packets)
    if output_mass != sum(source_probability):
        raise ArithmeticError("exact migrated probability total differs")
    source_totals = [
        sum(row[channel] for row in source_content) for channel in range(4)
    ]
    output_totals = [
        sum(row[channel] for row in marked)
        + sum(F(packet["signed_content"][channel]) for packet in packets)
        for channel in range(4)
    ]
    if output_totals != source_totals:
        raise ArithmeticError("exact migrated signed-content totals differ")
    if any(
        costs[key] != 0
        for key in (
            "DDE_solves",
            "model_calls",
            "matrix_exponentials",
            "spatial_matrix_constructions",
            "discounted_hit_solves",
            "backward_calls",
            "optimizer_steps",
            "training_steps",
        )
    ):
        raise ValueError("forbidden execution counter is nonzero")

    result = {
        "schema": "hcsn-n256-new-export-independent-audit-v1",
        "identity": EXPECTED_IDENTITY,
        "audit_candidate_imports": 0,
        "audit_numpy_imports": 0,
        "audit_scipy_imports": 0,
        "audit_DDE_model_optimizer_calls": [0, 0, 0],
        "decoded_npz_sha256": sha(npz_raw),
        "decoded_members": decoded,
        "coordinate_byte_comparisons": 257 + 257 + 257 * 4,
        "exact_probability_total_equal": True,
        "exact_signed_content_totals_equal": [True, True, True, True],
        "phase_packets_checked": 8,
        "phase_supports_checked": 8,
        "source_visit": selected["selection"],
        "historical_N256_missing_statement_preserved": True,
        "new_export_only": True,
        "dynamic_qualification": False,
        "global_HOLD": True,
        "all_closed": False,
        "findings": [],
    }
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "identity": EXPECTED_IDENTITY,
                "coordinate_byte_comparisons": result["coordinate_byte_comparisons"],
                "exact_totals": 5,
                "phase_packets": 8,
                "candidate_imports": 0,
                "DDE_model_optimizer_calls": [0, 0, 0],
                "findings": [],
                "global_HOLD": True,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
