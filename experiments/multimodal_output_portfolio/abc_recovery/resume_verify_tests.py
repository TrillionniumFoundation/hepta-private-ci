"""Synthetic suffix replay verifies real Adam state, media and gradient continuity."""

from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import torch
from torch.torch_version import TorchVersion

from ..v6.data import SourceCorpus, SourceSplit
from ..v6.observer import Recognizer
from ..v7.model import SlotPortfolio
from ..v7.snapshot import Snapshot
from .output_training import fit_arm
from .resume_verify import file_sha, load_verified_checkpoint, verify_resume


class ResumeVerifyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(2)
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary.name)
        rng = torch.Generator().manual_seed(61)
        images = torch.randint(256, (24, 1, 28, 28), generator=rng, dtype=torch.uint8)
        source = SourceSplit(images, torch.arange(24) % 10, tuple(f"resume-unit:{i}" for i in range(24)),
                             tuple(hashlib.sha256(image.numpy().tobytes()).hexdigest() for image in images))
        cls.corpus = SourceCorpus({"train": source}, {"manifest_sha256": "resume-unit-only"})
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(7)
            warm = Snapshot(SlotPortfolio(), {"source_manifest_sha256": "resume-unit-only"})
            cls.observer = Recognizer().eval().requires_grad_(False)
        protocol = json.loads(Path(__file__).with_name("protocol.json").read_text())
        protocol.update(study="synthetic-resume-unit-only", training_seeds=[17])
        protocol["training"].update(fine_tuning_steps=3, fine_tuning_conditions_per_step=2,
                                    fine_tuning_scenarios_per_condition=2, checkpoint_interval=1)
        cls.arms = protocol["training"]["arms"]
        with redirect_stdout(io.StringIO()):
            for arm in cls.arms:
                fit_arm(warm, cls.corpus, cls.observer, cls.root / arm, 17, arm, protocol)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_three_objectives_resume_exact_actual_outputs_all_parameters_and_adam(self):
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            for arm in self.arms:
                with self.subTest(arm=arm), torch.inference_mode():
                    report = verify_resume(self.root / arm, self.corpus, self.observer,
                                           Path(directory) / arm, start_step=1)
                    self.assertTrue(report["passed"], report)
                    self.assertEqual(report["matched_suffix_steps"], 2)
                    self.assertEqual(report["checks"]["exact_output_rows"], 8)
                    self.assertEqual(report["checks"]["exact_terminal_logprob_checks"], 8)
                    self.assertEqual(report["checks"]["actual_media_member_hashes"], 16)
                    self.assertEqual(report["checks"]["final_rng_tensor_checks"], 2)
                    self.assertGreater(report["checks"]["final_adam_tensor_checks"], 0)
                    self.assertGreater(report["checks"]["final_parameter_tensor_checks"], 0)
                    self.assertEqual(report["work"]["optimizer_updates"], 2)
                    self.assertEqual(report["work"].get("output_score_gradient_probe_backwards", 0),
                                     0 if arm == "sft_continuation" else 2)
                    summary = json.loads((self.root / arm / "summary.json").read_text())
                    self.assertEqual(report["original_and_replayed_full_row_sha256"], summary["training_rows_sha256"])
                    self.assertEqual(report["final_parameter_sha256"], summary["final_parameter_sha256"])

    def test_changed_adam_moment_cannot_pass_suffix_continuity(self):
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            source = Path(shutil.copytree(self.root / "output_mean", Path(directory) / "altered"))
            path = source / "checkpoints/step-0001.pt"
            checkpoint = torch.load(path, weights_only=True)
            next(iter(checkpoint["optimizer_state_dict"]["state"].values()))["exp_avg"].add_(.1)
            torch.save(checkpoint, path)
            summary = json.loads((source / "summary.json").read_text())
            row = next(row for row in summary["optimizer_checkpoints"] if row["step"] == 1)
            row.update(sha256=file_sha(path), bytes=path.stat().st_size)
            (source / "summary.json").write_text(json.dumps(summary))
            report = verify_resume(source, self.corpus, self.observer, Path(directory) / "failed", start_step=1)
            self.assertFalse(report["passed"])
            self.assertLess(report["matched_suffix_steps"], 2)
            self.assertTrue((Path(directory) / "failed/failure.json").is_file())

    def test_checkpoint_hash_checked_before_any_deserialization(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "wrong.pt"
            path.write_bytes(b"not a checkpoint")
            with patch("torch.load") as load:
                with self.assertRaisesRegex(ValueError, "before deserialization"):
                    load_verified_checkpoint(path, "0" * 64)
                load.assert_not_called()

    def test_known_torch_version_subclass_uses_only_named_safe_global(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "known-version.pt"
            torch.save({"version": TorchVersion(str(torch.__version__)), "tensor": torch.arange(3)}, path)
            record, allowed = load_verified_checkpoint(path, file_sha(path))
            self.assertEqual(allowed, ["torch.torch_version.TorchVersion"])
            self.assertEqual(str(record["version"]), str(torch.__version__))
            self.assertTrue(torch.equal(record["tensor"], torch.arange(3)))


if __name__ == "__main__":
    unittest.main()
