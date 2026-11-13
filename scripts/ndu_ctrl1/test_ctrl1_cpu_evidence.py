"""Targeted CPU termination and complete-roster failures; no full campaign."""

import copy
from dataclasses import asdict, replace
from fractions import Fraction
import json
import os
from pathlib import Path
import signal
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ndu_ctrl1 import sensitivity_run as campaign
from ndu_ctrl1.budget_sensitivity import checkpoint_is_complete, classify_termination
from ndu_ctrl1.learning import _sha, train_actor_critic
from ndu_ctrl1.model import Profile, Scenario, initial_state


def tiny_roster():
    profile = "a" * 64
    plan = {
        "profiles": [{"digest": profile}],
        "training_seeds": [7],
        "cpu_caps_seconds": [1],
        "methods": ["actor_critic", "distillation"],
        "confirmation": [{"id": "c1"}, {"id": "c2"}],
        "expected_workers": 2,
        "expected_comparison_rows": 4,
    }
    receipts, rows = [], []
    for method in plan["methods"]:
        key = f"{profile[:12]}-7-1-{method}"
        receipts.append(
            {
                "id": key,
                "profile_id": profile,
                "seed": 7,
                "method": method,
                "hard_worker_cpu_seconds": 1,
                "candidate_status": "NoCandidate",
                "source_drift": False,
                "parent_error": None,
                "worker_inclusive_cpu_seconds": 0.1,
                "completed_epochs": 0,
                "parameters_sha256": None,
            }
        )
        for scenario in ("c1", "c2"):
            rows.append(
                {
                    "attempt_id": key,
                    "scenario_id": scenario,
                    "profile_id": profile,
                    "training_seed": 7,
                    "cpu_cap_seconds": 1,
                    "method": method,
                    "candidate_status": "NoCandidate",
                    "worker_cpu_seconds": 0.1,
                    "retained_epochs": 0,
                    "parameters_sha256": None,
                    "value": None,
                    "policy_gap": None,
                }
            )
    return plan, receipts, rows


@unittest.skipUnless(
    hasattr(os, "waitstatus_to_exitcode"), "POSIX wait status is required"
)
class TerminationTests(unittest.TestCase):
    def test_clean_exit_requires_a_valid_completion_receipt(self):
        for status in ("Completed", "CpuBudgetStop"):
            self.assertTrue(
                classify_termination(0, {"status": status})[
                    "allows_retained_checkpoint"
                ]
            )
        for wait_status, worker in (
            (0, {}),
            (1 << 8, {"status": "Completed"}),
            (0, {"status": "Failed"}),
        ):
            self.assertFalse(
                classify_termination(wait_status, worker)["allows_retained_checkpoint"]
            )

    def test_only_explicit_cpu_signal_is_eligible_not_sigkill_or_other_signals(self):
        cpu = classify_termination(int(signal.SIGXCPU), {})
        self.assertEqual(
            (cpu["kind"], cpu["signal"], cpu["allows_retained_checkpoint"]),
            ("CpuBudgetSignal", "SIGXCPU", True),
        )
        for number, kind in (
            (signal.SIGKILL, "AmbiguousSigkill"),
            (signal.SIGALRM, "WallAlarmSignal"),
            (signal.SIGTERM, "UnexpectedSignal"),
            (signal.SIGSEGV, "UnexpectedSignal"),
        ):
            result = classify_termination(int(number), {})
            self.assertEqual(
                (
                    result["kind"],
                    result["exit_code"],
                    result["allows_retained_checkpoint"],
                ),
                (kind, -int(number), False),
            )
        self.assertFalse(
            classify_termination(int(signal.SIGXCPU), {"status": "Failed"})[
                "allows_retained_checkpoint"
            ]
        )

    def test_complete_epoch_is_bound_to_attempt_and_initial_only_is_unavailable(self):
        profile, scenario = Profile(), Scenario(prior=Fraction(3, 4), horizon=1)
        examples = [
            (
                scenario,
                replace(initial_state(scenario), budget_left=scenario.budget - 1),
            )
        ]
        model = train_actor_critic(
            examples, profile, seed=7, epochs=1, cpu_budget_seconds=0.9
        )
        record = model.record()
        plan = {
            "method": "actor_critic",
            "seed": 7,
            "max_epochs": 1,
            "examples": 1,
            "examples_sha256": _sha(examples),
            "profile_sha256": _sha(profile),
            "soft_training_cpu_seconds": 0.9,
        }
        self.assertTrue(checkpoint_is_complete(record, plan))
        with self.assertRaisesRegex(ValueError, "does not belong"):
            checkpoint_is_complete(record, {**plan, "seed": 8})
        initial = train_actor_critic(
            examples, profile, seed=7, epochs=1, cpu_budget_seconds=1e-12
        ).record()
        self.assertFalse(
            checkpoint_is_complete(
                initial, {**plan, "soft_training_cpu_seconds": 1e-12}
            )
        )


class RosterTests(unittest.TestCase):
    def test_all_unavailable_attempts_still_have_their_full_rows(self):
        plan, receipts, rows = tiny_roster()
        campaign.validate_complete(plan, receipts, rows)
        with self.assertRaisesRegex(ValueError, "incomplete"):
            campaign.validate_complete(plan, receipts, rows[:-1])

    def test_duplicate_worker_or_case_is_not_a_complete_denominator(self):
        plan, receipts, rows = tiny_roster()
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            campaign.validate_complete(plan, [receipts[0], receipts[0]], rows)
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            campaign.validate_complete(plan, receipts, rows[:-1] + [rows[0]])
        with self.assertRaisesRegex(ValueError, "incomplete"):
            campaign.validate_complete(plan, receipts[:-1], rows)

    def test_unavailable_scores_and_receipt_cost_substitution_are_rejected(self):
        plan, receipts, rows = tiny_roster()
        fabricated = copy.deepcopy(rows)
        fabricated[0].update(value=0.5, policy_gap=0.0)
        with self.assertRaisesRegex(ValueError, "fabricated"):
            campaign.validate_complete(plan, receipts, fabricated)
        changed = copy.deepcopy(rows)
        changed[0]["worker_cpu_seconds"] = 0.05
        with self.assertRaisesRegex(ValueError, "different worker"):
            campaign.validate_complete(plan, receipts, changed)

    def test_frozen_plan_denominators_cannot_be_silently_changed(self):
        plan, receipts, rows = tiny_roster()
        with self.assertRaisesRegex(ValueError, "Cartesian"):
            campaign.validate_complete(
                {**plan, "expected_comparison_rows": 3}, receipts, rows
            )
        with self.assertRaisesRegex(ValueError, "duplicated"):
            campaign.expected_rosters({**plan, "training_seeds": [7, 7]})

    def test_parent_failure_has_terminal_event_and_inventoried_original(self):
        profile, scenario = Profile(), Scenario(horizon=1)
        examples = [
            (
                scenario,
                replace(initial_state(scenario), budget_left=scenario.budget - 1),
            )
        ]
        identity = "confirmation-" + campaign.digest(asdict(scenario))[:16]

        def fail_worker(*args):
            directory = args[-1]
            directory.mkdir(parents=True)
            (directory / "partial-original.bin").write_bytes(
                b"retained failure original"
            )
            raise RuntimeError("injected parent-side transport failure")

        with tempfile.TemporaryDirectory(prefix="ctrl1-cpu-failure-") as temporary:
            output = Path(temporary) / "failed-run"
            with (
                patch.multiple(campaign, SEEDS=(7,), CPU_CAPS=(1,)),
                patch.object(campaign, "profiles", return_value=[profile]),
                patch.object(
                    campaign, "scenarios", return_value=[(identity, scenario)]
                ),
                patch.object(
                    campaign, "examples_for_training", return_value=(examples, [])
                ),
                patch.object(campaign, "run_budget_worker", side_effect=fail_worker),
            ):
                with self.assertRaisesRegex(RuntimeError, "transport failure"):
                    campaign.run(output)
            report = json.loads((output / "REPORT.json").read_bytes())
            inventory = json.loads((output / "ARTIFACTS.json").read_bytes())
            events = [
                json.loads(line)
                for line in (output / "attempts.jsonl").read_bytes().splitlines()
            ]
            self.assertEqual(
                [event["status"] for event in events], ["Started", "ParentFailed"]
            )
            self.assertEqual(report["status"], "FAILED_CPU_ALLOWANCE_SENSITIVITY")
            self.assertEqual(inventory["status"], report["status"])
            self.assertEqual(
                (report["worker_attempts"], report["expected_workers"]), (0, 2)
            )
            self.assertIn("FAILURE.json", inventory["files"])
            self.assertTrue(
                any(
                    name.endswith("partial-original.bin") for name in inventory["files"]
                )
            )


if __name__ == "__main__":
    unittest.main()
