"""Use pinned actual reader ZIPs; tests never fabricate a model success."""

from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import locomo_refusal_attribution as trial


ROOT = Path(os.environ.get("LOCOMO_FROZEN_ZIPS", "/mnt/data"))
FILES = {
    "public": ROOT / "locomo-public-original.zip",
    "decisions": ROOT / "locomo-retrieval-original.zip",
    "targets": ROOT / "locomo-targets-original.zip",
    "reader": ROOT / "locomo-qwen-32-original.zip",
    "score": ROOT / "locomo-qwen-hosted-scoring.zip",
}


class RefusalSensitivityTests(unittest.TestCase):
    def test_strict_refusal_never_silently_promoted(self):
        target = dict(unanswerable=True)
        self.assertEqual(trial.answer_f1(trial.REFUSAL, target), 1.0)
        answer = trial.REFUSAL + "\nHere is unrelated explanation."
        self.assertEqual(trial.answer_f1(answer, target), 0.0)
        self.assertEqual(
            trial.refusal_shape(answer),
            "canonical_prefix_plus_unreviewed_content",
        )
        self.assertEqual(
            trial.refusal_shape("I know the answer."), "not_canonical_refusal"
        )
        self.assertEqual(trial.refusal_shape(trial.REFUSAL), "strict_exact")

    def test_stable_original_token_f1_grammar(self):
        target = dict(unanswerable=False, answer="The Witcher 3")
        self.assertEqual(trial.answer_f1("witcher 3 [E1]", target), 1.0)
        self.assertEqual(trial.answer_f1("different answer", target), 0.0)
        self.assertEqual(trial.normalize("The [E2] Witcher, 3!"), "witcher 3")

    def test_duplicate_json_and_nonfinite_fail(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            trial.strict_json('{"a":1,"a":2}')
        with self.assertRaisesRegex(ValueError, "nonfinite"):
            trial.strict_json('{"a":NaN}')
        with self.assertRaises(ValueError):
            trial._rows(b'{"x":1}\n\n', max_rows=2)

    def test_source_provenance_requires_exact_outer_zip(self):
        if not FILES["reader"].exists():
            self.skipTest("exact original ZIPs are only staged in opt-in hosted replay")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "changed.zip"
            raw = FILES["reader"].read_bytes()
            path.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
            with self.assertRaisesRegex(ValueError, "ZIP SHA256"):
                trial.checked_zip(path, trial.EXPECTED_ZIPS["reader"])

    def test_all_original_32_answers_reproduce_hosted_metric(self):
        if not all(p.is_file() for p in FILES.values()):
            self.skipTest("no real original ZIP fixture on this host")
        record = trial.audit(FILES)
        self.assertEqual(record["original_model_runs"], 32)
        self.assertEqual(record["source_family_proxies"], 2)
        self.assertAlmostEqual(
            record["by_arm"]["lexical_k4"]["original_official"]["mean_f1"],
            0.17208258098192508,
        )
        self.assertAlmostEqual(
            record["by_arm"]["lexical_k8"]["original_official"]["mean_f1"],
            0.11148190095003518,
        )
        self.assertAlmostEqual(
            record["exact_registered_k8_minus_k4_f1"], -0.060600680031889904
        )
        self.assertEqual(record["by_arm"]["lexical_k4"]["refusal_strict_exact"], 1)
        self.assertEqual(
            record["by_arm"]["lexical_k4"][
                "refusal_prefix_with_extra_unreviewed_content"
            ],
            2,
        )
        self.assertEqual(record["by_arm"]["lexical_k8"]["refusal_strict_exact"], 0)
        self.assertEqual(
            record["by_arm"]["lexical_k8"][
                "refusal_prefix_with_extra_unreviewed_content"
            ],
            3,
        )
        self.assertAlmostEqual(
            record["sensitivity_prefix_refusal_k8_minus_k4_f1"], 0.0018993199681101025
        )
        self.assertFalse(record["retrieval_policy_promotion_qualified"])
        self.assertIsNone(record["semantic_citation_precision"])

    def test_publisher_support_strata_and_no_answer_leak_in_report(self):
        if not all(p.is_file() for p in FILES.values()):
            self.skipTest("no real original ZIP fixture on this host")
        record = trial.audit(FILES)
        a, b = record["by_arm"]["lexical_k4"], record["by_arm"]["lexical_k8"]
        self.assertEqual(a["cohorts"]["publisher_support_all_retrieved"]["planned"], 8)
        self.assertEqual(b["cohorts"]["publisher_support_all_retrieved"]["planned"], 9)
        self.assertEqual(
            record["paired_support_cohorts"]["additional_support_retrieved_by_k8"][
                "questions"
            ],
            1,
        )
        self.assertEqual(
            record["paired_support_cohorts"]["unanswerable"]["questions"], 3
        )
        self.assertEqual(
            record["paired_support_cohorts"]["support_retrieved_by_both"]["questions"],
            8,
        )
        self.assertEqual(
            record["paired_support_cohorts"]["support_missing_both"]["questions"], 4
        )
        self.assertNotIn("The Witcher 3", json.dumps(record))
        self.assertFalse(record["production_accepted"])

    def test_target_zip_is_opened_after_unedited_source_and_reader_checks(self):
        if not all(p.is_file() for p in FILES.values()):
            self.skipTest("original hosted artifact ZIPs missing")
        original = trial.checked_zip
        calls = []

        def traced(path, pin):
            label = next(key for key, value in FILES.items() if value == path)
            calls.append(label)
            return original(path, pin)

        with patch.object(trial, "checked_zip", side_effect=traced):
            trial._originals(FILES)
        self.assertEqual(calls[-1], "targets")
        self.assertEqual(set(calls), set(FILES))

    def test_stable_serialization_never_relabels_boolean_as_numeric(self):
        value = dict(original=0.20413421589842135, qualified=False)
        stable = trial.stable_wire_numbers(value)
        self.assertEqual(stable["original"], 0.204134215898)
        self.assertIs(stable["qualified"], False)
        self.assertEqual(
            trial.stable_wire_numbers(dict(v=[0.17208258098192508])),
            dict(v=[0.172082580982]),
        )

    def test_fake_score_or_mutated_generation_cannot_pass(self):
        if not all(p.is_file() for p in FILES.values()):
            self.skipTest("original hosted artifact ZIPs missing")
        questions, docs, decisions, rows, targets, hosted = trial._originals(FILES)
        fake = deepcopy(hosted)
        fake["arms"]["lexical_k4"]["diagnostic_f1"] = 1.0
        with self.assertRaisesRegex(ValueError, "hosted original reference"):
            trial.compute(questions, rows, targets, fake)
        changed = deepcopy(rows)
        changed[0]["answer"] += " unrelated appended assertion"
        with self.assertRaisesRegex(
            ValueError, "hosted original reference|original preregistered"
        ):
            trial.compute(questions, changed, targets, hosted)


if __name__ == "__main__":
    unittest.main()
