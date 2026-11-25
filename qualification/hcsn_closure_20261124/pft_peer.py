"""Process-separated ring exchange of fixed-feature sufficient statistics.

Loopback sockets exercise real framing, process restart, and communication cost.
They do not establish WAN scaling, authenticated people, or Byzantine security.
SHA256 binds bytes and common objectives; it is not an identity signature.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import sys
import threading
import time

import numpy as np

from .pft_linear import solve_normal


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def create_json(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


def envelope(origin, gram, rhs, count, binding):
    body = dict(
        schema="pft-ring-contribution-v1",
        origin=origin,
        gram=gram.tolist(),
        rhs=rhs.tolist(),
        count=int(count),
        binding=binding,
    )
    return dict(body=body, sha256=hashlib.sha256(canonical(body)).hexdigest())


def validate(packet, expected, binding, dimension, outputs):
    body = packet["body"]
    if (
        packet["sha256"] != hashlib.sha256(canonical(body)).hexdigest()
        or body["schema"] != "pft-ring-contribution-v1"
        or body["binding"] != binding
        or body["origin"] != expected
        or not isinstance(body["count"], int)
        or body["count"] < 1
    ):
        raise ValueError(
            "changed, duplicate, out-of-order, or incompatible contribution"
        )
    gram, rhs = np.asarray(body["gram"]), np.asarray(body["rhs"])
    if (
        gram.shape != (dimension, dimension)
        or rhs.shape != (dimension, outputs)
        or not np.isfinite(gram).all()
        or not np.isfinite(rhs).all()
        or not np.allclose(gram, gram.T, rtol=1e-11, atol=1e-11)
    ):
        raise ValueError("invalid sufficient-statistic geometry")
    return gram, rhs


def receive(connection, size):
    parts = []
    while size:
        part = connection.recv(min(size, 65536))
        if not part:
            raise ConnectionError("peer closed an incomplete frame")
        parts.append(part)
        size -= len(part)
    return b"".join(parts)


def exchange(outbound, inbound, packet):
    encoded = canonical(packet)
    sent = struct.pack("!Q", len(encoded)) + encoded
    errors = []

    def send():
        try:
            outbound.sendall(sent)
        except OSError as error:
            errors.append(error)

    sender = threading.Thread(target=send, daemon=True)
    sender.start()
    size = struct.unpack("!Q", receive(inbound, 8))[0]
    if size > 64 * 1024 * 1024:
        raise ValueError("oversized contribution")
    result = json.loads(receive(inbound, size))
    sender.join(timeout=30)
    if sender.is_alive():
        raise TimeoutError("peer send timed out")
    if errors:
        raise errors[0]
    return result, len(sent), size + 8


def worker(manifest_path, peer, listener_fd):
    started = time.perf_counter()
    manifest = json.loads(Path(manifest_path).read_text())
    binding = hashlib.sha256(canonical(manifest)).hexdigest()
    entry = manifest["peers"][peer]
    if sha(entry["shard"]) != entry["sha256"]:
        raise ValueError("local shard changed")
    with np.load(entry["shard"], allow_pickle=False) as arrays:
        x, y = arrays["x"].astype(np.float64), arrays["y"].astype(np.float64)
    dimension, outputs = manifest["dimension"], manifest["outputs"]
    if x.shape != (len(y), dimension) or y.shape != (len(x), outputs):
        raise ValueError("local feature/target geometry changed")
    own = envelope(peer, x.T @ x, x.T @ y, len(x), binding)
    feature_seconds = time.perf_counter() - started
    communication_started = time.perf_counter()
    listener = socket.socket(fileno=listener_fd)
    listener.settimeout(30)
    outbound = socket.create_connection(
        ("127.0.0.1", manifest["ports"][(peer + 1) % len(manifest["peers"])]),
        timeout=30,
    )
    inbound, _ = listener.accept()
    inbound.settimeout(30)
    listener.close()
    received, packet, traffic = {peer: own}, own, []
    try:
        for step in range(1, len(manifest["peers"])):
            packet, sent, read = exchange(outbound, inbound, packet)
            origin = (peer - step) % len(manifest["peers"])
            validate(packet, origin, binding, dimension, outputs)
            if origin in received:
                raise ValueError("duplicate contributor")
            received[origin] = packet
            traffic.append(
                dict(
                    round=step,
                    origin=origin,
                    bytes_sent=sent,
                    bytes_received=read,
                    contribution_sha256=packet["sha256"],
                )
            )
    finally:
        outbound.close()
        inbound.close()
    communication_seconds = time.perf_counter() - communication_started
    solved = time.perf_counter()
    contributions = [
        validate(received[k], k, binding, dimension, outputs)
        for k in range(len(manifest["peers"]))
    ]
    gram = sum((g for g, _ in contributions), np.zeros((dimension, dimension)))
    rhs = sum((h for _, h in contributions), np.zeros((dimension, outputs)))
    weight = solve_normal(gram, rhs, manifest["regularizer"])
    solve_seconds = time.perf_counter() - solved
    output = Path(manifest["output"]) / f"peer{peer}"
    output.mkdir()
    with (output / "candidate.npz").open("xb") as stream:
        np.savez_compressed(stream, weight=weight)
    create_json(
        output / "RECEIPT.json",
        dict(
            peer=peer,
            pid=os.getpid(),
            binding=binding,
            origins=sorted(received),
            traffic=traffic,
            candidate_sha256=sha(output / "candidate.npz"),
            n=sum(v["body"]["count"] for v in received.values()),
            feature_response_seconds=feature_seconds,
            communication_seconds=communication_seconds,
            solve_seconds=solve_seconds,
            worker_wall_seconds=time.perf_counter() - started,
        ),
    )


def run_ring(shards, binding, output, regularizer=0.2):
    """Launch peers; the coordinator supplies identities/ports, never aggregates."""
    start = time.perf_counter()
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    if len(shards) < 2:
        raise ValueError("at least two peers required")
    listeners = []
    peers = []
    for shard in shards:
        path = Path(shard).resolve()
        with np.load(path, allow_pickle=False) as z:
            dimensions = (z["x"].shape[1], z["y"].shape[1])
        if peers and dimensions != (dimension, outputs):
            raise ValueError("peer dimensions differ")
        dimension, outputs = dimensions
        peers.append(dict(shard=str(path), sha256=sha(path)))
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        listeners.append(listener)
    manifest = dict(
        schema="pft-ring-session-v1",
        scope="same-host-independent-processes",
        dimension=dimension,
        outputs=outputs,
        regularizer=regularizer,
        output=str(output),
        peers=peers,
        objective_binding=binding,
        ports=[s.getsockname()[1] for s in listeners],
    )
    create_json(output / "MANIFEST.json", manifest)
    processes, logs = [], []
    try:
        for peer, listener in enumerate(listeners):
            log = (output / f"peer{peer}.log").open("xb")
            logs.append(log)
            processes.append(
                subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        __name__,
                        "worker",
                        "--manifest",
                        str(output / "MANIFEST.json"),
                        "--peer",
                        str(peer),
                        "--listener-fd",
                        str(listener.fileno()),
                    ],
                    pass_fds=(listener.fileno(),),
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
            )
        for listener in listeners:
            listener.close()
        exits = [process.wait(timeout=60) for process in processes]
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)
        for listener in listeners:
            listener.close()
        for log in logs:
            log.close()
    receipt = dict(
        exits=exits,
        launch_to_exit_seconds=time.perf_counter() - start,
        peer_pids=[p.pid for p in processes],
        central_aggregation=False,
        independent_hosts=False,
        authenticated_users=False,
    )
    create_json(output / "TERMINAL.json", receipt)
    if any(exits):
        raise RuntimeError("ring worker failed; preserved exit and process logs")
    return receipt


def replay(candidate, observations, output):
    """Cold process loads saved weights without any fitting or test selection."""
    started = time.perf_counter()
    with np.load(candidate, allow_pickle=False) as z:
        weight = z["weight"]
    with np.load(observations, allow_pickle=False) as z:
        predictions = z["x"] @ weight
    create_json(
        output,
        dict(
            pid=os.getpid(),
            candidate_sha256=sha(candidate),
            observations_sha256=sha(observations),
            predictions=predictions.tolist(),
            wall_seconds=time.perf_counter() - started,
            optimizer_steps=0,
            real_user_adoption=False,
        ),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    p = sub.add_parser("worker")
    p.add_argument("--manifest", required=True)
    p.add_argument("--peer", type=int, required=True)
    p.add_argument("--listener-fd", type=int, required=True)
    p = sub.add_parser("replay")
    p.add_argument("--candidate", required=True)
    p.add_argument("--observations", required=True)
    p.add_argument("--output", required=True)
    args = vars(parser.parse_args())
    operation = args.pop("operation")
    if operation == "worker":
        args["manifest_path"] = args.pop("manifest")
        worker(**args)
    else:
        replay(**args)


if __name__ == "__main__":
    main()
