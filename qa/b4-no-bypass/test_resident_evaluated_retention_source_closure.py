"""Authenticate complete negative Candidate metadata without opening effects.

Exact source mutations preserve the original signature verifier, retained
baseline branch and pairwise T/B/S/C separation. They do not provide opaque
role receipts, original role hosts, publication or ordinary qualification.
"""

import importlib.util
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "resident_retention_auth_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
AGENT = "codex-rs/hepta-agentd/src/"
AUTH = AGENT + "authority_host_learning_resident_auth.rs"
WIRE = AGENT + "authority_host_learning_resident_wire.rs"
STAGES = AGENT + "authority_host_learning_resident_stages.rs"
CANDIDATE = AGENT + "cell_q24_candidate_stage_owners.rs"
VERIFY = "fn verify_non_model_attestations("


class ResidentEvaluatedRetentionSourceClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())

    def verifies(self, path, source):
        rows = [row for row in self.manifest["protected_file"] if row["path"] == path]
        self.assertEqual(len(rows), 1)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(source)
            PROOF._verify_protected_files(root, {"protected_file": rows})

    def rejects(self, path, function, marker, replacement="", after=None, occurrence=0):
        source = (ROOT / path).read_text()
        code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
        start = code.index(function)
        end = PROOF._rust_item_end(code, start)
        self.assertIsNotNone(end)
        offset = source.index(after, start, end + 1) if after else start
        for _ in range(occurrence + 1):
            chosen = source.index(marker, offset, end + 1)
            offset = chosen + len(marker)
        self.verifies(path, source)
        with self.assertRaises(PROOF.VerificationFailure, msg=(path, function, marker, after, occurrence)):
            self.verifies(path, source[:chosen] + replacement + source[chosen + len(marker):])

    def test_only_original_fourth_negative_evaluation_can_select_retention(self):
        for marker in (
            "profile\n        .require_verifier(verifier)",
            "profile.scope.validate_snapshot(snapshot)?;",
            "let coordinator = LearningIterationCoordinatorV1::from_snapshot(snapshot.clone())?;",
            "let evaluated_retention = matches!(",
            "snapshot.receipts.get(3).map(|receipt| &receipt.observation)",
            "disposition: LearningEvaluationDispositionV1::NoUpdate,",
            "if evaluated_retention {",
        ):
            self.rejects(AUTH, VERIFY, marker)
        for marker, changed in (
            ("let evaluated_retention = matches!(", "let evaluated_retention = !matches!("),
            ("snapshot.receipts.get(3)", "snapshot.receipts.get(2)"),
            ("disposition: LearningEvaluationDispositionV1::NoUpdate,", "disposition: LearningEvaluationDispositionV1::Qualified,"),
            ("if evaluated_retention {", "if !evaluated_retention {"),
        ):
            self.rejects(AUTH, VERIFY, marker, changed)

    def test_negative_shape_requires_exact_stage_order_and_original_candidate(self):
        for stage in ("Experience", "Dataset", "Training", "Evaluation", "Selection", "NextUse"):
            self.rejects(AUTH, VERIFY, "LearningIterationStageV1::" + stage + ",", after="let stages = [")
        for marker in (
            ".candidate()\n            .ok_or(Error::WrongScope)?",
            "let baseline = snapshot\n            .request\n            .selected_bundle\n            .digest()",
            "if !(4..=6).contains(&snapshot.receipts.len())",
            ".zip(stages)",
            ".all(|(receipt, stage)| receipt.observation.stage() == stage)",
            "snapshot.receipts[2].observation",
            "LearningIterationObservationV1::Training { .. }",
            "|| candidate == baseline",
            "|| coordinator.next_task_bundle() != Some(&snapshot.request.selected_bundle)",
            "|| snapshot.receipts.get(5).is_some_and(|receipt| {",
            "LearningIterationObservationV1::RetainedModelNextUse { .. }",
        ):
            self.rejects(AUTH, VERIFY, marker, after="if evaluated_retention {")
        for marker, changed in (
            ("if !(4..=6).contains", "if (4..=6).contains"),
            ("4..=6", "4..=7"),
            (".all(|(receipt, stage)|", ".any(|(receipt, stage)|"),
            ("receipt.observation.stage() == stage", "receipt.observation.stage() != stage"),
            ("|| !matches!(", "|| matches!("),
            ("|| candidate == baseline", "|| candidate != baseline"),
            ("coordinator.next_task_bundle() != Some", "coordinator.next_task_bundle() == Some"),
            (".get(5).is_some_and", ".get(5).is_none_or"),
            ("LearningIterationObservationV1::RetainedModelNextUse { .. }", "LearningIterationObservationV1::NextUse { .. }"),
        ):
            self.rejects(AUTH, VERIFY, marker, changed, after="if evaluated_retention {")
        self.rejects(AUTH, VERIFY, "!matches!(", "matches!(", after="snapshot.receipts.get(5)")

    def test_six_signature_exception_does_not_replace_model_or_training_no_update_bounds(self):
        for marker in (
            "proposal_count > 1",
            "proposal_count == 1\n            && (snapshot.receipts.len() != 5",
            "snapshot.receipts[4].observation.stage() != LearningIterationStageV1::Proposal",
            "signatures.len() + proposal_count != snapshot.receipts.len()",
            "signatures.len() > 5 && (!evaluated_retention || signatures.len() != 6)",
        ):
            self.rejects(AUTH, VERIFY, marker)
        for marker, changed in (
            ("signatures.len() > 5", "signatures.len() > 6"),
            ("!evaluated_retention || signatures.len() != 6", "evaluated_retention || signatures.len() != 6"),
            ("!evaluated_retention || signatures.len() != 6", "!evaluated_retention && signatures.len() != 6"),
            ("signatures.len() != 6", "signatures.len() == 6"),
            ("snapshot.receipts.len() != 5", "snapshot.receipts.len() != 6"),
        ):
            self.rejects(AUTH, VERIFY, marker, changed)
        for marker in (
            "verify_non_model_attestations(profile, verifier, snapshot, signatures, now)?",
            "(true, Some(model)) => model.require_original(profile, verifier, snapshot, signatures, now)",
            "(false, Some(_)) | (true, None) => Err(Error::WrongScope)",
        ):
            self.rejects(AUTH, "fn verify_original_evidence(", marker)

    def test_every_receipt_still_requires_current_original_signature_and_signed_time(self):
        for marker in (
            "learning_iteration_receipt_signing_bytes_v1(receipt)?",
            "verifier\n            .verify(role, signature, &payload, now)",
            ".map_err(Error::Evidence)?;",
            "evidence.principal().principal_id != receipt.actor_id",
            "&receipt.actor_id != snapshot.owners.owner(stage)",
            "evidence.trust_digest() != snapshot.owners.evidence_trust_digest",
            "evidence.objective_digest() != snapshot.request.envelope.objective_digest",
            "|| evaluated_retention && receipt.observed_unix_seconds > signature.issued_at",
        ):
            self.rejects(AUTH, VERIFY, marker, after="let payload = learning_iteration_receipt_signing_bytes_v1(receipt)?;")
        marker = "|| evaluated_retention && receipt.observed_unix_seconds > signature.issued_at"
        self.rejects(AUTH, VERIFY, marker, marker.replace(">", "<="))
        self.rejects(AUTH, VERIFY, marker, marker.replace("&&", "||"))
        self.rejects(AUTH, VERIFY, marker, marker.replace("evaluated_retention", "!evaluated_retention"))

    def test_selector_and_c_each_require_every_independent_original_predecessor(self):
        separation = "for (stage, current) in &verified {"
        self.rejects(AUTH, VERIFY, "LearningIterationStageV1::Evaluation => &[LearningIterationStageV1::Training]", after=separation)
        for marker in (
            "if snapshot.training_no_update_v2().is_none() && !evaluated_retention {",
            "if evaluated_retention {",
            "} else {\n                    &[LearningIterationStageV1::Training]\n                }",
        ):
            self.rejects(AUTH, VERIFY, marker, after=separation)
        self.rejects(AUTH, VERIFY, "if evaluated_retention {", "if !evaluated_retention {", after=separation)
        for anchor, stages in (
            ("if evaluated_retention {\n                    &[", ("Training", "Evaluation")),
            ("LearningIterationStageV1::NextUse if evaluated_retention => &[", ("Training", "Evaluation", "Selection")),
            ("LearningIterationStageV1::NextUse => &[", ("Training", "Selection")),
        ):
            for stage in stages:
                self.rejects(AUTH, VERIFY, "LearningIterationStageV1::" + stage, after=anchor)
        marker = "LearningIterationStageV1::NextUse if evaluated_retention => &["
        self.rejects(AUTH, VERIFY, marker, marker.replace("if evaluated_retention", "if !evaluated_retention"))
        for marker in (
            "for predecessor in independent {",
            ".find(|(stage, _)| stage == predecessor)",
            ".ok_or(Error::Evidence(SignedEvidenceError::ContextMismatch))?;",
            "verify_signed_actor_separation(&previous.1, current, now).map_err(Error::Evidence)?;",
        ):
            self.rejects(AUTH, VERIFY, marker, after=separation)
        marker = "verify_signed_actor_separation(&previous.1, current, now).map_err(Error::Evidence)?;"
        self.rejects(AUTH, VERIFY, marker, marker.replace(".map_err(Error::Evidence)?", ".or(Ok(()))?"))

    def test_wire_bound_is_six_and_the_complete_model_aware_auth_result_is_mandatory(self):
        function = "fn decode_current("
        for marker in (
            "if evidence.len() > 6 {", "encoded.len() > 10_924", "encoded.len() > BOUND",
            "!payload.is_empty()", "encoded.len() != 203",
            "ResidentOriginalModelProofV3::decode_root_reply(",
            "match &snapshot", "Some(snapshot) => authentication::verify_original_evidence(",
            "None if !attestations.is_empty() || dispatch_pending || model.is_some()",
        ):
            self.rejects(WIRE, function, marker)
        self.rejects(WIRE, function, "evidence.len() > 6", "evidence.len() > 7")
        self.rejects(WIRE, function, "evidence.len() > 6", "evidence.len() <= 6")
        for marker in ("profile,", "verifier,", "snapshot,", "&attestations,", "model.as_ref(),", "now,", ")?,"):
            self.rejects(WIRE, function, marker, after="Some(snapshot) => authentication::verify_original_evidence(")
        self.rejects(WIRE, function, ")?,", ").or(Ok(()))?,", after="Some(snapshot) => authentication::verify_original_evidence(")
        self.rejects(WIRE, function, "authentication::verify_original_evidence(", "authentication::verify_attestations(")

    def test_guarded_root_checks_cannot_be_hidden_in_dead_nested_blocks(self):
        for path, function, marker in (
            (AUTH, VERIFY, "profile.scope.validate_snapshot(snapshot)?;"),
            (AUTH, VERIFY, "let coordinator = LearningIterationCoordinatorV1::from_snapshot(snapshot.clone())?;"),
            (WIRE, "fn decode_current(", "match &snapshot"),
        ):
            self.rejects(path, function, marker, "if false { " + marker + " }")

    def test_authentication_does_not_open_candidate_effects_or_original_root_factories(self):
        self.rejects(STAGES, "fn require_stage(",
                     "matches!(self, Self::Candidate(_))\n                    && snapshot.training_no_update_v2().is_none()")
        self.rejects(CANDIDATE, "fn execute_stage<'a>",
                     "matches!(stage, Stage::Selection | Stage::NextUse)")
        self.rejects(CANDIDATE, "fn execute_stage<'a>",
                     "snapshot.training_no_update_v2().is_none()")
        boundaries = {row.identifier: row for row in PROOF._boundary_rows(self.manifest)}
        for identifier in (
            "root_resident_original_register", "root_resident_original_recover",
            "root_resident_service_register", "root_resident_service_recover",
            "root_resident_coordinator_run", "root_learning_original_stage_assembly",
        ):
            self.assertEqual(boundaries[identifier].product_callers, ())
        self.assertTrue(all(value is False for value in self.manifest["authority"].values()))


if __name__ == "__main__":
    unittest.main()
