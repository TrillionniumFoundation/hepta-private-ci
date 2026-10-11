"""Historical rejection and new preservation must never share a census identity."""

import copy
import json
import tempfile
import unittest
from pathlib import Path

from benchmark_coverage import plan_coverage
from benchmark_review import review
from native import load
from test_coverage import receipts


class NativeReviewProfileTests(unittest.TestCase):
    def inputs(self, root, policy):
        def sample(qid, content):
            return dict(
                question_id=qid,
                question_type="multi-session",
                question="What?",
                question_date="2026/01/02",
                answer="gold",
                answer_session_ids=["s"],
                haystack_session_ids=["s"],
                haystack_dates=["2026/01/01"],
                haystack_sessions=[[{"role": "user", "content": content}]],
            )

        source = root / "source.json"
        source.write_text(json.dumps([sample("a", ""), sample("b", "observed")]))
        benchmark = load(
            source,
            "longmemeval",
            empty_turns=policy,
            allow_unresolved_evidence=True,
            invalid_history="quarantine-question",
        )
        plan = plan_coverage(benchmark, folds=1, shards=1, per_fold_limit=None)
        binding = {"code": "pinned"}
        if policy == "preserve":
            binding["empty_turns"] = policy
        declared = dict(
            schema="hepta.memory-benchmark.preregistered.v1",
            coverage=plan.content(),
            execution_binding=binding,
        )
        plan_path = root / "plan.json"
        plan_path.write_text(json.dumps(declared))
        report = receipts(plan)[0]
        report["execution_binding"] = binding
        if policy == "reject":
            for records in report["results"].values():
                for row in records:
                    if row["question_id"] == "longmemeval:a":
                        row.update(
                            status="failed",
                            hypothesis=None,
                            diagnostic_token_f1=None,
                            stage="native-history-ingress",
                        )
        reports = root / "reports"
        reports.mkdir()
        (reports / "report.json").write_text(json.dumps(report))
        return source, plan_path, reports, declared, report

    def test_old_unlabelled_binding_keeps_quarantine_and_separate_family(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            source, plan, reports, _, _ = self.inputs(root, "reject")
            result = review(
                plan,
                reports,
                root / "out",
                validator_commit="b" * 40,
                benchmark_path=source,
            )
            self.assertEqual(result["all_attempts_exported"], 8)
            self.assertEqual(result["coverage"]["arms"]["rag"]["failed"], 1)
            self.assertEqual(
                result["paired_diagnostics"]["comparisons"][0]["family_groups"], 2
            )
            self.assertFalse(result["production_accepted"])

    def test_new_binding_preserves_history_and_unites_shared_native_roots(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            source, plan, reports, _, _ = self.inputs(root, "preserve")
            result = review(
                plan,
                reports,
                root / "out",
                validator_commit="b" * 40,
                benchmark_path=source,
            )
            self.assertEqual(result["coverage"]["arms"]["rag"]["failed"], 0)
            self.assertEqual(
                result["paired_diagnostics"]["comparisons"][0]["family_groups"], 1
            )
            self.assertFalse(result["paired_diagnostics"]["independence_verified"])
            self.assertIsNone(result["signed_semantic_citation_precision"])

    def test_relabelled_old_or_new_plan_cannot_change_source_family_census(self):
        for policy in ("reject", "preserve"):
            with self.subTest(policy=policy), tempfile.TemporaryDirectory() as name:
                root = Path(name)
                source, plan, reports, declared, report = self.inputs(root, policy)
                binding = {
                    "code": "pinned",
                    "empty_turns": "preserve" if policy == "reject" else "reject",
                }
                declared["execution_binding"] = binding
                report["execution_binding"] = binding
                plan.write_text(json.dumps(declared))
                (reports / "report.json").write_text(json.dumps(report))
                with self.assertRaisesRegex(ValueError, "census drift"):
                    review(
                        plan,
                        reports,
                        root / "out",
                        validator_commit="b" * 40,
                        benchmark_path=source,
                    )
                self.assertFalse((root / "out").exists())

    def test_unknown_or_mixed_profile_does_not_publish_review(self):
        for mixed in (False, True):
            with self.subTest(mixed=mixed), tempfile.TemporaryDirectory() as name:
                root = Path(name)
                source, plan, reports, declared, report = self.inputs(root, "preserve")
                binding = {"code": "pinned", "empty_turns": "impute"}
                report["execution_binding"] = binding
                if not mixed:
                    declared["execution_binding"] = copy.deepcopy(binding)
                plan.write_text(json.dumps(declared))
                (reports / "report.json").write_text(json.dumps(report))
                with self.assertRaises(ValueError):
                    review(
                        plan,
                        reports,
                        root / "out",
                        validator_commit="b" * 40,
                        benchmark_path=source,
                    )
                self.assertFalse((root / "out").exists())


if __name__ == "__main__":
    unittest.main()
