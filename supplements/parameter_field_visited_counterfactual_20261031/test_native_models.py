"""Focused pure/AST fixtures; no model or scientific outcome is constructed."""
import ast
from copy import deepcopy
import hashlib
import importlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import time

from . import counterfactual as k, native_common as n, native_models as m


def original_class(relative, name):
    roots = (Path(__file__).resolve().parents[2], Path("/workspace/scratch/092b68f38152/source-87c-git"))
    path = next((root / relative for root in roots if (root / relative).is_file()), None)
    if path is None:
        raise ValueError("Exact registered scientific source is unavailable for fixture")
    tree = ast.parse(path.read_text())
    selected = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == name)
    namespace = {"time": time}
    exec(compile(ast.Module(body=[selected], type_ignores=[]), str(path), "exec"), namespace)
    return namespace[name]


class NativeModelsTests(unittest.TestCase):
    def test_original_costs_and_work_physical_counter_is_not_rolled_back(self):
        classes = (
            original_class("experiments/multimodal_output_portfolio/field_bridge_v3_20261027/training_common.py", "Costs"),
            original_class("experiments/parameter_field_fullstudy_20261029/architecture_kernel.py", "Work"),
        )
        with tempfile.TemporaryDirectory() as temporary:
            for index, original in enumerate(classes):
                output = m.LiteralOutput(Path(temporary) / str(index))
                ledger = m.PhysicalLedger(output)
                costs = m.tracked_cost_type(original, ledger)()
                snapshot = costs.snapshot()
                costs.add("directional_backward_calls")
                costs.add("scheduled_gradient_microsteps")
                costs.add("discarded_microsteps", 1)
                self.assertEqual(ledger.count, 1)
                self.assertEqual(m.physical_steps(costs.values), 1)
                self.assertNotEqual(costs.snapshot(), snapshot)
                item = ledger.close()
                self.assertEqual(len(n.checked(item).read_text().splitlines()), 1)

    def test_completed_step_is_preserved_before_resource_failure(self):
        original = original_class("experiments/parameter_field_fullstudy_20261029/architecture_kernel.py", "Work")
        with tempfile.TemporaryDirectory() as temporary:
            def fail(*args):
                raise ValueError("resource stop")
            output = m.LiteralOutput(Path(temporary) / "out", fail)
            ledger = m.PhysicalLedger(output)
            costs = m.tracked_cost_type(original, ledger)()
            with self.assertRaisesRegex(ValueError, "resource stop"):
                costs.add("scheduled_gradient_microsteps")
            item = ledger.close()
            self.assertEqual(ledger.count, 1)
            self.assertEqual(len(n.checked(item).read_text().splitlines()), 1)

    def test_b_rejection_keeps_48_completed_steps_without_double_count(self):
        spec = next(iter(k.PARENTS.values()))
        receipt = {"action_index": 1, "start": 0, "end": 48, "schedule_id": spec["schedule"],
                   "multiplier": .25, "before": {"parameters": "a"*64, "optimizer": "b"*64},
                   "candidate": {"parameters": "c"*64, "optimizer": "d"*64},
                   "after": {"parameters": "a"*64, "optimizer": "b"*64},
                   "accepted": False, "guard_delta": -.1, "guard_values": [0.],
                   "guard_output_sha256": ["e"*64], "schedule_sha256": "f"*64,
                   "clock_advances_on_rejection": True,
                   "resources": {"scheduled_gradient_microsteps": 48, "discarded_gradient_microsteps": 48}}
        result = m.normalized(spec, receipt, "1"*64)
        self.assertEqual(result["scheduled_gradient_microsteps"], 48)
        self.assertEqual(result["native_after"], result["native_before"])

    def test_c_tape_identity_uses_complete_fixed_tape_and_not_loss(self):
        spec = next(row for row in k.PARENTS.values() if row["stage"] == "C")
        receipt = {"action": 2, "start": 0, "end": 16, "schedule": 8000, "multiplier": 1.,
                   "before": "a"*64, "candidate": "b"*64, "after": "b"*64,
                   "accepted": True, "guard_delta": 0., "guard_values": [0.],
                   "guard_output_sha256": ["c"*64], "clock_advances": True,
                   "microsteps": [{"step": i, "tape_identity": str(i), "noise_seed": i, "loss": i+1.}
                                  for i in range(16)],
                   "work_before": {"counts": {}}, "work_after": {"counts": {"native.scheduled_gradient_microsteps": 16}}}
        first = m.normalized(spec, receipt, "d"*64)
        changed = deepcopy(receipt)
        changed["microsteps"][0]["loss"] = -99.
        self.assertEqual(first["tape_sha256"], m.normalized(spec, changed, "d"*64)["tape_sha256"])
        changed["microsteps"].pop()
        with self.assertRaisesRegex(ValueError, "incomplete"):
            m.normalized(spec, changed, "d"*64)

    def test_semantic_receipt_excludes_only_costs(self):
        value = {"work_before": {"cpu_seconds": 7}, "work_after": {"cpu_seconds": 8},
                 "guard_values": [1], "parameter": "a"}
        self.assertEqual(m.semantic_receipt("C", value), {"guard_values": [1], "parameter": "a"})
        other = {"resources": {"cpu": 1}, "guard_delta": .2, "start": 0}
        self.assertEqual(m.semantic_receipt("B", other), {"guard_delta": .2, "start": 0})
        self.assertIn("resources", other)

    def test_literal_outputs_are_exclusive_and_hash_readback(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "out"
            output = m.LiteralOutput(root)
            item = output.bytes("nested/state", b"synthetic")
            self.assertEqual(item["sha256"], hashlib.sha256(b"synthetic").hexdigest())
            for name in ("nested/state", "../escape", "/absolute"):
                with self.assertRaises(ValueError):
                    output.bytes(name, b"x")
            with self.assertRaises(FileExistsError):
                m.LiteralOutput(root)
            output.unchanged()
            Path(item["path"]).write_bytes(b"wrong")
            with self.assertRaises(ValueError):
                output.unchanged()

    def test_wrong_original_module_location_is_rejected_before_usage(self):
        with patch.object(importlib, "import_module", return_value=type("Module", (), {"__file__": "/tmp/wrong.py"})):
            with self.assertRaisesRegex(ValueError, "another source"):
                m.original_module(Path("/work/source"), m.PREFIX + "run")


if __name__ == "__main__":
    unittest.main()
