"""Small POSIX engineering controls; no live SSH host or scientific panel runs."""

import copy
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import selectors
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

from distributed import Receiver, durable_write, encoded, hashed
from ssh_framed_io import MAX_FRAME, MAX_STDERR, Stream, WIRE, collect_stderr, terminate_owned_child, wait_owned_child
import ssh_snapshot
from test_direct_snapshot import fixture


def configurations(root):
    fixed, messages = fixture(root, [["127.0.0.1", 22], ["127.0.0.2", 22]])
    here = Path(ssh_snapshot.__file__).parent
    reference = here / "results/pft2_multihost.json"
    boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    roster = [{"alias": "local-engineering-" + str(node), "hostname": socket.gethostname(),
               "boot": boot, "uid": os.getuid(), "user": "local-engineering", "python": sys.executable,
               "stage": str(root / ("stage-" + str(node))), "address": "127.0.0." + str(node + 1),
               "interface": "lo"} for node in (0, 1)]
    result = []
    for node in (0, 1):
        config = {"schema": ssh_snapshot.SCHEMA, "deadline_seconds": 45,
                  "source_sha256": {name: ssh_snapshot.sha_file(here / name) for name in ssh_snapshot.SOURCES},
                  "frozen": fixed[node], "roster": roster, "reference": str(reference),
                  "reference_sha256": ssh_snapshot.sha_file(reference), "ssh": {"file_sha256": {}},
                  "remote_config_sha256": "b" * 64}
        config["context_id"] = ssh_snapshot.context(config)
        result.append(config)
    return result, messages


def pipe_peer(config, descriptors):
    """Local OS pipes only: the test must never claim a real SSH identity."""
    a_read, a_write, b_read, b_write = descriptors
    node = config["frozen"]["node"]
    reader, writer = (b_read, a_write) if node == 0 else (a_read, b_write)
    for fd in set(descriptors) - {reader, writer}:
        os.close(fd)
    projected, reference = ssh_snapshot.prepare(config)
    own = ssh_snapshot.identity(config, ("a" if node == 0 else "b") * 64)
    folder = Path(projected["directory"])
    folder.mkdir()
    stream = Stream(reader, writer, folder, node, projected["round_id"], config["context_id"], time.monotonic() + 4)
    try:
        value = ssh_snapshot.exchange(config, projected, reference, stream, own, "127.0.0.1 45000 127.0.0.2 22")
        durable_write(folder / "local-pipe-result.json", value)
    finally:
        os.close(reader)
        os.close(writer)


@unittest.skipUnless(sys.platform.startswith("linux"), "The fixed host qualification is Linux-only")
class SSHSnapshotTests(unittest.TestCase):
    def test_two_processes_exchange_original_statistics_over_direct_os_pipes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            configs, messages = configurations(root)
            descriptors = (*os.pipe(), *os.pipe())
            processes = [multiprocessing.get_context("fork").Process(target=pipe_peer, args=(config, descriptors))
                         for config in configs]
            try:
                for process in processes:
                    process.start()
                for fd in descriptors:
                    os.close(fd)
                for process in processes:
                    process.join(timeout=6)
                    self.assertEqual(process.exitcode, 0)
            finally:
                for process in processes:
                    if process.is_alive():
                        process.terminate()
                    process.join(timeout=2)
            results = [json.loads((root / str(node) / "local-pipe-result.json").read_text()) for node in (0, 1)]
            for key in ("candidate_sha256", "statistics_snapshot_id", "accepted_ids"):
                self.assertEqual(results[0][key], results[1][key])
            expected_ids = sorted(item["contribution_id"] for item in messages)
            for node, result in enumerate(results):
                self.assertEqual(result["accepted_ids"], expected_ids)
                self.assertEqual(result["effective_rank"], 8)
                self.assertLess(result["effective_direction_relative_error"], 1e-12)
                for event in result["transfers"]:
                    raw = (root / str(node) / "frames" / event["wire_sha256"]).read_bytes()
                    self.assertEqual(hashlib.sha256(raw).hexdigest(), event["wire_sha256"])
                    self.assertEqual(event["transferred_bytes"], len(raw))
                    self.assertEqual(event["status"], "complete")
                self.assertTrue(any(event["direction"] == "receive" for event in result["transfers"]))

    def test_fragmented_stream_uses_one_absolute_deadline_and_keeps_partial_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            left, right = socket.socketpair()
            stop = threading.Event()
            def slow_sender():
                try:
                    for byte in struct.pack("!I", 8) + b"{}      ":
                        if stop.wait(.035):
                            return
                        right.sendall(bytes([byte]))
                except OSError:
                    pass
            thread = threading.Thread(target=slow_sender)
            thread.start()
            started = time.monotonic()
            stream = Stream(left.fileno(), left.fileno(), temporary, 0, "round", "context", started + .12)
            try:
                with self.assertRaises(TimeoutError):
                    stream.receive("hello")
                self.assertLess(time.monotonic() - started, .7)
                self.assertGreater(stream.events[0]["frame_bytes"], 0)
                self.assertEqual(stream.events[0]["status"], "TimeoutError")
            finally:
                stop.set()
                thread.join()
                left.close()
                right.close()

    def test_oversized_prefix_and_replayed_sequence_fail_before_acceptance(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for label, packets in (("oversized", [struct.pack("!I", MAX_FRAME + 1)]),
                                   ("replay", [None, None])):
                folder = root / label
                folder.mkdir()
                left, right = socket.socketpair()
                stream = Stream(left.fileno(), left.fileno(), folder, 0, "round", "context", time.monotonic() + 1)
                try:
                    if label == "replay":
                        packet = {"schema": WIRE, "round_id": "round", "context_id": "context", "sender": 1,
                                  "recipient": 0, "sequence": 0, "kind": "hello", "body": {"value": 1}}
                        payload = encoded(packet).encode()
                        raw = struct.pack("!I", len(payload)) + payload
                        right.sendall(raw + raw)
                        self.assertEqual(stream.receive("hello"), {"value": 1})
                    else:
                        right.sendall(packets[0])
                    with self.assertRaises(ValueError):
                        stream.receive("hello")
                    self.assertEqual(stream.events[-1]["status"], "ValueError")
                finally:
                    left.close()
                    right.close()

    def test_roster_source_and_old_reference_substitution_fail(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            configs, messages = configurations(root)
            for mutate in (lambda c: c["source_sha256"].update({"ssh_snapshot.py": "f" * 64}),
                           lambda c: c["roster"][1].update({"address": "127.0.0.3"}),
                           lambda c: c.update({"reference_sha256": "f" * 64})):
                changed = copy.deepcopy(configs[0])
                mutate(changed)
                with self.assertRaises(ValueError):
                    ssh_snapshot.prepare(changed)
            projected, reference = ssh_snapshot.prepare(configs[0])
            receiver = Receiver(projected["header"])
            ssh_snapshot.accept_contribution(receiver, configs[0], messages[0], 0)
            malformed = {**messages[1], "client_id": "0"}
            with self.assertRaises(ValueError):
                ssh_snapshot.accept_contribution(receiver, configs[0], malformed, 1)
            self.assertEqual(list(receiver.messages), [messages[0]["contribution_id"]])
            ssh_snapshot.accept_contribution(receiver, configs[0], messages[1], 1)
            wrong_reference = copy.deepcopy(reference)
            wrong_reference["audit_candidate_integer_grid"][0] += 1
            folder = root / "candidate"
            folder.mkdir()
            with self.assertRaises(ValueError):
                ssh_snapshot.solve(receiver, configs[0], wrong_reference, folder)
            self.assertFalse((folder / "CANDIDATE.json").exists())

    def test_remote_connection_cannot_be_a_controller_relay(self):
        with tempfile.TemporaryDirectory() as temporary:
            configs, _ = configurations(Path(temporary))
            for connection in (None, "192.0.2.10 1234 127.0.0.2 22", "127.0.0.1 1234 127.0.0.2 2222"):
                with self.subTest(connection=connection), self.assertRaises(ValueError):
                    ssh_snapshot.check_connection(configs[0], connection)

    def test_stalled_owned_ssh_process_is_killed_and_reaped(self):
        process = subprocess.Popen([sys.executable, "-c",
                                    "import os,signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);os.write(1,b'1');time.sleep(30)"],
                                   stdout=subprocess.PIPE, start_new_session=True)
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                self.assertTrue(selector.select(timeout=2))
            self.assertEqual(process.stdout.read(1), b"1")
            started = time.monotonic()
            self.assertEqual(terminate_owned_child(process), -signal.SIGKILL)
            self.assertLess(time.monotonic() - started, 5)
            with self.assertRaises(ProcessLookupError):
                os.kill(process.pid, 0)
        finally:
            terminate_owned_child(process)
            process.stdout.close()

    def test_exited_leader_with_descendant_stderr_does_not_block_cleanup(self):
        code = """import os,signal,time
ready_read,ready_write=os.pipe()
child=os.fork()
if child==0:
    os.close(ready_read)
    os.close(1)
    signal.signal(signal.SIGTERM,signal.SIG_IGN)
    os.write(2,b'descendant owns stderr\\n')
    os.write(ready_write,b'1')
    os.close(ready_write)
    time.sleep(30)
else:
    os.close(ready_write)
    os.read(ready_read,1)
    print(child,flush=True)
    os._exit(0)
"""
        process = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, start_new_session=True)
        state, thread, stop, cancel = collect_stderr(process, time.monotonic() + .2)
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                self.assertTrue(selector.select(timeout=2))
            child = int(process.stdout.readline())
            self.assertEqual(wait_owned_child(process, time.monotonic() + 2), 0)
            self.assertIsNone(process.returncode)
            thread.join(timeout=.5)
            self.assertFalse(thread.is_alive())
            self.assertTrue(state["deadline_reached"])
            started = time.monotonic()
            self.assertEqual(terminate_owned_child(process), 0)
            process.stderr.close()
            self.assertLess(time.monotonic() - started, .5)
            child_state = Path(f"/proc/{child}/stat")
            until = time.monotonic() + .5
            while child_state.exists() and child_state.read_text().split()[2] != "Z" and time.monotonic() < until:
                time.sleep(.01)
            self.assertTrue(not child_state.exists() or child_state.read_text().split()[2] == "Z")
        finally:
            stop.set()
            terminate_owned_child(process)
            thread.join(timeout=.2)
            process.stdout.close()
            process.stderr.close()

    def test_group_identity_is_reserved_until_all_signals_then_reaped_once(self):
        process = subprocess.Popen([sys.executable, "-c", "pass"], start_new_session=True)
        observed = []
        real_killpg = os.killpg
        def checked_signal(group, signum):
            self.assertEqual(group, process.pid)
            self.assertIsNone(process.returncode)
            status = os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
            self.assertIsNotNone(status)
            observed.append(signum)
            return real_killpg(group, signum)
        try:
            self.assertEqual(wait_owned_child(process, time.monotonic() + 2), 0)
            self.assertIsNone(process.returncode)
            with mock.patch.object(os, "killpg", checked_signal), mock.patch.object(process, "wait", wraps=process.wait) as reap:
                self.assertEqual(terminate_owned_child(process), 0)
                self.assertEqual(reap.call_count, 1)
                self.assertEqual(terminate_owned_child(process), 0)
                self.assertEqual(reap.call_count, 1)
            self.assertEqual(observed, [signal.SIGTERM, signal.SIGKILL])
            with self.assertRaises(ChildProcessError):
                os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
        finally:
            terminate_owned_child(process)

    def test_stderr_overflow_only_notifies_the_owner_and_retains_the_bound(self):
        process = subprocess.Popen([sys.executable, "-c", f"import os;os.write(2,b'x'*{MAX_STDERR + 2})"],
                                   stderr=subprocess.PIPE, start_new_session=True)
        state, thread, stop, cancel = collect_stderr(process, time.monotonic() + 2)
        try:
            with mock.patch.object(os, "killpg", wraps=os.killpg) as signals:
                thread.join(timeout=2)
                self.assertFalse(thread.is_alive())
                self.assertTrue(state["overflow"])
                self.assertTrue(cancel.is_set())
                self.assertEqual(len(state["raw"]), MAX_STDERR)
                self.assertGreater(state["observed_bytes"], MAX_STDERR)
                self.assertEqual(signals.call_count, 0)
            self.assertIsNone(process.returncode)
        finally:
            stop.set()
            terminate_owned_child(process)
            thread.join(timeout=.2)
            process.stderr.close()

    def test_configuration_is_parsed_from_the_same_bytes_that_were_pinned(self):
        class PreparationObserved(Exception):
            pass
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "config.json"
            original = {"identity": "admitted"}
            path.write_text(json.dumps(original))
            digest = ssh_snapshot.sha_file(path)
            original_read = Path.read_bytes
            reads = []
            def replace_after_read(current):
                raw = original_read(current)
                if current == path:
                    reads.append(current)
                    current.write_text(json.dumps({"identity": "replacement"}))
                return raw
            with mock.patch.object(Path, "read_bytes", replace_after_read), mock.patch.object(
                ssh_snapshot, "prepare", side_effect=PreparationObserved
            ) as prepare:
                with self.assertRaises(PreparationObserved):
                    ssh_snapshot.run(path, digest)
            self.assertEqual(reads, [path])
            self.assertEqual(prepare.call_args.args, (original,))


if __name__ == "__main__":
    unittest.main()
