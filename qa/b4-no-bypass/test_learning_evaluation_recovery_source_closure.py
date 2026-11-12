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
ORIGINAL = "codex-rs/hepta-agentd/src/neuron_cell_evaluation_original_observers.rs"
PRODUCT = "codex-rs/hepta-intelligence-eval/src/product_execution.rs"
OWNER = "codex-rs/hepta-agentd/src/neuron_cell_evaluation_receipt_owner.rs"
CALLERS = {
    "cell_original_evaluation_execution": (),
    "product_original_evaluation_execution": (CELL, ORIGINAL),
    "cell_completed_evaluation_readback": (OWNER,),
    "product_completed_evaluation_readback": (CELL, ORIGINAL),
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
            for path in (CELL, ORIGINAL, PRODUCT, OWNER)
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

    def test_root_observers_keep_both_physical_checks_and_the_original_runner(self):
        source = (ROOT / ORIGINAL).read_text()
        for function in ("fn evaluate_original(", "fn read_original_execution("):
            start = source.index(function)
            for marker in (
                "self.require_original_plan(plan)?;",
                "if request.plan != &plan.product",
                "let product: &mut ProductEvaluationRunnerV1<_> = &mut runner.product;",
                "let temporal = result.map_err(CellEvaluationErrorV1::Execution)?;",
            ):
                with self.subTest(function=function, marker=marker):
                    at = source.index(marker, start)
                    self.rejects(ORIGINAL, source[:at] + source[at + len(marker):])
                    self.rejects(ORIGINAL, source[:at] + "/*" + marker + "*/" + source[at + len(marker):])
            marker = "self.require_original_plan(plan)?;"
            at = source.index(marker, source.index(marker, start) + len(marker))
            self.rejects(ORIGINAL, source[:at] + source[at + len(marker):])

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

    def test_execution_context_keeps_canonical_original_owner_key_before_claim(self):
        source = (ROOT / PRODUCT).read_text()
        for function, marker in (
            ("fn execution_context(", ".read_consumption(&request.plan.frozen_plan)"),
            ("fn execution_context(", "product_evaluation_execution_key_v1(request.plan, namespace, request.evaluator)?"),
            ("fn product_evaluation_execution_key_v1(", "if namespace.is_zero()"),
            ("fn product_evaluation_execution_key_v1(", "evaluator\n        .validate(evaluator.authenticated_at)"),
            ("fn evaluate_or_readback_temporal_comparison<", "let (key, previous) = self.execution_context(request)?;"),
        ):
            with self.subTest(function=function, marker=marker):
                offset = source.index(marker, source.index(function))
                self.rejects(PRODUCT, source[:offset] + source[offset + len(marker) :])
        marker = "let key = product_evaluation_execution_key_v1(request.plan, namespace, request.evaluator)?;"
        self.rejects(PRODUCT, source.replace(marker, "if false {" + marker + "}", 1))

    def test_read_only_recovery_keeps_plan_journal_and_original_authentication(self):
        cases = {
            CELL: (
                "fn readback_completed(",
                (
                    "plan.require_journals(journals)?",
                    "if request.plan != &plan.product",
                    ".readback_temporal_comparison(request, executions)",
                    ".map_err(CellEvaluationErrorV1::Execution)?",
                ),
            ),
            PRODUCT: (
                "fn readback_temporal_comparison(",
                (
                    "let (key, _) = self.execution_context(request)?",
                    "executions.readback(&key)?",
                    "return Err(ProductEvaluationExecutionErrorV1::Pending)",
                    "self.authenticate_completed_execution(request, key, &bytes)",
                ),
            ),
        }
        for path, (function, markers) in cases.items():
            source = (ROOT / path).read_text()
            start = source.index(function)
            for marker in markers:
                with self.subTest(path=path, marker=marker):
                    offset = source.index(marker, start)
                    self.rejects(path, source[:offset] + source[offset + len(marker) :])

    def test_read_only_recovery_cannot_skip_checks_in_dead_blocks(self):
        for path, function, marker in (
            (CELL, "fn readback_completed(", "plan.require_journals(journals)?;"),
            (PRODUCT, "fn authenticate_completed_execution(", "authenticate(request, &signed, &signing_payload(&key, body))?;"),
        ):
            with self.subTest(path=path, function=function):
                source = (ROOT / path).read_text()
                offset = source.index(marker, source.index(function))
                changed = source[:offset] + "if false {" + marker + "}" + source[offset + len(marker) :]
                self.rejects(path, changed)


if __name__ == "__main__":
    unittest.main()
