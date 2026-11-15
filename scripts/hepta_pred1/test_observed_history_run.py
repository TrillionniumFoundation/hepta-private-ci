"""Whole offline history pipeline tests; these runs contain only fixture data."""

from hashlib import sha256
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from .native_ledger import Artifact
from .observed_history_run import run_history_study
from .test_observed_history import fixture_history_study


class ObservedHistoryRunTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def test_three_models_replay_from_retained_sources_without_backdated_choices(self):
        manifest = fixture_history_study(self.root / "inputs")
        originals = {p.name: p.read_bytes() for p in manifest.parent.glob("history-decision-*.json")}
        output = self.root / "run"
        report = run_history_study(manifest, output).payload
        self.assertEqual((report["train_samples"], report["dev_samples"]), (12, 6))
        self.assertEqual(set(report["models"]), {"empirical", "mlp", "gru"})
        self.assertEqual(report["new_policy_adoption"], "NoUpdate")
        self.assertEqual(report["new_policy_real_task_comparisons"], 0)
        self.assertEqual(report["original_policy_eligibility"]["decision"], "NoUpdate")
        self.assertEqual(originals, {p.name: p.read_bytes() for p in manifest.parent.glob("history-decision-*.json")})
        for kind, model in report["models"].items():
            self.assertEqual(model["metadata"]["training"]["source_counts"], {"fixture": 12})
            self.assertEqual(model["metadata"]["optimizer_calls"], 0 if kind == "empirical" else 3)
            self.assertEqual(len(model["holdout_artifacts"]), 6)
            forecast = Artifact.read(output / f"{kind}-dev-0000.json").payload
            self.assertFalse(forecast["prediction_deployed"])
            self.assertNotIn("decision_at", forecast)
            self.assertIsNone(forecast["counterfactual_policy_value"])
        receipt = Artifact.read(output / "COMPLETED.json").payload
        for item in receipt["artifacts"]:
            self.assertEqual(sha256((output / item["path"]).read_bytes()).hexdigest(), item["sha256"])
        # A fresh process imports only the retained source closure, not this checkout.
        replay = self.root / "replay"
        env = {**os.environ, "PYTHONPATH": str(output / "source")}
        done = subprocess.run([sys.executable, "-m", "hepta_pred1.observed_history_run",
                               "--manifest", str(output / "REPLAY_INPUT.json"), "--output", str(replay)],
                              cwd=self.root, env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        for kind in report["models"]:
            for index in range(6):
                name = f"{kind}-dev-{index:04d}.json"
                self.assertEqual(Artifact.read(output / name).payload["prediction"],
                                 Artifact.read(replay / name).payload["prediction"])
        with self.assertRaises(FileExistsError):
            run_history_study(manifest, output)

    def test_failed_gru_readback_keeps_prior_work_and_terminal_cost_receipt(self):
        manifest = fixture_history_study(self.root / "inputs")
        with patch(__package__ + ".observed_history_run.ObservedGRU.load", side_effect=ValueError("fixture restore failure")):
            with self.assertRaisesRegex(ValueError, "fixture restore"):
                run_history_study(manifest, self.root / "failed")
        receipt = Artifact.read(self.root / "failed/FAILED.json").payload
        self.assertEqual(receipt["stage"], "gru_checkpoint_readback")
        self.assertTrue((self.root / "failed/mlp-calibration.json").is_file())
        self.assertTrue((self.root / "failed/gru.json").is_file())
        self.assertGreater(receipt["wall_seconds"], 0)
        self.assertFalse((self.root / "failed/COMPLETED.json").exists())

    def test_missing_action_support_keeps_all_six_holdout_records(self):
        manifest = fixture_history_study(self.root / "inputs", train_actions=("a",))
        run_history_study(manifest, self.root / "run")
        for kind in ("empirical", "mlp", "gru"):
            summary = Artifact.read(self.root / f"run/{kind}-calibration.json").payload["overall"]
            self.assertEqual(summary["unsupported_predictions"], 3)
            self.assertEqual(summary["metrics"]["quality_brier"]["count"], 6)
            self.assertEqual(summary["metrics"]["quality_brier"]["eligible"], 3)

    def test_confirmations_panel_drift_and_missing_originals_are_refused(self):
        manifest = fixture_history_study(self.root / "inputs")
        original = Artifact.read(manifest)
        for case in ("confirm", "panel", "snapshot"):
            payload = original.payload
            if case == "confirm":
                payload["confirm"] = [{"path": "DO_NOT_OPEN", "sha256": "0" * 64}]
            elif case == "panel":
                payload["action_ids"].reverse()
            else:
                payload["train"][0]["snapshot"]["sha256"] = "0" * 64
            path = manifest.parent / (case + ".json")
            Artifact.make(payload).save(path)
            with self.subTest(case=case), self.assertRaises(ValueError):
                run_history_study(path, self.root / case)
            failure = Artifact.read(self.root / case / "FAILED.json").payload
            self.assertEqual(failure["stage"], "input_validation")
            self.assertEqual((self.root / case / "INPUT.raw").read_bytes(), path.read_bytes())
            self.assertTrue((self.root / case / "source/hepta_pred1/observed_gru.py").is_file())

    def test_source_identity_drift_is_retained_as_failed_work(self):
        from .observed_models import fit_observed_model

        manifest = fixture_history_study(self.root / "inputs")
        def mismatched_source(*args, **kwargs):
            model = fit_observed_model(*args, **kwargs)
            model.metadata["source_sha256"] = "0" * 64
            return model
        with patch(__package__ + ".observed_history_run.fit_observed_model", side_effect=mismatched_source):
            with self.assertRaisesRegex(ValueError, "retained source"):
                run_history_study(manifest, self.root / "source-drift")
        receipt = Artifact.read(self.root / "source-drift/FAILED.json").payload
        self.assertEqual(receipt["stage"], "empirical_fit")
        self.assertGreater(len(receipt["artifacts"]), 14)

    def test_same_native_attempt_cannot_cross_splits_under_new_decision_and_group(self):
        from .observed_evaluation import UtilityContract
        from .owner_bridge import freeze_owner_decision, join_owner_effect

        manifest = fixture_history_study(self.root / "inputs")
        for case, error in (("attempt", "native owner attempt reused"),
                            ("run", "native owner run crosses train/dev")):
            with self.subTest(case=case):
                root, payload = manifest.parent, Artifact.read(manifest).payload
                train, dev = payload["train"][0], payload["dev"][0]
                train_snapshot = Artifact.read(root / train["snapshot"]["path"])
                original_decision = Artifact.read(root / dev["decision"]["path"])
                original_sample = Artifact.read(root / dev["sample"]["path"])
                snapshot_payload = Artifact.read(root / dev["snapshot"]["path"]).payload
                identity = train_snapshot.payload["identity"]
                if case == "run":
                    identity["step_id"] = "another-step"
                snapshot_payload["identity"] = identity
                snapshot_payload["collection"]["identity"] = identity
                snapshot_payload["collection_digest"] = Artifact.make(snapshot_payload["collection"]).digest
                snapshot = Artifact.make(snapshot_payload)
                snapshot_path = root / f"repeated-native-{case}-snapshot.json"
                snapshot.save(snapshot_path)
                decision_path = root / f"repeated-native-{case}-decision.json"
                d, observed = original_decision.payload, original_sample.payload["observed"]
                decision = freeze_owner_decision(
                    decision_path, snapshot_path,
                    predictions={action: d["predictions"][action] for action in d["action_order"]},
                    chosen_action=d["chosen_action"], policy_id=d["policy_id"], model_sha256=d["model_sha256"],
                    task_group=d["task_group"], split=d["split"], information_set_digest=d["information_set_digest"],
                    contract=UtilityContract(**d["utility_contract"]), prediction_at=d["prediction_at"],
                    decision_at=d["decision_at"], success_definition=d["success_definition"], source="fixture",
                )
                collection = snapshot_payload["collection"]
                collection.update(cursor=collection["cursor"] + 1, available_at=40.)
                collection["rows"]["attempts"] = [{**identity, "authority_epoch": 1,
                    "grant_id": "fixture-grant", "grant_nonce_digest": "8" * 64,
                    "record_command_id": "command", "started_at_ms": 1}]
                effect = Artifact.make({
                    "schema": "pred1-independent-effect-v1", "target_domain": "independent_task_effect",
                    "target_schema_sha256": d["target_schema_sha256"], "decision_digest": decision.digest,
                    "snapshot_digest": snapshot.digest, "identity": identity, "clock_id": d["clock_id"],
                    "chosen_action": d["chosen_action"], "executed_action": d["chosen_action"],
                    "executed_at": 14., "execution_ref": observed["execution_ref"],
                    "observer_ref": "fixture-observer", "evidence": observed["evidence"],
                    "costs": observed["costs"], "full_wall_seconds": observed["full_wall_seconds"],
                    "source": "fixture",
                })
                sample_path = root / f"repeated-native-{case}-sample.json"
                sample = join_owner_effect(sample_path, decision_path, Artifact.make(collection), effect)
                for kind, path, artifact in (("sample", sample_path, sample),
                                             ("decision", decision_path, decision),
                                             ("snapshot", snapshot_path, snapshot)):
                    dev[kind] = {"path": path.name, "sha256": artifact.digest}
                self.assertNotEqual(decision.digest, Artifact.read(root / train["decision"]["path"]).digest)
                self.assertNotEqual(d["task_group"], Artifact.read(root / train["decision"]["path"]).payload["task_group"])
                duplicate_manifest = root / f"REPEATED_NATIVE_{case}_MANIFEST.json"
                Artifact.make(payload).save(duplicate_manifest)
                with self.assertRaisesRegex(ValueError, error):
                    run_history_study(duplicate_manifest, self.root / f"repeated-native-{case}")
                failure = Artifact.read(self.root / f"repeated-native-{case}/FAILED.json").payload
                self.assertEqual(failure["stage"], "input_validation")


if __name__ == "__main__":
    unittest.main()
