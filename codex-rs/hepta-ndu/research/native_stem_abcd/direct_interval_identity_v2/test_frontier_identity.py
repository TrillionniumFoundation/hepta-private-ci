"""Bounded identity regressions; synthetic bounds do not qualify R20 physics.

The only unmocked solver invocation is a one-split CLI smoke check.  No fitting,
training, NumPy, SciPy or Torch is used by this suite.
"""

from fractions import Fraction as F
import heapq
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import global_interval_v2 as v2


ROOT = (F(-3), F(3), F(-3), F(3))
LEFT = (F(-3), F(0), F(-3), F(3))
RIGHT = (F(0), F(3), F(-3), F(3))
CANDIDATE = (F(1), F(1), F(1), F(1))
LEFT_BOTTOM = (F(-3), F(0), F(-3), F(0))
LEFT_TOP = (F(-3), F(0), F(0), F(3))


def fixed_bounds(box, extra=True):
    # An isolated heap-control fixture, not the original entropic objective.
    return {
        CANDIDATE: (F(1), F(1)),
        ROOT: (F(0), F(2)),
        LEFT: (F(3, 4), F(2)),
        RIGHT: (F(7, 8), F(2)),
        LEFT_BOTTOM: (F(13, 16), F(2)),
        LEFT_TOP: (F(7, 8), F(2)),
    }[tuple(box)]


def mathematical_receipt(receipt):
    omitted = {
        "schema", "wall", "frontier_sha256", "arithmetic_source_sha256",
        "arithmetic_source_git_blob", "frontier_id_policy",
    }
    return {key: value for key, value in receipt.items() if key not in omitted}


class FrontierIdentityTests(unittest.TestCase):
    def run_fixture(self, module, *, threshold=F(1, 4), cap=2, oracle=fixed_bounds):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "frontier.jsonl"
            with patch.object(module, "cost_bounds", side_effect=oracle):
                receipt = module.bnb(F(1), F(1), True, threshold, cap, output)
            rows = [json.loads(line) for line in output.read_text().splitlines()]
        return receipt, rows

    def test_original_one_split_fixture_exposes_two_boxes_with_one_id(self):
        receipt, rows = self.run_fixture(v2._LEGACY)
        self.assertEqual((receipt["nodes_split"], receipt["frontier_count"]), (1, 2))
        self.assertEqual([row["id"] for row in rows], [2, 2])
        self.assertEqual(len({tuple(row["box"]) for row in rows}), 2)

    def test_stop_reinserts_original_tuple_and_keeps_unique_ids(self):
        popped = []
        pushed = []

        def pop(queue):
            node = heapq.heappop(queue)
            popped.append(node)
            return node

        def push(queue, node):
            pushed.append(node)
            heapq.heappush(queue, node)

        with patch.object(v2, "heappop", side_effect=pop), patch.object(v2, "heappush", side_effect=push):
            receipt, rows = self.run_fixture(v2)
        self.assertIs(pushed[-1], popped[-1])
        self.assertEqual(rows, [
            {"id": 1, "lower": "3/4", "box": list(map(str, LEFT))},
            {"id": 2, "lower": "7/8", "box": list(map(str, RIGHT))},
        ])
        self.assertEqual(
            (receipt["nodes_split"], receipt["global_cost_lower"], receipt["global_regret_upper"],
             receipt["passes_frozen_global_threshold"]),
            (1, "3/4", "1/4", True),
        )

    def test_math_receipt_and_boxes_unchanged_when_only_ids_change(self):
        old_receipt, old_rows = self.run_fixture(v2._LEGACY)
        new_receipt, new_rows = self.run_fixture(v2)
        self.assertEqual(mathematical_receipt(old_receipt), mathematical_receipt(new_receipt))
        old_boxes = sorted((tuple(row["box"]), row["lower"]) for row in old_rows)
        new_boxes = sorted((tuple(row["box"]), row["lower"]) for row in new_rows)
        self.assertEqual(old_boxes, new_boxes)

    def test_one_split_cap_keeps_threshold_failure(self):
        old_receipt, old_rows = self.run_fixture(v2._LEGACY, threshold=F(1, 8), cap=1)
        receipt, rows = self.run_fixture(v2, threshold=F(1, 8), cap=1)
        self.assertEqual(rows, old_rows)
        self.assertEqual(mathematical_receipt(receipt), mathematical_receipt(old_receipt))
        self.assertEqual((receipt["nodes_split"], receipt["passes_frozen_global_threshold"]), (1, False))
        self.assertEqual([row["id"] for row in rows], [1, 2])

    def test_nonstop_second_split_allocates_new_ids(self):
        old_receipt, old_rows = self.run_fixture(v2._LEGACY, threshold=F(1, 8), cap=2)
        receipt, rows = self.run_fixture(v2, threshold=F(1, 8), cap=2)
        self.assertEqual(rows, old_rows)
        self.assertEqual(mathematical_receipt(receipt), mathematical_receipt(old_receipt))
        self.assertEqual(
            (receipt["nodes_split"], receipt["frontier_count"], receipt["global_regret_upper"],
             receipt["passes_frozen_global_threshold"]),
            (2, 3, "3/16", False),
        )
        self.assertEqual([row["id"] for row in rows], [2, 3, 4])

    def test_pruning_keeps_only_the_unpruned_child(self):
        def oracle(box, extra=True):
            return (F(1), F(2)) if tuple(box) == RIGHT else fixed_bounds(box, extra)

        receipt, rows = self.run_fixture(v2, oracle=oracle)
        self.assertEqual(rows, [{"id": 1, "lower": "3/4", "box": list(map(str, LEFT))}])
        self.assertEqual((receipt["nodes_split"], receipt["frontier_count"]), (1, 1))

    def test_root_stop_keeps_root_identity(self):
        receipt, rows = self.run_fixture(v2, threshold=F(1), cap=2)
        self.assertEqual(rows, [{"id": 0, "lower": "0", "box": list(map(str, ROOT))}])
        self.assertEqual((receipt["nodes_split"], receipt["frontier_count"]), (0, 1))

    def test_changed_arithmetic_bytes_are_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            altered = Path(directory) / "global_interval.py"
            altered.write_bytes(Path(v2._LEGACY.__file__).read_bytes() + b"\n")
            with self.assertRaisesRegex(ValueError, "frozen R20 interval source mismatch"):
                v2._load_legacy(altered)

    def test_actual_cli_routes_to_v2_and_respects_one_split_cap(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "bounds.json"
            frontier = Path(directory) / "frontier.jsonl"
            environment = dict(os.environ, NDU_R20_LEGACY_SOURCE=v2._LEGACY.__file__)
            subprocess.run(
                [sys.executable, str(Path(v2.__file__).resolve()),
                 "--a", "1.54696889", "--b", ".44887401", "--cap", "1",
                 "--out", str(output), "--frontier", str(frontier)],
                check=True, capture_output=True, text=True, env=environment, timeout=10,
            )
            receipt = json.loads(output.read_text())
            rows = [json.loads(line) for line in frontier.read_text().splitlines()]
        self.assertEqual(receipt["schema"], v2.SCHEMA)
        self.assertEqual((receipt["nodes_split"], receipt["passes_frozen_global_threshold"]), (1, False))
        self.assertEqual(len({row["id"] for row in rows}), len(rows))


if __name__ == "__main__":
    unittest.main(verbosity=2)
