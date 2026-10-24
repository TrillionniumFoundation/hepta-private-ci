"""Freeze original warmup exports and bounded native-process graph dispatch requests.

This module has no transport implementation, training, task scorer, or gold reader.
The existing root process owner executes the generated native requests and retains
its real dispatch/read/status receipts. No SSH, sockets, daemon, or serial fallback.
"""

import argparse
import hashlib
import io
import json
from pathlib import Path
import sys
import time
import zipfile

import numpy as np

from cell_graph_worker import HEAD_IDS, MAX_INPUT, canonical, sha, strict_json, tensor, array

RETENTION_PROTOCOL = "5f963295e4e49a64cde085aa2a4dde92c291df3b0450d768f986264e482d3832"
COHORT_RECEIPT = "7af61dfa851583d6d31c0163b5d9453841e21bef106058206731870d706364df"
SCHEMA = "hepta.fixed-cell-graph.benchmark.v1"
BLOCK_ORDERS = (("A", "B", "C"), ("A", "C", "B"), ("B", "A", "C"),
                ("B", "C", "A"), ("C", "A", "B"), ("C", "B", "A"))
SHARDS = ((0, 3, 4), (1, 2, 5))


def write(path, value):
    data = canonical(value) + b"\n"
    with Path(path).open("xb") as stream:
        stream.write(data)
    return sha(data)


def safe_file(path, maximum):
    path = Path(path)
    if any(parent.is_symlink() for parent in (path, *path.parents)) or not path.is_file() or path.stat().st_size > maximum:
        raise ValueError("bounded regular source file without symlink parents required")
    return path.read_bytes()


def deny_outcomes(event, args):
    if event == "open" and args and isinstance(args[0], (str, bytes)):
        path = Path(args[0].decode() if isinstance(args[0], bytes) else args[0])
        if path.name in ("final_labels.json", "frozen_predictions.npz", "summary.json", "score-v1.json") or "conditions" in path.parts:
            raise RuntimeError("graph export cannot inspect outcomes, final labels or controlled heads")


def export_graph(run, protocol, output, *, expected_protocol_sha256):
    """Read exactly original six warmup states and common projected features."""
    from cell_field_state import CellTrainingState
    from cell_learning_models import canonical as original_canonical
    began, cpu = time.perf_counter_ns(), time.process_time_ns()
    run, output = Path(run), Path(output)
    plan = checked_protocol(protocol, expected_protocol_sha256)
    original = safe_file(run / "protocol.json", 65536)
    if sha(original) != RETENTION_PROTOCOL:
        raise ValueError("original frozen retention protocol changed")
    retention = strict_json(original)
    source_digests = {name: sha(safe_file(Path(__file__).with_name(name), 131072))
        for name in ("cell_field_state.py", "cell_learning_models.py", "cell_learning_metrics.py")}
    if any(retention["source_code_sha256"][name] != digest for name, digest in source_digests.items()):
        raise ValueError("original export implementation differs")
    packed = safe_file(run / "projected_features.npz", 131072)
    with zipfile.ZipFile(io.BytesIO(packed)) as archive:
        if len(archive.infolist()) != 2 or sum(v.file_size for v in archive.infolist()) > 131072:
            raise ValueError("bounded original projected feature archive required")
    with np.load(io.BytesIO(packed), allow_pickle=False) as arrays:
        if set(arrays.files) != {"features", "projection"}:
            raise ValueError("exact projected feature members required")
        features, projection = arrays["features"].copy(), arrays["projection"].copy()
    if (features.shape != (480, 8) or features.dtype != np.float64 or not np.isfinite(features).all()
            or projection.shape != (384, 8) or projection.dtype != np.float64 or not np.isfinite(projection).all()):
        raise ValueError("exact frozen480x8 projection required")
    files = {"protocol.json": sha(original), "projected_features.npz": sha(packed)}
    heads, original_states, identities = [], [], []
    for index, name in enumerate(HEAD_IDS):
        folder = run / "initial" / name
        metadata = safe_file(folder / "manifest.json", 65536)
        payload = safe_file(folder / "state.npz", 131072)
        manifest = strict_json(metadata)
        bindings = manifest["bindings"]
        seed, mode = (7, 17, 29)[index // 2], ("linear", "gated")[index % 2]
        if (bindings.get("protocol_sha256") != RETENTION_PROTOCOL
                or bindings.get("cohort_receipt_sha256") != COHORT_RECEIPT
                or bindings.get("seed") != seed or bindings.get("head") != mode
                or bindings.get("source_code_sha256") != retention["source_code_sha256"]
                or manifest.get("step_count") != 64 or manifest.get("active_context") != "current_train"
                or manifest.get("head") != {"width": 8, "classes": 4, "mode": mode, "rank": 8, "max_parameters": 100000}):
            raise ValueError("original fixed warmup census identity required")
        identity = bindings["feature_identity"]
        if (identity.get("projected_tensor_sha256") != sha(features.tobytes())
                or identity.get("projection_sha256") != sha(projection.tobytes())
                or identity.get("projection") != retention["projection"]):
            raise ValueError("original warmup feature binding differs")
        state = CellTrainingState.load(folder, bindings, expected_protocol=retention["optimizer"],
            expected_contexts=manifest["contexts"], expected_state_digest=manifest["state_sha256"])
        heads.append({"id": name, "mode": mode, "tensor_sha256": state.head.digest(),
                      "params": {key: tensor(value) for key, value in sorted(state.head.params.items())}})
        identities.append(original_canonical(identity))
        original_states.append(state.digest())
        files[f"initial/{name}/manifest.json"] = sha(metadata)
        files[f"initial/{name}/state.npz"] = sha(payload)
    if len(set(identities)) != 1:
        raise ValueError("six original heads do not share the exact feature identity")
    graph = {"schema": "hepta.fixed-cell-graph.input.v1", "protocol_sha256": expected_protocol_sha256,
        "retention_protocol_sha256": RETENTION_PROTOCOL, "cohort_receipt_sha256": COHORT_RECEIPT,
        "features": tensor(features), "heads": heads, "head_order": list(HEAD_IDS),
        "reducer": "canonical-index-order np.stack then float64 mean(axis=0); equal1/6 weights",
        "original_states": original_states, "original_source_files_sha256": files,
        "feature_identity": strict_json(identities[0]), "authority": "DENY_ALL",
        "labels_or_outcomes_read": False, "head_selection": "all six original warmup heads; fixed before any new outcome"}
    output.mkdir(parents=True, exist_ok=False)
    graph_sha = write(output / "graph.json", graph)
    receipt = {"schema": "hepta.fixed-cell-graph.export.v1", "graph_sha256": graph_sha,
        "protocol_sha256": expected_protocol_sha256, "source_files": files, "source_code_sha256": source_digests,
        "wall_ns": time.perf_counter_ns() - began, "cpu_ns": time.process_time_ns() - cpu,
        "shared_once_cost_not_per_inference": True, "labels_or_outcomes_read": False}
    write(output / "export_receipt.json", receipt)
    return receipt


def checked_protocol(path, expected):
    data = safe_file(path, 65536)
    if sha(data) != expected:
        raise ValueError("graph protocol differs from explicit freeze")
    plan = strict_json(data)
    if (plan.get("schema") != SCHEMA or plan.get("status") != "FROZEN_BEFORE_GRAPH_INFERENCE"
            or plan.get("head_ids") != list(HEAD_IDS) or plan.get("block_orders") != [list(v) for v in BLOCK_ORDERS]
            or plan.get("shards") != [list(v) for v in SHARDS] or plan.get("authority") != "DENY_ALL"
            or plan.get("worker_count") != 30 or plan.get("graph_count") != 18):
        raise ValueError("exact bounded graph protocol required")
    for name, digest in plan["source_code_sha256"].items():
        if sha(safe_file(Path(__file__).with_name(name), 131072)) != digest:
            raise ValueError("frozen graph implementation differs")
    return plan


def freeze_environments(main, pocket4, output, *, protocol, expected_protocol_sha256, physical_attestation):
    plan = checked_protocol(protocol, expected_protocol_sha256)
    inventories = {host: strict_json(safe_file(path, 32768)) for host, path in (("main", main), ("pocket4", pocket4))}
    for host, record in inventories.items():
        declared = plan["declared_environment_versions"][host]
        if (record.get("worker_source_sha256") != sha(Path(__file__).with_name("cell_graph_worker.py").read_bytes())
                or any(record.get(key) != value for key, value in declared.items())
                or record.get("model_checkpoint_or_task_labels_opened") is not False
                or record.get("thread_environment") != {"OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1",
                    "MKL_NUM_THREADS": "1", "CUDA_VISIBLE_DEVICES": ""}):
            raise ValueError("exact pre-inference worker inventory required")
    if inventories["main"]["hostname_sha256"] == inventories["pocket4"]["hostname_sha256"]:
        raise ValueError("two independently identified host bindings required")
    attestation = strict_json(safe_file(physical_attestation, 32768))
    if (attestation.get("distinct_physical_hosts") is not True or attestation.get("authority") != "existing_native_process_owner"
            or set(attestation.get("host_evidence_sha256", {})) != {"main", "pocket4"}
            or any(not isinstance(value, str) or len(value) != 64 for value in attestation["host_evidence_sha256"].values())):
        raise ValueError("separate prior operator physical-host evidence required; hostname alone is insufficient")
    value = {"schema": "hepta.fixed-cell-graph.environments.v1", "protocol_sha256": expected_protocol_sha256,
        "inventories": inventories, "inventory_sha256": {host: sha(canonical(item)) for host, item in inventories.items()},
        "physical_attestation": attestation, "own_cgroup_ceiling_attestation_required_per_worker": True,
        "frozen_before_inference": True, "scope": "heterogeneous host/dispatch stacks, not isolated CPU architecture causal effect"}
    return {"environment_freeze_sha256": write(output, value), "inventory_sha256": value["inventory_sha256"]}


def prepare_requests(graph, environments, protocol, output, *, expected_protocol_sha256,
                     expected_graph_sha256, expected_environment_sha256):
    plan = checked_protocol(protocol, expected_protocol_sha256)
    graph_data, environment_data = safe_file(graph, MAX_INPUT), safe_file(environments, 65536)
    if sha(graph_data) != expected_graph_sha256 or sha(environment_data) != expected_environment_sha256:
        raise ValueError("explicit fixed graph/environment identity differs")
    frozen, hosts = strict_json(graph_data), strict_json(environment_data)
    if (frozen.get("protocol_sha256") != expected_protocol_sha256 or frozen.get("head_order") != list(HEAD_IDS)
            or len(frozen.get("heads", [])) != 6 or hosts.get("protocol_sha256") != expected_protocol_sha256
            or hosts.get("frozen_before_inference") is not True):
        raise ValueError("exact graph and pre-inference environments required")
    array(frozen["features"], (480, 8))
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    graphs = []
    began, cpu = time.perf_counter_ns(), time.process_time_ns()
    for block, arms in enumerate(BLOCK_ORDERS):
        for arm in arms:
            graph_id = f"b{block}-{arm}"
            selections = (tuple(range(6)),) if arm == "A" else SHARDS
            graph_record = {"graph_id": graph_id, "block": block, "arm": arm, "requests": [],
                "submission": "one" if arm == "A" else "concurrent Promise.all; no serial fallback",
                "aggregate_cpu_quota_percent": 200, "reducer_host": "original external graph owner"}
            for shard, indices in enumerate(selections):
                host = "pocket4" if arm == "C" and shard == (block % 2) else "main"
                request_id = graph_id + f"-s{shard}"
                request = {"schema": "hepta.fixed-cell-graph.worker.v1", "request_id": request_id,
                    "graph_sha256": expected_graph_sha256, "protocol_sha256": expected_protocol_sha256,
                    "environment_sha256": hosts["inventory_sha256"][host], "features": frozen["features"],
                    "heads": [frozen["heads"][i] for i in indices], "head_indices": list(indices),
                    "resource_limits": {"cpu_quota_percent": 200 if arm == "A" else 100,
                        "memory_max_bytes": 2_147_483_648 if arm == "A" else 1_073_741_824}, "authority": "DENY_ALL"}
                request_bytes = canonical(request) + b"\n"
                if len(request_bytes) > MAX_INPUT:
                    raise ValueError("request exceeds native stdin budget")
                path = output / f"{request_id}.json"
                with path.open("xb") as stream:
                    stream.write(request_bytes)
                request_sha = sha(request_bytes)
                graph_record["requests"].append({"request_id": request_id, "host": host, "head_indices": list(indices),
                    "request_file": path.name, "request_sha256": request_sha, "request_bytes": len(request_bytes),
                    "idempotency_key": f"cell-graph-v1-{expected_graph_sha256[:16]}-{request_id}",
                    "python_executable": hosts["inventories"][host]["python_executable"],
                    "cpu_quota_percent": 200 if arm == "A" else 100,
                    "memory_max_bytes": request["resource_limits"]["memory_max_bytes"],
                    "cpu_seconds": 10, "wall_seconds": 45, "max_stdout_bytes": 196608, "max_stderr_bytes": 8192,
                    "worker_source_sha256": hosts["inventories"][host]["worker_source_sha256"],
                    "environment_sha256": request["environment_sha256"]})
            graphs.append(graph_record)
    result = {"schema": "hepta.fixed-cell-graph.dispatch.v1", "protocol_sha256": expected_protocol_sha256,
        "graph_sha256": expected_graph_sha256, "environment_freeze_sha256": expected_environment_sha256,
        "graphs": graphs, "requests": sum(len(v["requests"]) for v in graphs),
        "recovery_requests_after_primary_census": [f"b0-{arm}-s0" for arm in ("A", "B", "C")],
        "prepare_wall_ns": time.perf_counter_ns() - began, "prepare_cpu_ns": time.process_time_ns() - cpu,
        "prepare_is_common_setup": True}
    return {"dispatch_sha256": write(output / "dispatch.json", result), "requests": result["requests"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest="mode", required=True)
    export = modes.add_parser("export")
    for name in ("run", "protocol", "output", "expected-protocol-sha256"):
        export.add_argument("--" + name, required=True)
    env = modes.add_parser("freeze-environments")
    for name in ("main", "pocket4", "output", "protocol", "expected-protocol-sha256", "physical-attestation"):
        env.add_argument("--" + name, required=True)
    requests = modes.add_parser("prepare")
    for name in ("graph", "environments", "protocol", "output", "expected-protocol-sha256", "expected-graph-sha256", "expected-environment-sha256"):
        requests.add_argument("--" + name, required=True)
    args = vars(parser.parse_args())
    mode = args.pop("mode")
    if mode == "export":
        sys.addaudithook(deny_outcomes)
    result = export_graph(**args) if mode == "export" else freeze_environments(**args) if mode == "freeze-environments" else prepare_requests(**args)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
