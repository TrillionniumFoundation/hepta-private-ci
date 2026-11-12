"""Root consumes either concrete original bundle; no open owner callback.

The Candidate branch still refuses absent independent B/Outcome/Model rights.
An actual T checkpoint precedes its Candidate-material Evaluation dispatch.
"""
import importlib.util
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "resident_candidate_stage_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
AGENT = "codex-rs/hepta-agentd/src/"
FACTORY = AGENT + "authority_host_learning_resident.rs"
STAGES = AGENT + "authority_host_learning_resident_stages.rs"
RUNTIME = AGENT + "authority_host_learning_resident_runtime.rs"
AUTH = AGENT + "authority_host_learning_resident_auth.rs"
CANDIDATE = AGENT + "cell_q24_candidate_stage_owners.rs"
EXPECTED = {
    "learning_original_no_update_stage_initial": ("codex-rs/hepta-agentd/src/authority_host_learning_resident_stages.rs", "codex-rs/hepta-agentd/src/cell_q24_candidate_stage_owners.rs",),
    "learning_original_no_update_stage_resident_gate": ("codex-rs/hepta-agentd/src/authority_host_learning_resident_stages.rs", "codex-rs/hepta-agentd/src/cell_q24_candidate_stage_owners.rs",),
    "learning_original_candidate_stage_initial": ("codex-rs/hepta-agentd/src/authority_host_learning_resident_stages.rs",),
    "learning_original_candidate_stage_resident_gate": ("codex-rs/hepta-agentd/src/authority_host_learning_resident_stages.rs",),
    "root_resident_candidate_runtime_consume": (),
    "root_resident_concrete_stages_initial": ("codex-rs/hepta-agentd/src/authority_host_learning_resident_runtime.rs",),
    "root_resident_concrete_stages_gate": ("codex-rs/hepta-agentd/src/authority_host_learning_resident_runtime.rs",),
    "root_resident_concrete_stages_route": ("codex-rs/hepta-agentd/src/authority_host_learning_resident_runtime.rs",),
}


class ResidentCandidateStageClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {row.identifier: row for row in PROOF._boundary_rows(cls.manifest)}

    def code(self, source):
        return PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))

    def verifies(self, path, source):
        rows = [row for row in self.manifest["protected_file"] if row["path"] == path]
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["required"])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(source)
            PROOF._verify_protected_files(root, {"protected_file": rows})

    def rejects(self, path, function, marker, replacement=""):
        source = (ROOT / path).read_text()
        code = self.code(source)
        start = code.index(function)
        end = PROOF._rust_item_end(code, start)
        self.assertIsNotNone(end)
        offset = source.index(marker, start, end + 1)
        self.verifies(path, source)
        changed = source[:offset] + replacement + source[offset + len(marker):]
        with self.assertRaises(PROOF.VerificationFailure):
            self.verifies(path, changed)

    def test_only_the_concrete_root_factory_and_closed_enum_call_each_bundle(self):
        paths = {
            path for identifier in EXPECTED
            for path in (self.boundaries[identifier].definition_path,
                         *self.boundaries[identifier].product_callers)
        }
        sources = {path: self.code((ROOT / path).read_text()) for path in paths}
        for identifier, expected in EXPECTED.items():
            with self.subTest(boundary=identifier):
                row = self.boundaries[identifier]
                self.assertEqual(row.product_callers, expected)
                self.assertIn(identifier, self.manifest["privileged_inventory"]["required_boundary_ids"])
                PROOF._verify_boundary(ROOT, row, sources, ())
                method = row.symbol.rsplit("::", 1)[-1]
                extra = dict(sources)
                extra[AGENT + "unregistered_resident_candidate.rs"] = (
                    f"fn bypass(owner: &mut {row.receiver_type}) {{ owner.{method}(); }}"
                )
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, row, extra, ())

    def test_both_factories_consume_original_values_under_the_same_root_registration(self):
        for function, marker in (
            ("fn into_runtime(", "stages: crate::OriginalCellQ24NoUpdateStageOwnersV1"),
            ("fn into_runtime(", "self.owner,\n            stages::ResidentOriginalStageOwnersV3::NoUpdate(stages),\n            verifier,\n            capacity"),
            ("fn into_candidate_runtime(", "stages: crate::OriginalCellQ24CandidateStageOwnersV1"),
            ("fn into_candidate_runtime(", "self.owner,\n            stages::ResidentOriginalStageOwnersV3::Candidate(stages),\n            verifier,\n            capacity"),
        ):
            self.rejects(FACTORY, function, marker)
        for marker in (
            "OriginalCellQ24NoUpdateStageOwnersV1::require_initial(",
            "OriginalCellQ24CandidateStageOwnersV1::require_initial(",
        ):
            self.rejects(STAGES, "fn require_initial(", marker)
        for marker in (
            "profile\n        .require_verifier(&verifier)",
            "ResidentOriginalStageOwnersV3::require_initial(\n        &stages,\n        &profile.initial,\n        &profile.scope,\n        &verifier,\n    )",
            "owner\n        .authority\n        .authorization_binding()",
            "admission_requested: readonly",
        ):
            self.rejects(RUNTIME, "fn compose(", marker)

    def test_only_fresh_cas_installs_the_same_gate_and_no_callback_or_clone_can_escape(self):
        for marker in (
            "ResidentRegisteredStateV3::admit(&self.owner, cancellation).await?",
            "ResidentStagesV3::Uninstalled(slot)",
            "slot.take().ok_or(Error::CommitUncertain)?",
            "ResidentOriginalStageOwnersV3::install_fresh_resident_gate(",
            "let stages = Arc::new(stages)",
            "self.stages = ResidentStagesV3::Installed(Arc::clone(&stages))",
            "Box::pin(continue_original(owner, stages, verifier, continuation))",
        ):
            self.rejects(RUNTIME, "fn admit(", marker)
        for marker in (
            "OriginalCellQ24NoUpdateStageOwnersV1::install_fresh_resident_gate(stages, gate)",
            "OriginalCellQ24CandidateStageOwnersV1::install_fresh_resident_gate(stages, gate)",
        ):
            self.rejects(STAGES, "fn install_fresh_resident_gate(", marker)
        for replacement in (
            "pub enum ResidentOriginalStageOwnersV3",
            "impl Clone for ResidentOriginalStageOwnersV3 {}",
            "fn callback(owner: &dyn LearningIterationStageOwnerPortsV1) {}",
        ):
            source = (ROOT / STAGES).read_text()
            self.verifies(STAGES, source)
            with self.assertRaises(PROOF.VerificationFailure):
                self.verifies(STAGES, source + "\n" + replacement + "\n")

    def test_actual_training_checkpoint_precedes_candidate_material_and_missing_caps_stay_denied(self):
        self.rejects(CANDIDATE, "fn validate_recovery<'a>", "self.common.origin == Origin::Recovered")
        self.rejects(CANDIDATE, "fn validate_recovery<'a>", "LearningIterationStageOwnerPortsV1::validate_recovery(&self.common, snapshot).await")
        self.rejects(RUNTIME, "fn continue_original(", "ResidentOriginalStageOwnersV3::require_stage(stages.as_ref(), stage)?")
        self.rejects(RUNTIME, "fn continue_original(", "gate.begin(&predecessor, stage).await?")
        self.rejects(RUNTIME, "fn continue_original(", "gate.checkpoint(&predecessor, coordinator.snapshot().clone())\n            .await?")
        for marker in (
            "Stage::Proposal => Err(Error::OwnerUnavailable(",
            "Self::NoUpdate(_) => Err(Error::OwnerUnavailable(",
            "Self::Candidate(_) => Ok(())",
        ):
            self.rejects(STAGES, "fn require_stage(", marker)
        self.rejects(CANDIDATE, "fn execute_stage<'a>", "self.execute_original_evaluation(snapshot).await")
        self.rejects(AUTH, "fn original_attestations(", "stages.validate_recovery(snapshot).await?")
        self.rejects(AUTH, "fn original_attestations(", "let (_, fresh) = owner.read(cancellation).await?")
        for marker in (
            "LearningIterationStageV1::Proposal =>",
            "snapshot.receipts.get(3) != Some(receipt)",
            "receipt.predecessor != training.snapshot().head_digest",
            "receipt.operation_id != profile.initial.request.operation_id",
            "receipt.observed_unix_seconds > signature.issued_at",
            "*candidate_bundle == candidate",
            "*evaluation_profile == profile.initial.request.evaluation_profile",
            "LearningEvidenceRoleV1::Evaluator",
            "LearningIterationStageV1::Evaluation => &[LearningIterationStageV1::Training]",
        ):
            self.rejects(AUTH, "fn verify_attestations(", marker)
        self.rejects(AUTH, "fn verify_attestations(", "snapshot.training_no_update_v2().is_none()")


if __name__ == "__main__":
    unittest.main()
