"""Authored unit fixtures, never reported as independently reviewed examples."""

import copy
import unittest

from necessity_data import (
    HEADER,
    LIMITS,
    decision,
    make_case,
    parse_chains,
    select,
    verified_chains,
    verified_questions,
)
from native import digest


def fixture(i=0):
    q = dict(
        id=str(i),
        question=dict(
            stem=f"What links item{i}?",
            choices=[
                dict(label=k, text=f"answer{i}" if k == "A" else f"other{i}{k}")
                for k in "ABCD"
            ],
        ),
        answerKey="A",
    )
    cells = [
        str(i),
        "1",
        "test",
        q["question"]["stem"],
        f"answer{i}",
        f"item{i} needs bridge{i}",
        f"bridge{i} yields answer{i}",
        "1.0",
        "yes",
        "yes yes yes",
        "NIL",
        f"item{i} yields answer{i}",
    ]
    raw = (HEADER + "\n" + "\t".join(cells) + "\n").encode()
    return parse_chains(raw)[0], q


class NecessityDataTests(unittest.TestCase):
    def test_unknown_single_fact_and_disagreement_are_not_two_fact_support(self):
        record, q = fixture()
        self.assertEqual(
            decision(record, {q["id"]: q}), "eligible_published_unanimous_claim"
        )
        for aggregate, votes in (
            ("fact1", "fact1 fact1 yes"),
            ("yes", "yes yes no"),
            ("yes", "yes yes"),
            ("?", "yes no"),
            ("no", "yes yes yes"),
        ):
            changed = copy.deepcopy(record)
            changed["row"].update(Turk=aggregate, Turks=votes)
            self.assertEqual(
                decision(changed, {q["id"]: q}), "not_unanimous_two_fact_judgement"
            )

    def test_extra_fact_and_original_join_mismatch_stay_excluded(self):
        record, q = fixture()
        for field, value, expected in (
            ("Extra Facts", "missing premise", "unprovided_extra_requirement"),
            ("Question", "wrong", "original_question_mismatch"),
            ("Answer", "wrong", "original_answer_mismatch"),
            ("Fact2", record["row"]["Fact1"], "identical_facts_not_two_requirements"),
        ):
            changed = copy.deepcopy(record)
            changed["row"][field] = value
            self.assertEqual(decision(changed, {q["id"]: q}), expected)

    def test_pins_and_duplicate_rows_fail(self):
        for function in (verified_chains, verified_questions):
            with self.assertRaises(ValueError):
                function(b"replacement")
        record, _ = fixture()
        row = "\t".join(record["row"][k] for k in HEADER.split("\t"))
        with self.assertRaises(ValueError):
            parse_chains((HEADER + "\n" + row + "\n" + row).encode())

    def test_frozen_census_and_shared_source_coalescing(self):
        records, questions = [], {}
        for i in range(sum(LIMITS.values()) + 2):
            r, q = fixture(i)
            records.append(r)
            questions[q["id"]] = q
        selected, dispositions, census = select(records, questions)
        again, _, _ = select(tuple(reversed(records)), questions)
        self.assertEqual(selected, again)
        self.assertEqual({p: len(v) for p, v in selected.items()}, LIMITS)
        self.assertEqual(len(dispositions), len(records))
        records[1]["row"]["Fact1"] = records[0]["row"]["Fact1"]
        _, _, coalesced = select(records, questions)
        self.assertEqual(
            coalesced["unanimous_components"], census["unanimous_components"] - 1
        )
        missing, rows, _ = select(records[:3], questions)
        self.assertIsNone(missing)
        self.assertEqual(len(rows), 3)

    def test_question_options_preserved_but_key_and_votes_not_model_inputs(self):
        record, q = fixture()
        record["family"] = "fixture"
        case, label = make_case(record, q, ["noise"], "2026-01-01T00:00:00Z", "train")
        poisoned = copy.deepcopy(q)
        poisoned["answerKey"] = "B"
        other, _ = make_case(
            record, poisoned, ["noise"], "2026-01-01T00:00:00Z", "train"
        )
        self.assertEqual(case, other)
        for choice in q["question"]["choices"]:
            self.assertIn(
                f"({choice['label']}) {choice['text']}", case["question"]["content"]
            )
        self.assertIsNone(label["reviewed_at"])
        self.assertNotIn("yes yes yes", case["question"]["content"])
        full = case["conditions"]["publisher_pair"]
        a = case["conditions"]["without_fact1"]
        b = case["conditions"]["without_fact2"]
        self.assertEqual(len(full["bundle"]["selected"]), 2)
        self.assertEqual(a["bundle"]["selected"], full["bundle"]["selected"][1:])
        self.assertEqual(b["bundle"]["selected"], full["bundle"]["selected"][:1])
        self.assertTrue(a["world_answerability_unchanged"])
        self.assertFalse(full["sufficient_context_certified"])
        self.assertEqual(case["frontier"], digest(case["originals"]))


if __name__ == "__main__":
    unittest.main()
