"""Small explicit development fixtures for immutable training and its audit."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from .. import deployment
from ..ledger import sha
from . import audit, runner


class TrainingEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        protocol = json.loads(runner.PROTOCOL_PATH.read_text())
        protocol["screening_seeds"], protocol["confirmation_seeds"] = [910101], [910103]
        protocol["training"].update(outer_steps=2, support_episodes=4, query_episodes=4)
        protocol["audit"]["hypergradient_probe_episodes"] = 3
        self.protocol_path = self.root / "PROTOCOL.json"
        self.protocol_path.write_text(json.dumps(protocol))
        self.seal = self.root / "DEVELOPMENT_SEAL.json"
        self.seal.write_text('{"development_fixture": true}\n')
        # This substitutes provenance only for a tiny test fixture. Scientific
        # entry points always call the genuine verifier without this patch.
        verification = {"development_fixture": True, "seal_sha256": sha(self.seal)}
        patches = [
            patch.object(runner, "PROTOCOL_PATH", self.protocol_path),
            patch.object(audit, "PROTOCOL_PATH", self.protocol_path),
            patch.object(runner, "verify", return_value=verification),
            patch.object(audit, "verify", return_value=verification),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def execute(self, name="run"):
        destination = self.root / name
        runner.run_phase("screening", destination, self.seal)
        return destination

    def republish_fixture_hashes(self, root, record):
        """Model an attacker changing receipts as well as their container hashes."""
        directory = root / record["directory"]
        path = directory / "COMPLETE.json"
        complete = json.loads(path.read_text())
        complete["files"] = {name: sha(directory / name) for name in complete["files"]}
        path.write_text(json.dumps(complete))
        record["complete_sha256"] = sha(path)

    def test_complete_models_and_optimizer_history_pass_independent_audit(self):
        root = self.execute()
        before = {str(path): sha(path) for path in root.rglob("*.json")}
        result = audit.audit_phase(root, self.seal, self.root / "AUDIT.json")
        self.assertEqual(result["fits_verified"], 3)
        self.assertTrue(result["passed"])
        self.assertEqual(result["training_index_sha256"], sha(root / "INDEX.json"))
        self.assertTrue(result["raw_files_unchanged"])
        self.assertEqual(len(result["hypergradient_checks"]), 1)
        self.assertEqual(len(result["hypergradient_checks"][0]["checks"]), 3)
        self.assertEqual(
            before, {str(path): sha(path) for path in root.rglob("*.json")}
        )
        with self.assertRaises(FileExistsError):
            runner.run_phase("screening", root, self.seal)

    def test_rehashed_summary_tampering_is_not_accepted(self):
        root = self.execute()
        index_path = root / "INDEX.json"
        index = json.loads(index_path.read_text())
        record = index["fits"][0]
        training_path = root / record["directory"] / "TRAINING.json"
        training = json.loads(training_path.read_text())
        training["actual_neural_cell_updates"] += 8
        training_path.write_text(json.dumps(training))
        self.republish_fixture_hashes(root, record)
        index_path.write_text(json.dumps(index))
        with self.assertRaisesRegex(ValueError, "training summary"):
            audit.audit_phase(root, self.seal, self.root / "AUDIT.json")

    def test_deployment_requires_audit_of_exact_confirmation_checkpoints(self):
        root = self.root / "confirmation"
        runner.run_phase("confirmation", root, self.seal)
        audit_path = self.root / "CONFIRMATION_AUDIT.json"
        result = audit.audit_phase(root, self.seal, audit_path)
        config = json.loads(self.protocol_path.read_text())
        expected = [
            {"seed": seed, "training_arm": arm}
            for seed in config["confirmation_seeds"]
            for arm in config["training"]["arms"]
        ]
        with patch.object(deployment, "protocol", return_value=config):
            models = deployment.fitted_inputs(
                root, expected, result["source"], audit_path
            )
            self.assertEqual(
                list(models),
                [(row["seed"], row["training_arm"]) for row in expected],
            )
            for label, message in (
                ("index", "exact training index"),
                ("checkpoint", "another checkpoint"),
            ):
                changed = json.loads(audit_path.read_text())
                if label == "index":
                    changed["training_index_sha256"] = "0" * 64
                else:
                    changed["fit_records"][-1]["checkpoint_sha256"] = "0" * 64
                altered = self.root / f"ALTERED_{label}.json"
                altered.write_text(json.dumps(changed))
                with (
                    self.subTest(identity=label),
                    self.assertRaisesRegex(ValueError, message),
                ):
                    deployment.fitted_inputs(root, expected, result["source"], altered)

    def test_rehashed_optimizer_history_tampering_is_not_accepted(self):
        root = self.execute()
        index_path = root / "INDEX.json"
        index = json.loads(index_path.read_text())
        record = index["fits"][-1]
        path = root / record["directory"] / "history/steps_0001_0002.json"
        history = json.loads(path.read_text())
        history["rows"][0]["outer_first_moment"][0] += 0.01
        path.write_text(json.dumps(history))
        self.republish_fixture_hashes(root, record)
        index_path.write_text(json.dumps(index))
        with self.assertRaisesRegex(AssertionError, "outer optimizer field"):
            audit.audit_phase(root, self.seal, self.root / "AUDIT.json")

    def test_missing_and_duplicate_fit_rosters_fail(self):
        root = self.execute()
        index_path = root / "INDEX.json"
        original = json.loads(index_path.read_text())
        for changed in (original["fits"][:-1], [original["fits"][0]] * 3):
            index = dict(original, fits=changed)
            index_path.write_text(json.dumps(index))
            with self.assertRaisesRegex(ValueError, "fit roster"):
                audit.audit_phase(root, self.seal, self.root / "AUDIT.json")

    def test_late_write_failure_preserves_actual_checkpoint_and_invalid_attempt(self):
        destination = self.root / "failed"
        original = runner.write_json_exclusive

        def fail_summary(path, value):
            if Path(path).name == "TRAINING.json":
                raise OSError("injected late artifact failure")
            return original(path, value)

        with patch.object(runner, "write_json_exclusive", side_effect=fail_summary):
            with self.assertRaisesRegex(OSError, "injected late"):
                runner.run_phase("screening", destination, self.seal)
        partial = destination / "seed_910101/standard"
        self.assertTrue((partial / "progress/step_0002.json").is_file())
        self.assertTrue((partial / "checkpoint.json").is_file())
        self.assertTrue((partial / "neural.json").is_file())
        self.assertFalse((partial / "COMPLETE.json").exists())
        invalid = json.loads((destination / "INVALID_ATTEMPT.json").read_text())
        self.assertEqual(invalid["progress"]["last_completed_step"], 2)
        self.assertEqual(invalid["completed_fits"], [])


if __name__ == "__main__":
    unittest.main()
