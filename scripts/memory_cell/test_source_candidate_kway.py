"""Source-lexicon controls; authored likelihoods are never model results."""

import copy
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from source_candidate_kway import ARMS, probe, roster, summarize


def examples():
    return [
        dict(query=dict(identity=f"q{i}", scope="family1", content="which value"), target=v)
        for i, v in enumerate(("id_a", "id_b", "id_c"))
    ]


def rows(cases):
    from native import digest

    result = []
    for case in cases:
        for arm in ARMS:
            for value in case["candidates"]:
                result.append(
                    dict(
                        question_id=case["query"]["identity"],
                        actual_reader_question_id="paraphrase",
                        scope=case["scope"],
                        arm=arm,
                        candidate_digest=digest(value),
                        prompt_digest="prompt",
                        reader_profile="frozen",
                        delivered_evidence=[],
                        status="succeeded",
                        mean_nll=(
                            0.1
                            if value == ("id_a" if arm == "base" else case["target"])
                            else 1.0
                        ),
                        seconds=0.1,
                        input_tokens=24,
                        supervised_tokens=2,
                    )
                )
    return result


class KwayTests(unittest.TestCase):
    def test_full_scope_without_gold_driven_topk(self):
        cases, excluded = roster(examples(), maximum_questions=2)
        self.assertEqual(len(cases), 2)
        self.assertEqual(excluded, ())
        self.assertTrue(
            all(c["candidates"] == ("id_a", "id_b", "id_c") for c in cases)
        )
        inverted, _ = roster(list(reversed(examples())), maximum_questions=2)
        self.assertEqual(cases, inverted)

    def test_entire_scope_over_budget_is_not_truncated_to_answer(self):
        source = [
            dict(
                query=dict(identity=f"q{i}", scope="family1", content="q"),
                target=f"v{i:02d}",
            )
            for i in range(17)
        ]
        cases, excluded = roster(source)
        self.assertEqual(cases, ())
        self.assertEqual(excluded[0]["candidate_count"], 17)

    def test_candidate_list_is_nonparametric_not_a_model_gain(self):
        cases, _ = roster(examples())
        result = summarize(rows(cases), cases)
        self.assertEqual((result["memory_wins"], result["memory_losses"]), (1, 0))
        self.assertTrue(result["lexicon_from_source_not_parameters"])
        self.assertFalse(result["production_accepted"])
        self.assertIsNone(result["downstream_task_success"])
        self.assertEqual(result["complete_base_adapter_questions"], 2)

    def test_failures_preserve_complete_denominator_and_bounds(self):
        cases, _ = roster(examples())
        data = rows(cases)
        data[0].update(status="failed", error_type="TimeoutError")
        for key in ("mean_nll", "seconds", "input_tokens", "supervised_tokens"):
            data[0].pop(key)
        result = summarize(data, cases)
        self.assertEqual(result["complete_base_adapter_questions"], 1)
        self.assertEqual(result["missing_question_pairs"], 1)
        self.assertEqual(result["all_planned_effect_bounds"], [0.0, 1.0])

    def test_duplicates_input_drift_and_forged_scores_rejected(self):
        cases, _ = roster(examples())
        for key, value in (
            ("prompt_digest", "drift"),
            ("reader_profile", "different"),
            ("actual_reader_question_id", "different"),
            ("delivered_evidence", ["leaked"]),
            ("mean_nll", float("nan")),
            ("supervised_tokens", True),
        ):
            data = rows(cases)
            data[0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                summarize(data, cases)
        data = rows(cases)
        data[-1] = copy.deepcopy(data[0])
        with self.assertRaises(ValueError):
            summarize(data, cases)

    def test_invalid_ambiguous_or_duplicate_source_query_reject(self):
        for sample in (
            [],
            examples() + [examples()[0]],
            examples()[:1]
            + [dict(query=dict(identity="x", scope="s", content=""), target="v")],
        ):
            with self.assertRaises(ValueError):
                roster(sample)


class DiskProbeTests(unittest.TestCase):
    def test_original_sources_only_raw_before_scoring(self):
        from native import digest

        class Question:
            identity = "other_question"
            content = "no evidence question"

        class Reader:
            roots = {"root"}
            scopes = {"family1"}
            profile = "pinned-frozen-reader"
            tokenizer = object()

            def verify_frozen(self):
                self.checked = True

        class Document:
            root = "root"
            scope = "family1"

        def validate_score(item, prefix):
            self.assertEqual(item["input_tokens"], prefix + item["supervised_tokens"])

        modules = dict(
            experience_memory=types.SimpleNamespace(
                render=lambda tokenizer, q, evidence, derived: [1, 2, 3, 4],
                source_examples=lambda docs, **kwargs: (examples(), []),
            ),
            source_paraphrase_probe=types.SimpleNamespace(
                paraphrase_writer_question=lambda entry: Question(),
            ),
            source_recall_likelihood=types.SimpleNamespace(
                _valid_score=validate_score,
                conditional_nll=lambda *args: None,
            ),
        )
        reader = Reader()
        with tempfile.TemporaryDirectory() as dirname, patch.dict(sys.modules, modules):
            output = Path(dirname) / "out"
            observed = []

            def score(reader, ids, text, arm):
                self.assertEqual(ids, [1, 2, 3, 4])
                observed.append((text, arm))
                return dict(
                    mean_nll=0.4, seconds=0.02, input_tokens=6, supervised_tokens=2
                )

            report = probe(
                reader,
                [Document()],
                output,
                ready_sha="a" * 64,
                writer_source="b" * 40,
                source_commit="c" * 40,
                scorer=score,
            )
            self.assertTrue(reader.checked)
            self.assertEqual(report["planned_model_calls"], 12)
            self.assertEqual(len(observed), 12)
            self.assertEqual(report["completed_model_calls"], 12)
            plan = json.loads((output / "plan.json").read_text())
            self.assertTrue(
                all(
                    item["lexicon_digests"]
                    == [digest(v) for v in ("id_a", "id_b", "id_c")]
                    for item in plan["comparisons"]
                )
            )
            self.assertNotIn("correct_value_digest", (output / "plan.json").read_text())
            self.assertFalse(report["production_accepted"])
            self.assertTrue((output / "raw-likelihoods.jsonl").is_file())


if __name__ == "__main__":
    unittest.main()
