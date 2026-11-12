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
ADOPTION = AGENT + "cell_q24_candidate_stage_adoption.rs"
GATE = AGENT + "authority_host_learning_resident_gate.rs"
EXPECTED = {
    "learning_original_candidate_adoption_stage": ("codex-rs/hepta-agentd/src/authority_host_learning_resident_stages.rs",),
    "learning_original_no_update_stage_initial": ("codex-rs/hepta-agentd/src/authority_host_learning_resident_stages.rs", "codex-rs/hepta-agentd/src/cell_q24_candidate_stage_owners.rs",),
    "learning_original_no_update_stage_resident_gate": ("codex-rs/hepta-agentd/src/authority_host_learning_resident_stages.rs", "codex-rs/hepta-agentd/src/cell_q24_candidate_stage_owners.rs",),
    "learning_original_candidate_stage_initial": ("codex-rs/hepta-agentd/src/authority_host_learning_resident_stages.rs",),
    "learning_original_candidate_stage_resident_gate": ("codex-rs/hepta-agentd/src/authority_host_learning_resident_stages.rs",),
    "root_resident_candidate_runtime_consume": (),
    "root_resident_concrete_stages_initial": ("codex-rs/hepta-agentd/src/authority_host_learning_resident_runtime.rs", "codex-rs/hepta-agentd/src/authority_host_learning_resident_auth.rs",),
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
        self.rejects(RUNTIME, "fn continue_original(", "ResidentOriginalStageOwnersV3::require_stage(\n            stages.as_ref(),\n            coordinator.snapshot(),\n            stage,\n        )?")
        self.rejects(RUNTIME, "fn continue_original(", "gate.begin(&predecessor, stage).await?")
        self.rejects(RUNTIME, "fn continue_original(", "gate.checkpoint(&predecessor, coordinator.snapshot().clone())\n            .await?")
        for marker in (
            "Stage::Evaluation | Stage::Proposal => match self",
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
            self.rejects(AUTH, "fn verify_non_model_attestations(", marker)
        for marker in (
            "snapshot.training_no_update_v2().is_some()",
            "proposal_count != 1 || snapshot.receipts.len() < 6",
            "proposal_count != 1 || snapshot.receipts.len() != 7",
        ):
            self.rejects(AUTH, "fn verify_non_model_attestations(", marker)
        # Keep Candidate and NoUpdate separate. The concrete private Candidate
        # route now checks the original cut and installed gate before dispatch.
        self.rejects(STAGES, "fn require_stage(", "snapshot.training_no_update_v2().is_none()")


    def test_private_adoption_dispatch_keeps_exact_fresh_cut_and_installed_gate(self):
        # Baseline verification is source qualification, not a successful
        # runtime adoption or an independent Qualified B/retention panel.
        for path in (STAGES, ADOPTION, CANDIDATE):
            self.verifies(path, (ROOT / path).read_text())
        for marker in (
            "let Self::Candidate(stages) = self else {",
            "return Err(Error::WrongScope);",
            "OriginalCellQ24CandidateStageOwnersV1::require_original_adoption_stage(",
            "stages, snapshot, stage,",
        ):
            self.rejects(STAGES, "fn require_stage(", marker)
        for marker, replacement in (
            ("self.require_adoption_cut(snapshot, stage, Action::Execute)?;", ""),
            ("Action::Execute", "Action::Readback"),
            ("if self.common.root.is_none() {", ""),
            ('return Err(Error::OwnerUnavailable("fresh resident continuation"));', ""),
        ):
            self.rejects(ADOPTION, "fn require_original_adoption_stage(", marker, replacement)
        for marker, replacement in (
            ("self.require_live_deadline()?;", ""),
            ("model_cut(self, snapshot)?;", ""),
            ("(Stage::Selection, Action::Execute) => 5,", "(Stage::Selection, Action::Execute) => 6,"),
            ("(Stage::NextUse, Action::Execute) => 6,", "(Stage::NextUse, Action::Execute) => 5,"),
            ("snapshot.receipts.len() != expected", ""),
            ("action == Action::Execute", "action == Action::Readback"),
            ("self.common.origin != Origin::Fresh", ""),
            ("LearningIterationCoordinatorV1::from_snapshot(snapshot.clone())?.next_stage()", ""),
            ("!= Some(stage)", ""),
            ("_ => return Err(Error::WrongScope),", ""),
        ):
            self.rejects(ADOPTION, "fn require_adoption_cut(", marker, replacement)
        for marker in (
            "owners.training_prefix(snapshot)?;",
            "if !(5..=7).contains(&snapshot.receipts.len()) {",
            "owners.common.material.initial.clone(),",
            "for receipt in &snapshot.receipts[..5] {",
            "cut.record(receipt.clone(), receipt.observed_unix_seconds)?;",
            "if cut.next_stage() != Some(Stage::Selection) {",
            "owners.common.material.scope.validate_snapshot(cut.snapshot())?;",
        ):
            self.rejects(ADOPTION, "fn model_cut(", marker)
        source = (ROOT / ADOPTION).read_text()
        private = "pub(crate) fn require_original_adoption_stage("
        self.assertEqual(source.count(private), 1)
        with self.assertRaises(PROOF.VerificationFailure):
            self.verifies(ADOPTION, source.replace(
                private, "pub fn require_original_adoption_stage(", 1,
            ))

    def test_private_adoption_never_replaces_generic_denials_or_actual_root_fences(self):
        for function, marker in (
            ("fn execute_stage<'a>", "matches!(stage, Stage::Selection | Stage::NextUse)"),
            ("fn execute_stage<'a>", "snapshot.training_no_update_v2().is_none()"),
            ("fn execute_stage<'a>", 'return Err(Error::OwnerUnavailable(\n                        "original Candidate Model, Selector, version and FinalUse capabilities are required",\n                    ));'),
            ("fn receipt_attestation<'a>", 'return Err(Error::OwnerUnavailable(\n                        "original Candidate Model and adoption attestation capabilities are required",\n                    ));'),
            ("fn require_live_deadline(", "Instant::now() >= self.end"),
            ("fn require_live_deadline(", "return Err(Error::DeadlineExceeded);"),
        ):
            self.rejects(CANDIDATE, function, marker)
        # The predicate cannot establish CURRENT. The original runtime must
        # begin its real durable dispatch and enforce cancellation/current.
        for marker in (
            "gate.begin(&predecessor, stage).await?",
            "ResidentOriginalStageOwnersV3::execute_original_stage(",
            "gate.cancellation().cancelled()",
            "RootResidentLearningEffectGateV3::require_current(gate, &predecessor, &profile.scope).await?",
        ):
            self.rejects(RUNTIME, "fn continue_original(", marker)
        for marker in (
            "!self.inner.active.load(Ordering::Acquire)",
            "self.inner.cancellation.is_cancelled()",
            "predecessor.request != profile.initial.request",
            "predecessor.owners != profile.initial.owners",
            "profile.scope.validate_snapshot(predecessor).is_err()",
            "result.is_err() || self.inner.cancellation.is_cancelled()",
        ):
            self.rejects(GATE, "fn local(", marker)
        for marker in (
            "self.require_live_deadline()?;",
            "self.common.root.as_ref().ok_or(Error::CommitUncertain)?;",
            "RootResidentLearningEffectGateV3::require_current(",
            "gate, snapshot, &self.common.material.scope,",
        ):
            self.rejects(ADOPTION, "fn require_adoption_effect(", marker)


if __name__ == "__main__":
    unittest.main()
