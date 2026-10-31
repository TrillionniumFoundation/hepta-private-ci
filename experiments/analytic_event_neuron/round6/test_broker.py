"""Actual dev-only process, disk transport and acquired-information checks."""

import hashlib
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from .broker import Broker, Rejected, digest
from ..round4.runtime_evidence import EvidenceZip


class BrokerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.data = self.root / "private-development.npz"
        np.savez(self.data, initial_output=[.25, -.5], self_evaluation=[1.25, .25],
            wait_evaluation=[2.5, 3.75], sensor_variance=[.2, .3], wait_variance=[.4, .5],
            repair_cost=[.12, .48], wait_cost=[.04, .12], target=[4321.1234, -9876.54321],
            ids=["secret-regime:first", "secret-regime:second"], domain="private-domain")

    def tearDown(self):
        self.temporary.cleanup()

    def broker(self):
        return Broker(self.data, self.root / "broker", "unit_development")

    def test_actual_readback_costs_and_target_free_client(self):
        with patch("numpy.load", side_effect=AssertionError("Policy loaded private data")):
            with self.broker() as broker:
                self.assertNotEqual(broker.process.pid, os.getpid())
                public = broker.start(0, "analytic")
                self.assertEqual(public, {"initial": .25, "residuals": [1.0], "variances": [.2],
                    "repair_cost": .12, "wait_cost": .04, "wait_variance": .4})
                start_wire = json.dumps(broker.last_response)
                self.assertNotIn("2.5", start_wire)
                self.assertNotIn("secret-regime", start_wire)
                waited = broker.wait()
                self.assertEqual(waited, {**public, "residuals": [1.0, 2.25], "variances": [.2, .4]})
                result = broker.finish("repair", .75)
                self.assertEqual(set(result), {"delivered", "cost", "transport", "final_readback_ns"})
                self.assertEqual((result["delivered"], result["cost"]), (1.0, .16))
                receipts = [json.loads(x) for x in Path(result["transport"]["receipt_path"]).read_text().splitlines()]
                final = receipts[-1]
                directory = broker.case_dir / "readbacks"
                with Image.open(directory / final["image_path"]) as image:
                    pixels = np.asarray(image)
                bits = bytes(sum((int(pixels[0, j * 4]) // 255) << (7 - j % 8)
                    for j in range(i, i + 8)) for i in range(0, 64, 8))
                self.assertEqual(struct.unpack(">d", bits)[0], result["delivered"])
                self.assertLess(final["readback_ns"], result["final_readback_ns"])
            self.assertEqual(broker.close_receipt, {"complete": True, "finished_cases": 1})
        transcript = (broker.root / "BROKER_TRANSCRIPT.jsonl").read_text()
        self.assertNotIn("4321.1234", transcript)
        self.assertNotIn("-9876.54321", transcript)
        self.assertNotIn("private-domain", transcript)
        previous = "0" * 64
        for line in transcript.splitlines():
            record = json.loads(line)
            self.assertEqual(record["previous_sha256"], previous)
            previous = record.pop("sha256")
            self.assertEqual(previous, digest(record))
            if record["response"]["ok"] and record["state"] is not None:
                state = record["state"]
                self.assertTrue(all(r["readback_ns"] <= state["durable_readback_ns"]
                                    for r in record["transport_records"]))
                if record["operation"] == "finish":
                    self.assertEqual(state["durable_readback_ns"], result["final_readback_ns"])
                    self.assertEqual(state["result"]["final_readback_ns"], result["final_readback_ns"])

    def test_refusals_leave_task_state_and_artifacts_unchanged(self):
        with self.broker() as broker:
            broker.start(0, "event")
            def refused(operation, **fields):
                before = broker.last_response["state_sha256"]
                inventory = {str(p.relative_to(broker.case_dir)): hashlib.sha256(p.read_bytes()).hexdigest()
                             for p in broker.case_dir.rglob("*") if p.is_file()}
                with self.assertRaises(Rejected):
                    broker.request(operation, **fields)
                self.assertEqual(broker.last_response["state_sha256"], before)
                self.assertFalse(broker.last_response["fatal"])
                self.assertEqual(inventory, {str(p.relative_to(broker.case_dir)): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in broker.case_dir.rglob("*") if p.is_file()})
            refused("wait", future_observation=123)
            refused("start", index=1, arm="event")
            refused("finish", choice="stop", repair_amount=.1)
            refused("finish", choice="repair", repair_amount=True)
            for value in (float("nan"), float("inf")):
                before = broker.sequence
                with self.assertRaises(ValueError):
                    broker.finish("repair", value)
                self.assertEqual(broker.sequence, before)
            broker.wait()
            refused("wait")
            broker.finish("stop")
            refused("wait")
            refused("finish", choice="repair", repair_amount=0)
            refused("start", index=0, arm="event")

    def test_archive_then_next_case_and_incomplete_close(self):
        archive = EvidenceZip(self.root / "cases.zip")
        with self.broker() as broker:
            broker.start(0, "direct")
            self.assertEqual(broker.finish("stop")["cost"], 0.0)
            first_dir = broker.case_dir
            archive.append(first_dir, "case0")
            self.assertFalse(first_dir.exists())
            broker.start(1, "direct")
            result = broker.finish("repair", .5)
            self.assertEqual((result["delivered"], result["cost"]), (0.0, .48))
            archive.append(broker.case_dir, "case1")
        self.assertEqual(broker.close_receipt, {"complete": True, "finished_cases": 2})
        self.assertTrue(archive.finish()["all_entries_reopened_before_source_removal"])
        with Broker(self.data, self.root / "unfinished", "unit_unfinished") as incomplete:
            incomplete.start(0, "direct")
        self.assertEqual(incomplete.close_receipt, {"complete": False, "finished_cases": 0})

    def test_invalid_case_and_scope_have_no_delivery(self):
        with self.broker() as broker:
            for fields in ({"index": -1, "arm": "event"}, {"index": True, "arm": "event"},
                           {"index": 0, "arm": "../outside"}):
                with self.assertRaises(Rejected):
                    broker.request("start", **fields)
            self.assertFalse((broker.root / "cases").exists())


if __name__ == "__main__":
    unittest.main()
