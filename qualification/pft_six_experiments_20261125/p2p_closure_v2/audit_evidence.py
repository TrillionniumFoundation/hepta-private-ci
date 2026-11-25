#!/usr/bin/env python3
"""Read frozen host archives and independently audit peer equality and ridge solves."""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import tarfile
import time
import zlib

import numpy as np

from sufficient import MODEL_SHA, digest, encode, load_model, sha


def finite(value):
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Nonfinite JSON evidence")
    if isinstance(value, dict):
        for item in value.values():
            finite(item)
    if isinstance(value, list):
        for item in value:
            finite(item)


def packet_counter(result, direction):
    return Counter((p["sha256"], p["bytes"], p["kind"]) for p in result["metrics"]["packets"] if p["direction"] == direction)


def read_archives(folder, host):
    files, archives = {}, []
    for path in sorted(folder.glob(f"pft2_ssh_{host}_*.tar.xz")):
        raw = path.read_bytes()
        if len(raw) >= 512000:
            raise ValueError("Oversized publication blob")
        archives.append({"name": path.name, "sha256": sha(raw), "bytes": len(raw)})
        with tarfile.open(path, "r:xz") as archive:
            for member in archive.getmembers():
                if not member.isfile() or ".." in Path(member.name).parts or Path(member.name).is_absolute():
                    raise ValueError("Invalid bounded archive member")
                content = archive.extractfile(member).read()
                if member.name in files:
                    raise ValueError("Repeated archive member")
                files[member.name] = content
    manifest = json.loads((folder / f"{host}_manifest.json").read_text())
    for name, identity in manifest["files"].items():
        if name not in files or sha(files[name]) != identity["sha256"] or len(files[name]) != identity["bytes"]:
            raise ValueError("Host manifest differs from archived bytes")
    return files, archives


def load_case(files, round_id):
    result_raw = files[round_id + "/result.json"]
    result = json.loads(result_raw)
    terminal = json.loads(files[round_id + "/terminal_receipt.json"])
    if terminal["result_sha256"] != sha(result_raw) or terminal["result_bytes"] != len(result_raw):
        raise ValueError("Terminal receipt is not bound to the complete result")
    stats_raw = files[round_id + "/stats.json.zlib"]
    if result["stats_sha256"] != sha(stats_raw) or result["stats_bytes"] != len(stats_raw):
        raise ValueError("Statistics identity mismatch")
    stats = json.loads(zlib.decompress(stats_raw))
    finite(result)
    finite(stats)
    return result, stats, terminal


def audit_case(round_id, first, second, frozen_model):
    a, sa, ta = load_case(first, round_id)
    b, sb, tb = load_case(second, round_id)
    ordered = sorted(sa["messages"], key=lambda m: m["id"])
    other = sorted(sb["messages"], key=lambda m: m["id"])
    identity_equal = ordered == other and a["header"] == b["header"] == sa["header"] == sb["header"]
    if not identity_equal or len(ordered) != 8:
        raise ValueError("Peers do not retain the same complete statistics")
    n, seed = a["size"], a["seed"]
    gram = sum(np.asarray(message["gram"]) for message in ordered)
    moment = sum(np.asarray(message["moment"]) for message in ordered)
    ridge = sa["artifact"]["objective"]["ridge"]
    reference = np.linalg.solve(gram + ridge * np.eye(n), moment)
    action = np.asarray(a["solution"]["action"])
    error = float(np.linalg.norm(action - reference) / max(np.linalg.norm(reference), 1e-30))
    parent, truth = frozen_model.model(n, seed)
    average, sample_count = np.zeros(n), sum(m["count"] for m in ordered)
    for host in ("ai395", "pocket4"):
        local = [m for m in ordered if m["node"] == host]
        g = sum(np.asarray(m["gram"]) for m in local)
        h = sum(np.asarray(m["moment"]) for m in local)
        average += sum(m["count"] for m in local) / sample_count * np.linalg.solve(g + ridge * np.eye(n), h)
    heldout = np.random.default_rng(9000000 + seed + n).standard_normal((2048, n))
    targets = heldout @ np.asarray(truth)
    pooled_rmse = float(np.sqrt(np.mean((heldout @ (np.asarray(parent) + action) - targets) ** 2)))
    average_rmse = float(np.sqrt(np.mean((heldout @ (np.asarray(parent) + average) - targets) ** 2)))
    crash = json.loads(second[round_id + "/crash.json"])
    compressed = second[round_id + "/crash_checkpoint.json.zlib"]
    checkpoint = zlib.decompress(compressed)
    saved = json.loads(checkpoint)
    checks = {"same_complete_stats": identity_equal, "raw_candidate_equal": a["solution"]["candidate_sha256"] == b["solution"]["candidate_sha256"],
              "raw_candidate_hash_valid": digest(a["solution"]["candidate"]) == a["solution"]["candidate_sha256"],
              "central_ridge_relative_error_under_1e_10": error < 1e-10,
              "ai395_to_pocket4_bytes_equal": a["metrics"]["tx_bytes"] == b["metrics"]["rx_bytes"],
              "pocket4_to_ai395_bytes_equal": b["metrics"]["tx_bytes"] == a["metrics"]["rx_bytes"],
              "all_frame_hashes_equal_ab": packet_counter(a, "tx") == packet_counter(b, "rx"),
              "all_frame_hashes_equal_ba": packet_counter(b, "tx") == packet_counter(a, "rx"),
              "actual_ssh_exit_codes_17_then_0": [v["ssh_exit_code"] for v in a["ssh_attempts"]] == [17, 0],
              "direct_usb4_on_both_sessions": all(v["transport"]["selected_transport"] == "usb4" and v["transport"]["endpoint_verified"] for v in a["ssh_attempts"]),
              "new_pid_and_five_restored": b["restored_contributions"] == 5 and b["pid"] != crash["pid"] == b["previous_pid"],
              "crash_checkpoint_archive_valid": sha(compressed) == crash["checkpoint_archive_sha256"],
              "exact_checkpoint_restored": sha(checkpoint) == crash["ledger_sha256"] == b["restore_ledger_sha256"],
              "checkpoint_envelope_valid": digest(saved["body"]) == saved["sha256"] and len(saved["body"]["messages"]) == 5 and not saved["body"]["frozen"],
              "same_protocol_sources": a["sources"] == b["sources"],
              "fixed_model_source": a["model_source_sha256"] == b["model_source_sha256"] == MODEL_SHA,
              "out_of_order_and_duplicate_idempotence": a["metrics"]["statuses"].get("duplicate") == 4 and b["metrics"]["statuses"].get("duplicate") == 5,
              "stale_parent_rejected": a["metrics"]["statuses"].get("rejected_version") == 1 and b["metrics"]["statuses"].get("rejected_version") == 2}
    if not all(checks.values()):
        raise ValueError("Failed frozen-evidence audit: " + str(checks))
    phases = {}
    for result, terminal in ((a, ta), (b, tb)):
        phases[result["node"]] = {k: v for k, v in result["metrics"].items() if k.endswith("_seconds")}
        phases[result["node"]].update({"process_wall_seconds": result["process_wall_seconds"],
                                       "wall_to_result_readback_seconds": terminal["process_wall_to_result_readback_seconds"],
                                       "result_write_seconds": terminal["result_write_seconds"],
                                       "result_readback_seconds": terminal["result_readback_seconds"]})
    return {"round_id": round_id, "size": n, "seed": seed, "checks": checks, "candidate_sha256": a["solution"]["candidate_sha256"],
            "aggregate_sha256": a["solution"]["aggregate_sha256"], "numpy_relative_action_error": error,
            "weighted_local_average_relative_action_error": float(np.linalg.norm(average - reference) / max(np.linalg.norm(reference), 1e-30)),
            "independent_heldout_rmse_pooled": pooled_rmse, "independent_heldout_rmse_average": average_rmse,
            "heldout_count": len(heldout), "heldout_source": "independent PCG64 isotropic inputs and noiseless known truth; never used in fitting",
            "ai395_to_pocket4_application_bytes": a["metrics"]["tx_bytes"], "pocket4_to_ai395_application_bytes": b["metrics"]["tx_bytes"],
            "node_phases": phases, "case_wall_before_final_archive_seconds": a["case_wall_seconds"],
            "remote_recovery_gap_seconds": a["remote_recovery_gap_seconds"], "crashed_remote_pid": crash["pid"],
            "resumed_remote_pid": b["pid"], "ai395_pid": a["pid"], "sources": a["sources"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archives", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--model", default=str(Path(__file__).resolve().parents[1] / "multihost.py"))
    args = parser.parse_args()
    start = time.monotonic()
    a, archives_a = read_archives(Path(args.archives), "ai395")
    b, archives_b = read_archives(Path(args.archives), "pocket4")
    model = load_model(args.model)
    names = sorted({name.split("/")[0] for name in a if name.endswith("/result.json")})
    expected = {f"pft2-usb4-v2-n{n}-s{s}" for n in (8, 16, 32, 64) for s in (271801, 271802, 271803)}
    if set(names) != expected:
        raise ValueError("The full twelve-case frozen experiment is required")
    records = [audit_case(name, a, b, model) for name in names]
    supervisor = json.loads(a["supervisor_result.json"])
    report = {"record_kind": "pft2_direct_physical_peer_ssh_audit", "schema_version": 1,
              "audit_source_sha256": sha(Path(__file__).read_bytes()), "numpy_version": np.__version__,
              "experiment": "new synthetic transport qualification, separate from E1-E6 training budgets",
              "transport": "two physical hosts, existing strict SSH over directly selected USB4; no controller data relay",
              "archives": archives_a + archives_b, "records": records, "complete_cases": len(records),
              "all_checks_passed": all(all(r["checks"].values()) for r in records),
              "max_numpy_relative_action_error": max(r["numpy_relative_action_error"] for r in records),
              "weighted_average_worse_heldout_cases": sum(r["independent_heldout_rmse_average"] > r["independent_heldout_rmse_pooled"] for r in records),
              "total_application_bytes_both_directions": sum(r["ai395_to_pocket4_application_bytes"] + r["pocket4_to_ai395_application_bytes"] for r in records),
              "supervisor_wall_seconds": supervisor["wall_seconds"], "independent_audit_seconds": time.monotonic() - start,
              "limitations": ["This is a shared-basis linear ridge subproblem, not a full nonlinear parameter-field inverse.",
                              "Application frame bytes exclude SSH encryption, TCP/IP headers, and retransmissions.",
                              "Node wall intervals overlap; pipe read waits contain peer compute and I/O. Stage counters cannot be summed across hosts.",
                              "The resumed node wall covers its second process. The launcher/supervisor wall includes both processes and the fault gap.",
                              "Crash-time final fsync and unclassified Python/protocol overhead are bounded by complete wall time, not exhaustively assigned to phase counters.",
                              "Authentication uses existing SSH identities; no Byzantine data truth, privacy, or permissionless membership claim is tested."]}
    finite(report)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    raw = encode(report) + b"\n"
    output.write_bytes(raw)
    print(json.dumps({k: report[k] for k in ("complete_cases", "all_checks_passed", "max_numpy_relative_action_error", "weighted_average_worse_heldout_cases", "total_application_bytes_both_directions", "supervisor_wall_seconds")}))
    print(json.dumps({"result_sha256": sha(raw), "result_bytes": len(raw)}))


if __name__ == "__main__":
    main()
