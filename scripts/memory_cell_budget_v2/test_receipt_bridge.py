"""Synthetic raw receipts exercise coverage; real receipts use qualify.py."""

import copy
import json
from pathlib import Path
import tempfile
import unittest

from common import file_identity, save
from receipt_bridge import collect
from test_support import plan, process


class Receipts(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def controller(self, name, children, child_cpu, own=7, wall=100):
        path = self.root / (name + ".json")
        save(
            path,
            {
                "schema": "hepta.memory.warm-controller-cost.v1",
                "self_cpu_excludes_child_cpu": True,
                "self_cpu_ns": own,
                "whole_execute_wall_ns": wall,
                "charged_child_cpu_ns": child_cpu,
                "controller_plus_child_cpu_ns": None
                if child_cpu is None
                else own + child_cpu,
                "error": None,
            },
        )
        return {
            "kind": "warm-controller-v1",
            "path": str(path),
            "identity": file_identity(path),
            "id": name,
            "related": children,
        }

    def test_controller_children_and_covering_outer_are_not_double_charged(self):
        first = process(self.root, "a", cpu=25, wall=20)
        second = process(self.root, "b", cpu=35, wall=30)
        caller = self.controller("caller", ["a", "b"], 60)
        result = collect(plan(first, second, caller, wall_owner="caller"))
        self.assertEqual(
            (
                result["observation"]["cpu_ns"],
                result["observation"]["wall_ns"],
                result["attempt_wall_sum_ns"],
            ),
            (67, 100, 150),
        )
        outer = process(self.root, "outer", cpu=67, wall=110)
        outer["related"] = ["a", "b", "caller"]
        result = collect(plan(first, second, caller, outer, wall_owner="outer"))
        self.assertEqual(
            (
                result["observation"]["cpu_ns"],
                result["charged_ids"],
                result["attribution_to"],
            ),
            (67, ["outer"], {"a": "outer", "b": "outer", "caller": "outer"}),
        )

    def test_unknown_stays_null_with_known_subtotal(self):
        entry = process(self.root, "unknown")
        path = Path(entry["path"])
        value = json.loads(path.read_bytes())
        value["usage"] = None
        path.write_text(json.dumps(value))
        entry["identity"] = file_identity(path)
        caller = self.controller("caller", ["unknown"], None)
        result = collect(plan(entry, caller, wall_owner="caller"))
        self.assertEqual(
            (
                result["observation"]["cpu_ns"],
                result["known_subtotals"]["cpu_ns"],
                result["unknown_charged_rows"]["cpu_ns"],
            ),
            (None, 7, 1),
        )
        self.assertIsNone(result["observation"]["input_tokens"])
        self.assertIsNone(result["observation"]["write_bytes"])

    def test_duplicate_receipt_and_duplicate_coverage_refused(self):
        entry = process(self.root, "a")
        alias = copy.deepcopy(entry)
        alias["id"] = "alias"
        with self.assertRaises(ValueError):
            collect(plan(entry, alias))
        outer = process(self.root, "outer")
        another = process(self.root, "another")
        outer["related"] = another["related"] = ["a"]
        with self.assertRaises(ValueError):
            collect(plan(entry, outer, another, wall_owner="outer"))
        another["related"] = ["missing"]
        with self.assertRaises(ValueError):
            collect(plan(another))

    def test_tampered_raw_stream_and_controller_sum_refused(self):
        entry = process(self.root, "a", cpu=10)
        caller = self.controller("caller", ["a"], 30)
        with self.assertRaises(ValueError):
            collect(plan(entry, caller, wall_owner="caller"))
        (Path(entry["path"]).parent / "stdout").write_bytes(b"changed")
        with self.assertRaises(ValueError):
            collect(plan(entry))

    def test_timeout_is_infrastructure_failure_but_task_negative_is_complete(self):
        negative = collect(plan(process(self.root, "negative", returncode=1)))
        timeout = collect(
            plan(process(self.root, "timeout", returncode=-9, timeout=True))
        )
        self.assertTrue(negative["receipts"][0]["process_failed"])
        self.assertEqual(negative["infrastructure_status"], "completed")
        self.assertEqual(timeout["infrastructure_status"], "timeout")

    def test_covered_wall_owner_and_receipt_pin_drift_refused(self):
        child = process(self.root, "child")
        outer = process(self.root, "outer")
        outer["related"] = ["child"]
        with self.assertRaises(ValueError):
            collect(plan(child, outer, wall_owner="child"))
        Path(child["path"]).write_text("{}")
        with self.assertRaises(ValueError):
            collect(plan(child))
