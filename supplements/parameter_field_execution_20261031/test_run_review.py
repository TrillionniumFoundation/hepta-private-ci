"""Synthetic orchestration fixtures; never access sealed or unsealed outcomes."""

from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import io
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from supplements.parameter_field_execution_20261031 import run_review as runner


def fixture():
    analyses = {}
    for stage, names, seeds in (("B", runner.p1_interpretation.B_EFFECTS, [17, 29, 43]),
                                ("C", runner.p1_interpretation.C_EFFECTS, list(range(801, 809)))):
        effects = {}
        for name in names:
            value = -.005 if "clean" in name else {
                "field-ordinary task": .0005, "dual field increment task": -.02,
                "ordinary field increment task": -.04}.get(name, .02)
            effects[name] = {"role": "clean" if "clean" in name else "task",
                "point": {o: value for o in ("reward", "audit")},
                "ci": {o: [value-.0001, value+.0001] for o in ("reward", "audit")},
                "per_seed": {str(s): {o: value for o in ("reward", "audit")} for s in seeds}}
        formal = {"stage": stage, "formal_family": list(names), "seeds": seeds,
                  "observers": ["reward", "audit"], "effects": effects}
        formal["statistical_thresholds"] = runner.coverage.expected_thresholds(formal, stage)
        analyses[stage] = formal
    aggregate = {"formal_analyses": analyses}
    review = {"integrity_issues": {"issue_count": 0}}
    audit = {"cost_coverage_deficiencies": [], "declared_cost_rows_complete": True,
             "coverage_scope": "Synthetic named current costs only; historical cost unknown."}
    p0 = {"status": "DESCRIPTIVE_COMPLETE", "consumed_inputs": [
        {"path": "/synthetic/input.json", "bytes": 2, "sha256": "1"*64, "roles": ["synthetic"]}]}
    return aggregate, review, audit, p0


class UnifiedReviewTests(unittest.TestCase):
    def test_absent_or_malformed_external_pin_never_calls_gate(self):
        with patch.object(runner.coverage, "read_after_review_complete") as gate:
            for args in ([], ["--review-complete", "/synthetic/COMPLETE.json",
                               "--expected-review-complete-sha256", "bad"]):
                output = io.StringIO()
                with redirect_stdout(output):
                    code = runner.main(args)
                self.assertEqual((code, json.loads(output.getvalue())["scientific_payloads_decoded"]), (2, False))
            gate.assert_not_called()

    def test_rejected_original_gate_never_runs_analysis_or_raw_diagnostics(self):
        with patch.object(runner.coverage, "read_after_review_complete", side_effect=ValueError("synthetic incomplete seals")), \
             patch.object(runner.coverage, "aggregate_checks") as analysis, \
             patch.object(runner.p0_actions, "analyze") as raw, redirect_stderr(io.StringIO()) as errors:
            code = runner.main(["--review-complete", "/synthetic/COMPLETE.json",
                                "--expected-review-complete-sha256", "1"*64])
            self.assertEqual(code, 2)
            self.assertEqual(json.loads(errors.getvalue())["status"], "NOT_EVALUATED")
            analysis.assert_not_called()
            raw.assert_not_called()

    def test_original_gates_and_negative_simple_effects_are_preserved(self):
        aggregate, review, audit, p0 = fixture()
        before = deepcopy((aggregate, review, audit, p0))
        result = runner.assemble(aggregate, review, audit, p0)
        self.assertEqual((aggregate, review, audit, p0), before)
        self.assertEqual(result["original_statistical_gates"], {
            s: aggregate["formal_analyses"][s]["statistical_thresholds"] for s in ("B", "C")})
        self.assertFalse(result["original_statistical_gates"]["B"]["field_advantage_thresholds_pass"])
        self.assertTrue(result["original_statistical_gates"]["C"]["interaction_and_retention_thresholds_pass"])
        self.assertEqual(result["interpretations"]["C"]["statistical_relationship"],
                         "positive_interaction_with_two_negative_simple_effects_less_harm")
        self.assertTrue(all(r["evidence_context"]["activity"]["status"] == "unknown" for r in result["interpretations"].values()))

    def test_missing_context_is_not_zero_or_complete(self):
        aggregate, review, audit, p0 = fixture()
        result = runner.assemble(aggregate, {}, {"coverage_scope": "not supplied"}, p0)
        self.assertEqual(result["status"], "EVIDENCE_CONTEXT_INCOMPLETE")
        for stage in ("B", "C"):
            context = result["interpretations"][stage]["evidence_context"]
            self.assertEqual((context["integrity"]["status"], context["cost_coverage"]["status"]), ("unknown", "unknown"))
        audit.update(cost_coverage_deficiencies=["synthetic missing cost"], declared_cost_rows_complete=False)
        self.assertEqual(runner.assemble(aggregate, review, audit, p0)["status"], "COST_COVERAGE_INCOMPLETE")
        review["integrity_issues"]["issue_count"] = 1
        with self.assertRaises(ValueError):
            runner.assemble(aggregate, review, audit, p0)

    def test_single_gate_wiring_stability_and_nested_timings(self):
        aggregate, review, audit, p0 = fixture()
        context = {"inputs": SimpleNamespace(unchanged=Mock())}
        descriptors = {k: {"path": "/synthetic/"+k, "bytes": 2, "sha256": "1"*64}
                       for k in ("review_complete", "review", "aggregate")}
        with patch.object(runner.coverage, "read_after_review_complete", return_value=(aggregate, review, descriptors, context)) as gate, \
             patch.object(runner.coverage, "aggregate_checks", return_value=audit) as checks, \
             patch.object(runner.coverage, "checked_bytes", return_value=b"{}") as stable, \
             patch.object(runner.p0_actions, "analyze", return_value=p0) as p0_call, redirect_stdout(io.StringIO()) as output:
            code = runner.main(["--review-complete", "/synthetic/COMPLETE.json",
                                "--expected-review-complete-sha256", "1"*64])
        result = json.loads(output.getvalue())
        self.assertEqual(code, 0)
        gate.assert_called_once_with("/synthetic/COMPLETE.json", "1"*64)
        checks.assert_called_once_with(aggregate)
        p0_call.assert_called_once_with(context)
        context["inputs"].unchanged.assert_called_once()
        self.assertEqual(stable.call_count, 3)
        self.assertEqual(result["consumed_inputs"], p0["consumed_inputs"])
        self.assertEqual(result["gate_input_descriptors"], descriptors)
        self.assertEqual(len(result["implementation_sources"]), 5)
        self.assertEqual(len(result["timing"]["components"]), 6)
        self.assertTrue(result["timing"]["enclosing_total_is_not_additive_to_components"])


if __name__ == "__main__":
    unittest.main()
