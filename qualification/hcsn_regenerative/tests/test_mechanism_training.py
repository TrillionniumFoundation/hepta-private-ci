"""Behavioral guards for the independent mechanism pilot and its new RNN."""

import copy
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from qualification.hcsn_regenerative.mechanism_contract import (
    ARMS, batch_order, digest, make_data, ordered_roster, read_json, select_group, validate_execution_environment, write_json,
)
from qualification.hcsn_regenerative.mechanism_training import (
    claim_directory, execute_group, execute_one_fit, execute_selected_fit, import_history, main, read_attempt, select_block, validate_selection_lock,
)


def fixture_plan():
    return dict(arms=list(ARMS), tasks=["delayed_recall", "adding"], training_seeds=[1103, 2207, 3301, 4409],
                learning_rates=[.001, .003], test_episode_seeds=[4703, 5801], schedule_seed=78137, split_seed=917003,
                sequence_length=64, train_count=2048, validation_count=512, test_count=1024,
                batch_size=64, train_updates=400, max_fit_wall_seconds=480, state_count=81, expected_parameter_count=2890)


def fixture_bundle():
    rng = np.random.default_rng(478)
    matrix = rng.uniform(.1, 1., (2, 4, 81, 81))
    matrix /= matrix.sum(-1, keepdims=True)
    first = rng.uniform(.1, 1., (2, 4, 81))
    first /= first.sum(-1, keepdims=True)
    features = rng.uniform(.05, .95, (2, 4, 81, 3))
    arrays, metadata = {}, dict(arms={}, state_count=81)
    for arm in ARMS:
        for name, value in (("matrix", matrix), ("first_step", first), ("features", features)):
            data = value.astype(np.float32).copy()
            if arm != "conditional_boundary":
                data[1] = data[0]
            arrays[arm + "__" + name] = data
        metadata["arms"][arm] = dict(channel={"margin_only": "margin", "call_only": "call", "risk_only": "risk"}.get(arm, "dual"))
    return arrays, metadata


class ContractTests(unittest.TestCase):
    def test_roster_preserves_complete_seed_blocks_and_lr_pairs(self):
        plan = fixture_plan()
        first, second = ordered_roster(plan), ordered_roster(copy.deepcopy(plan))
        self.assertEqual(first, second)
        self.assertEqual(len({row["fit_id"] for row in first}), 160)
        self.assertEqual(digest(first), digest(second))
        for offset in range(0, 160, 20):
            group = first[offset:offset + 20]
            self.assertEqual(len({row["group_id"] for row in group}), 1)
            self.assertEqual({row["arm"] for row in group}, set(ARMS))
            for i in range(0, 20, 2):
                self.assertEqual((group[i]["arm"], group[i]["lr_index"], group[i + 1]["arm"], group[i + 1]["lr_index"]),
                                 (group[i]["arm"], 0, group[i]["arm"], 1))
        plan["schedule_seed"] += 1
        self.assertNotEqual(digest(first), digest(ordered_roster(plan)))

    def test_split_rng_preserves_targets_and_independent_time_sequences(self):
        plan = fixture_plan()
        for task in plan["tasks"]:
            data, receipt = make_data(plan, task, "train")
            repeated, repeated_receipt = make_data(plan, task, "train")
            self.assertEqual(receipt, repeated_receipt)
            np.testing.assert_array_equal(data["x"], repeated["x"])
            self.assertGreater(np.unique(data["dt_indices"], axis=0).shape[0], 1)
            self.assertLessEqual(receipt["physical_time_max"], 6.400001)
            self.assertEqual(receipt["physical_time_max"], float((data["dt_indices"] + 1).sum(1).max() / 40))
            if task == "adding":
                np.testing.assert_array_equal(data["x"][..., 1].sum(1), np.full(len(data["x"]), 2))
                np.testing.assert_allclose(data["y"][:, 0], (data["x"][..., 0] * data["x"][..., 1]).sum(1), atol=1e-7)
            else:
                np.testing.assert_array_equal(data["y"][:, 0], data["x"][:, 0, 0])
            _, validation = make_data(plan, task, "validation")
            _, test_a = make_data(plan, task, "test", 4703)
            _, test_b = make_data(plan, task, "test", 5801)
            self.assertEqual(len({r["data_identity_sha256"] for r in (receipt, validation, test_a, test_b)}), 4)

    def test_batch_order_is_paired_across_arms_and_lr_but_not_training_seeds(self):
        plan = fixture_plan()
        rows = ordered_roster(plan)
        a = np.asarray(list(batch_order(plan, rows[0])))
        b = np.asarray(list(batch_order(plan, rows[3])))
        c = np.asarray(list(batch_order(plan, rows[20])))
        np.testing.assert_array_equal(a, b)
        self.assertFalse(np.array_equal(a, c))
        self.assertEqual(a.size, plan["train_updates"] * plan["batch_size"])

    def test_selection_failure_preserves_missing_arm_and_denies_full_comparator(self):
        plan = fixture_plan()
        group = ordered_roster(plan)[:20]
        terminals = {fit["fit_id"]: dict(status="COMPLETED", optimizer_updates_completed=400,
                     validation=dict(count=512, mse=.1 + fit["lr_index"] * .01), checkpoint_sha256="fixture") for fit in group}
        good = select_group(plan, group, terminals, {"fixture": True})
        self.assertTrue(good["strongest_full_registered_set_eligible"])
        self.assertEqual(good["strongest_registered_comparator"], "smooth_dual")
        failed = group[0]
        terminals[failed["fit_id"]] = dict(status="FAILED", optimizer_updates_completed=7)
        partial = select_group(plan, group, terminals, {"fixture": True})
        self.assertFalse(partial["strongest_full_registered_set_eligible"])
        self.assertIsNone(partial["strongest_registered_comparator"])
        self.assertNotIn(failed["arm"], partial["selected"])
        self.assertEqual(len(partial["selected"]), 9)


class LedgerTests(unittest.TestCase):
    def test_worker_rejects_unregistered_fit_or_different_environment(self):
        from qualification.hcsn_regenerative.mechanism_worker import run_job
        plan = fixture_plan()
        arrays, metadata = fixture_bundle()
        roster = ordered_roster(plan)
        identity = dict(fixture=True)
        altered = dict(roster[0], learning_rate=.9)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_json(root / "job.json", dict(attempt_path=str(root), identity=identity, fit=altered, phase="fit", device="cpu", bundle="fixture", plan="fixture"))
            with patch("qualification.hcsn_regenerative.mechanism_worker.load_contract", return_value=(plan, metadata, arrays, roster, identity)):
                result = run_job(root / "job.json")
            self.assertEqual((result["status"], result["optimizer_updates_completed"]), ("FAILED", 0))
            self.assertIn("exact frozen roster", result["error"]["message"])
        observed = dict(python="fixture-python", numpy="fixture-numpy", torch="fixture-torch-v1",
                        cuda_build="fixture-cuda", device="cuda", cpu_threads=1, deterministic_algorithms=True,
                        gpu=dict(name="fixture-T4", total_memory=16_000_000_000, compute_capability=[7, 5], uuid="GPU-fixture-A"))
        metadata = dict(schema="fixture-bundle", python="fixture-builder-python", numpy="fixture-builder-numpy", scipy="fixture-builder-scipy")
        plan = dict(execution_environment=dict(copy.deepcopy(observed), gpu_uuid_policy="same_model_new_lease"),
                    bundle_construction_environment=dict(metadata))
        new_lease = copy.deepcopy(observed)
        new_lease["gpu"]["uuid"] = "GPU-fixture-B"
        self.assertTrue(validate_execution_environment(plan, new_lease, metadata)["matched"])
        with self.assertRaisesRegex(ValueError, "torch"):
            validate_execution_environment(plan, dict(observed, torch="fixture-torch-v2"), metadata)
        with self.assertRaisesRegex(ValueError, "device"):
            validate_execution_environment(plan, dict(observed, device="cpu"), metadata)
        with self.assertRaisesRegex(ValueError, "construction environment mismatch"):
            validate_execution_environment(plan, observed, dict(metadata, numpy="different-builder-version"))
        plan["execution_environment"].update(gpu_uuid_policy="pinned", allowed_gpu_uuids=["GPU-fixture-A"])
        with self.assertRaisesRegex(ValueError, "UUID"):
            validate_execution_environment(plan, new_lease, metadata)

    def test_interrupted_group_continues_only_unstarted_fits(self):
        plan, identity = fixture_plan(), {"fixture": True}
        roster = ordered_roster(plan)
        group = roster[:20]
        launched = []
        with tempfile.TemporaryDirectory() as temporary:
            study = Path(temporary)
            write_json(study / "study.json", dict(identity=identity))
            claim_directory(study / "blocks" / group[0]["group_id"], dict(identity=identity, fits=group))
            claim_directory(study / "attempts" / group[0]["fit_id"], dict(identity=identity))
            with self.assertRaisesRegex(ValueError, "no replay"):
                execute_one_fit(study, plan, Path("fixture.npz"), Path("fixture-plan.json"), group[0], group, roster, identity, "cpu")

            def fail_worker(job, timeout):
                launched.append(job["fit"]["fit_id"])
                result = dict(identity=identity, fit=job["fit"], phase="fit", status="FAILED", optimizer_updates_completed=3,
                              training_examples_completed=192, evaluation_examples_completed={})
                path = Path(job["attempt_path"])
                write_json(path / "terminal.json", result)
                write_json(path / "process-completion.json", dict(returncode=1, timed_out=False, supervised_wall_seconds=2., child_user_cpu_seconds=1., child_system_cpu_seconds=.1))
                return result

            with patch("qualification.hcsn_regenerative.mechanism_training.supervised_worker", fail_worker):
                result = execute_group(study, plan, Path("fixture.npz"), Path("fixture-plan.json"), group, roster, identity, "cpu", True)
            self.assertEqual(launched, [fit["fit_id"] for fit in group[1:]])
            self.assertFalse(result["complete"])
            self.assertEqual(result["selected_test_status"], {})
            summary = read_json(study / "blocks" / group[0]["group_id"] / "study-progress.json")
            self.assertEqual(summary["counts"], {"COMPLETED": 0, "UNSTARTED": 140, "FAILED": 19, "TIMEOUT": 0, "UNKNOWN": 1})
            self.assertEqual(summary["totals"]["optimizer_updates_completed"], 57)
            self.assertEqual(summary["attempts_with_missing_complete_process_cost"], ["attempts/" + group[0]["fit_id"]])

    def test_completed_worker_with_failed_process_remains_unknown(self):
        from qualification.hcsn_regenerative.mechanism_contract import file_sha
        identity, fit = {"fixture": True}, ordered_roster(fixture_plan())[0]
        with tempfile.TemporaryDirectory() as temporary:
            study = Path(temporary)
            attempt = study / "attempts" / fit["fit_id"]
            claim_directory(attempt, dict(identity=identity))
            (attempt / "checkpoint.pt").write_bytes(b"fixture")
            write_json(attempt / "terminal.json", dict(identity=identity, fit=fit, phase="fit", status="COMPLETED", checkpoint_sha256=file_sha(attempt / "checkpoint.pt")))
            write_json(attempt / "process-completion.json", dict(returncode=-9, timed_out=True))
            self.assertEqual(read_attempt(study, fit, identity)["status"], "UNKNOWN")
            (attempt / "process-completion.json").unlink()
            self.assertEqual(read_attempt(study, fit, identity)["status"], "UNKNOWN")

    def test_exclusive_claim_unknown_and_conflicting_history(self):
        identity, fit = {"fixture": True}, ordered_roster(fixture_plan())[0]
        with tempfile.TemporaryDirectory() as temporary:
            study, history = Path(temporary) / "study", Path(temporary) / "history"
            for root in (study, history):
                write_json(root / "study.json", dict(identity=identity))
            claim_directory(history / "attempts" / fit["fit_id"], dict(identity=identity))
            import_history(study, [history], identity)
            self.assertEqual(read_attempt(study, fit, identity)["status"], "UNKNOWN")
            with self.assertRaises(FileExistsError):
                claim_directory(study / "attempts" / fit["fit_id"], dict(identity=identity))
            write_json(history / "attempts" / fit["fit_id"] / "started.json", dict(changed=True), replace=True)
            with self.assertRaisesRegex(ValueError, "Conflicting immutable history"):
                import_history(study, [history], identity)

    def test_all_training_precedes_atomic_selection_and_any_test(self):
        plan, identity = fixture_plan(), {"fixture": True}
        roster = ordered_roster(plan)
        events = []
        with tempfile.TemporaryDirectory() as temporary:
            study = Path(temporary)
            write_json(study / "study.json", dict(identity=identity))
            with self.assertRaisesRegex(ValueError, "twenty registered fits"):
                select_block(study, plan, roster[:20], roster, identity, "cpu")
            with self.assertRaisesRegex(ValueError, "selection lock first"):
                execute_selected_fit(study, plan, Path("fixture.npz"), Path("fixture-plan.json"), roster[0], roster[:20], roster, identity, "cpu")
            with patch("qualification.hcsn_regenerative.mechanism_training.load_contract", return_value=(plan, {}, {}, roster, identity)):
                with self.assertRaisesRegex(ValueError, "exactly one fit"):
                    main(["--bundle", "fixture", "--plan", "fixture", "--output", str(study), "--device", "cpu", "--fit-range", "0:20"])

            def fake_worker(job, timeout):
                attempt, fit = Path(job["attempt_path"]), job["fit"]
                events.append(job["phase"])
                result = dict(identity=identity, fit=fit, phase=job["phase"], status="COMPLETED",
                              optimizer_updates_completed=400 if job["phase"] == "fit" else 0,
                              training_examples_completed=25600 if job["phase"] == "fit" else 0,
                              evaluation_examples_completed={"validation": 512} if job["phase"] == "fit" else {"test-4703": 1024, "test-5801": 1024})
                if job["phase"] == "fit":
                    from qualification.hcsn_regenerative.mechanism_contract import file_sha
                    self.assertFalse((study / "blocks" / fit["group_id"] / "selection-lock.json").exists())
                    (attempt / "checkpoint.pt").write_bytes(b"fixture checkpoint")
                    result.update(validation=dict(count=512, mse=.5 + fit["lr_index"]), checkpoint_sha256=file_sha(attempt / "checkpoint.pt"))
                else:
                    self.assertEqual(events[:20], ["fit"] * 20)
                    lock = read_json(job["selection_lock"])
                    self.assertEqual(len(lock["selected"]), 10)
                    result["selection_lock_sha256"] = job["selection_lock_sha256"]
                write_json(attempt / "terminal.json", result)
                write_json(attempt / "process-completion.json", dict(returncode=0, timed_out=False, supervised_wall_seconds=1., child_user_cpu_seconds=.5, child_system_cpu_seconds=.1))
                return result

            with patch("qualification.hcsn_regenerative.mechanism_training.supervised_worker", fake_worker):
                result = execute_group(study, plan, Path("fixture.npz"), Path("fixture-plan.json"), roster[:20], roster, identity, "cpu")
            self.assertEqual(events, ["fit"] * 20 + ["selected_test"] * 10)
            self.assertTrue(result["complete"])
            summary = read_json(study / "blocks" / roster[0]["group_id"] / "study-progress.json")
            self.assertEqual(summary["counts"], {"COMPLETED": 20, "UNSTARTED": 140, "FAILED": 0, "TIMEOUT": 0, "UNKNOWN": 0})
            self.assertEqual(summary["totals"]["supervised_child_cpu_seconds"], 30 * .6)
            from qualification.hcsn_regenerative.mechanism_contract import file_sha
            block = study / "blocks" / roster[0]["group_id"]
            lock_path, receipt_path = block / "selection-lock.json", block / "selection-receipt.json"
            original_lock, original_receipt = lock_path.read_bytes(), receipt_path.read_bytes()
            validate_selection_lock(study, plan, roster[:20], identity)
            changed = read_json(lock_path)
            changed["strongest_registered_comparator"] = "regenerative_dual"
            write_json(lock_path, changed, replace=True)
            with self.assertRaisesRegex(ValueError, "original receipt SHA"):
                validate_selection_lock(study, plan, roster[:20], identity)
            receipt = read_json(receipt_path)
            receipt["selection_lock_sha256"] = file_sha(lock_path)
            write_json(receipt_path, receipt, replace=True)
            with self.assertRaisesRegex(ValueError, "strongest_registered_comparator"):
                validate_selection_lock(study, plan, roster[:20], identity)
            lock_path.write_bytes(original_lock)
            receipt_path.write_bytes(original_receipt)
            terminal_path = study / "attempts" / roster[0]["fit_id"] / "terminal.json"
            original_terminal = terminal_path.read_bytes()
            terminal = read_json(terminal_path)
            terminal["validation"]["mse"] += .01
            write_json(terminal_path, terminal, replace=True)
            with self.assertRaisesRegex(ValueError, "terminal.json"):
                validate_selection_lock(study, plan, roster[:20], identity)
            terminal_path.write_bytes(original_terminal)
            with self.assertRaisesRegex(ValueError, "already claimed"):
                execute_group(study, plan, Path("fixture.npz"), Path("fixture-plan.json"), roster[:20], roster, identity, "cpu", True)


@unittest.skipUnless(importlib.util.find_spec("torch"), "Torch runtime required for new-graph behavior")
class TorchGraphTests(unittest.TestCase):
    def test_real_worker_checkpoint_validation_and_selected_evaluation(self):
        from qualification.hcsn_regenerative.mechanism_contract import file_sha
        from qualification.hcsn_regenerative.mechanism_worker import configure_torch, run_job
        from qualification.hcsn_regenerative.mechanism_model import environment
        plan = fixture_plan()
        plan.update(sequence_length=3, train_count=8, validation_count=4, test_count=8, batch_size=4,
                    train_updates=2, mass_tolerance=5e-5, latency_warmup=1, latency_repeats=2,
                    throughput_batch=4, throughput_repeats=2)
        arrays, metadata = fixture_bundle()
        configure_torch("cpu")
        observed = environment("cpu")
        metadata.update(schema="unit-fixture-only", python=observed["python"], numpy=observed["numpy"], scipy="unused-unit-fixture")
        plan["execution_environment"] = dict(observed, gpu_uuid_policy="not_applicable")
        plan["bundle_construction_environment"] = {key: metadata[key] for key in ("schema", "python", "numpy", "scipy")}
        fit = ordered_roster(plan)[0]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle, plan_path = root / "fixture.npz", root / "fixture-plan.json"
            bundle.write_bytes(b"explicit unit-test loader fixture")
            plan_path.write_text("{}")
            source = Path(__file__).parents[1] / "mechanism_worker.py"
            plan["source_pins"] = {"qualification/hcsn_regenerative/mechanism_worker.py": file_sha(source)}
            identity = dict(fixture=True, plan_sha256=file_sha(plan_path), bundle_sha256=file_sha(bundle))
            attempt = root / "fit"
            attempt.mkdir()
            job = dict(attempt_path=str(attempt), identity=identity, fit=fit, phase="fit", device="cpu",
                       bundle=str(bundle), plan=str(plan_path))
            write_json(attempt / "job.json", job)
            with patch("qualification.hcsn_regenerative.mechanism_worker.load_contract", return_value=(plan, metadata, arrays, [fit], identity)):
                trained = run_job(attempt / "job.json")
            self.assertEqual((trained["status"], trained["optimizer_updates_completed"], trained["validation"]["count"]), ("COMPLETED", 2, 4))
            self.assertGreater(trained["observed_gradients"]["total_ever_nonzero_gradient_elements"], 2700)
            lock = dict(identity=identity, selected={fit["arm"]: dict(fit_id=fit["fit_id"], checkpoint_sha256=trained["checkpoint_sha256"])})
            write_json(root / "selection-lock.json", lock)
            evaluation = root / "evaluation"
            evaluation.mkdir()
            job.update(attempt_path=str(evaluation), phase="selected_test", selection_lock=str(root / "selection-lock.json"),
                       selection_lock_sha256=file_sha(root / "selection-lock.json"), checkpoint_path=str(attempt / "checkpoint.pt"))
            write_json(evaluation / "job.json", job)
            with patch("qualification.hcsn_regenerative.mechanism_worker.load_contract", return_value=(plan, metadata, arrays, [fit], identity)):
                tested = run_job(evaluation / "job.json")
            self.assertEqual(tested["status"], "COMPLETED")
            self.assertEqual([row["episode_seed"] for row in tested["test"]], [4703, 5801])
            self.assertEqual(tested["independent_training_replicates_represented"], 1)
            self.assertEqual(sum(tested["evaluation_examples_completed"].values()), 16)
            self.assertIsNone(tested["energy"]["full_physical_energy_joules"])

    def test_three_step_carry_and_represented_gradient_mirror(self):
        from qualification.hcsn_regenerative.mechanism_qualify import graph_checks
        arrays, metadata = fixture_bundle()
        checks = graph_checks(arrays, metadata, "cpu")
        self.assertTrue(checks)
        self.assertEqual([check for check in checks if not check["passed"]], [])

    def test_mass_error_is_not_hidden_by_observation_conditioning(self):
        import torch
        from qualification.hcsn_regenerative.mechanism_model import make_model
        arrays, metadata = fixture_bundle()
        arrays["regenerative_dual__matrix"] *= .99
        model = make_model(arrays, "regenerative_dual", "dual", 1103)
        with self.assertRaisesRegex(FloatingPointError, "Unconditioned"):
            model(torch.zeros(2, 3, 3), torch.zeros(2, 3, dtype=torch.int64))

    def test_checkpoint_restores_next_optimizer_block(self):
        import torch
        from qualification.hcsn_regenerative.mechanism_model import make_model
        arrays, _ = fixture_bundle()
        first = make_model(arrays, "regenerative_dual", "dual", 1103)
        first_optimizer = torch.optim.Adam(first.parameters(), lr=.003)
        x = torch.tensor([[[.3, 1., .025], [-.2, 0., .05], [.8, 0., .075]]])
        dt = torch.tensor([[0, 1, 2]])

        def step(model, optimizer):
            optimizer.zero_grad(set_to_none=True)
            prediction, _ = model(x, dt)
            prediction.square().mean().backward()
            optimizer.step()

        step(first, first_optimizer)
        buffer = io.BytesIO()
        torch.save(dict(model=first.state_dict(), optimizer=first_optimizer.state_dict()), buffer)
        buffer.seek(0)
        state = torch.load(buffer, weights_only=True)
        restored = make_model(arrays, "regenerative_dual", "dual", 2207)
        restored_optimizer = torch.optim.Adam(restored.parameters(), lr=.003)
        restored.load_state_dict(state["model"])
        restored_optimizer.load_state_dict(state["optimizer"])
        step(first, first_optimizer)
        step(restored, restored_optimizer)
        for name, value in first.state_dict().items():
            torch.testing.assert_close(value, restored.state_dict()[name], rtol=0, atol=0)


if __name__ == "__main__":
    unittest.main()
