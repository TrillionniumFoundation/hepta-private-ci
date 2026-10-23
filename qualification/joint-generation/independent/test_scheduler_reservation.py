"""Manual-clock and opaque-service fixtures; no data, model, inference or build."""

from contextlib import nullcontext
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from independent import run
from independent.accounting import WorkLedger


class SchedulerReservationTests(unittest.TestCase):
    def test_pending_shared_cpu_refuses_round_and_is_finally_charged_only_once(self):
        now, selected, progress, costs, ledgers = [0.0], [], {}, {}, {}
        systems = ("supervised", "ndu")
        for index, system in enumerate(systems):
            rng, objective = Mock(), Mock()
            rng.integers.side_effect = AssertionError("unadmitted RNG draw")
            objective.step.side_effect = AssertionError("unadmitted update")
            model = SimpleNamespace(dimensions=(2, 2, 3, 3))
            state = {"model": model, "objective": objective, "rng": rng,
                     "last_step_cpu": 0.0}
            progress[system] = {"_selected_states": {11: state}, "candidates": []}
            costs[system] = {"cpu_seconds": 6.25, "refinement_cpu_seconds": float(index + 2)}
            ledgers[system] = WorkLedger(system, total_cap=100)
            selected.append({"system": system, "seed": 11, "updates": 3, "mode": "full",
                "model_file": "opaque.npz", "model_sha256": "hand", "model_digest": "hand",
                "validation": {"full": {}}, "name": system})
        plan = {"systems": systems, "model_seeds": [11], "refinement_policy": "selected-residual-v1",
            "batch_size": 1, "calibration_rows": 1, "calibration_repeats": 3,
            "cpu_guard_seconds": 1.0, "cpu_seconds_per_system": 10.0}
        receipt = {"tail_units": 1, "changed_model_units": 0, "tail_cpu_seconds": 2.0,
            "changed_model_cpu_seconds": 0.0, "arithmetic_safety": 1.0,
            "training_cpu_per_unit_max": 0.0, "cpu_cap": 10.0}
        original_admit, decisions = run.admit_round, []

        def reserve(*args, **kwargs):
            now[0] += .25  # Active preparation: belongs only to this arm.
            return {}

        def guard(system, plan, out, ledger, cost, candidates, phase, **kwargs):
            if phase == "refinement_prepared":
                now[0] += .5  # Shared bookkeeping outside either active arm.

        def admit(forecast, ledger, cpu_seconds, step_units, **kwargs):
            self.assertEqual(costs[ledger.arm]["cpu_seconds"], 6.5)
            self.assertTrue(original_admit(forecast, ledger, 6.5, step_units, **kwargs))
            result = original_admit(forecast, ledger, cpu_seconds, step_units, **kwargs)
            decisions.append((ledger.arm, cpu_seconds, result))
            return result

        with patch.object(run, "cpu_clock", side_effect=lambda: now[0]), \
             patch.object(run, "reserve_work", side_effect=reserve), \
             patch.object(run, "forecast", side_effect=lambda *args: dict(receipt)), \
             patch.object(run, "adaptation_step_work", return_value={"scalar_ops": 1}), \
             patch.object(run, "guard_cpu_budget", side_effect=guard), \
             patch.object(run, "admit_round", side_effect=admit), \
             patch.object(run, "batch_validation", side_effect=AssertionError("no validation")), \
             patch.object(run, "save_model", side_effect=AssertionError("no model export")):
            run.refine_content(selected, progress, ledgers, costs, plan, {}, {"labels": ()},
                               {"labels": ()}, Path("/unused"), [], [])
        self.assertEqual(decisions, [("supervised", 7.5, False), ("ndu", 7.5, False)])
        for index, system in enumerate(systems):
            self.assertEqual(costs[system]["refinement_scheduler_cpu_seconds"], 1.0)
            self.assertEqual(costs[system]["cpu_seconds"], 7.5)
            self.assertEqual(costs[system]["refinement_cpu_seconds"], index + 2.25)
            self.assertEqual(ledgers[system].consumed_units, 0)
            progress[system]["_selected_states"][11]["rng"].integers.assert_not_called()
            progress[system]["_selected_states"][11]["objective"].step.assert_not_called()
        self.assertTrue(all(row["refinement_updates"] == 0 for row in selected))

    def test_future_partial_keeps_finished_service_receipt_without_fabricating_interrupted_one(self):
        from independent import telemetry
        original = RuntimeError("handmade next service interrupted")
        report = {"mode": "full", "cost": {"cpu_ns": 123, "prepare_cpu_ns": 7,
            "batches": [{"rows": 1, "cpu_ns": 123}]}, "per_row_cost": {"work_units": [8]}}
        ledger = WorkLedger("supervised")
        shared = WorkLedger("shared")
        rows = [{"system": "supervised", "seed": seed, "mode": "full"} for seed in (11, 23)]
        cost = {"cpu_seconds": 1.0, "active_candidate_cpu_seconds": 0.0}
        plan = {"systems": ["supervised"], "model_seeds": [11, 23], "learning_rates": [.1],
                "cpu_seconds_per_system": 100, "static_modes": ["full"]}
        frozen = {"plan": plan, "source_commit": "opaque-handmade-source"}
        common = {"calibrations": {seed: {"cpu_ns": {"full": 1}} for seed in (11, 23)}}

        def arm(*args, progress, **kwargs):
            progress.update(ledger=ledger, cost=cost, candidates=[], phase="handmade")
            return iter(())

        def service(selected, *args):
            if selected[0]["seed"] == 23:
                raise original
            return {11: report}

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            profile = SimpleNamespace(can_evaluate=True, marker_path=root / "no-opening")
            with patch.object(run, "_experiment", return_value=profile), \
                 patch.object(run, "cpu_clock", return_value=0.0), \
                 patch.object(run, "check_freeze", return_value=frozen), \
                 patch.object(run, "prepare_shared", return_value=(shared, {}, {"split": "hand-fit"}, {"split": "hand-monitor"}, common)), \
                 patch.object(run, "train_system", side_effect=arm), \
                 patch.object(run, "run_candidate_rounds", return_value={"supervised": (ledger, [], rows, cost)}), \
                 patch.object(run, "refine_content"), patch.object(run, "guard_cpu_budget"), \
                 patch.object(run, "traced_phase", side_effect=lambda *args, **kwargs: nullcontext()), \
                 patch.object(run, "validate_selected", side_effect=service), \
                 patch.object(run, "dataset_manifest", side_effect=lambda data: {"split": data["split"]}), \
                 patch.object(run, "sha", return_value="handmade-sha"), \
                 patch.object(telemetry, "numerical_runtime", return_value={"handmade": True}):
                with self.assertRaises(RuntimeError) as caught:
                    run.train(root / "unread-freeze.json", root / "partial")
            self.assertIs(caught.exception, original)
            partial = json.loads((root / "partial/partial-build.json").read_text())
            self.assertEqual(partial["completed_selected_service_measures"], {"supervised": {"11": report}})
            self.assertNotIn("23", partial["completed_selected_service_measures"]["supervised"])
            self.assertEqual(json.loads((root / "partial/failure.json").read_text())["error"], str(original))
            self.assertFalse(profile.marker_path.exists())


if __name__ == "__main__":
    unittest.main()
