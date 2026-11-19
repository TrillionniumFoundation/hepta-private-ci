"""Independent mTLS replica processes: loss, quorum refusal, restart and repair."""

from dataclasses import asdict
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from cryptography.hazmat.primitives import serialization
from authority_client import QuorumClient, QuorumUnavailable
from authority_contract import decode, encode
from distributed_test_support import certificates, membership
from rpc_costs import MeteredRPC


class ReplicaProcess:
    def __init__(self, root, config):
        self.root, self.config = Path(root), dict(config)
        self.root.mkdir()
        self.ready = self.root / "ready.json"
        self.start()

    def start(self):
        self.ready.unlink(missing_ok=True)
        config = self.root / "config.json"
        config.write_bytes(encode(self.config))
        self.log = (self.root / "process.log").open("ab")
        self.process = subprocess.Popen(
            [
                sys.executable,
                "-B",
                str(Path(__file__).with_name("distributed_serve.py")),
                "--config",
                str(config),
                "--ready",
                str(self.ready),
            ],
            stdin=subprocess.DEVNULL,
            stdout=self.log,
            stderr=self.log,
        )
        deadline = time.monotonic() + 15
        while not self.ready.exists():
            if self.process.poll() is not None or time.monotonic() >= deadline:
                self.stop()
                raise AssertionError((self.root / "process.log").read_text())
            time.sleep(0.02)
        self.identity = decode(self.ready.read_bytes())
        self.address = f"https://127.0.0.1:{self.identity['port']}"
        self.config.update(port=self.identity["port"], creation="existing")

    def stop(self):
        if self.process.poll() is None:
            self.process.kill()
            self.process.wait(timeout=10)
        self.log.close()


class ProcessTests(unittest.TestCase):
    def test_actual_process_loss_restart_repair_and_prepared_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            members, writer, keys = membership()
            certs = certificates(
                root / "certs", dict(server="server", publisher="client")
            )
            public = dict(
                authority_id=members.authority_id,
                writer_key=members.writer_key,
                member_keys=dict(members.member_keys),
            )
            grant = dict(
                certificate_sha256=certs["publisher"]["certificate_sha256"],
                operations=["read", "prepare", "commit", "pending", "history"],
                scopes=["scope-a"],
                evidence_roots=[],
            )
            processes = {}
            try:
                for name, key in keys.items():
                    key_file = root / (name + ".key")
                    key_file.write_bytes(
                        key.private_bytes(
                            serialization.Encoding.PEM,
                            serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption(),
                        )
                    )
                    key_file.chmod(0o600)
                    config = dict(
                        role="replica",
                        root=str(root / (name + "-state")),
                        credentials=asdict(certs["server"]["credentials"]),
                        grants=[grant],
                        host="127.0.0.1",
                        port=0,
                        member_id=name,
                        membership=public,
                        private_key_file=str(key_file),
                        creation="genesis",
                    )
                    processes[name] = ReplicaProcess(root / name, config)
                self.assertEqual(
                    len({p.identity["pid"] for p in processes.values()}), 3
                )
                self.assertEqual(
                    len({p.identity["boot_id_sha256"] for p in processes.values()}), 1
                )
                rpc = MeteredRPC(root / "rpc.jsonl")
                client = QuorumClient(
                    members,
                    {name: p.address for name, p in processes.items()},
                    certs["publisher"]["credentials"],
                    timeout=0.5,
                    rpc=rpc,
                )
                view = dict(scope="scope-a", epoch=0, revoked=[])
                first = client.proposal("scope-a", view, [], writer)
                client.publish(first)
                processes["replica-2"].stop()
                client.publish(
                    client.proposal("scope-a", dict(view, epoch=1), [], writer)
                )
                processes["replica-1"].stop()
                with self.assertRaises(QuorumUnavailable):
                    client.read("scope-a")
                processes["replica-2"].start()
                self.assertEqual(
                    client.read("scope-a")["proposal"]["state"]["sequence"], 2
                )
                self.assertEqual(client.repair("scope-a", "replica-2")["sequence"], 2)
                processes["replica-1"].start()
                proposal = client.proposal("scope-a", dict(view, epoch=2), [], writer)
                for name in ("replica-0", "replica-1"):
                    rpc(
                        processes[name].address,
                        client.credentials,
                        dict(op="prepare", proposal=proposal),
                    )
                    processes[name].stop()
                    processes[name].start()
                recovered = client.recover_pending("scope-a")
                self.assertEqual(recovered["certificate"]["proposal"], proposal)
                self.assertEqual(client.read("scope-a")["proposal"], proposal)
                rows = [decode(line) for line in rpc.journal.read_bytes().splitlines()]
                self.assertTrue(any(row.get("ok") is False for row in rows))
                self.assertTrue(
                    all(
                        row["request_payload_bytes"] > 0
                        for row in rows
                        if row["phase"] == "started"
                    )
                )
            finally:
                for process in processes.values():
                    process.stop()


if __name__ == "__main__":
    unittest.main()
