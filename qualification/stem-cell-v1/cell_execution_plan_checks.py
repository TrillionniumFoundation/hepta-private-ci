"""Finite episode costs and actual dispatch; synthetic values are not benchmarks."""
from dataclasses import asdict, replace
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

import torch

import cell_execution_plan as engine
from development_tensors import BasisCellHeads, parameter_digest
from bounded_multicell_probe import METHODS

SCOPE = "1"*64


class FiniteEpisodeChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.threads = torch.get_num_threads()
        torch.set_num_threads(1)

    @classmethod
    def tearDownClass(cls):
        torch.set_num_threads(cls.threads)

    def setUp(self):
        self.bank = BasisCellHeads(4, 2, 2, ("a", "b"), seed=17)
        g = torch.Generator().manual_seed(34)
        with torch.no_grad():
            self.bank.coefficients.normal_(0, .03, generator=g)
            self.bank.gates.normal_(0, .03, generator=g)
        self.x = torch.randn(4, 4, generator=g)
        self.f = torch.arange(40) % 4
        self.c = torch.arange(40) % 2
        self.profile = engine.CostProfile(
            engine._binding(self.bank, self.x, self.f, self.c, SCOPE), engine._runtime(),
            (engine.MethodCost(METHODS[0], 0, 150, 0), engine.MethodCost(METHODS[1], 0, 100, 0),
             engine.MethodCost(METHODS[2], 500, 10, 120), engine.MethodCost(METHODS[3], 0, 200, 0)),
            1000, "2"*64)

    def run_episode(self, profile=None, passes=1, budget=4096, x=None):
        with torch.no_grad():
            return engine.execute(self.bank, self.x if x is None else x, self.f, self.c,
                self.profile if profile is None else profile, passes=passes,
                compiled_byte_budget=budget, scope_digest=SCOPE)

    def test_finite_reuse_pays_real_startup_before_dense_can_win(self):
        self.assertEqual(engine.choose(self.profile, passes=1, compiled_byte_budget=4096)["method"], METHODS[1])
        self.assertEqual(engine.choose(self.profile, passes=10, compiled_byte_budget=4096)["method"], METHODS[2])

    def test_no_infinite_amortization_and_exact_integer_cost(self):
        r = engine.choose(self.profile, passes=5, compiled_byte_budget=4096)
        self.assertEqual(r["estimated_wall_ns"], 500)
        self.assertEqual(r["feasible_estimates_ns"][METHODS[2]], 550)

    def test_resident_budget_excludes_otherwise_fast_dense(self):
        r = engine.choose(self.profile, passes=32, compiled_byte_budget=0)
        self.assertEqual(r["method"], METHODS[1])
        self.assertNotIn(METHODS[2], r["feasible_estimates_ns"])

    def test_invalid_caps_rejected(self):
        for passes, budget in ((True, 0), (0, 0), (33, 0), (1, -1), (1, True), (1, 2**30)):
            with self.subTest(passes=passes, budget=budget), self.assertRaises(ValueError):
                engine.choose(self.profile, passes=passes, compiled_byte_budget=budget)

    def test_invalid_costs_and_duplicate_methods_rejected(self):
        for costs in ((self.profile.methods[0],)*4,
                      (replace(self.profile.methods[0], per_pass_ns=True), *self.profile.methods[1:]),
                      (replace(self.profile.methods[0], per_pass_ns=float("nan")), *self.profile.methods[1:]),
                      (replace(self.profile.methods[0], startup_ns=-1), *self.profile.methods[1:])):
            with self.subTest(costs=costs), self.assertRaises(ValueError):
                engine.choose(replace(self.profile, methods=costs), passes=1, compiled_byte_budget=0)

    def test_tie_has_fixed_order_not_latest_measurement(self):
        costs = tuple(engine.MethodCost(m, 1, 10, 0) for m in METHODS)
        r = engine.choose(replace(self.profile, methods=costs), passes=1, compiled_byte_budget=0)
        self.assertEqual(r["method"], METHODS[0])

    def test_shared_selection_never_compiles_dense_control(self):
        with patch.object(engine, "_fold", side_effect=AssertionError("must not compile")):
            output, report = self.run_episode(budget=0)
        self.assertEqual(report["executed_methods"], [METHODS[1]])
        self.assertEqual(report["compiled_numeric_bytes"], 0)
        with torch.no_grad():
            self.assertTrue(torch.allclose(output, self.bank(self.x[self.f], self.c), atol=1e-6))

    def test_dense_is_compiled_once_for_the_finite_episode(self):
        with patch.object(engine, "_fold", wraps=engine._fold) as compile_call:
            output, report = self.run_episode(passes=10)
        self.assertEqual(compile_call.call_count, 1)
        self.assertEqual(len(report["actual_pass_wall_ns"]), 10)
        self.assertEqual(report["compiled_numeric_bytes"], 120)
        self.assertEqual(report["compiled_bytes_retained_after_episode"], 0)
        with torch.no_grad():
            self.assertTrue(torch.allclose(output, self.bank(self.x[self.f], self.c), atol=1e-6))

    def test_actual_dense_bytes_not_self_declared_zero_bytes(self):
        costs = tuple(replace(c, compiled_bytes=0, startup_ns=0, per_pass_ns=1)
                      if c.method == METHODS[2] else c for c in self.profile.methods)
        with patch.object(engine, "_fold", side_effect=AssertionError("must not compile")):
            with self.assertRaisesRegex(ValueError, "actual compiled storage"):
                self.run_episode(profile=replace(self.profile, methods=costs), passes=10, budget=0)

    def test_new_values_same_layout_do_not_use_calibration_labels(self):
        changed = self.x + .3
        output, _ = self.run_episode(x=changed)
        with torch.no_grad():
            self.assertTrue(torch.allclose(output, self.bank(changed[self.f], self.c), atol=1e-6))
        self.assertNotEqual(output.tolist(), self.run_episode()[0].tolist())

    def test_parameter_drift_fails_before_model_dispatch(self):
        with torch.no_grad():
            self.bank.coefficients[0, 0] += 1
        with patch.object(engine, "_checked_comparison", side_effect=AssertionError("no dispatch")):
            with self.assertRaisesRegex(ValueError, "stale cost profile"):
                self.run_episode()

    def test_generation_or_runtime_drift_rejects_profile(self):
        self.bank.generation += 1
        with self.assertRaises(ValueError):
            self.run_episode()
        self.bank.generation -= 1
        with self.assertRaises(ValueError):
            self.run_episode(profile=replace(self.profile, runtime="f"*64))

    def test_scope_and_layout_drift_rejects_profile(self):
        self.f = self.f.roll(1)
        with self.assertRaises(ValueError):
            self.run_episode()
        self.f = self.f.roll(-1)
        with torch.no_grad(), self.assertRaises(ValueError):
            engine.execute(self.bank, self.x, self.f, self.c, self.profile,
                           passes=1, compiled_byte_budget=0, scope_digest="3"*64)

    def test_invalid_features_or_awake_state_never_execute(self):
        for values in (self.x*float("nan"), self.x[:, :3]):
            with self.subTest(shape=values.shape), self.assertRaises(ValueError):
                self.run_episode(x=values)
        self.bank.awake = (False, True)
        with self.assertRaises(ValueError):
            self.run_episode()

    def test_autograd_is_not_silently_disabled(self):
        with self.assertRaisesRegex(ValueError, "disabled autograd"):
            engine.execute(self.bank, self.x, self.f, self.c, self.profile,
                           passes=1, compiled_byte_budget=0, scope_digest=SCOPE)

    def test_calibration_costs_and_source_are_bound(self):
        with torch.no_grad():
            profile, original = engine.calibrate(self.bank, self.x, self.f, self.c, scope_digest=SCOPE)
        self.assertEqual(profile.calibration_record_sha256, engine._digest(original))
        self.assertGreater(profile.calibration_wall_ns, 0)
        self.assertEqual(len(original["trials"]), 16)
        for cost in profile.methods:
            self.assertEqual(cost.per_pass_ns, max(t["wall_ns"] for t in original["trials"] if t["method"] == cost.method))
        output, report = self.run_episode(profile=profile)
        self.assertEqual(report["prior_calibration_wall_ns"], profile.calibration_wall_ns)
        self.assertFalse(report["production_authorized"])

    def test_input_and_original_bank_never_updated(self):
        before, values = parameter_digest(self.bank), self.x.clone()
        self.run_episode(passes=10)
        self.assertEqual(parameter_digest(self.bank), before)
        self.assertTrue(torch.equal(self.x, values))

    def test_execution_error_is_not_retried_or_reported_success(self):
        with patch.object(engine, "_checked_comparison", side_effect=ValueError("fixture failure")) as dispatch:
            with self.assertRaisesRegex(ValueError, "fixture failure"):
                self.run_episode()
        self.assertEqual(dispatch.call_count, 1)

    def test_tiled_can_be_selected_without_persistent_matrices(self):
        costs = tuple(replace(c, startup_ns=0, per_pass_ns=1) if c.method == METHODS[3] else c
                      for c in self.profile.methods)
        _, report = self.run_episode(profile=replace(self.profile, methods=costs), budget=0)
        self.assertEqual(report["executed_methods"], [METHODS[3]])
        self.assertGreater(report["maximum_tile_scratch_bytes"], 0)
        self.assertEqual(report["compiled_numeric_bytes"], 0)


class PlanStudyChecks(unittest.TestCase):
    def test_real_study_precommits_all_choices_then_executes_new_values(self):
        import tempfile
        from cell_execution_plan_study import study_plan
        bank = BasisCellHeads(4, 2, 2, ("a", "b"), seed=21)
        g = torch.Generator().manual_seed(23)
        a, b = torch.randn(3, 4, generator=g), torch.randn(3, 4, generator=g)
        f, c = torch.arange(12) % 3, torch.arange(12) % 2
        with tempfile.TemporaryDirectory() as root, torch.no_grad():
            out = Path(root) / "study"
            result = study_plan(bank, a, b, f, c, out)
            plans = json.loads((out / "choices-before-execution.json").read_text())
            self.assertEqual(len(plans), 6)
            self.assertEqual([r["plan"] for r in result["episodes"]], plans)
            self.assertTrue(all(r["argmax_reversals"] == 0 for r in result["episodes"]))
            with self.assertRaises(FileExistsError):
                study_plan(bank, a, b, f, c, out)

    def test_measured_inputs_cannot_be_same_as_calibration(self):
        import tempfile
        from cell_execution_plan_study import study_plan
        bank = BasisCellHeads(4, 2, 2, ("a",), seed=21)
        with tempfile.TemporaryDirectory() as root, torch.no_grad():
            out = Path(root) / "study"
            with self.assertRaisesRegex(ValueError, "calibration inputs"):
                study_plan(bank, torch.ones(1, 4), torch.ones(1, 4),
                           torch.tensor([0]), torch.tensor([0]), out)
            self.assertTrue((out / "FAILED.json").exists())


class TensorDependencyChecks(unittest.TestCase):
    def test_actual_safetensors_torch_roundtrip(self):
        from safetensors.torch import load, save
        x = torch.arange(4)
        self.assertTrue(torch.equal(load(save({"x": x}))["x"], x))

    def test_missing_packaging_reproduces_the_hosted_import_failure(self):
        # Fresh process, fault injection only. Never remove installed packages.
        code = '''import sys, importlib.abc
class MissingPackaging(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "packaging" or fullname.startswith("packaging."):
            raise ModuleNotFoundError("No module named 'packaging'")
sys.meta_path.insert(0, MissingPackaging())
from safetensors.torch import load, save
'''
        p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=20)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("No module named 'packaging'", p.stderr)


if __name__ == "__main__":
    unittest.main()
