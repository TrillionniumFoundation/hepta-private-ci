"""Bounded owned-host TCP sufficient-statistic exchange; synthetic E5/E6 support.

Both peers send their own Gram/rhs, independently add the same ridge term once,
and solve. The controller schedules processes but is absent from the data path.
An existing private overlay is transport, not evidence of direct WAN routing,
different owners, secure aggregation, HCSN learning, or fault-tolerant consensus.
"""

import argparse
import hashlib
import json
import math
import os
import platform
import socket
import struct
import sys
import time
from pathlib import Path


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def feature_rows(peer, width):
    """Public deterministic synthetic rows, generated only for the local shard."""
    rows, targets = [], []
    for i in range(peer["rows"]):
        row = [
            math.sin((i + 1) * (j + 1) * peer["frequency"]) + peer["offset"] + 0.07 * j
            for j in range(width)
        ]
        target = sum(x * ((j % 3) - 1) / (j + 1) for j, x in enumerate(row))
        rows.append(row)
        targets.append(target + 0.03 * math.cos(i + 1))
    return rows, targets


def statistics(peer, width):
    rows, targets = feature_rows(peer, width)
    return {
        "gram": [
            [sum(x[i] * x[j] for x in rows) for j in range(width)] for i in range(width)
        ],
        "rhs": [sum(x[i] * y for x, y in zip(rows, targets)) for i in range(width)],
        "count": len(rows),
        "dimension": width,
    }


def solve_ridge(gram, rhs, ridge):
    """Small pure-Python Cholesky solve; controller validates with NumPy."""
    n = len(rhs)
    chol = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1):
            value = gram[i][j] + (ridge if i == j else 0.0)
            value -= sum(chol[i][k] * chol[j][k] for k in range(j))
            chol[i][j] = math.sqrt(value) if i == j else value / chol[j][j]
    z, result = [0.0] * n, [0.0] * n
    for i in range(n):
        z[i] = (rhs[i] - sum(chol[i][j] * z[j] for j in range(i))) / chol[i][i]
    for i in reversed(range(n)):
        result[i] = (
            z[i] - sum(chol[j][i] * result[j] for j in range(i + 1, n))
        ) / chol[i][i]
    return result


class Frames:
    """Hard payload cap, independent frame hashes, explicit app-wire accounting."""

    def __init__(self, deadline, cap):
        self.deadline, self.cap = deadline, cap
        self.sent, self.received = 0, 0
        self.events = []

    def remaining(self):
        left = self.deadline - time.monotonic()
        if left <= 0:
            raise TimeoutError("frozen probe deadline expired")
        return left

    def send(self, stream, value):
        data = canonical(value)
        if len(data) > self.cap:
            raise ValueError("payload exceeds frozen cap")
        stream.settimeout(self.remaining())
        stream.sendall(struct.pack("!I", len(data)) + data)
        self.sent += 4 + len(data)
        self.events.append(
            {
                "direction": "send",
                "bytes": 4 + len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
                "phase": value["phase"],
            }
        )

    def receive(self, stream):
        def exact(size):
            pieces = bytearray()
            while len(pieces) < size:
                stream.settimeout(self.remaining())
                part = stream.recv(size - len(pieces))
                if not part:
                    raise EOFError("peer closed before frame completed")
                pieces.extend(part)
                self.received += len(part)
            return bytes(pieces)

        size = struct.unpack("!I", exact(4))[0]
        if size > self.cap:
            raise ValueError("received payload exceeds frozen cap")
        data = exact(size)
        value = json.loads(data)
        self.events.append(
            {
                "direction": "receive",
                "bytes": size + 4,
                "sha256": hashlib.sha256(data).hexdigest(),
                "phase": value["phase"],
            }
        )
        return value


def run(manifest, manifest_sha, alias):
    started = time.perf_counter_ns()
    peers = manifest["peers"]
    if len(peers) != 2 or alias not in peers:
        raise ValueError("exactly two frozen owned peers required")
    other = next(name for name in peers if name != alias)
    mine, theirs = peers[alias], peers[other]
    source_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    if source_sha != manifest["source_sha256"]:
        raise ValueError("source does not match pre-run manifest")
    width, ridge = manifest["width"], manifest["ridge"]
    if not (1 <= width <= 64 and ridge > 0 and 1024 <= manifest["port"] <= 65535):
        raise ValueError("invalid frozen dimensions or nonprivileged port")
    feature_start = time.perf_counter_ns()
    local = statistics(mine, width)
    feature_ns = time.perf_counter_ns() - feature_start
    deadline = time.monotonic() + manifest["network_timeout_seconds"]
    wire = Frames(deadline, manifest["max_frame_bytes"])
    identity = {
        "run_id": manifest["run_id"],
        "manifest_sha256": manifest_sha,
        "source_sha256": source_sha,
        "peer": alias,
    }
    receipt = {
        **identity,
        "hostname": socket.gethostname(),
        "pid": os.getpid(),
        "python": sys.version,
        "platform": platform.platform(),
        "feature_response_ns": feature_ns,
        "source_stats": local,
        "local_stats_sha256": digest(local),
        "peer": alias,
        "local_address": mine["ip"],
        "peer_address": theirs["ip"],
    }
    sockets = []
    communication_start = time.perf_counter_ns()
    try:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sockets.append(listener)
        listener.bind((mine["ip"], manifest["port"]))
        listener.listen(1)
        print(
            json.dumps({**identity, "phase": "listening", "port": manifest["port"]}),
            flush=True,
        )
        attempts = 0
        while True:
            outgoing = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            outgoing.bind((mine["ip"], 0))
            outgoing.settimeout(min(1.0, wire.remaining()))
            attempts += 1
            try:
                outgoing.connect((theirs["ip"], manifest["port"]))
                sockets.append(outgoing)
                break
            except (ConnectionRefusedError, TimeoutError):
                outgoing.close()
                time.sleep(min(0.2, wire.remaining()))
        wire.send(
            outgoing,
            {
                **identity,
                "phase": "stats",
                "statistics": local,
                "statistics_sha256": digest(local),
            },
        )
        listener.settimeout(wire.remaining())
        incoming, address = listener.accept()
        sockets.append(incoming)
        if address[0] != theirs["ip"]:
            raise ValueError("unexpected remote overlay address")
        remote = wire.receive(incoming)
        for key, expected in (
            ("run_id", manifest["run_id"]),
            ("manifest_sha256", manifest_sha),
            ("source_sha256", source_sha),
            ("peer", other),
            ("phase", "stats"),
        ):
            if remote.get(key) != expected:
                raise ValueError("received frame identity mismatch: " + key)
        remote_stats = remote["statistics"]
        if (
            remote_stats["count"] != theirs["rows"]
            or remote_stats["dimension"] != width
        ):
            raise ValueError("received dimensions/count mismatch")
        if digest(remote_stats) != remote["statistics_sha256"]:
            raise ValueError("received statistics commitment mismatch")
        received_ns = time.perf_counter_ns()
        gram = [
            [local["gram"][i][j] + remote_stats["gram"][i][j] for j in range(width)]
            for i in range(width)
        ]
        rhs = [local["rhs"][i] + remote_stats["rhs"][i] for i in range(width)]
        weights = solve_ridge(gram, rhs, ridge)
        aggregate_sha = digest({"gram": gram, "rhs": rhs})
        solve_end = time.perf_counter_ns()
        agreement = {
            **identity,
            "phase": "agreement",
            "aggregate_sha256": aggregate_sha,
            "weights": weights,
            "count": local["count"] + remote_stats["count"],
        }
        wire.send(outgoing, agreement)
        peer_agreement = wire.receive(incoming)
        for key, expected in (
            ("phase", "agreement"),
            ("manifest_sha256", manifest_sha),
            ("peer", other),
            ("aggregate_sha256", aggregate_sha),
        ):
            if peer_agreement.get(key) != expected:
                raise ValueError("peer solution agreement mismatch: " + key)
        error = max(abs(x - y) for x, y in zip(weights, peer_agreement["weights"]))
        if error > manifest["tolerance"]:
            raise ValueError("peers independently computed inconsistent solutions")
        receipt.update(
            {
                "status": "pass",
                "remote_stats_sha256": digest(remote_stats),
                "aggregate_sha256": aggregate_sha,
                "weights": weights,
                "count": agreement["count"],
                "peer_solution_max_error": error,
                "solve_ns": solve_end - received_ns,
                "connect_attempts": attempts,
                "incoming_remote_endpoint": list(address),
                "outgoing_local_endpoint": list(outgoing.getsockname()),
                "outgoing_remote_endpoint": list(outgoing.getpeername()),
            }
        )
    except Exception as error:
        receipt.update(
            {"status": "fail", "error_type": type(error).__name__, "error": str(error)}
        )
    finally:
        for stream in sockets:
            stream.close()
        receipt.update(
            {
                "sockets_closed": True,
                "app_bytes_sent": wire.sent,
                "app_bytes_received": wire.received,
                "frame_events": wire.events,
                "elapsed_ns": time.perf_counter_ns() - started,
                "communication_and_wait_ns": time.perf_counter_ns()
                - communication_start
                - receipt.get("solve_ns", 0),
            }
        )
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--peer", required=True)
    args = parser.parse_args()
    raw = Path(args.manifest).read_bytes()
    receipt = run(json.loads(raw), hashlib.sha256(raw).hexdigest(), args.peer)
    print(json.dumps(receipt, sort_keys=True, allow_nan=False), flush=True)
    return 0 if receipt["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
