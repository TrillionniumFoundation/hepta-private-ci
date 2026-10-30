"""Real tensor candidates: strict identity checks and new-episode migration.

Native execution is exercised by the deployment workflow, never a fake owner.
"""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import torch

from experiments.multimodal_output_portfolio.joint_hepta_20261029.checkpoint import generation_metadata, save_checkpoint
from experiments.multimodal_output_portfolio.joint_hepta_20261029.deployment import cost_accounting, load_candidate
from experiments.multimodal_output_portfolio.joint_hepta_20261029.mechanism_data import batch
from experiments.multimodal_output_portfolio.joint_hepta_20261029.model import JointGenerator, tensor_digest
from experiments.multimodal_output_portfolio.joint_hepta_20261029.runtime import make_profile


class CandidateDeploymentTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        torch.manual_seed(571)
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "MODEL.pt"
        self.manifest = self.path.with_suffix(".pt.manifest.json")
        self.model = JointGenerator(width=4).eval()
        self.public, _ = batch([5])
        self.profile = make_profile()
        with torch.no_grad():
            state = self.model.encode(self.public)
            state, _ = self.model.advance(state, "shared", self.public)
        self.identity = save_checkpoint(self.path, self.model, state,
            torch.Generator().manual_seed(771), self.profile, self.public,
            metadata=generation_metadata(self.model, self.public, self.profile,
                                         arm="hepta_dynamic_risk", study_seed=17))

    def rewrite_payload(self, payload):
        """Refresh outer hashes to exercise semantic source checks, not bytes."""
        torch.save(payload, self.path)
        manifest = json.loads(self.manifest.read_text())
        manifest.update(payload_sha256=tensor_digest(payload), file_bytes=self.path.stat().st_size,
                        file_sha256=hashlib.sha256(self.path.read_bytes()).hexdigest())
        self.manifest.write_text(json.dumps(manifest))

    def test_valid_weights_start_fresh_without_installing_saved_global_rng(self):
        torch.manual_seed(872)
        before = torch.get_rng_state().clone()
        model, lineage = load_candidate(self.path, expected_model_sha256=self.identity["model_sha256"],
                                        expected_arm="hepta_dynamic_risk")
        self.assertTrue(torch.equal(before, torch.get_rng_state()))
        self.assertEqual(tensor_digest(model.state_dict()), self.identity["model_sha256"])
        self.assertEqual(model.encode(self.public).steps, 0)
        self.assertFalse(lineage["old_trajectory_restored"])
        self.assertFalse(any(parameter.requires_grad for parameter in model.parameters()))
        self.assertFalse(model.training)

    def test_missing_manifest_is_rejected(self):
        self.manifest.unlink()
        with self.assertRaisesRegex(ValueError, "manifest"):
            load_candidate(self.path)

    def test_wrong_external_model_identity_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "model identity"):
            load_candidate(self.path, expected_model_sha256="0" * 64)

    def test_wrong_internal_model_manifest_is_rejected(self):
        manifest = json.loads(self.manifest.read_text())
        manifest["model_sha256"] = "0" * 64
        self.manifest.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "identities"):
            load_candidate(self.path)

    def test_wrong_model_source_is_rejected_even_with_consistent_payload_hash(self):
        payload = torch.load(self.path, weights_only=True, map_location="cpu")
        payload["source_sha256"]["joint_hepta_20261029/model.py"] = "0" * 64
        self.rewrite_payload(payload)
        with self.assertRaisesRegex(ValueError, "source code"):
            load_candidate(self.path)

    def test_new_runtime_source_migration_keeps_old_lineage_but_not_old_episode(self):
        payload = torch.load(self.path, weights_only=True, map_location="cpu")
        name = "joint_hepta_20261029/runtime.py"
        payload["source_sha256"][name] = "0" * 64
        self.rewrite_payload(payload)
        model, lineage = load_candidate(self.path, expected_model_sha256=self.identity["model_sha256"])
        self.assertEqual(lineage["source_changes_for_new_episode"][name]["old"], "0" * 64)
        self.assertEqual(lineage["old_profile"], self.profile.to_dict())
        self.assertFalse(lineage["old_rng_and_physical_clocks_restored"])
        self.assertEqual(tensor_digest(model.state_dict()), self.identity["model_sha256"])


class DeploymentCostTests(unittest.TestCase):
    def test_a_more_expensive_student_has_no_cost_break_even(self):
        cost = cost_accounting({"wall": 50.0, "cpu": 60.0},
            {"teacher": {"wall": .5, "cpu": .8}, "student": {"wall": .5, "cpu": .8}},
            {"mean_cost": .02, "population_ce": .8}, {"mean_cost": .021, "population_ce": .78})
        self.assertIsNone(cost["cost_only_break_even_episodes"])
        self.assertLess(cost["observed_teacher_minus_student_serving_cost"], 0)
        self.assertLess(cost["student_primary_ce_change"], 0)
        self.assertFalse(cost["quality_noninferiority_established"])


if __name__ == "__main__":
    unittest.main()
