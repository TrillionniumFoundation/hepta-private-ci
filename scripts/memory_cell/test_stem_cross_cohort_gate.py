"""No-go decision uses pinned original bytes, not fabricated independent tasks."""

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from stem_cross_cohort_gate import (
    PINS,
    pinned_inputs,
    audit_receipts,
    strict_json,
)

ROOT = Path(__file__).parent / "data"
NAMES = tuple(PINS)


def fixture():
    documents, receipt = pinned_inputs(ROOT)
    return [documents[name] for name in NAMES], receipt


class CrossCohortGateTests(unittest.TestCase):
    def test_real_git_blob_pins_and_negative_gate(self):
        (locomo, stem, rag), receipts = fixture()
        result = audit_receipts(locomo, stem, rag)
        self.assertEqual(result["locomo"]["native_support_evaluable_questions"], 13)
        self.assertEqual(result["locomo"]["source_coverage_selected"], 9)
        self.assertEqual(result["locomo"]["source_coverage_fixed_k4"], 8)
        self.assertEqual(
            result["locomo"]["incremental_k8_minus_k4_source_utf8_bytes"], 8449
        )
        self.assertEqual(
            result["strict_native_stem"]["distinct_test_transfer_questions"], 16
        )
        self.assertEqual(
            result["strict_native_stem"]["learned_arms_with_proven_test_transfer_gain"],
            0,
        )
        self.assertEqual(
            result["authored_strong_rag"]["correct_tasks_for_organized_path"], 8
        )
        self.assertEqual(
            result["authored_strong_rag"]["complete_declared_citation_chain_both"], 4
        )
        self.assertFalse(result["production_accepted"])
        self.assertTrue(result["do_not_pool_cross_benchmark_denominators"])
        self.assertEqual(
            {x["git_blob_sha1"] for x in receipts.values()}, set(PINS.values())
        )

    def test_single_byte_mutation_of_any_source_fails_before_metrics(self):
        for name in NAMES:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                for source in NAMES:
                    raw = (ROOT / source).read_bytes()
                    if source == name:
                        raw += b" "
                    (base / source).write_bytes(raw)
                with self.assertRaisesRegex(ValueError, "pinned historical Git blob"):
                    pinned_inputs(base)

    def test_symlink_source_and_empty_document_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            for source in NAMES:
                (base / source).write_bytes((ROOT / source).read_bytes())
            (base / NAMES[0]).unlink()
            (base / NAMES[0]).symlink_to(ROOT / NAMES[0])
            with self.assertRaisesRegex(ValueError, "non-symlink"):
                pinned_inputs(base)
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            for source in NAMES:
                (base / source).write_bytes((ROOT / source).read_bytes())
            (base / NAMES[0]).write_bytes(b"")
            with self.assertRaisesRegex(ValueError, "regular"):
                pinned_inputs(base)

    def test_duplicate_json_and_nonfinite_not_silently_parsed(self):
        for invalid in (b'{"a":1,"a":2}', b'{"metric":NaN}', b'{"x":Infinity}'):
            with self.subTest(data=invalid), self.assertRaises(ValueError):
                strict_json(invalid)

    def test_lookahead_or_borrowed_labels_cannot_be_promoted(self):
        (locomo, stem, rag), _ = fixture()
        for key, invalid in (
            ("models_generated", 1),
            ("selected_arm", "fusion_k8"),
            ("independent_source_family_authentication", True),
            ("production_accepted", True),
        ):
            changed = deepcopy(locomo)
            changed[key] = invalid
            with self.subTest(key=key), self.assertRaises(ValueError):
                audit_receipts(changed, stem, rag)

    def test_repeated_stem_checkpoints_not_unique_tasks_or_gains(self):
        (locomo, stem, rag), _ = fixture()
        for key, invalid in (
            ("test_and_transfer_unique_questions_per_checkpoint", 48),
            ("test_and_transfer_repeated_stage_pairs_per_learned_arm", 16),
            ("heldout_development_source_selection_wins_per_arm", 1),
            ("semantic_citation_precision_certified", True),
        ):
            altered = deepcopy(stem)
            altered[key] = invalid
            with self.subTest(key=key), self.assertRaises(ValueError):
                audit_receipts(locomo, altered, rag)

    def test_reader_citation_and_run_independence_not_fabricated(self):
        (locomo, stem, rag), _ = fixture()
        for field, invalid in (
            ("independent_new_source_families", 2),
            ("independent_semantic_citation_adjudication", True),
            ("repeated_questions_are_independent", True),
            ("production_accepted", True),
            ("source_runs", 32),
        ):
            altered = deepcopy(rag)
            altered[field] = invalid
            with self.subTest(field=field), self.assertRaises(ValueError):
                audit_receipts(locomo, stem, altered)

    def test_source_coverage_mismatch_cannot_be_relabelled(self):
        (locomo, stem, rag), _ = fixture()
        altered = deepcopy(locomo)
        altered["evaluation"]["lexical_k8"]["full_annotated_support_covered"] = 10
        with self.assertRaises(ValueError):
            audit_receipts(altered, stem, rag)
        altered = deepcopy(locomo)
        first = next(iter(altered["evaluation"]["lexical_k8"]["per_family"]))
        altered["evaluation"]["lexical_k8"]["per_family"][first]["eligible"] -= 1
        with self.assertRaisesRegex(ValueError, "denominator"):
            audit_receipts(altered, stem, rag)


if __name__ == "__main__":
    unittest.main()
