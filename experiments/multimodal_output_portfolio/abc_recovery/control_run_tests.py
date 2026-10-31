"""Integrated finite actual-output training, freeze, deployment and dual scoring."""

import io
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import torch

from ..v6.data import SourceCorpus, SourceSplit
from ..v6.observer import Recognizer
from ..v7.model import SlotPortfolio
from ..v7.snapshot import Snapshot
from .control_run import evaluate_model, fit_model, load_bundle, validate_snapshot


class ControlRunTests(unittest.TestCase):
    def test_parameter_identity_does_not_substitute_for_training_recipe_identity(self):
        protocol = json.loads(Path(__file__).with_name("protocol.json").read_text())
        canonical = json.dumps(dict(protocol, primary_observer_parameter_sha256="primary"),
                               sort_keys=True, separators=(",", ":")).encode()
        metadata = {"profile": "output_ndu", "seed": 17, "source_manifest_sha256": "sources",
                    "protocol_canonical_sha256": hashlib.sha256(canonical).hexdigest(),
                    "actual_output_score_used_in_optimizer": True, "risk_aversion": 2.,
                    "native_auxiliary_weight": .05}
        snapshot = Snapshot(SlotPortfolio(), metadata)
        row = {"arm": "output_ndu", "seed": 17, "snapshot_sha256": snapshot.fingerprint}
        validate_snapshot(snapshot, row, protocol, "sources", "primary")
        for key, wrong in (("profile", "output_mean"), ("seed", 29), ("risk_aversion", 0.),
                           ("native_auxiliary_weight", 1.), ("source_manifest_sha256", "other")):
            changed = Snapshot(snapshot._model, dict(metadata, **{key: wrong}))
            self.assertEqual(changed.fingerprint, snapshot.fingerprint)
            with self.assertRaises(ValueError):
                validate_snapshot(changed, row, protocol, "sources", "primary")

    def test_complete_small_synthetic_pipeline_never_uses_evaluation_for_fit(self):
        torch.set_num_threads(2)
        with torch.random.fork_rng():
            torch.manual_seed(88)
            snapshot = Snapshot(SlotPortfolio())
            observers = {name: Recognizer().eval().requires_grad_(False) for name in ("primary", "secondary")}
        generator = torch.Generator().manual_seed(11)
        splits = {}
        for role in ("development", "forecast_fit", "forecast_calibration"):
            count = 1800
            ids = tuple(f"synthetic:{role}:{i}" for i in range(count))
            splits[role] = SourceSplit(torch.randint(256, (count, 1, 28, 28), dtype=torch.uint8, generator=generator),
                                       torch.randint(10, (count,), generator=generator), ids, ids)
        corpus = SourceCorpus(splits, {"manifest_sha256": "synthetic-only"})
        protocol = json.loads(Path(__file__).with_name("protocol.json").read_text())
        for name in ("critic_fit", "critic_calibration", "static_tuning", "evaluation"):
            protocol["roles"][name]["pair_count"] = 1
        protocol["tuning_generation_scenarios"] = 2
        protocol["evaluation_generation_scenarios"] = 2
        protocol["critic"].update({"steps_per_horizon": 2, "hidden_dim": 8, "batch_size": 64})
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "model"
            frozen = fit_model(snapshot, corpus, observers["primary"], destination, protocol, 17, "output_ndu")
            self.assertTrue(frozen["policy_freeze_sha256"])
            freeze_record = json.loads((destination / "policies/policy-freeze.json").read_text())
            self.assertFalse(freeze_record["task_evaluation_opened"])
            self.assertFalse((destination / "evaluation").exists())
            bundle = load_bundle(destination / "policies")
            output = io.StringIO()
            report = evaluate_model(snapshot, corpus, observers, destination, bundle, protocol, 17, "output_ndu", output)
            rows = [json.loads(line) for line in output.getvalue().splitlines()]
            self.assertEqual(len(rows), 14 * 16)
            self.assertEqual(report["policy_replay_rows"], len(rows))
            self.assertEqual(len({row["policy"] for row in rows}), 14)
            self.assertEqual(len({tuple(row["source_ids"]) for row in rows}), 1)
            self.assertTrue(all(set(row["observers"]) == {"primary", "secondary"} for row in rows))
            self.assertTrue(all(row["case"] == 608 for row in rows))
            self.assertEqual(freeze_record, json.loads((destination / "policies/policy-freeze.json").read_text()))


if __name__ == "__main__":
    unittest.main()
