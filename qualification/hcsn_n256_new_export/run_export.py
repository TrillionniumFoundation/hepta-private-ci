"""Create one new, source-bound N256 migration export and no dynamics.

This is not a recovery of historical N256 bytes.  It maps the published
visit897 source law once through the already-published graded migration code.
It does not import the DDE/model modules and executes no flow, exponential,
backward pass, optimizer, or training operation.
"""

import argparse
import base64
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import resource
import sys
import time

import numpy as np


IDENTITY = "hcsn-n256-new-export-20261112-c06d-attempt001"
BASE_COMMIT = "0296bce6a8e2ad0998f7ad67143005b109f857ad"
EXPECTED = {
    "selected_law": "7a4b7485bf224b5e343f2c17fccf4ea7ca2dfdd06121810d16c503134f9e92fb",
    "migration": "0e85587433dee39f583fe2c1409e127c75498c96928640890936fadaa12de517",
    "spatial": "ad6b6865374d1f7f6ed493d6485a60be9f39795d1eb232e681f32a020f5b50f0",
    "packet": "0e20e456e2789a824f3cab4d52fd911b8ed446a13abd4a32c9e3e5a8b9adda22",
}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def exact_strings(values):
    return [str(value) for value in values]


def fp64_hex(values):
    array = np.asarray(values, dtype=np.float64)
    return [float(value).hex() for value in array.reshape(-1)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("one-attempt output directory must be absent")

    root = Path(__file__).resolve().parents[2]
    scale = root / "qualification/hcsn_currentstate_scale_spec"
    sources = scale / "sources"
    selected_path = scale / "inputs/SELECTED_ORIGINAL_LAW.json"
    migration_path = sources / "qualification/hcsn_initial_law/migration.py"
    spatial_path = sources / "qualification/hcsn_graded/spatial.py"
    packet_path = sources / "qualification/hcsn_boundary_audit/refractory_transport.py"
    actual = {
        "selected_law": sha(selected_path.read_bytes()),
        "migration": sha(migration_path.read_bytes()),
        "spatial": sha(spatial_path.read_bytes()),
        "packet": sha(packet_path.read_bytes()),
    }
    if actual != EXPECTED:
        raise ValueError(f"source/input binding differs: {actual}")

    sys.path.insert(0, str(sources))
    from qualification.hcsn_graded.spatial import GradedSpatialGenerator
    from qualification.hcsn_initial_law.migration import MigrationBasis, migrate

    selected = json.loads(selected_path.read_text())
    if (
        selected["selection"]
        != {
            "arm": "c0_b1",
            "first_cell_mass": 0.1779507048816143,
            "position": 1,
            "seed": 37,
            "update_index": 24,
            "visit_index": 897,
        }
        or selected["origin_line_sha256"]
        != "fed0107753b35d114c0cb8c3c668fb7f205b78697bb23db98c6e5fafd8a4054b"
    ):
        raise ValueError("published visit897 selection differs")
    probability = selected["state"]["probability"][0]
    content = selected["state"]["content_mass"][0]
    if len(probability) != 25 or len(content) != 25 or any(len(row) != 4 for row in content):
        raise ValueError("published source law shape differs")

    args.output.mkdir(parents=True, exist_ok=False)
    wall_start = time.perf_counter_ns()
    cpu_start = time.process_time_ns()
    physics = selected["parameters"]
    spatial = GradedSpatialGenerator(256, 8.0, physics["mu"], physics["sigma"], 6.0)
    nodes = spatial.nodes
    basis = MigrationBasis(
        4.8,
        16,
        1.0,
        0.2,
        8,
        8.0,
        256,
        actual_nodes=tuple(nodes),
    )
    migrated = migrate(
        basis,
        probability,
        content,
        identity="seed37-c0_b1-step24-pos1-n256-new-export",
    )
    active, marked, phase = migrated.solve_inputs()
    cpu_ns = time.process_time_ns() - cpu_start
    wall_ns = time.perf_counter_ns() - wall_start

    if active.shape != (257,) or marked.shape != (257, 4) or nodes.shape != (257,):
        raise ArithmeticError("N256 mapped shape differs")
    if len(phase) != 8:
        raise ArithmeticError("all eight phase packets must be retained")

    npz_path = args.output / "N256_STATE.npz"
    np.savez_compressed(npz_path, nodes=nodes, active=active, content=marked)
    npz_raw = npz_path.read_bytes()
    (args.output / "N256_STATE.npz.b64").write_text(
        base64.b64encode(npz_raw).decode("ascii") + "\n"
    )
    state = {
        "schema": "hcsn-n256-new-export-state-v1",
        "identity": IDENTITY,
        "intervals": 256,
        "nodes_shape": [257],
        "active_shape": [257],
        "content_shape": [257, 4],
        "dtype": "<f8",
        "nodes_fp64_hex": fp64_hex(nodes),
        "active_probability_fp64_hex": fp64_hex(active),
        "signed_content_fp64_hex_row_major": fp64_hex(marked),
        "active_probability_exact": exact_strings(migrated.active),
        "signed_content_exact": [exact_strings(row) for row in migrated.content],
    }
    state_path = args.output / "N256_STATE.json"
    state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    phases = {
        "schema": "hcsn-n256-new-export-phase-v1",
        "identity": IDENTITY,
        "packet_count": len(phase),
        "packets": [
            {
                "identity": packet.identity,
                "start": str(packet.start),
                "end": str(packet.end),
                "mass": str(packet.mass),
                "signed_content": exact_strings(packet.content),
            }
            for packet in phase
        ],
    }
    phase_path = args.output / "N256_PHASE.json"
    phase_path.write_text(json.dumps(phases, indent=2, sort_keys=True) + "\n")

    reset_distance = math.log(physics["absolute_reset"]) - physics["log_boundary"]
    costs = {
        "schema": "hcsn-n256-new-export-cost-v1",
        "identity": IDENTITY,
        "wall_ns": wall_ns,
        "cpu_ns": cpu_ns,
        "ru_maxrss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "graded_node_coordinates": 257,
        "migration_lift_rows": 17,
        "migration_lift_coordinates": 17 * 257,
        "active_coordinates": 257,
        "signed_content_coordinates": 257 * 4,
        "phase_packets": 8,
        "source_probability_coordinates": 25,
        "source_signed_content_coordinates": 25 * 4,
        "DDE_solves": 0,
        "model_calls": 0,
        "matrix_exponentials": 0,
        "spatial_matrix_constructions": 0,
        "discounted_hit_solves": 0,
        "backward_calls": 0,
        "optimizer_steps": 0,
        "training_steps": 0,
    }
    costs_path = args.output / "COSTS.json"
    costs_path.write_text(json.dumps(costs, indent=2, sort_keys=True) + "\n")
    metadata = {
        "schema": "hcsn-n256-new-export-metadata-v1",
        "identity": IDENTITY,
        "base_commit": BASE_COMMIT,
        "scope": "A new export-only N256 mapping from the published visit897 law. It is not recovered historical N256 bytes and confers no dynamic or large-grid qualification.",
        "historical_N256_export_present": False,
        "new_export": True,
        "global_HOLD": True,
        "all_closed": False,
        "largegrid_qualification": False,
        "dynamic_execution_allowed": False,
        "source_input_sha256": actual,
        "source_visit": {
            "index": 897,
            "seed": 37,
            "arm": "c0_b1",
            "update_index": 24,
            "position": 1,
            "origin_line_sha256": selected["origin_line_sha256"],
            "model_sha256": selected["model_sha256"],
        },
        "physics": physics,
        "reset_distance": reset_distance,
        "upper_semantics": "permanently active nonreturning escape coordinate",
        "npz": {
            "bytes": len(npz_raw),
            "sha256": sha(npz_raw),
            "base64_bytes": (args.output / "N256_STATE.npz.b64").stat().st_size,
            "base64_sha256": sha((args.output / "N256_STATE.npz.b64").read_bytes()),
        },
        "state_json_sha256": sha(state_path.read_bytes()),
        "phase_json_sha256": sha(phase_path.read_bytes()),
        "cost_json_sha256": sha(costs_path.read_bytes()),
        "migration_report": migrated.report,
    }
    metadata_path = args.output / "METADATA.json"
    metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n")
    receipt = {
        "identity": IDENTITY,
        "exit_code": 0,
        "outputs": {
            path.name: {"bytes": path.stat().st_size, "sha256": sha(path.read_bytes())}
            for path in sorted(args.output.iterdir())
            if path.is_file()
        },
        "DDE_model_optimizer_calls": [0, 0, 0],
        "historical_N256_missing_statement_preserved": True,
        "new_export_only": True,
    }
    receipt_path = args.output / "RECEIPT.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "identity": IDENTITY,
                "intervals": 256,
                "nodes": 257,
                "active": 257,
                "signed_content": 1028,
                "phase_packets": 8,
                "npz_sha256": metadata["npz"]["sha256"],
                "DDE_model_optimizer_calls": [0, 0, 0],
                "new_export_only": True,
                "global_HOLD": True,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
