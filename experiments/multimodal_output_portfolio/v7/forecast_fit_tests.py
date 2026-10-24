"""Unit-only synthetic tables exercise OOF/CRPS/admission, not research samples."""

from copy import deepcopy
import unittest

import torch

from .forecast import FEATURE_DIM
from .forecast_data import EndpointData
from .forecast_fit import fit_forecast
from .metric import MetricContract
from .model import SlotPortfolio
from .plans import ControlledSnapshot, PlanHead
from .snapshot import Snapshot


class ForecastFitTests(unittest.TestCase):
    def test_grouped_fit_calibration_and_cross_role_leak_rejection(self):
        torch.set_num_threads(2)
        torch.manual_seed(17)
        snapshot = ControlledSnapshot(Snapshot(SlotPortfolio()), PlanHead())
        contract = MetricContract("unit_only", 3, 3, -1., 1., "a" * 64,
                                  (("unit_observer", "b" * 64),), "raw_png_utf8")
        rng = torch.Generator().manual_seed(67)

        def dataset(role, offset):
            features = torch.randn(24, FEATURE_DIM, generator=rng)
            targets = torch.full((24, 21), float("nan"), dtype=torch.float64)
            targets[:, 0] = torch.linspace(-.8, .8, 24)
            targets[::3, 1:] = .7
            return EndpointData(features, targets, torch.arange(8).repeat_interleave(3), [], {
                "role": role, "pairs": 8, "snapshot_sha256": snapshot.fingerprint,
                "metric_contract_sha256": contract.validate(), "source_manifest_sha256": "d" * 64,
                "source_pair_sha256": f"{offset:064x}", "candidate_family": "unit only",
                "views": ["unit"], "scenarios": 4,
                "source_pairs": [[f"unit:{offset + i * 2}:pixel-{offset + i * 2}",
                                  f"unit:{offset + i * 2 + 1}:pixel-{offset + i * 2 + 1}"] for i in range(8)],
            })

        fitting = dataset("forecast_fit", 100)
        calibration = dataset("forecast_calibration", 200)
        artifact, evidence = fit_forecast(snapshot, fitting, calibration, contract,
                                          seed=17, steps=2, batch_size=8)
        self.assertEqual([(fold["held_source_pairs"], fold["train_source_pairs"])
                          for fold in evidence["folds"]], [(2, 6)] * 4)
        self.assertGreater(evidence["final_training"]["gradient_abs_sum_max"], 0)
        self.assertGreaterEqual(artifact.calibration["radius"], 0)
        self.assertLessEqual(artifact.calibration["radius"], 2)
        self.assertEqual(evidence["calibration_diagnostic"]["labeled_predictions"], 184)
        changed = deepcopy(calibration)
        changed.evidence["source_pairs"][0] = fitting.evidence["source_pairs"][0]
        with self.assertRaises(ValueError):
            fit_forecast(snapshot, fitting, changed, contract, steps=2, batch_size=8)
        changed = deepcopy(calibration)
        changed.evidence["snapshot_sha256"] = "e" * 64
        with self.assertRaises(ValueError):
            fit_forecast(snapshot, fitting, changed, contract, steps=2, batch_size=8)


if __name__ == "__main__":
    unittest.main()
