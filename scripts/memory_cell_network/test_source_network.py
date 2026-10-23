"""Source-service withdrawal reaches real TCP workers without a second write."""

import os
from pathlib import Path
import tempfile
import unittest

from memory_service import MemoryService
from network_client import NetworkClient
from network_test_support import ServiceProcess
from network_wire import RemoteError, call
import test_parametric_model as tiny


class SourceNetworkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tiny.SourceMemoryCellTests.setUpClass()
        cls.addClassCleanup(tiny.SourceMemoryCellTests.tearDownClass)
        cls.base = tiny.SourceMemoryCellTests.base

    def test_service_revoke_automatically_fences_both_worker_processes(self):
        with tempfile.TemporaryDirectory() as directory:
            root, key = Path(directory), os.urandom(32)
            key_file = root / "key"
            key_file.write_bytes(key)
            source_root = root / "source"
            source = MemoryService(source_root, "alpha")
            written = source.write("fact-1", "one", "color", "red")
            trained = source.work_once(
                self.base, steps=4, rank=8, templates=tiny.TEMPLATES
            )
            self.assertEqual(trained["status"], "published")
            active = source.parameter_binding()["active"]
            authority = ServiceProcess(
                root / "authority",
                "authority",
                key_file,
                source_root=source_root,
                scope="alpha",
            )
            nodes = []
            try:
                for node_id in ("a", "b"):
                    nodes.append(
                        ServiceProcess(
                            root / node_id,
                            "worker",
                            key_file,
                            node_id=node_id,
                            authority=authority.address,
                            model=self.base,
                        )
                    )
                client = NetworkClient(
                    authority.address,
                    {
                        node: process.address
                        for node, process in zip(("a", "b"), nodes, strict=True)
                    },
                    key,
                )
                client.stage(
                    "a", active.directory, active.manifest_sha256, active.scope
                )
                initial = dict(
                    scope=active.scope,
                    cell_id=active.cell_id,
                    node_id="a",
                    generation=0,
                    manifest_sha256=active.manifest_sha256,
                    roots=list(active.roots),
                )
                client.publish(initial, None)
                question = "What is the color of one?"
                raw = source.invoke_parameter(
                    "one", "color", question, client.service_reader
                )
                self.assertEqual(raw["status"], "generated")
                self.assertFalse(raw["response"]["journal"]["fact_input"])
                client.migrate(initial, "b")
                self.assertEqual(
                    source.invoke_parameter(
                        "one", "color", question, client.service_reader
                    )["status"],
                    "generated",
                )
                counts = [
                    call(node.address, key, {"op": "status"})["model_callbacks"]
                    for node in nodes
                ]
                self.assertEqual(
                    source.invoke_parameter(
                        "absent", "color", question, client.service_reader
                    )["status"],
                    "unknown",
                )
                source.revoke("fact-1", written.revision)
                # This is deliberately the only withdrawal write in this test.
                for node in nodes:
                    with self.assertRaises(RemoteError):
                        call(
                            node.address,
                            key,
                            dict(
                                op="read",
                                scope="alpha",
                                cell_id="memory",
                                questions=[question],
                                control="adapter",
                            ),
                        )
                self.assertEqual(
                    [
                        call(node.address, key, {"op": "status"})["model_callbacks"]
                        for node in nodes
                    ],
                    counts,
                )
                self.assertEqual(
                    client.snapshot("alpha", "memory")["frontier"]["epoch"],
                    source.authority_view().epoch,
                )
                with self.assertRaisesRegex(
                    RemoteError, "owned by the bound source service"
                ):
                    call(
                        authority.address,
                        key,
                        dict(
                            op="frontier",
                            frontier={"scope": "alpha", "epoch": 100, "revoked": []},
                        ),
                    )
                self.assertTrue(
                    all(str(source_root) not in node.arguments for node in nodes)
                )
                self.assertFalse(
                    any((node.root / "sources.sqlite").exists() for node in nodes)
                )
            finally:
                for node in nodes:
                    node.stop()
                authority.stop()


if __name__ == "__main__":
    unittest.main()
