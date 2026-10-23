import json
from contextlib import nullcontext
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import numpy as np

from independent import run
from independent.accounting import BudgetExceeded, WorkLedger


class DecodedObserverReuseTests(unittest.TestCase):
    def test_three_mode_validation_observes_once_with_unchanged_exact_scores(self):
        import data
        from model import JointModel
        model = JointModel(202, 12, 192, hidden=4, seed=1701)
        manual = {"full": np.random.default_rng(2108).uniform(0, 1, (4, 202)),
                  "labels": np.array([0, 2, 7, 11])}
        ledger = WorkLedger("manual-validation")
        before = model.digest()
        with patch.object(data, "decoded_observations", wraps=data.decoded_observations) as observe:
            actual, predictions = run.batch_validation(model, manual, ledger)
        self.assertEqual(observe.call_count, 1)
        for mode, (p, q) in predictions.items():
            reward = data.outcome_table(model)[manual["labels"]]
            metrics = data.decoded_metrics(model, p, q, manual["labels"])
            metrics["task_utility"] = np.einsum("ni,nij,nj->n", p, reward, q)
            self.assertEqual(actual[mode], {key: float(value.mean()) for key, value in metrics.items()})
        self.assertEqual(ledger.consumed_units,
                         ledger.estimate_kernel(**run.validation_work(model, 4)))
        self.assertEqual(model.digest(), before)

    def test_selected_observer_charge_matches_two_preparations(self):
        from independent.inference import _sum_work
        from independent.learning import setup_work
        from model import JointModel
        model = JointModel(202, 12, 192, hidden=4, seed=1701)
        report = {"per_row_cost": {"work_units": [10, 11]},
                  "cost": {"prepare": {"consumed_units": 5}}}
        ledger = WorkLedger("manual-selected")
        run.charge_measure(report, model, 2, ledger)
        observed = run.observer_work(2)
        observed["macs"] += 2 * 2 * 12 * 12
        observed["scalar_ops"] += 2 * 2
        setup = setup_work(model.dimensions, "additive")
        self.assertEqual(ledger.consumed_units,
                         26 + ledger.estimate_kernel(**_sum_work(setup, setup, observed)))


class AffineControllerIntegrationTests(unittest.TestCase):
    def test_selected_head_export_records_kind_tensor_inventory_and_dispatches_reload(self):
        from independent.gain_head import AffineGainHead, KIND
        from model import JointModel
        model = JointModel(202, 12, 192, hidden=4, seed=9)
        head = AffineGainHead(4, np.zeros(14), np.ones(14), np.zeros(14), .1, np.array([.1, .1]))
        row = {"seed": 11, "name": "manual", "reference_full_cpu_ns": 100000}
        states = {11: {"model": model, "objective": SimpleNamespace(reward=np.zeros((12, 12, 12)))}}
        ledger = WorkLedger("manual-head-export")
        plan = {"rho": 1.5, "controller": {"gain_head": KIND, "ridge_regularization": .001}}
        with tempfile.TemporaryDirectory() as temporary:
            with patch("independent.controller_cost.fit_and_calibrate", return_value=(head, .002, {"cost_ratio": .1})) as fit:
                run.fit_selected_controls([row], plan, {}, Path(temporary), {}, ledger, states, {})
            loaded = run.controller_for(Path(temporary), row)
            self.assertEqual((row["critic_kind"], row["gain_head_kind"], loaded.kind), (KIND, KIND, KIND))
            self.assertEqual(ledger.totals["serialized_tensors"], 8)
            self.assertIs(fit.call_args.args[0], model)
            np.testing.assert_array_equal(loaded.weights, head.weights)


class FrozenRunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name)
        self.root = self.repo / "qualification/joint-generation"
        self.independent = self.root / "independent"
        self.independent.mkdir(parents=True)
        self.plan = self.independent / "plan.json"
        self.plan.write_text(json.dumps({"fixture": True}))
        (self.root / "model.py").write_text("BOUND = 1\n")
        for argv in (["git", "init", "-q"], ["git", "add", "."],
                     ["git", "-c", "user.name=Qualification fixture", "-c",
                      "user.email=fixture@example.invalid", "commit", "-qm", "fixture"]):
            subprocess.run(argv, cwd=self.repo, check=True, capture_output=True)
        self.marker = self.independent / "efficient-r2-test-opened.json"
        for name, value in (("ROOT", self.root), ("PLAN", self.plan), ("MARKER", self.marker)):
            manager = patch.object(run, name, value)
            manager.start()
            self.addCleanup(manager.stop)

    def test_committed_protocol_freezes_then_source_changes_reject(self):
        receipt = self.independent / "frozen.json"
        run.freeze(receipt)
        value = run.check_freeze(receipt)
        self.assertFalse(value["test_opened"])
        self.assertEqual(value["sources"], {"model.py": run.sha(self.root / "model.py")})
        (self.root / "model.py").write_text("BOUND = 2\n")
        with self.assertRaisesRegex(ValueError, "source changed"):
            run.check_freeze(receipt)
        self.assertFalse(self.marker.exists())

    def test_uncommitted_protocol_is_not_accepted_as_frozen(self):
        self.plan.write_text(json.dumps({"fixture": False}))
        with self.assertRaisesRegex(ValueError, "commit all protocol"):
            run.freeze(self.independent / "uncommitted.json")
        self.assertFalse((self.independent / "uncommitted.json").exists())

    def test_experiment_opening_blocks_new_freeze_and_training_preflight(self):
        receipt = self.independent / "frozen.json"
        run.freeze(receipt)
        self.marker.write_text("{}")
        with self.assertRaisesRegex(ValueError, "already opened"):
            run.freeze(self.independent / "another-freeze.json")
        with self.assertRaisesRegex(ValueError, "already opened"):
            run.check_freeze(receipt)
        self.assertFalse((self.independent / "another-freeze.json").exists())

    def test_freeze_receipt_cannot_be_overwritten(self):
        receipt = self.independent / "frozen.json"
        run.freeze(receipt)
        before = receipt.read_bytes()
        with self.assertRaises(FileExistsError):
            run.freeze(receipt)
        self.assertEqual(receipt.read_bytes(), before)


class CandidateSchedulingTests(unittest.TestCase):
    def test_rotating_rounds_exclude_other_arms_cpu_and_preserve_returns(self):
        now, observed = [0.0], []

        def candidates(name, effort):
            active = run.ActiveCPU(lambda: now[0])
            for index in range(3):
                active.resume()
                now[0] += effort
                active.pause()
                observed.append((name, index))
                yield {"system": name, "round": index}
            return {"active_cpu": active.total, "name": name}

        tasks = {name: candidates(name, effort) for name, effort in (("S", 1), ("A", 2), ("N", 3))}
        retained = []
        completed = run.run_candidate_rounds(tasks, ("S", "A", "N"), 3,
            on_candidate=lambda system, index, row: retained.append(row))
        self.assertEqual(observed, [("S", 0), ("A", 0), ("N", 0),
            ("A", 1), ("N", 1), ("S", 1), ("N", 2), ("S", 2), ("A", 2)])
        self.assertEqual(completed, {"S": {"active_cpu": 3.0, "name": "S"},
            "A": {"active_cpu": 6.0, "name": "A"}, "N": {"active_cpu": 9.0, "name": "N"}})
        self.assertEqual(len(retained), 9)

    def test_generator_exception_flushes_active_cpu_without_charging_idle(self):
        now, progress = [0.0], {}

        def failing(*args, **kwargs):
            active = run.ActiveCPU(lambda: now[0])
            active.resume()
            progress.update(_activity=active, cost={})
            now[0] += 2
            active.pause()
            yield {"name": "first"}
            active.resume()
            now[0] += 3
            raise RuntimeError("kernel failed")

        with patch.object(run, "_train_system_candidates", failing):
            task = run.train_system("S", {}, None, None, {}, {}, {}, {"cpu_seconds": 1}, progress=progress)
            self.assertEqual(next(task), {"name": "first"})
            now[0] += 1000  # Other arm executes while this arm is yielded.
            with self.assertRaisesRegex(RuntimeError, "kernel failed"):
                next(task)
        self.assertEqual(progress["cost"], {"cpu_seconds": 6.0, "active_candidate_cpu_seconds": 5.0})
        self.assertIsNone(progress["_activity"].started)

    def test_over_cap_stops_before_candidate_work_and_keeps_partial_ledger(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            shared = WorkLedger("shared")
            shared.record("base_pretrain", units=7, content_updates=1)
            progress = {}
            task = run.train_system("S", {"operator_units_per_system": 100,
                "cpu_seconds_per_system": 10}, path, shared, {}, {}, {},
                {"cpu_seconds": 10.5}, progress=progress)
            with patch.object(run, "plain_copy", side_effect=AssertionError("no later computation")):
                with self.assertRaises(BudgetExceeded):
                    next(task)
            receipt = json.loads((path / "S-partial-arm.json").read_text())
            self.assertEqual(receipt["ledger"]["consumed_units"], 7)
            self.assertEqual(receipt["completed_candidates"], [])
            self.assertGreater(receipt["cost"]["cpu_seconds"], 10)
            self.assertEqual(receipt["phase"], "candidate_initialization")
            self.assertIsNone(progress["_activity"].started)

    def test_tail_failure_still_charges_actual_phase_and_keeps_original_error(self):
        now, cost, progress = [0.0], {"cpu_seconds": 4.0}, {}
        with patch.object(run, "cpu_clock", lambda: now[0]):
            with self.assertRaisesRegex(RuntimeError, "critic failed"):
                with run.active_tail_phase(cost, progress, "critic_fit", {"seed": 11}, "critic_cpu_seconds"):
                    now[0] += 2.5
                    raise RuntimeError("critic failed")
        self.assertEqual(cost, {"cpu_seconds": 6.5, "critic_cpu_seconds": 2.5})
        self.assertEqual(progress, {"phase": "critic_fit", "current": {"seed": 11}})

    def test_over_cap_archive_error_preserves_budget_failure(self):
        with patch.object(run, "write_json", side_effect=OSError("archive unavailable")):
            with self.assertRaisesRegex(BudgetExceeded, "actual CPU 11.000000000s") as caught:
                run.guard_cpu_budget("S", {"cpu_seconds_per_system": 10}, Path("/unused"),
                                     WorkLedger("S"), {"cpu_seconds": 11}, [], "candidate")
        self.assertIn("partial-arm persistence", caught.exception.__notes__[0])

    def test_failure_archiving_errors_preserve_the_original_kernel_error(self):
        original = RuntimeError("original kernel failure")
        plan = {"systems": ["S"], "model_seeds": [1], "learning_rates": [0.1],
                "cpu_seconds_per_system": 100}
        common = {"calibrations": {1: {"cpu_ns": {"full": 1}}}}
        frozen = {"plan": plan, "source_commit": "fixture"}
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "out"
            with patch.object(run, "check_freeze", return_value=frozen), \
                    patch.object(run, "prepare_shared", return_value=(WorkLedger("shared"), {}, {}, {}, common)), \
                    patch.object(run, "run_candidate_rounds", side_effect=original), \
                    patch.object(run, "manifest", return_value={"fixture": True}), \
                    patch.object(run, "write_json", side_effect=OSError("archive unavailable")) as writer, \
                    patch.object(run, "sha", return_value="fixture"):
                with self.assertRaises(RuntimeError) as caught:
                    run.train(Path(directory) / "freeze.json", out)
        self.assertIs(caught.exception, original)
        self.assertEqual(len(original.__notes__), 4)
        self.assertEqual([call.args[0].name for call in writer.call_args_list],
                         ["shared-build.json", "partial-build.json", "failure.json", "telemetry.json"])
        self.assertTrue(any("shared-build" in note for note in original.__notes__))
        self.assertTrue(any("partial-build" in note for note in original.__notes__))
        self.assertTrue(any("failure persistence" in note for note in original.__notes__))
        self.assertTrue(any("telemetry" in note for note in original.__notes__))

    def test_prepared_failure_keeps_shared_metadata_without_constructing_data(self):
        original = ValueError("no useful candidate admission budget")
        plan = {"systems": ["S"], "model_seeds": [11, 23, 47], "learning_rates": [.001],
                "cpu_seconds_per_system": 100}
        shared = WorkLedger("shared")
        shared.record("base_pretrain", units=7, content_updates=1)
        common = {"native_compile": {"cpu_ns": 123, "sha256": "c" * 64},
                  "calibrations": {seed: {"cpu_ns": {"full": 1},
                    "prepare_cpu_samples_ns": {"full": [10, 11, 12], "low": [20, 21, 22]}}
                    for seed in plan["model_seeds"]},
                  "_calibration_data": {"full": np.zeros((1, 202))}}
        frozen = {"plan": plan, "source_commit": "fixture-source", "sources": {"model.py": "a" * 64},
                  "plan_sha256": "b" * 64}
        train, validation = {"split": "train"}, {"split": "validation"}
        manifests = {"train": {"rows": 8, "inputs_sha256": "d" * 64},
                     "validation": {"rows": 4, "inputs_sha256": "e" * 64}}
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "out"
            with patch.object(run, "check_freeze", return_value=frozen), \
                    patch.object(run, "prepare_shared", return_value=(shared, {}, train, validation, common)), \
                    patch.object(run, "run_candidate_rounds", side_effect=original), \
                    patch.object(run, "dataset", side_effect=AssertionError("no new data")) as data, \
                    patch.object(run, "manifest", side_effect=lambda value: manifests[value["split"]]) as manifest, \
                    patch.object(run, "traced_phase", return_value=nullcontext()), \
                    patch.object(run, "cpu_clock", return_value=10.), \
                    patch.object(run, "sha", return_value="fixture-freeze"):
                with self.assertRaises(ValueError) as caught:
                    run.train(Path(directory) / "freeze.json", out)
                data.assert_not_called()
                self.assertEqual([call.args[0] for call in manifest.call_args_list], [train, validation])
            self.assertIs(caught.exception, original)
            receipt = json.loads((out / "shared-build.json").read_text())
            self.assertEqual(receipt["ledger"], shared.snapshot())
            self.assertEqual(receipt["common"]["native_compile"], common["native_compile"])
            self.assertEqual(receipt["common"]["calibrations"],
                             json.loads(json.dumps(common["calibrations"])))
            self.assertNotIn("_calibration_data", receipt["common"])
            self.assertEqual(receipt["datasets"], manifests)
            self.assertEqual((receipt["source_commit"], receipt["sources"], receipt["plan_sha256"], receipt["freeze_sha256"]),
                             ("fixture-source", frozen["sources"], "b" * 64, "fixture-freeze"))
            self.assertEqual(json.loads((out / "failure.json").read_text())["error"], str(original))
            self.assertTrue((out / "telemetry.json").is_file())
            self.assertFalse((out / "selection.json").exists())

    def test_static_selected_validation_does_not_prepare_random_routing(self):
        row = {"system": "anchor", "model_file": "unused.npz", "seed": 1,
               "mode": "full", "reference_full_cpu_ns": 1}
        with patch.object(run.JointModel, "load", return_value=object()), \
                patch.object(run, "controller_for", return_value=None), \
                patch("independent.evaluation.measure", return_value={"static": True}), \
                patch.object(run, "charge_measure"), \
                patch.object(run, "FrozenGenerator", side_effect=AssertionError("unused random baseline")):
            measured = run.validate_selected([row], {}, {}, Path("/unused"), {"labels": ()}, None)
        self.assertEqual(measured, {1: {"static": True}})
        self.assertNotIn("random_full_probability", row)

    def test_early_or_extra_candidates_are_not_silently_accepted(self):
        with self.assertRaisesRegex(ValueError, "stopped before"):
            run.run_candidate_rounds({"S": iter(())}, ("S",), 1)
        with self.assertRaisesRegex(ValueError, "exceeded"):
            run.run_candidate_rounds({"S": iter(({}, {}))}, ("S",), 1)


class ResidualContinuationTests(unittest.TestCase):
    def fixture(self, cap=16):
        now, order, originals, selected, progress, ledgers, costs = [0.0], [], [], [], {}, {}, {}
        systems, seeds = ("supervised", "ndu"), (11, 23, 47)
        for system in systems:
            candidates, states = [], {}
            for seed in seeds:
                model = SimpleNamespace(dimensions=(202, 12, 192, 32), marker=0, _moments={"retained": seed})

                class Objective:
                    def step(self, current, x, y, lr, *, ledger, stage, name=system, value=seed):
                        ledger.charge_kernel(stage, "mock_update", scalar_ops=1)
                        now[0] += 0.01
                        current.marker += 1
                        order.append((name, value))

                states[seed] = {"model": model, "objective": Objective(),
                    "rng": np.random.default_rng(seed), "last_step_cpu": 0.01, "refinement_updates": 0}
                row = {"system": system, "seed": seed, "name": f"{system}-{seed}",
                       "updates": 3, "learning_rate": 0.01, "mode": "full",
                       "validation": {"full": {"task_utility": 0.2}}, "model_file": "original.npz",
                       "model_sha256": "original-sha", "model_digest": "original-digest"}
                candidates.append(row)
                originals.append(row)
                selected.append(dict(row))
            progress[system] = {"_selected_states": states, "candidates": candidates}
            ledgers[system], costs[system] = WorkLedger(system, total_cap=cap), {"cpu_seconds": 0.0}
        plan = {"systems": systems, "model_seeds": seeds, "refinement_policy": "selected-residual-v1",
                "batch_size": 1, "calibration_rows": 72, "calibration_repeats": 3,
                "cpu_guard_seconds": 0.001, "cpu_seconds_per_system": 100,
                "static_modes": ("full", "low", "ensemble"), "compute_price": 0.02}
        common = {"reference_full_cpu_ns": 1, "calibrations": {
            seed: {"cpu_ns": {mode: 1 for mode in plan["static_modes"]}} for seed in seeds}}
        receipt = {"tail_units": 7, "changed_model_units": 3, "tail_cpu_seconds": 0.0,
                   "changed_model_cpu_seconds": 0.0, "arithmetic_safety": 1.0,
                   "training_cpu_per_unit_max": 0.0, "cpu_cap": 100}
        train = {"full": np.array([[1.0, 2.0], [3.0, 4.0]]),
                 "low": np.array([[0.0, 1.0], [1.0, 2.0]]), "labels": np.array([0, 1])}
        return now, order, originals, selected, progress, ledgers, costs, plan, common, receipt, train

    def test_residual_rounds_keep_states_search_rows_and_frozen_lr_mode(self):
        now, order, originals, selected, progress, ledgers, costs, plan, common, receipt, train = self.fixture()
        identities = {system: {seed: (id(state["model"]), id(state["objective"]), id(state["rng"]),
            id(state["model"]._moments)) for seed, state in value["_selected_states"].items()}
            for system, value in progress.items()}

        def validation(model, data, ledger, *, stage):
            ledger.charge_kernel(stage, "mock_validation", scalar_ops=1)
            return {mode: {"task_utility": float(model.marker)} for mode in plan["static_modes"]}, None

        with patch.object(run, "cpu_clock", lambda: now[0]), \
                patch.object(run, "reserve_work", return_value={}) as reserve, \
                patch.object(run, "forecast", side_effect=lambda *args: dict(receipt)), \
                patch.object(run, "step_work", return_value={"scalar_ops": 1}), \
                patch.object(run, "traced_phase", side_effect=lambda *args, **kwargs: nullcontext()), \
                patch.object(run, "batch_validation", side_effect=validation), \
                patch.object(run, "save_model", return_value={"file": "final-refined.npz", "sha256": "final", "digest": "final"}), \
                patch.object(run, "choose_global", side_effect=AssertionError("no reselection")):
            run.refine_content(selected, progress, ledgers, costs, plan, common, train,
                               {"labels": ()}, Path("/unused"), [], [])
        self.assertTrue(all(call.kwargs["plan"] is plan for call in reserve.call_args_list))
        self.assertEqual(order[:6], [("supervised", 11), ("ndu", 11), ("ndu", 23),
                                     ("supervised", 23), ("supervised", 47), ("ndu", 47)])
        self.assertEqual(order[6], ("ndu", 11))
        for system, value in progress.items():
            self.assertEqual(ledgers[system].remaining_units, 7)
            for seed, state in value["_selected_states"].items():
                self.assertEqual(identities[system][seed], (id(state["model"]), id(state["objective"]),
                    id(state["rng"]), id(state["model"]._moments)))
                self.assertEqual(state["model"].marker, 2)
        for row in selected:
            self.assertEqual((row["learning_rate"], row["mode"], row["updates"]), (0.01, "full", 5))
            self.assertEqual(row["refinement_updates"], 2)
            self.assertEqual(row["search_model_sha256"], "original-sha")
            self.assertEqual(row["validation"]["full"]["task_utility"], 2)
        self.assertTrue(all(row["updates"] == 3 and row["model_sha256"] == "original-sha" for row in originals))

    def test_unaffordable_round_reuses_validation_without_padding(self):
        now, _, _, selected, progress, ledgers, costs, plan, common, receipt, train = self.fixture(cap=12)
        with patch.object(run, "cpu_clock", lambda: now[0]), \
                patch.object(run, "reserve_work", return_value={}), \
                patch.object(run, "forecast", side_effect=lambda *args: dict(receipt)), \
                patch.object(run, "step_work", return_value={"scalar_ops": 1}), \
                patch.object(run, "batch_validation", side_effect=AssertionError("unchanged model")), \
                patch.object(run, "save_model", side_effect=AssertionError("unchanged model")):
            run.refine_content(selected, progress, ledgers, costs, plan, common, train,
                               {"labels": ()}, Path("/unused"), [], [])
        self.assertTrue(all(row["refinement_updates"] == 0 for row in selected))
        self.assertTrue(all(ledger.consumed_units == 0 for ledger in ledgers.values()))


if __name__ == "__main__":
    unittest.main()
