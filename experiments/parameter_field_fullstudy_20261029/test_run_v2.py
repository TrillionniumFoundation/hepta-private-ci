"""Synthetic operational tests; no model assets, banks or endpoint roles."""
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import patch

from . import run_v2 as r


class Storage:
    def __init__(self):
        self.calls = []

    def check(self, additional=0):
        if type(additional) is not int or additional < 0:
            raise ValueError("Invalid payload")
        self.calls.append(additional)


class RunV2Tests(unittest.TestCase):
    def test_phase_budgets_keep_original_counts_and_accept_exact_pending_bytes(self):
        for phase, cap in r.CAPS.items():
            if phase == "R":
                continue
            storage = Storage()
            costs = SimpleNamespace(values={"scheduled_gradient_microsteps": cap})
            budget = r.phase_budget_type(storage, "/tmp/registered-root", phase)("/tmp/registered-root", costs, phase)
            budget(37)
            self.assertEqual(storage.calls, [37])
            costs.values["scheduled_gradient_microsteps"] += 1
            with self.assertRaises(ValueError):
                budget()
            with self.assertRaises(ValueError):
                budget(-1)

    def test_scope_and_original_time_gates_are_preserved(self):
        cls = r.phase_budget_type(Storage(), "/tmp/a", "A")
        with self.assertRaises(ValueError):
            cls("/tmp/b", SimpleNamespace(values={}), "A")
        with self.assertRaises(ValueError):
            cls("/tmp/a", SimpleNamespace(values={}), "B")
        budget = cls("/tmp/a", SimpleNamespace(values={}), "A")
        budget.wall -= 10801
        with self.assertRaises(ValueError):
            budget()
        budget.wall += 10801
        budget.cpu -= 7201
        with self.assertRaises(ValueError):
            budget()

    def test_replay_override_keeps_inherited_serialization_methods(self):
        class Old:
            def __init__(self, root, costs):
                self.root, self.costs = root, costs
                self.wall, self.cpu = r.time.monotonic(), r.time.process_time()

            def write(self, path, payload):
                return (path, payload)

        storage = Storage()
        costs = SimpleNamespace(values={"scheduled_gradient_microsteps": 32256})
        cls = r.replay_budget_type(Old, storage, "/tmp/r")
        budget = cls("/tmp/r", costs)
        self.assertIs(cls.write, Old.write)
        budget.check(101)
        self.assertEqual(storage.calls, [101])
        costs.values["scheduled_gradient_microsteps"] += 1
        with self.assertRaises(ValueError):
            budget.check()

    def test_process_local_override_is_restored_on_failure(self):
        original, replacement = object(), object()
        module = SimpleNamespace(__name__="synthetic_original", Budget=original)
        argv = sys.argv
        with self.assertRaisesRegex(RuntimeError, "synthetic"):
            with r.scoped_runner(module, "Budget", replacement, ["--seed", "17"]):
                self.assertIs(module.Budget, replacement)
                self.assertEqual(sys.argv, ["synthetic_original", "--seed", "17"])
                raise RuntimeError("synthetic")
        self.assertIs(module.Budget, original)
        self.assertIs(sys.argv, argv)

    def test_frozen_closure_rejects_escape_and_mutation(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            source = root / "module.py"
            source.write_text("value = 1\n")
            freeze = {"source_files": {"module.py": r.file_hash(source)}}
            r.verify_files(freeze, root)
            source.write_text("value = 2\n")
            with self.assertRaises(ValueError):
                r.verify_files(freeze, root)
            with self.assertRaises(ValueError):
                r.verify_files({"source_files": {"../module.py": "0" * 64}}, root)

    def test_completion_population_paths(self):
        self.assertEqual(r.completion_path("/tmp/raw", "W", None), Path("/tmp/raw/stage_W/COMPLETE.json"))
        for phase in ("A", "B", "R"):
            for seed in (17, 29, 43):
                self.assertEqual(r.completion_path("/tmp/raw", phase, seed), Path(f"/tmp/raw/stage_{phase}/seed-{seed}/COMPLETE.json"))


if __name__ == "__main__":
    unittest.main()
