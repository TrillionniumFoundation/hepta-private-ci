"""V7 transitive selections and once-only gate boundaries before Encoder access."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from bridge_campaign_utils import build_reader, save_model, write
from group_encoder import file_digest
from retention_campaign import feedback, train
from retention_campaign_utils import selected_models, source_inventory
from retention_evaluation import evaluate


class RetentionCampaignTests(unittest.TestCase):
    def test_joint_failure_blocks_feedback_and_fresh_before_loading_encoder(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = SimpleNamespace(output=root)
            write(root, "training-completion.json", dict(primary_all_passed=False))
            inputs = ({}, {"reader_train": ()}, {"train": ()}, ())
            with patch("retention_campaign.checked_design", return_value=inputs), \
                    patch("retention_campaign.load_bank") as bank:
                with self.assertRaisesRegex(ValueError, "joint qualification"):
                    feedback(args)
                bank.assert_not_called()
            with patch("retention_evaluation.checked_design", return_value=inputs), \
                    patch("retention_evaluation.load_bank") as bank:
                with self.assertRaisesRegex(ValueError, "joint gates"):
                    evaluate(args)
                bank.assert_not_called()
            self.assertFalse((root / "feedback-start.json").exists())
            self.assertFalse((root / "evaluation-start.json").exists())

    def test_failed_real_feedback_still_blocks_fresh(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write(root, "training-completion.json", dict(primary_all_passed=True))
            write(root, "feedback-completion.json", dict(primary_all_passed=False))
            with patch("retention_evaluation.checked_design", return_value=(
                    {}, {"reader_train": ()}, {"train": ()}, ())), \
                    patch("retention_evaluation.load_bank") as bank:
                with self.assertRaisesRegex(ValueError, "joint gates"):
                    evaluate(SimpleNamespace(output=root))
                bank.assert_not_called()
            self.assertFalse((root / "evaluation-start.json").exists())

    def test_started_training_attempt_cannot_silently_repeat(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write(root, "training-start.json", {})
            with patch("retention_campaign.checked_design", return_value=({}, {}, {}, ())), \
                    patch("retention_campaign.load_bank") as bank:
                with self.assertRaises(FileExistsError):
                    train(SimpleNamespace(output=root))
                bank.assert_not_called()

    def test_last_of_eighteen_weight_files_checked_before_fresh_marker(self):
        with tempfile.TemporaryDirectory() as directory:
            root, manifests = Path(directory), {}
            for relative, name in selected_models().items():
                seed = int(Path(relative).parts[0].split("-")[1])
                model = build_reader("bridge", seed).eval().requires_grad_(False)
                model.training_source_groups = ("train-fixture",)
                save_model((root / relative).parent, name, model, {"fixture": True}, seed=seed)
                manifests[relative] = file_digest(root / relative)
            record = json.loads((root / relative).read_text())
            ((root / relative).parent / record["file"]).write_bytes(b"changed final selection")
            for file in ("training-completion.json", "feedback-completion.json"):
                write(root, file, dict(primary_all_passed=True))
            write(root, "all-models-frozen.json", dict(manifests=manifests,
                runtime_source_sha256=source_inventory(), gate_evidence_sha256={}, frozen_ns=1))
            with patch("retention_evaluation.checked_design", return_value=(
                    {}, {"reader_train": ()}, {"train": ()}, ())), \
                    patch("retention_evaluation.load_bank") as bank:
                with self.assertRaisesRegex(ValueError, "weight or training receipt"):
                    evaluate(SimpleNamespace(output=root))
                bank.assert_not_called()
            self.assertFalse((root / "evaluation-start.json").exists())


if __name__ == "__main__":
    unittest.main()
