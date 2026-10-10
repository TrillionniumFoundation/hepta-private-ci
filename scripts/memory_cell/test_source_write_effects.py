"""Exact effect/census tests; fixtures are not model results or human reviews."""

import copy
import unittest

from source_write_effects import ARMS, align_records, effects


def fixture():
    cases = {}
    raw, scored = [], []
    for i, kind in enumerate(("fact", "procedure")):
        qid = "q" + str(i)
        cases[qid] = dict(
            kind=kind,
            candidate_digest="pool" + str(i),
            candidate_ids=["source"],
            controls={"hybrid": {"selected": ["source"]}, "organized": {"selected": ["source"]}, "empty": {"selected": []}},
        )
        for arm in ARMS:
            empty = arm in ("parameter_only", "empty")
            receipt = dict(
                reader_identity="base",
                reader_profile="profile",
                knowledge_module_enabled=arm in ("knowledge", "parameter_only"),
                input_ids_digest="empty" if empty else "same",
                delivered_evidence=[] if empty else [dict(excerpt="original")],
                derived_evidence=[] if empty else [dict(original_id="source")],
                input_tokens=3,
                generated_tokens=1,
                seconds=0.1,
            )
            row = dict(question_id=qid, arm=arm, kind=kind, candidate_digest="pool" + str(i), selected=[] if empty else ["source"], status="succeeded", answer="value", receipt=receipt)
            raw.append(row)
            annotated = copy.deepcopy(row)
            annotated.update(parsed_identifier="value", strict_task_success=arm in ("organized", "knowledge", "policy"))
            if kind == "procedure":
                annotated["procedure_verification"] = dict(exit_code=0, seconds=0.1)
            scored.append(annotated)
    return raw, scored, cases


class SourceEffectTests(unittest.TestCase):
    def test_policy_tie_with_organizer_is_not_independent_learning_gain(self):
        raw, scored, cases = fixture()
        report = effects(raw, scored, cases)
        pairs = report["contrasts"]
        self.assertEqual(pairs["organization_vs_hybrid"]["all"]["wins"], 2)
        self.assertEqual(pairs["policy_vs_initialization"]["all"]["wins"], 2)
        self.assertEqual(pairs["policy_vs_organized"]["all"]["all_planned_effect_bounds"], [0, 0])
        self.assertFalse(pairs["knowledge_vs_same_evidence"]["all"]["observed_win_without_loss"])
        self.assertIsNone(report["semantic_citation_precision"])
        self.assertFalse(report["production_accepted"])

    def test_parameter_only_requires_empty_context_and_has_its_own_comparison(self):
        raw, scored, cases = fixture()
        for r in scored:
            if r["arm"] == "parameter_only":
                r["strict_task_success"] = True
        item = effects(raw, scored, cases)["contrasts"]["parameter_only_vs_empty"]["all"]
        self.assertEqual((item["wins"], item["losses"]), (2, 0))
        i = next(i for i, r in enumerate(raw) if r["arm"] == "parameter_only")
        raw[i]["receipt"]["delivered_evidence"] = [{"excerpt": "leaked"}]
        scored[i]["receipt"] = copy.deepcopy(raw[i]["receipt"])
        with self.assertRaises(ValueError):
            effects(raw, scored, cases)

    def test_failures_widen_bounds_instead_of_disappearing(self):
        raw, scored, cases = fixture()
        i = next(i for i, r in enumerate(raw) if r["arm"] == "knowledge")
        raw[i] = {k: v for k, v in raw[i].items() if k not in ("answer", "receipt")}
        raw[i]["status"] = "failed"
        raw[i]["error_type"] = "TimeoutError"
        scored[i] = copy.deepcopy(raw[i])
        item = effects(raw, scored, cases)["contrasts"]["knowledge_vs_same_evidence"]["all"]
        self.assertEqual(item["missing_pairs"], 1)
        self.assertEqual(item["all_planned_effect_bounds"], [-0.5, 0.5])
        self.assertFalse(item["observed_win_without_loss"])

    def test_task_kinds_do_not_mask_a_procedure_regression(self):
        raw, scored, cases = fixture()
        for r in scored:
            if r["arm"] == "knowledge" and r["kind"] == "procedure":
                r["strict_task_success"] = False
        item = effects(raw, scored, cases)["contrasts"]["knowledge_vs_same_evidence"]
        self.assertEqual(item["kind:procedure"]["losses"], 1)
        self.assertEqual(item["kind:fact"]["losses"], 0)

    def test_source_answer_and_score_mutations_are_not_new_evidence(self):
        for field, value in (("answer", "repaired [E1]"), ("kind", "different"), ("candidate_digest", "different")):
            raw, scored, cases = fixture()
            scored[0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                effects(raw, scored, cases)
        raw, scored, cases = fixture()
        raw[0]["strict_task_success"] = False
        with self.assertRaises(ValueError):
            effects(raw, scored, cases)

    def test_census_missing_duplicate_and_reordered_annotations_reject(self):
        for mode in ("missing", "duplicate", "order"):
            raw, scored, cases = fixture()
            if mode == "missing":
                raw.pop()
            elif mode == "duplicate":
                raw[-1] = raw[0]
            else:
                scored.reverse()
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                effects(raw, scored, cases)

    def test_derived_prompt_or_adapter_drift_invalidates_paired_claim(self):
        for key, value in (("derived_evidence", []), ("input_ids_digest", "different"), ("knowledge_module_enabled", False), ("reader_identity", "different")):
            raw, scored, cases = fixture()
            i = next(i for i, r in enumerate(raw) if r["arm"] == "knowledge")
            raw[i]["receipt"][key] = value
            scored[i]["receipt"][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                effects(raw, scored, cases)

    def test_invalid_observation_numbers_cannot_pass(self):
        for key, value in (("seconds", float("nan")), ("seconds", -1), ("input_tokens", True), ("generated_tokens", -1)):
            raw, scored, cases = fixture()
            raw[0]["receipt"][key] = value
            scored[0]["receipt"][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                align_records(raw, scored, cases)

    def test_answer_changes_are_not_successes(self):
        raw, scored, cases = fixture()
        for r in raw:
            if r["arm"] == "knowledge":
                r["answer"] = "different"
        for r in scored:
            if r["arm"] == "knowledge":
                r["answer"] = "different"
        item = effects(raw, scored, cases)["contrasts"]["knowledge_vs_same_evidence"]["all"]
        self.assertEqual(item["changed_answers"], 2)
        self.assertEqual(item["wins"], 0)


if __name__ == "__main__":
    unittest.main()
