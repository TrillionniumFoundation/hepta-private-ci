"""ABBA comparison of real source-shard work on existing Runtime-owned workers.

This is source-snapshot integrity work, not a learning/general-agent benchmark.
The driver owns SSH transports only; worker lifecycle belongs to Runtime.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import select
import shlex
import statistics
import subprocess
import tarfile
import time

from network_followup import IsolatedConnection
from network_study import encoded
from source_shard import safe_path


def save(path, value):
    with path.open("xb") as stream:
        stream.write(encoded(value))


def central_copy(node, transfer, output):
    """One actual remote snapshot transfer, retained for warm local reuse."""
    started, cpu = time.perf_counter(), time.process_time()
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    target = node["ssh_target"]
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", target) or not 0 < transfer["archive_bytes"] <= 80 * 1024 * 1024:
        raise ValueError("bounded existing SSH target/archive required")
    command = ["ssh", "-S", "none", "-o", "ControlMaster=no", "-o", "ControlPath=none",
               "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes", "-o", "ConnectTimeout=10",
               "-o", "ServerAliveInterval=10", "-o", "ServerAliveCountMax=3",
               target, "cat -- " + shlex.quote(transfer["remote_archive"])]
    archive = output / "central-source.tar.gz"
    total, digest = 0, hashlib.sha256()
    with archive.open("xb") as destination, (output / "transfer.stderr").open("xb") as error:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=error)
        try:
            while True:
                if time.perf_counter() - started > 60 or not select.select([process.stdout], [], [], 30)[0]:
                    raise TimeoutError("bounded source transfer deadline")
                chunk = os.read(process.stdout.fileno(), 65536)
                if not chunk:
                    break
                total += len(chunk)
                if total > transfer["archive_bytes"]:
                    raise ValueError("archive transfer exceeded registered bytes")
                destination.write(chunk); digest.update(chunk)
            if process.wait(timeout=30) or total != transfer["archive_bytes"] or digest.hexdigest() != transfer["archive_sha256"]:
                raise ValueError("archive transfer identity or exit status differs")
        finally:
            if process.poll() is None:
                process.kill(); process.wait()
            process.stdout.close()
    received_seconds = time.perf_counter() - started
    manifest = json.loads(Path(transfer["manifest"]).read_bytes())
    extract_snapshot(archive, Path(transfer["local_root"]), manifest)
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    return {"archive_bytes":total, "archive_sha256":digest.hexdigest(), "receive_wall_seconds":received_seconds,
            "transfer_and_extract_wall_seconds":time.perf_counter()-started, "coordinator_cpu_seconds":time.process_time()-cpu,
            "ssh_client_cpu_seconds":after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime,
            "files":len(manifest["files"]), "source_bytes":sum(entry["bytes"] for entry in manifest["files"]),
            "source_location":"existing remote node source snapshot; origin identity is recorded in its manifest, with no main-to-remote data staging"}


def extract_snapshot(archive, incoming, manifest):
    if not incoming.is_dir() or any(incoming.iterdir()):
        raise ValueError("central destination must be a new empty owned directory")
    wanted = {entry["path"]: entry for entry in manifest["files"]}
    seen = set()
    with tarfile.open(archive, "r|gz") as stream:
        for member in stream:
            if not member.isfile() or not safe_path(member.name) or member.name not in wanted or member.name in seen or member.size != wanted[member.name]["bytes"]:
                raise ValueError("unregistered archive member")
            target_file = incoming / member.name; target_file.parent.mkdir(parents=True, exist_ok=True)
            source = stream.extractfile(member)
            raw = source.read(member.size + 1)
            if len(raw) != member.size:
                raise ValueError("archive member truncated")
            with target_file.open("xb") as destination:
                destination.write(raw)
            seen.add(member.name)
    if seen != set(wanted):
        raise ValueError("archive omitted registered source files")


def trial(connections, identities, arm, number):
    active = [0] if arm == "local_only" else [0, 1]
    started, cpu = time.perf_counter(), time.process_time()
    before = {index: connections[index].call({"kind":"stats"}, f"before-{number}-{index}")[0] for index in active}
    sent = [connection.sent for connection in connections]; received = [connection.received for connection in connections]
    task = time.perf_counter()
    if arm == "local_only":
        reads = [connections[0].call({"kind":"audit_shard", "manifest_sha256":identity}, f"local-{number}-{index}")
                 for index, identity in enumerate(identities)]
    else:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(connections[index].call, {"kind":"audit_shard", "manifest_sha256":identity}, f"distributed-{number}-{index}")
                       for index, identity in enumerate(identities)]
            reads = [future.result() for future in futures]
    task_seconds = time.perf_counter() - task
    if any(not response.get("ok") for response, _ in reads):
        raise RuntimeError("source audit failed: " + json.dumps([response for response, _ in reads]))
    after = {index: connections[index].call({"kind":"stats"}, f"after-{number}-{index}")[0] for index in active}
    for index in active:
        if not before[index].get("ok") or not after[index].get("ok"):
            raise RuntimeError("worker statistics unavailable")
        expected = 2 if arm == "local_only" else 1
        if after[index]["audit_requests"] - before[index]["audit_requests"] != expected or after[index]["failed_audit_requests"] != before[index]["failed_audit_requests"]:
            raise RuntimeError("unexpected or failed registered work")
    return {"arm":arm, "sequence":number, "task_wall_seconds":task_seconds,
            "instrumented_trial_wall_seconds":time.perf_counter()-started, "coordinator_cpu_seconds":time.process_time()-cpu,
            "reads":[{"summary":response["summary"], "rpc_ns":elapsed, "native_read_hash_ns":response["compute_ns"]} for response, elapsed in reads],
            "application_sent_bytes":sum(connection.sent - value for connection, value in zip(connections, sent, strict=True)),
            "application_received_bytes":sum(connection.received - value for connection, value in zip(connections, received, strict=True)),
            "worker_before":before, "worker_after":after}


def run(args):
    study_wall, study_cpu = time.perf_counter(), time.process_time()
    children_start = resource.getrusage(resource.RUSAGE_CHILDREN)
    deployment = json.loads(args.deployments.read_bytes())
    nodes = deployment["nodes"]
    if len(nodes) != 2 or nodes[0].get("ssh_target") or not nodes[1].get("ssh_target") or any(not node.get("runtime_job_id") for node in nodes):
        raise ValueError("one local and one remote Runtime-owned worker required")
    args.output.mkdir(parents=True, exist_ok=False)
    identities = deployment["manifest_sha256"]
    if len(identities) != 2 or identities[0] == identities[1]:
        raise ValueError("two different real source shards required")
    source = {name:hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
              for name in ("locality_study.py", "source_shard.py", "network_study.py", "network_followup.py")}
    protocol = {"schema":"hepta.source-shard-locality.v1", "source":source,
                "deployment_sha256":hashlib.sha256(args.deployments.read_bytes()).hexdigest(),
                "order":["local_only","distributed","distributed","local_only"] * 2,
                "work":"one full read/SHA256/newline audit of each distinct registered source file per trial",
                "cache":"OS page cache is not controlled; ABBA pairs measure persistent workers, not cold disks",
                "cold_worker":"use actual separately retained Runtime startup/deployment receipts; do not label the second run cold",
                "scope":"native source-integrity subtask; no learning, agent capability or AGI claim",
                "transfer":"one initial compressed remote-to-main transfer; warm local baseline reuses its local copy"}
    save(args.output / "FREEZE.json", protocol)
    connections, records, failure = [], [], None
    try:
        # Worker sockets have a 30-second idle deadline. Complete the potentially
        # longer transfer before opening persistent RPC streams; this also leaves
        # the initially empty, registered central root ready for its first audit.
        transfer = central_copy(nodes[1], deployment["central_transfer"], args.output)
        save(args.output / "CENTRAL_TRANSFER.json", transfer)
        for node in nodes:
            connections.append(IsolatedConnection(node))
        for index, connection in enumerate(connections):
            before, _ = connection.call({"kind":"stats"}, f"fence-before-{index}")
            denied, _ = connection.call({"kind":"audit_shard", "manifest_sha256":identities[index]}, f"stale-{index}", generation=nodes[index]["generation"] - 1)
            after, _ = connection.call({"kind":"stats"}, f"fence-after-{index}")
            if denied.get("error") != "binding_mismatch" or after["audit_requests"] != before["audit_requests"]:
                raise RuntimeError("stale generation performed registered file work")
        expected = None
        for number, arm in enumerate(protocol["order"]):
            row = trial(connections, identities, arm, number)
            summaries = [read["summary"] for read in row["reads"]]
            if expected is None:
                expected = summaries
            if summaries != expected:
                raise RuntimeError("local and distributed source audits differ")
            records.append(row); save(args.output / f"trial-{number}-{arm}.json", row)
            print(json.dumps({"arm":arm, "sequence":number, "task_wall_seconds":row["task_wall_seconds"]}), flush=True)
    except BaseException as error:
        failure = repr(error)
        raise
    finally:
        for connection in connections:
            connection.close()
        children_end = resource.getrusage(resource.RUSAGE_CHILDREN)
        ssh_cpu = children_end.ru_utime + children_end.ru_stime - children_start.ru_utime - children_start.ru_stime
        if failure is not None:
            save(args.output / "FAILURE.json", {"error":failure, "completed_trials":len(records), "automatic_retries":0,
                "observed_wall_seconds":time.perf_counter()-study_wall, "coordinator_cpu_seconds":time.process_time()-study_cpu,
                "owned_ssh_cpu_seconds":ssh_cpu, "external_worker_failure_costs":"retain separate Runtime job usage"})
    summary = {arm:{"trials":sum(row["arm"] == arm for row in records),
                    "task_wall_seconds_median":statistics.median(row["task_wall_seconds"] for row in records if row["arm"] == arm),
                    "instrumented_wall_seconds_median":statistics.median(row["instrumented_trial_wall_seconds"] for row in records if row["arm"] == arm)}
               for arm in ("local_only", "distributed")}
    setup = deployment.get("external_setup_wall_seconds")
    break_even = None
    if setup is not None:
        difference = setup["distributed"] + connections[1].startup_seconds - (setup["local_only"] + transfer["transfer_and_extract_wall_seconds"])
        saving = summary["local_only"]["task_wall_seconds_median"] - summary["distributed"]["task_wall_seconds_median"]
        if saving > 0:
            import math
            break_even = max(1, math.ceil(max(0, difference) / saving))
    save(args.output / "RESULT.json", {"schema":"hepta.source-shard-locality-result.v1", "protocol":protocol,
        "summary":summary, "trials":records, "verified_summaries":expected, "central_transfer":transfer,
        "connection_startup_seconds":[connection.startup_seconds for connection in connections],
        "ssh_wire_bytes":[connection.transfer for connection in connections],
        "external_setup_receipts":deployment.get("setup_receipts"), "external_setup_wall_seconds":setup,
        "break_even_repeated_audits":break_even, "full_cost_exact":False,
        "observed_coordinator_wall_seconds":time.perf_counter()-study_wall,
        "observed_coordinator_cpu_seconds":time.process_time()-study_cpu, "owned_ssh_cpu_seconds":ssh_cpu,
        "unknown_costs":["OS page-cache state", "remote SSH server CPU", "source-copy SSH framing bytes", "complete worker resident-byte integral", "hardware energy"],
        "network_benefit_automatically_claimed":False})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--deployments", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args())
