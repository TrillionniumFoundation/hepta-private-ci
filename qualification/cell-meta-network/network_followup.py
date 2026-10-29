"""Run a stronger local baseline without changing the first network experiment.

This process owns only its temporary SSH forwarders. Existing native workers
must already belong to the Runtime process owner. No worker is started,
restarted, signalled, or granted publication authority here.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import socket
import statistics
import subprocess
import threading
import time

import network_study as original


class IsolatedConnection(original.Connection):
    """Charge a dedicated SSH transport rather than a pre-existing master."""

    def __init__(self, node):
        if not node.get("ssh_target"):
            super().__init__(node)
            return
        target = node["ssh_target"]
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", target):
            raise ValueError("an existing, bounded SSH host alias is required")
        self.node, self.process, self.transfer = node, None, None
        self.lock = threading.Lock()
        self.sent, self.received = 0, 0
        began = time.perf_counter()
        host, remote_port = node["address"].rsplit(":", 1)
        if host != "127.0.0.1":
            raise ValueError("worker must be loopback-bound")
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            local_port = reservation.getsockname()[1]
        argv = ["ssh", "-N", "-v", "-S", "none", "-o", "ControlMaster=no",
                "-o", "ControlPath=none", "-o", "ControlPersist=no", "-o", "BatchMode=yes",
                "-o", "StrictHostKeyChecking=yes", "-o", "ExitOnForwardFailure=yes",
                "-o", "ConnectTimeout=10", "-L",
                f"127.0.0.1:{local_port}:127.0.0.1:{remote_port}", target]
        self.process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                        stderr=subprocess.PIPE, text=True)
        self.drain = threading.Thread(target=self._drain, daemon=True)
        self.drain.start()
        try:
            for _ in range(250):
                if self.process.poll() is not None:
                    raise RuntimeError("owned SSH forwarding process exited")
                try:
                    self.socket = socket.create_connection((host, local_port), timeout=0.2)
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


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    with path.open("xb") as stream:
        stream.write(original.encoded(value))


def summarize(trials):
    summary = []
    for arm in ("local_only", "pooled_centralized", "fixed_round_robin", "adaptive"):
        for batch in (1, 32):
            selected = [row for row in trials if row["arm"] == arm and row["batch_size"] == batch]
            if not selected:
                continue
            placement = {}
            for trial in selected:
                for row in trial["records"]:
                    placement[row["node"]] = placement.get(row["node"], 0) + row["rows"]
            summary.append({"arm": arm, "batch_size": batch, "trials": len(selected),
                "task_seconds_median": statistics.median(r["task_wall_seconds"] for r in selected),
                "measured_trial_seconds_median": statistics.median(r["lifecycle_wall_seconds"] for r in selected),
                "task_rows_by_node": placement,
                "coordinator_cpu_seconds_total": sum(r["coordinator_cpu_seconds"] for r in selected),
                "ssh_client_cpu_seconds_total": sum(r["ssh_cpu_seconds"] for r in selected),
                "ssh_wire_counters_complete": all(c["ssh_wire_bytes"] is not None
                    for r in selected for c in r["communication"] if c["node"] not in r["local_nodes"]),
                "application_bytes_total": sum(c["application_sent_bytes"] + c["application_received_bytes"]
                    for r in selected for c in r["communication"])})
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deployments", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rows", type=int, default=512)
    parser.add_argument("--repetitions", type=int, default=4)
    args = parser.parse_args()
    if not 64 <= args.rows <= 65536 or not 1 <= args.repetitions <= 10:
        raise ValueError("bounded experiment workload required")
    deployment = json.loads(args.deployments.read_bytes())
    nodes = deployment["nodes"]
    if len(nodes) != 2 or len({n["name"] for n in nodes}) != 2 or nodes[0].get("ssh_target"):
        raise ValueError("one local worker followed by one distinct remote worker is required")
    if not nodes[1].get("ssh_target") or any(not n.get("runtime_job_id") for n in nodes):
        raise ValueError("original Runtime job identities and the remote SSH alias are required")
    fixture = json.loads(args.fixture.read_bytes())
    if not fixture["features"] or len(fixture["features"]) != len(fixture["values"]):
        raise ValueError("frozen features and expected outputs must have the same nonzero length")
    args.output.mkdir(parents=True, exist_ok=False)
    original_source = Path(original.__file__).resolve()
    fingerprints = {str(p.resolve()): sha(p) for p in
                    (Path(__file__), original_source, args.fixture, args.deployments)}
    arms = ["local_only", "pooled_centralized", "fixed_round_robin", "adaptive"]
    protocol = {"schema": "hepta.native-cell-network-followup.v1", "sources": fingerprints,
        "rows_per_trial": args.rows, "repetitions": args.repetitions, "batch_sizes": [1, 32],
        "arms": arms, "available_host_pool": [n["name"] for n in nodes], "client_concurrency": 2,
        "local_only": "Only the local worker is connected or warmed; remote capacity remains unused",
        "ssh": "Dedicated nonmultiplexed client; original host-key verification is retained",
        "budget_claim": "Same available host pool and bounded workload, not equal consumed CPU or verified end-to-end cgroup budget",
        "timing_claim": "Measured trial time includes connection, calibration, execution and teardown; external deployment/recovery are separate",
        "unknown_costs": ["remote SSH service CPU", "complete resident-byte time integral", "hardware energy"],
        "scope": "A replicated native numeric Cell and placement policies; no inter-Cell computation graph or distributed learning"}
    save(args.output / "FREEZE.json", protocol)
    trials = []
    original.Connection = IsolatedConnection
    sequence = 2000
    for repetition in range(args.repetitions):
        order = arms[repetition % len(arms):] + arms[:repetition % len(arms)]
        for batch in (1, 32):
            for arm in order:
                selected = nodes[:1] if arm == "local_only" else nodes
                dispatch = {"local_only": "centralized", "pooled_centralized": "centralized",
                            "fixed_round_robin": "fixed_graph", "adaptive": "adaptive"}[arm]
                try:
                    row = original.trial(selected, fixture, dispatch, batch, sequence, args.rows)
                except Exception as error:
                    save(args.output / "FAILURE.json", {"arm": arm, "batch_size": batch,
                        "repetition": repetition, "request_namespace": sequence,
                        "error": repr(error), "completed_trials": len(trials),
                        "automatic_retry_count": 0})
                    raise
                row.update(arm=arm, dispatch_implementation=dispatch, repetition=repetition,
                           request_namespace=sequence, local_nodes=[n["name"] for n in selected if not n.get("ssh_target")])
                sequence += 1
                trials.append(row)
                save(args.output / f"{repetition}-{batch}-{arm}.json", row)
                print(json.dumps({"arm": arm, "batch": batch, "repetition": repetition,
                    "task_seconds": row["task_wall_seconds"],
                    "measured_trial_seconds": row["lifecycle_wall_seconds"]}), flush=True)
    if any(sha(path) != expected for path, expected in fingerprints.items()):
        raise ValueError("frozen source or inputs changed during the comparison")
    save(args.output / "RESULT.json", {"schema": "hepta.native-cell-network-followup-result.v1",
        "protocol": protocol, "trials": trials, "summary": summarize(trials),
        "all_tasks_correct": all(r["correct_rows"] == r["rows"] for r in trials),
        "network_benefit_automatically_claimed": False,
        "external_deployment_migration_costs": deployment.get("lifecycle_costs")})


if __name__ == "__main__":
    main()
