"""Measure real native Cell workers on a fixed pool of physical hosts.

The launcher supplies existing Runtime-owned workers. This script owns only its
SSH forwarding children and closes them on exit. It never launches an agent,
changes a host service or grants a model source/publication authority.
"""

import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import socket
import statistics
import subprocess
import threading
import time


CAP = 2 * 1024 * 1024


def encoded(value):
    return json.dumps(value, separators=(",", ":"), allow_nan=False).encode() + b"\n"


class Connection:
    def __init__(self, node):
        self.node = node
        self.process = None
        self.transfer = None
        self.lock = threading.Lock()
        self.sent, self.received = 0, 0
        began = time.perf_counter()
        host, port = node["address"].rsplit(":", 1)
        if host != "127.0.0.1":
            raise ValueError("worker must be loopback-bound")
        if node.get("ssh_target"):
            with socket.socket() as reservation:
                reservation.bind(("127.0.0.1", 0))
                local_port = reservation.getsockname()[1]
            command = ["ssh", "-N", "-v", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
                       "-o", "ExitOnForwardFailure=yes", "-o", "ConnectTimeout=10",
                       "-L", f"127.0.0.1:{local_port}:127.0.0.1:{port}", node["ssh_target"]]
            self.process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                            stderr=subprocess.PIPE, text=True)
            self.drain = threading.Thread(target=self._drain, daemon=True)
            self.drain.start()
            port = local_port
        try:
            for _ in range(250):
                if self.process is not None and self.process.poll() is not None:
                    raise RuntimeError("owned SSH forwarding process exited")
                try:
                    self.socket = socket.create_connection((host, int(port)), timeout=0.2)
                    break
                except OSError:
                    time.sleep(0.02)
            else:
                raise TimeoutError("worker connection did not become ready")
            self.socket.settimeout(30)
            self.socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self.reader = self.socket.makefile("rb")
        except BaseException:
            self.close()
            raise
        self.startup_seconds = time.perf_counter() - began

    def _drain(self):
        # Authentication diagnostics are discarded; retain only aggregate wire
        # counters from this dedicated tunnel, never key paths or credentials.
        for line in self.process.stderr:
            match = re.search(r"Transferred: sent (\d+), received (\d+) bytes", line)
            if match:
                self.transfer = {"sent_bytes": int(match[1]), "received_bytes": int(match[2])}

    def call(self, action, request_id, **overrides):
        request = {"request_id": request_id, "instance": self.node["instance"],
                   "generation": self.node["generation"], "artifact_sha256": self.node["artifact_sha256"],
                   "action": action, **overrides}
        raw = encoded(request)
        if len(raw) > CAP:
            raise ValueError("oversized request")
        with self.lock:
            began = time.perf_counter_ns()
            self.socket.sendall(raw)
            response = self.reader.readline(CAP + 1)
            elapsed = time.perf_counter_ns() - began
            if not response.endswith(b"\n") or len(response) > CAP:
                raise RuntimeError("invalid bounded worker response")
            self.sent += len(raw)
            self.received += len(response)
        result = json.loads(response)
        if result.get("request_id") != request_id:
            raise RuntimeError("response does not belong to this operation")
        return result, elapsed

    def close(self):
        if hasattr(self, "reader"):
            self.reader.close()
            self.socket.close()
        if self.process is not None:
            if self.process.poll() is None:
                self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
            self.drain.join(timeout=2)


def trial(nodes, fixture, arm, batch_size, repetition, total_rows):
    start, cpu = time.perf_counter(), time.process_time()
    children_before = resource.getrusage(resource.RUSAGE_CHILDREN)
    connections = []
    try:
        for node in nodes:
            connections.append(Connection(node))
        before, calibration, stale = [], [], []
        for index, connection in enumerate(connections):
            stats, _ = connection.call({"kind": "stats"}, f"before-{index}")
            if not stats.get("ok"):
                raise RuntimeError("worker refused bound stats")
            before.append(stats)
            denied, _ = connection.call({"kind": "read", "features": [fixture["features"][0]]},
                                        f"stale-{index}", generation=nodes[index]["generation"] - 1)
            stale.append(denied)
            if denied.get("ok") or denied.get("error") != "binding_mismatch":
                raise RuntimeError("stale generation admitted model work")
            times = []
            for warm in range(4 if arm == "adaptive" else 1):
                response, elapsed = connection.call(
                    {"kind": "read", "features": [fixture["features"][0]] * batch_size},
                    f"calibrate-{index}-{warm}")
                if not response.get("ok") or response["values"] != [fixture["values"][0]] * batch_size:
                    raise RuntimeError("native calibration prediction changed")
                times.append(elapsed)
            calibration.append(statistics.median(times))
        if {s["parameter_sha256"] for s in before} != {fixture["parameter_sha256"]}:
            raise RuntimeError("physical nodes loaded different parameters")
        jobs = []
        for offset in range(0, total_rows, batch_size):
            addresses = [i % len(fixture["features"]) for i in range(offset, min(offset + batch_size, total_rows))]
            jobs.append((offset, addresses))
        active = [0] * len(nodes)
        records = []
        pending = {}
        started = time.perf_counter()
        with ThreadPoolExecutor(max_workers=2) as pool:
            cursor = 0
            while cursor < len(jobs) or pending:
                while cursor < len(jobs) and len(pending) < 2:
                    offset, addresses = jobs[cursor]
                    if arm == "centralized":
                        selected = 0
                    elif arm == "fixed_graph":
                        selected = cursor % len(nodes)
                    elif arm == "adaptive":
                        selected = min(range(len(nodes)), key=lambda i: (active[i] + 1) * calibration[i])
                    else:
                        raise ValueError("unknown network organization")
                    active[selected] += 1
                    submitted = time.perf_counter_ns()
                    future = pool.submit(connections[selected].call,
                                         {"kind": "read", "features": [fixture["features"][i] for i in addresses]},
                                         f"{arm}-{repetition}-{batch_size}-{offset}")
                    pending[future] = (selected, addresses, submitted, offset)
                    cursor += 1
                completed, _ = wait(pending, return_when=FIRST_COMPLETED)
                for future in completed:
                    selected, addresses, submitted, offset = pending.pop(future)
                    response, rpc_ns = future.result()
                    active[selected] -= 1
                    if not response.get("ok") or response["values"] != [fixture["values"][i] for i in addresses]:
                        raise RuntimeError("real worker task result differs from the frozen fixture")
                    records.append({"offset": offset, "node": nodes[selected]["name"], "rows": len(addresses),
                                    "rpc_ns": rpc_ns, "end_to_end_ns": time.perf_counter_ns() - submitted,
                                    "compute_ns": response["compute_ns"],
                                    "values_sha256": hashlib.sha256(encoded(response["values"])).hexdigest()})
        task_wall = time.perf_counter() - started
        after = [connection.call({"kind": "stats"}, f"after-{index}")[0]
                 for index, connection in enumerate(connections)]
        if any(not item.get("ok") for item in after):
            raise RuntimeError("worker stats unavailable after tasks")
        for index, node in enumerate(nodes):
            task_rows = sum(row["rows"] for row in records if row["node"] == node["name"])
            expected_rows = task_rows + (4 if arm == "adaptive" else 1) * batch_size
            if after[index]["rows"] - before[index]["rows"] != expected_rows:
                raise RuntimeError("unexpected model calls, including possible stale work")
    finally:
        for connection in connections:
            connection.close()
    children_after = resource.getrusage(resource.RUSAGE_CHILDREN)
    latencies = sorted(row["end_to_end_ns"] for row in records)
    return {"arm": arm, "batch_size": batch_size, "repetition": repetition,
            "rows": total_rows, "correct_rows": sum(row["rows"] for row in records),
            "task_wall_seconds": task_wall, "lifecycle_wall_seconds": time.perf_counter() - start,
            "coordinator_cpu_seconds": time.process_time() - cpu,
            "ssh_cpu_seconds": children_after.ru_utime + children_after.ru_stime - children_before.ru_utime - children_before.ru_stime,
            "request_p50_ns": statistics.median(latencies), "request_p95_ns": latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))],
            "calibration_median_ns": calibration, "before": before, "after": after,
            "stale_bindings_rejected": len(stale), "records": sorted(records, key=lambda row: row["offset"]),
            "communication": [{"node": node["name"], "application_sent_bytes": connection.sent,
                               "application_received_bytes": connection.received,
                               "ssh_wire_bytes": connection.transfer,
                               "connection_startup_seconds": connection.startup_seconds}
                              for node, connection in zip(nodes, connections, strict=True)]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--deployments", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rows", type=int, default=512)
    parser.add_argument("--repetitions", type=int, default=3)
    args = parser.parse_args()
    if not 64 <= args.rows <= 65536 or not 1 <= args.repetitions <= 10:
        raise ValueError("bounded experiment workload required")
    deployments = json.loads(args.deployments.read_bytes())
    nodes = deployments["nodes"]
    if len(nodes) < 2 or len({node["name"] for node in nodes}) != len(nodes):
        raise ValueError("at least two distinct deployed host aliases required")
    fixture = json.loads(args.fixture.read_bytes())
    args.output.mkdir(parents=True, exist_ok=False)
    protocol = {"schema": "hepta.native-cell-network-study.v1", "rows_per_trial": args.rows,
                "repetitions": args.repetitions, "batch_sizes": [1, 32],
                "organizations": ["centralized", "fixed_graph", "adaptive"],
                "host_pool": [node["name"] for node in nodes], "client_concurrency": 2,
                "worker_cpu_cap": "one CPU per Runtime-owned worker; same pool in every arm",
                "feature_transport": "inline frozen encoder features; embedding generation is common and outside this transport trial",
                "identity": {"fixture_sha256": hashlib.sha256(args.fixture.read_bytes()).hexdigest(),
                             "deployments_sha256": hashlib.sha256(args.deployments.read_bytes()).hexdigest(),
                             "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},
                "scope": "real physical node transport and placement of a native numeric Cell, not an Agentd authority replacement"}
    (args.output / "FREEZE.json").write_bytes(encoded(protocol))
    records = []
    for repetition in range(args.repetitions):
        arms = protocol["organizations"][repetition:] + protocol["organizations"][:repetition]
        for batch_size in protocol["batch_sizes"]:
            for arm in arms:
                record = trial(nodes, fixture, arm, batch_size, repetition, args.rows)
                records.append(record)
                path = args.output / f"{repetition}-{batch_size}-{arm}.json"
                path.write_bytes(encoded(record))
                print(json.dumps({"completed": path.name, "task_seconds": record["task_wall_seconds"],
                                  "lifecycle_seconds": record["lifecycle_wall_seconds"]}), flush=True)
    result = {"schema": "hepta.native-cell-network-result.v1", "protocol": protocol, "trials": records,
              "network_benefit_automatically_claimed": False,
              "worker_deployment_migration_recovery_costs": deployments.get("lifecycle_costs"),
              "all_tasks_correct": all(row["rows"] == row["correct_rows"] for row in records)}
    (args.output / "RESULT.json").write_bytes(encoded(result))


if __name__ == "__main__":
    main()
