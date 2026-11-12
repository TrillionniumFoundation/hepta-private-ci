"""Keep actual retention observations distinct from positive adoption eligibility.

These source controls accompany the existing real material/Cold CURRENT mechanism.
They do not establish a Qualified ordinary panel or a successful Version effect.
"""
import importlib.util
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest

from rust_source_marker_support import source_marker_span

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "original_retention_admission_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)

MATERIAL = "codex-rs/hepta-agentd/src/neuron_cell_evaluation_model_material.rs"
VERIFY = "codex-rs/hepta-agentd/src/neuron_cell_evaluation_model_material_verify.rs"


class OriginalRetentionAdmissionClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())

    def records(self, path):
        rows = [row for row in self.manifest["protected_file"] if row["path"] == path]
        self.assertTrue(rows, path)
        return rows

    def verifies(self, path, source):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(source)
            PROOF._verify_protected_files(root, {"protected_file": self.records(path)})

    def rejects(self, path, function, marker, replacement=""):
        source = (ROOT / path).read_text()
        code = PROOF._strip_rust_non_code(source)
        self.assertEqual(code.count(function), 1)
        start = code.index(function)
        end = PROOF._rust_item_end(code, start)
        self.assertIsNotNone(end)
        first, limit = source_marker_span(code, marker, start, end + 1)
        self.verifies(path, source)
        changed = source[:first] + replacement + source[limit:]
        self.assertNotEqual(changed, source)
        with self.assertRaises(PROOF.VerificationFailure):
            self.verifies(path, changed)

    def test_complete_material_records_validate_without_execution_authority(self):
        for path in (MATERIAL, VERIFY):
            self.verifies(path, (ROOT / path).read_text())
        self.assertTrue(all(value is False for value in self.manifest["authority"].values()))

    def test_acceptance_cannot_skip_actual_members_signatures_or_the_complete_retention_set(self):
        for marker in (
            "context.authenticate(current)?",
            "super::super::wire::authenticate_completed(context, snapshot, signed, current)?",
            "body.members.len() != context.registration.retention().len() + 1",
            "std::iter::once(context.registration.primary()).chain(context.registration.retention())",
            "member::verify(raw, context, task, &generator, current)?",
            "member::cohort(raw, &checked, context, task, &generator, current)?",
            "!namespaces.insert(raw.execution_namespace)",
            "!namespaces.insert(raw.qualification_namespace)",
            "run == context.training.request.source_run_id.as_str()",
            "!runs.insert(run.to_owned())",
            "checked_members.push(checked)",
            "retention.is_empty()",
            "primary.retention != retention",
            "Digest32::of_bytes(&panel) != body.panel",
            "primary.qualification != expected.receipt().evidence_digest",
            "primary.evaluator_issued_at != expected.receipt().observed_unix_seconds",
        ):
            with self.subTest(marker=marker):
                self.rejects(VERIFY, "fn material(", marker)

    def test_all_verified_members_govern_admission_without_rewriting_primary_observation(self):
        marker = "let qualified = checked_members.iter().all(|member| member.qualified)"
        for replacement in (
            "let qualified = primary.qualified",
            "let qualified = true",
            "let qualified = checked_members.iter().any(|member| member.qualified)",
            "let qualified = checked_members.iter().skip(1).all(|member| member.qualified)",
            "let qualified = checked_members.iter().filter(|member| member.qualified).all(|member| member.qualified)",
        ):
            with self.subTest(replacement=replacement):
                self.rejects(VERIFY, "fn material(", marker, replacement)
        self.rejects(
            VERIFY, "fn material(", "let disposition = if primary.qualified",
            "let disposition = if qualified",
        )
        self.rejects(
            VERIFY, "fn material(",
            "Ok(Checked { candidate, material: model_material.ok_or(Error::CommitUncertain)?, qualified, })",
            "Ok(Checked { candidate, material: model_material.ok_or(Error::CommitUncertain)?, qualified: primary.qualified, })",
        )

    def test_model_and_selector_require_the_same_verified_acceptance_gate(self):
        for marker in (
            "training != &self.context.training",
            "training_evidence != &self.context.training_evidence",
            "current < self.observed_at",
            "Digest32::of_bytes(&self.bytes) != self.binding",
            "verify::material(&self.context, &self.evaluation, &self.bytes, current)?",
            "if !checked.qualified",
        ):
            with self.subTest(marker=marker):
                self.rejects(MATERIAL, "fn require_original_model_input(", marker)
        self.rejects(
            MATERIAL, "fn require_original_model_input(", "if !checked.qualified",
            "if checked.qualified",
        )
        gate = ("self.require_original_model_input("
                "&self.context.training, &self.context.training_evidence, current,)?")
        self.rejects(MATERIAL, "fn require_original_selector_material(", gate)
        self.rejects(
            MATERIAL, "fn require_original_selector_material(", gate,
            "self.authenticate_current(current)?",
        )


if __name__ == "__main__":
    unittest.main()
