"""Original unchanged-weight results cannot acquire another learning role."""

import importlib.util
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "training_no_update_caller_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
AGENT = "codex-rs/hepta-agentd/src/"
READBACK = AGENT + "cell_composed_q24_training_observation.rs"


class TrainingNoUpdateSourceClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())

    def rejects(self, path, marker, replacement=""):
        original = (ROOT / path).read_text()
        self.assertIn(marker, original)
        rows = [row for row in self.manifest["protected_file"] if row["path"] == path]
        self.assertTrue(rows)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(original)
            PROOF._verify_protected_files(root, {"protected_file": rows})
            target.write_text(original.replace(marker, replacement, 1))
            with self.assertRaises(PROOF.VerificationFailure):
                PROOF._verify_protected_files(root, {"protected_file": rows})

    def test_readback_boundary_does_not_grant_a_product_caller(self):
        rows = {row.identifier: row for row in PROOF._boundary_rows(self.manifest)}
        row = rows["cell_q24_original_training_observation"]
        self.assertIn(row.identifier, self.manifest["privileged_inventory"]["required_boundary_ids"])
        self.assertEqual(row.product_callers, ())
        sources = {READBACK: PROOF._strip_rust_non_code((ROOT / READBACK).read_text())}
        PROOF._verify_boundary(ROOT, row, sources, ())
        sources[AGENT + "unregistered_training_result.rs"] = (
            "fn unexpected(owner: &CellQ24TrainingOwnerV1) { owner.read_learning_observation(); }"
        )
        with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
            PROOF._verify_boundary(ROOT, row, sources, ())

    def test_readback_requires_original_completed_bytes_scope_and_current_witness(self):
        for marker in (
            "self.require_current()?;", "if original_dataset_cut != &self.plan.prefix",
            "self.journal.readback(&self.key)?", "return Err(Error::Pending)",
            "self.decode(&payload)?", "self.plan\n            .scope\n            .validate_observation(&observation)",
            "self.plan.scope.binding()", "self.key.binding_digest.as_array(),\n                &payload",
        ):
            with self.subTest(marker=marker):
                self.rejects(READBACK, marker)
        self.rejects(READBACK, "if original_dataset_cut != &self.plan.prefix",
            "if false && original_dataset_cut != &self.plan.prefix")
        for forbidden in ("self.plan.fit();", "self.journal.claim();", "self.journal.complete();",
            "SystemTime::now();", "key.sign();"):
            with self.subTest(forbidden=forbidden):
                self.rejects(READBACK, "let payload = match", forbidden + " let payload = match")

    def test_no_update_keeps_frozen_rule_and_generator_selector_separation(self):
        for path, marker in (
            ("codex-rs/hepta-learning-artifacts/src/learning_iteration_scope.rs",
                "outcome.update_rule != self.update_rule"),
            (AGENT + "learning_iteration_auth.rs",
                "LearningIterationStageV1::Selection if snapshot.training_no_update_v2().is_some()"),
            (AGENT + "learning_iteration_auth.rs",
                "LearningIterationStageV1::Training => LearningEvidenceRoleV1::Generator"),
            (AGENT + "learning_iteration_auth.rs",
                "verify_signed_actor_separation(&prior, &current, clock()?)"),
            (AGENT + "learning_iteration.rs", "else if restored.snapshot().requires_scoped_owner_v2()"),
            ("codex-rs/hepta-learning-artifacts/src/learning_iteration_types.rs",
                "self.training_no_update_v2().is_some() || self.local_decision_v2().is_some()"),
        ):
            with self.subTest(path=path, marker=marker):
                self.rejects(path, marker)

    def test_local_choice_requires_its_own_bound_policy_and_current_selector_evidence(self):
        artifacts = "codex-rs/hepta-learning-artifacts/src/"
        for path, markers in (
            (artifacts + "learning_iteration.rs", (
                "decision.proposal_head == self.snapshot.head_digest",
                "candidate_digest == Some(decision.candidate_bundle)",
                "!decision.policy_digest.is_zero()",
                "!decision.reason_digest.is_zero()",
                "decision.selected_bundle == request.selected_bundle.digest()?",
                "candidate_digest == Some(decision.selected_bundle)",
            )),
            (artifacts + "learning_iteration_digest.rs", (
                "hepta.learning.iteration-local-decision.v2",
                "hepta.learning.iteration-observation.v1",
            )),
            (AGENT + "learning_iteration_auth.rs", (
                "verify_receipt(ports, verifier, snapshot, decision, clock).await?",
            )),
            (AGENT + "learning_iteration.rs", (
                "if let Some(decision)",
                "decision,",
                "&receipt,",
            )),
            (AGENT + "learning_iteration_checkpoint_codec.rs", (
                "9 if local_decision =>",
                "snapshot.local_decision_v2().is_some() != local_decision",
            )),
        ):
            for marker in markers:
                with self.subTest(path=path, marker=marker):
                    self.rejects(path, marker)


if __name__ == "__main__":
    unittest.main()
