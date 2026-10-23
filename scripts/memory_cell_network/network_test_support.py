"""Process fixtures: real TCP workers and a real tiny decoder, no accuracy claim."""

import json
import os
from pathlib import Path
import subprocess
import sys
import time

from network_wire import server
from network_worker import Worker


class ServiceProcess:
    def __init__(
        self,
        root,
        role,
        key_file,
        *,
        node_id=None,
        authority=None,
        model=None,
        port=0,
        source_root=None,
        scope=None,
        cell_role="semantic",
    ):
        self.root, self.role = Path(root), role
        self.root.mkdir(parents=True, exist_ok=True)
        self.ready = self.root / "ready.json"
        self.arguments = [
            sys.executable,
            "-B",
            str(Path(__file__).with_name("network_serve.py")),
            role,
            "--root",
            str(self.root),
            "--key-file",
            str(key_file),
            "--ready-file",
            str(self.ready),
        ]
        if role == "worker":
            self.arguments += [
                "--node-id",
                node_id,
                "--authority",
                authority,
                "--model",
                str(model),
            ]
        elif source_root is not None:
            self.arguments += [
                "--source-root",
                str(source_root),
                "--scope",
                scope,
                "--cell-role",
                cell_role,
            ]
        self.port = port
        self.process = None
        self.log = None
        self.start()

    def start(self):
        self.ready.unlink(missing_ok=True)
        self.log = (self.root / "process.log").open("ab")
        self.process = subprocess.Popen(
            self.arguments + ["--port", str(self.port)],
            stdin=subprocess.DEVNULL,
            stdout=self.log,
            stderr=self.log,
        )
        deadline = time.monotonic() + 30
        while not self.ready.exists():
            if self.process.poll() is not None or time.monotonic() >= deadline:
                self.stop()
                raise AssertionError((self.root / "process.log").read_text()[-4000:])
            time.sleep(0.02)
        self.receipt = json.loads(self.ready.read_text())
        self.address = self.receipt["endpoint"]
        self.port = int(self.address.rsplit(":", 1)[1])

    def stop(self):
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=10)
        if self.log is not None:
            self.log.close()


def paused_worker(root, node_id, authority, key, model, started, resume, ready):
    worker = Worker(root, node_id, authority, key, model)
    original = worker.reader

    def reader(active, questions, control):
        started.set()
        if not resume.wait(30):
            raise ValueError("test callback release timed out")
        return original(active, questions, control)

    worker.reader = reader
    instance = server(worker, key)
    ready.put(
        dict(endpoint=f"http://127.0.0.1:{instance.server_port}", pid=os.getpid())
    )
    instance.serve_forever(poll_interval=0.1)
