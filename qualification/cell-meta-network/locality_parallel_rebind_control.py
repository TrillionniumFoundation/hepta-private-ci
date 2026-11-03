"""Independent warm control after explicitly observed old worker termination.

Original data evidence is retained. Fresh Runtime workers keep the immutable
binary/model/shards but have new lifecycle bindings; no stale ready is reused.
"""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import resource
import statistics
import time

from locality_parallel_control import ORDER, PLACEMENTS, read, save, sha, trial
from network_followup import IsolatedConnection


TERMINAL_STATES = {"timed_out", "timeout", "exited", "completed", "succeeded", "failed", "cancelled", "canceled", "terminated", "killed"}
SOURCES = ("locality_parallel_rebind_control.py", "locality_parallel_control.py", "network_followup.py", "network_study.py")


def pointer(value, path):
    if path == "":
        return value
    if not isinstance(path, str) or not path.startswith("/"):
        raise ValueError("explicit JSON pointer required")
    for part in path[1:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


def evidence(spec, pins):
    path = Path(spec["path"]).resolve(strict=True)
    actual = sha(path)
    if actual != spec["sha256"]:
        raise ValueError("saved evidence SHA256 changed: " + str(path))
    pins[str(path)] = actual
    value = pointer(read(path), spec.get("document_pointer", ""))
    if spec.get("decode_json_string", False):
        if not isinstance(value, str):
            raise ValueError("JSON-string evidence field required")
        value = json.loads(value)
    return value


def runtime_receipt(spec, node, pins, terminal=False):
    value = evidence(spec, pins)
    if pointer(value, spec["job_pointer"]) != node["runtime_job_id"]:
        raise ValueError("Runtime evidence belongs to a different job")
    if terminal:
        state = pointer(value, spec["state_pointer"])
        if state not in TERMINAL_STATES or state != spec["terminal_state"]:
            raise ValueError("old Runtime job lacks an explicit matching terminal observation")
        return {"runtime_job_id":node["runtime_job_id"], "terminal_state":state,
                "receipt_sha256":spec["sha256"],
                "exit_code":value.get("exit_code"), "output_complete":value.get("output_complete"),
                "cleanup_scope":"provider terminal observation; wrapper/cgroup resource closure is recorded separately"}
    return {"runtime_job_id":node["runtime_job_id"], "receipt_sha256":spec["sha256"]}


def lifecycle_receipt(spec, node, binary, pins, fresh):
    value = evidence(spec, pins)
    if value.get("schema") != "hepta.cell-worker-lifecycle.v1" or value.get("worker_sha256") != binary \
            or value.get("launch_attempts") != 1:
        raise ValueError("worker lifecycle binary or launch identity differs")
    if fresh and (value.get("state") != "ready" or value.get("complete") is not False or value.get("child_reaped") is not False):
        raise ValueError("fresh worker needs a captured ready lifecycle snapshot")
    if not fresh and (value.get("state") != "terminal" or value.get("complete") is not True
                      or value.get("child_reaped") is not True or not isinstance(value.get("wait4_usage"), dict)):
        raise ValueError("old worker needs the completed direct-child lifecycle receipt")
    capture = value.get("ready", {})
    raw = base64.b64decode(capture["raw_base64"], validate=True)
    if len(raw) != capture["bytes"] or hashlib.sha256(raw).hexdigest() != capture["sha256"] \
            or json.loads(raw) != capture["json"]:
        raise ValueError("captured ready bytes and parsed worker identity differ")
    ready = value.get("ready", {}).get("json", {})
    if ready.get("ready") is not True or any(ready.get(key) != node[key] for key in ("address", "instance", "generation", "artifact_sha256")):
        raise ValueError("lifecycle ready is not the declared worker instance/generation")
    inherited = value.get("runtime_job_id_environment_observation")
    # This is an additional consistency check, never an alternative to the
    # independently pinned Runtime receipt validated by runtime_receipt().
    if inherited is not None and inherited != node["runtime_job_id"]:
        raise ValueError("lifecycle inherited Runtime job differs")
    return ready, {"worker_sha256":binary, "lifecycle_snapshot_sha256":spec["sha256"],
                   "observed_state":value.get("state"), "wrapper_complete":value.get("complete"),
                   "wrapper_classification":value.get("classification"),
                   "wrapper_child_reaped":value.get("child_reaped"),
                   "wait4_usage":value.get("wait4_usage"),
                   "wrapper_self_usage":value.get("wrapper_self_usage"),
                   "observed_lifecycle_wall_seconds":value.get("observed_lifecycle_wall_seconds"),
                   "clock_ticks_per_second":value.get("clock_ticks_per_second"),
                   "started_unix_ns":value.get("started_unix_ns"),
                   "finished_unix_ns":value.get("finished_unix_ns"),
                   "inherited_runtime_job_observation":inherited,
                   "startup_seconds":value.get("ready", {}).get("wrapper_start_to_ready_seconds"),
                   "resource_scope":"captured snapshot; retain final original/new Runtime and wrapper resource receipts independently"}


def inputs(args):
    deployment, previous, transfer, bindings = (read(path) for path in
        (args.prior_deployments, args.prior_result, args.prior_transfer, args.rebindings))
    if previous.get("schema") != "hepta.source-shard-locality-result.v1" \
            or previous["protocol"]["deployment_sha256"] != sha(args.prior_deployments) \
            or previous["central_transfer"] != transfer:
        raise ValueError("original data/result/transfer evidence differs")
    original, identities, expected = deployment["nodes"], deployment["manifest_sha256"], previous["verified_summaries"]
    if len(original) != 2 or len(identities) != 2 or identities[0] == identities[1] \
            or len(expected) != 2 or [row["manifest_sha256"] for row in expected] != identities \
            or original[0].get("ssh_target") or not original[1].get("ssh_target"):
        raise ValueError("original two-source identity differs")
    if bindings.get("schema") != "hepta.source-shard-worker-rebindings.v1" \
            or len(bindings["old_workers"]) != 2 or len(bindings["fresh_workers"]) != 3:
        raise ValueError("two explicit old terminations and three fresh workers required")
    binary = bindings["worker_sha256"]
    if len(binary) != 64 or any(char not in "0123456789abcdef" for char in binary):
        raise ValueError("pinned immutable worker SHA256 required")
    central = deployment["central_transfer"]
    root = Path(central["local_root"]).resolve(strict=True)
    if not root.is_dir() or not any(root.iterdir()) or Path(bindings["central_root"]).resolve(strict=True) != root \
            or sha(Path(central["manifest"])) != identities[1] \
            or any(transfer[key] != central[key] for key in ("archive_sha256", "archive_bytes")):
        raise ValueError("original populated central copy/manifest/transfer must be reused")
    paths = [args.prior_deployments, args.prior_result, args.prior_transfer, args.rebindings,
             Path(central["manifest"]), *(Path(__file__).with_name(name) for name in SOURCES)]
    pins = {str(path.resolve()):sha(path) for path in paths}
    observations = {"old":[], "fresh":[]}
    for old, proof in zip(original, bindings["old_workers"], strict=True):
        terminal = runtime_receipt(proof["runtime_terminal"], old, pins, terminal=True)
        _, lifecycle = lifecycle_receipt(proof["lifecycle_snapshot"], old, binary, pins, fresh=False)
        observations["old"].append({"node":old, "terminal":terminal, "lifecycle":lifecycle})
    nodes = [proof["node"] for proof in bindings["fresh_workers"]]
    if nodes[0].get("ssh_target") or nodes[2].get("ssh_target") or nodes[1].get("ssh_target") != original[1].get("ssh_target") \
            or not nodes[1].get("ssh_target") or nodes[0]["address"] == nodes[2]["address"]:
        raise ValueError("fresh placement must be main, original remote host, second main socket")
    for key in ("name", "instance", "runtime_job_id"):
        if any(not node.get(key) for node in nodes) or len({node[key] for node in nodes}) != 3:
            raise ValueError("fresh worker identities must be distinct: " + key)
    old_jobs = {node["runtime_job_id"] for node in original}
    if any(node["runtime_job_id"] in old_jobs or node["generation"] <= 0 for node in nodes) \
            or len({node["artifact_sha256"] for node in original + nodes}) != 1 \
            or any(nodes[index]["generation"] <= original[index]["generation"] for index in (0, 1)):
        raise ValueError("replacement generation/job must advance while model stays unchanged")
    for index, (node, proof) in enumerate(zip(nodes, bindings["fresh_workers"], strict=True)):
        startup = runtime_receipt(proof["runtime_start"], node, pins)
        ready, lifecycle = lifecycle_receipt(proof["lifecycle_ready_snapshot"], node, binary, pins, fresh=True)
        required = identities[0 if index == 0 else 1]
        if required not in ready.get("registered_shards", []) or not isinstance(proof.get("setup_receipts"), list) \
                or not proof["setup_receipts"]:
            raise ValueError("fresh worker must register its original shard and retain setup costs")
        setup = []
        for receipt in proof["setup_receipts"]:
            if not receipt.get("stage"):
                raise ValueError("setup receipt stage required")
            setup.append({"stage":receipt["stage"], "receipt_sha256":receipt["evidence"]["sha256"],
                          "observation":evidence(receipt["evidence"], pins)})
        observations["fresh"].append({"node":node, "runtime_start":startup, "lifecycle":lifecycle,
                                     "setup_receipts":setup})
    return nodes, identities, expected, transfer, observations, pins


def run(args):
    began, cpu = time.perf_counter(), time.process_time()
    child_before = resource.getrusage(resource.RUSAGE_CHILDREN)
    args.output.mkdir(parents=True, exist_ok=False)
    connections, records, warmups, failure = [], [], [], None
    try:
        nodes, identities, expected, transfer, observations, pins = inputs(args)
        protocol = {"schema":"hepta.source-shard-parallel-control.v2", "source_and_input_sha256":pins,
            "nodes":nodes, "manifest_sha256":identities, "order":ORDER, "placements":PLACEMENTS,
            "worker_rebindings":observations, "same_process_continuation":False,
            "parallelism":"two concurrent audit requests on two distinct fresh workers in either arm",
            "warmup":"one actual registered audit per fresh worker, separately recorded",
            "transfer":"reuse original successful transfer and existing content roots; no new transfer or extraction",
            "prior_performance_used_to_select_rounds":False, "cache":"uncontrolled OS page cache; separate warm experiment",
            "scope":"immutable source work on freshly bound Runtime workers; no cold deployment comparison or effect authority"}
        save(args.output / "FREEZE.json", protocol)
        for node in nodes:
            connections.append(IsolatedConnection(node))
        required = [identities[0], identities[1], identities[1]]
        for index, connection in enumerate(connections):
            before, _ = connection.call({"kind":"stats"}, f"rb-fence-before-{index}")
            if not before.get("ok") or required[index] not in before.get("registered_shards", []):
                raise RuntimeError("fresh live worker lacks the original shard")
            denied, _ = connection.call({"kind":"audit_shard", "manifest_sha256":required[index]},
                                        f"rb-stale-{index}", generation=nodes[index]["generation"]-1)
            after, _ = connection.call({"kind":"stats"}, f"rb-fence-after-{index}")
            if denied.get("error") != "binding_mismatch" or after["audit_requests"] != before["audit_requests"]:
                raise RuntimeError("fresh worker allowed stale generation to perform source work")
        for index in (0, 2, 1):
            response, elapsed = connections[index].call({"kind":"audit_shard", "manifest_sha256":required[index]}, f"rb-warmup-{index}")
            if not response.get("ok") or response["summary"] != expected[0 if index == 0 else 1]:
                raise RuntimeError("fresh worker source summary differs from immutable original")
            warmups.append({"worker":index, "rpc_ns":elapsed, "native_read_hash_ns":response["compute_ns"], "summary":response["summary"]})
        save(args.output / "WARMUP.json", {"records":warmups})
        for number, arm in enumerate(ORDER):
            row = trial(connections, identities, arm, number)
            if [item["summary"] for item in row["reads"]] != expected:
                raise RuntimeError("fresh control changed a frozen source result")
            records.append(row); save(args.output / f"trial-{number}-{arm}.json", row)
            print(json.dumps({"sequence":number, "arm":arm, "task_wall_seconds":row["task_wall_seconds"]}), flush=True)
        if any(sha(Path(path)) != identity for path, identity in pins.items()):
            raise RuntimeError("immutable proof/source snapshot changed during control")
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
                "worker_resources":"retain all original and fresh Runtime lifecycle receipts; no worker is signalled here"})
    summary = {arm:{"trials":sum(row["arm"] == arm for row in records),
                   "task_wall_seconds_median":statistics.median(row["task_wall_seconds"] for row in records if row["arm"] == arm),
                   "instrumented_wall_seconds_median":statistics.median(row["instrumented_trial_wall_seconds"] for row in records if row["arm"] == arm)}
               for arm in PLACEMENTS}
    pairs = []
    for offset in range(0, len(records), 2):
        pair = {row["arm"]:row for row in records[offset:offset+2]}
        pairs.append({"sequences":[offset, offset+1], "order":[row["arm"] for row in records[offset:offset+2]],
            "distributed_minus_local_seconds":pair["distributed"]["task_wall_seconds"]-pair["parallel_local"]["task_wall_seconds"]})
    save(args.output / "RESULT.json", {"schema":"hepta.source-shard-parallel-control-result.v2", "protocol":protocol,
        "summary":summary, "pairs":pairs, "paired_delta_median_seconds":statistics.median(pair["distributed_minus_local_seconds"] for pair in pairs),
        "trials":records, "warmups":warmups, "verified_summaries":expected,
        "original_transfer_receipt":transfer, "original_transfer_recharged":False, "new_source_transfer_performed":False,
        "fresh_worker_setup_receipts":[record["setup_receipts"] for record in observations["fresh"]],
        "connection_startup_seconds":[connection.startup_seconds for connection in connections],
        "ssh_wire_bytes":[connection.transfer for connection in connections],
        "observed_wall_seconds":time.perf_counter()-began, "coordinator_cpu_seconds":time.process_time()-cpu,
        "owned_ssh_cpu_seconds":ssh_cpu, "full_cost_exact":False, "cold_cost_comparison":None,
        "unknown_costs":["OS page-cache state", "host background contention", "remote SSH service CPU", "complete resident-byte integrals", "hardware energy"],
        "interpretation":"independent two-worker warm experiment after explicit rebinding; original A/B and all old/new startup costs remain separate"})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--prior-deployments", type=Path, required=True)
    parser.add_argument("--prior-result", type=Path, required=True)
    parser.add_argument("--prior-transfer", type=Path, required=True)
    parser.add_argument("--rebindings", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args())
