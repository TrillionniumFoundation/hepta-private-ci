"""Manufactured factorial contracts; no native execution or efficacy evidence."""

from collections import Counter
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
import runpy
import tempfile
import unittest
from unittest.mock import patch

import ctrl_macro_factorial as factorial
import ctrl_macro_study as study
from ndu_real_runtime import macro_execution, macro_policy
from ndu_real_runtime.critic_context import context_digest
from ndu_real_runtime.metacontrol_macro_contract import digest
from ndu_real_runtime.test_macro_actor import fixture_deployment
from ndu_real_runtime.test_macro_execution_plan import plan_fixture
from ndu_real_runtime.test_macro_training_fixtures import save


def file_pin(path):
    return {"path": str(path), "sha256": study.sha(path.read_bytes())}


class FactorialContracts(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        base = plan_fixture(self.root)
        self.base = base
        self.repository = str(Path(__file__).resolve().parents[1])
        self.modules = study.modules(self.repository)
        self.studies, self.contexts, self.executions = {}, {}, {}
        self.args = SimpleNamespace(
            repository=self.repository,
            output=str(self.root / "factorial"),
            frozen_dir=str(self.root / "frozen"),
            adapted_dir=str(self.root / "adapted"),
            frozen_freeze="1" * 64,
            adapted_freeze="2" * 64,
        )
        receipt = {
            "schema": "ctrl.content-adaptation.v1",
            "status": "COMPLETED",
            "freeze_sha256": self.args.frozen_freeze,
            "base_weights_sha256": base["profiles"]["STOP"]["model_sha256"],
            "weights_sha256": study.sha(b"manufactured adapted parameters"),
            "initial_content_sha256": "3" * 64,
            "final_content_sha256": "4" * 64,
            "parameter_sha256": "5" * 64,
            "cold_load_parameter_sha256": "5" * 64,
            "training": {"optimizer_steps": 3},
            "fit_sources": ["a", "b"],
        }
        adapted_weights = self.root / "adapted-content/weights.pt"
        adapted_weights.parent.mkdir()
        adapted_weights.write_bytes(b"manufactured adapted parameters")
        self.receipt = receipt
        self.receipt_path = adapted_weights.with_name("receipt.json")
        save(self.receipt_path, receipt)
        self.args.adaptation_receipt = str(self.receipt_path)
        self.args.adaptation_sha256 = study.sha(self.receipt_path.read_bytes())
        for mode in factorial.MODES:
            directory = Path(getattr(self.args, mode + "_dir"))
            directory.mkdir()
            profile = {
                k: v for k, v in base["profiles"]["STOP"].items() if k != "macro_policy"
            }
            source_pins = deepcopy(base["source_pins"])
            if mode == "adapted":
                profile.update(
                    weights=str(adapted_weights),
                    model_sha256=receipt["weights_sha256"],
                    training_receipt_sha256=self.args.adaptation_sha256,
                )
                source_pins.append(file_pin(self.receipt_path))
            plan = {
                "profile": profile,
                "config": deepcopy(base["config"]),
                "source_splits": {
                    "train": ["a", "b"],
                    "calibration": ["cal" + str(i) for i in range(10)],
                    "future": [],
                },
                "pairs": [{"pair_id": "registered-train-pair"}],
                "action_budget_seconds": base["action_budget_seconds"],
                "source_pins": source_pins,
            }
            context = study.context_for(plan, self.modules)
            deployment = fixture_deployment(
                context=context, weights=profile["model_sha256"]
            )
            checkpoint = deployment["checkpoint_utf8"].encode()
            (directory / "CHECKPOINT.json").write_bytes(checkpoint)
            save(directory / "CHECKPOINT_PIN.json", {"sha256": study.sha(checkpoint)})
            save(
                directory / "COLD_LOAD.json",
                {
                    "checkpoint_sha256": study.sha(checkpoint),
                    "context_sha256": context_digest(context),
                    "fresh_process": True,
                },
            )
            frozen = {
                "collection_plan": plan,
                "evaluation_cases": deepcopy(base["registered_cases"]),
                "context": context.to_wire(),
                "methods": list(macro_policy.METHODS),
                "read_seconds_bound": 2.0,
                "finalizer_seconds_reserve": 1.0,
                "alpha": 0.1,
                "ridge": 0.001,
                "observer_sha256": base["observer_sha256"],
            }
            self.studies[mode], self.contexts[mode] = frozen, context

        # Upstream study freeze is covered separately; all critic loads below are real.
        def thaw_prior(args, modules):
            mode = Path(args.run_dir).name
            self.assertEqual(args.freeze_sha256, getattr(self.args, mode + "_freeze"))
            return Path(args.run_dir), self.studies[mode], self.contexts[mode]

        self.prior_thaw = patch.object(study, "thaw", side_effect=thaw_prior)
        self.prior_thaw.start()
        self.addCleanup(self.prior_thaw.stop)

    def loaded(self):
        registrations = {
            mode: {
                "directory": getattr(self.args, mode + "_dir"),
                "freeze_sha256": getattr(self.args, mode + "_freeze"),
            }
            for mode in factorial.MODES
        }
        return factorial.inputs(self.repository, registrations)[0]

    def freeze(self):
        factorial.freeze(self.args)
        self.args.factorial_sha256 = study.sha(
            (Path(self.args.output) / "FROZEN.json").read_bytes()
        )

    def prepare_unstarted_executions(self):
        for mode, (directory, frozen, _) in self.loaded().items():
            plan, profiles, arms = frozen["collection_plan"], {}, []
            deployments = directory / "deployments"
            deployments.mkdir()
            for method in macro_policy.METHODS:
                deployment = fixture_deployment(
                    method,
                    context=self.contexts[mode],
                    weights=plan["profile"]["model_sha256"],
                )
                control = self.modules["ControlPlan"](
                    **study.read(plan["profile"]["control_plan"])["control"]
                )
                deployment["control_sha256"] = digest(asdict(control))
                path = deployments / (method + ".json")
                save(path, deployment)
                profiles[method] = {
                    **plan["profile"],
                    "macro_policy": file_pin(path),
                }
                arms.append(
                    {
                        "arm_id": method,
                        "policy": method,
                        "content_mode": "off",
                        "control_mode": "on"
                        if method in {"point", "unconditional", "conditional"}
                        else "off",
                        "content_sha256": plan["profile"]["model_sha256"],
                        "critic_context_sha256": context_digest(self.contexts[mode]),
                    }
                )
            execution = deepcopy(self.base)
            execution.update(profiles=profiles, source_pins=plan["source_pins"])
            execution["cohort"].update(
                arms=arms,
                one_off_costs={
                    name: {k: None for k in ("fit", "calibration", "tuning")}
                    for name in profiles
                },
            )
            execution["cohort_sha256"] = digest(execution["cohort"])
            (directory / "evaluation").mkdir()
            self.executions[mode] = execution
            self.save_execution(mode, execution)

    def save_execution(self, mode, execution):
        directory = Path(getattr(self.args, mode + "_dir"))
        save(directory / "EXECUTION_PLAN.json", execution)
        save(directory / "EXECUTION_PIN.json", {"canonical_sha256": digest(execution)})
        save(directory / "evaluation/PLAN.json", execution)
        save(
            directory / "evaluation/RUN.json",
            {
                "schema": "ndu.real.macro-execution.v1",
                "plan_sha256": digest(execution),
                "evidence_kind": "native_macro",
            },
        )

    def test_freeze_thaw_and_unstarted_twelve_arm_roster_preserve_unknown(self):
        self.freeze()
        _, frozen, loaded, _ = factorial.thaw(self.args)
        self.assertEqual(
            frozen["factorial"],
            {
                "off_off": "frozen/STOP",
                "off_on": "frozen/conditional",
                "on_off": "adapted/STOP",
                "on_on": "adapted/conditional",
            },
        )
        self.assertNotEqual(loaded["frozen"][2].sha256, loaded["adapted"][2].sha256)
        self.prepare_unstarted_executions()
        with patch.object(
            macro_execution,
            "execute",
            side_effect=AssertionError("reconcile must not execute"),
        ):
            factorial.reconcile(self.args)
        report = study.read(Path(self.args.output) / "REPORT.json")
        self.assertEqual(report["cohort"]["planned_executions"], 24)
        self.assertEqual(len(report["cohort"]["arms"]), 12)
        self.assertTrue(
            all(
                r["status"] == "NOT_STARTED" and r["quality"] is None
                for r in report["rows"]
            )
        )
        self.assertIsNone(
            report["cohort"]["factorial"]["quality"]["source_equal_interaction"]
        )
        self.assertFalse(report["recursive_ndu_qualified"])
        for state in (report, report["cohort"]):
            self.assertEqual(
                (
                    state["decision"],
                    state["owner_evaluation"],
                    state["owner_decision"],
                ),
                ("HOLD", "not_evaluated", None),
            )

    def test_summary_keeps_declared_owner_results_unevaluated(self):
        self.freeze()
        self.prepare_unstarted_executions()
        factorial.reconcile(self.args)
        report = study.read(Path(self.args.output) / "REPORT.json")
        summarize = runpy.run_path(
            str(
                Path(self.repository)
                / "qualification/ctrl-real-comparison-20261112/analysis"
                / "summarize_ctrl_factorial.py"
            )
        )["summarize"]
        for declared in (None, "NoUpdate", "Adopt"):
            supplied = deepcopy(report)
            for state in (supplied, supplied["cohort"]):
                state["decision"] = declared or "NoUpdate"
                if declared is None:
                    del state["owner_evaluation"]
                    del state["owner_decision"]
                else:
                    state.update(owner_evaluation="completed", owner_decision=declared)
            original = deepcopy(supplied)
            with self.subTest(declared=declared):
                summary = summarize(supplied)
                self.assertEqual(
                    (
                        summary["limits"]["decision"],
                        summary["limits"]["owner_evaluation"],
                        summary["limits"]["owner_decision"],
                    ),
                    ("HOLD", "not_evaluated", None),
                )
                self.assertTrue(summary["stored_mean_audit"]["all_match"])
                self.assertEqual(summary["denominators"]["statuses"]["NOT_STARTED"], 24)
                self.assertEqual(supplied, original)

    def test_receipt_rejects_aliases_nonparameters_and_false_optimizer_steps(self):
        loaded = self.loaded()
        identical = deepcopy(loaded)
        identical["adapted"][1]["collection_plan"]["profile"]["model_sha256"] = (
            self.receipt["base_weights_sha256"]
        )
        with self.assertRaises(ValueError):
            factorial.validate_pair(identical, self.receipt)
        for field, value in (
            ("weights_sha256", self.receipt["base_weights_sha256"]),
            ("initial_content_sha256", "label"),
            ("final_content_sha256", self.receipt["initial_content_sha256"]),
            ("parameter_sha256", None),
            ("cold_load_parameter_sha256", "f" * 64),
            ("fit_sources", ["a", "b", "s"]),
        ):
            changed = deepcopy(self.receipt)
            changed[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                factorial.validate_pair(loaded, changed)
        for value in (True, 0, -1, 1.5, float("nan")):
            changed = deepcopy(self.receipt)
            changed["training"]["optimizer_steps"] = value
            with self.subTest(optimizer_steps=value), self.assertRaises(ValueError):
                factorial.validate_pair(loaded, changed)

    def test_pair_rejects_frontier_profile_partition_and_critic_drift(self):
        source = self.studies["adapted"]["evaluation_cases"][0]["case"]["source_sha256"]
        for path, value in (
            ((0, "collection_plan", "config", "latency_weight"), 0.5),
            ((0, "collection_plan", "profile", "memory_mode"), "carry"),
            ((0, "collection_plan", "profile", "training_seed"), 999),
            ((0, "evaluation_cases", 0, "read_condition"), "noise"),
            ((0, "collection_plan", "pairs", 0, "pair_id"), "different-case"),
            ((1, "context", "answer_sha256"), "f" * 64),
            ((1, "source_bindings", "a"), source),
        ):
            loaded = deepcopy(self.loaded())
            target = [loaded["adapted"][1], loaded["adapted"][2].data]
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = value
            with self.subTest(path=path), self.assertRaises(ValueError):
                factorial.validate_pair(loaded, self.receipt)

    def test_freeze_rejects_previous_evaluation_and_unbound_receipt(self):
        for marker in (
            "EVALUATE_START.json",
            "EVALUATION_REPORT.json",
            "evaluation",
            "deployments",
        ):
            path = Path(self.args.adapted_dir) / marker
            path.touch()
            with (
                self.subTest(marker=marker),
                self.assertRaisesRegex(ValueError, "before either evaluation"),
            ):
                factorial.freeze(self.args)
            self.assertFalse(Path(self.args.output).exists())
            path.unlink()
        self.studies["adapted"]["collection_plan"]["profile"][
            "training_receipt_sha256"
        ] = "f" * 64
        with self.assertRaisesRegex(ValueError, "original training receipt"):
            factorial.freeze(self.args)

    def test_inputs_require_bound_fresh_process_context(self):
        path = Path(self.args.adapted_dir) / "COLD_LOAD.json"
        original = study.read(path)
        for field, value in (
            ("fresh_process", False),
            ("context_sha256", "f" * 64),
            ("checkpoint_sha256", "f" * 64),
        ):
            save(path, {**original, field: value})
            with (
                self.subTest(field=field),
                self.assertRaisesRegex(ValueError, "fresh-process readback"),
            ):
                self.loaded()
        save(path, original)

    def test_thaw_rejects_new_critic_after_factorial_freeze(self):
        self.freeze()
        directory = Path(self.args.adapted_dir)
        changed = fixture_deployment(
            width=2,
            context=self.contexts["adapted"],
            weights=self.receipt["weights_sha256"],
        )
        (directory / "CHECKPOINT.json").write_text(changed["checkpoint_utf8"])
        save(
            directory / "CHECKPOINT_PIN.json", {"sha256": changed["checkpoint_sha256"]}
        )
        cold = study.read(directory / "COLD_LOAD.json")
        save(
            directory / "COLD_LOAD.json",
            {**cold, "checkpoint_sha256": changed["checkpoint_sha256"]},
        )
        with self.assertRaisesRegex(ValueError, "Critic changed"):
            factorial.thaw(self.args)

    def test_reconcile_rejects_unpinned_or_substituted_execution_inputs(self):
        self.freeze()
        self.prepare_unstarted_executions()
        directory = Path(self.args.adapted_dir)
        original = self.executions["adapted"]
        changed = deepcopy(original)
        changed["action_budget_seconds"] += 1
        save(directory / "EXECUTION_PLAN.json", changed)
        with self.assertRaisesRegex(ValueError, "plan differs"):
            factorial.reconcile(self.args)
        self.save_execution("adapted", changed)
        with self.assertRaisesRegex(ValueError, "departed from frozen"):
            factorial.reconcile(self.args)
        self.assertFalse((Path(self.args.output) / "REPORT.json").exists())

    def test_evaluate_prepares_both_plans_before_serial_create_only_schedule(self):
        self.freeze()
        frozen = study.read(Path(self.args.output) / "FROZEN.json")
        calls = []
        fixture_report = {
            "schema": "manufactured.execution-report",
            "native_execution": False,
        }

        def fixture_steps(execution, output, *, expected_plan_sha256, operation_order):
            self.assertEqual(digest(execution), expected_plan_sha256)
            mode = Path(output).parent.name
            for operation in operation_order:
                for other in factorial.MODES:
                    self.assertTrue(
                        (
                            Path(getattr(self.args, other + "_dir"))
                            / "EXECUTION_PLAN.json"
                        ).is_file()
                    )
                calls.append((mode, operation))
                yield operation

        with (
            patch.object(
                macro_execution, "execute_steps", side_effect=fixture_steps
            ) as steps,
            patch.object(
                macro_execution, "reconcile", return_value=fixture_report
            ) as readback,
            patch.object(factorial, "reconcile") as combined,
        ):
            factorial.evaluate(self.args)
            expected = []
            for entry in frozen["execution_order"]:
                directory = Path(getattr(self.args, entry["mode"] + "_dir"))
                plan = study.read(directory / "EXECUTION_PLAN.json")
                pin = study.read(directory / "EXECUTION_PIN.json")["canonical_sha256"]
                operation = "macro-" + digest(
                    [
                        pin,
                        plan["cohort"]["contexts"][entry["context_index"]],
                        entry["policy"],
                    ]
                )
                expected.append((entry["mode"], operation))
            self.assertEqual(calls, expected)
            self.assertEqual(len(calls), 24)
            self.assertEqual(len(set(calls)), 24)
            self.assertEqual(
                Counter(mode for mode, _ in calls), {"frozen": 12, "adapted": 12}
            )
            for mode in factorial.MODES:
                directory = Path(getattr(self.args, mode + "_dir"))
                self.assertEqual(
                    study.read(directory / "EVALUATION_REPORT.json"), fixture_report
                )
                self.assertTrue((directory / "EVALUATE_COMPLETED.json").is_file())
            self.assertTrue(
                (Path(self.args.output) / "EVALUATE_COMPLETED.json").is_file()
            )
            combined.assert_called_once_with(self.args)
            self.assertEqual((steps.call_count, readback.call_count), (2, 2))
            with self.assertRaises(FileExistsError):
                factorial.evaluate(self.args)
            self.assertEqual(calls, expected)
            self.assertEqual(
                (steps.call_count, readback.call_count, combined.call_count), (2, 2, 1)
            )


class ExecutionScheduleContracts(unittest.TestCase):
    def test_williams_schedule_balances_positions_and_ordered_predecessors(self):
        cases = [
            {
                "source_id": f"source-{i // 4}",
                "case_id": f"case-{i}",
                "seed": 7,
                "read_condition": "repeat",
                "case": {"private_reference": f"hidden-{i}"},
            }
            for i in range(48)
        ]
        original = deepcopy(cases)
        schedule = factorial.execution_schedule(cases)
        self.assertEqual(schedule, factorial.execution_schedule(deepcopy(cases)))
        self.assertEqual(cases, original)
        changed = deepcopy(cases)
        for case in changed:
            case.update(read_condition="noise", case={"score": 0.0})
        self.assertEqual(schedule, factorial.execution_schedule(changed))
        self.assertEqual(len(schedule), 576)
        arms = {
            (mode, policy)
            for mode in factorial.MODES
            for policy in macro_policy.METHODS
        }
        positions, predecessors, contexts = Counter(), Counter(), []
        for offset in range(0, len(schedule), 12):
            block = schedule[offset : offset + 12]
            context = block[0]["context_index"]
            contexts.append(context)
            self.assertTrue(
                all(set(row) == {"context_index", "mode", "policy"} for row in block)
            )
            self.assertTrue(all(row["context_index"] == context for row in block))
            sequence = [(row["mode"], row["policy"]) for row in block]
            self.assertEqual(set(sequence), arms)
            positions.update((arm, position) for position, arm in enumerate(sequence))
            predecessors.update(zip(sequence, sequence[1:]))
        self.assertEqual(sorted(contexts), list(range(48)))
        self.assertEqual(
            positions,
            Counter({(arm, position): 4 for arm in arms for position in range(12)}),
        )
        self.assertEqual(
            predecessors, Counter({(a, b): 4 for a in arms for b in arms if a != b})
        )

    def test_execution_order_accepts_only_unique_positive_timestamped_prefixes(self):
        schedule = factorial.execution_schedule(
            [{"source_id": "source", "case_id": "case", "seed": 7}]
        )
        starts = [(100 + i, deepcopy(row)) for i, row in enumerate(schedule)]
        original = deepcopy(schedule)
        for prefix in ([], starts[:5], starts):
            with self.subTest(prefix=len(prefix)):
                self.assertEqual(
                    factorial.check_execution_order(schedule, list(reversed(prefix))),
                    len(prefix),
                )
        unknown = {**schedule[0], "policy": "unknown"}
        invalid = {
            "wrong first": [(100, schedule[1])],
            "wrong order": [(100, schedule[1]), (101, schedule[0])],
            "repeated arm": [(100, schedule[0]), (101, schedule[0])],
            "unknown arm": [(100, unknown)],
            "tied timestamp": [(100, schedule[0]), (100, schedule[1])],
            "overlong": starts + [(200, schedule[0])],
        }
        for timestamp in (0, -1, True, 1.5, "100"):
            invalid[f"bad time {timestamp!r}"] = [(timestamp, schedule[0])]
        for name, records in invalid.items():
            with self.subTest(name=name), self.assertRaises(ValueError):
                factorial.check_execution_order(schedule, records)
        self.assertEqual(schedule, original)
