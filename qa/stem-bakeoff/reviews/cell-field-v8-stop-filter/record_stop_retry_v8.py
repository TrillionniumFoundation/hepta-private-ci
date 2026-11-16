"""Preserve the disk-full attempt before a complete unchanged infrastructure retry."""

from datetime import datetime, timezone
import gzip
import json
from pathlib import Path
import os
import zipfile

from stop_census_v8 import canonical, digest, read, require, sha


def record(workspace):
    workspace = Path(workspace)
    attempt = workspace/"pft-stop-filter-v8"
    staging = workspace/"pft-development-v8"
    logfile = staging/"stop-run.log"
    freeze_file = staging/"stop-source-freeze.json"
    freeze = read(freeze_file)
    require(freeze["source_commit"] == "bdaed1dc94adc1c52dfbc0ac9a0f1ebc6299f9af"
        and len(freeze["source_hashes"]) == 111, "original111-source publication")
    for name, pin in freeze["source_hashes"].items():
        require(sha(workspace/"hepta-repo-v8/qa/stem-bakeoff"/name) == pin, "no algorithm changes before infrastructure retry")
    require(sha(attempt/"protocol.json") == "6342a84f7582a8bce9334f12500f904f01e64c9f4451cb27b6bc7d3cf5414851"
        and sha(attempt/"source-freeze.json") == sha(freeze_file), "original protocol/source unchanged")
    inventory, invalid = {}, []
    for path in sorted(attempt.rglob("*")):
        if not path.is_file():
            continue
        name = path.relative_to(attempt).as_posix()
        inventory[name] = {"bytes": path.stat().st_size, "sha256": sha(path)}
        try:
            if path.suffix == ".json":
                json.loads(path.read_bytes())
            elif path.name.endswith(".json.gz"):
                json.loads(gzip.decompress(path.read_bytes()))
            elif path.suffix == ".npz":
                with zipfile.ZipFile(path) as stream:
                    require(stream.testzip() is None, "array archive member CRC mismatch")
        except Exception as error:
            invalid.append({"path": name, "error": {"type": type(error).__name__, "message": str(error)}})
    completed, costs, negative = [], {"proposal_cpu_ns": 0, "single_ray_filter_cpu_ns": 0,
        "joint_filter_cpu_ns": 0, "independent_replay_cpu_ns": 0}, []
    for path in sorted(attempt.glob("config*/*/*/case.json")):
        try:
            case = read(path)
        except Exception:
            continue
        completed.append({"slot": case["slot"], "horizon": case["attempted_horizon"],
            "filters": {name: {"status": row["status"], "safe": row["qualified_safe_witness"],
                "audit_error": row["audit_error"]} for name, row in case["filters"].items()}})
        costs["proposal_cpu_ns"] += case["proposal"]["call"]["cpu_ns"]
        costs["independent_replay_cpu_ns"] += case["proposal"]["audit"]["cpu_ns"]
        for name, key in (("single_ray_v7", "single_ray_filter_cpu_ns"), ("joint_actual_old_v8", "joint_filter_cpu_ns")):
            costs[key] += case["filters"][name]["call"]["cpu_ns"]
            costs["independent_replay_cpu_ns"] += case["filters"][name]["audit"]["cpu_ns"]
        if case["filters"]["single_ray_v7"]["qualified_safe_witness"] and not case["filters"]["joint_actual_old_v8"]["qualified_safe_witness"]:
            negative.append(case["slot"])
    require(len(completed) == 9 and len(negative) == 2
        and "OSError: [Errno 28] No space left on device" in logfile.read_text(), "observed infrastructure failure and retained negative outcomes")
    result = {"schema": "hepta.cell-field-stop-attempt-interruption.v8", "cause": "infrastructure_disk_full",
        "attempt_directory": str(attempt), "completed_case_files": 9, "completed_filter_slots": 18,
        "attempted_next_origin": "config00/v5-dbpedia-seed7-gated/loss2_h8",
        "next_case_file_bytes": (attempt/"config00/v5-dbpedia-seed7-gated/loss2_h8/case.json").stat().st_size,
        "process_exit_code": 1, "log_sha256": sha(logfile), "log_bytes": logfile.stat().st_size,
        "source_freeze_sha256": sha(freeze_file), "protocol_sha256": freeze["protocol_sha256"],
        "files": inventory, "file_count": len(inventory), "retained_bytes": sum(v["bytes"] for v in inventory.values()),
        "incomplete_or_invalid_files": invalid, "completed": completed,
        "retained_single_ray_safe_joint_not_safe_origins": negative,
        "recoverable_recorded_costs": costs,
        "cost_scope": "sum of recovered complete-case call and replay timing records; interrupted in-flight/preparation/serialization CPU is unrecorded, so total attempt CPU is unknown and these are lower bounds",
        "whole_attempt_cpu_ns": None, "scientific_acceptance": False,
        "original_attempt_edited_or_replaced": False, "recorder_sha256": sha(__file__)}
    target = staging/"stop-attempt1-interruption.json"
    require(not target.exists(), "new failure inventory outside original output")
    target.write_bytes(canonical(result)+b"\n")
    stat = os.statvfs(workspace)
    declaration = {"schema": "hepta.cell-field-stop-infrastructure-retry.v8", "declared_at": datetime.now(timezone.utc).isoformat(),
        "cause": "infrastructure_disk_full", "previous_attempt_inventory_sha256": sha(target),
        "previous_attempt_log_sha256": sha(logfile), "source_freeze_sha256": sha(freeze_file),
        "source_commit": freeze["source_commit"], "source_closure_sha256": digest(freeze["source_hashes"]),
        "protocol_sha256": freeze["protocol_sha256"], "origins_manifest_sha256": sha(staging/"stop-origins/manifest.json"),
        "planning_only_index_sha256": sha(workspace/"pft-development-v7b/planning-only/index.json"),
        "retry_output_directory": str(workspace/"pft-stop-filter-v8-r2"), "registered_origins": 98,
        "registered_filter_slots": 196, "retry_all_origins_same_order": True,
        "solver_configuration_or_input_changes": False, "outcome_selected_subset": False,
        "runtime": {"PYTHONDONTWRITEBYTECODE": "1", "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1"},
        "actual_free_bytes_at_declaration": stat.f_bfree*stat.f_frsize,
        "cost_accounting": "retain attempt1 recoverable cost lower bounds separately and add to attempt2 measured totals; never claim missing attempt1 total CPU is known",
        "primary_complete_attempt": "r2 only if complete sealed196-slot census; attempt1 remains published failure evidence",
        "scientific_acceptance": False}
    retry = staging/"stop-retry-declaration.json"
    require(not retry.exists() and not (workspace/"pft-stop-filter-v8-r2").exists(), "pre-execution retry declaration")
    retry.write_bytes(canonical(declaration)+b"\n")
    return {"inventory_sha256": sha(target), "retry_declaration_sha256": sha(retry), "costs": costs,
        "actual_free_bytes": declaration["actual_free_bytes_at_declaration"]}


if __name__ == "__main__":
    print(canonical(record(Path(__file__).resolve().parent.parent)).decode())
