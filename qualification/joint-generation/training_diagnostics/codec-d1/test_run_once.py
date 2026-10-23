"""Isolated failure persistence and handmade report-only observation checks."""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location("codec_master", Path(__file__).with_name("run_once.py"))
driver = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(driver)


class MasterTests(unittest.TestCase):
    def test_destination_failure_preserves_original_fault_and_other_receipt(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            out, stage = root / "out", root / "stage"
            out.mkdir(); stage.mkdir()
            fault = {"type": "RuntimeError", "error": "original actual cap"}
            terminal = {"fault": fault, "exit_code": 1}
            original = driver.write

            def write(path, value):
                if Path(path).parent == out:
                    raise PermissionError("handmade output failure")
                return original(path, value)

            with patch.object(driver, "DIRECTORY", stage), patch.object(driver, "write", side_effect=write):
                result = driver.persist_terminal(out, terminal)
            self.assertEqual(result["fault"], fault)
            self.assertEqual(result["exit_code"], 1)
            self.assertEqual(json.loads((stage / "PARTIAL.json").read_text())["fault"], fault)
            self.assertEqual(result["persistence_errors"][0]["type"], "PermissionError")

    def test_mkdir_failure_after_start_keeps_partial_and_runs_no_child(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            stage, runs = root / "stage", root / "runs"
            stage.mkdir(); runs.mkdir()
            freeze, out = root / "freeze.json", runs / "fixed"
            freeze.write_text("{}")
            plan = {"training_diagnostic": {"output_root": "runs/fixed", "build_order": ["A", "B", "B", "A"],
                                           "max_master_bytes": 2097152}}
            frozen = {"source_commit": "fixture", "plan_sha256": "fixture"}
            previous = Path.cwd()
            real_mkdir = Path.mkdir

            def mkdir(path, *args, **kwargs):
                if path == out:
                    raise PermissionError("handmade mkdir failure")
                return real_mkdir(path, *args, **kwargs)

            import sys
            try:
                with patch.object(driver, "ROOT", root), patch.object(driver, "DIRECTORY", stage), \
                     patch.object(driver, "source_guard", return_value=(frozen, plan)), \
                     patch.object(driver, "protected_files", return_value={}), \
                     patch.object(driver.subprocess, "check_output", return_value="fixture\n"), \
                     patch.object(driver, "execute_slot") as child, \
                     patch.object(Path, "mkdir", new=mkdir), \
                     patch.dict(sys.modules, {"analyze": object()}), \
                     patch.object(sys, "argv", ["run_once.py", "--freeze", str(freeze), "--out", str(out)]):
                    self.assertEqual(driver.main(), 1)
                    child.assert_not_called()
            finally:
                import os
                os.chdir(previous)
            self.assertTrue((stage / "START.json").is_file())
            terminal = json.loads((stage / "PARTIAL.json").read_text())
            self.assertEqual(terminal["fault"]["type"], "PermissionError")
            self.assertEqual(terminal["unexecuted_slots"], [0, 1, 2, 3])

    def test_report_only_risk_uses_handmade_inputs_without_training_or_dataset(self):
        import numpy as np
        from model import JointModel

        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            run, out = root / "slot", root / "report"
            run.mkdir(); out.mkdir(); (run / "train-evidence").mkdir()
            model = JointModel(202, 12, 192, hidden=2, seed=71)
            path = run / "model.npz"
            model.save(path)
            before = driver.sha(path)
            np.savez_compressed(run / "train-evidence/monitor.npz", full=np.zeros((2, 202)), labels=np.array([0, 1]))
            (run / "selection.json").write_text(json.dumps({"selected": [{"system": "ndu", "seed": 11,
                "model_file": "model.npz", "model_sha256": before}]}))
            with patch("independent.data_v2.dataset", side_effect=AssertionError("dataset")), \
                 patch.object(JointModel, "apply_gradients", side_effect=AssertionError("training")):
                result = driver.risk_observation([run], {"rho": 1.5, "ce_anchor": .2}, out)
            self.assertEqual(len(result["rows"]), 1)
            self.assertTrue(np.isfinite(result["rows"][0]["risk_mean"]))
            self.assertGreater(result["rows"][0]["ledger"]["consumed_units"], 0)
            self.assertEqual(driver.sha(path), before)
            self.assertTrue((out / "risk-observer-values.npz").is_file())


if __name__ == "__main__":
    unittest.main()
