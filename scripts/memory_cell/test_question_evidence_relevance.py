"""Pure TRAIN-manipulation fixtures, never independent semantic labels."""
from copy import deepcopy
import unittest
import five_causal_experiments as c
import question_evidence_relevance as r


def examples():
    rows = []
    for i in range(4):
        request = {"question": f"What is item {i}?", "options": [], "evidence": [
            {"id": "E"+str(i), "text": f"Source {i}: fact {i}.", "modality": "text",
             "position": 0, "asset_sha256": None}]}
        for kind in ("annotated_answer", "empty_refusal"):
            rows.append({"id": c.digest([i, kind]), "question_id": c.digest(f"raw{i}"),
                "family": f"family{i}", "split": "train", "source_sha256": "a"*64,
                "kind": kind, "request": deepcopy(request) if kind == "annotated_answer" else request | {"evidence": []},
                "response": f"fact {i} [E{i}]" if kind == "annotated_answer" else r.REFUSAL})
    return rows


class PlanTests(unittest.TestCase):
    def test_same_nonempty_sources_different_questions(self):
        plan = r.build_plan(examples())
        self.assertEqual(plan["available_extra_pairs"], 4)
        for unit in plan["units"]:
            rows = r.extra_examples(unit, r.ALIGNED)
            self.assertEqual(rows[0]["request"]["evidence"], rows[2]["request"]["evidence"])
            self.assertNotEqual(rows[0]["request"]["question"], rows[2]["request"]["question"])
            self.assertEqual(rows[0]["response"], rows[2]["response"])
            self.assertEqual(rows[1]["response"], rows[3]["response"])

    def test_input_not_modified(self):
        data = examples(); before = deepcopy(data)
        plan = r.build_plan(data)
        r.extra_examples(plan["units"][0], r.REPEAT_EMPTY)
        self.assertEqual(data, before)
        self.assertTrue(plan["units"][0]["mismatched_request"]["evidence"])

    def test_empty_control_changes_only_mismatched_evidence(self):
        unit = r.build_plan(examples())["units"][0]
        a, b = r.extra_examples(unit, r.ALIGNED), r.extra_examples(unit, r.REPEAT_EMPTY)
        self.assertEqual(a[:2], b[:2])
        for x, y in zip(a[2:], b[2:]):
            self.assertEqual(x["response"], y["response"])
            self.assertEqual(x["request"] | {"evidence": []}, y["request"])

    def test_reversed_keeps_exact_inputs_and_target_multiset(self):
        unit = r.build_plan(examples())["units"][0]
        self.assertEqual(r.extra_examples(unit, r.ALIGNED), r.extra_examples(unit, r.REVERSED))
        self.assertEqual(r.directions(r.REVERSED), ((1, 0), (2, 3)))

    def test_target_partitions_cannot_enter_train(self):
        for split in ("select", "test", "confirmation"):
            data = examples(); data[0]["split"] = split
            with self.assertRaises(c.Invalid): r.build_plan(data)

    def test_forbidden_family(self):
        with self.assertRaises(c.Invalid): r.build_plan(examples(), ["family0"])

    def test_duplicate_or_missing_original_pair(self):
        for data in (examples()+[examples()[0]], examples()[:-1]):
            with self.assertRaises(c.Invalid): r.build_plan(data)

    def test_source_pin_not_mixed(self):
        data = examples(); data[0]["source_sha256"] = "b"*64
        with self.assertRaises(c.Invalid): r.build_plan(data)

    def test_exact_suffix_preserves_bracketed_body(self):
        data = examples(); data[0]["response"] = "[not] fact [E0]"
        plan = r.build_plan(data)
        # Directly force the only donor, retaining bracketed target content.
        plan = r.build_plan(data[:4])
        self.assertTrue(any(x["donor_response"] == "[not] fact [S1]" for x in plan["units"]))

    def test_wrong_suffix_or_empty_answer_not_repaired(self):
        for text in ("fact [invented]", " [E0]", r.REFUSAL+" [E0]"):
            data = examples(); data[0]["response"] = text
            with self.assertRaises(c.Invalid): r.build_plan(data)

    def test_unavailable_donor_keeps_original_unit(self):
        data = examples()[:2]
        plan = r.build_plan(data)
        self.assertEqual(plan["planned_pairs"], 1)
        self.assertEqual(plan["available_extra_pairs"], 0)
        self.assertEqual(r.extra_examples(plan["units"][0], r.ALIGNED), [])

    def test_original_identity_donor_rule_is_reused(self):
        plan = r.build_plan(examples())
        reverse = r.build_plan(list(reversed(examples())))
        self.assertEqual(plan["units"], reverse["units"])
        for unit in plan["units"]:
            self.assertNotEqual(unit["family"], unit["donor_family"])

    def test_equal_question_different_metadata_not_accepted(self):
        data = examples()
        for row in data: row["request"]["question"] = "Same question?"
        with self.assertRaises(c.Invalid): r.build_plan(data)

    def test_unknown_profile_and_mutated_context_rejected(self):
        unit = r.build_plan(examples())["units"][0]
        with self.assertRaises(c.Invalid): r.extra_examples(unit, "auto")
        unit["mismatched_request"]["evidence"][0]["text"] = "changed"
        with self.assertRaises(c.Invalid): r.extra_examples(unit, r.ALIGNED)

    def test_no_semantic_or_production_authority(self):
        plan = r.build_plan(examples())
        self.assertFalse(plan["independent_incompatibility_review"])
        self.assertFalse(plan["production_accepted"])
        self.assertEqual(set(plan["units"][0]["matched_request"]), {"question", "options", "evidence"})

    def test_source_cardinality_not_truncated(self):
        data = examples()[:4]
        data[0]["request"]["evidence"].append({"id":"Extra", "position":1,"text":"Other", "modality":"text", "asset_sha256":None})
        data[0]["response"] = "fact 0 [E0] [Extra]"
        plan = r.build_plan(data)
        self.assertEqual(plan["available_extra_pairs"], 0)
        self.assertEqual(plan["planned_pairs"], 2)


if __name__ == "__main__": unittest.main()
