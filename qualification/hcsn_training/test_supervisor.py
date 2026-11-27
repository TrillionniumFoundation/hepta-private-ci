"""Actual Linux subprocess lifecycle and immutable output binding fixtures."""

from concurrent.futures import ThreadPoolExecutor
import copy
import json
import os
import py_compile
from pathlib import Path
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import torch
from .test_joint_graph import fixture
from . import supervisor
from .supervisor_store import (alive, decode, encoded, identity, job_path, open_store, process_identity,
                               read_bytes, sha, validate_outputs)


@unittest.skipUnless(sys.platform == "linux", "concrete supervisor v1 uses Linux process incarnations")
class SupervisorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)

    def setUp(self):
        retained = Path(os.environ.get("HCSN_SUPERVISOR_TEST_ARTIFACTS", tempfile.gettempdir())).resolve()
        retained.mkdir(parents=True, exist_ok=True)
        self.directory = Path(tempfile.mkdtemp(prefix="hcsn-supervisor-", dir=retained))
        print(f"retained_supervisor_fixture={self.directory}", flush=True)
        self.started = {}
        self.addCleanup(self.cleanup_processes)
        self.root = self.directory/"private-jobs"
        self.script = Path(__file__).with_name("supervisor.py").resolve()
        self.cli = [sys.executable, "-I", "-B", str(self.script), "--root", str(self.root)]
        subprocess.run([*self.cli, "--initialize"], check=True, capture_output=True, timeout=10)
        self.request = fixture(self.directory)[1]
        self.host_id = open_store(self.root)["host_id"]

    def cleanup_processes(self):
        for command in self.started.values():
            try:
                self.call(self.cancel(command, label="cleanup-"+command["target"]["job_id"]))
            except (OSError, AssertionError, subprocess.SubprocessError):
                pass
            job = job_path(self.root, command["target"])
            for name in ("runner.json", "worker.json"):
                try:
                    process = decode(read_bytes(job/name, 4096))
                    if alive(process, self.host_id):
                        self.signal_process(process, signal.SIGKILL)
                except (OSError, ValueError, AssertionError):
                    pass

    def signal_process(self, process, sig):
        descriptor = os.pidfd_open(process["process_id"])
        try:
            self.assertEqual(process_identity(process["process_id"], self.host_id), process)
            signal.pidfd_send_signal(descriptor, sig)
            if sig == signal.SIGKILL:
                poller = select.poll()
                poller.register(descriptor, select.POLLIN)
                self.assertTrue(poller.poll(5000))
        finally:
            os.close(descriptor)

    def call(self, command):
        if command["action"] == "start":
            self.started[command["target"]["job_id"]] = command
        result = subprocess.run(self.cli, input=encoded(command), capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
        return json.loads(result.stdout)

    def start(self, label="job", request=None):
        payload = encoded(self.request if request is None else request).decode()
        job = identity("provider-effect:v1:"+sha(label.encode()), sha(payload.encode()))
        return dict(schema_version=1, action="start", dispatch=job, target=job, payload=payload)

    def status(self, start):
        return dict(start, action="status", payload=None)

    def cancel(self, start, label="cancel"):
        target = start["target"]
        dispatch = identity("provider-effect:v1:"+sha(label.encode()), sha(encoded(target)))
        return dict(schema_version=1, action="cancel", dispatch=dispatch, target=target, payload=None)

    def until(self, command, states, timeout=30):
        deadline = time.monotonic()+timeout
        while time.monotonic() < deadline:
            observed = self.call(self.status(command))
            if observed["state"] in states:
                return observed
            time.sleep(.03)
        self.fail(f"supervisor did not reach {states}: {observed}")

    def test_real_worker_lost_reply_reuse_cold_status_and_tamper(self):
        command = self.start()
        self.call(command)  # Deliberately discard this launch observation.
        result = self.until(command, {"succeeded", "failed"})
        self.assertEqual(result["state"], "succeeded")
        job = job_path(self.root, command["target"])
        runner = (job/"runner.json").read_bytes()
        self.assertEqual(self.call(command), result)
        self.assertEqual((job/"runner.json").read_bytes(), runner)
        self.assertEqual(self.call(self.status(command)), result)
        changed = copy.deepcopy(self.request)
        changed["targets"][0][0] += 1
        conflict = self.start(request=changed)
        self.assertEqual(self.call(conflict)["state"], "unknown")
        self.assertEqual(len(list((self.root/"jobs").iterdir())), 1)
        self.assertEqual(self.call(self.cancel(command))["state"], "succeeded")
        output = job/command["target"]["output_id"]
        receipt = output/"receipt.json"
        receipt.write_bytes(receipt.read_bytes()+b" ")
        self.assertEqual(self.call(self.status(command))["state"], "unknown")
        self.assertEqual(self.call(command)["state"], "unknown")
        self.assertEqual((job/"runner.json").read_bytes(), runner)

    def test_prestart_cancel_binds_payload_and_status_is_read_only(self):
        command = self.start("prestart")
        before = sorted(str(path.relative_to(self.root)) for path in self.root.rglob("*"))
        self.assertEqual(self.call(self.status(command))["state"], "unknown")
        self.assertEqual(sorted(str(path.relative_to(self.root)) for path in self.root.rglob("*")), before)
        cancellation = self.cancel(command, "early-cancel")
        self.assertEqual(self.call(cancellation)["state"], "unknown")
        changed = copy.deepcopy(self.request)
        changed["targets"][0][0] += 1
        conflict = self.start("prestart", changed)
        self.assertEqual(self.call(conflict)["state"], "unknown")
        self.assertFalse(job_path(self.root, command["target"]).exists())
        result = self.call(command)
        self.assertEqual(result["state"], "cancelled")
        self.assertIsNone(result["process"])
        self.assertFalse((job_path(self.root, command["target"])/"runner.json").exists())
        self.assertEqual(self.call(command), result)
        self.assertEqual(self.call(cancellation)["state"], "cancelled")

    def test_concurrent_same_key_launches_one_worker(self):
        command = self.start("concurrent")
        with ThreadPoolExecutor(max_workers=3) as pool:
            replies = list(pool.map(self.call, [command]*3))
        self.assertTrue(all(reply["target"] == command["target"] for reply in replies))
        terminal = self.until(command, {"succeeded", "failed"})
        self.assertEqual(terminal["state"], "succeeded")
        self.assertEqual(len(list((self.root/"jobs").iterdir())), 1)
        self.assertEqual(self.call(command), terminal)

    def test_cancel_serializes_with_reservation_setup(self):
        command = self.start("setup-race")
        cancellation = self.cancel(command, "setup-cancel")
        entered, release = threading.Event(), threading.Event()
        original = supervisor.sources
        popen, runners = subprocess.Popen, []
        def retain_runner(*args, **kwargs):
            child = popen(*args, **kwargs)
            runners.append(child)
            return child
        def paused_sources():
            entered.set()
            if not release.wait(1):
                raise RuntimeError("test reservation gate expired")
            return original()
        self.started[command["target"]["job_id"]] = command
        with patch.object(supervisor, "sources", paused_sources), \
                patch.object(supervisor.subprocess, "Popen", retain_runner), ThreadPoolExecutor(max_workers=2) as pool:
            starting = pool.submit(supervisor.dispatch, self.root, open_store(self.root), command)
            self.assertTrue(entered.wait(1))
            cancelling = pool.submit(supervisor.dispatch, self.root, open_store(self.root), cancellation)
            self.assertFalse(cancelling.done())
            release.set()
            starting.result(timeout=5)
            cancelling.result(timeout=5)
        terminal = self.until(cancellation, {"cancelled", "succeeded", "failed"})
        self.assertEqual(terminal["state"], "cancelled")
        for runner in runners:
            runner.wait(timeout=5)

    @unittest.skipUnless(hasattr(os, "pidfd_open") and hasattr(signal, "pidfd_send_signal"), "pidfd required")
    def test_dead_runner_stays_unknown_until_explicit_orphan_cancel(self):
        request = copy.deepcopy(self.request)
        request["optimizer_steps"] = request["limits"]["max_optimizer_steps"] = 64
        command = self.start("orphan", request)
        self.call(command)
        running = self.until(command, {"running", "succeeded", "failed"})
        self.assertEqual(running["state"], "running")
        job = job_path(self.root, command["target"])
        limits = Path(f"/proc/{running['process']['process_id']}/limits").read_text()
        self.assertRegex(limits, r"Max cpu time\s+300\s+300")
        self.signal_process(decode(read_bytes(job/"runner.json", 4096)), signal.SIGKILL)
        before = sorted(path.name for path in job.iterdir() if path.name != command["target"]["output_id"])
        self.assertEqual(self.call(self.status(command))["state"], "unknown")
        self.assertEqual(sorted(path.name for path in job.iterdir()
                                if path.name != command["target"]["output_id"]), before)
        self.assertTrue(alive(running["process"], self.host_id))
        terminal = self.call(self.cancel(command, "orphan-cancel"))
        self.assertEqual(terminal["state"], "cancelled")
        self.assertFalse(alive(running["process"], self.host_id))
        self.assertEqual(len(list(job.glob("orphan-stop-*.result.json"))), 1)
        self.assertEqual(self.call(command)["state"], "cancelled")

    @unittest.skipUnless(hasattr(os, "pidfd_open") and hasattr(signal, "pidfd_send_signal"), "pidfd required")
    def test_completed_orphan_outputs_are_preserved_without_claiming_success(self):
        command = self.start("completed-orphan")
        self.call(command)
        running = self.until(command, {"running", "succeeded", "failed"})
        self.assertEqual(running["state"], "running")
        job = job_path(self.root, command["target"])
        runner = decode(read_bytes(job/"runner.json", 4096))
        self.signal_process(runner, signal.SIGSTOP)
        output = job/command["target"]["output_id"]
        deadline = time.monotonic()+20
        while alive(running["process"], self.host_id) and time.monotonic() < deadline:
            time.sleep(.03)
        self.assertFalse(alive(running["process"], self.host_id))
        evidence = validate_outputs(job, decode(read_bytes(job/"reservation.json", 2*1024*1024)))
        self.signal_process(runner, signal.SIGKILL)
        self.assertEqual(self.call(self.cancel(command, "completed-orphan-cancel"))["state"], "unknown")
        self.assertEqual(self.call(command)["state"], "unknown")
        self.assertFalse((job/"terminal.json").exists())
        self.assertEqual(sha(read_bytes(output/"candidate.pt", 32*1024*1024)), evidence["candidate_sha256"])

    def test_every_handoff_digest_and_count_matches_diagnostics(self):
        command = self.start("handoff")
        self.call(command)
        self.assertEqual(self.until(command, {"succeeded", "failed"})["state"], "succeeded")
        job = job_path(self.root, command["target"])
        reservation = decode(read_bytes(job/"reservation.json", 2*1024*1024))
        path = job/command["target"]["output_id"]/"handoff.bin"
        original = read_bytes(path, 439)
        (self.directory/"original-handoff.bin").write_bytes(original)
        prefix = len(b"hepta.hcsn.task-bp-handoff.v1\0\0")
        for index in range(11):
            altered = bytearray(original)
            altered[prefix+32*index] ^= 1
            with patch("qualification.hcsn_training.supervisor_store.read_bytes", side_effect=
                       lambda file, limit=1024*1024: bytes(altered) if file == path else read_bytes(file, limit)):
                with self.subTest(digest=index), self.assertRaises(ValueError):
                    validate_outputs(job, reservation)
        for index in range(7):
            altered = bytearray(original)
            altered[prefix+11*32+8*index+7] ^= 1
            with patch("qualification.hcsn_training.supervisor_store.read_bytes", side_effect=
                       lambda file, limit=1024*1024: bytes(altered) if file == path else read_bytes(file, limit)):
                with self.subTest(count=index), self.assertRaises(ValueError):
                    validate_outputs(job, reservation)

    def test_nonregular_reads_and_nonfinite_json_fail_within_bound(self):
        fifo = self.directory/"untrusted-fifo"
        os.mkfifo(fifo)
        code = "from qualification.hcsn_training.supervisor_store import read_bytes; import sys; read_bytes(sys.argv[1])"
        result = subprocess.run([sys.executable, "-c", code, str(fifo)], cwd=Path(__file__).resolve().parents[2],
                                capture_output=True, timeout=3)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"file identity", result.stderr)
        with self.assertRaises(ValueError):
            decode(b'{"number":1e999}')

    def test_cli_ignores_timestamp_valid_bytecode_from_checkout(self):
        source = self.directory/"checkout"/"qualification"/"hcsn_training"
        source.mkdir(parents=True)
        (source/"__init__.py").write_text("")
        (source.parent/"__init__.py").write_text("")
        script = source/"supervisor.py"
        shutil.copyfile(self.script, script)
        module = source/"supervisor_store.py"
        trusted = self.script.with_name("supervisor_store.py").read_bytes()
        counterfeit = b"raise RuntimeError('stale checkout bytecode executed')\n"
        module.write_bytes(counterfeit+b" "*(len(trusted)-len(counterfeit)))
        timestamp = int(time.time())
        os.utime(module, (timestamp, timestamp))
        py_compile.compile(str(module), doraise=True, invalidation_mode=py_compile.PycInvalidationMode.TIMESTAMP)
        module.write_bytes(trusted)
        os.utime(module, (timestamp, timestamp))
        store = self.directory/"bytecode-test-store"
        result = subprocess.run([sys.executable, "-I", "-B", str(script), "--root", str(store), "--initialize"],
                                capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
        self.assertTrue((store/"store.json").is_file())

    def test_cancel_only_after_owned_worker_termination(self):
        request = copy.deepcopy(self.request)
        request["optimizer_steps"] = request["limits"]["max_optimizer_steps"] = 64
        command = self.start("cancel-target", request)
        self.call(command)
        running = self.until(command, {"running", "succeeded", "failed"})
        self.assertEqual(running["state"], "running")
        cancellation = self.cancel(command)
        self.call(cancellation)
        terminal = self.until(cancellation, {"cancelled", "succeeded", "failed"})
        self.assertEqual(terminal["state"], "cancelled")
        self.assertIsNotNone(terminal["evidence"]["receipt_sha256"])
        self.assertEqual(terminal["process"], running["process"])
        self.assertEqual(self.call(command)["state"], "cancelled")
        self.assertEqual(self.call(cancellation), terminal)

    def test_empty_reservation_missing_job_and_failed_worker_never_relaunch(self):
        command = self.start("unacknowledged")
        self.assertEqual(self.call(self.status(command))["state"], "unknown")
        self.assertFalse(job_path(self.root, command["target"]).exists())
        job_path(self.root, command["target"]).mkdir()
        self.assertEqual(self.call(command)["state"], "unknown")
        self.assertFalse((job_path(self.root, command["target"])/"runner.json").exists())
        failed_request = copy.deepcopy(self.request)
        failed_request["mechanism"] = "ndu_score"
        failed = self.start("invalid-loss", failed_request)
        self.call(failed)
        result = self.until(failed, {"failed"})
        self.assertEqual(self.call(failed), result)
        self.assertIsNone(result["evidence"]["candidate_sha256"])
