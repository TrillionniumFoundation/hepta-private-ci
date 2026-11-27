"""Prevent retrospective relabeling and final-label ingress into frozen reads."""

from pathlib import Path
import tempfile
import unittest

from cohort_contract import (
    admit_prospective_score,
    failure_excerpt,
    prospective_candidates,
    seal,
    validate_seal,
)
from budget_ledger import digest


class CohortTests(unittest.TestCase):
    def test_future_enrollment_preserves_unresolved_and_excludes_old_or_own(self):
        reg = dict(
            registered_at="2026-10-24T04:00:00Z",
            admission_deadline="2026-10-24T06:00:00Z",
            maximum_new_root_cause_groups=12,
            exclusion=dict(
                already_observed_run_ids=[1],
                this_research_branch_fragments=["memory-budget"],
                this_research_workflow_fragments=["memory"],
            ),
        )
        freeze = dict(
            effective_registered_at="2026-10-24T04:01:00Z",
            canonical_protocol_sha256=digest(reg),
        )
        base = dict(
            created_at="2026-10-24T04:02:00Z",
            updated_at="2026-10-24T04:03:00Z",
            status="completed",
            conclusion="failure",
            head_sha="a" * 40,
            path="workflow.yml",
            head_branch="fix/real",
            name="CI",
        )
        runs = [
            dict(base, id=1),
            dict(base, id=2),
            dict(base, id=3, head_branch="memory-budget/test"),
            dict(base, id=4, created_at="2026-10-24T03:59:00Z"),
        ]
        result = prospective_candidates(runs, reg, freeze)
        self.assertEqual([x["run_id"] for x in result["candidates"]], [2])
        self.assertEqual(result["candidates"][0]["repair_outcome"], "unresolved")
        self.assertEqual(len(result["rejections"]), 3)

    def test_seal_rejects_final_gold_and_detects_later_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            code = root / "code.py"
            code.write_text("print('source')\n")
            meta = [
                dict(
                    task_id="task",
                    root_cause_group="new",
                    classification="retrospective_time_holdout",
                )
            ]
            with self.assertRaises(ValueError):
                seal(
                    root / "bad",
                    protocol={},
                    source_documents=[],
                    requests=[
                        dict(task_id="task", text="original", paths=[], gold="answer")
                    ],
                    task_metadata=meta,
                    code_paths=[code],
                )
            seal(
                root / "good",
                protocol={},
                source_documents=[],
                requests=[dict(task_id="task", text="original", paths=[])],
                task_metadata=meta,
                code_paths=[code],
            )
            validate_seal(root / "good")
            code.write_text("print('changed')\n")
            with self.assertRaises(ValueError):
                validate_seal(root / "good")

    def test_predicting_after_repair_never_becomes_prospective(self):
        resolution = dict(
            previously_seen_group=False,
            earliest_repair_published_at_ns=20,
            original_outcome_available_at_ns=30,
            original_execution_verified=True,
        )
        self.assertFalse(
            admit_prospective_score(
                dict(classification="prospective_unresolved"),
                dict(frozen_at_ns=21),
                resolution,
            )
        )
        self.assertFalse(
            admit_prospective_score(
                dict(classification="retrospective_time_holdout"),
                dict(frozen_at_ns=10),
                resolution,
            )
        )
        self.assertTrue(
            admit_prospective_score(
                dict(classification="prospective_unresolved"),
                dict(frozen_at_ns=10),
                resolution,
            )
        )

    def test_input_excerpt_retains_original_help_without_inventing_answer(self):
        raw = "setup\n2026-10-24T01:00:00Z error: component missing\n2026-10-24T01:00:00Z help: install tool\nfooter\n"
        self.assertEqual(
            failure_excerpt(raw), "error: component missing\nhelp: install tool\nfooter"
        )


if __name__ == "__main__":
    unittest.main()
