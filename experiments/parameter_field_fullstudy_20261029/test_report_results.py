"""Synthetic barriers, non-additive historical subtotals, and nuisance identities."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from . import report_results as report


class ReportResultsTests(unittest.TestCase):
    def test_blocked_status_never_opens_efficacy(self):
        spec = {"schema": report.SCHEMA, "attempt_id": "attempt02", "stages": {
            phase: {"status": "BLOCKED", "endpoint": {"path": "/must-not-open"}} for phase in report.PHASES}}
        with patch.object(report, "ready_operations", side_effect=AssertionError("early outcome access")):
            value = report.assemble(spec)
        self.assertEqual(value["status"], "BLOCKED")
        self.assertFalse(value["efficacy_artifacts_opened"])
        self.assertIsNone(value["actual_costs"])
        self.assertIn("Planned work is separate", report.render(value))

    def test_failed_cost_subtotals_are_not_added_twice(self):
        with tempfile.TemporaryDirectory() as tmp:
            def saved(name, value):
                path = Path(tmp) / name
                path.write_text(json.dumps(value))
                return {"path": str(path), "bytes": path.stat().st_size, "sha256": report.sha(path)}
            preflights = [saved(f"preflight-{i}.json", {"schema": "hepta.fullstudy.real-kernel-preflight.1", "complete": True,
                         "costs": {"scheduled_gradient_microsteps": 432}, "wall_seconds": 19. + i}) for i in range(2)]
            failed = saved("infrastructure.json", {"schema": "hepta.fullstudy.infrastructure-failure.1",
                           "known_scheduled_gradient_microsteps_lower_bound": {"attempt01_training_total": 102320,
                           "attempt01_preflight": 432, "earlier_disk_preflight": 432, "all_known_before_retry": 103184}})
            spec = {"engineering_preflights": preflights, "failed_attempts": [{"receipt": failed,
                    "training_microsteps_lower_bound": 102320, "engineering_microsteps_included": 0, "unknown_additional_work": True}]}
            self.assertEqual(report.prior_costs(spec)["gradient_microsteps_known_lower_bound"], 103184)
            spec["engineering_preflights"] = [preflights[0], preflights[0]]
            with self.assertRaisesRegex(ValueError, "Duplicate engineering"):
                report.prior_costs(spec)

    def test_legal_hash_diversity_is_not_parameter_diversity(self):
        branches = [{"action": action, "first": {"dynamics": str(action > 0),
                    "components": {"parameters": "p", "optimizer": "m", "gradients": str(action > 0)}}} for action in range(4)]
        template = {"branches": branches, "baseline": 2, "action_values": [0.] * 4, "advantages": [0.] * 4, "prefix_replay_equal": True}
        rows = [deepcopy(template) for unused in range(48)]
        rows[0]["branches"][3]["first"]["components"]["parameters"] = "changed"
        counts = report.bank_diagnostics({"complete": True, "seed": 17, "records": rows, "heads": {}})["counts"]
        self.assertEqual(counts["parents_with_multiple_complete_legal_hashes"], 48)
        self.assertEqual(counts["parents_with_multiple_parameter_optimizer_successors"], 1)
        self.assertEqual(counts["parents_with_hash_diversity_only_in_other_components"], 47)

    def test_parameter_divergence_clock_and_negative_development_are_preserved(self):
        trace = [{"transaction": {"end": (i + 1) * 48, "after": {"parameters": "p", "optimizer": "m"}, "accepted": True},
                  "choice": {"override": False}} for i in range(6)]
        ordinary = {"seed": 17, "schedule_id": 1, "method": "ordinary", "trace": trace}
        field = {**ordinary, "method": "field12", "trace": deepcopy(trace), "first_legal_divergence_clock": 48}
        field["trace"][2]["transaction"]["after"]["optimizer"] = "different"
        value = report.path_diagnostics([ordinary, field], "A")[1]
        self.assertEqual(value["first_complete_legal_hash_divergence_clock"], 48)
        self.assertEqual(value["first_parameter_optimizer_divergence_clock"], 144)
        records = [{"seed": seed, "method": method, "role": role,
                    "values": {o: [-1. if method == "field12" else 0.] for o in ("reward", "audit")}}
                   for seed in report.SEEDS for method in ("ordinary", "field12", "history6", "full_current_state", "frozen") for role in ("task", "clean")]
        self.assertEqual(report.development_summary(records)["effects"]["field12-ordinary task"]["point"]["audit"], -1.)


if __name__ == "__main__":
    unittest.main()
