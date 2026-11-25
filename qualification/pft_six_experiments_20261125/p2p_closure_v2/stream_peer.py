#!/usr/bin/env python3
"""Two authenticated peers exchange bounded frames over one full-duplex SSH stream."""
import argparse
import json
import os
from pathlib import Path
import select
import struct
import sys
import time
import zlib

from sufficient import State, digest, durable, encode, sha, signed_message


class Frames:
    def __init__(self, reader, writer, state):
        self.reader, self.writer, self.state = reader.fileno(), writer.fileno(), state

    def read_exact(self, count):
        parts, deadline = [], time.monotonic() + 30
        while count:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([self.reader], [], [], remaining)[0]:
                raise TimeoutError("Peer frame deadline")
            part = os.read(self.reader, count)
            if not part:
                raise EOFError("Peer stream closed")
            parts.append(part)
            count -= len(part)
        return b"".join(parts)

    def record(self, direction, kind, raw):
        metrics = self.state.metrics
        metrics[direction + "_bytes"] += len(raw)
        metrics["packets"].append({"direction": direction, "kind": kind, "bytes": len(raw), "sha256": sha(raw)})

    def send(self, kind, payload):
        tick = time.perf_counter()
        packet = {"kind": kind, "payload": payload, "round_id": self.state.args.round_id,
                  "sender": self.state.args.node, "sources": digest(self.state.source)}
        body = encode(packet)
        raw = struct.pack("!I", len(body)) + body
        self.state.metrics["encode_seconds"] += time.perf_counter() - tick
        tick, offset = time.perf_counter(), 0
        while offset < len(raw):
            if not select.select([], [self.writer], [], 30)[1]:
                raise TimeoutError("Peer write deadline")
            offset += os.write(self.writer, raw[offset:])
        self.state.metrics["pipe_write_seconds"] += time.perf_counter() - tick
        self.record("tx", kind, raw)

    def receive(self, expected=None):
        tick = time.perf_counter()
        try:
            prefix = self.read_exact(4)
            length = struct.unpack("!I", prefix)[0]
            if not 0 < length <= 16 * 1024 * 1024:
                raise ValueError("Invalid bounded frame size")
            body = self.read_exact(length)
        finally:
            self.state.metrics["pipe_read_wait_seconds"] += time.perf_counter() - tick
        tick = time.perf_counter()
        packet = json.loads(body)
        self.state.metrics["decode_seconds"] += time.perf_counter() - tick
        self.record("rx", packet.get("kind"), prefix + body)
        peer = "pocket4" if self.state.args.node == "ai395" else "ai395"
        if packet["round_id"] != self.state.args.round_id or packet["sources"] != digest(self.state.source) or packet["sender"] != peer:
            raise ValueError("Session identity mismatch")
        if expected is not None and packet["kind"] != expected:
            raise ValueError("Unexpected protocol phase")
        return packet


def hello(state):
    value = {"header": state.header, "pid": os.getpid(), "unix_ns": time.time_ns(), "restored_contributions": state.restored,
             "restore_ledger_sha256": getattr(state, "restore_sha", None), "previous_pid": state.previous_pid}
    crash = state.folder / "crash.json"
    if crash.exists():
        value["crash_receipt"] = json.loads(crash.read_text())
    return value


def check_hello(state, packet):
    value = packet["payload"]
    if value["header"] != state.header:
        raise ValueError("Peer parent, basis, or objective mismatch")
    return value


def send_contributions(channel, state):
    stale = {k: v for k, v in state.own[0].items() if k != "payload_hash"}
    stale["parent"] = "0" * 64
    channel.send("contribution", signed_message(stale))
    if channel.receive("ack")["payload"]["status"] != "rejected_version":
        raise ValueError("Stale parent was not rejected")
    order = [3, 1, 0, 2, 1, 3, 0, 2]
    for index in order:
        message = state.own[index]
        channel.send("contribution", message)
        ack = channel.receive("ack")["payload"]
        if ack["status"] not in ("accepted", "duplicate") or ack["id"] != message["id"]:
            raise ValueError("Peer rejected contribution")
    channel.send("phase_done", {"own_ids": [m["id"] for m in state.own]})
    channel.receive("phase_ack")


def receive_contributions(channel, state, inject_crash=False):
    while True:
        packet = channel.receive()
        if packet["kind"] == "phase_done":
            if not all(identity in state.messages for identity in packet["payload"]["own_ids"]):
                raise ValueError("Premature peer completion")
            channel.send("phase_ack", {"contributions": len(state.messages)})
            return
        if packet["kind"] != "contribution":
            raise ValueError("Expected contribution")
        message = packet["payload"]
        if message.get("node") == state.args.node:
            raise ValueError("Peer may only send its own contributions")
        status = state.accept(message)
        if inject_crash and status == "accepted":
            ledger_sha = state.persist()
            checkpoint = zlib.compress(state.ledger.read_bytes(), 9)
            copy_write, copy_read = durable(state.folder / "crash_checkpoint.json.zlib", checkpoint)
            crash = {"pid": os.getpid(), "intended_exit_code": 17, "ledger_sha256": ledger_sha,
                     "checkpoint_archive_sha256": sha(checkpoint), "checkpoint_archive_bytes": len(checkpoint),
                     "checkpoint_copy_write_seconds": copy_write, "checkpoint_copy_readback_seconds": copy_read,
                     "persisted_contributions": len(state.messages), "received_id": message["id"],
                     "elapsed_before_exit_seconds": time.monotonic() - state.started, "unix_ns": time.time_ns()}
            durable(state.folder / "crash.json", encode(crash) + b"\n")
            os._exit(17)
        channel.send("ack", {"status": status, "id": message.get("id")})


def server(args):
    state = State(args)
    if not args.local_test and not os.environ.get("SSH_CONNECTION"):
        raise ValueError("Server requires an authenticated SSH session")
    channel = Frames(sys.stdin.buffer, sys.stdout.buffer, state)
    channel.send("hello", hello(state))
    peer = check_hello(state, channel.receive("hello"))
    receive_contributions(channel, state, inject_crash=not args.resume)
    send_contributions(channel, state)
    solution = state.solve()
    channel.send("candidate", solution)
    confirm = channel.receive("candidate_confirm")["payload"]
    if confirm["candidate_sha256"] != solution["candidate_sha256"] or confirm["aggregate_sha256"] != solution["aggregate_sha256"]:
        raise ValueError("Peers have different candidates")
    channel.send("done", {"candidate_sha256": solution["candidate_sha256"]})
    channel.receive("done_ack")
    state.finish({"transport": "direct_peer_ssh" if not args.local_test else "local_pipe_test",
                  "peer_pid": peer["pid"], "peer_same_candidate": True,
                  "ssh_connection_sha256": sha(os.environ.get("SSH_CONNECTION", "local-test").encode())})


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node", choices=["pocket4", "ai395"], required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--root", required=True)
    parser.add_argument("--round-id", required=True)
    parser.add_argument("--size", type=int, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--external")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--local-test", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    server(arguments())
