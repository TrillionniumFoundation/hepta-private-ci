"""Real owner effects under pause, deadline, ACK loss and bounded repair."""

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from skill_lifecycle import LifecycleDestination, SkillContract, goals_digest


class Clock:
    def __init__(self):
        self.now = 10

    def __call__(self):
        return self.now


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "destination"
        self.clock = Clock()
        self.task = {
            "id": "task",
            "version": 1,
            "goals": ["one", "two"],
            "fault": "normal",
        }
        self.contract = SkillContract(
            "task", 1, goals_digest(self.task["goals"]), 100, 1
        )

    def make(self, **changes):
        return LifecycleDestination(
            self.path, self.task, replace(self.contract, **changes), self.clock
        )

    def test_pause_resumes_original_deadline_without_mutations(self):
        d = self.make()
        d.inspect()
        d.pause()
        d.ensure()
        self.assertEqual(
            (d.state, d.owner.calls, d.owner.audit()["effect_count"]),
            ("PAUSED", ["observe"], 0),
        )
        self.clock.now = 20
        d.resume()
        d.ensure()
        self.assertEqual(
            (d.state, d.owner.audit()["effect_count"], d.contract.deadline_ns),
            ("RUNNING", 1, 100),
        )
        self.assertEqual(d.score(True)["effect_knowledge"], "UNKNOWN")

    def test_deadline_between_stage_and_apply_blocks_publication(self):
        d = self.make()
        d.inspect()
        original = d.owner.stage

        def stage(*args):
            result = original(*args)
            self.clock.now = 100
            return result

        with patch.object(d.owner, "stage", stage):
            d.ensure()
        self.assertEqual(
            (d.state, d.owner.calls, d.owner.audit()["effect_count"]),
            ("DEADLINE", ["observe", "stage"], 0),
        )
        self.assertTrue((self.path / "staged" / "0").exists())
        d.resume()
        d.ensure()
        self.assertNotIn("apply", d.owner.calls)
        self.assertFalse(d.inspect()["complete"])

    def test_expired_session_can_reconcile_original_completed_effect(self):
        self.task["goals"] = ["one"]
        self.contract = replace(
            self.contract, goals_digest=goals_digest(self.task["goals"])
        )
        d = self.make()
        d.inspect()
        d.ensure()
        self.clock.now = 101
        self.assertTrue(d.inspect()["complete"])
        result = d.score(True)
        self.assertEqual(
            (
                result["state"],
                result["effect_knowledge"],
                result["claimed_success"],
                result["end_to_end_ns"],
            ),
            ("DEADLINE", "CONFIRMED_COMPLETE", True, 91),
        )
        self.assertEqual(
            next((self.path / "effects").glob("*/value")).read_text(), "one"
        )

    def test_lost_ack_reconciles_without_duplicate_dispatch(self):
        self.task["fault"] = "lost_reply"
        d = self.make()
        d.inspect()
        d.ensure()
        self.assertIsNone(d.view)
        self.assertEqual(d.score(True)["claimed_success"], False)
        d.ensure()  # Observe original effect before considering the next goal.
        d.ensure()
        d.inspect()
        result = d.score(True)
        self.assertEqual(
            (
                result["complete"],
                result["lost_replies"],
                result["duplicate_effects"],
                d.owner.calls.count("apply"),
            ),
            (True, 1, 0, 2),
        )

    def test_only_confirmed_precommit_failure_uses_retry_budget(self):
        self.task["fault"] = "partial_failure"
        d = self.make()
        for _ in range(12):
            if d.view and d.view["complete"]:
                break
            d.ensure()
        result = d.score(True)
        self.assertEqual(
            (
                result["complete"],
                result["repair_count"],
                result["duplicate_effects"],
                d.owner.calls.count("apply"),
            ),
            (True, 1, 0, 3),
        )

    def test_exhausted_budget_blocks_retry_but_not_observation(self):
        self.task["fault"] = "partial_failure"
        d = self.make(max_retries=0)
        for _ in range(6):
            d.ensure()
        self.assertEqual(
            (d.state, d.owner.calls.count("apply"), d.owner.audit()["effect_count"]),
            ("RETRY_EXHAUSTED", 2, 1),
        )
        self.assertFalse(d.inspect()["complete"])
        d.resume()
        d.ensure()
        self.assertEqual(d.owner.calls.count("apply"), 2)

    def test_failed_read_drops_prior_completion_knowledge(self):
        self.task["goals"] = ["one"]
        self.contract = replace(
            self.contract, goals_digest=goals_digest(self.task["goals"])
        )
        d = self.make()
        d.inspect()
        d.ensure()
        self.assertTrue(d.inspect()["complete"])
        with patch.object(d.owner, "observe", side_effect=OSError("read unavailable")):
            with self.assertRaises(OSError):
                d.inspect()
        result = d.score(True)
        self.assertEqual(
            (result["complete"], result["effect_knowledge"], result["claimed_success"]),
            (True, "UNKNOWN", False),
        )

    def test_foreign_parameters_fail_before_owner_creation(self):
        for change in (
            {"task_id": "other"},
            {"version": True},
            {"goals_digest": "bad"},
            {"deadline_ns": True},
            {"max_retries": -1},
        ):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.make(**change)
            self.assertFalse(self.path.exists())

    def test_unclassified_reply_does_not_allow_redispatch(self):
        d = self.make()
        d.inspect()
        with patch.object(
            d.owner, "apply", return_value={"status": "unknown", "ack_lost": False}
        ) as apply:
            d.ensure()
            d.inspect()
            d.ensure()
            self.assertEqual(apply.call_count, 1)
        self.assertEqual(d.score(False)["effect_count"], 0)


if __name__ == "__main__":
    unittest.main()
