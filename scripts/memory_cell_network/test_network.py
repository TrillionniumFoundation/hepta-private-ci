"""Real TCP/process lifecycle with trained tiny-decoder checkpoint bytes."""

import base64
from concurrent.futures import ThreadPoolExecutor
import json
import multiprocessing
import os
from pathlib import Path
import select
import shutil
import signal
import sys
import tempfile
import time
import unittest

from network_checkpoints import pack
from network_client import NetworkClient
from network_test_support import ServiceProcess, paused_worker
from network_wire import RemoteError, call
from parametric_model import SourceMemoryCell
import test_parametric_model as tiny


def decoder_rows(result):
    return [
        {key: value for key, value in row.items() if key != "seconds"}
        for row in result["journal"]["rows"]
    ]


class NetworkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tiny.SourceMemoryCellTests.setUpClass()
        cls.addClassCleanup(tiny.SourceMemoryCellTests.tearDownClass)
        cls.base = tiny.SourceMemoryCellTests.base
        cls.artifacts = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.artifacts.cleanup)
        cls.versions = []
        for label, value, source in (("ancestor", "red", "a"), ("clean", "blue", "b")):
            cell = SourceMemoryCell(cls.base)
            cell.reset("alpha")
            receipt = cell.fit_sources(
                [tiny.fact("one", value, source)], 4, 0.001, tiny.TEMPLATES
            )
            directory = Path(cls.artifacts.name) / label
            pin = cell.save(directory, receipt)
            cls.versions.append((directory, pin, [source * 64]))

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.key = os.urandom(32)
        self.key_file = self.root / "key"
        self.key_file.write_bytes(self.key)
        self.authority = self.process("authority", "authority")
        self.a = self.process("a", "worker", node_id="a")
        self.b = self.process("b", "worker", node_id="b")
        self.client = NetworkClient(
            self.authority.address, {"a": self.a.address, "b": self.b.address}, self.key
        )
        directory, pin, roots = self.versions[0]
        self.initial = dict(
            scope="alpha",
            cell_id="memory",
            node_id="a",
            generation=0,
            manifest_sha256=pin,
            roots=roots,
        )
        self.client.stage("a", directory, pin, "alpha")
        self.client.publish(self.initial, None)
        self.request = dict(
            op="read",
            scope="alpha",
            cell_id="memory",
            questions=["What is the color of one?"],
            control="adapter",
        )

    def process(self, name, role, **options):
        if role == "worker":
            options.update(authority=self.authority.address, model=self.base)
        result = ServiceProcess(self.root / name, role, self.key_file, **options)
        self.addCleanup(result.stop)
        return result

    def counts(self):
        return {
            name: call(process.address, self.key, {"op": "status"})["model_callbacks"]
            for name, process in (("a", self.a), ("b", self.b))
        }

    def revoke(self):
        return call(
            self.authority.address,
            self.key,
            dict(
                op="frontier", frontier=dict(scope="alpha", epoch=1, revoked=["a" * 64])
            ),
        )

    def test_real_process_migration_controls_revocation_restart_and_clean_replay(self):
        self.assertEqual(
            len({os.getpid(), self.a.receipt["pid"], self.b.receipt["pid"]}), 3
        )
        before = self.client.read("alpha", "memory", self.request["questions"])
        controls = {
            control: self.client.read(
                "alpha", "memory", self.request["questions"], control=control
            )
            for control in ("base", "shuffled")
        }
        self.assertFalse(before["journal"]["fact_input"])
        self.assertFalse(before["journal"]["retrieval_input"])
        self.assertFalse(before["journal"]["answer_lexicon_input"])
        self.assertNotEqual(before["pid"], before["journal"]["decoder_process"]["pid"])
        self.assertEqual(before["journal"]["decoder_process"]["returncode"], 0)
        self.assertEqual(
            before["journal"]["decoder_process"]["tensor_lifetime"],
            "child_process_completed",
        )
        self.assertEqual(
            before["journal"]["admitted_adapter_state_sha256"],
            controls["base"]["journal"]["admitted_adapter_state_sha256"],
        )
        self.assertNotEqual(
            controls["shuffled"]["journal"]["admitted_adapter_state_sha256"],
            controls["shuffled"]["journal"]["consumed_adapter_state_sha256"],
        )
        moved = self.client.migrate(self.initial, "b")
        self.assertEqual(
            moved["placement"], dict(self.initial, node_id="b", generation=1)
        )
        self.assertTrue(self.client.migrate(self.initial, "b")["already_current"])
        with self.assertRaisesRegex(RemoteError, "CAS mismatch"):
            self.client.publish(dict(self.initial, generation=1), 0)
        count = self.counts()
        with self.assertRaisesRegex(RemoteError, "not assigned"):
            call(self.a.address, self.key, self.request)
        self.assertEqual(self.counts(), count)
        after = self.client.read("alpha", "memory", self.request["questions"])
        self.assertNotEqual(before["pid"], after["pid"])
        self.assertEqual(decoder_rows(before), decoder_rows(after))
        self.assertEqual(
            before["journal"]["consumed_adapter_state_sha256"],
            after["journal"]["consumed_adapter_state_sha256"],
        )
        for filename in (
            "lineage.json",
            "adapter_config.json",
            "adapter_model.safetensors",
        ):
            relative = Path("checkpoints") / self.initial["manifest_sha256"] / filename
            self.assertEqual(
                (self.a.root / relative).read_bytes(),
                (self.b.root / relative).read_bytes(),
            )
            self.assertNotEqual(
                (self.a.root / relative).resolve(), (self.b.root / relative).resolve()
            )
        self.revoke()
        count = self.counts()
        for node in (self.a, self.b):
            with self.assertRaises(RemoteError):
                call(node.address, self.key, self.request)
        self.assertEqual(self.counts(), count)
        old_pid = self.b.receipt["pid"]
        self.b.stop()
        self.b.start()
        self.assertNotEqual(old_pid, self.b.receipt["pid"])
        with self.assertRaisesRegex(RemoteError, "withdrawn"):
            call(self.b.address, self.key, self.request)
        self.assertEqual(self.counts(), count)
        clean, clean_pin, clean_roots = self.versions[1]
        self.client.stage("b", clean, clean_pin, "alpha")
        recovered = dict(
            self.initial,
            node_id="b",
            generation=2,
            manifest_sha256=clean_pin,
            roots=clean_roots,
        )
        self.client.publish(recovered, 1)
        result = self.client.read("alpha", "memory", self.request["questions"])
        self.assertEqual(result["placement"], recovered)
        self.assertEqual(result["frontier_epoch"], 1)
        count = self.counts()
        self.authority.stop()
        for node in (self.a, self.b):
            with self.assertRaises(RemoteError):
                call(node.address, self.key, self.request)
        self.assertEqual(self.counts(), count)
        self.authority.start()
        self.assertEqual(
            self.client.snapshot("alpha", "memory")["placement"], recovered
        )
        self.assertEqual(
            decoder_rows(
                self.client.read("alpha", "memory", self.request["questions"])
            ),
            decoder_rows(result),
        )

    def test_tampering_closed_queries_authentication_and_durable_rollback_fences(self):
        checkpoint, pin, _roots = self.versions[0]
        package = pack(checkpoint, pin, "alpha")
        original = base64.b64decode(package["files"]["adapter_model.safetensors"])
        package["files"]["adapter_model.safetensors"] = base64.b64encode(
            original[:-1] + bytes([original[-1] ^ 1])
        ).decode()
        with self.assertRaises(RemoteError):
            call(
                self.b.address,
                self.key,
                dict(op="stage", package=package, retained_manifest_sha256=pin),
            )
        self.assertFalse((self.b.root / "checkpoints" / pin).exists())
        with self.assertRaisesRegex(RemoteError, "closed RPC schema"):
            call(
                self.a.address, self.key, dict(self.request, facts=["injected answer"])
            )
        with self.assertRaisesRegex(ValueError, "authentication"):
            call(self.a.address, os.urandom(32), self.request)
        self.assertEqual(self.counts(), {"a": 0, "b": 0})
        backup = self.root / "authority-before.sqlite"
        shutil.copyfile(self.authority.root / "authority.sqlite", backup)
        self.client.migrate(self.initial, "b")
        # Observe generation 1 without executing the model, then roll back only
        # placement (the source epoch is still zero) across all process restarts.
        call(
            self.b.address, self.key, dict(op="export", scope="alpha", cell_id="memory")
        )
        with self.assertRaisesRegex(RemoteError, "not assigned"):
            call(self.a.address, self.key, self.request)
        migrated = self.root / "authority-migrated.sqlite"
        shutil.copyfile(self.authority.root / "authority.sqlite", migrated)
        self.a.stop()
        self.b.stop()
        self.authority.stop()
        shutil.copyfile(backup, self.authority.root / "authority.sqlite")
        self.authority.start()
        self.a.start()
        self.b.start()
        for node in (self.a, self.b):
            with self.assertRaisesRegex(RemoteError, "placement rollback"):
                call(node.address, self.key, self.request)
        self.authority.stop()
        shutil.copyfile(migrated, self.authority.root / "authority.sqlite")
        self.authority.start()
        self.revoke()
        for node in (self.a, self.b):
            with self.assertRaises(RemoteError):
                call(node.address, self.key, self.request)
        self.a.stop()
        self.b.stop()
        self.authority.stop()
        shutil.copyfile(backup, self.authority.root / "authority.sqlite")
        self.authority.start()
        self.a.start()
        self.b.start()
        for node in (self.a, self.b):
            with self.assertRaisesRegex(RemoteError, "rollback"):
                call(node.address, self.key, self.request)
        self.assertEqual(self.counts(), {"a": 0, "b": 0})

    @unittest.skipUnless(
        sys.platform == "linux" and hasattr(os, "pidfd_open"),
        "Linux parent-death and pidfd qualification",
    )
    def test_failed_decoder_and_inflight_worker_kill_preserve_restart_reads(self):
        self.a.stop()
        model_argument = self.a.arguments.index("--model") + 1
        self.a.arguments[model_argument] = str(self.root / "absent-model")
        self.a.start()
        with self.assertRaisesRegex(RemoteError, "isolated decoder exited"):
            self.client.read("alpha", "memory", self.request["questions"])
        receipts = self.a.root / "model-processes"
        failure = json.loads(next(receipts.glob("*.result.json")).read_text())
        self.assertNotEqual(failure["returncode"], 0)
        self.assertEqual(failure["bootstrap"]["parent_pid"], self.a.process.pid)
        self.assertEqual(
            call(self.a.address, self.key, {"op": "status"})["model_callbacks"], 1
        )
        self.a.stop()
        self.a.arguments[model_argument] = str(self.base)
        self.a.start()
        before = self.client.read("alpha", "memory", self.request["questions"])
        known = set(receipts.glob("*.stderr.txt"))
        child_fd = None
        with ThreadPoolExecutor(max_workers=1) as executor:
            pending = executor.submit(
                call,
                self.a.address,
                self.key,
                dict(self.request, questions=self.request["questions"] * 128),
            )
            try:
                deadline = time.monotonic() + 30
                startup = None
                while startup is None and time.monotonic() < deadline:
                    for path in set(receipts.glob("*.stderr.txt")) - known:
                        lines = path.read_text().splitlines()
                        if lines:
                            startup, stderr_path = json.loads(lines[0]), path
                    if startup is None:
                        time.sleep(0.01)
                self.assertIsNotNone(startup, "decoder bootstrap was not observed")
                child_pid = startup["pid"]
                child_fd = os.pidfd_open(child_pid)
                os.kill(child_pid, signal.SIGSTOP)
                # procfs can expose an outer PID namespace in a local sandbox.
                fdinfo = Path(f"/proc/self/fdinfo/{child_fd}").read_text()
                proc_pid = int(
                    next(
                        line.split()[1]
                        for line in fdinfo.splitlines()
                        if line.startswith("Pid:")
                    )
                )
                state = Path(f"/proc/{proc_pid}/stat")
                while state.read_text().split(") ", 1)[1].split()[0] != "T":
                    if time.monotonic() >= deadline:
                        self.fail("decoder did not enter the observed stopped state")
                    time.sleep(0.01)
                worker_pid = self.a.process.pid
                self.assertEqual(startup["parent_pid"], worker_pid)
                self.assertEqual(startup["parent_death"]["status"], "bound")
                self.a.process.kill()
                self.a.process.wait(timeout=10)
                self.assertEqual(select.select([child_fd], [], [], 10)[0], [child_fd])
                with self.assertRaises(OSError):
                    pending.result(timeout=10)
                try:
                    proc_fields = state.read_text().split(") ", 1)[1].split()
                    observed = {
                        "proc_state": proc_fields[0],
                        "adopted_parent_pid": int(proc_fields[1]),
                        "wait_status": int(proc_fields[49]),
                        "proc_entry_present": True,
                    }
                    self.assertEqual(observed["proc_state"], "Z")
                    self.assertEqual(
                        os.WTERMSIG(observed["wait_status"]), signal.SIGKILL
                    )
                except FileNotFoundError:
                    observed = {"proc_entry_present": False, "reaped_by_test": False}
                observation = {
                    "schema": "hepta.memory-network.parent-death-observation.v1",
                    "worker_pid": worker_pid,
                    "worker_returncode": self.a.process.returncode,
                    "child_start": startup,
                    "child_exit_observed_by_pidfd": True,
                    "procfs_pid": proc_pid,
                    "child_returncode": None,
                    "raw_stderr": stderr_path.read_text(),
                    "child_was_stopped_before_parent_kill": True,
                    "child_ceased_execution": True,
                    "post_exit_observation": observed,
                    "test_is_not_the_child_reaper": True,
                    "failed_decoder_process": failure,
                }
            finally:
                self.a.stop()
                if child_fd is not None:
                    if not select.select([child_fd], [], [], 0)[0]:
                        signal.pidfd_send_signal(child_fd, signal.SIGKILL)
                    os.close(child_fd)
        self.a.start()
        after = self.client.read("alpha", "memory", self.request["questions"])
        self.assertNotEqual(before["pid"], after["pid"])
        self.assertEqual(after["placement"], self.initial)
        self.assertEqual(decoder_rows(before), decoder_rows(after))
        observation["restarted_worker_pid"] = after["pid"]
        observation["restarted_decoder_process"] = after["journal"]["decoder_process"]
        observation["before_read"] = before
        observation["after_read"] = after
        observation["checkpoint_and_raw_read_preserved"] = True
        print(json.dumps(observation, sort_keys=True), flush=True)

    def test_placement_and_revocation_changes_during_real_callback_discard_output(self):
        context = multiprocessing.get_context("spawn")
        started, resume, ready = context.Event(), context.Event(), context.Queue()
        paused = context.Process(
            target=paused_worker,
            args=(
                str(self.root / "paused"),
                "paused",
                self.authority.address,
                self.key,
                str(self.base),
                started,
                resume,
                ready,
            ),
        )
        paused.start()
        self.addCleanup(lambda: (paused.terminate(), paused.join(10)))
        address = ready.get(timeout=30)["endpoint"]
        client = NetworkClient(
            self.authority.address,
            {"a": self.a.address, "b": self.b.address, "paused": address},
            self.key,
        )
        moved = client.migrate(self.initial, "paused")["placement"]
        directory, pin, _roots = self.versions[0]
        client.stage("b", directory, pin, "alpha")
        with ThreadPoolExecutor(max_workers=1) as executor:
            pending = executor.submit(call, address, self.key, self.request)
            try:
                self.assertTrue(started.wait(20))
                moved = client.publish(dict(moved, node_id="b", generation=2), 1)
            finally:
                resume.set()
            with self.assertRaisesRegex(RemoteError, "placement changed"):
                pending.result(timeout=30)
        client.publish(dict(moved, node_id="paused", generation=3), 2)
        started.clear()
        resume.clear()
        with ThreadPoolExecutor(max_workers=1) as executor:
            pending = executor.submit(call, address, self.key, self.request)
            try:
                self.assertTrue(started.wait(20))
                self.revoke()
            finally:
                resume.set()
            with self.assertRaisesRegex(
                RemoteError, "frontier or active version changed"
            ):
                pending.result(timeout=30)
        self.assertEqual(
            call(address, self.key, {"op": "status"})["model_callbacks"], 2
        )
        with self.assertRaisesRegex(RemoteError, "withdrawn"):
            call(address, self.key, self.request)
        self.assertEqual(
            call(address, self.key, {"op": "status"})["model_callbacks"], 2
        )


if __name__ == "__main__":
    unittest.main()
