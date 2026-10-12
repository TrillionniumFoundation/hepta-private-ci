"""Protocol-only fixtures; no pretrained answers or independent reviews."""

from copy import deepcopy
import unittest

from locomo_frozen_reader_pair import ARMS, LIMIT, metric, normalized, summarize


class FrozenReaderPairTests(unittest.TestCase):
    def cases(self):
        cases = [
            dict(question_id="q1", family_proxy_digest="f1", source_census_sha256="s1"),
            dict(question_id="q2", family_proxy_digest="f2", source_census_sha256="s2"),
        ]
        decisions = {}
        rows = []
        for q in cases:
            for arm, k in zip(ARMS, (4, 8), strict=True):
                selected = [str(i) for i in range(k)]
                decisions[(q["question_id"], arm)] = dict(
                    selected=selected,
                    source_census_sha256=q["source_census_sha256"],
                    family_proxy_digest=q["family_proxy_digest"],
                )
                rows.append(
                    dict(
                        question_id=q["question_id"],
                        arm=arm,
                        selected=selected,
                        source_census_sha256=q["source_census_sha256"],
                        family_proxy_digest=q["family_proxy_digest"],
                        status="succeeded",
                        answer="Blue [E1]",
                        receipt=dict(
                            reader_identity="pinned",
                            reader_profile="frozen",
                            token_limit=LIMIT,
                            input_tokens=100,
                            generated_tokens=4,
                            trainable_parameters=0,
                            answer_postprocessed=False,
                            seconds=0.1,
                            delivered_evidence=[
                                dict(
                                    label="E" + str(i + 1),
                                    original_id=s,
                                    excerpt="Blue",
                                )
                                for i, s in enumerate(selected)
                            ],
                        ),
                    )
                )
        targets = {
            "q1": dict(answer="Blue", unanswerable=False),
            "q2": dict(answer="Red", unanswerable=False),
        }
        return cases, decisions, rows, targets

    def test_identical_answers_are_not_an_optimization_gain(self):
        cases, decisions, rows, targets = self.cases()
        report = summarize(rows, cases, decisions, targets)
        self.assertEqual(report["paired"]["wins"], 0)
        self.assertEqual(report["paired"]["losses"], 0)
        self.assertEqual(report["paired"]["ties"], 2)
        self.assertEqual(
            report["arms"]["lexical_k8"]["diagnostic_f1"],
            report["arms"]["lexical_k4"]["diagnostic_f1"],
        )
        self.assertIsNone(report["independently_adjudicated_citation_precision"])
        self.assertFalse(report["production_accepted"])

    def test_complete_failure_census_widens_bounds(self):
        cases, decisions, rows, targets = self.cases()
        rows[3].update(status="failed", error_type="TimeoutError")
        del rows[3]["answer"]
        del rows[3]["receipt"]
        result = summarize(rows, cases, decisions, targets)
        self.assertEqual(result["paired"]["missing_or_unscored"], 1)
        self.assertEqual(result["paired"]["all_planned_delta_bounds"], [-0.5, 0.5])
        self.assertEqual(result["arms"]["lexical_k8"]["failed"], 1)

    def test_cannot_hide_reorder_or_switch_reference_reader(self):
        cases, decisions, rows, targets = self.cases()
        for version in ("missing", "reversed", "wrong_reader", "wrong_source"):
            changed = deepcopy(rows)
            if version == "missing":
                changed.pop()
            elif version == "reversed":
                changed.reverse()
            elif version == "wrong_reader":
                changed[0]["receipt"]["reader_identity"] = "other"
            else:
                changed[0]["selected"][0] = "invented"
            with self.subTest(version=version), self.assertRaises(ValueError):
                summarize(changed, cases, decisions, targets)

    def test_source_labels_are_structural_only_and_no_posthoc_answer_change(self):
        cases, decisions, rows, targets = self.cases()
        rows[0]["answer"] = "Blue [E9]"
        result = summarize(rows, cases, decisions, targets)
        self.assertEqual(result["arms"][ARMS[0]]["answers_with_undelivered_marker"], 1)
        self.assertEqual(rows[0]["answer"], "Blue [E9]")
        self.assertIsNone(
            result["arms"][ARMS[0]]["independent_citation_entailment_precision"]
        )

    def test_missing_gold_is_not_unanswerability(self):
        self.assertEqual(
            metric("guess", dict(answer="", unanswerable=False))["eligible"], False
        )
        self.assertEqual(metric("guess", dict(answer="", unanswerable=True))["f1"], 0)
        self.assertEqual(
            metric(
                "I do not have enough evidence.", dict(answer="", unanswerable=True)
            )["f1"],
            1,
        )

    def test_diagnostic_score_normalization_preserves_original(self):
        self.assertEqual(normalized("The Blue [E1]"), "blue")
        self.assertEqual(normalized("Blue [E17]"), "blue")


if __name__ == "__main__":
    unittest.main()
