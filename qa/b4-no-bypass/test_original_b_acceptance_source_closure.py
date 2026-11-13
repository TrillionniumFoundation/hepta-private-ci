"""The original Root completion fact is fresh, immutable and committed last."""

import importlib.util
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[2]
AGENT = "codex-rs/hepta-agentd/src/"
SPEC = importlib.util.spec_from_file_location("b_acceptance_proof", ROOT / "scripts/verify_hepta_callers.py")
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)

CASES = (
    ("authority_host_q24_evaluation_acceptance", "fn retain_original_completed_acceptance(", (
        "self.completed_acceptance.is_some()",
        "self.realized_training_head != Some(completed.training.head_digest.into_array())",
        "verifier.trust_digest().into_array() != self.trust",
        ".validate_snapshot(&completed.training)",
        "learning_iteration_receipt_signing_bytes_v1(training)",
        "self.original_training_attestation.as_ref() != Some(&training_bytes)",
        "self.completed_receipt != Some(Digest32::of_bytes(&evaluation_payload).into_array())",
        "let verified_at = HostAuthorityService::original_learning_unix_seconds(service)?",
        "LearningEvidenceRoleV1::Generator,", "&completed.training_attestation,", "&training_payload,", "verified_at,",
        "LearningEvidenceRoleV1::Evaluator,", "&completed.attestation,", "&evaluation_payload,", "verified_at,",
        "generator.principal().principal_id != completed.training.owners.trainer",
        "evaluator.principal().principal_id != completed.training.owners.evaluator",
        "verify_signed_actor_separation(&generator, &evaluator, verified_at)",
        "root_verified_at_seconds: verified_at", "native_verified_at_seconds: completed.verified_at",
        "enrollment_cut: self.completed_enrollment_cut()?.into_array()",
        "acceptance.require_original(self)?", "self.completed_acceptance = Some(acceptance)",
    )),
    ("authority_host_q24_evaluation_acceptance", "fn require_completed_acceptance(", (
        "match (&self.completed_receipt, &self.completed_acceptance)",
        "(None, None) => Ok(())", "(Some(_), Some(acceptance)) => acceptance.require_original(self)",
        "_ => Err(io::Error::other(",
    )),
    ("authority_host_q24_evaluation_acceptance", "fn completed_enrollment_cut(", (
        "self.completed_receipt.is_none()", "self.realized_training_head.is_none()",
        "self.realized_plan.is_none()", "self.realized_plan_statement.is_none()",
        "self.original_training_attestation.is_none()", "self.original_training_work.is_none()",
        "self.heads.is_none()", "self.cell_images.as_ref().is_none_or(Vec::is_empty)",
        "self.output_images.is_empty()", "self.admitted_source.is_none()",
        "self.released_source != self.admitted_source", "let mut original = self.clone()",
        "original.completed_acceptance = None", "serde_json::to_vec(&original)",
        "Digest32::of_parts(&[", "&bytes",
    )),
    ("authority_host_q24_evaluation_acceptance", "fn require_original(", (
        "self.schema != 1", "self.frozen_scope == [0; 32]",
        "self.root_verified_at_seconds < original.registered_at_seconds",
        "self.root_verified_at_seconds >= original.expires_at_seconds",
        "self.native_verified_at_seconds < original.registered_at_seconds",
        "self.native_verified_at_seconds > self.root_verified_at_seconds",
        "self.training_attestation != Digest32::of_bytes(training).into_array()",
        "self.evaluation_attestation == [0; 32]",
        "self.enrollment_cut != original.completed_enrollment_cut()?.into_array()",
    )),
    ("authority_host_q24_evaluation_record", "fn inspect<T>(", (
        "let before = self.load_ready()?", "armed.phase = Phase::Inspecting",
        ".compare_and_set(&self.owner, &before, &armed)", "let value = action(&mut enrollment)?",
        "immutable.completed_acceptance = original.completed_acceptance.clone()",
        "if &immutable != original",
        ".is_some_and(|old| enrollment.completed_acceptance.as_ref() != Some(old))",
        "Instant::now() >= end", "OriginalBEnrollment::require_completed_acceptance(&enrollment)?",
        "ready.phase = Phase::Ready", ".compare_and_set(&self.owner, &armed, &ready)",
        "self.store.load(&self.owner).map_err(io::Error::other)? != ready",
        "if result.is_err()", "self.poisoned.store(true, Ordering::Release)",
    )),
    ("authority_host_q24_evaluation_record", "fn load_ready(", (
        "if self.poisoned.load(Ordering::Acquire)", "self.store.load(&self.owner)",
        "loaded.schema != 2", "loaded.purpose !=",
        "loaded.phase != Phase::Ready", "OriginalBEnrollment::require_completed_acceptance(",
        "if let Err(error) = acceptance", "self.poisoned.store(true, Ordering::Release)", "Ok(loaded)",
    )),
    ("authority_host_q24_evaluation_operation", "fn with_operation<T>(", (
        "let end = self.end.min(frame_end)", "OriginalBRecord::inspect(&self.record, end,",
        "let previously_completed = enrollment.completed_receipt", "service.with_learning_profile(",
        "Ok((value?, after, before, authorities))", "owner_alive(owner, end)?",
        "require_files(files, enrollment, now)?", "if cell_locks.is_none()",
        "if previously_completed.is_none()", "!matches!(operation, Operation::Complete { .. })",
        "super::super::record::OriginalBEnrollment::retain_original_completed_acceptance(",
        "&self.profile.require_cell_scope(&self.initial)?", "&authorities.verifier",
        "files.require_original_files()?", "native.original_heads(Digest32::from_array(enrollment.namespace))?",
        "enrollment.output_images != native.output_images(files)?", "owner_alive(owner, end)?", "Ok(value)",
    )),
)

BOUNDARIES = {
    "root_independent_b_accept_completed": ("authority_host_q24_evaluation_operation",),
    "root_independent_b_require_completed_fact": ("authority_host_q24_evaluation_record",),
}


class OriginalBCompletionAcceptanceSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())

    def rows(self, stem):
        required = {
            "authority_host_q24_evaluation_acceptance": "struct OriginalBCompletedAcceptanceV1",
            "authority_host_q24_evaluation_record": "completed_acceptance",
            "authority_host_q24_evaluation_operation": "let previously_completed = enrollment.completed_receipt;",
        }[stem]
        rows = [r for r in self.manifest["protected_file"]
                if r["path"] == AGENT + stem + ".rs" and required in r["required"]]
        self.assertEqual(len(rows), 1)
        return rows

    def test_new_guards_match_actual_functions(self):
        for stem in dict.fromkeys(stem for stem, _, _ in CASES):
            PROOF._verify_protected_files(ROOT, {"protected_file": self.rows(stem)})

    def test_every_acceptance_gate_rejects_removal_or_comment(self):
        for stem, function, markers in CASES:
            path = AGENT + stem + ".rs"
            original = (ROOT / path).read_text()
            code = PROOF._strip_rust_non_code(original)
            self.assertEqual(code.count(function), 1)
            start = code.index(function)
            end = PROOF._rust_item_end(code, start)
            self.assertIsNotNone(end)
            body = code[start:end + 1]
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                target = root / path
                target.parent.mkdir(parents=True)
                cursor = len(function)
                for marker in markers:
                    position = body.index(marker, cursor)
                    cursor = position + len(marker)
                    offset = start + position
                    for replacement in ("", "/*" + marker + "*/"):
                        with self.subTest(function=function, marker=marker):
                            target.write_text(original[:offset] + replacement + original[offset + len(marker):])
                            with self.assertRaises(PROOF.VerificationFailure):
                                PROOF._verify_protected_files(root, {"protected_file": self.rows(stem)})

    def test_only_actual_completion_and_root_record_are_callers(self):
        inventory = self.manifest["privileged_inventory"]["required_boundary_ids"]
        for name, callers in BOUNDARIES.items():
            rows = [r for r in self.manifest["boundary"] if r["id"] == name]
            self.assertEqual(len(rows), 1)
            self.assertIn(name, inventory)
            self.assertEqual(rows[0]["product_callers"], [AGENT + c + ".rs" for c in callers])
        clock = next(r for r in self.manifest["boundary"] if r["id"] == "root_original_learning_time")
        self.assertIn(AGENT + "authority_host_q24_evaluation_acceptance.rs", clock["product_callers"])


if __name__ == "__main__":
    unittest.main()
