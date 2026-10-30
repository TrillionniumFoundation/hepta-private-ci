"""Small synthetic tests only: no science imports, training, network or uploads."""

import copy
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

import durable_archive as archive
import supervisor


class DurableSemantics(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def prepare(self):
        source = self.root / "source.bin"
        source.write_bytes(bytes(range(256)) * 71)
        empty = self.root / "empty.bin"
        empty.write_bytes(b"")
        binding = {"sequence": 1, "label": "A-17", "completed_jobs": ["A-17"], "test_only": True}
        request = archive.build_archive(self.root / "archive", {"raw/example.bin": source, "raw/empty.bin": empty},
                                        binding, payload_limit=4096)
        return request, archive.read(request["path"])

    def synthetic_ack(self, descriptor, request):
        receipt = self.root / "SYNTHETIC_TOOL_RECEIPT.json"
        archive.write_json(receipt, {"synthetic": True, "real_remote_operation": False})
        items = []
        for index, item in enumerate(request["items"]):
            destination = self.root / ("readback-" + str(index))
            shutil.copyfile(item["path"], destination)
            remote = {"library_file_id": "synthetic-test-only-" + str(index), "version": "synthetic"}
            items.append({"local": item, "upload_item_success": True, "remote_readback_performed": True,
                          "remote_identity": remote, "readback_remote_identity": remote,
                          "readback": archive.descriptor(destination), "upload_receipt": archive.descriptor(receipt),
                          "readback_receipt": archive.descriptor(receipt)})
        value = {"schema": "hepta.fullstudy.library-archive-ack.1", "status": "VERIFIED_REMOTE_READBACK",
                 "unknown_upload_outcome": False, "request": descriptor, "binding": request["binding"], "items": items}
        target = self.root / "ACK.json"
        archive.write_json(target, value)
        return target, value

    def test_streamed_chunks_reconstruct_and_corruption_fails(self):
        descriptor, request = self.prepare()
        manifest = archive.read(request["manifest"]["path"])
        result = archive.verify_parts(manifest, self.root / "archive")
        self.assertEqual((result["logical_files_verified"], result["logical_bytes_verified"]), (2, 256 * 71))
        self.assertTrue(all(row["payload_bytes"] <= 4096 for row in manifest["parts"]))
        # Even substituting a new compressed-file digest cannot hide corruption
        # from the independent decompression and logical-file verifier.
        part = Path(manifest["parts"][0]["artifact"]["path"])
        payload = bytearray(part.read_bytes())
        payload[len(payload) // 2] ^= 1
        part.write_bytes(payload)
        manifest["parts"][0]["artifact"] = archive.descriptor(part)
        with self.assertRaises((ValueError, OSError, EOFError)):
            archive.verify_parts(manifest, self.root / "archive")

    def test_ack_requires_every_distinct_actual_readback(self):
        descriptor, request = self.prepare()
        path, value = self.synthetic_ack(descriptor, request)
        checked = archive.verify_ack(path, descriptor)
        self.assertEqual(checked["items_verified"], len(request["items"]))
        self.assertTrue(checked["readback_bytes_verified_here"])
        for change in ("missing", "unknown", "alias", "wrong_identity", "wrong_bytes"):
            candidate = copy.deepcopy(value)
            if change == "missing":
                candidate["items"].pop()
            elif change == "unknown":
                candidate["unknown_upload_outcome"] = True
            elif change == "alias":
                candidate["items"][0]["readback"] = candidate["items"][0]["local"]
            elif change == "wrong_identity":
                candidate["items"][0]["readback_remote_identity"] = {"library_file_id": "different"}
            else:
                Path(candidate["items"][0]["readback"]["path"]).write_bytes(b"changed")
            archive.write_json(path, candidate, replace=True)
            with self.subTest(change=change), self.assertRaises(ValueError):
                archive.verify_ack(path, descriptor)

    def test_activation_requires_completed_prefix_and_real_verified_ack(self):
        with self.assertRaises(ValueError):
            supervisor.require_durable_predecessor(2, ["A-17"], [])
        descriptor, request = self.prepare()
        path, value = self.synthetic_ack(descriptor, request)
        checked = archive.verify_ack(path, descriptor)
        supervisor.require_durable_predecessor(2, ["A-17"], [checked])
        with self.assertRaises(ValueError):
            supervisor.require_durable_predecessor(3, ["A-17", "A-29"], [checked])
        with self.assertRaises(ValueError):
            supervisor.require_durable_predecessor(14, ["A-17"], [checked], finalize=True)

    def test_accepted_definitions_and_early_finalization_are_rejected(self):
        canonical = {"jobs": [{"id": name, "requires": [] if i == 0 else [supervisor.ORDER[i - 1]]}
                              for i, name in enumerate(supervisor.ORDER[:4])], "finalize": False}
        previous = supervisor.activated_prefix(canonical, 1)
        changed = copy.deepcopy(canonical)
        changed["jobs"][0]["requires"] = ["A-29"]
        with self.assertRaises(ValueError):
            supervisor.activated_prefix(changed, 2, previous)
        with self.assertRaises(ValueError):
            supervisor.activated_prefix(canonical, 4, finalize=True)
        with self.assertRaises(ValueError):
            supervisor.activated_prefix(canonical, 3, previous)

    def test_old_successful_child_is_never_signalled_again(self):
        child = object.__new__(supervisor.OwnedChild)
        child.result = {"exit_code": 0}
        with patch.object(supervisor.os, "killpg") as kill:
            self.assertEqual(child.stop(), {"already_exited_successfully": True, "signals_sent": 0})
            kill.assert_not_called()

    def test_start_receipt_failure_cleans_and_reaps_its_new_child(self):
        original_write = supervisor.write
        def failing_start(path, value, **kwargs):
            if str(path).endswith(".START.json"):
                raise OSError("synthetic START write failure")
            return original_write(path, value, **kwargs)
        with patch.object(supervisor, "write", failing_start), self.assertRaises(OSError):
            supervisor.OwnedChild(self.root / "children", "synthetic",
                                  [sys.executable, "-B", "-c", "import time; time.sleep(30)"],
                                  self.root, dict(os.environ))
        failure = archive.read(self.root / "children/synthetic.SPAWN_FAILED.json")
        self.assertTrue(failure["cleanup"]["popen_returned"])
        self.assertIsNotNone(failure["cleanup"]["wait4"])
        self.assertNotEqual(failure["cleanup"]["wait4"]["exit_code"], 0)
        self.assertFalse((Path("/proc") / str(failure["cleanup"]["pid"])).exists())

    def test_endpoint_access_files_and_closed_cwd_receipts_are_in_scope(self):
        raw, ops = self.root / "raw", self.root / "ops"
        relatives = ["stage_B/endpoints/ENDPOINTS.json", "stage_B/ENDPOINT_CHECKPOINTS.json",
                     "stage_B/QUALIFICATION_ACCESS_FREEZE.json", "controller/B_endpoint.START.json",
                     "controller/B_endpoint.RESULT.json", "controller/B_endpoint.log"]
        for relative in relatives:
            path = raw / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}\n")
        for name in ("REQUEST.json", "STARTED.json"):
            archive.write_json(ops / "cwd_launches/B_endpoint" / name, {"synthetic": True})
        config = archive.write_json(self.root / "CONFIG.json", {"synthetic": True})
        item = object.__new__(supervisor.Supervisor)
        item.config_desc, item.pins, item.config = config, {}, {}
        item.registrations, item.done, item.children = {}, ["B_endpoint"], []
        with patch.object(supervisor, "RAW", raw), patch.object(supervisor, "OPS", ops):
            selected = item.closed_job_paths({"id": "B_endpoint", "phase": "B"})
            selected.update(item.metadata())
        self.assertTrue(set("raw/" + name for name in relatives) <= set(selected))
        self.assertTrue({"metadata/cwd_launches/B_endpoint/REQUEST.json",
                         "metadata/cwd_launches/B_endpoint/STARTED.json"} <= set(selected))


if __name__ == "__main__":
    unittest.main()
