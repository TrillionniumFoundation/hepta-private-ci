"""Current publication admission through the actual source-bound TCP endpoint."""

import json
import os
import sqlite3
from pathlib import Path
import tempfile
import unittest

from memory_service import MemoryService
from network_client import NetworkClient
from network_test_support import ServiceProcess
from network_wire import RemoteError, call
import test_parametric_model as tiny


class CurrentParameterNetworkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tiny.SourceMemoryCellTests.setUpClass()
        cls.addClassCleanup(tiny.SourceMemoryCellTests.tearDownClass)
        cls.base = tiny.SourceMemoryCellTests.base

    def test_source_changes_deny_direct_reads_and_stale_publication_then_recover(self):
        for change in ("conflict", "addition"):
            with (
                self.subTest(change=change),
                tempfile.TemporaryDirectory() as directory,
            ):
                root, secret = Path(directory), os.urandom(32)
                key_file = root / "key"
                key_file.write_bytes(secret)
                source = MemoryService(root / "source", "alpha")
                source.write("s1", "one", "color", "red")
                source.work_once(self.base, steps=4, rank=2, templates=tiny.TEMPLATES)
                active = source.parameter_binding()["active"]
                authority = ServiceProcess(
                    root / "authority",
                    "authority",
                    key_file,
                    source_root=root / "source",
                    scope="alpha",
                )
                worker = None
                try:
                    worker = ServiceProcess(
                        root / "worker",
                        "worker",
                        key_file,
                        node_id="a",
                        authority=authority.address,
                        model=self.base,
                    )
                    client = NetworkClient(
                        authority.address, {"a": worker.address}, secret
                    )
                    client.stage(
                        "a", active.directory, active.manifest_sha256, active.scope
                    )
                    placement = dict(
                        scope="alpha",
                        cell_id="memory",
                        node_id="a",
                        generation=0,
                        manifest_sha256=active.manifest_sha256,
                        roots=list(active.roots),
                    )
                    client.publish(placement, None)
                    request = dict(
                        op="read",
                        scope="alpha",
                        cell_id="memory",
                        questions=["What is the color of one?"],
                        control="adapter",
                    )
                    call(worker.address, secret, request, timeout=60)
                    before = call(worker.address, secret, {"op": "status"})[
                        "model_callbacks"
                    ]
                    if change == "conflict":
                        source.write("s2", "one", "color", "blue")
                        self.assertEqual(
                            source.read("one", "color").status.value, "conflict"
                        )
                    else:
                        source.write("s2", "two", "color", "blue")
                    self.assertIsNone(source.parameter_binding())
                    # Neither a direct reader nor a trusted stale publisher can
                    # relabel the old checkpoint as the current source version.
                    with self.assertRaisesRegex(RemoteError, "binding is unavailable"):
                        call(worker.address, secret, request, timeout=60)
                    with self.assertRaisesRegex(RemoteError, "binding is unavailable"):
                        client.publish(dict(placement, generation=1), 0)
                    self.assertEqual(
                        call(worker.address, secret, {"op": "status"})[
                            "model_callbacks"
                        ],
                        before,
                    )
                    with sqlite3.connect(worker.root / "fences.sqlite") as database:
                        observed = json.loads(
                            database.execute(
                                "SELECT value FROM frontier WHERE scope='alpha'"
                            ).fetchone()[0]
                        )
                    self.assertEqual(observed["epoch"], source.authority_view().epoch)
                    if change == "conflict":
                        source.correct("s2", "red", 0)
                    source.work_once(
                        self.base, steps=8, rank=2, templates=tiny.TEMPLATES
                    )
                    current = source.parameter_binding()["active"]
                    with self.assertRaisesRegex(RemoteError, "differs from current"):
                        call(worker.address, secret, request, timeout=60)
                    with self.assertRaisesRegex(RemoteError, "differs from current"):
                        client.publish(dict(placement, generation=1), 0)
                    client.stage(
                        "a", current.directory, current.manifest_sha256, current.scope
                    )
                    updated = dict(
                        placement,
                        generation=1,
                        manifest_sha256=current.manifest_sha256,
                        roots=list(current.roots),
                    )
                    client.publish(updated, 0)
                    recovered = call(worker.address, secret, request, timeout=60)
                    self.assertEqual(recovered["placement"], updated)
                    self.assertEqual(
                        call(worker.address, secret, {"op": "status"})[
                            "model_callbacks"
                        ],
                        before + 1,
                    )
                    authority.stop()
                    authority.start()
                    worker.stop()
                    worker.start()
                    self.assertEqual(
                        call(worker.address, secret, request, timeout=60)["placement"],
                        updated,
                    )
                finally:
                    if worker is not None:
                        worker.stop()
                    authority.stop()


if __name__ == "__main__":
    unittest.main()
