"""Training-role guards and bounded orchestration on small local fixtures."""

import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import numpy as np

from action_microbatch_compare import file_sha
from probe_action_microbatch_training import prepare_bank, run_probe


class ActionTrainingProbeTests(unittest.TestCase):
    def fixture(self):
        metadata = {"schema": "hepta.action-runtime-input-bundle.v1", "task_id": "action_usefulness",
            "generation": 1, "width": 770, "classes": 2, "feature_identity": "a"*64,
            "training": {"role": "train", "budget": 32, "seed": 7}}
        x = np.random.default_rng(725).normal(size=(32, 770)).astype(np.float32)
        y = np.arange(32, dtype=np.int64) % 2
        rows = [{"source_id": f"s-{i}", "group_id": f"g-{i}"} for i in range(32)]
        return metadata, x, y, rows

    def test_training_roles_and_independent_bug_count_are_enforced(self):
        metadata, x, y, rows = self.fixture()
        bank = prepare_bank(metadata, x, y, rows)
        np.testing.assert_array_equal(bank.raw_rows("action_usefulness"), x)
        metadata["training"]["role"] = "calibration"
        with self.assertRaisesRegex(ValueError, "train-only"):
            prepare_bank(metadata, x, y, rows)
        metadata["training"]["role"] = "train"
        rows[-1]["group_id"] = rows[0]["group_id"]
        with self.assertRaisesRegex(ValueError, "train-only"):
            prepare_bank(metadata, x, y, rows)

    def test_complete_small_fixture_has_persisted_parameters_and_fresh_process_recovery(self):
        fixture = self.fixture()
        module = types.ModuleType("cell_runtime_bundle")
        module.load_training_inputs = lambda root, *, expected_manifest_sha256: fixture
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)/"probe"
            with patch.dict(sys.modules, {"cell_runtime_bundle": module}), \
                    patch("probe_action_microbatch_training.SCALES", (2,)), \
                    patch("probe_action_microbatch_training.MODES", ("linear",)), \
                    patch("probe_action_microbatch_training.CODE_FILES", ("action_microbatch_compare.py",)), \
                    contextlib.redirect_stdout(io.StringIO()):
                result = run_probe(Path(temporary)/"input", "b"*64, root)
            self.assertEqual(result["task_count"], 1)
            self.assertEqual(result["actual_total_private_optimizer_updates_both_methods"], 80)
            self.assertEqual(result["actual_total_example_updates_both_methods"], 2560)
            checkpoint = root/"linear-2"
            child = subprocess.run([sys.executable, str(Path(__file__).with_name("probe_action_microbatch_training.py")),
                "--verify-checkpoint", str(checkpoint), "--checkpoint-manifest-sha256", file_sha(checkpoint/"checkpoint.json")],
                capture_output=True, text=True, check=True, timeout=30)
            recovered = json.loads(child.stdout)
            self.assertEqual([r["cell_index"] for r in recovered["restored_head_checks"]], [0, 1])
            self.assertEqual(recovered["optimizer_updates"], 0)
            manifest = json.loads((root/"manifest.json").read_bytes())
            for relative, spec in manifest.items():
                self.assertEqual(spec, {"sha256": file_sha(root/relative), "bytes": (root/relative).stat().st_size})
            with self.assertRaisesRegex(ValueError, "fresh owned"):
                run_probe(Path(temporary)/"input", "b"*64, root)

    def test_end_of_run_changed_inputs_leave_a_costed_failed_attempt(self):
        fixture = self.fixture()
        changed = (fixture[0], fixture[1]+1, fixture[2], fixture[3])
        module = types.ModuleType("cell_runtime_bundle")
        reads = iter((fixture, changed))
        module.load_training_inputs = lambda root, *, expected_manifest_sha256: next(reads)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)/"probe"
            with patch.dict(sys.modules, {"cell_runtime_bundle": module}), \
                    patch("probe_action_microbatch_training.SCALES", (1,)), \
                    patch("probe_action_microbatch_training.MODES", ("linear",)), \
                    patch("probe_action_microbatch_training.CODE_FILES", ("action_microbatch_compare.py",)), \
                    contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(ValueError, "changed during"):
                    run_probe(Path(temporary)/"input", "b"*64, root)
            failure = json.loads((root/"failed-attempt.json").read_bytes())
            self.assertEqual(failure["completed_conditions"], 1)
            self.assertTrue(failure["partial_work_is_not_zero_cost"])
            self.assertGreater(failure["wall_ns"], 0)
            self.assertFalse((root/"report.json").exists())
            condition = json.loads((root/"linear-1"/"report.json").read_bytes())
            self.assertEqual(condition["actual_total_private_optimizer_updates_both_methods"], 40)

    def test_code_pins_precede_input_loading_and_failure_preserves_missing_file(self):
        fixture, events = self.fixture(), []
        code = {"action_microbatch_compare.py": "a"*64}
        def pin():
            events.append("code snapshot")
            return code.copy()
        def load(root, *, expected_manifest_sha256):
            self.assertEqual(events[0], "code snapshot")
            events.append("input load")
            code["action_microbatch_compare.py"] = None
            return fixture
        module = types.ModuleType("cell_runtime_bundle")
        module.load_training_inputs = load
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)/"probe"
            with patch.dict(sys.modules, {"cell_runtime_bundle": module}), \
                    patch("probe_action_microbatch_training.SCALES", (1,)), \
                    patch("probe_action_microbatch_training.MODES", ("linear",)), \
                    patch("probe_action_microbatch_training.source_code_snapshot", side_effect=pin), \
                    contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(ValueError, "changed during"):
                    run_probe(Path(temporary)/"input", "b"*64, root)
            failure = json.loads((root/"failed-attempt.json").read_bytes())
            self.assertEqual(failure["source_code_sha256_initial"], {"action_microbatch_compare.py": "a"*64})
            self.assertEqual(failure["source_code_sha256_observed_at_failure"], {"action_microbatch_compare.py": None})
            self.assertEqual(failure["changed_code_files"],
                {"action_microbatch_compare.py": {"initial": "a"*64, "observed": None}})


if __name__ == "__main__":
    unittest.main()
