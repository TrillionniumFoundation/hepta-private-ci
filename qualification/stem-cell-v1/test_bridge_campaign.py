"""Variant persistence and closed-gate boundaries without real model training."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from bridge_campaign import continuation, feedback, warmup
from bridge_campaign_utils import (build_reader, checked_design, load_model,
    reader_identity, save_initialization, save_model, selected_model_paths, source_inventory, write)
from bridge_evaluation import evaluate
from group_encoder import file_digest


class BridgeCampaignTests(unittest.TestCase):
    def test_variant_round_trip_cannot_load_as_base_or_wrong_admitted_arm(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model = build_reader("bridge", 41).eval().requires_grad_(False)
            model.training_source_groups = ("train-source",)
            record = save_model(root, "selected", model, {"fixture": True}, seed=41)
            restored, same = load_model(root, "selected", expected_arm="bridge")
            self.assertEqual(reader_identity(model), reader_identity(restored))
            self.assertEqual(record, same)
            with self.assertRaisesRegex(ValueError, "admitted arm"):
                load_model(root, "selected", expected_arm="wide")
            record["architecture"]["arm"] = "base"
            write(root, "selected-model.json", record)
            with self.assertRaisesRegex(ValueError, "architecture contract"):
                load_model(root, "selected")

    def test_changed_initialization_bytes_are_rejected_before_encoder_loading(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old = root / "old"
            old.mkdir()
            write(old, "design.json", {})
            folder = root / "seed-41" / "bridge"
            save_initialization(folder, build_reader("bridge", 41), 41)
            relative = "seed-41/bridge/initialization.bin"
            design = dict(runtime_source_sha256=source_inventory(),
                previous_v5_design_sha256=file_digest(old / "design.json"),
                initialization_files_sha256={relative: file_digest(root / relative)}, historical_baselines={})
            write(root, "design.json", design)
            args = SimpleNamespace(output=root, previous_v5=old)
            with patch("bridge_campaign_utils.old_inputs", return_value=({}, {}, {})):
                self.assertEqual(checked_design(args), (design, {}, {}))
                path = root / relative
                path.write_bytes(path.read_bytes()[:-1] + b"x")
                with self.assertRaisesRegex(ValueError, "initialization evidence"):
                    checked_design(args)

    def test_failed_primary_closes_continuation_feedback_and_fresh_before_encoder(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = SimpleNamespace(output=root)
            write(root, "warmup-completion.json", dict(primary_all_passed=False))
            write(root, "continuation-completion.json", dict(contrastive_all_passed=False))
            write(root, "all-models-frozen.json", {})
            with patch("bridge_campaign.checked_design", return_value=({}, {}, {})), \
                    patch("bridge_campaign.load_bank") as bank:
                with self.assertRaisesRegex(ValueError, "bridge seeds"):
                    continuation(args)
                with self.assertRaisesRegex(ValueError, "retention"):
                    feedback(args)
                bank.assert_not_called()
            with patch("bridge_evaluation.checked_design", return_value=({}, {}, {})), \
                    patch("bridge_evaluation.load_bank") as bank:
                with self.assertRaisesRegex(ValueError, "gate closed"):
                    evaluate(args)
                bank.assert_not_called()
            self.assertFalse((root / "evaluation-start.json").exists())

    def test_started_attempt_cannot_silently_resume_or_repeat(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write(root, "warmup-start.json", dict(started_ns=1))
            with patch("bridge_campaign.checked_design", return_value=({}, {}, {})), \
                    patch("bridge_campaign.load_bank") as bank:
                with self.assertRaises(FileExistsError):
                    warmup(SimpleNamespace(output=root))
                bank.assert_not_called()

    def test_last_selected_weight_is_checked_before_fresh_start_or_encoding(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifests = {}
            for relative, selection in selected_model_paths().items():
                folder = (root / relative).parent
                seed = int(Path(relative).parts[0].split("-")[1])
                model = build_reader(selection["arm"], seed).eval().requires_grad_(False)
                model.training_source_groups = ("train-source",)
                save_model(folder, selection["name"], model, {"fixture": True}, seed=seed)
                manifests[relative] = file_digest(root / relative)
            last = root / relative
            record = json.loads(last.read_text())
            (last.parent / record["file"]).write_bytes(b"changed selected weights")
            write(root, "warmup-completion.json", dict(primary_all_passed=True))
            write(root, "continuation-completion.json", dict(contrastive_all_passed=True))
            write(root, "all-models-frozen.json", dict(manifests=manifests,
                runtime_source_sha256=source_inventory(), gate_evidence_sha256={}, frozen_ns=1))
            with patch("bridge_evaluation.checked_design", return_value=({}, {}, {})), \
                    patch("bridge_evaluation.load_bank") as bank:
                with self.assertRaisesRegex(ValueError, "weight or training receipt bytes"):
                    evaluate(SimpleNamespace(output=root))
                bank.assert_not_called()
            self.assertFalse((root / "evaluation-start.json").exists())


if __name__ == "__main__":
    unittest.main()
