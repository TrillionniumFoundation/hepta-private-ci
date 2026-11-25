"""Bounded engineering controls; no research matrix or new labels are generated."""

import copy
import hashlib
import json
from pathlib import Path
import random
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import zlib

import numpy as np

import direct_snapshot
from distributed import array_hash, hashed, seal
from transport import Peer, pack, receive, worker


def fixture(root, addresses):
    here = Path(__file__).parent
    rng = random.Random(731 * 1009 + 8)
    parent = [rng.gauss(0, .1) for _ in range(8)]
    sources = {name: hashlib.sha256((here / name).read_bytes()).hexdigest() for name in direct_snapshot.SOURCES}
    header = {"size": 8, "parent_id": array_hash(parent), "coordinate_id": array_hash(np.eye(8)),
              "objective_id": hashed({"ridge": .01, "loss": "sum squared residual", "version": 1})}
    configurations, messages = [], []
    for node, host in enumerate(("pocket4", "ai395")):
        archive = here / "results" / f"pft2_multihost_{host}.json.zlib"
        raw = archive.read_bytes()
        original = json.loads(zlib.decompress(raw))
        record = next(record for record in original["records"] if record["size"] == 8 and record["seed"] == 731)
        message = seal({**header, "client_id": str(node), "count": record["sample_count"],
                        "data_sha256": hashed(record["data_hashes"]), "gram": record["gram"], "moment": record["moment"]})
        messages.append(message)
        configurations.append({"schema": direct_snapshot.SCHEMA, "scope": "engineering_frozen_statistics",
                               "training_runs": 0, "real_user_adoptions": 0, "source_sha256": sources,
                               "hosts": ["pocket4", "ai395"], "addresses": addresses, "node": node,
                               "deadline_seconds": 45, "retry_interval_seconds": 1,
                               "archive": str(archive), "archive_sha256": hashlib.sha256(raw).hexdigest(),
                               "original_source_sha256": original["source_sha256"], "size": 8, "seed": 731,
                               "record_sha256": hashed(record), "parent": parent, "round_id": "local-engineering-only",
                               "output": str(root / str(node))})
    for config in configurations:
        config["expected_contributions"] = [message["payload_sha256"] for message in messages]
        config["expected_contribution_ids"] = [message["contribution_id"] for message in messages]
    return configurations, messages


class DirectSnapshotTests(unittest.TestCase):
    def test_slow_fragmented_frame_obeys_one_absolute_deadline(self):
        left, right = socket.socketpair()
        stop = threading.Event()
        def slow_sender():
            try:
                for byte in b"\x00\x00\x00\x08{}      ":
                    if stop.wait(.04):
                        break
                    right.sendall(bytes([byte]))
            except OSError:
                pass
        thread = threading.Thread(target=slow_sender)
        thread.start()
        started = time.monotonic()
        try:
            with self.assertRaises(TimeoutError):
                receive(left, deadline=started + .13)
            self.assertLess(time.monotonic() - started, .8)
        finally:
            stop.set()
            left.close()
            right.close()
            thread.join()

    def test_delivery_failure_closes_the_listener(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                address = list(listener.getsockname())
            configs, _ = fixture(root, [address, ["127.0.0.2", address[1]]])
            folder = root / "0"
            folder.mkdir()
            projected = direct_snapshot.prepare(configs[0], folder)
            projected.update(deadline_seconds=.12, retry_interval_seconds=.02)
            path = root / "worker.json"
            path.write_text(json.dumps(projected))
            with self.assertRaises(TimeoutError):
                worker(path, False)
            with socket.socket() as listener:
                listener.bind(tuple(address))
            self.assertFalse((folder / "result.json").exists())

    def test_two_real_processes_exchange_fixed_stats_and_retain_original_frames(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            reservations = [socket.socket() for _ in range(2)]
            for connection in reservations:
                connection.bind(("127.0.0.1", 0))
            addresses = [list(connection.getsockname()) for connection in reservations]
            for connection in reservations:
                connection.close()
            configs, messages = fixture(root, addresses)
            processes = []
            for node, config in enumerate(configs):
                path = root / f"config-{node}.json"
                path.write_text(json.dumps(config))
                processes.append(subprocess.Popen([sys.executable, str(Path(direct_snapshot.__file__)), str(path),
                                                   "--expected", hashlib.sha256(path.read_bytes()).hexdigest()],
                                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
            for process in processes:
                stdout, stderr = process.communicate(timeout=12)
                self.assertEqual(process.returncode, 0, stdout + stderr)
            results = [json.loads((root / str(node) / "result.json").read_text()) for node in range(2)]
            self.assertEqual(results[0]["candidate_sha256"], results[1]["candidate_sha256"])
            self.assertEqual(results[0]["statistics_snapshot_id"], results[1]["statistics_snapshot_id"])
            for node, result in enumerate(results):
                self.assertEqual(set(result["accepted_ids"]), {message["contribution_id"] for message in messages})
                self.assertEqual(json.loads((root / str(node) / "END.json").read_text())["status"], "COMPLETE")
                for event in result["transfers"]:
                    if event["frame_bytes"]:
                        raw = (root / str(node) / "frames" / event["wire_sha256"]).read_bytes()
                        self.assertEqual(hashlib.sha256(raw).hexdigest(), event["wire_sha256"])
                        self.assertEqual(event["socket_local"][0], "127.0.0.1")
            with self.assertRaises(FileExistsError):
                direct_snapshot.run(root / "config-0.json", hashlib.sha256((root / "config-0.json").read_bytes()).hexdigest())

    def test_snapshot_source_parent_and_peer_pins_are_required_before_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            configs, _ = fixture(root, [["127.0.0.1", 31001], ["127.0.0.2", 31002]])
            for key, value in (("archive_sha256", "f" * 64), ("record_sha256", "f" * 64),
                               ("source_sha256", {}), ("parent", [0.] * 8),
                               ("expected_contributions", ["f" * 64, "e" * 64])):
                changed = {**configs[0], key: value}
                with self.subTest(key=key), self.assertRaises(ValueError):
                    direct_snapshot.prepare(changed, root / "0")
            self.assertFalse((root / "0").exists())

    def test_tcp_peer_rejects_source_owner_and_registered_payload_substitution(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            configs, messages = fixture(root, [["127.0.0.1", 31001], ["127.0.0.2", 31002]])
            folder = root / "0"
            folder.mkdir()
            peer = Peer(direct_snapshot.prepare(configs[0], folder), False)
            valid = {"sender": 1, "recipient": 0, "round_id": configs[0]["round_id"], "kind": "contribution", "message": messages[1]}
            changed_owner = copy.deepcopy(valid)
            changed_owner["message"]["client_id"] = "0"
            changed_payload = copy.deepcopy(valid)
            changed_payload["message"] = seal({**messages[1], "data_sha256": "f" * 64})
            for source, packet in (("127.0.0.1", valid), ("127.0.0.2", changed_owner), ("127.0.0.2", changed_payload)):
                with self.subTest(source=source), socket.socket() as listener:
                    listener.bind(("127.0.0.1", 0))
                    listener.listen()
                    with socket.create_connection(listener.getsockname(), source_address=(source, 0)) as client:
                        connection, _ = listener.accept()
                        with connection:
                            client.sendall(pack(packet)[0])
                            with self.assertRaises(ValueError):
                                peer.incoming(connection)
                self.assertEqual(len(peer.receiver.messages), 1)


if __name__ == "__main__":
    unittest.main()
