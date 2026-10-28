"""Durable, complete RPC evidence for a local research adapter."""

import json
from pathlib import Path
import time

from experiments.adaptive_neuron_v2.ledger import sha, write_json_exclusive
from experiments.adaptive_neuron_v2.owner.common import Native


class LoggedProcess:
    def __init__(self, binary, root, records, label):
        self.root = Path(root)
        self.records = Path(records) / label
        self.records.mkdir(parents=True, exist_ok=False)
        self.native = Native(binary, root)
        self.closed = False

    def call(self, request, *, expect_error=False):
        before = len(self.native.rows)
        sent = time.monotonic_ns()
        try:
            return self.native.call(request, expect_error=expect_error)
        finally:
            received = time.monotonic_ns()
            for index in range(before, len(self.native.rows)):
                self.native.rows[index]["sent_monotonic_ns"] = sent
                self.native.rows[index]["received_monotonic_ns"] = received
                write_json_exclusive(
                    self.records / f"rpc.{index:04d}.json", self.native.rows[index]
                )

    def close(self):
        if not self.closed:
            receipt = self.native.close()
            receipt["cpu_accounting"] = (
                "Child CPU is a process-lifetime observation interval and can overlap "
                "another open process; the enclosing stage CPU is authoritative."
            )
            write_json_exclusive(self.records / "PROCESS.json", receipt)
            self.closed = True


def load_rpc(root):
    return [json.loads(p.read_text()) for p in sorted(Path(root).glob("*/rpc.*.json"))]


def file_manifest(root):
    return {
        str(p.relative_to(root)): {"sha256": sha(p), "bytes": p.stat().st_size}
        for p in sorted(Path(root).rglob("*"))
        if p.is_file()
    }
