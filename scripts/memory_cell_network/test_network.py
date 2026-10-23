"""Real TCP/process lifecycle with trained tiny-decoder checkpoint bytes."""

import base64
from concurrent.futures import ThreadPoolExecutor
import multiprocessing
import os
from pathlib import Path
import shutil
import tempfile
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
