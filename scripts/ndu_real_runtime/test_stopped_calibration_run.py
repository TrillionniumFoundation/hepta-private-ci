"""Frozen-checkpoint diagnostic integration through the actual Torch runtime."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from .stopped_calibration_run import parse_args, run
from .stopped_torch import source_identity
from .test_stopped_diagnostics import registration
from .test_stopped_torch import linked, records


class DiagnosticTorchIntegrationTests(unittest.TestCase):
    def setUp(self):
        import torch
        from .neural import ReceiptPortfolioModel

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.weights = self.root / "weights.pt"
        torch.manual_seed(73)
        torch.save(ReceiptPortfolioModel("ordinary").state_dict(), self.weights)
        self.digest = hashlib.sha256(self.weights.read_bytes()).hexdigest()
        self.rows = []
        for group in ("c1", "c2", "d1", "d2"):
            sequence = records()
            for index, row in enumerate(sequence):
                row.update(
                    source_group=group,
                    episode_id=group,
                    origin_run_id="run-" + group,
                    record_id=f"run-{group}/transition/{index:02d}",
                    behavior_weights_sha256=self.digest,
                )
            self.rows.extend(linked(sequence))
        self.data = self.root / "records.jsonl"
        self.data.write_text("".join(json.dumps(x) + "\n" for x in self.rows))
        self.reg = self.root / "registration.json"
        self.reg.write_text(json.dumps(registration()))
        self.meta = self.root / "metadata.json"
        self.meta.write_text(
            json.dumps(
                {
                    "status": "CONTENT_PRETRAINED",
                    "core": "ordinary",
                    "weights_sha256": self.digest,
                    "records": {"source_groups": 1},
                    "fixture_only": True,
                }
            )
        )

    def arguments(self, suffix):
        args = [
            "--output",
            str(self.root / suffix),
            "--device",
            "cpu",
            "--max-wall-seconds",
            "60",
            "--expected-source-sha256",
            source_identity(),
        ]
        for name, path in (
            ("records", self.data),
            ("weights", self.weights),
            ("registration", self.reg),
            ("behavior-metadata", self.meta),
        ):
            args += [
                "--" + name,
                str(path),
                "--expected-" + name + "-sha256",
                hashlib.sha256(path.read_bytes()).hexdigest(),
            ]
        return parse_args(args)

    def test_actual_driver_keeps_observed_predictions_separate_from_policy_return(self):
        before = self.weights.read_bytes()
        args = self.arguments("complete")
        self.assertEqual(run(args), 0)
        receipt = json.loads((args.output / "receipt.json").read_text())
        self.assertEqual(receipt["status"], "completed")
        self.assertEqual(receipt["diagnostic_status_counts"], {"supported": 4})
        self.assertEqual(receipt["bank"]["calibration_source_groups"], 2)
        self.assertFalse(receipt["net_benefit_established"])
        self.assertEqual(receipt["independent_training_repeats"], 0)
        for row in (args.output / "diagnostics.jsonl").read_text().splitlines():
            item = json.loads(row)
            self.assertFalse(item["counterfactual_outcomes_created"])
            for result in item["prediction_sensitivity"]:
                self.assertIsNone(result["actual_outcome_for_choice"])
                alignment = result["ordinary_risk_alignment"]
                self.assertTrue(alignment["selected_action_equal"])
                self.assertTrue(alignment["values_equal_within_1e12"])
                self.assertFalse(alignment["independent_ndu_benefit_established"])
        self.assertEqual(before, self.weights.read_bytes())

    def test_training_roster_cannot_be_shrunk_to_relabel_known_fit_extent(self):
        meta = json.loads(self.meta.read_text())
        meta["records"]["source_groups"] = 40
        self.meta.write_text(json.dumps(meta))
        args = self.arguments("refused")
        self.assertEqual(run(args), 1)
        receipt = json.loads((args.output / "receipt.json").read_text())
        self.assertEqual(receipt["status"], "failed")
        self.assertEqual(receipt["diagnostic_macros_attempted"], 0)
        self.assertTrue((args.output / "traceback.txt").is_file())


if __name__ == "__main__":
    unittest.main()
