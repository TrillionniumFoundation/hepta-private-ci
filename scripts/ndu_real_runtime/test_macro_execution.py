"""Lifecycle and original-callback fixtures; no native policy efficacy claims."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ndu_real_materials import common
from . import macro_execution as execution
from .metacontrol_macro_contract import digest, sha
from .test_macro_execution_plan import plan_fixture
from .test_macro_realization import fixture, save, sync_steps


class RetainedFixtureHost:
    calls, failure, tamper = 0, None, False

    def __init__(self, config, case, profile, output, *, training):
        type(self).calls += 1
        if training or not (output.parent / "START.json").is_file():
            raise ValueError("Actor attempted before START or with training labels")
        if self.failure == "constructor":
            raise OSError("manufactured constructor failure")
        self.output, self.case = output, case
        output.mkdir()
        policy = common.strict_json(Path(profile["macro_policy"]["path"]).read_bytes())[
            "policy"
        ]
        macro = "STOP" if policy == "STOP" else "READ"
        data = fixture(output, macro=macro)
        for path in data["directory"].iterdir():
            path.rename(output / path.name)
        data["directory"].rmdir()
        self.records = common.strict_json((output / "trajectory.json").read_bytes())[
            "steps"
        ]
        state = {
            "features": self.records[0]["public_features"],
            "context_belief": [1.0],
            "pending_evidence": False,
            "freshness_seconds": 0.0,
            "remaining_seconds": 10.0,
            "legal_macros": ["STOP", "READ"],
        }
        for index, step in enumerate(self.records):
            step.update(
                case_id=case["id"],
                weights_sha256=profile["model_sha256"],
                controller={
                    "macro": macro,
                    "macro_step": index,
                    "macro_policy": policy,
                    "macro_public_state_sha256": digest(state),
                    "macro_deployment_sha256": profile["macro_policy"]["sha256"],
                },
            )
        self.records[0]["controller"]["macro_public_state"] = state
        self.template = common.strict_json((output / "public-input.json").read_bytes())
        self.template.update(case_id=case["id"], forced_action=None)
        self.template["delivery"]["case_id"] = case["id"]
        self.observation = self.template["observation"]
        self.public, self.steps = output / "public", []
        self.result = data["result"]
        self.result.update(
            original_operation_id=profile["original_operation_id"],
            case_id=case["id"],
            source_group_id=case["source_id"],
            source_sha256=case["source_sha256"],
        )
        snapshot = output / f"delivery-{len(self.records):02d}"
        delivery = common.strict_json((snapshot / "delivery.json").read_bytes())
        delivery["case_id"] = case["id"]
        save(snapshot / "delivery.json", delivery)
        score = self.result["score_components"]
        score.update(
            case_id=case["id"],
            source_group=case["source_id"],
            role=case["role"],
            reference_sha256=case["reference"]["sha256"],
            delivery_sha256=sha((snapshot / "delivery.json").read_bytes()),
        )
        save(snapshot / "evaluation.json", score)
        self.launch = common.strict_json((output / "launch.json").read_bytes())
        self.ready = common.strict_json(self.launch["stdout"].splitlines()[0])
        self.ready.update(
            case_id=case["id"], macro_policy_sha256=profile["macro_policy"]["sha256"]
        )

    def public_step(self):
        return common.json_bytes(
            {
                **self.template,
                "step": len(self.steps),
                "observation": self.observation,
                "remaining_seconds": 60.0,
            }
        )

    def run(self):
        if self.failure == "interrupt":
            raise KeyboardInterrupt("manufactured interrupted operation")
        if self.failure == "runtime":
            raise RuntimeError("manufactured uncertain host completion")
        replies = []
        for step in self.records:
            raw = self.public_step()
            replies.append(raw)
            step["remaining_seconds"] = common.strict_json(raw)["remaining_seconds"]
            self.steps.append(step)
        self.launch["stdout"] = "\n".join(
            json.dumps(e) for e in [self.ready, *self.steps]
        )
        save(self.output / "launch.json", self.launch)
        sync_steps(self.output, self.steps)
        launch = common.strict_json((self.output / "launch.json").read_bytes())
        for raw, exchange in zip(replies, launch["host_exchanges"]):
            exchange.update(reply_sha256=sha(raw), reply_bytes=len(raw))
        save(self.output / "launch.json", launch)
        save(self.output / "result.json", self.result)
        if self.tamper is True:
            path = self.output / "macro-public-00.json"
            path.write_bytes(path.read_bytes() + b" ")
        elif self.tamper == "ready":
            self.ready["macro_policy_sha256"] = "0" * 64
            launch["stdout"] = "\n".join(
                json.dumps(e) for e in [self.ready, *self.steps]
            )
            save(self.output / "launch.json", launch)
            sync_steps(self.output, self.steps)
        elif self.tamper == "ordinal":
            self.steps[0]["controller"]["macro_step"] = False
            sync_steps(self.output, self.steps)
        return self.result


class MacroExecutionTests(unittest.TestCase):
    def run_plan(self, plan, output, host=RetainedFixtureHost):
        return execution.execute(
            plan,
            output,
            expected_plan_sha256=digest(plan),
            host_class=host,
            allow_fixtures=True,
        )

    def test_registered_cartesian_execution_captures_exact_raw_callbacks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = plan_fixture(root)
            report = self.run_plan(plan, root / "run")
            self.assertEqual([r["status"] for r in report["rows"]], ["COMPLETED"] * 4)
            self.assertFalse(
                report["cohort"]["registered_full_cost_comparison_complete"]
            )
            for row in report["rows"]:
                branch = root / "run" / row["execution_id"] / "native"
                raw = (branch / "macro-public-00.json").read_bytes()
                launch = common.strict_json((branch / "launch.json").read_bytes())
                self.assertEqual(launch["host_exchanges"][0]["reply_sha256"], sha(raw))
                self.assertEqual(common.strict_json(raw)["remaining_seconds"], 10.0)
                self.assertNotIn(b"expected_text", raw)
                self.assertIs(row["full_cost_observed"], False)
                self.assertGreater(row["task_cost"], 0)
            with self.assertRaises(FileExistsError):
                self.run_plan(plan, root / "run")

    def test_step_iterators_interleave_original_outcomes_and_keep_full_denominators(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            runs, expected, streams, observed = [], [], [], []
            initial_calls = RetainedFixtureHost.calls
            for name in ("first", "second"):
                root = Path(tmp) / name
                root.mkdir()
                plan = plan_fixture(root)
                pin = digest(plan)
                order = [entry[0] for entry in execution._roster(plan, pin)][::-1]
                output = root / "run"
                streams.append(
                    execution.execute_steps(
                        plan,
                        output,
                        expected_plan_sha256=pin,
                        host_class=RetainedFixtureHost,
                        allow_fixtures=True,
                        operation_order=order,
                    )
                )
                runs.append((output, pin))
                expected.append(order)
                self.assertTrue((output / "PLAN.json").is_file())
                self.assertTrue((output / "RUN.json").is_file())
                self.assertEqual(RetainedFixtureHost.calls, initial_calls)
                unstarted = execution.reconcile(
                    output, expected_plan_sha256=pin, allow_fixtures=True
                )
                self.assertEqual(
                    [row["status"] for row in unstarted["rows"]], ["NOT_STARTED"] * 4
                )
            for index in range(4):
                for mode, (output, pin) in enumerate(runs):
                    operation = next(streams[mode])
                    self.assertEqual(operation, expected[mode][index])
                    observed.append((mode, operation))
                    self.assertTrue((output / operation / "TERMINAL.json").is_file())
                    report = execution.reconcile(
                        output, expected_plan_sha256=pin, allow_fixtures=True
                    )
                    self.assertEqual(report["cohort"]["planned_executions"], 4)
                    self.assertEqual(
                        [r["status"] for r in report["rows"]].count("COMPLETED"),
                        index + 1,
                    )
                    self.assertEqual(
                        [r["status"] for r in report["rows"]].count("NOT_STARTED"),
                        3 - index,
                    )
            starts = [
                (
                    common.strict_json(
                        (output / operation / "START.json").read_bytes()
                    )["time_ns"],
                    mode,
                    operation,
                )
                for mode, (output, _) in enumerate(runs)
                for operation in expected[mode]
            ]
            self.assertEqual(
                [(mode, operation) for _, mode, operation in sorted(starts)], observed
            )
            for stream in streams:
                with self.assertRaises(StopIteration):
                    next(stream)

    def test_invalid_step_order_fails_before_output_or_actor(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = plan_fixture(root)
            pin = digest(plan)
            order = [entry[0] for entry in execution._roster(plan, pin)]
            for invalid in (
                order[:-1],
                [order[0]] * len(order),
                [*order, "unknown"],
                [*order[:-1], "unknown"],
                [*order[:-1], False],
                order[0],
            ):
                with (
                    self.subTest(order=invalid),
                    patch.object(
                        RetainedFixtureHost,
                        "__init__",
                        side_effect=AssertionError("actor before order validation"),
                    ) as actor,
                ):
                    with self.assertRaises(ValueError):
                        list(
                            execution.execute_steps(
                                plan,
                                root / "run",
                                expected_plan_sha256=pin,
                                host_class=RetainedFixtureHost,
                                allow_fixtures=True,
                                operation_order=invalid,
                            )
                        )
                    actor.assert_not_called()
                    self.assertFalse((root / "run").exists())

    def test_interruption_keeps_missing_whole_source_and_readonly_reconcile(self):
        class Interrupted(RetainedFixtureHost):
            failure = "interrupt"

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = plan_fixture(root)
            output = root / "run"
            with self.assertRaises(KeyboardInterrupt):
                self.run_plan(plan, output, Interrupted)
            before = {str(p): p.read_bytes() for p in output.rglob("*") if p.is_file()}
            with patch.object(
                Interrupted, "run", side_effect=AssertionError("read-only")
            ):
                report = execution.reconcile(
                    output, expected_plan_sha256=digest(plan), allow_fixtures=True
                )
            self.assertEqual(
                [r["status"] for r in report["rows"]],
                ["UNKNOWN", *(["NOT_STARTED"] * 3)],
            )
            self.assertTrue(all(r["task_cost"] is None for r in report["rows"]))
            self.assertEqual(report["cohort"]["planned_executions"], 4)
            self.assertEqual(
                {str(p): p.read_bytes() for p in output.rglob("*") if p.is_file()},
                before,
            )

    def test_constructor_and_runtime_failure_keep_distinct_unknown_semantics(self):
        for failure, status in (("constructor", "FAILED"), ("runtime", "UNKNOWN")):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as tmp:
                host = type("FailedHost", (RetainedFixtureHost,), {"failure": failure})
                root = Path(tmp)
                report = self.run_plan(plan_fixture(root), root / "run", host)
                self.assertEqual([r["status"] for r in report["rows"]], [status] * 4)
                self.assertTrue(
                    all(
                        r["quality"] is None and r["task_cost"] > 0
                        for r in report["rows"]
                    )
                )
                self.assertTrue(
                    all(t["runner_error"] is not None for t in report["terminals"])
                )

    def test_fixture_optin_duplicate_outcome_and_public_tampering_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = plan_fixture(root)
            with self.assertRaises(ValueError):
                execution.execute(
                    plan,
                    root / "run",
                    expected_plan_sha256=digest(plan),
                    host_class=RetainedFixtureHost,
                )
            host = type("TamperedHost", (RetainedFixtureHost,), {"tamper": True})
            report = self.run_plan(plan, root / "run", host)
            self.assertEqual([r["status"] for r in report["rows"]], ["FAILED"] * 4)
            self.assertTrue(
                all(
                    t["native_terminal_status"] == "Completed"
                    for t in report["terminals"]
                )
            )
            directory = root / "run" / report["rows"][0]["execution_id"]
            (directory / "TERMINAL-copy.json").write_bytes(
                (directory / "TERMINAL.json").read_bytes()
            )
            with self.assertRaises(ValueError):
                execution.reconcile(
                    root / "run", expected_plan_sha256=digest(plan), allow_fixtures=True
                )

    def test_actual_policy_readiness_and_macro_ordinals_are_bound(self):
        for change in ("ready", "ordinal"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                host = type(
                    "TamperedPolicy", (RetainedFixtureHost,), {"tamper": change}
                )
                report = self.run_plan(plan_fixture(root), root / "run", host)
                self.assertEqual([r["status"] for r in report["rows"]], ["FAILED"] * 4)


if __name__ == "__main__":
    unittest.main()
