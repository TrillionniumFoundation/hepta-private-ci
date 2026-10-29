"""Bind every completed policy benchmark condition to its actual storage window."""

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build_context():
    directory = ROOT / "policy_benchmark_results"
    matrix_path = directory / "matrix.json"
    matrix = json.loads(matrix_path.read_text())
    protocol_path = ROOT / "policy_benchmark_protocol.json"
    protocol = json.loads(protocol_path.read_text())
    migration_path = ROOT / "workspace_migration.json"
    start_path = directory / "attempts" / "attempt_05_started.json"
    start = json.loads(start_path.read_text())
    prefix_path = directory / "attempts" / "attempt_04_failure.json"
    prefix = json.loads(prefix_path.read_text())
    old_hashes = prefix["completed_result_sha256"]
    if (matrix.get("all_completed") is not True or matrix.get("conditions") != 80
            or len(matrix["receipts"]) != 80 or len(old_hashes) != 64
            or start["completed_results_verified_unchanged"] != 64
            or sha(migration_path) != start["workspace_migration_sha256"]
            or matrix["protocol_sha256"] != start["protocol_sha256"]
            or matrix["protocol_sha256"] != sha(protocol_path)
            or matrix["measurement_cpu"] != 3 or start["cpu_affinity"] != [3]
            or start["minimum_free_bytes"] != 200 * 1024 * 1024):
        raise ValueError("Expected the complete matrix and its recorded 64-condition migration boundary")
    conditions = []
    original_seen = set()
    seen = set()
    for receipt in matrix["receipts"]:
        path = (ROOT / receipt["path"]).resolve()
        if ROOT not in path.parents or sha(path) != receipt["sha256"]:
            raise ValueError("Result path/hash mismatch")
        row = json.loads(path.read_text())
        identity = row["identity"]
        key = (identity["variant"], identity["training_seed"], identity["policy_instances"])
        checkpoint = f"results/{identity['variant']}/seed_{identity['training_seed']}/model.pt"
        if (key in seen or identity != receipt["identity"]
                or row.get("status") != "completed" or identity["cpu_affinity"] != [3]
                or identity["protocol_sha256"] != matrix["protocol_sha256"]
                or identity["checkpoint_sha256"] != protocol["checkpoints_sha256"].get(checkpoint)):
            raise ValueError("Duplicate, incomplete, or inconsistent condition identity")
        seen.add(key)
        relative = str(path.relative_to(directory))
        is_original = relative in old_hashes
        if is_original:
            if receipt["sha256"] != old_hashes[relative]:
                raise ValueError("An original completed window was modified")
            original_seen.add(relative)
        conditions.append({"identity": identity, "result_sha256": receipt["sha256"],
            "storage_window": "original_shared_disk" if is_original else "tmpfs_recovery",
            "completed_at_utc": row["completed_at_utc"],
            "resource_quality": row["resource_quality"]})
    if original_seen != set(old_hashes):
        raise ValueError("An original completed condition is missing")
    groups = []
    for variant in ("rr_full", "ctrnn_state_cpu", "alif", "resource_lif"):
        for count in (64, 256, 1024, 4096):
            rows = [row for row in conditions if row["identity"]["variant"] == variant
                    and row["identity"]["policy_instances"] == count]
            seeds = sorted(row["identity"]["training_seed"] for row in rows)
            if seeds != [101, 211, 307, 401, 503]:
                raise ValueError("Every strategy/scale group must retain all five seeds")
            groups.append({"variant": variant, "policy_instances": count,
                "original_shared_disk_training_seeds": sorted(row["identity"]["training_seed"]
                    for row in rows if row["storage_window"] == "original_shared_disk"),
                "tmpfs_recovery_training_seeds": sorted(row["identity"]["training_seed"]
                    for row in rows if row["storage_window"] == "tmpfs_recovery")})
    new = [row for row in conditions if row["storage_window"] == "tmpfs_recovery"]
    if len(new) != 16 or any(row["identity"]["policy_instances"] != 4096
                            or row["identity"]["training_seed"] == 101 for row in new):
        raise ValueError("The recorded migration resumes precisely the last16 fixed conditions")
    result = {"schema": "rrsnn-v4-policy-benchmark-storage-context-1",
        "source_sha256": sha(__file__), "matrix_sha256": sha(matrix_path),
        "workspace_migration_sha256": sha(migration_path),
        "attempt_04_failure_sha256": sha(prefix_path), "attempt_05_start_sha256": sha(start_path),
        "protocol_sha256": matrix["protocol_sha256"],
        "original_completed_conditions": 64, "tmpfs_completed_conditions": 16,
        "all_original_result_hashes_unchanged": True,
        "same_cpu_affinity": [3], "same_interpreter_path": start["interpreter"],
        "same_guard_threshold_bytes": start["minimum_free_bytes"],
        "source_and_output_storage_environment_changed": True,
        "environment_caveat": "Original conditions used the shared-disk tree in the default sandbox. Remaining conditions used its byte-verified tmpfs recovery tree through the normal require_escalated execution mode. CPU3, interpreter path, source, weights, observations, repeats, timing boundaries, and guard threshold were retained. File I/O is outside the model/full-loop timers, but tmpfs consumes shared cgroup memory and the process/filesystem namespace changed; the storage and shared-host environments must not be described as identical. No completed window was remeasured or replaced.",
        "runtime_identity_scope": "This context manifest directly binds the recorded interpreter path. The coordinator separately audited selected runtime binaries and CPU quota across namespaces; this field is not an exhaustive dependency-identity proof.",
        "groups": groups, "conditions": conditions}
    destination = directory / "storage_context.json"
    encoded = (json.dumps(result, sort_keys=True, indent=2) + "\n").encode()
    if destination.exists():
        if destination.read_bytes() != encoded:
            raise ValueError("Refusing to replace different storage-window evidence")
    else:
        with destination.open("xb") as stream:
            stream.write(encoded)
    return destination


if __name__ == "__main__":
    destination = build_context()
    print(json.dumps({"output": str(destination), "sha256": sha(destination)}))
