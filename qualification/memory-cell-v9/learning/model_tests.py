"""Development checks on synthetic sources, never the independent V9 fixture."""

from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

import numpy as np

ROOT = Path(__file__).resolve()
sys.path.insert(0, str(ROOT.parents[2] / "memory-cell-v7"))
sys.path.insert(0, str(ROOT.parents[1]))

from training import canonical, sha
from learning.paired import CONFIG, initialize
from learning.byte_model import artifact, initial_arrays, metadata, parameter_digest, targets, typed_bytes


def rows(count=3):
    return [{"source_id": sha(f"source:{i}".encode()), "record": {
        "entity": f"entity:development-{i}", "value": {"factor": i + 2, "label": f"dev-{i}"}}}
        for i in range(count)]


class InterventionTests(unittest.TestCase):
    def test_frozen_parent_preserves_old_parameters_after_catalog_reindex(self):
        old = initialize(rows(), "semantic", CONFIG)
        extended = rows(5)
        extended[-1]["record"]["value"] = {"factor": -8, "label": "new-first"}
        rebased = initialize(extended, "semantic", CONFIG, old)
        np.testing.assert_array_equal(old.A, rebased.A)
        np.testing.assert_array_equal(old.a, rebased.a)
        for previous, value in enumerate(old.catalog):
            current = rebased.catalog.index(value)
            np.testing.assert_array_equal(old.B[:, previous], rebased.B[:, current])
            self.assertEqual(old.b[previous], rebased.b[current])
        self.assertEqual(rebased.training_receipt["steps"], 0)
        self.assertEqual(len(rebased.supports), 5)

    def test_frozen_parent_refuses_withdrawal_or_corrected_value(self):
        old = initialize(rows(), "semantic", CONFIG)
        changed = deepcopy(rows())
        changed[0]["record"]["value"]["factor"] = 99
        with self.assertRaises(ValueError):
            initialize(changed, "semantic", CONFIG, old)
        with self.assertRaises(ValueError):
            initialize(rows(2), "semantic", CONFIG, old)

    def test_byte_wire_contains_no_target_table_and_parent_bits_are_exact(self):
        selected = rows()
        arrays = initial_arrays()
        encoded, report = artifact(metadata(selected, "semantic"), arrays, {"steps": 0})
        wire = json.loads(encoded["native"])
        self.assertFalse({"catalog", "values", "labels", "lengths", "targets"} & set(wire))
        self.assertEqual(set(wire["supports"]), {sha(row["record"]["entity"].encode()) for row in selected})
        self.assertEqual(parameter_digest(initial_arrays(wire)), report["parameter_digest"])
        packed = np.packbits(targets(selected, "semantic").astype(np.uint8), axis=1)
        for row, bytes_row in zip(selected, packed):
            raw = bytes(bytes_row)
            length = int.from_bytes(raw[:2], "big")
            self.assertEqual(raw[2:2+length], typed_bytes(row["record"]["value"]))
            self.assertEqual(set(raw[2+length:]), {0})

    def test_byte_bound_counts_utf8_not_unicode_characters(self):
        selected = rows(1)
        selected[0]["record"]["value"]["label"] = "界" * 60
        with self.assertRaises(ValueError):
            targets(selected, "semantic")


if __name__ == "__main__":
    unittest.main()
