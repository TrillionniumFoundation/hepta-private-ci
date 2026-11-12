"""Fence the two reviewed retention guards without inventing member evidence.

These are source-mutation checks of the original verifier, not execution of a
signed positive-primary/negative-retention panel. That behavior fixture remains
unavailable; no qualification seal, signature, owner or receipt is fabricated.
"""

import importlib.util
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "original_evaluation_retention_guard_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
AGENT = "codex-rs/hepta-agentd/src/"
PANEL = AGENT + "neuron_cell_evaluation_panel_binding.rs"
MATERIAL = AGENT + "neuron_cell_evaluation_model_material_verify.rs"
PANEL_GUARD = (
    "if observed[0]\n"
    "            .qualification\n"
    "            .product()\n"
    "            .decision\n"
    "            .decision\n"
    "            .disposition"
)
MATERIAL_GUARD = (
    "if primary.qualified\n"
    "        && checked_members\n"
    "            .iter()\n"
    "            .skip(1)\n"
    "            .any(|member| !member.qualified)"
)


class OriginalEvaluationRetentionGuardClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())

    def assert_rejected(self, path, changed):
        original = (ROOT / path).read_text()
        self.assertNotEqual(original, changed)
        rows = [row for row in self.manifest["protected_file"] if row["path"] == path]
        self.assertEqual(len(rows), 1)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(original)
            PROOF._verify_protected_files(root, {"protected_file": rows})
            target.write_text(changed)
            with self.assertRaises(PROOF.VerificationFailure):
                PROOF._verify_protected_files(root, {"protected_file": rows})

    def guard(self, path):
        source = (ROOT / path).read_text()
        marker, tail = (
            (PANEL_GUARD, "        Ok(())")
            if path == PANEL
            else (MATERIAL_GUARD, "    let disposition = if primary.qualified")
        )
        self.assertEqual(source.count(marker), 1)
        start = source.index(marker)
        end = source.index(tail, start)
        return source, start, end, source[start:end]

    def test_guard_deletion_inversion_and_incomplete_retention_iteration_are_rejected(self):
        for path in (PANEL, MATERIAL):
            source, start, end, guard = self.guard(path)
            self.assert_rejected(path, source[:start] + source[end:])
            replacements = (
                (
                    "== IndependentEvaluationDispositionV1::EligibleForIndependentSelection",
                    "!= IndependentEvaluationDispositionV1::EligibleForIndependentSelection",
                ),
                (
                    "!= IndependentEvaluationDispositionV1::EligibleForIndependentSelection",
                    "== IndependentEvaluationDispositionV1::EligibleForIndependentSelection",
                ),
            ) if path == PANEL else (
                (
                    "primary.qualified\n        &&",
                    "!primary.qualified\n        &&",
                ),
                ("|member| !member.qualified", "|member| member.qualified"),
            )
            replacements += (
                (".any(", ".all("),
                (".skip(1)", ".skip(2)"),
                ("return Err(Error::Binding(", "return Err(Error::CommitUncertain("),
            )
            for old, new in replacements:
                with self.subTest(path=path, mutation=(old, new)):
                    self.assertEqual(guard.count(old), 1)
                    changed = guard.replace(old, new, 1)
                    self.assert_rejected(path, source[:start] + changed + source[end:])

    def test_guard_must_execute_at_the_original_top_level_before_success_mapping(self):
        for path in (PANEL, MATERIAL):
            source, start, end, guard = self.guard(path)
            for hidden in (
                "/* " + guard + " */\n",
                "if false {\n" + guard + "}\n",
                "if additional_condition {\n" + guard + "}\n",
            ):
                with self.subTest(path=path, hidden=hidden[:30]):
                    self.assert_rejected(path, source[:start] + hidden + source[end:])
            if path == MATERIAL:
                tail = "    let disposition = if primary.qualified {\n"
                source_without = source[:start] + source[end:]
                changed = source_without.replace(tail, tail + guard, 1)
                self.assert_rejected(path, changed)

    def test_original_unknown_signed_member_order_and_complete_no_update_mapping_remain(self):
        panel = (ROOT / PANEL).read_text()
        unknown = "== IndependentEvaluationDispositionV1::InsufficientEvidence"
        self.assertEqual(panel.count(unknown), 1)
        self.assert_rejected(PANEL, panel.replace(unknown, "", 1))
        material = (ROOT / MATERIAL).read_text()
        for marker in (
            "let generator = context.authenticate(current)?;",
            "let actual = super::super::wire::authenticate_completed(context, snapshot, signed, current)?;",
            "body.members.len() != context.registration.retention().len() + 1",
            "let checked = member::verify(raw, context, task, &generator, current)?;",
            "let cohort = member::cohort(raw, &checked, context, task, &generator, current)?;",
            "checked_members.push(checked);",
            "primary.retention != retention",
            "Digest32::of_bytes(&panel) != body.panel",
            "primary.qualification != expected.receipt().evidence_digest",
            "primary.evaluator_issued_at != expected.receipt().observed_unix_seconds",
            "let disposition = if primary.qualified {",
            "LearningEvaluationDispositionV1::NoUpdate",
            "if expected.receipt().observation",
            "qualified: primary.qualified",
        ):
            with self.subTest(marker=marker):
                self.assertEqual(material.count(marker), 1)
                self.assert_rejected(MATERIAL, material.replace(marker, "", 1))


if __name__ == "__main__":
    unittest.main()
