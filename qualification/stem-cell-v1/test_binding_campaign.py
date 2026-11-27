"""Campaign boundary checks without loading an Encoder or training models."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from binding_campaign import continuation, feedback
from binding_campaign_utils import load_model, save_model, write
from binding_evaluation import evaluate, public_permutation, _transitions
from binding_protocol import build_binding_protocol
from token_reader import TokenReader


class BindingCampaignTests(unittest.TestCase):
    def test_failed_learning_gate_blocks_dependent_phases_before_encoder_loading(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = SimpleNamespace(output=root)
            write(root, "warmup-completion.json", dict(all_passed=False))
            write(root, "continuation-completion.json", dict(contrastive_all_passed=False))
            write(root, "all-models-frozen.json", {})
            with patch("binding_campaign.checked_design", return_value=({}, {}, {})), \
                    patch("binding_campaign.load_bank") as load:
                with self.assertRaisesRegex(ValueError, "warmups"):
                    continuation(args)
                with self.assertRaisesRegex(ValueError, "retention"):
                    feedback(args)
                load.assert_not_called()
            with patch("binding_evaluation.checked_design", return_value=({}, {}, {})), \
                    patch("binding_evaluation.load_bank") as load:
                with self.assertRaisesRegex(ValueError, "gate closed"):
                    evaluate(args)
                load.assert_not_called()
            self.assertFalse((root / "evaluation-start.json").exists())

    def test_checkpoint_round_trip_checks_both_digest_names_and_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model = TokenReader(384, 32).eval().requires_grad_(False)
            model.training_source_groups = ("training-source",)
            record = save_model(root, "selected", model, {"fixture": True})
            restored, same = load_model(root, "selected")
            self.assertEqual(record, same)
            self.assertEqual(restored.training_source_groups, model.training_source_groups)
            record["execution_parameter_sha256"] = record["training_parameter_sha256"]
            write(root, "selected-model.json", record)
            with self.assertRaisesRegex(ValueError, "named weight digest"):
                load_model(root, "selected")
            path = root / "selected.pt"
            path.write_bytes(path.read_bytes() + b"changed")
            with self.assertRaisesRegex(ValueError, "weight bytes"):
                load_model(root, "selected")

    def test_public_feedback_shuffle_is_reproducible_complete_and_deranged(self):
        ids = [case.case_id for case in build_binding_protocol()["fresh_combinations"][:16]]
        permutation = public_permutation(ids, 41)
        self.assertEqual(permutation, public_permutation(ids, 41))
        self.assertEqual(sorted(permutation), list(range(16)))
        self.assertTrue(all(i != donor for i, donor in enumerate(permutation)))

    def test_failed_child_retains_startup_exit_cost_and_log_without_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = subprocess.run([sys.executable, str(Path(__file__).with_name("binding_process.py")),
                "--receipt", str(root / "receipt.json"), "--log", str(root / "child.log"),
                "--", sys.executable, "-c", "print('retained failure'); raise SystemExit(3)"],
                capture_output=True, text=True)
            receipt = json.loads((root / "receipt.json").read_text())
            self.assertEqual((result.returncode, receipt["exit_code"], receipt["retry_performed"]), (3, 3, False))
            self.assertIn("retained failure", (root / "child.log").read_text())
            self.assertGreater(receipt["wall_ns"], 0)
            self.assertGreater(receipt["cpu_ns"], 0)

    def test_transition_counts_include_damage_and_handle_no_initial_error(self):
        cases = build_binding_protocol()["reader_train"][:4]
        truth = [case.label for case in cases]
        initial = [1 - truth[0], *truth[1:]]
        final = [truth[0], 1 - truth[1], *truth[2:]]
        report = _transitions(cases, initial, final)
        self.assertEqual((report["initial_wrong"], report["corrected"], report["damaged"],
                          report["net_corrected"]), (1, 1, 1, 0))
        self.assertIsNone(_transitions(cases, truth, truth)["wrong_to_correct_rate"])


if __name__ == "__main__":
    unittest.main()
