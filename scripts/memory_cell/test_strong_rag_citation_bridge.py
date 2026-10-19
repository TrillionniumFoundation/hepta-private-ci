"""Nine-arm literal-citation fidelity tests; no model inference or gold admission."""

from copy import deepcopy
import unittest

from historical_event_citation_chain import audit_evaluation
from test_historical_event_citation_chain import case


ARMS = (
    "selected_k",
    "hybrid_k4",
    "hybrid_k6",
    "hybrid_k4_reversed",
    "single_hop",
    "entity_time",
    "organized",
    "program_support",
    "empty",
)


def nine_arms(*, answer=None):
    row, public, documents = case()
    # A real evaluation scope must equal its query identity; the standalone
    # historical fixture otherwise uses a generic, unrelated scope string.
    for source in documents.values():
        source["scope"] = row["question_id"]
    for delivery in row["receipt"]["delivered_evidence"]:
        delivery["scope"] = row["question_id"]
    if answer is not None:
        row["answer"] = answer
        row["citation_audit"]["request"]["answer"] = answer
    rows = []
    for arm in ARMS:
        copy = deepcopy(row)
        copy["arm"] = arm
        rows.append(copy)
    specs = [dict(id="q1", kind="composition", **public)]
    labels = [dict(id="q1", support=["first", "second"])]
    return rows, specs, labels, documents


class FormalCitationBridgeTests(unittest.TestCase):
    def evaluate(self, rows, specs, labels, documents):
        return audit_evaluation(
            rows,
            specs,
            labels,
            documents,
            expected_qids=["q1"],
            arms=ARMS,
        )

    def test_citation_completeness_is_not_task_success(self):
        output = self.evaluate(*nine_arms())
        for arm in ARMS:
            self.assertEqual(output["by_arm"][arm]["strict_task_success"], 1)
            self.assertEqual(
                output["by_arm"][arm]["correct_with_full_program_declared_citations"],
                0,
            )
            self.assertEqual(
                output["by_arm"][arm]["correct_with_public_event_chain_connected"],
                0,
            )
        self.assertFalse(output["production_accepted"])
        self.assertFalse(output["independent_semantic_adjudication"])

    def test_two_hop_complete_citations_are_detected(self):
        data = nine_arms(answer="site_good [E1] [E2]")
        found = self.evaluate(*data)
        self.assertEqual(len(found["cases"]), len(ARMS))
        for arm in ARMS:
            self.assertEqual(
                found["by_arm"][arm]["correct_with_public_event_chain_connected"], 1
            )

    def test_missing_or_duplicated_arm_is_not_hidden(self):
        rows, specs, labels, docs = nine_arms()
        for changed in (rows[:-1], rows + rows[:1]):
            with self.assertRaises(ValueError):
                self.evaluate(changed, specs, labels, docs)

    def test_failed_generation_stays_in_denominator(self):
        rows, specs, labels, docs = nine_arms()
        rows[0] = {
            "question_id": "q1",
            "kind": "composition",
            "arm": "selected_k",
            "status": "failed",
        }
        found = self.evaluate(rows, specs, labels, docs)
        self.assertEqual(found["planned_attempts"], 9)
        self.assertEqual(found["by_arm"]["selected_k"]["strict_task_success"], 0)
        self.assertEqual(found["by_arm"]["selected_k"]["generations_failed"], 1)

    def test_fabricated_citation_and_excerpt_tampering_fail_closed(self):
        rows, specs, labels, docs = nine_arms()
        changed = deepcopy(rows)
        changed[0]["answer"] = "site_good [E3]"
        changed[0]["citation_audit"]["request"]["answer"] = "site_good [E3]"
        with self.assertRaises(ValueError):
            self.evaluate(changed, specs, labels, docs)
        changed = deepcopy(rows)
        changed[0]["receipt"]["delivered_evidence"][0]["excerpt"] = "modified"
        with self.assertRaises(ValueError):
            self.evaluate(changed, specs, labels, docs)

    def test_public_task_kind_and_boolean_score_are_enforced(self):
        rows, specs, labels, docs = nine_arms()
        changed = deepcopy(rows)
        changed[0]["strict_task_success"] = 1
        with self.assertRaises(ValueError):
            self.evaluate(changed, specs, labels, docs)
        changed_specs = deepcopy(specs)
        changed_specs[0]["kind"] = "procedure"
        with self.assertRaises(ValueError):
            self.evaluate(rows, changed_specs, labels, docs)


if __name__ == "__main__":
    unittest.main()
