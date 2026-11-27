"""Exercise the current v2 holdout guards with the original source verifier."""

import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "fenced_holdout_v2_envelope_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
OWNER = "codex-rs/hepta-intelligence-eval/src/fenced_holdout.rs"
JOURNAL = (
    "HoldoutJournalV2::from_snapshot_with_record_limit(current.journal, MAX_RECORDS)"
)
FIND = (
    "let Some(record) = journal.records().iter().find(|record| match &record.plan {\n"
    "            HoldoutPlanEnvelopeV2::CrossFold(stored) => stored.plan_id == plan.plan_id,\n"
    "            HoldoutPlanEnvelopeV2::Paired(stored) => stored.spec().plan_id == plan.plan_id,\n"
    "        }) else {\n"
    "            return Ok((self.binding, None));\n"
    "        };"
)
TUPLE = (
    "let (\n"
    "            HoldoutPlanEnvelopeV2::CrossFold(stored_plan),\n"
    "            HoldoutUseEnvelopeV2::CrossFold(stored_use),\n"
    "        ) = (&record.plan, &record.use_receipt)\n"
    "        else {\n"
    "            return Err(FencedHoldoutError::Binding);\n"
    "        };"
)
PLAN = (
    "if stored_plan.as_ref() != plan {\n"
    "            return Err(FencedHoldoutError::Binding);\n"
    "        }"
)
SNAPSHOT = (
    "if journal.snapshot() != self.journal.snapshot() {\n"
    "            return Err(FencedHoldoutError::Corrupt);\n"
    "        }"
)
USE = "use_receipt: stored_use.as_ref().clone()"


class FencedHoldoutV2EnvelopeSourceClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        manifest = PROOF._load_manifest(ROOT / "CALLERS.toml")
        rows = [row for row in manifest["protected_file"] if row["path"] == OWNER]
        assert len(rows) == 1
        cls.manifest = {"protected_file": rows}
        cls.source = (ROOT / OWNER).read_text()

    def rejects(self, original, changed):
        self.assertEqual(self.source.count(original), 1, original)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / OWNER
            target.parent.mkdir(parents=True)
            target.write_text(self.source)
            PROOF._verify_protected_files(root, self.manifest)
            target.write_text(
                self.source.replace(original, changed, 1)
                + "\n/* Removed guard is only a comment:\n"
                + original
                + "\n*/\n"
            )
            with self.assertRaises(PROOF.VerificationFailure):
                PROOF._verify_protected_files(root, self.manifest)

    def test_actual_current_v2_source_passes(self):
        PROOF._verify_protected_files(ROOT, self.manifest)

    def test_bounded_current_snapshot_is_required(self):
        for changed in (
            JOURNAL.replace("HoldoutJournalV2", "FinalHoldoutJournalV1"),
            JOURNAL.replace("current.journal", "self.journal.snapshot()"),
            JOURNAL.replace("MAX_RECORDS", "MAX_RECORDS + 1"),
            JOURNAL.replace("from_snapshot_with_record_limit", "from_snapshot"),
        ):
            with self.subTest(replacement=changed):
                self.rejects(JOURNAL, changed)

    def test_both_variant_plan_ids_select_the_original_record(self):
        for changed in (
            FIND.replace(
                "stored.plan_id == plan.plan_id", "stored.plan_id != plan.plan_id"
            ),
            FIND.replace(
                "stored.spec().plan_id == plan.plan_id",
                "stored.spec().plan_id != plan.plan_id",
            ),
            FIND.replace("plan.plan_id", "other_plan.plan_id"),
            FIND.replace("journal.records()", "self.journal.records()"),
            FIND.replace(
                "HoldoutPlanEnvelopeV2::Paired(stored) => stored.spec().plan_id == plan.plan_id,",
                "_ => false,",
            ),
        ):
            with self.subTest(replacement=changed):
                self.rejects(FIND, changed)

    def test_empty_lookup_keeps_original_binding_and_none(self):
        for changed in (
            FIND.replace("Ok((self.binding, None))", "Ok((Digest32::ZERO, None))"),
            FIND.replace(
                "Ok((self.binding, None))", "Err(FencedHoldoutError::Binding)"
            ),
            FIND.replace("return Ok", "let ignored = Ok"),
        ):
            with self.subTest(replacement=changed):
                self.rejects(FIND, changed)

    def test_record_selection_executes_in_current_top_level_function(self):
        for changed in (
            "if false {\n" + FIND + "\n}",
            "fn unused() {\n" + FIND + "\n}",
        ):
            with self.subTest(replacement=changed):
                self.rejects(FIND, changed)

    def test_plan_and_use_share_cross_fold_variant_and_record(self):
        for changed in (
            TUPLE.replace(
                "HoldoutPlanEnvelopeV2::CrossFold", "HoldoutPlanEnvelopeV2::Paired"
            ),
            TUPLE.replace(
                "HoldoutUseEnvelopeV2::CrossFold", "HoldoutUseEnvelopeV2::Paired"
            ),
            TUPLE.replace("&record.plan", "&other.plan"),
            TUPLE.replace("&record.use_receipt", "&other.use_receipt"),
            TUPLE.replace(
                "HoldoutUseEnvelopeV2::CrossFold(stored_use)",
                "stored_use",
            ),
        ):
            with self.subTest(replacement=changed):
                self.rejects(TUPLE, changed)

    def test_variant_mismatch_must_return_binding(self):
        for changed in (
            TUPLE.replace("FencedHoldoutError::Binding", "FencedHoldoutError::Corrupt"),
            TUPLE.replace("return Err", "let ignored = Err"),
            TUPLE.replace(
                "return Err(FencedHoldoutError::Binding);",
                "return Ok((self.binding, None));",
            ),
        ):
            with self.subTest(replacement=changed):
                self.rejects(TUPLE, changed)

    def test_tuple_guard_cannot_be_inert_or_only_declared(self):
        for changed in (
            "",
            "if false {\n" + TUPLE + "\n}",
            "fn unused() {\n" + TUPLE + "\n}",
        ):
            with self.subTest(replacement=changed):
                self.rejects(TUPLE, changed)

    def test_complete_stored_plan_must_match_input(self):
        for changed in (
            PLAN.replace("!=", "=="),
            PLAN.replace(
                "stored_plan.as_ref() != plan", "stored_plan.plan_id != plan.plan_id"
            ),
            PLAN.replace("stored_plan.as_ref()", "other_plan.as_ref()"),
            PLAN.replace("!= plan", "!= other_plan"),
            "if false {\n" + PLAN + "\n}",
        ):
            with self.subTest(replacement=changed):
                self.rejects(PLAN, changed)

    def test_plan_mismatch_must_return_binding(self):
        for changed in (
            "",
            PLAN.replace("return Err", "let ignored = Err"),
            PLAN.replace("FencedHoldoutError::Binding", "FencedHoldoutError::Corrupt"),
            PLAN.replace(
                "return Err(FencedHoldoutError::Binding);",
                "return Ok((self.binding, None));",
            ),
        ):
            with self.subTest(replacement=changed):
                self.rejects(PLAN, changed)

    def test_selection_precedes_tuple_and_plan_validation(self):
        span = FIND + "\n        " + TUPLE + "\n        " + PLAN
        for changed in (
            TUPLE + "\n        " + FIND + "\n        " + PLAN,
            FIND + "\n        " + PLAN + "\n        " + TUPLE,
        ):
            with self.subTest(replacement=changed):
                self.rejects(span, changed)

    def test_snapshot_guard_precedes_envelope_selection(self):
        span = SNAPSHOT + "\n        " + FIND
        self.rejects(span, FIND + "\n        " + SNAPSHOT)

    def test_receipt_uses_the_matched_cross_fold_use(self):
        for changed in (
            "use_receipt: record.use_receipt.clone()",
            "use_receipt: other_use.as_ref().clone()",
            "use_receipt: stored_use.clone()",
        ):
            with self.subTest(replacement=changed):
                self.rejects(USE, changed)


if __name__ == "__main__":
    unittest.main()
