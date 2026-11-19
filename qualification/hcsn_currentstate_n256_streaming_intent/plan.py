"""Static N256 streaming full-state preservation and comparator resource plan.

This source reads only published JSON/JSONL evidence. It does not import NumPy,
SciPy, Torch, the candidate, or the oracle, and performs no numerical dynamics.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path

EXPECTED = {
    "summary": "e3e21bd9f21940e22738b8f06b9b50333d82a923a6d46894316c242b88dd122f",
    "capsules": "eebc5a010c935c9ca5fc3daaa1716733907f34039c7e3ae4e4bf8fff8ef441f8",
    "packets": "cc5a9199c076215d2f808f0974cc201d34954eafebafea1bf955c929eb36dc1c",
    "engineering_audit": "4ee017d5c418f6288c24fbad6f451e0e78524ad048a9b20d75bf5e626bd28376",
}
ROSTER_IDENTITY = "e289c20d6595cb6d92dd3e2585bc7cb40fb0d5a408725c5edc14a9fb7f328fe2"
INPUT_BUNDLE_IDENTITY = "17086fb6ba83211e8626c7ac9c22183f6c9c9a7dc615772b5a32d2c14ecb8e95"
SOURCE_COMMIT = "8b0d34034902a699b7a437a4076fbe76ad032368"
CHUNK_COORDINATES = 65_536
CHUNK_BYTES = CHUNK_COORDINATES * 8
FRAME_MANIFEST_BYTES = 48
FIXED_HEADER_BYTES = 128
HASH_TABLE_BYTES = 8 * 64
CAPSULE_DIRECTORY_BYTES = 64
PACKET_METADATA_BYTES = 112
CAPSULE_TRAILER_BYTES = 64
OPERATOR_METADATA_BYTES = 44
EVIDENCE_RESERVE_BYTES = 1_048_576
STATE_COORDINATES_PER_CAPSULE = 10 * 255 + 50

N128_RETAINED_CAPS = {
    "per_buffer_bytes": 8_388_608,
    "cumulative_preserved_bytes": 201_326_592,
    "canonical_archive_bytes": 268_435_456,
}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_bound(path, expected):
    path = Path(path)
    if digest(path) != expected:
        raise ValueError(f"hash mismatch: {path.name}")
    return path.read_text()


def validate_records(summary, capsules, packets, audit):
    if (
        summary["coordinate_identity_sha256"] != ROSTER_IDENTITY
        or summary["input_bundle_sha256"] != INPUT_BUNDLE_IDENTITY
        or summary["fp64_coordinate_denominator"] != 18_225_028
        or summary["capsules"] != 14
        or summary["packet_tuples"] != 185
        or summary["new_export_only"] is not True
        or summary["historical_N256_export_present"] is not False
    ):
        raise ValueError("N256 roster identity")
    if (
        audit["schema"] != "hcsn-n256-engineering-static-resource-audit-v1"
        or audit["status"] != "RED_RESOURCE_CAP_HOLD"
        or audit["roster_identity"] != ROSTER_IDENTITY
        or audit["input_bundle_sha256"] != INPUT_BUNDLE_IDENTITY
        or audit["source_sha256"]["candidate.py"]
        != "91c55d87fd993c9d01d1b1e98ba855bf171dfd74f2bdc12bd94fc23d9dc7a9d3"
        or audit["dynamic_runs"] != 0
        or audit["matrix_exponentials"] != 0
        or audit["oracle_numeric_calls"] != 0
    ):
        raise ValueError("#6295 RED dependency")
    if len(capsules) != 14 or len(packets) != 185:
        raise ValueError("published denominator")
    grouped = {index: [] for index in range(len(capsules))}
    for packet in packets:
        order = packet["capsule_order"]
        if order not in grouped:
            raise ValueError("capsule order")
        grouped[order].append(packet)
    dense_coordinates = 0
    packet_vector_coordinates = 0
    packet_dimensions = 0
    for order, capsule in enumerate(capsules):
        records = grouped[order]
        if [item["packet_order"] for item in records] != list(range(len(records))):
            raise ValueError("packet order")
        if len(records) != capsule["packets"]:
            raise ValueError("packet count")
        if capsule["lane"] not in {"warm", "coarse", "cold"}:
            raise ValueError("lane")
        expected = STATE_COORDINATES_PER_CAPSULE
        for record in records:
            dimension = record["dimension"]
            if type(dimension) is not int or dimension < 1:
                raise ValueError("packet dimension")
            coordinate_count = dimension * dimension + 6 * dimension
            if record["coordinate_count"] != coordinate_count:
                raise ValueError("packet coordinate count")
            expected += coordinate_count
            dense_coordinates += coordinate_count
            packet_vector_coordinates += 6 * dimension
            packet_dimensions += dimension
        if expected != capsule["coordinate_count"]:
            raise ValueError("capsule coordinate count")
        dense_coordinates += STATE_COORDINATES_PER_CAPSULE
    if dense_coordinates != summary["fp64_coordinate_denominator"]:
        raise ValueError("full coordinate denominator")
    return grouped, packet_vector_coordinates, packet_dimensions


def compile_plan(roster_dir, engineering_audit):
    roster_dir = Path(roster_dir)
    summary = json.loads(read_bound(roster_dir / "SUMMARY.json", EXPECTED["summary"]))
    capsules = json.loads(read_bound(roster_dir / "CAPSULES.json", EXPECTED["capsules"]))
    packets = [
        json.loads(line)
        for line in read_bound(
            roster_dir / "PACKET_ROSTER.jsonl", EXPECTED["packets"]
        ).splitlines()
    ]
    audit = json.loads(read_bound(engineering_audit, EXPECTED["engineering_audit"]))
    grouped, packet_vector_coordinates, packet_dimensions = validate_records(
        summary, capsules, packets, audit
    )

    operator_table_bytes = (
        4
        + audit["unique_sparse_operator_bytes"]
        + audit["candidate_operators"] * OPERATOR_METADATA_BYTES
    )
    capsule_payloads = []
    for order, capsule in enumerate(capsules):
        records = grouped[order]
        packet_bytes = 4 + sum(
            PACKET_METADATA_BYTES + 48 * record["dimension"] for record in records
        )
        state_bytes = 8 + STATE_COORDINATES_PER_CAPSULE * 8
        payload = state_bytes + packet_bytes + CAPSULE_TRAILER_BYTES
        capsule_payloads.append(payload)

    candidate_container_bytes = (
        FIXED_HEADER_BYTES
        + HASH_TABLE_BYTES
        + len(capsules) * CAPSULE_DIRECTORY_BYTES
        + operator_table_bytes
        + sum(capsule_payloads)
        + 32
    )
    oracle_payload_bytes = summary["fp64_coordinate_denominator"] * 8
    frames = math.ceil(summary["fp64_coordinate_denominator"] / CHUNK_COORDINATES)
    frame_manifest_bytes = frames * FRAME_MANIFEST_BYTES
    preserved_bytes = (
        candidate_container_bytes
        + oracle_payload_bytes
        + frame_manifest_bytes
        + EVIDENCE_RESERVE_BYTES
    )
    peak_compare_buffers = 2 * CHUNK_BYTES
    storage_caps_satisfied = (
        max(max(capsule_payloads), CHUNK_BYTES)
        <= N128_RETAINED_CAPS["per_buffer_bytes"]
        and preserved_bytes
        <= N128_RETAINED_CAPS["cumulative_preserved_bytes"]
        and preserved_bytes <= N128_RETAINED_CAPS["canonical_archive_bytes"]
    )
    if not storage_caps_satisfied:
        raise ValueError("stream storage plan exceeds retained caps")

    return {
        "schema": "hcsn-n256-streaming-fullstate-static-plan-v1",
        "status": "PASS_STREAM_STORAGE_HOLD_DYNAMIC",
        "admission": "HOLD_NO_NUMERICAL_EXECUTION",
        "all_closed": False,
        "source_dependency_commit": SOURCE_COMMIT,
        "roster_identity": ROSTER_IDENTITY,
        "input_bundle_sha256": INPUT_BUNDLE_IDENTITY,
        "capsules": len(capsules),
        "packet_tuples": len(packets),
        "conceptual_fp64_coordinates": summary["fp64_coordinate_denominator"],
        "conceptual_coordinate_denominator_unchanged": True,
        "conceptual_dual_dense_bytes": audit[
            "conceptual_candidate_and_dense_oracle_bytes"
        ],
        "candidate_structured": {
            "state_coordinates": len(capsules) * STATE_COORDINATES_PER_CAPSULE,
            "packet_vector_coordinates": packet_vector_coordinates,
            "packet_dimension_sum": packet_dimensions,
            "unique_operator_bytes_with_metadata": operator_table_bytes,
            "container_bytes": candidate_container_bytes,
            "largest_capsule_payload_bytes": max(capsule_payloads),
        },
        "oracle_stream": {
            "payload_bytes": oracle_payload_bytes,
            "chunk_coordinates": CHUNK_COORDINATES,
            "chunk_bytes": CHUNK_BYTES,
            "frames": frames,
            "manifest_bytes": frame_manifest_bytes,
            "iteration_order": "capsule/state/packet/alpha/generator-row-major/output",
            "candidate_reconstruction": "implicit-zero expansion from canonical CSR",
        },
        "preservation": {
            "evidence_reserve_bytes": EVIDENCE_RESERVE_BYTES,
            "total_bytes": preserved_bytes,
            "peak_compare_buffers_bytes": peak_compare_buffers,
            "retained_caps": N128_RETAINED_CAPS,
            "storage_caps_satisfied": storage_caps_satisfied,
        },
        "unclosed": [
            "N256 numerical candidate implementation",
            "independent numerical oracle implementation",
            "expm workspace and actual RSS profile",
            "canonical serializer and cold-loader execution",
            "host and ancestor-cgroup allocation",
            "concurrency and calendar reservation",
            "warm/cold byte equality on actual N256 state",
        ],
        "nonclaims": [
            "dynamic resource safety",
            "full-state numerical qualification",
            "historical N256 recovery",
            "third or later cycles",
            "continuum or rare-tail qualification",
            "Torch, optimizer, training, fullnetwork, or task benefit",
            "production adoption",
        ],
        "execution_counts": {
            "dynamic_runs": 0,
            "matrix_exponentials": 0,
            "oracle_numeric_calls": 0,
            "serializer_numeric_calls": 0,
            "torch_calls": 0,
            "optimizer_steps": 0,
            "training_runs": 0,
        },
        "largegrid_qualification": False,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--roster", required=True)
    parser.add_argument("--engineering-audit", required=True)
    parser.add_argument("--output")
    args = parser.parse_args()
    result = compile_plan(args.roster, args.engineering_audit)
    payload = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(payload)
    print(payload, end="")


if __name__ == "__main__":
    main()
