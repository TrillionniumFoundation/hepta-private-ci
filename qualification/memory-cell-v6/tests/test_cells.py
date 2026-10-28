"""Behavioral checks for actual training, causal reads and clean rebuilding."""

import hashlib
import json
import unittest

import numpy as np

from v6.cells import AssociativeCell, canonical, execute_program, key_digest
from v6.learning import LearningSession


class CellTests(unittest.TestCase):
    def test_trained_associations_survive_reload_and_depend_on_weights(self):
        keys = [f"nonce-{i:03d}" for i in range(24)]
        values = [{"factor": i % 4 + 1, "label": f"class-{i % 4}"} for i in range(24)]
        cell = AssociativeCell.fit(keys, values, seed=79, support_ids=[[f"source-{i}"] for i in range(24)])
        self.assertLess(
            cell.training_receipt["final_cross_entropy"], cell.training_receipt["initial_cross_entropy"] / 20
        )
        self.assertEqual([cell.read(key)["value"] for key in keys], values)
        loaded = AssociativeCell.from_bytes(cell.to_bytes())
        self.assertEqual([loaded.read(key) for key in keys], [cell.read(key) for key in keys])
        self.assertNotIn(keys[0].encode(), cell.to_bytes())
        self.assertEqual(cell.supports[key_digest(keys[0])], ["source-0"])
        self.assertIsNone(loaded.read("never-written-nonce")["value"])
        loaded.B.fill(0)
        loaded.b.fill(0)
        loaded.threshold = 0
        self.assertLess(sum(loaded.read(key)["value"] == value for key, value in zip(keys, values)), len(keys) / 2)
        self.assertGreater(cell.cost()["serialized_bytes"], cell.cost()["parameter_bytes"])

    def test_correction_and_transitive_deletion_require_clean_rebuild(self):
        session = LearningSession(seed=83)
        for i in range(12):
            session.write(f"source-{i}", f"key-{i}", {"factor": i % 3 + 1, "label": f"c{i % 3}"})
        session.rebuild()
        session.write("correction", "key-0", {"factor": 31, "label": "new"})
        self.assertEqual(session.read("key-0")["abstain"], "rebuild-required")
        session.rebuild(inherit=True)
        self.assertEqual(session.read("key-0")["value"], {"factor": 31, "label": "new"})
        self.assertIn("source-0", session.model.lineage_sources)
        session.revoke("source-0")
        self.assertEqual(session.read("key-0")["abstain"], "rebuild-required")
        with self.assertRaisesRegex(ValueError, "clean fit"):
            session.rebuild(inherit=True)
        session.rebuild()
        self.assertNotIn("source-0", session.model.lineage_sources)
        self.assertEqual(session.read("key-0")["value"], {"factor": 31, "label": "new"})
        session.revoke("source-1")
        session.rebuild()
        self.assertEqual(session.read("key-1")["abstain"], "outside-written-support")
        self.assertEqual(session.read("key-2")["value"], {"factor": 3, "label": "c2"})
        with self.assertRaisesRegex(ValueError, "new scoped"):
            session.write("resurrect", "key-1", {"factor": 99, "label": "old"})

    def test_replay_preserves_old_associations_when_new_entities_arrive(self):
        session = LearningSession(seed=89)
        for i in range(12):
            session.write(f"s-{i}", f"old-{i}", {"factor": i % 4, "label": "old"})
        session.rebuild()
        old = {row["key"]: row["value"] for row in session.valid_records()}
        for i in range(8):
            session.write(f"new-s-{i}", f"new-{i}", {"factor": i + 20, "label": "new"})
        receipt = session.rebuild(inherit=True)
        self.assertEqual({key: session.read(key)["value"] for key in old}, old)
        self.assertEqual(receipt["valid_rows"], 20)
        self.assertEqual(session.read("new-6")["value"], {"factor": 26, "label": "new"})

    def test_inherited_prefix_is_trained_and_wrong_base_is_rejected(self):
        parent = AssociativeCell.fit(["a", "b"], [1, 2], seed=7, hidden=16)
        child = AssociativeCell.fit(["a", "b", "c"], [1, 2, 3], seed=11, hidden=8, parent=parent)
        self.assertEqual(child.training_receipt["inherited_hidden_units"], 8)
        self.assertEqual([child.read(key)["value"] for key in ["a", "b", "c"]], [1, 2, 3])
        with self.assertRaisesRegex(ValueError, "incompatible"):
            AssociativeCell.fit(["a"], [1], parent=parent, dimension=32)

    def test_no_replay_control_keeps_catalog_and_initial_parameters_fixed(self):
        old_keys, old_values = [f"old-{i}" for i in range(12)], [i % 3 for i in range(12)]
        new_keys, new_values = [f"new-{i}" for i in range(8)], [3] * 8
        parent = AssociativeCell.fit(old_keys, old_values, seed=71)
        catalog = parent.catalog + new_values
        recent = AssociativeCell.fit(new_keys, new_values, seed=71, parent=parent, catalog_values=catalog)
        replay = AssociativeCell.fit(
            old_keys + new_keys, old_values + new_values, seed=71, parent=parent, catalog_values=catalog
        )
        self.assertEqual(recent.catalog, replay.catalog)
        self.assertEqual(recent.training_receipt["initial_parameters"], replay.training_receipt["initial_parameters"])
        raw_old = [recent.catalog[int(index)] for index in recent.probabilities(old_keys).argmax(axis=1)]
        self.assertLess(sum(a == b for a, b in zip(raw_old, old_values)), len(old_keys))
        self.assertEqual([replay.read(key)["value"] for key in old_keys], old_values)
        self.assertTrue(all(recent.read(key)["abstain"] == "outside-written-support" for key in old_keys))
        with self.assertRaisesRegex(ValueError, "fixed catalog"):
            AssociativeCell.fit(["x"], [99], catalog_values=[1, 2])

    def test_no_feasible_calibration_abstains_instead_of_claiming_confidence(self):
        cell = AssociativeCell.fit(["a", "b"], [1, 1])
        calibration = cell.calibrate(["a", "b"], [2, 2])
        self.assertFalse(cell.acceptance_enabled)
        self.assertEqual(calibration["selected"]["accepted"], 0)
        self.assertIsNotNone(AssociativeCell.from_bytes(cell.to_bytes()).read("a")["abstain"])

    def test_unknown_critical_fields_and_corrupt_tensors_are_rejected(self):
        cell = AssociativeCell.fit(["a", "b"], [1, 2])
        encoded = json.loads(cell.to_bytes())
        encoded["payload"]["answers"] = {"a": 1}
        encoded["sha256"] = hashlib.sha256(canonical(encoded["payload"])).hexdigest()
        with self.assertRaisesRegex(ValueError, "schema"):
            AssociativeCell.from_bytes(canonical(encoded))
        encoded = json.loads(cell.to_bytes())
        encoded["payload"]["arrays"]["A"]["shape"] = [1, 2]
        encoded["sha256"] = hashlib.sha256(canonical(encoded["payload"])).hexdigest()
        with self.assertRaisesRegex(ValueError, "shape"):
            AssociativeCell.from_bytes(canonical(encoded))

    def test_procedure_reads_feed_an_actual_bounded_interpreter(self):
        program = {"opcode": "affine", "bias": 7, "limit": 30}
        semantic = {"factor": 4, "label": "calibration"}
        cell = AssociativeCell.fit(["sensor"], [program], kind="procedure")
        restored = AssociativeCell.from_bytes(cell.to_bytes())
        self.assertEqual(execute_program(restored.read("sensor")["value"], 5, semantic), 27)
        self.assertEqual(execute_program({"opcode": "clamp", "bias": 0, "limit": 3}, -7, semantic), -3)
        self.assertEqual(execute_program({"opcode": "clamp", "bias": 7, "limit": 10}, 2, semantic), 10)
        with self.assertRaises(ValueError):
            execute_program({"opcode": "eval", "bias": 0, "limit": 0}, 1, semantic)
        with self.assertRaises(ValueError):
            execute_program(program, np.inf, semantic)
        with self.assertRaises(ValueError):
            execute_program(program, True, semantic)
        with self.assertRaises(ValueError):
            execute_program(program, 1_000_001, semantic)


if __name__ == "__main__":
    unittest.main()
