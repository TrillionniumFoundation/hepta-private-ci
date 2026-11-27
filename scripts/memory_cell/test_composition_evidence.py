"""Mechanism fixtures; not extra publisher annotations or independent evidence."""

from dataclasses import asdict
import json
import unittest

from composition_evidence import fact_root, make_case, parse_json, unpack, validate_row
from evidence_bundle import EvidenceBundle, EvidenceSpan
from native import Document, Question


def row():
    return dict(
        id="fixture",
        question=dict(
            stem="Where does the sample belong?",
            choices=[dict(label=c, text="choice " + c) for c in "ABCDEFGH"],
        ),
        fact1="The sample is 水.",
        fact2="水 belongs to class B.",
        combinedfact="The sample belongs to B.",
        answerKey="B",
    )


class CompositionEvidenceTests(unittest.TestCase):
    def test_original_multibyte_facts_and_missing_premise_are_not_relabelled(self):
        original = row()
        case, label = make_case(
            original, ["A distinct source."], "2026-10-10T00:00:00Z", "capability"
        )
        self.assertFalse(label["unanswerable"])
        self.assertEqual(label["answer"], "choice B")
        self.assertNotIn("combinedfact", case)
        self.assertNotIn("choices", case["question"])
        q = Question(**case["question"])
        docs = {
            d["identity"]: Document(**(d | {"assets": tuple(d["assets"])}))
            for d in case["originals"]
        }
        for condition in case["conditions"].values():
            value = condition["bundle"]
            bundle = EvidenceBundle(
                value["query_digest"],
                value["source_frontier"],
                tuple(EvidenceSpan(**s) for s in value["selected"]),
                value["mode"],
                value["rounds"],
            )
            bundle.validate(q, docs, frontier=case["frontier"], revoked=set())
            self.assertEqual(bundle.delivered(), condition["delivered_evidence"])
            self.assertFalse(condition["sufficient_context_certified"])
            self.assertTrue(condition["world_answerability_unchanged"])
        self.assertEqual(
            case["conditions"]["without_fact1"]["delivered_evidence"][0]["excerpt"],
            original["fact2"],
        )
        self.assertEqual(
            case["conditions"]["without_fact2"]["delivered_evidence"][0]["excerpt"],
            original["fact1"],
        )

    def test_answer_and_combination_changes_do_not_modify_reader_plan(self):
        source = row()
        a, _ = make_case(source, [], "2026-10-10T00:00:00Z", "capability")
        source.update(answerKey="H", combinedfact="deliberately different label")
        b, _ = make_case(source, [], "2026-10-10T00:00:00Z", "capability")
        self.assertEqual(a, b)

    def test_permutation_changes_order_not_source_identity(self):
        case, _ = make_case(
            row(),
            ["Unrelated one.", "Unrelated two."],
            "2026-10-10T00:00:00Z",
            "capability",
        )
        a = case["conditions"]["publisher_pair"]["bundle"]["selected"]
        b = case["conditions"]["pair_reversed"]["bundle"]["selected"]
        self.assertEqual(a, tuple(reversed(b)))
        for name in ("noise_before", "noise_after"):
            values = case["conditions"][name]["bundle"]["selected"]
            self.assertEqual(
                {s["source_id"] for s in values[:2] if s in a}
                | {s["source_id"] for s in values[2:] if s in a},
                {s["source_id"] for s in a},
            )

    def test_duplicate_facts_and_invalid_input_cannot_supply_fake_requirements(self):
        source = row()
        source["fact2"] = "  THE sample is 水. "
        with self.assertRaises(ValueError):
            validate_row(source)
        for payload in ('{"a":1,"a":2}', '{"a":NaN}'):
            with self.assertRaises(ValueError):
                parse_json(payload)
        with self.assertRaises(ValueError):
            unpack(b"not the original publisher archive")

    def test_revocation_still_applies_to_publisher_evidence(self):
        case, _ = make_case(row(), [], "2026-10-10T00:00:00Z", "capability")
        q = Question(**case["question"])
        source = Document(**(case["originals"][0] | {"assets": ()}))
        span = EvidenceSpan(
            **case["conditions"]["publisher_pair"]["bundle"]["selected"][0]
        )
        with self.assertRaises(ValueError):
            span.validate(source, q, {source.root})
        self.assertEqual(fact_root(source.content), fact_root(source.content.upper()))


if __name__ == "__main__":
    unittest.main()
