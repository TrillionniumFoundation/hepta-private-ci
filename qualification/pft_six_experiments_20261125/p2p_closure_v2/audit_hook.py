#!/usr/bin/env python3
"""Audit frozen real-provider peer traffic and local artifacts without opening tests."""
import argparse
import io
import json
import math
from pathlib import Path
import tarfile
import time
import zlib

import numpy as np

from audit_evidence import finite, load_case, packet_counter
from sufficient import digest, encode, sha

EXPECTED_SOURCES = {
    "sufficient.py": "aa00a413a973c93cb74761c2918c3618100909d05870b062d5eb0507cfe38553",
    "stream_peer.py": "0a1a6a8721197ab756cd7a40f460723832bc98cbf56eb2cd06a5442d0872c638",
    "ssh_runner.py": "e860287e58562531566d3c4ff90f71beba5df9a1d46cd19862b9d2939d337f7f",
}


def read_host(folder, node):
    manifest = json.loads((folder / f"{node}_manifest.json").read_text())
    files = {}
    for archive in manifest["archives"]:
        pieces = []
        for part in archive["parts"]:
            raw = (folder / part["name"]).read_bytes()
            if len(raw) != part["bytes"] or sha(raw) != part["sha256"] or len(raw) >= 512000:
                raise ValueError("Archive part identity or size mismatch")
            pieces.append(raw)
        raw = b"".join(pieces)
        if len(raw) != archive["bytes"] or sha(raw) != archive["sha256"]:
            raise ValueError("Logical archive identity mismatch")
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:xz") as stream:
            for member in stream.getmembers():
                if not member.isfile() or member.name in files or Path(member.name).is_absolute() or ".." in Path(member.name).parts:
                    raise ValueError("Invalid archive member")
                files[member.name] = stream.extractfile(member).read()
    if set(files) != set(manifest["files"]):
        raise ValueError("Host archive roster mismatch")
    for name, expected in manifest["files"].items():
        if sha(files[name]) != expected["sha256"] or len(files[name]) != expected["bytes"]:
            raise ValueError("Host file identity mismatch")
    return files, manifest


def original_local_artifact(stats, node):
    fields = ("batch", "count", "data_hash", "gram", "moment")
    local = sorted((m for m in stats["messages"] if m["node"] == node), key=lambda m: m["batch"])
    return {**stats["artifact"], "batches": [{k: row[k] for k in fields} for row in local]}


def inspect_case(name, first, second, providers, protocol):
    a, sa, ta = load_case(first, name)
    b, sb, tb = load_case(second, name)
    n, seed = a["size"], a["seed"]
    all_messages = sorted(sa["messages"], key=lambda m: m["id"])
    other = sorted(sb["messages"], key=lambda m: m["id"])
    gram = sum(np.asarray(m["gram"]) for m in all_messages)
    moment = sum(np.asarray(m["moment"]) for m in all_messages)
    operator = gram + protocol["objective"]["ridge"] * np.eye(n)
    start = time.perf_counter()
    reference = np.linalg.solve(operator, moment)
    reference_seconds = time.perf_counter() - start
    actual = np.asarray(a["solution"]["action"])
    relative = float(np.linalg.norm(actual - reference) / max(1.0, np.linalg.norm(reference)))
    residual = float(np.linalg.norm(operator @ actual - moment) / max(1.0, np.linalg.norm(moment)))
    crash = json.loads(second[name + "/crash.json"])
    compressed = second[name + "/crash_checkpoint.json.zlib"]
    checkpoint = zlib.decompress(compressed)
    saved = json.loads(checkpoint)
    vectors_valid = all(isinstance(values, list) and len(values) == n
                        and all(type(x) in (int, float) and math.isfinite(x) for x in values)
                        for result, stats in ((a, sa), (b, sb))
                        for values in (result["solution"]["candidate"], result["solution"]["action"], stats["artifact"]["parent"]))
    checks = {"same_complete_statistics": all_messages == other and len(all_messages) == 8,
              "both_node_identity_dimension_seed": a["node"] == "ai395" and b["node"] == "pocket4"
                    and b["size"] == n and b["seed"] == seed and a["round_id"] == b["round_id"] == name,
              "both_vector_shapes_and_finite_types": vectors_valid,
              "aggregate_content_hash": digest([gram.tolist(), moment.tolist()]) == a["solution"]["aggregate_sha256"] == b["solution"]["aggregate_sha256"],
              "same_headers": a["header"] == b["header"] == sa["header"] == sb["header"],
              "same_fixed_protocol_source": a["sources"] == b["sources"] == EXPECTED_SOURCES,
              "same_raw_candidate": a["solution"]["candidate_sha256"] == b["solution"]["candidate_sha256"],
              "ai395_candidate_content_hash": digest(a["solution"]["candidate"]) == a["solution"]["candidate_sha256"],
              "pocket4_candidate_content_hash": digest(b["solution"]["candidate"]) == b["solution"]["candidate_sha256"],
              "candidate_values_equal": a["solution"]["candidate"] == b["solution"]["candidate"],
              "action_values_equal": a["solution"]["action"] == b["solution"]["action"],
              "ai395_candidate_is_parent_plus_action": a["solution"]["candidate"] == [p + x for p, x in zip(sa["artifact"]["parent"], a["solution"]["action"])],
              "pocket4_candidate_is_parent_plus_action": b["solution"]["candidate"] == [p + x for p, x in zip(sb["artifact"]["parent"], b["solution"]["action"])],
              "central_ridge_solution": relative <= protocol["relative_central_tolerance"],
              "relative_normal_residual": residual <= protocol["relative_normal_residual_tolerance"],
              "frame_hashes_ai395_to_pocket4": packet_counter(a, "tx") == packet_counter(b, "rx"),
              "frame_hashes_pocket4_to_ai395": packet_counter(b, "tx") == packet_counter(a, "rx"),
              "application_byte_conservation": a["metrics"]["tx_bytes"] == b["metrics"]["rx_bytes"] and b["metrics"]["tx_bytes"] == a["metrics"]["rx_bytes"],
              "actual_exit_17_then_0": [v["ssh_exit_code"] for v in a["ssh_attempts"]] == [17, 0],
              "direct_usb4_sessions": all(v["transport"]["endpoint_verified"] and v["transport"]["selected_transport"] == "usb4" for v in a["ssh_attempts"]),
              "crash_checkpoint_identity": sha(compressed) == crash["checkpoint_archive_sha256"] and sha(checkpoint) == crash["ledger_sha256"] == b["restore_ledger_sha256"],
              "crash_checkpoint_content": digest(saved["body"]) == saved["sha256"] and len(saved["body"]["messages"]) == 5 and not saved["body"]["frozen"],
              "new_process_restored_five": b["restored_contributions"] == 5 and b["pid"] != crash["pid"] == b["previous_pid"],
              "duplicates_idempotent": a["metrics"]["statuses"].get("duplicate") == 4 and b["metrics"]["statuses"].get("duplicate") == 5,
              "stale_parent_rejected": a["metrics"]["statuses"].get("rejected_version") == 1 and b["metrics"]["statuses"].get("rejected_version") == 2}
    artifact_records, timing = [], {}
    for node, stats, result, terminal in (("ai395", sa, a, ta), ("pocket4", sb, b, tb)):
        artifact = original_local_artifact(stats, node)
        filename = f"stats_d{n}_s{seed}.json"
        expected = next(row for row in providers[node]["records"] if row["path"] == filename)
        raw = encode(artifact) + b"\n"
        checks[node + "_original_local_artifact"] = sha(raw) == expected["sha256"] and len(raw) == expected["bytes"]
        checks[node + "_physical_provider_identity"] = (artifact["feature_provider_sha256"] == digest(protocol["sources"])
                and artifact["shared_capsule_sha256"] == protocol["shared_capsule_sha256"]
                and artifact["objective"] == protocol["objective"]
                and artifact["evidence"]["kind"] == "real_SmallHCSN_frozen_physics_readout_update"
                and artifact["evidence"]["local_generation"] and not artifact["evidence"]["test_created"]
                and artifact["evidence"]["physical_parameters_updated"] == 0)
        header = stats["header"]
        checks[node + "_actual_boundary_binding"] = (header["parent"] == digest(artifact["parent"])
                and header["coordinates"] == artifact["coordinates_sha256"]
                and header["objective"] == digest([artifact["objective"], artifact["feature_provider_sha256"], artifact["shared_capsule_sha256"]])
                and header["sources"] == digest(EXPECTED_SOURCES))
        artifact_records.append({"node": node, "artifact_sha256": sha(raw), "artifact_bytes": len(raw),
                                 "basis_file_sha256": artifact["evidence"]["basis_file_sha256"],
                                 "physical_state_sha256": artifact["evidence"]["physical_state_sha256"],
                                 "neuron_width": artifact["evidence"]["neuron_width"]})
        timing[node] = {k: v for k, v in result["metrics"].items() if k.endswith("_seconds")}
        timing[node].update({"protocol_wall_to_result_readback_seconds": terminal["process_wall_to_result_readback_seconds"],
                             "provider_wall_before_serialization_seconds": artifact["evidence"]["provider_wall_s_before_serialization"],
                             "model_setup_seconds": artifact["evidence"]["model_setup_wall_s"]})
    checks["same_shared_physical_parent"] = artifact_records[0]["physical_state_sha256"] == artifact_records[1]["physical_state_sha256"]
    checks["same_serialized_coordinate_basis"] = artifact_records[0]["basis_file_sha256"] == artifact_records[1]["basis_file_sha256"]
    if not all(checks.values()):
        raise ValueError("Failed real-provider peer audit: " + str(checks))
    return {"round_id": name, "dimension": n, "seed": seed, "checks": checks,
            "candidate_sha256": a["solution"]["candidate_sha256"], "result_sha256_ai395": sha(first[name + "/result.json"]),
            "result_sha256_pocket4": sha(second[name + "/result.json"]), "local_artifacts": artifact_records,
            "central_relative_action_error": relative, "relative_normal_residual": residual,
            "independent_central_solve_seconds": reference_seconds,
            "application_bytes_both_directions": a["metrics"]["tx_bytes"] + b["metrics"]["tx_bytes"],
            "node_timing": timing, "test_generated_or_read_by_this_audit": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archives", required=True)
    parser.add_argument("--protocol", required=True)
    parser.add_argument("--provider-manifests", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    start = time.monotonic()
    protocol_bytes = Path(args.protocol).read_bytes()
    protocol = json.loads(protocol_bytes)
    first, ma = read_host(Path(args.archives), "ai395")
    second, mb = read_host(Path(args.archives), "pocket4")
    providers = {node: json.loads((Path(args.provider_manifests) / f"{node}_provider_manifest.json").read_text()) for node in ("ai395", "pocket4")}
    expected = {f"pft2-hcsn-usb4-v2-n{5 * (n // 2) + 1}-s{s}" for n in protocol["widths"] for s in protocol["seeds"]}
    observed = {name.split("/")[0] for name in first if name.endswith("/result.json")}
    other_observed = {name.split("/")[0] for name in second if name.endswith("/result.json")}
    if observed != expected or other_observed != expected:
        raise ValueError("Incomplete real-provider case roster")
    records = [inspect_case(name, first, second, providers, protocol) for name in sorted(expected)]
    supervisor = json.loads(first["supervisor_result.json"])
    report = {"record_kind": "pft_real_hcsn_direct_peer_pretest_audit", "schema_version": 1,
              "audit_source_sha256": sha(Path(__file__).read_bytes()), "protocol_sha256": sha(protocol_bytes),
              "numpy_version": np.__version__, "records": records, "complete_cases": len(records),
              "all_checks_passed": all(all(row["checks"].values()) for row in records),
              "test_generated_or_read": False, "controller_training_data_relay": False,
              "max_central_relative_action_error": max(row["central_relative_action_error"] for row in records),
              "max_relative_normal_residual": max(row["relative_normal_residual"] for row in records),
              "total_application_bytes": sum(row["application_bytes_both_directions"] for row in records),
              "protocol_supervisor_wall_seconds": supervisor["wall_seconds"],
              "provider_wall_seconds_by_host": {node: value["wall_s"] for node, value in providers.items()},
              "archive_manifests": {"ai395": digest(ma), "pocket4": digest(mb)},
              "audit_wall_seconds": time.monotonic() - start,
              "scope": "Actual SmallHCSN features with frozen nonlinear physics; distributed readout update on a new synthetic task. Generalization is evaluated separately only after candidate sealing."}
    finite(report)
    raw = encode(report) + b"\n"
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(raw)
    print(json.dumps({"cases": len(records), "all_checks_passed": report["all_checks_passed"],
                      "max_central_relative_action_error": report["max_central_relative_action_error"],
                      "result_sha256": sha(raw), "bytes": len(raw)}))


if __name__ == "__main__":
    main()
