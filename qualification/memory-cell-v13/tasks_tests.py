"""Behavioral checks for execution, information isolation, and source chronology.

These checks never fit a model or choose a rule using held-out predictions.
"""

import copy
import unittest

import numpy as np

from baselines import BM25, Centroid, ExactStore, NearestExample, ProfileExactStore
from tasks import (SKILLS, canonical, execute, load_split, profile_input,
                   profile_journal, profile_learning_split, public_input,
                   resolve_profile, score_prediction)


class ExecutableSkillTests(unittest.TestCase):
    def test_order_and_count_are_distinct_real_operations(self):
        payload = ["10", "2", "10", "-3"]
        self.assertEqual(execute("unique_stable", payload), ["10", "2", "-3"])
        self.assertEqual(execute("sort_numeric", payload), ["-3", "2", "10", "10"])
        self.assertEqual(execute("count_items", payload), {"10": 2, "2": 1, "-3": 1})
        self.assertEqual(payload, ["10", "2", "10", "-3"])

    def test_unicode_contracts_preserve_their_differences(self):
        value = "Ａ e\u0301 ß"
        self.assertEqual(execute("normalize_nfc", value), "Ａ é ß")
        self.assertEqual(execute("normalize_nfkc", value), "A é ß")
        self.assertEqual(execute("casefold", value), "ａ e\u0301 ss")
        self.assertEqual(execute("collapse_whitespace", " \tKeep\u00a0CASE\n"), "Keep CASE")

    def test_csv_executes_quotes_and_embedded_newlines(self):
        rows = [["x,y", 'a"b', "line\nend"]]
        encoded = '"x,y","a""b","line\nend"\n'
        self.assertEqual(execute("csv_write", rows), encoded)
        self.assertEqual(execute("csv_parse", encoded), rows)

    def test_json_parse_differs_from_compact_text(self):
        text = ' { "z" : "a  b", "a" : [true, null] } '
        self.assertEqual(execute("json_parse", text), {"z": "a  b", "a": [True, None]})
        self.assertEqual(execute("json_compact", text), '{"z":"a  b","a":[true,null]}')

    def test_wrong_operation_runs_and_is_scored_as_failure(self):
        row = dict(payload=["9", "2", "9"], skill="sort_numeric",
                   expected=["2", "9", "9"])
        result = score_prediction(row, "unique_stable")
        self.assertEqual(result, dict(output=["9", "2"], error=None, correct=False,
                                     label_correct=False, predicted_skill="unique_stable"))
        self.assertFalse(score_prediction(row, "csv_parse")["correct"])
        self.assertFalse(score_prediction(row, None)["correct"])

    def test_public_input_is_independent_of_oracle_metadata(self):
        row = load_split("train")[0]
        adversarial = copy.deepcopy(row)
        adversarial.update(label=11, skill="json_compact", domain="different",
                           expected="fabricated answer", fixture_id="oracle leakage")
        self.assertEqual(public_input(row), public_input(adversarial))
        self.assertEqual(set(public_input(row)), {"text", "payload"})

    def test_training_goldens_are_not_executor_generated(self):
        for row in load_split("train") + load_split("calibration"):
            with self.subTest(id=row["id"]):
                self.assertEqual(canonical(execute(row["skill"], row["payload"])),
                                 canonical(row["expected"]))

    def test_rejects_bad_payloads_and_unknown_operations(self):
        for skill, value in (("missing", []), ("csv_write", ["flat"]),
                             ("sort_numeric", ["NaN"]), ("unique_stable", [1])):
            with self.subTest(skill=skill), self.assertRaises((TypeError, ValueError)):
                execute(skill, value)


class BaselineAndChronologyTests(unittest.TestCase):
    def setUp(self):
        self.rows = [dict(split="train", label=0, text="remove duplicate names", id="a"),
                     dict(split="train", label=1, text="sort numeric values", id="b")]
        self.features = np.asarray([[1.0, 0.0], [0.0, 1.0]])

    def test_baselines_share_training_only_admission(self):
        contaminated = self.rows + [dict(split="test", label=0, text="secret answer")]
        for constructor in (BM25, ExactStore):
            with self.assertRaises(ValueError):
                constructor(contaminated)
        for constructor in (NearestExample, Centroid):
            with self.assertRaises(ValueError):
                constructor(contaminated, np.ones((3, 2)))

    def test_reference_retrievers_use_the_actual_query(self):
        self.assertEqual(BM25(self.rows).predict("numeric sort")[0], 1)
        for constructor in (NearestExample, Centroid):
            model = constructor(self.rows, self.features)
            self.assertEqual(model.predict(np.asarray([0.1, 1.0]))[0], 1)
        exact = ExactStore(self.rows)
        self.assertEqual(exact.predict("REMOVE duplicate names"), (0, 1.0))
        self.assertEqual(exact.predict("discard repeats"), (None, 0.0))

    def test_future_corrections_do_not_leak_into_earlier_frontier(self):
        journal = profile_journal()
        early = resolve_profile(journal, "amber", 3)
        late = resolve_profile(journal, "amber", 4)
        self.assertEqual((early["revision"], early["operation_id"]), (1, "unique_stable"))
        self.assertEqual((late["revision"], late["operation_id"]), (2, "sort_numeric"))
        self.assertIsNone(resolve_profile(journal, "cobalt", 2))
        self.assertNotEqual(early["digest"], late["digest"])

    def test_profile_parameter_input_has_no_live_policy(self):
        old = profile_learning_split("train", 3)
        updated = profile_learning_split("train", 4)
        self.assertEqual([public_input(row) for row in old],
                         [public_input(row) for row in updated])
        self.assertNotEqual([row["label"] for row in old], [row["label"] for row in updated])
        self.assertEqual([row["label"] for row in old if row["project"] != "amber"],
                         [row["label"] for row in updated if row["project"] != "amber"])
        for row in old:
            self.assertNotIn("source_digest", public_input(row))
            self.assertNotIn(row["skill"], row["text"])
        self.assertIn("Current project rule:", profile_input(old[0], profile_journal())["text"])

    def test_exact_project_lookup_tracks_legal_observations(self):
        journal = profile_journal()
        first, second = ProfileExactStore(journal, 3), ProfileExactStore(journal, 4)
        query = "Process the amber project batch."
        self.assertEqual(first.predict(query)[0], SKILLS.index("unique_stable"))
        self.assertEqual(second.predict(query)[0], SKILLS.index("sort_numeric"))
        self.assertEqual(second.predict("An unknown project"), (None, 0.0))
        self.assertEqual(second.predict("amber and birch"), (None, 0.0))

    def test_profile_training_goldens_respect_each_source_revision(self):
        for frontier in (3, 4, 5, 6):
            for split in ("train", "calibration"):
                for row in profile_learning_split(split, frontier):
                    self.assertTrue(score_prediction(row, row["skill"])["correct"])


if __name__ == "__main__":
    unittest.main()
