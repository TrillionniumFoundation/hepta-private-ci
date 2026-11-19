"""Evidence accounting tests; test fixtures are not scientific observations."""

import json
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from . import run_neuroscience as runner
from .protocol import canonical_digest


class NeuroscienceRunnerTests(unittest.TestCase):
    def specs(self):
        return [
            {"attempt_id": str(i), "family": "fixture", "method": "fixture", "seed": i}
            for i in range(3)
        ]

    def test_failed_attempt_stays_in_denominator_and_plan_precedes_execution(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "run"

            def run(spec):
                plan = json.loads((output / "PLAN.json").read_text())
                self.assertEqual(plan["plan"]["roster"], self.specs())
                if spec["seed"] == 1:
                    raise RuntimeError("injected test-only failure")
                return {**spec, "status": "completed", "fixture": True}

            result = runner.execute(output, self.specs(), {"fixture": run})
            self.assertEqual(result["attempt_summary"]["counts"]["completed"], 2)
            self.assertEqual(result["attempt_summary"]["counts"]["failed"], 1)
            self.assertEqual(result["status"], "DEVELOPMENT_EXECUTION_INCOMPLETE")
            with self.assertRaises(FileExistsError):
                runner.execute(output, self.specs(), {"fixture": run})
            self.assertEqual(
                runner.inspect_run(output)["attempt_records"], result["attempt_records"]
            )

    def test_interrupt_retains_unstarted_slots_without_retrying(self):
        calls = []

        def interrupt(spec):
            calls.append(spec["attempt_id"])
            raise KeyboardInterrupt()

        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "run"
            with self.assertRaises(KeyboardInterrupt):
                runner.execute(output, self.specs(), {"fixture": interrupt})
            counts = runner.inspect_run(output)["attempt_summary"]["counts"]
            self.assertEqual((counts["cancelled"], counts["unstarted"]), (1, 2))
            self.assertEqual(calls, ["0"])

    def test_identity_change_is_failure_and_source_change_prevents_completion(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "run"
            with patch.object(
                runner, "inventory", side_effect=[{"digest": "a"}, {"digest": "b"}]
            ):
                result = runner.execute(
                    output,
                    self.specs()[:1],
                    {
                        "fixture": lambda spec: {
                            **spec,
                            "attempt_id": "foreign",
                            "status": "completed",
                        }
                    },
                )
            self.assertFalse(result["source_unchanged"])
            self.assertEqual(result["attempt_summary"]["counts"]["failed"], 1)

    def test_tampered_plan_and_orphan_finish_cannot_be_read_as_success(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "run"
            runner.execute(
                output,
                self.specs()[:1],
                {
                    "fixture": lambda spec: {
                        **spec,
                        "status": "completed",
                        "fixture": True,
                    }
                },
            )
            next((output / "attempts").glob("*.started.json")).unlink()
            with self.assertRaisesRegex(ValueError, "lacks original start"):
                runner.inspect_run(output)
            plan_path = output / "PLAN.json"
            plan = json.loads(plan_path.read_text())
            plan["plan"]["roster"][0]["seed"] = 99
            plan_path.write_text(json.dumps(plan))
            with self.assertRaisesRegex(ValueError, "plan digest"):
                runner.inspect_run(output)

    def test_source_failure_and_missing_end_remain_incomplete_during_inspection(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "changed"
            with patch.object(
                runner, "inventory", side_effect=[{"digest": "a"}, {"digest": "b"}]
            ):
                result = runner.execute(
                    output,
                    self.specs()[:1],
                    {
                        "fixture": lambda spec: {
                            **spec,
                            "status": "completed",
                            "fixture": True,
                        }
                    },
                )
            self.assertFalse(result["execution_complete"])
            inspected = runner.inspect_run(output)
            self.assertFalse(inspected["source_unchanged"])
            self.assertFalse(inspected["execution_complete"])
            with (
                patch.object(runner.sys, "argv", ["runner", "--inspect", str(output)]),
                patch("builtins.print"),
            ):
                self.assertEqual(runner.main(), 1)
            (output / "RUN_END.json").unlink()
            inspected = runner.inspect_run(output)
            self.assertTrue(inspected["attempt_summary"]["complete"])
            self.assertIsNone(inspected["source_unchanged"])
            self.assertFalse(inspected["execution_complete"])
            self.assertFalse(inspected["run_end_present"])
            with (
                patch.object(runner.sys, "argv", ["runner", "--inspect", str(output)]),
                patch("builtins.print"),
            ):
                self.assertEqual(runner.main(), 1)

    def test_executor_mutation_cannot_reidentify_or_expand_the_frozen_request(self):
        specs = [{**self.specs()[0], "budget": {"steps": 1}}]
        original = copy.deepcopy(specs)

        def mutate(spec):
            spec["seed"] = 99
            spec["budget"]["steps"] = 999
            return {**spec, "status": "completed"}

        with tempfile.TemporaryDirectory() as temp:
            result = runner.execute(Path(temp) / "run", specs, {"fixture": mutate})
            self.assertEqual(specs, original)
            self.assertEqual(result["attempt_summary"]["counts"]["failed"], 1)
            self.assertIn(
                "mutated the frozen request", result["attempt_records"][0]["reason"]
            )
            self.assertFalse(result["execution_complete"])

    def test_returned_full_specification_and_terminal_state_are_checked(self):
        specs = [{**self.specs()[0], "budget": {"steps": 1}}]
        for change in (
            {"budget": {"steps": 999}},
            {"seed": False},
            {"status": "running"},
        ):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as temp:
                result = runner.execute(
                    Path(temp) / "run",
                    specs,
                    {
                        "fixture": lambda spec: {
                            **spec,
                            "status": "completed",
                            **change,
                        }
                    },
                )
                self.assertEqual(result["attempt_summary"]["counts"]["failed"], 1)

    def test_checksums_and_nested_outcomes_prevent_relabeling_failed_work(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "run"
            runner.execute(
                output,
                self.specs()[:1],
                {
                    "fixture": lambda spec: {
                        **spec,
                        "status": "failed",
                        "reason": "original failure",
                    }
                },
            )
            finish = next((output / "attempts").glob("*.finished.json"))
            event = json.loads(finish.read_text())
            event["record"]["status"] = "completed"
            finish.write_text(json.dumps(event))
            with self.assertRaisesRegex(ValueError, "record digest"):
                runner.inspect_run(output)
            event["record_digest"] = canonical_digest(event["record"])
            finish.write_text(json.dumps(event))
            with self.assertRaisesRegex(ValueError, "nested outcome"):
                runner.inspect_run(output)
            start = next((output / "attempts").glob("*.started.json"))
            event = json.loads(start.read_text())
            event["record"]["status"] = "completed"
            event["record_digest"] = canonical_digest(event["record"])
            start.write_text(json.dumps(event))
            with self.assertRaisesRegex(ValueError, "original running record"):
                runner.inspect_run(output)

    def test_source_metadata_and_final_event_set_are_bound(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "run"
            runner.execute(
                output,
                self.specs()[:1],
                {
                    "fixture": lambda spec: {
                        **spec,
                        "status": "completed",
                        "fixture": True,
                    }
                },
            )
            path = output / "PLAN.json"
            original = path.read_text()
            plan = json.loads(original)
            plan["source"] = {"digest": "wrong source"}
            path.write_text(json.dumps(plan))
            with self.assertRaisesRegex(ValueError, "binding digest"):
                runner.inspect_run(output)
            path.write_text(original)
            finish = next((output / "attempts").glob("*.finished.json"))
            event = json.loads(finish.read_text())
            event["record"]["result"]["fixture"] = "changed observation"
            event["record_digest"] = canonical_digest(event["record"])
            finish.write_text(json.dumps(event))
            with self.assertRaisesRegex(ValueError, "differ from run-end"):
                runner.inspect_run(output)

    def test_unplanned_failure_cannot_disappear_from_the_denominator(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "run"
            runner.execute(
                output,
                self.specs()[:2],
                {
                    "fixture": lambda spec: {
                        **spec,
                        "status": "completed" if spec["seed"] == 0 else "failed",
                        "reason": None if spec["seed"] == 0 else "original failure",
                    }
                },
            )
            path = output / "PLAN.json"
            plan = json.loads(path.read_text())
            plan["plan"]["roster"].pop()
            plan["plan_digest"] = canonical_digest(plan["plan"])
            plan["binding_digest"] = canonical_digest(
                {key: plan[key] for key in ("plan", "source", "git")}
            )
            path.write_text(json.dumps(plan))
            with self.assertRaisesRegex(ValueError, "unplanned"):
                runner.inspect_run(output)

    def test_run_end_supports_recovery_without_the_derived_result_report(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "run"
            result = runner.execute(
                output,
                self.specs()[:1],
                {
                    "fixture": lambda spec: {
                        **spec,
                        "status": "completed",
                        "fixture": True,
                    }
                },
            )
            (output / "RESULT.json").unlink()
            inspected = runner.inspect_run(output)
            self.assertTrue(inspected["execution_complete"])
            self.assertEqual(inspected["attempt_records"], result["attempt_records"])


if __name__ == "__main__":
    unittest.main()
