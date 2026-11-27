"""MEM6 report and runner failures retain the complete planned roster."""

import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ndu_real_materials.common import binding, strict_json, write_json
from . import candidate_retention_public_report as reporting
from . import run_candidate_retention_public as runner
from .candidate_retention_report import unknown_episode
from .test_candidate_retention_public_plan import fixture_plan, request
from . import candidate_retention_public_plan as planning


class PublicRetentionReportTests(unittest.TestCase):
    def test_new_execution_sources_must_be_pinned_before_actor_planning(self):
        with tempfile.TemporaryDirectory() as temporary:
            value = request(Path(temporary))
            for name in (
                "candidate_retention_public_plan.py",
                "candidate_retention_public_report.py",
                "run_candidate_retention_public.py",
            ):
                bad = copy.deepcopy(value)
                bad["source_pins"] = [
                    pin
                    for pin in bad["source_pins"]
                    if pin["path"] != "scripts/ndu_real_runtime/" + name
                ]
                with (
                    self.subTest(source=name),
                    patch.object(planning, "prior_source_groups") as prior,
                ):
                    with self.assertRaisesRegex(ValueError, "Incomplete.*source pins"):
                        planning.freeze(bad, Path(temporary) / "unused")
                    prior.assert_not_called()

    def test_report_rejects_rebound_selector_budget_or_old_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            _, plan, _ = fixture_plan(Path(temporary))
            for mutation in (
                lambda p: p["episodes"][0].update(selector_mode="frozen_neural"),
                lambda p: p["episodes"][0]["candidate_selector_profile"].update(
                    mode="frozen_neural"
                ),
                lambda p: p["episodes"][0]["candidate_memory_profile"].update(
                    max_entries=127
                ),
                lambda p: p["episodes"][0].update(weights_sha256="0" * 64),
                lambda p: p["excluded_source_groups"].append("development"),
                lambda p: p.update(prior_episode_plans=[]),
                lambda p: p.update(cross_session_memory_evaluated=True),
            ):
                bad = copy.deepcopy(plan)
                mutation(bad)
                with self.assertRaises(ValueError):
                    reporting.validate_plan(bad)

    def test_unknown_noop_and_source_pairs_keep_all_denominators(self):
        with tempfile.TemporaryDirectory() as temporary:
            _, plan, _ = fixture_plan(Path(temporary))
            rows = []
            for expected in plan["episodes"][:-1]:
                row = unknown_episode(expected, "fixture")
                row.update(
                    evidence_status="VERIFIED",
                    terminal_status="Completed",
                    unconditional_success=True,
                    initial_correct=True,
                    no_op_success=True,
                    candidate_mediated_delivered=False,
                    fixed_selector_audit_verified=True,
                )
                rows.append(row)
            report = reporting.summarize(plan["episodes"], rows)
            self.assertEqual(
                report["paired_unconditional_success_difference"]["unknown_pairs"], 1
            )
            self.assertEqual(report["planned_episodes"], 12)
            self.assertEqual(report["source_group_count"], 2)
            self.assertEqual(
                sum(
                    p["no_op_successes"]
                    for key, p in report["panels"].items()
                    if key.endswith("/all_planned")
                ),
                11,
            )
            self.assertIsNone(
                report["paired_unconditional_success_difference"]["value"]
            )
            self.assertIsNone(
                report["costs"]["bounded"]["attempt_wall_seconds"]["sum_complete"]
            )
            self.assertEqual(report["scientific_acceptance"], "HOLD")

    def test_attempt_costs_are_byte_bound_and_invalid_values_reject(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            expected = {"original_operation_id": "pair-bounded"}
            path = root / "attempt.json"
            write_json(
                path,
                {
                    **expected,
                    "selector_mode": "public_rule",
                    "wall_seconds": 3.0,
                    "cpu_seconds": 1.0,
                },
            )
            item = {"attempt": binding(path, root)}
            self.assertEqual(
                reporting.episode_costs(root, item, expected, None),
                {
                    "attempt_wall_seconds": 3.0,
                    "attempt_cpu_seconds": 1.0,
                    "deployment_wall_seconds": None,
                },
            )
            with self.assertRaises(ValueError):
                reporting.episode_costs(
                    root, item, {"original_operation_id": "other"}, None
                )
            path.write_bytes(path.read_bytes() + b" ")
            with self.assertRaisesRegex(ValueError, "registered bytes"):
                reporting.episode_costs(root, item, expected, None)
            with self.assertRaises(ValueError):
                reporting.episode_costs(
                    root, {}, expected, {"deployment_meter": {"wall_seconds": -1}}
                )

    def test_absent_evidence_remains_unknown_in_frozen_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            value, plan, _ = fixture_plan(root)
            run = root / "run"
            manifest = {
                "schema": "ndu.real.candidate-retention-public-evidence.v1",
                "plan_sha256": binding(run / "PLAN.json", run)["sha256"],
                "episodes": [],
            }
            write_json(run / "EVIDENCE.json", manifest)
            with patch(
                "ndu_real_runtime.candidate_retention_public_plan.prior_source_groups",
                return_value=(
                    set(plan["prior_episode_source_groups"]),
                    plan["prior_episode_plans"],
                ),
            ):
                report = reporting.generate(
                    run,
                    value["config"]["material_root"],
                    manifest["plan_sha256"],
                    binding(run / "EVIDENCE.json", run)["sha256"],
                )
            self.assertEqual(
                [r["evidence_status"] for r in report["episodes"]], ["UNKNOWN"] * 12
            )
            self.assertEqual(
                report["paired_unconditional_success_difference"]["unknown_pairs"], 6
            )
            self.assertFalse(report["production_adoption"])

    def test_known_success_without_memory_or_selector_chain_is_not_attributable(self):
        from .candidate_retention_report import evaluate_episode
        from .test_candidate_retention_report import fixture

        for missing in ("memory", "selector"):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as tmp:
                args = fixture("bounded")
                if missing == "memory":
                    args[5][0] = None
                row = evaluate_episode(*args)
                self.assertTrue(row["unconditional_success"])
                if missing == "selector":
                    with self.assertRaises(FileNotFoundError):
                        reporting.shadow_choices(
                            Path(tmp), args[0], args[1], args[4], args[5], []
                        )
                report = reporting.summarize(
                    [args[0], fixture("current_only")[0]], [row]
                )
                self.assertEqual(
                    report["observed_terminal_success"]["bounded"]["numerator"], 1
                )
                self.assertIsNone(report["episodes"][0]["unconditional_success"])
                self.assertEqual(
                    report["paired_unconditional_success_difference"]["unknown_pairs"],
                    1,
                )

    def test_malformed_episode_shape_keeps_attempt_cost_and_other_denominators(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            value, plan, _ = fixture_plan(root)
            run, expected = root / "run", plan["episodes"][0]
            write_json(run / "bad-result.json", [])
            write_json(
                run / "attempt.json",
                {
                    "original_operation_id": expected["original_operation_id"],
                    "selector_mode": "public_rule",
                    "status": "Failed",
                    "wall_seconds": 3.0,
                    "cpu_seconds": 1.0,
                },
            )
            psha = binding(run / "PLAN.json", run)["sha256"]
            write_json(
                run / "EVIDENCE.json",
                {
                    "schema": "ndu.real.candidate-retention-public-evidence.v1",
                    "plan_sha256": psha,
                    "episodes": [
                        {
                            "original_operation_id": expected["original_operation_id"],
                            "result": binding(run / "bad-result.json", run),
                            "attempt": binding(run / "attempt.json", run),
                        }
                    ],
                },
            )
            with patch(
                "ndu_real_runtime.candidate_retention_public_plan.prior_source_groups",
                return_value=(
                    set(plan["prior_episode_source_groups"]),
                    plan["prior_episode_plans"],
                ),
            ):
                report = reporting.generate(
                    run,
                    value["config"]["material_root"],
                    psha,
                    binding(run / "EVIDENCE.json", run)["sha256"],
                )
            row = report["episodes"][0]
            self.assertEqual(row["evidence_status"], "REJECTED")
            self.assertEqual(row["costs"]["attempt_wall_seconds"], 3.0)
            self.assertEqual(row["attempt_terminal_status"], "Failed")
            self.assertEqual(report["planned_episodes"], 12)


class PublicRetentionRunnerTests(unittest.TestCase):
    def test_runner_passes_both_memory_modes_to_fixed_selector_host(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            value, _, jobs = fixture_plan(root)
            run = root / "run"
            (run / "attempts").mkdir()
            with patch("ndu_real_runtime.episode.EpisodeHost") as host:
                host.return_value.run.side_effect = RuntimeError(
                    "Injected isolation refusal; no actor result fabricated"
                )
                results = runner.run_pair(
                    value, run, jobs[0], binding(run / "PLAN.json", run)["sha256"]
                )
            self.assertEqual([r["status"] for r in results], ["Failed", "Failed"])
            profiles = [call.args[2] for call in host.call_args_list]
            self.assertEqual(
                {p["candidate_memory"]["mode"] for p in profiles},
                {"current_only", "bounded"},
            )
            self.assertEqual(
                [p["candidate_selector"]["mode"] for p in profiles],
                ["public_rule", "public_rule"],
            )
            self.assertEqual(
                {r["original_operation_id"] for r in results},
                {j["expected"]["original_operation_id"] for j in jobs[0]},
            )
            for row in results:
                self.assertIsNone(row["retry_of"])
                self.assertEqual(
                    strict_json(
                        (
                            run / "attempts" / (row["original_operation_id"] + ".json")
                        ).read_bytes()
                    ),
                    row,
                )

    def test_cli_uses_mem6_report_and_failed_run_exits_nonzero(self):
        args = ["mem6", "--request", "r", "--output", "o", "--independent-report"]
        with (
            patch("sys.argv", args),
            patch.object(runner, "run", return_value={"status": "Failed"}) as run,
        ):
            with self.assertRaises(SystemExit) as error:
                runner.main()
        self.assertEqual(error.exception.code, 1)
        self.assertIs(run.call_args.kwargs["report_generator"], reporting.generate)


if __name__ == "__main__":
    unittest.main()
