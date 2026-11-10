"""Integration tests; every generated owner, task and effect is a fixture."""

from dataclasses import asdict
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from .action_history import encode
from .contracts import Evidence
from .native_ledger import Artifact, IDENTITY_FIELDS, freeze_snapshot
from .observed_evaluation import COST_FIELDS, UtilityContract
from .observed_models import fit_observed_model
from .observed_run import run_observed
from .owner_bridge import freeze_owner_decision, join_owner_effect, owner_information_digest


def fixture_study(root, *, train_actions=("a", "b"), epochs=8):
    """Build a small engineering dataset through the real join APIs, not live owners."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    contract = UtilityContract("fixture-resource", .01, .1, max_wall_seconds=100., max_total_cost=100.)
    prediction = dict(success_probability=.5, duration_values=[.01, .04], duration_probabilities=[.5, .5],
                      cost_values=[.002, .008], cost_probabilities=[.5, .5])
    entries = {"train": [], "dev": []}
    for index in range(18):
        split = "train" if index < 12 else "dev"
        action = train_actions[index % len(train_actions)] if split == "train" else ("a", "b")[index % 2]
        identity = dict(zip(IDENTITY_FIELDS, ("fixture-owner", f"run-{index}", "step", 1,
                         "1" * 64, "2" * 64, "3" * 64, "fixture-destination")))
        collection = Artifact.make({"schema": "pred1-native-collection-v1", "identity": identity,
                                   "clock_id": "fixture-clock", "cursor": 0, "available_at": 10.,
                                   "rows": {"attempts": [], "observations": [], "reconciliations": []},
                                   "database_path": "synthetic", "scope": "fixture"})
        history = encode([], actions=("a", "b"), decision_at=11., through_sequence=0,
                         remaining_budget=float(index + 1), deadline_at=100.)
        snapshot_path = root / f"snapshot-{index}.json"
        snapshot = freeze_snapshot(snapshot_path, history, collection)
        panel = {"b": prediction, "a": prediction}
        decision_path = root / f"decision-{index}.json"
        decision = freeze_owner_decision(
            decision_path, snapshot_path, predictions=panel, chosen_action=action,
            policy_id="fixture-parent", model_sha256="7" * 64, task_group=f"fixture-group-{index}", split=split,
            information_set_digest=owner_information_digest(snapshot, list(panel), contract, "fixture parity outcome"),
            contract=contract, prediction_at=12., decision_at=13., success_definition="fixture parity outcome",
            source="fixture",
        )
        later = collection.payload
        later.update(cursor=1, available_at=40.)
        later["rows"]["attempts"] = [{**identity, "authority_epoch": 1, "grant_id": "fixture-grant",
                                      "grant_nonce_digest": "8" * 64, "record_command_id": "command", "started_at_ms": 1}]
        cost, duration = .002 * (1 + index % 3), .013 + .007 * (index % 3)
        costs = dict.fromkeys(COST_FIELDS, 0.)
        costs["action"] = cost
        effect = Artifact.make({
            "schema": "pred1-independent-effect-v1", "target_domain": "independent_task_effect",
            "target_schema_sha256": decision.payload["target_schema_sha256"],
            "decision_digest": decision.digest, "snapshot_digest": snapshot.digest, "identity": identity,
            "clock_id": "fixture-clock", "chosen_action": action, "executed_action": action,
            "executed_at": 14., "execution_ref": f"fixture-execution-{index}", "observer_ref": "fixture-observer",
            "evidence": asdict(Evidence(observation_status="terminal", outcome=index % 2, time_kind="exact",
                                       time_lower=duration, observed_at=40., final_cost=cost, receipt_ref=f"fixture-receipt-{index}")),
            "costs": costs, "full_wall_seconds": 30., "source": "fixture",
        })
        sample_path = root / f"sample-{index}.json"
        sample = join_owner_effect(sample_path, decision_path, Artifact.make(later), effect)
        entries[split].append({"path": sample_path.name, "sha256": sample.digest})
    manifest = Artifact.make({
        "schema": "pred1-observed-study-input-v1", **entries,
        "feature_names": list(history.feature_names), "action_ids": ["a", "b"],
        "success_definition": "fixture parity outcome", "utility_contract": asdict(contract),
        "seed": 77, "hidden_size": 4, "epochs": epochs, "learning_rate": .01,
    })
    path = root / "MANIFEST.json"
    manifest.save(path)
    return path


class ObservedRunTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def test_cli_pipeline_has_bound_checkpoints_and_no_backdated_decisions(self):
        manifest = fixture_study(self.root / "inputs")
        original = (manifest.parent / "decision-12.json").read_bytes()
        output = self.root / "run"
        done = subprocess.run([sys.executable, "-m", "scripts.hepta_pred1.observed_run",
                               "--manifest", str(manifest), "--output", str(output)],
                              cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        report = Artifact.read(output / "REPORT.json").payload
        self.assertEqual((report["train_samples"], report["dev_samples"]), (12, 6))
        self.assertEqual(report["models"]["mlp"]["optimizer_calls"], 8)
        self.assertEqual(report["models"]["mlp"]["sample_presentations"], 96)
        self.assertEqual(report["adoption"]["decision"], "NoUpdate")
        self.assertFalse(report["confirmation_data_opened"])
        self.assertEqual(original, (manifest.parent / "decision-12.json").read_bytes())
        self.assertEqual(Artifact.read(output / "COMPLETED.json").payload["state"], "COMPLETED")
        forecast = Artifact.read(output / "mlp-dev-0000.json").payload
        self.assertFalse(forecast["prediction_deployed"])
        self.assertNotIn("decision_at", forecast)
        self.assertIsNone(forecast["counterfactual_policy_value"])
        self.assertEqual(Artifact.read(manifest.parent / "decision-12.json").payload["action_order"], ["b", "a"])
        with self.assertRaises(FileExistsError):
            run_observed(manifest, output)

    def test_failed_fit_preserves_partial_model_and_terminal_cost_receipt(self):
        manifest = fixture_study(self.root / "inputs")
        def fail_mlp(*args, **kwargs):
            if kwargs["kind"] == "mlp":
                raise RuntimeError("fixture interrupted fit")
            return fit_observed_model(*args, **kwargs)
        with patch(__package__ + ".observed_run.fit_observed_model", side_effect=fail_mlp):
            with self.assertRaises(RuntimeError):
                run_observed(manifest, self.root / "failed")
        receipt = Artifact.read(self.root / "failed/FAILED.json").payload
        self.assertEqual(receipt["stage"], "mlp_fit")
        self.assertEqual(receipt["state"], "FAILED")
        self.assertTrue((self.root / "failed/empirical.json").exists())
        self.assertGreater(receipt["wall_seconds"], 0)
        self.assertFalse((self.root / "failed/COMPLETED.json").exists())

    def test_confirmation_entries_are_refused_before_opening_them(self):
        manifest = fixture_study(self.root / "inputs")
        payload = Artifact.read(manifest).payload
        payload["confirm"] = [{"path": "must-remain-unopened.json", "sha256": "f" * 64}]
        sealed = manifest.parent / "with-confirm.json"
        Artifact.make(payload).save(sealed)
        with self.assertRaisesRegex(ValueError, "manifest fields differ"):
            run_observed(sealed, self.root / "rejected")
        self.assertEqual(Artifact.read(self.root / "rejected/FAILED.json").payload["stage"], "input_validation")

    def test_unsupported_holdout_action_stays_in_denominator(self):
        manifest = fixture_study(self.root / "inputs", train_actions=("a",))
        report = run_observed(manifest, self.root / "run").payload
        for model in report["models"].values():
            self.assertEqual(model["unsupported_holdout_actions"], 3)
            self.assertEqual(len(model["holdout_artifacts"]), 6)
            self.assertEqual(model["holdout_scores"]["quality_brier"]["observed_count"], 3)


if __name__ == "__main__":
    unittest.main()
