"""Engineering fixtures only: no real source images, endpoints, or study results."""

from copy import deepcopy
import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import postseal_analysis_coverage as audit


def phase_fixture(stage):
    family, arms = (audit.B_EFFECTS, audit.B_ARMS) if stage == "B" else (audit.C_EFFECTS, audit.C_ARMS)
    seeds = [17, 29, 43] if stage == "B" else list(range(801, 809))
    offsets = [0.05, .06, .065, .055, .045, 0.] if stage == "B" else [0., -.02, 0., -.01, 0., 0.]
    means = {role: {arm: {o: .5 + (offsets[i] if role == "task" else 0.)
                          for o in audit.OBSERVERS} for i, arm in enumerate(arms)} for role in ("task", "clean")}
    effects = {}
    for name, (role, expression) in family.items():
        point = {o: audit.effect_value(means[role], arms, expression, o) for o in audit.OBSERVERS}
        effects[name] = {"role": role, "point": point,
                         "ci": {o: [v-.0001, v+.0001] for o, v in point.items()},
                         "per_seed": {str(seed): dict(point) for seed in seeds}}
    costs = {}
    for arm in arms:
        empty = stage == "B" and arm == "frozen"
        n = (3 if empty else 48) if stage == "B" else 8
        costs[arm] = {"expected_paths": n, "paths_with_costs": 0 if empty else n,
                      "metrics": {key: {"paths": n, "mean": float(value or 1), "minimum": float(value or 1),
                                        "maximum": float(value or 1), "sum_over_recorded_paths": float((value or 1) * n)}
                                  for key, value in audit.path_cost_requirements(stage, arm).items()}}
    result = {"stage": stage, "seeds": seeds, "observers": list(audit.OBSERVERS),
              "source_pairs": {"task": 512, "clean": 812} if stage == "B" else {"task": 988, "clean": 988},
              "source_pair_identities_sha256": {"task": "a"*64, "clean": "b"*64},
              "formal_family": list(family), "effects": effects, "arm_means": means,
              "statistics": {"draws": 8000, "seed": 291029 if stage == "B" else 291030,
                             "family_size_per_observer": len(family), "family_alpha": .05,
                             "quantiles": [.05/(2*len(family)), 1-.05/(2*len(family))]},
              "costs": {"arms": costs, "field_minus_taper_descriptive":
                        {key: {"paired_paths": 48, "mean_difference": 0., "sum_difference": 0.}
                         for key in audit.path_cost_requirements("B", "fixed_taper")}}}
    result["statistical_thresholds"] = audit.expected_thresholds(result, stage)
    return result


def aggregate_fixture():
    rows = []
    for phase, total in audit.PLANNED.items():
        seeds = [17, 29, 43] if phase in ("A", "B", "R") else [None]
        for seed in seeds:
            n = total // len(seeds)
            ledger = {"scheduled_gradient_microsteps": n, "gradient_backward_calls": n,
                      "gradient_generator_calls": 2 * n, "gradient_teacher_calls": 2 * n}
            if phase == "C":
                ledger = {"counts": {p + "." + key: value for p, value in
                          {"warmup": 8000, "bank": 46080, "evaluation": 3072, "replay_audit": 384}.items()
                          for key in ("scheduled_gradient_microsteps", "backward_calls", "generator_forward_calls")},
                          "cpu_seconds": 1., "wall_seconds": 1.}
            rows.append({"phase": phase, "kind": "training", "seed": seed, "gradient_microsteps": n,
                         "ledger": ledger, "cpu_seconds": 1., "wall_seconds": 1.})
    for phase in ("A", "B", "C"):
        ledger = ({"counts": {"endpoint." + k: 1 for k in ("generator_forward_calls", "reward_observer_calls", "audit_observer_calls")}}
                  if phase == "C" else {f"endpoint_{role}_{k}": 1 for role in ("task", "clean")
                                        for k in ("generator_calls", "reward_observer_calls", "audit_observer_calls")})
        rows.append({"phase": phase, "kind": "endpoint_scoring", "gradient_microsteps": 0,
                     "ledger": ledger, "cpu_seconds": 1., "wall_seconds": 1.})
    rows += [{"kind": "engineering_preflight", "gradient_microsteps": 216,
              "ledger": {"scheduled_gradient_microsteps": 216, "gradient_backward_calls": 216,
                         "gradient_generator_calls": 432, "gradient_teacher_calls": 432},
              "cpu_seconds": 1., "wall_seconds": 1.} for unused in range(2)]
    return {"status": "COMPLETE", "efficacy_artifacts_opened": True,
            "five_priority_findings": [{"priority": i} for i in range(1, 6)],
            "formal_analyses": {phase: phase_fixture(phase) for phase in ("B", "C")},
            "actual_costs": {"rows": rows, "completed_receipt_gradient_microsteps": sum(r["gradient_microsteps"] for r in rows)}}


class CoverageChecks(unittest.TestCase):
    def test_independent_factorial_identity_and_original_gate(self):
        value = aggregate_fixture()
        result = audit.aggregate_checks(value)
        self.assertTrue(result["declared_cost_rows_complete"])
        self.assertFalse(result["net_benefit_admission_assigned"])
        c = value["formal_analyses"]["C"]
        self.assertTrue(c["statistical_thresholds"]["interaction_and_retention_thresholds_pass"])
        self.assertLess(c["effects"]["dual field increment task"]["ci"]["reward"][1], 0)

    def test_missing_total_cost_is_not_replaced_by_complete_path_ledgers(self):
        value = aggregate_fixture()
        value["actual_costs"] = {}
        result = audit.aggregate_checks(value)
        self.assertFalse(result["declared_cost_rows_complete"])
        self.assertTrue(any("local path ledgers cannot substitute" in v for v in result["cost_coverage_deficiencies"]))

    def test_missing_arm_ledger_and_C_warmstart_cost_are_reported(self):
        value = aggregate_fixture()
        value["formal_analyses"]["B"]["costs"]["arms"].pop("field12")
        value["formal_analyses"]["C"]["costs"]["arms"]["dual+frozen"].update(paths_with_costs=0, metrics={})
        result = audit.aggregate_checks(value)
        self.assertTrue(any("B:field12" in v for v in result["cost_coverage_deficiencies"]))
        self.assertTrue(any("C:dual+frozen" in v for v in result["cost_coverage_deficiencies"]))

    def test_identity_boolean_and_missing_simple_effect_fail(self):
        for which in ("point", "gate", "simple_effect"):
            value = aggregate_fixture()
            c = value["formal_analyses"]["C"]
            if which == "point":
                c["effects"]["interaction task"]["point"]["reward"] += .3
            elif which == "gate":
                c["statistical_thresholds"]["interaction_and_retention_thresholds_pass"] = False
            else:
                del c["effects"]["dual field increment task"]
            with self.assertRaises(ValueError):
                audit.aggregate_checks(value)

    def test_duplicate_stage_seed_is_not_complete_coverage(self):
        value = aggregate_fixture()
        a = [r for r in value["actual_costs"]["rows"] if r.get("phase") == "A" and r["kind"] == "training"]
        a[1]["seed"] = a[0]["seed"]
        self.assertTrue(any("duplicated or omitted A seed" in v
                            for v in audit.aggregate_checks(value)["cost_coverage_deficiencies"]))

    def test_cost_roundoff_and_nonadditive_peak(self):
        phase = phase_fixture("B")
        metric = phase["costs"]["arms"]["field12"]["metrics"]["guarded_transition_cpu_ns"]
        metric.update(minimum=.1, mean=.09999999999999999, maximum=.1, sum_over_recorded_paths=4.8)
        audit.cost_coverage(phase, "B")
        phase["costs"]["arms"]["field12"]["metrics"]["peak_rss"] = dict(metric)
        with self.assertRaisesRegex(ValueError, "Peak resource"):
            audit.cost_coverage(phase, "B")

    def test_single_metric_on_single_path_cannot_mean_full_cost_coverage(self):
        value = aggregate_fixture()
        metrics = value["formal_analyses"]["B"]["costs"]["arms"]["field12"]["metrics"]
        metrics.clear()
        metrics["selected_operation_cpu_ns"] = {"paths": 1, "mean": 1., "minimum": 1., "maximum": 1.}
        missing = audit.aggregate_checks(value)["cost_coverage_deficiencies"]
        self.assertTrue(any("incomplete metric coverage selected_operation_cpu_ns: 1/48" in v for v in missing))
        self.assertTrue(any("required cost metric absent: scheduled_gradient_microsteps" in v for v in missing))

    def test_missing_overall_cpu_or_physical_ledger_never_imputed(self):
        value = aggregate_fixture()
        row = value["actual_costs"]["rows"][-1]
        del row["cpu_seconds"]  # Original preflight producer does not save total CPU.
        row["ledger"] = {"selected_operation_cpu_ns": 10}
        result = audit.aggregate_checks(value)
        missing = result["cost_coverage_deficiencies"]
        self.assertTrue(any("overall cpu_seconds absent" in v for v in result["cost_scope_limitations"]))
        self.assertTrue(any("scheduled-gradient physical counter absent" in v for v in missing))

    def test_recorded_gradient_count_must_match_physical_backward_work(self):
        value = aggregate_fixture()
        value["actual_costs"]["rows"][0]["ledger"]["gradient_backward_calls"] -= 1
        with self.assertRaisesRegex(ValueError, "backward calls disagree"):
            audit.aggregate_checks(value)

    def test_missing_counter_and_partial_paired_cost_do_not_pass(self):
        value = aggregate_fixture()
        c = value["formal_analyses"]["C"]["costs"]["arms"]["dual+frozen"]["metrics"]
        del c["counts/warmup.scheduled_gradient_microsteps"]
        paired = value["formal_analyses"]["B"]["costs"]["field_minus_taper_descriptive"]
        paired["guarded_transition_cpu_ns"]["paired_paths"] = 1
        missing = audit.aggregate_checks(value)["cost_coverage_deficiencies"]
        self.assertTrue(any("dual+frozen: required cost metric absent" in v for v in missing))
        self.assertTrue(any("paired field-minus-taper metric guarded_transition_cpu_ns uses 1/48" in v for v in missing))

    def test_complete_original_sparse_counter_records_proven_zeros_not_missing_costs(self):
        value = aggregate_fixture()
        metrics = value["formal_analyses"]["B"]["costs"]["arms"]["field12"]["metrics"]
        metrics["rejected_blocks"] = {"paths": 1, "mean": 2., "minimum": 2., "maximum": 2., "sum_over_recorded_paths": 2.}
        result = audit.aggregate_checks(value)
        self.assertTrue(result["declared_cost_rows_complete"])
        row = result["per_path_cost_coverage"]["B"]["arms"]["field12"]
        self.assertEqual(row["schema_proven_zero_suppressed_path_counts"]["rejected_blocks"], 47)
        self.assertEqual(metrics["rejected_blocks"]["mean"], 2.)

    def test_no_real_gate_means_NOT_EVALUATED(self):
        output = io.StringIO()
        with patch("sys.argv", ["audit"]), contextlib.redirect_stdout(output):
            self.assertEqual(audit.main(), 2)
        result = json.loads(output.getvalue())
        self.assertEqual(result["status"], "NOT_EVALUATED")
        self.assertFalse(result["scientific_payloads_decoded"])

    def test_incomplete_review_refuses_before_import_or_scientific_read(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            path = Path(directory) / "COMPLETE.json"
            raw = json.dumps({"schema": "hepta.execution05.postseal-review-completion.1", "complete": False}).encode()
            path.write_bytes(raw)
            with patch.object(audit.importlib, "import_module", side_effect=AssertionError("No gate import allowed")):
                with self.assertRaisesRegex(ValueError, "did not complete"):
                    audit.read_after_review_complete(path, hashlib.sha256(raw).hexdigest())

    def test_completed_metadata_still_reenters_original_gate_before_any_outcome(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory)
            source = root / "operational/parameter_field_recovery06/postseal/review.py"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"# Engineering mock source only.\n")
            provenance = {"implementation": {"path": str(source), "bytes": source.stat().st_size,
                           "sha256": hashlib.sha256(source.read_bytes()).hexdigest()},
                          "arguments": {"fixture": True}, "supplement_wait4": {"fixture": True}}
            path = root / "COMPLETE.json"
            raw = json.dumps({"schema": "hepta.execution06.postseal-review-completion.1", "complete": True,
                              "status": "REVIEW_COMPLETE", "provenance": provenance}).encode()
            path.write_bytes(raw)
            gate = Mock(return_value={"gate": {"status": "NOT_ADMITTED"}})
            module = SimpleNamespace(__file__=str(source), open_gate=gate)
            with patch.object(audit.importlib, "import_module", return_value=module):
                with self.assertRaisesRegex(ValueError, "whole-study source/seal gate did not admit"):
                    audit.read_after_review_complete(path, hashlib.sha256(raw).hexdigest())
            gate.assert_called_once_with(provenance["arguments"], provenance["supplement_wait4"])


if __name__ == "__main__":
    unittest.main()
