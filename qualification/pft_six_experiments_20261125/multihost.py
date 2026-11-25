#!/usr/bin/env python3
"""Two configured hosts compute their own data and exchange sufficient statistics directly."""
import argparse
import hashlib
import json
import math
import os
import random
import socket
import socketserver
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path

NODES = ["pocket4", "ai395"]
RIDGE = 0.01
QUANTIZATION = 10 ** 10


def encode(value):
    return json.dumps(value, allow_nan=False, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(encode(value).encode()).hexdigest()


def source_hash():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def save(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w") as stream:
        stream.write(encode(value) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def model(size, seed):
    rng = random.Random(seed * 1009 + size)
    return [rng.gauss(0, 0.1) for _ in range(size)], [rng.gauss(0, 1 / math.sqrt(size)) for _ in range(size)]


def generate(node, size, seed, batches):
    parent, truth = model(size, seed)
    index = NODES.index(node)
    header = {"parent": digest(parent), "coordinates": digest(["identity", size]),
              "objective": digest([RIDGE, "sum_squared_residual", source_hash()])}
    rng, messages = random.Random(seed * 65537 + size * 17 + index), []
    for batch in range(batches):
        count = max(6, size // 4) + batch * 2
        x = [[rng.gauss(0, 2.0 if j % 2 == index else 0.15) for j in range(size)] for _ in range(count)]
        y = [sum(a * b for a, b in zip(row, truth)) + rng.gauss(0, 0.05) for row in x]
        residual = [target - sum(a * b for a, b in zip(row, parent)) for row, target in zip(x, y)]
        gram = [[sum(row[i] * row[j] for row in x) for j in range(size)] for i in range(size)]
        moment = [sum(row[i] * value for row, value in zip(x, residual)) for i in range(size)]
        message = {**header, "node": node, "batch": batch, "count": count,
                   "data_hash": digest([x, y]), "gram": gram, "moment": moment}
        message["id"] = digest([header, node, batch, message["data_hash"]])
        message["payload_hash"] = digest(message)
        messages.append(message)
    return header, messages


def totals(messages, size):
    gram, moment = [[0.0] * size for _ in range(size)], [0.0] * size
    for message in sorted(messages, key=lambda m: m["id"]):
        for i in range(size):
            moment[i] += message["moment"][i]
            for j in range(size):
                gram[i][j] += message["gram"][i][j]
    return gram, moment


def solve(gram, moment, ridge=RIDGE):
    n = len(moment)
    lower = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1):
            value = gram[i][j] + (ridge if i == j else 0) - sum(lower[i][k] * lower[j][k] for k in range(j))
            lower[i][j] = math.sqrt(value) if i == j else value / lower[j][j]
    z, result = [0.0] * n, [0.0] * n
    for i in range(n):
        z[i] = (moment[i] - sum(lower[i][j] * z[j] for j in range(i))) / lower[i][i]
    for i in range(n - 1, -1, -1):
        result[i] = (z[i] - sum(lower[j][i] * result[j] for j in range(i + 1, n))) / lower[i][i]
    return result


def frame(packet):
    start = time.perf_counter()
    body = encode(packet).encode()
    return struct.pack("!I", len(body)) + body, time.perf_counter() - start


def receive(connection):
    def exact(count):
        parts = []
        while count:
            part = connection.recv(count)
            if not part:
                raise ConnectionError("Incomplete frame")
            parts.append(part)
            count -= len(part)
        return b"".join(parts)
    prefix = exact(4)
    length = struct.unpack("!I", prefix)[0]
    if length > 2_000_000:
        raise ValueError("Frame exceeds bounded protocol size")
    body = exact(length)
    start = time.perf_counter()
    return json.loads(body), prefix + body, time.perf_counter() - start


class State:
    def __init__(self, args):
        self.args, self.lock, self.done = args, threading.RLock(), False
        self.folder = Path(args.root) / f"n{args.size}-s{args.seed}"
        self.folder.mkdir(parents=True, exist_ok=True)
        self.ledger, self.metric_file = self.folder / "ledger.json", self.folder / "metrics.json"
        self.restored = 0
        self.metrics = {"sent_bytes": 0, "received_bytes": 0, "serialization_seconds": 0.0,
                        "exchange_seconds": 0.0, "statuses": {}, "packets": {}, "peer_address_validated": False}
        if args.resume:
            envelope = json.loads(self.ledger.read_text())
            if digest(envelope["body"]) != envelope["hash"]:
                raise ValueError("Ledger hash mismatch")
            self.header, self.messages = envelope["body"]["header"], envelope["body"]["messages"]
            self.restored = len(self.messages)
            self.metrics = json.loads(self.metric_file.read_text())
        else:
            self.header, messages = generate(args.node, args.size, args.seed, args.batches)
            self.messages = {m["id"]: m for m in messages}
            self.persist()
        self.own = [m for m in self.messages.values() if m["node"] == args.node]

    def persist(self):
        body = {"header": self.header, "messages": self.messages}
        save(self.ledger, {"body": body, "hash": digest(body)})
        save(self.metric_file, self.metrics)

    def record(self, direction, raw, serialization, status="ok", elapsed=0.0):
        with self.lock:
            self.metrics["sent_bytes" if direction == "tx" else "received_bytes"] += len(raw)
            self.metrics["serialization_seconds"] += serialization
            self.metrics["exchange_seconds"] += elapsed
            key = hashlib.sha256(raw).hexdigest()
            entry = self.metrics["packets"].setdefault(key, {"bytes": len(raw), "tx": 0, "rx": 0})
            entry[direction] += 1
            self.metrics["statuses"][status] = self.metrics["statuses"].get(status, 0) + 1

    def accept(self, message):
        if any(message[k] != v for k, v in self.header.items()) or message["node"] not in NODES:
            return "rejected_version"
        expected = digest({k: v for k, v in message.items() if k != "payload_hash"})
        if expected != message["payload_hash"] or not 0 <= message["batch"] < self.args.batches:
            return "rejected_integrity"
        if any(not math.isfinite(v) for row in message["gram"] for v in row) or any(not math.isfinite(v) for v in message["moment"]):
            return "rejected_nonfinite"
        identity = message["id"]
        if identity in self.messages:
            return "duplicate" if self.messages[identity]["payload_hash"] == expected else "rejected_conflict"
        self.messages[identity] = message
        self.persist()
        return "accepted"

    def incoming(self, connection, address):
        if address[0] != self.args.peer:
            raise ValueError("Unexpected peer address")
        self.metrics["peer_address_validated"] = True
        connection.settimeout(5)
        packet, raw, decoding = receive(connection)
        with self.lock:
            self.record("rx", raw, decoding)
            status = self.accept(packet["message"]) if packet["kind"] == "contribution" else "done"
            if status == "done":
                self.done = True
            if self.args.node == "ai395" and not self.args.resume and status == "accepted":
                self.persist()
                save(self.folder / "crash.json", {"pid": os.getpid(), "exit_code": 17, "persisted_contributions": len(self.messages)})
                os._exit(17)
        ack, encoding = frame({"status": status, "wire_hash": hashlib.sha256(raw).hexdigest()})
        connection.sendall(ack)
        self.record("tx", ack, encoding, status)

    def send(self, packet):
        raw, encoding = frame(packet)
        start, sent = time.perf_counter(), False
        try:
            with socket.create_connection((self.args.peer, self.args.port), timeout=0.5, source_address=(self.args.bind, 0)) as connection:
                connection.settimeout(5)
                connection.sendall(raw)
                sent = True
                answer, acknowledgement, decoding = receive(connection)
                self.record("rx", acknowledgement, decoding, answer["status"])
                if answer["wire_hash"] != hashlib.sha256(raw).hexdigest() or answer["status"] not in {"accepted", "duplicate", "done"}:
                    raise ValueError("Peer rejected frame or acknowledgement hash mismatch")
            self.record("tx", raw, encoding, "acknowledged", time.perf_counter() - start)
            return True
        except (OSError, ConnectionError) as error:
            self.record("tx", raw if sent else b"", encoding, type(error).__name__, time.perf_counter() - start)
            return False


def worker(args):
    started = time.perf_counter()
    state = State(args)
    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            try:
                state.incoming(self.request, self.client_address)
            except (OSError, ConnectionError):
                pass
    class Server(socketserver.ThreadingTCPServer):
        allow_reuse_address, daemon_threads = True, False
    server = Server((args.bind, args.port), Handler)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
    thread.start()
    deadline = time.monotonic() + args.timeout
    if args.node == "ai395" and not args.resume:
        while time.monotonic() < deadline:
            time.sleep(0.05)
        raise TimeoutError("No direct incoming contribution before deadline")
    order = list(state.own)
    random.Random(args.seed + NODES.index(args.node)).shuffle(order)
    packets = [{"kind": "contribution", "message": message} for message in order + order[::-1]] + [{"kind": "done"}]
    for packet in packets:
        while not state.send(packet):
            if time.monotonic() >= deadline:
                state.persist()
                raise TimeoutError("Direct peer delivery deadline")
            time.sleep(0.1)
    while len(state.messages) != 2 * args.batches or not state.done:
        if time.monotonic() >= deadline:
            raise TimeoutError("Direct peer convergence deadline")
        time.sleep(0.05)
    time.sleep(0.3)
    server.shutdown()
    server.server_close()
    thread.join()
    gram, moment = totals(list(state.messages.values()), args.size)
    action = solve(gram, moment)
    parent, truth = model(args.size, args.seed)
    candidate = [round((p + a) * QUANTIZATION) for p, a in zip(parent, action)]
    residual = [sum(gram[i][j] * action[j] for j in range(args.size)) + RIDGE * action[i] - moment[i] for i in range(args.size)]
    state.persist()
    result = {"node": args.node, "pid": os.getpid(), "python": sys.version.split()[0], "size": args.size, "seed": args.seed,
              "source_sha256": source_hash(), "header": state.header, "candidate_integer_grid": candidate,
              "candidate_sha256": digest(candidate), "quantization_step": 1 / QUANTIZATION,
              "aggregate_sha256": digest([gram, moment]), "normal_equation_residual_l2": math.sqrt(sum(v * v for v in residual)),
              "own_data_hashes": [m["data_hash"] for m in sorted(state.own, key=lambda m: m["batch"])],
              "accepted_contribution_ids": sorted(state.messages), "restored_contributions": state.restored,
              "metrics": state.metrics, "elapsed_seconds": time.perf_counter() - started}
    save(state.folder / "result.json", result)


def supervise(args):
    root = Path(args.root)
    root.mkdir(parents=True, exist_ok=True)
    records = []
    for index, (size, seed) in enumerate((n, s) for n in map(int, args.sizes.split(",")) for s in range(args.seed, args.seed + args.num_seeds)):
        command = [sys.executable, str(Path(__file__).resolve()), "--worker", "--node", args.node, "--bind", args.bind,
                   "--peer", args.peer, "--port", str(args.port + index), "--root", str(root), "--size", str(size),
                   "--seed", str(seed), "--batches", str(args.batches), "--timeout", str(args.timeout)]
        exits = []
        for attempt in range(2):
            completed = subprocess.run(command + (["--resume"] if attempt else []), capture_output=True, text=True, timeout=args.timeout + 10)
            exits.append(completed.returncode)
            if completed.returncode == 0:
                result = json.loads((root / f"n{size}-s{seed}" / "result.json").read_text())
                result["supervisor_exit_codes"] = exits
                records.append(result)
                break
            if completed.returncode == 17 and attempt == 0:
                time.sleep(0.35)
                continue
            save(root / "failure.json", {"node": args.node, "size": size, "seed": seed, "exit_codes": exits, "stderr": completed.stderr[-4000:]})
            save(root / "node_results.json", {"node": args.node, "source_sha256": source_hash(), "records": records, "failed": True})
            raise RuntimeError("Remote peer experiment failed; private failure receipt preserved")
    result = {"node": args.node, "source_sha256": source_hash(), "batches": args.batches, "records": records, "failed": False}
    save(root / "node_results.json", result)
    print(encode({"node": args.node, "runs": len(records), "source_sha256": source_hash(), "result_sha256": digest(result)}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node", choices=NODES, required=True)
    parser.add_argument("--bind", required=True)
    parser.add_argument("--peer", required=True)
    parser.add_argument("--root", required=True)
    parser.add_argument("--port", type=int, default=38641)
    parser.add_argument("--sizes", default="8,16,32,64")
    parser.add_argument("--size", type=int, default=32)
    parser.add_argument("--seed", type=int, default=731)
    parser.add_argument("--num-seeds", type=int, default=3)
    parser.add_argument("--batches", type=int, default=4)
    parser.add_argument("--timeout", type=int, default=150)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    worker(args) if args.worker else supervise(args)


if __name__ == "__main__":
    main()
