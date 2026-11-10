"""Protect the combined frozen-profile and original evaluation recovery boundary."""

from dataclasses import replace
import importlib.util
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "learning_evaluation_recovery_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
CELL = "codex-rs/hepta-agentd/src/neuron_cell_evaluation.rs"
PRODUCT = "codex-rs/hepta-intelligence-eval/src/product_execution.rs"
CALLERS = {
    "cell_original_evaluation_execution": (),
    "product_original_evaluation_execution": (CELL,),
}


class LearningEvaluationRecoverySourceClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {row.identifier: row for row in PROOF._boundary_rows(cls.manifest)}
        cls.sources = {
            path: PROOF._strip_cfg_test_items(
                PROOF._strip_rust_non_code((ROOT / path).read_text())
            )
            for path in (CELL, PRODUCT)
        }

    def rejects(self, path, changed):
        rows = [row for row in self.manifest["protected_file"] if row["path"] == path]
        self.assertTrue(rows)
        source = (ROOT / path).read_text()
        self.assertNotEqual(source, changed)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(source)
            manifest = {"protected_file": rows}
            PROOF._verify_protected_files(root, manifest)
            target.write_text(changed)
            with self.assertRaises(PROOF.VerificationFailure):
                PROOF._verify_protected_files(root, manifest)

    def test_original_recovery_callers_remain_closed(self):
        inventory = self.manifest["privileged_inventory"]["required_boundary_ids"]
        for identifier, callers in CALLERS.items():
            with self.subTest(boundary=identifier):
                self.assertIn(identifier, inventory)
                row = self.boundaries[identifier]
                self.assertEqual(row.product_callers, callers)
                PROOF._verify_boundary(ROOT, row, self.sources, ())
                if callers:
                    with self.assertRaises(PROOF.VerificationFailure):
                        PROOF._verify_boundary(
                            ROOT, replace(row, product_callers=()), self.sources, ()
                        )
                sources = dict(self.sources)
                method = row.symbol.rsplit("::", 1)[1]
                sources["codex-rs/hepta-agentd/src/unregistered_evaluation.rs"] = (
                    f"fn unregistered(owner: &{row.receiver_type}) {{ owner.{method}(); }}"
                )
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, row, sources, ())
        self.assertTrue(all(value is False for value in self.manifest["authority"].values()))

    def test_cell_profile_journals_and_exact_plan_precede_execution(self):
        source = (ROOT / CELL).read_text()
        for marker in (
            "evaluation_profile.is_zero()",
            "Some(evaluation_profile.into_array())",
            "plan.require_journals(journals)?",
            "request.plan != &plan.product",
        ):
            with self.subTest(marker=marker):
                start = source.index("fn evaluate_or_readback<") if marker.startswith(("plan.", "request.")) else 0
                offset = source.index(marker, start)
                self.rejects(CELL, source[:offset] + source[offset + len(marker) :])

    def test_pending_signed_bytes_current_consumption_and_evaluator_are_required(self):
        source = (ROOT / PRODUCT).read_text()
        for marker in (
            "ProductEvaluationExecutionErrorV1::Pending",
            "if previous.is_some()",
            "authenticate(request, &signed, &signing_payload(&key, body))?",
            "if current.as_ref() != Some(&consumed)",
            "restored.execution_evaluator = Some(request.evaluator.clone())",
            "let now = (request.clock)()?",
            "verified.principal() != request.evaluator",
            "verified.objective_digest() != request.plan.frozen_plan.objective_digest",
        ):
            with self.subTest(marker=marker):
                self.rejects(PRODUCT, source.replace(marker, "", 1))

    def test_authentication_cannot_move_after_private_execution_decode(self):
        source = (ROOT / PRODUCT).read_text()
        marker = "authenticate(request, &signed, &signing_payload(&key, body))?;"
        changed = source.replace(marker, "", 1).replace(
            "if restored.candidate.plan_digest", marker + "if restored.candidate.plan_digest", 1
        )
        self.rejects(PRODUCT, changed)


if __name__ == "__main__":
    unittest.main()
