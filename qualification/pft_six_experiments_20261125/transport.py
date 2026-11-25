#!/usr/bin/env python3
"""PFT2 transport: four independent processes, real loopback TCP, disk recovery."""
import argparse
import hashlib
import json
import os
import socket
import socketserver
import struct
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
import numpy as np
from distributed import Receiver, array_hash, durable_write, encoded, hashed, seal


def pack(packet):
    start = time.perf_counter()
    body = encoded(packet).encode()
    return struct.pack("!I", len(body)) + body, time.perf_counter() - start


def read_exact(connection, length):
    pieces = []
    while length:
        part = connection.recv(length)
        if not part:
            raise ConnectionError("Connection closed before complete frame")
        pieces.append(part)
        length -= len(part)
    return b"".join(pieces)


def receive(connection):
    prefix = read_exact(connection, 4)
    length = struct.unpack("!I", prefix)[0]
    if length > 8_000_000:
        raise ValueError("Oversized application frame")
    body = read_exact(connection, length)
    start = time.perf_counter()
    packet = json.loads(body)
    return packet, prefix + body, time.perf_counter() - start


class Peer:
    def __init__(self, config, resume):
        self.config, self.identity = config, config["node"]
        self.directory = Path(config["directory"])
        self.ledger = self.directory / "ledger.json"
        self.metrics_path = self.directory / "metrics.json"
        self.lock = threading.RLock()
        self.receiver = Receiver.restore(self.ledger, expected_header=config["header"]) if resume else Receiver(config["header"])
        self.restored_count = len(self.receiver.messages)
        if not resume:
            self.receiver.accept(config["message"])
            self.receiver.checkpoint(self.ledger)
        self.metrics = json.loads(self.metrics_path.read_text()) if resume else []
        self.done = {self.identity}
        self.crash = config["crash_once"] and not resume

    def record(self, direction, peer, frame, elapsed, serialization=0.0, status="ok"):
        with self.lock:
            self.metrics.append({"direction": direction, "peer": peer, "frame_bytes": len(frame),
                                 "wire_sha256": hashlib.sha256(frame).hexdigest(),
                                 "elapsed_seconds": elapsed, "serialization_seconds": serialization, "status": status})
            durable_write(self.metrics_path, self.metrics)

    def incoming(self, connection):
        connection.settimeout(2.0)
        started = time.perf_counter()
        packet, frame, decode_time = receive(connection)
        sender = packet["sender"]
        if packet["recipient"] != self.identity or packet["round_id"] != self.config["round_id"]:
            raise ValueError("Peer or experiment round mismatch")
        self.record("receive", sender, frame, time.perf_counter() - started, decode_time)
        with self.lock:
            if packet["kind"] == "contribution":
                status = self.receiver.accept(packet["message"])
                if status == "accepted":
                    self.receiver.checkpoint(self.ledger)
                if self.crash and status == "accepted" and len(self.receiver.messages) >= 2:
                    durable_write(self.directory / "crash.json", {"pid": os.getpid(), "exit_code": 17,
                                  "durable_contributions": len(self.receiver.messages), "received_wire_sha256": hashlib.sha256(frame).hexdigest()})
                    os._exit(17)
            elif packet["kind"] == "done":
                self.done.add(sender)
                status = "done"
            else:
                raise ValueError("Unknown packet kind")
        acknowledgement, encode_time = pack({"sender": self.identity, "status": status,
                                             "received_wire_sha256": hashlib.sha256(frame).hexdigest()})
        connection.sendall(acknowledgement)
        self.record("ack_send", sender, acknowledgement, time.perf_counter() - started, encode_time, status)

    def send(self, recipient, kind):
        packet = {"sender": self.identity, "recipient": recipient, "round_id": self.config["round_id"], "kind": kind}
        if kind == "contribution":
            packet["message"] = self.config["message"]
        frame, encode_time = pack(packet)
        start, sent = time.perf_counter(), False
        try:
            with socket.create_connection(tuple(self.config["addresses"][recipient]), timeout=0.3) as connection:
                connection.settimeout(2.0)
                connection.sendall(frame)
                sent = True
                answer, ack_frame, decode_time = receive(connection)
                if answer["received_wire_sha256"] != hashlib.sha256(frame).hexdigest() or answer["sender"] != recipient:
                    raise ValueError("Acknowledgement hash or peer mismatch")
                self.record("ack_receive", recipient, ack_frame, time.perf_counter() - start, decode_time, answer["status"])
                if answer["status"] not in {"accepted", "duplicate", "done"}:
                    raise ValueError("Receiver rejected a valid contribution")
            self.record("send", recipient, frame, time.perf_counter() - start, encode_time, "acknowledged")
            return True
        except (OSError, ConnectionError) as error:
            self.record("send" if sent else "connect_failed", recipient, frame if sent else b"",
                        time.perf_counter() - start, encode_time, type(error).__name__)
            return False


def worker(config_path, resume):
    config = json.loads(Path(config_path).read_text())
    ridge = config["ridge"]
    if type(ridge) not in (int, float) or not np.isfinite(ridge) or ridge <= 0:
        raise ValueError("A finite positive ridge cost is required")
    objective = {"ridge": ridge, "loss": "sum squared residual", "version": 1}
    if config["header"]["objective_id"] != hashed(objective):
        raise ValueError("The actual solve differs from the frozen objective")
    parent = np.asarray(config["parent"], dtype=float)
    if parent.shape != (config["header"]["size"],) or not np.isfinite(parent).all():
        raise ValueError("A finite parent in the frozen coordinates is required")
    if array_hash(parent) != config["header"]["parent_id"]:
        raise ValueError("The actual parent differs from the frozen parent")
    peer = Peer(config, resume)
    if not resume:
        time.sleep(config["startup_delay_seconds"])
    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            try:
                peer.incoming(self.request)
            except (ConnectionError, OSError):
                pass
    class Server(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = False
    server = Server(tuple(config["addresses"][config["node"]]), Handler)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 30
    if peer.crash:
        while time.monotonic() < deadline:
            time.sleep(0.02)
        raise TimeoutError("Expected crash-triggering packet was not received")
    recipients = [node for node in range(len(config["addresses"])) if node != config["node"]]
    for kind, repetitions in [("contribution", 2), ("done", 1)]:
        pending = {node: repetitions for node in recipients}
        while any(pending.values()):
            for node in recipients:
                if pending[node] and peer.send(node, kind):
                    pending[node] -= 1
            if time.monotonic() > deadline:
                raise TimeoutError("Peer delivery deadline exceeded")
            time.sleep(0.02)
    while True:
        with peer.lock:
            complete = len(peer.receiver.messages) == len(config["addresses"]) and len(peer.done) == len(config["addresses"])
        if complete:
            break
        if time.monotonic() > deadline:
            raise TimeoutError("Peer convergence deadline exceeded")
        time.sleep(0.02)
    time.sleep(0.3)
    server.shutdown()
    server.server_close()
    thread.join()
    snapshot = peer.receiver.freeze(config["round_id"])
    peer.receiver.checkpoint(peer.ledger)
    gram, moment = peer.receiver.sums()
    action = np.linalg.solve(gram + config["ridge"] * np.eye(len(moment)), moment)
    candidate = parent + action
    result = {"node": config["node"], "pid": os.getpid(), "restored_contributions": peer.restored_count,
              "accepted_ids": sorted(peer.receiver.messages), "candidate": candidate.tolist(),
              "candidate_sha256": array_hash(candidate), "ledger_sha256": hashlib.sha256(peer.ledger.read_bytes()).hexdigest(),
              "statistics_snapshot_id": snapshot["snapshot_id"],
              "transfers": peer.metrics}
    durable_write(Path(config["directory"]) / "result.json", result)


def run_case(size, seed):
    rng = np.random.default_rng(np.random.SeedSequence([seed, size, 251]))
    nodes, ridge = 4, 0.01
    parent, truth = rng.normal(scale=0.1, size=size), rng.normal(size=size) / np.sqrt(size)
    header = {"size": size, "parent_id": array_hash(parent), "coordinate_id": array_hash(np.eye(size)),
              "objective_id": hashed({"ridge": ridge, "loss": "sum squared residual", "version": 1})}
    messages, matrices, residuals = [], [], []
    for node in range(nodes):
        scales = np.where(np.arange(size) % nodes == node, 2.0, 0.15)
        matrix = rng.normal(size=(size // 2 + 8, size)) * scales
        target = matrix @ truth + rng.normal(scale=0.05, size=len(matrix))
        residual = target - matrix @ parent
        messages.append(seal({**header, "client_id": str(node), "count": len(matrix),
                              "data_sha256": hashed([array_hash(matrix), array_hash(target)]),
                              "gram": (matrix.T @ matrix).tolist(), "moment": (matrix.T @ residual).tolist()}))
        matrices.append(matrix)
        residuals.append(residual)
    matrix, residual = np.vstack(matrices), np.concatenate(residuals)
    central = parent + np.linalg.solve(matrix.T @ matrix + ridge * np.eye(size), matrix.T @ residual)
    holders = [socket.socket() for _ in range(nodes)]
    for holder in holders:
        holder.bind(("127.0.0.1", 0))
    addresses = [list(holder.getsockname()) for holder in holders]
    for holder in holders:
        holder.close()
    processes, configurations, restart_records = {}, {}, []
    start = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="pft2-tcp-") as temporary:
        directory = Path(temporary)
        try:
            for node in range(nodes):
                folder = directory / str(node)
                folder.mkdir()
                config = {"node": node, "header": header, "message": messages[node], "addresses": addresses,
                          "round_id": hashed([size, seed, "tcp-v1"]), "directory": str(folder), "parent": parent.tolist(),
                          "ridge": ridge, "crash_once": node == 2, "startup_delay_seconds": 0.25 if node == 1 else 0.0}
                path = folder / "config.json"
                durable_write(path, config)
                configurations[node] = path
                processes[node] = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--worker", str(path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            deadline = time.monotonic() + 40
            restarted = False
            while True:
                for node, process in list(processes.items()):
                    code = process.poll()
                    if code == 17 and node == 2 and not restarted:
                        crash = json.loads((directory / str(node) / "crash.json").read_text())
                        time.sleep(0.35)
                        processes[node] = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--worker", str(configurations[node]), "--resume"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                        restart_records.append({**crash, "new_pid": processes[node].pid, "restart_delay_seconds": 0.35})
                        restarted = True
                    elif code not in {None, 0}:
                        raise RuntimeError(f"Node {node} exited {code}: {process.stderr.read()}")
                if all(process.poll() == 0 for process in processes.values()):
                    break
                if time.monotonic() > deadline:
                    raise TimeoutError("Coordinator deadline exceeded")
                time.sleep(0.02)
            results = [json.loads((directory / str(node) / "result.json").read_text()) for node in range(nodes)]
        finally:
            for process in processes.values():
                if process.poll() is None:
                    process.kill()
                process.wait()
    for result in results:
        candidate = np.asarray(result.pop("candidate"))
        result["central_relative_error"] = float(np.linalg.norm(candidate - central) / max(np.linalg.norm(central), 1e-15))
        result["true_parameter_relative_error"] = float(np.linalg.norm(candidate - truth) / np.linalg.norm(truth))
    transfers = [transfer for result in results for transfer in result["transfers"]]
    checks = {"same_candidate_hash": len({r["candidate_sha256"] for r in results}) == 1,
              "central_equivalence": max(r["central_relative_error"] for r in results) < 1e-9,
              "all_contributions_at_every_peer": all(len(r["accepted_ids"]) == nodes for r in results),
              "real_exit_and_persistent_restore": len(restart_records) == 1 and results[2]["restored_contributions"] >= 2,
              "duplicate_packets_observed": any(t["status"] == "duplicate" for t in transfers),
              "independent_peer_processes": len({r["pid"] for r in results}) == nodes}
    return {"size": size, "seed": seed, "nodes": nodes, "header": header, "checks": checks,
            "restart_records": restart_records, "node_results": results, "elapsed_seconds": time.perf_counter() - start,
            "application_frame_bytes_sent": sum(t["frame_bytes"] for t in transfers if t["direction"] in {"send", "ack_send"}),
            "application_frame_bytes_received": sum(t["frame_bytes"] for t in transfers if t["direction"] in {"receive", "ack_receive"}),
            "serialization_and_parsing_seconds": sum(t["serialization_seconds"] for t in transfers),
            "outgoing_exchange_seconds_sum": sum(t["elapsed_seconds"] for t in transfers if t["direction"] == "send"),
            "connect_failure_count": sum(t["direction"] == "connect_failed" for t in transfers)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(__file__).parent / "results/pft2_transport.json")
    parser.add_argument("--seed", type=int, default=731)
    parser.add_argument("--num-seeds", type=int, default=3)
    parser.add_argument("--sizes", default="8,16,32,64")
    parser.add_argument("--worker", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--resume", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        worker(args.worker, args.resume)
        return
    start = time.perf_counter()
    records = [run_case(size, seed) for size in map(int, args.sizes.split(",")) for seed in range(args.seed, args.seed + args.num_seeds)]
    summary = {"runs": len(records), "all_checks": all(all(r["checks"].values()) for r in records),
               "max_central_relative_error": max(n["central_relative_error"] for r in records for n in r["node_results"]),
               "total_frame_bytes_sent": sum(r["application_frame_bytes_sent"] for r in records)}
    payload = {"experiment": "PFT2_transport", "transport": "single-host multi-process P2P TCP over 127.0.0.1; not WAN or multi-host",
               "created_utc": datetime.now(timezone.utc).isoformat(), "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               "dependency_sha256": hashlib.sha256(Path(__file__).with_name("distributed.py").read_bytes()).hexdigest(),
               "configuration": {"sizes": args.sizes, "seed": args.seed, "num_seeds": args.num_seeds},
               "limitations": ["Coordinator creates experiment fixtures and restarts one failed process; every peer independently exchanges statistics and solves the candidate.",
                               "Byte counts are application frames including length prefix, excluding TCP/IP headers; sends accepted by sendall are counted even if acknowledgement is lost.",
                               "Exchange times overlap across processes and include receiver handling; their sum is not wall-clock latency.",
                               "No TLS, peer authentication, privacy, Byzantine consensus, WAN faults, long-duration soak or production runtime integration.",
                               "Atomic checkpoint and fsync recovery is tested after process exit, not host power loss."],
               "summary": summary, "records": records, "elapsed_seconds": time.perf_counter() - start}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(encoded(payload) + "\n")
    print(encoded({"output": str(args.output), "summary": summary, "elapsed_seconds": payload["elapsed_seconds"]}))


if __name__ == "__main__":
    main()
