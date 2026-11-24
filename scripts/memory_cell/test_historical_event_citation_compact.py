"""Model-free regression checks for deterministic historical citation summaries."""

from copy import deepcopy
import unittest

from historical_event_citation_compact import compact_report


def fixture():
    def row(qid, arm, *, success=False, complete=False):
        return dict(
            question_id=qid,
            kind="composition",
            arm=arm,
            strict_task_success=success,
            program_declared_support_cited=complete,
            cited_source_ids=["a"] if complete else [],
            missing_program_declared_support=[] if complete else ["b"],
            publicly_declared_event_path_connected=complete,
        )

    rows = [row(str(i), "arm", success=i < 3, complete=i == 0) for i in range(48)]
    model = dict(
        archive_sha256="a" * 64,
        attempted=48,
        generating_commit="b" * 40,
        scored_answers_sha256="c" * 64,
        cases=rows,
        by_arm={
            "arm": dict(
                attempted=48,
                strict_task_success=3,
                correct_with_full_program_declared_citations=1,
            )
        },
    )
    return dict(
        schema="hepta.memory-cell.historical-formal-citation.v1",
        pinned_plan_sha256="d" * 64,
        generating_commit="b" * 40,
        real_model_generations=96,
        model_semantic_entailment_certified=False,
        program_declared_support_is_human_certified=False,
        formal_event_path_is_production_semantic_precision=False,
        independent_source_families=0,
        production_accepted=False,
        models={"qwen-3b": deepcopy(model), "smol-1.7b": deepcopy(model)},
    )


class CompactCitationTests(unittest.TestCase):
    def test_compact_retains_aggregate_and_only_noncomplete_correct_cases(self):
        got = compact_report(fixture())
        self.assertNotIn("cases", got["models"]["qwen-3b"])
        self.assertEqual(
            len(got["models"]["qwen-3b"]["failed_complete_program_citation_rows"]),
            2,
        )
        self.assertEqual(
            got["models"]["qwen-3b"]["by_arm"]["arm"]["strict_task_success"],
            3,
        )
        self.assertFalse(got["production_accepted"])

    def test_missing_case_cannot_make_success_denominator_smaller(self):
        data = fixture()
        data["models"]["qwen-3b"]["cases"].pop()
        with self.assertRaises(ValueError):
            compact_report(data)

    def test_duplicate_slot_rejected(self):
        data = fixture()
        data["models"]["qwen-3b"]["cases"][1] = deepcopy(
            data["models"]["qwen-3b"]["cases"][0]
        )
        with self.assertRaises(ValueError):
            compact_report(data)

    def test_score_disagrees_with_cases_rejected(self):
        data = fixture()
        data["models"]["smol-1.7b"]["by_arm"]["arm"]["strict_task_success"] = 4
        with self.assertRaises(ValueError):
            compact_report(data)

    def test_source_promotion_and_mixed_generating_commits_rejected(self):
        for key, value in (
            ("production_accepted", True),
            ("independent_source_families", 1),
        ):
            data = fixture()
            data[key] = value
            with self.assertRaises(ValueError):
                compact_report(data)
        data = fixture()
        data["models"]["qwen-3b"]["generating_commit"] = "1" * 40
        with self.assertRaises(ValueError):
            compact_report(data)

    def test_unknown_format_fields_fail_closed(self):
        data = fixture()
        data["unexpected_confidence"] = 0.99
        with self.assertRaises(ValueError):
            compact_report(data)


if __name__ == "__main__":
    unittest.main()
