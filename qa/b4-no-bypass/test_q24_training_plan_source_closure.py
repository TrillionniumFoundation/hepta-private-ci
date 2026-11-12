"""Keep the Q24 row plan tied to original frozen scope and loaded material."""

from dataclasses import replace
import importlib.util
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "q24_training_plan_caller_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
AGENT = "codex-rs/hepta-agentd/src/"
PLAN = AGENT + "cell_composed_q24_training_plan.rs"
TRAINING = AGENT + "cell_composed_q24_training.rs"
PROFILE = AGENT + "authority_host_learning_profile.rs"
PREPARED = AGENT + "cell_q24_prepared_learning.rs"
CALLERS = {
    "learning_frozen_update_scope_constructor": (PROFILE, PLAN, PREPARED),
    "cell_q24_single_head_training_plan": (TRAINING, PREPARED),
    "cell_q24_single_head_candidate_validation": (),
}


class Q24TrainingPlanSourceClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {
            row.identifier: row for row in PROOF._boundary_rows(cls.manifest)
        }
        paths = {
            path
            for identifier in CALLERS
            for path in (
                cls.boundaries[identifier].definition_path,
                *cls.boundaries[identifier].product_callers,
            )
        }
        cls.sources = {
            path: PROOF._strip_cfg_test_items(
                PROOF._strip_rust_non_code((ROOT / path).read_text())
            )
            for path in paths
        }

    def rejects_source(self, changed):
        rows = [row for row in self.manifest["protected_file"] if row["path"] == PLAN]
        source = (ROOT / PLAN).read_text()
        self.assertNotEqual(source, changed)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / PLAN
            target.parent.mkdir(parents=True)
            target.write_text(source)
            manifest = {"protected_file": rows}
            PROOF._verify_protected_files(root, manifest)
            target.write_text(changed)
            with self.assertRaises(PROOF.VerificationFailure):
                PROOF._verify_protected_files(root, manifest)

    def rejects(self, function, marker):
        source = (ROOT / PLAN).read_text()
        start = source.index(function)
        end = PROOF._rust_item_end(PROOF._strip_rust_non_code(source), start)
        self.assertIsNotNone(end)
        assert end is not None
        body = source[start : end + 1]
        self.assertEqual(body.count(marker), 1, marker)
        offset = start + body.index(marker)
        self.rejects_source(source[:offset] + source[offset + len(marker) :])

    def test_scope_and_material_entrypoints_keep_exact_callers(self):
        for identifier, expected in CALLERS.items():
            with self.subTest(boundary=identifier):
                row = self.boundaries[identifier]
                self.assertEqual(row.product_callers, expected)
                PROOF._verify_boundary(ROOT, row, self.sources, ())
                if expected:
                    with self.assertRaises(PROOF.VerificationFailure):
                        PROOF._verify_boundary(
                            ROOT, replace(row, product_callers=()), self.sources, ()
                        )
                method = row.symbol.rsplit("::", 1)[-1]
                call = (
                    f"fn extra(plan: &{row.receiver_type}) {{ plan.{method}(); }}"
                    if row.receiver_type
                    else f"fn extra() {{ {row.symbol}(); }}"
                )
                sources = dict(self.sources)
                sources[AGENT + "unregistered_q24_plan.rs"] = call
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, row, sources, ())

    def test_rejection_guards_cannot_be_disabled_by_a_false_condition(self):
        source = (ROOT / PLAN).read_text()
        for guard in (
            "if optimizer_rule.is_zero()",
            "if coordinator.next_stage() != Some(LearningIterationStageV1::Training)",
            "if snapshot.request != self.prefix.request",
        ):
            with self.subTest(guard=guard):
                self.assertEqual(source.count(guard), 1)
                weakened = "if false && " + guard.removeprefix("if ")
                self.rejects_source(source.replace(guard, weakened, 1))

    def test_canonical_rule_keeps_baseline_row_and_nonzero_optimizer(self):
        for marker in (
            "optimizer_rule.is_zero()",
            "baseline.digest().map_err(LearningIterationError::from)?",
            "CellQ24PrivateHeadV1::Drive { index } => (1_u8, index)",
            "CellQ24PrivateHeadV1::Prediction { index } => (2_u8, index)",
            "bundle.as_array()",
            "&[tag]",
            "&index.to_le_bytes()",
            "optimizer_rule.as_array()",
        ):
            with self.subTest(marker=marker):
                self.rejects("fn cell_q24_single_head_update_rule_v1(", marker)

    def test_dataset_cut_cannot_omit_original_scope_or_loaded_baseline(self):
        for marker in (
            "LearningIterationCoordinatorV1::from_snapshot(snapshot.clone())?",
            "coordinator.next_stage() != Some(LearningIterationStageV1::Training)",
            "baseline.components() != &snapshot.request.selected_bundle.components",
            "index >= baseline.output_width()",
            "cell_q24_single_head_update_rule_v1(",
            "FrozenLearningScopeV2::freeze(",
            "LearningUpdateScopeV2::Cell",
            "if scope != expected",
            "scope.validate_snapshot(&snapshot)?",
        ):
            with self.subTest(marker=marker):
                self.rejects("fn from_dataset_cut(", marker)

    def test_training_requires_original_prefix_one_receipt_and_actual_bytes(self):
        for marker in (
            "LearningIterationCoordinatorV1::from_snapshot(snapshot.clone())?",
            "snapshot.request != self.prefix.request",
            "snapshot.owners != self.prefix.owners",
            "snapshot.receipts.len() != self.prefix.receipts.len() + 1",
            "!snapshot.receipts.starts_with(&self.prefix.receipts)",
            "coordinator.next_stage() != Some(LearningIterationStageV1::Evaluation)",
            "self.scope.validate_snapshot(snapshot)?",
            "LearningIterationObservationV1::Training",
            "candidate.components() != &bundle.components",
            ".validate_single_head_candidate(candidate, self.head)",
        ):
            with self.subTest(marker=marker):
                self.rejects("fn validate_training_candidate(", marker)

    def test_scope_checks_cannot_move_after_material_acceptance_or_hide(self):
        source = (ROOT / PLAN).read_text()
        check = "scope.validate_snapshot(&snapshot)?;"
        binding = "if scope != expected {"
        self.rejects_source(
            source.replace(check, "", 1).replace(binding, check + binding, 1)
        )
        check = "self.scope.validate_snapshot(snapshot)?;"
        self.rejects_source(
            source.replace(check, "", 1).replace(
                "Ok(self.baseline", check + "Ok(self.baseline", 1
            )
        )
        for replacement in (
            "if false { " + check + " }",
            "fn unused() { " + check + " }",
        ):
            with self.subTest(replacement=replacement):
                self.rejects_source(source.replace(check, replacement, 1))


if __name__ == "__main__":
    unittest.main()
