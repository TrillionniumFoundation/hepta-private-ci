"""Warm source-locality control with two concurrent workers in both arms.

Reuse the original transfer and immutable inputs. This helper owns only its
temporary SSH transport; Runtime owns all three existing worker lifecycles.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import resource
import statistics
import time

from network_followup import IsolatedConnection
from network_study import encoded


ORDER = ["parallel_local", "distributed", "distributed", "parallel_local",
         "distributed", "parallel_local", "parallel_local", "distributed"] * 2
PLACEMENTS = {"parallel_local":(0, 2), "distributed":(0, 1)}
SOURCES = ("locality_parallel_control.py", "network_followup.py", "network_study.py")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    if not 0 < path.stat().st_size <= 8 * 1024 * 1024:
        raise ValueError("bounded prior evidence/configuration required")
    return json.loads(path.read_bytes())


def save(path, value):
    with path.open("xb") as stream:
        stream.write(encoded(value))


def inputs(args):
    deployment, previous, transfer, extra = (read(path) for path in
        (args.prior_deployments, args.prior_result, args.prior_transfer, args.additional_worker))
    if previous["schema"] != "hepta.source-shard-locality-result.v1" \
            or previous["protocol"]["deployment_sha256"] != sha(args.prior_deployments) \
            or previous["central_transfer"] != transfer:
        raise ValueError("original result/deployment/transfer binding differs")
    identities = deployment["manifest_sha256"]
    original = deployment["nodes"]
    if len(identities) != 2 or identities[0] == identities[1] or len(original) != 2 \
            or original[0].get("ssh_target") or not original[1].get("ssh_target"):
        raise ValueError("original one-main/one-remote study shape differs")
    expected = previous["verified_summaries"]
    if len(expected) != 2 or [row["manifest_sha256"] for row in expected] != identities:
        raise ValueError("original successful source summaries differ")
    central = deployment["central_transfer"]
    root = Path(central["local_root"]).resolve(strict=True)
    if not root.is_dir() or not any(root.iterdir()) or Path(extra["source_root"]).resolve(strict=True) != root \
            or extra["manifest_sha256"] != identities[1] or sha(Path(central["manifest"])) != identities[1]:
        raise ValueError("reuse the existing filled central root and exact remote manifest")
    if any(transfer[key] != central[key] for key in ("archive_sha256", "archive_bytes")):
        raise ValueError("original transfer archive differs")
    nodes = original + [extra["node"]]
    if nodes[2].get("ssh_target") or not isinstance(extra.get("setup_receipts"), list) or not extra["setup_receipts"]:
        raise ValueError("additional local worker and explicit setup receipt required")
    for key in ("name", "instance", "runtime_job_id"):
        if any(not node.get(key) for node in nodes) or len({node[key] for node in nodes}) != 3:
            raise ValueError("three distinct Runtime-owned worker identities required: " + key)
    if nodes[0]["address"] == nodes[2]["address"] or any(node["generation"] <= 0 for node in nodes) \
            or len({node["artifact_sha256"] for node in nodes}) != 1:
        raise ValueError("local sockets must be distinct and the frozen model identical")
    paths = [args.prior_deployments, args.prior_result, args.prior_transfer, args.additional_worker,
             Path(central["manifest"]), *(Path(__file__).with_name(name) for name in SOURCES)]
    pins = {str(path.resolve()):sha(path) for path in paths}
    return nodes, identities, expected, transfer, extra, pins


def byte_counts(connections):
    return sum(connection.sent for connection in connections), sum(connection.received for connection in connections)


def byte_delta(after, before):
    return {"sent":after[0]-before[0], "received":after[1]-before[1]}


def trial(connections, identities, arm, number):
    active = PLACEMENTS[arm]
    began, cpu = time.perf_counter(), time.process_time()
    all_bytes = byte_counts(connections)
    before = {index:connections[index].call({"kind":"stats"}, f"pc-before-{number}-{index}")[0] for index in active}
    work_bytes = byte_counts(connections)
    started = time.perf_counter()
    # Both arms create the same two-thread executor and dispatch exactly one
    # source audit to each independent worker. No serial local shortcut.
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(connections[index].call, {"kind":"audit_shard", "manifest_sha256":identity},
                                   f"pc-audit-{number}-{slot}")
                   for slot, (index, identity) in enumerate(zip(active, identities, strict=True))]
        reads = [future.result() for future in futures]
    task_seconds = time.perf_counter()-started
    task_bytes = byte_delta(byte_counts(connections), work_bytes)
    if any(not response.get("ok") for response, _ in reads):
        raise RuntimeError("registered audit failed: " + json.dumps([response for response, _ in reads]))
    after = {index:connections[index].call({"kind":"stats"}, f"pc-after-{number}-{index}")[0] for index in active}
    for index in active:
        if not before[index].get("ok") or not after[index].get("ok") \
                or after[index]["audit_requests"] - before[index]["audit_requests"] != 1 \
                or after[index]["failed_audit_requests"] != before[index]["failed_audit_requests"]:
            raise RuntimeError("each active worker must complete exactly one successful audit")
    return {"arm":arm, "sequence":number, "active_workers":list(active), "concurrent_workers":2,
        "task_wall_seconds":task_seconds, "instrumented_trial_wall_seconds":time.perf_counter()-began,
        "coordinator_cpu_seconds":time.process_time()-cpu,
        "application_task_bytes":task_bytes, "application_instrumented_bytes":byte_delta(byte_counts(connections), all_bytes),
        "reads":[{"worker":index, "summary":response["summary"], "rpc_ns":elapsed, "native_read_hash_ns":response["compute_ns"]}
                 for index, (response, elapsed) in zip(active, reads, strict=True)],
        "worker_before":before, "worker_after":after}


def run(args):
    began, cpu = time.perf_counter(), time.process_time()
    child_before = resource.getrusage(resource.RUSAGE_CHILDREN)
    args.output.mkdir(parents=True, exist_ok=False)
    connections, records, warmups, failure = [], [], [], None
    try:
        nodes, identities, expected, transfer, extra, pins = inputs(args)
        protocol = {"schema":"hepta.source-shard-parallel-control.v1", "source_and_input_sha256":pins,
            "nodes":nodes, "manifest_sha256":identities, "order":ORDER, "placements":PLACEMENTS,
            "parallelism":"exactly two concurrent audit requests on two distinct workers in either arm",
            "warmup":"one actual registered audit per worker, separately recorded before measured trials",
            "transfer":"reuse original CENTRAL_TRANSFER and existing central root; no new transfer, extraction or source staging",
            "prior_performance_used_to_select_rounds":False, "cache":"OS page cache uncontrolled; warm process/task comparison only",
            "scope":"source-integrity subtask; matched worker count does not imply identical hardware or measured CPU quotas",
            "new_worker_setup":"record separately; this control does not claim complete cold deployment cost"}
        save(args.output / "FREEZE.json", protocol)
        for node in nodes:
            connections.append(IsolatedConnection(node))
        required = [identities[0], identities[1], identities[1]]
        for index, connection in enumerate(connections):
            before, _ = connection.call({"kind":"stats"}, f"pc-fence-before-{index}")
            if not before.get("ok") or required[index] not in before.get("registered_shards", []):
                raise RuntimeError("actual worker does not register the required original shard")
            denied, _ = connection.call({"kind":"audit_shard", "manifest_sha256":required[index]}, f"pc-stale-{index}", generation=nodes[index]["generation"]-1)
            after, _ = connection.call({"kind":"stats"}, f"pc-fence-after-{index}")
            if denied.get("error") != "binding_mismatch" or after["audit_requests"] != before["audit_requests"]:
                raise RuntimeError("stale generation performed source work")
        for index in (0, 2, 1):
            response, elapsed = connections[index].call({"kind":"audit_shard", "manifest_sha256":required[index]}, f"pc-warmup-{index}")
            if not response.get("ok") or response["summary"] != expected[0 if index == 0 else 1]:
                raise RuntimeError("warmup differs from the original immutable summary")
            warmups.append({"worker":index, "rpc_ns":elapsed, "native_read_hash_ns":response["compute_ns"], "summary":response["summary"]})
        save(args.output / "WARMUP.json", {"records":warmups})
        for number, arm in enumerate(ORDER):
            row = trial(connections, identities, arm, number)
            if [read["summary"] for read in row["reads"]] != expected:
                raise RuntimeError("parallel control changed an original source result")
            records.append(row); save(args.output / f"trial-{number}-{arm}.json", row)
            print(json.dumps({"sequence":number, "arm":arm, "task_wall_seconds":row["task_wall_seconds"]}), flush=True)
        if any(sha(Path(path)) != identity for path, identity in pins.items()):
            raise RuntimeError("frozen source or prior evidence changed during control")
    except BaseException as error:
        failure = repr(error)
        raise
    finally:
        for connection in connections:
            connection.close()
        child_after = resource.getrusage(resource.RUSAGE_CHILDREN)
        ssh_cpu = child_after.ru_utime+child_after.ru_stime-child_before.ru_utime-child_before.ru_stime
        if failure is not None:
            save(args.output / "FAILURE.json", {"error":failure, "completed_trials":len(records), "warmups":warmups,
                "automatic_retries":0, "observed_wall_seconds":time.perf_counter()-began,
                "coordinator_cpu_seconds":time.process_time()-cpu, "owned_ssh_cpu_seconds":ssh_cpu,
                "worker_resources":"retain the external Runtime lifecycle receipts; no worker is signalled here"})
    summary = {arm:{"trials":sum(row["arm"] == arm for row in records),
                   "task_wall_seconds_median":statistics.median(row["task_wall_seconds"] for row in records if row["arm"] == arm),
                   "instrumented_wall_seconds_median":statistics.median(row["instrumented_trial_wall_seconds"] for row in records if row["arm"] == arm)}
               for arm in PLACEMENTS}
    pairs = []
    for offset in range(0, len(records), 2):
        pair = {row["arm"]:row for row in records[offset:offset+2]}
        pairs.append({"sequences":[offset, offset+1], "order":[row["arm"] for row in records[offset:offset+2]],
            "distributed_minus_local_seconds":pair["distributed"]["task_wall_seconds"]-pair["parallel_local"]["task_wall_seconds"]})
    save(args.output / "RESULT.json", {"schema":"hepta.source-shard-parallel-control-result.v1", "protocol":protocol,
        "summary":summary, "pairs":pairs, "paired_delta_median_seconds":statistics.median(pair["distributed_minus_local_seconds"] for pair in pairs),
        "trials":records, "warmups":warmups, "verified_summaries":expected,
        "original_transfer_receipt":transfer, "original_transfer_recharged":False, "new_source_transfer_performed":False,
        "additional_worker_setup_receipts":extra["setup_receipts"],
        "connection_startup_seconds":[connection.startup_seconds for connection in connections],
        "ssh_wire_bytes":[connection.transfer for connection in connections],
        "observed_wall_seconds":time.perf_counter()-began, "coordinator_cpu_seconds":time.process_time()-cpu,
        "owned_ssh_cpu_seconds":ssh_cpu, "full_cost_exact":False, "cold_cost_comparison":None,
        "unknown_costs":["OS page-cache state", "remote SSH service CPU", "complete resident-byte integrals", "hardware energy"],
        "interpretation":"two-worker warm control; original serial-local A/B remains separate; no automatic network benefit claim"})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--prior-deployments", type=Path, required=True)
    parser.add_argument("--prior-result", type=Path, required=True)
    parser.add_argument("--prior-transfer", type=Path, required=True)
    parser.add_argument("--additional-worker", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args())
