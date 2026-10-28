"""KB-scale synthetic evidence only: no Torch import, model, fit or holdout."""

import hashlib
import itertools
import json
from pathlib import Path
import random
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from experiments.multimodal_output_portfolio.field_bridge_v6_preparation_20261028 import branch_state as state
from experiments.multimodal_output_portfolio.field_bridge_v6_preparation_20261028 import budget, codec


def fixture():
    h = hashlib.sha256(b"synthetic-only").hexdigest()
    tape = [{"step": step, "adapt_seed": step + 1, "clean_seed": step + 2, "noise_seed": step + 3,
             "condition": "clean"} for step in range(240, 288)]
    parameters = {"adapter.A": np.arange(4, dtype=np.float32).reshape(2, 2),
                  "adapter.B": np.ones((2, 2), dtype=np.float32)}
    return {"schema": state.SCHEMA,
        "binding": {"study_id": "synthetic-preparation-only", **{key: h for key in
            ("proposal_sha256", "source_freeze_sha256", "runtime_sha256", "prospective_protocol_sha256", "global_resource_limits_sha256")}},
        "immutable": {"model_refs": {key: h for key in ("frozen_base", "original_generator", "reward_observer")},
            "model_configuration": {"device": "cpu", "architecture_sha256": h,
                "module_training": {"": False, "adapter": True},
                "parameters": {key: {"dtype": value.dtype.str, "shape": list(value.shape), "requires_grad": True}
                               for key, value in parameters.items()},
                "buffers": {"count": {"dtype": "<i8", "shape": [1]}}, "named_rngs": ["toy"]}, "source_roles": state.ROLES,
            "context_input_sha256": h, "guard_baseline": {"panel_sha256": h, "source_ids": [("a", "b"), ("c", "d")],
                "output_sha256": [h, h], "values": np.asarray([.125, .25], dtype=np.float64)}},
        "parameters": parameters, "buffers": {"count": np.asarray([7], dtype=np.int64)},
        "requires_grad": {key: True for key in parameters},
        "optimizer": {"kind": "SGD", "state": {0: {"momentum_buffer": np.ones((2, 2), dtype=np.float32)}},
            "param_groups": [{"params": [0, 1], "lr": .01, "momentum": .9, "dampening": 0., "weight_decay": 0.,
                "nesterov": False, "maximize": False, "foreach": None, "differentiable": False, "fused": None}]},
        "optimizer_parameter_names": {0: "adapter.A", 1: "adapter.B"},
        "gradients": {"adapter.A": np.full((2, 2), .25, dtype=np.float32), "adapter.B": None},
        "rng": {"torch_cpu": np.arange(16, dtype=np.uint8), "python": random.Random(7).getstate(),
                "numpy": np.random.RandomState(7).get_state(), "named": {"toy": np.random.PCG64(17).state}},
        "cursor": {"seed": 17, "schedule_id": 6000, "path_kind": "baseline", "clock": 240, "total_steps": 288,
            "remaining_steps": 48, "decision_index": 5, "guard_grain": 48, "baseline_action_index": 2,
            "schedule_sha256": codec.digest(tape)}, "remaining_schedule": tape}


def synthetic_transition(record, action, ledger):
    """A declared toy recurrence, not a neural/gradient training operation."""
    saved = codec.dumps(record)
    rng = np.random.Generator(np.random.PCG64())
    rng.bit_generator.state = record["rng"]["named"]["toy"]
    mark = int(rng.integers(1, 9)) + record["remaining_schedule"][0]["noise_seed"]
    incoming = record["gradients"]["adapter.A"].copy()
    momentum = record["optimizer"]["state"][0]["momentum_buffer"]
    candidate = momentum + incoming + np.float32(mark + action)
    record["gradients"]["adapter.A"] = candidate.copy()
    record["rng"]["named"]["toy"] = rng.bit_generator.state
    ledger["synthetic_work_units"] = ledger.get("synthetic_work_units", 0) + 48
    ledger["synthetic_attempts"] = ledger.get("synthetic_attempts", 0) + 1
    if action:
        record["parameters"]["adapter.A"] += np.float32(action) * candidate
        record["optimizer"]["state"][0]["momentum_buffer"] = candidate.copy()
    accepted = action != 3
    if not accepted:
        record.clear()
        record.update(codec.loads(saved, hashlib.sha256(saved).hexdigest(), len(saved)))
    record["cursor"].update(clock=288, remaining_steps=0, decision_index=6, schedule_sha256=codec.digest([]))
    record["remaining_schedule"] = []
    return {"accepted": accepted, "candidate_scalar": float(candidate.sum())}


class PreparationTests(unittest.TestCase):
    def seal(self):
        record = fixture()
        fixed = state.environment_identity(record)
        raw, sha = state.seal(record, fixed)
        self.assertLess(len(raw), 65536)
        return record, fixed, raw, sha

    def test_literal_full_state_roundtrip_and_real_serializer_measurement(self):
        original, fixed, raw, sha = self.seal()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.state"
            receipt = codec.save(path, original, 65536)
            restored = state.restore(path.read_bytes(), receipt["sha256"], fixed, 65536)
            self.assertEqual(codec.dumps(restored), raw)
            self.assertEqual(codec.measure(original)["file_bytes"], path.stat().st_size)
            self.assertEqual(budget.measured_envelope(path)["sha256"], sha)
            self.assertIsNone(restored["gradients"]["adapter.B"])
            self.assertEqual(type(restored["rng"]["python"]), tuple)

    def test_all_24_branch_orders_share_identical_per_action_results_and_charge_all_work(self):
        original, fixed, raw, sha = self.seal()
        expected = None
        for order in itertools.permutations(range(4)):
            ledger = {"earlier_work": 999}
            result = state.fork_all(raw, sha, fixed, order, synthetic_transition, ledger)
            self.assertTrue(result["complete"])
            signature = codec.digest(result["branches"])
            expected = signature if expected is None else expected
            self.assertEqual(signature, expected)
            self.assertEqual(ledger, {"earlier_work": 999, "synthetic_work_units": 192, "synthetic_attempts": 4})
            self.assertEqual(codec.dumps(original), raw)

    def test_zero_and_rejected_actions_preserve_parameters_but_advance_clock_and_charge(self):
        original, fixed, raw, sha = self.seal()
        ledger = {}
        result = state.fork_all(raw, sha, fixed, [0, 1, 2, 3], synthetic_transition, ledger)
        for action in (0, 3):
            terminal = result["branches"][action]["state"]
            self.assertEqual(codec.digest(terminal["parameters"]), codec.digest(original["parameters"]))
            self.assertEqual(codec.digest(terminal["optimizer"]), codec.digest(original["optimizer"]))
            self.assertEqual(terminal["cursor"]["clock"], 288)
        rejected = result["branches"][3]["state"]
        self.assertEqual(codec.digest(rejected["rng"]), codec.digest(original["rng"]))
        self.assertEqual(codec.digest(rejected["gradients"]), codec.digest(original["gradients"]))
        self.assertEqual(ledger["synthetic_work_units"], 192)

    def test_incoming_gradients_and_rng_are_material_state(self):
        original, fixed, raw, sha = self.seal()
        baseline = state.fork_all(raw, sha, fixed, [0, 1, 2, 3], synthetic_transition, {})
        for field in ("gradients", "rng"):
            changed = state.restore(raw, sha, fixed, len(raw))
            if field == "gradients":
                changed[field]["adapter.A"] *= 2
            else:
                changed[field]["named"]["toy"] = np.random.PCG64(99).state
            encoded, checksum = state.seal(changed, fixed)
            other = state.fork_all(encoded, checksum, fixed, [0, 1, 2, 3], synthetic_transition, {})
            self.assertNotEqual(codec.digest(other["branches"]), codec.digest(baseline["branches"]))

    def test_corruption_truncation_and_trailing_bytes_are_rejected(self):
        unused, fixed, raw, sha = self.seal()
        for changed in (raw[:-1], raw + b"x", raw[:-1] + bytes([raw[-1] ^ 1])):
            with self.assertRaises(ValueError):
                state.restore(changed, sha, fixed, 65536)

    def test_missing_state_immutable_drift_and_wrong_optimizer_mapping_are_rejected(self):
        for change in ("gradient", "guard", "mapping", "clock", "role", "group", "protocol"):
            original, fixed, unused, sha = self.seal()
            if change == "gradient": original["gradients"].pop("adapter.B")
            elif change == "guard": original["immutable"]["guard_baseline"]["values"][0] += 1
            elif change == "mapping": original["optimizer_parameter_names"][0] = "missing"
            elif change == "clock": original["cursor"]["remaining_steps"] = 0
            elif change == "role": original["immutable"]["source_roles"] = ["fresh_holdout"]
            elif change == "protocol": original["binding"]["prospective_protocol_sha256"] = "f" * 64
            else: original["optimizer"]["param_groups"][0].pop("lr")
            with self.subTest(change=change), self.assertRaises(ValueError): state.seal(original, fixed)

    def test_failure_keeps_partial_state_completed_branches_and_nonrollback_costs(self):
        unused, fixed, raw, sha = self.seal()
        def fail(record, action, ledger):
            value = synthetic_transition(record, action, ledger)
            if action == 1: raise RuntimeError("synthetic interruption")
            return value
        ledger = {}
        result = state.fork_all(raw, sha, fixed, [0, 1, 2, 3], fail, ledger)
        self.assertFalse(result["complete"])
        self.assertEqual(set(result["branches"]), {0})
        self.assertEqual(result["failure"]["action"], 1)
        self.assertFalse(result["failure"]["work_ledger_integrity_failure"])
        self.assertEqual(ledger["synthetic_work_units"], 96)
        self.assertTrue(codec.dumps(result["failure"]["last_state"]))

    def test_optimizer_alias_and_equivalent_float_or_bool_cursors_are_rejected(self):
        original, fixed, raw, sha = self.seal()
        original["optimizer_parameter_names"][2] = "adapter.A"
        original["optimizer"]["param_groups"][0]["params"].append(2)
        with self.assertRaises(ValueError):
            state.seal(original, fixed)
        for field in ("seed", "schedule_id", "clock", "total_steps", "remaining_steps", "decision_index", "guard_grain", "baseline_action_index"):
            for convert in (float, bool):
                changed = state.restore(raw, sha, fixed, len(raw))
                changed["cursor"][field] = convert(changed["cursor"][field])
                with self.subTest(field=field, convert=convert.__name__), self.assertRaisesRegex(ValueError, "integer types"):
                    state.seal(changed, fixed)

    def test_self_consistent_tensor_omission_and_missing_named_rng_are_rejected(self):
        original, fixed, raw, sha = self.seal()
        for group in ("parameters", "gradients", "requires_grad"):
            original[group].pop("adapter.B")
        original["optimizer_parameter_names"].pop(1)
        original["optimizer"]["param_groups"][0]["params"].remove(1)
        with self.assertRaisesRegex(ValueError, "inventory"):
            state.seal(original, fixed)
        changed = state.restore(raw, sha, fixed, len(raw))
        changed["rng"]["named"].clear()
        with self.assertRaisesRegex(ValueError, "RNG inventory"):
            state.seal(changed, fixed)

    def test_action_iterator_snapshot_and_exact_integer_actions(self):
        unused, fixed, raw, sha = self.seal()
        result = state.fork_all(raw, sha, fixed, (i for i in range(4)), synthetic_transition, {})
        self.assertEqual(set(result["branches"]), {0, 1, 2, 3})
        actions = [0, 1, 2, 3]
        def mutate_list(record, action, ledger):
            actions.clear()
            return synthetic_transition(record, action, ledger)
        self.assertTrue(state.fork_all(raw, sha, fixed, actions, mutate_list, {})["complete"])
        for invalid in ([False, True, 2, 3], [0., 1., 2., 3.]):
            with self.assertRaises(ValueError):
                state.fork_all(raw, sha, fixed, invalid, synthetic_transition, {})

    def test_encoder_and_measurement_share_decoder_format_limits(self):
        small = [np.asarray([], dtype=np.uint8) for unused in range(4)]
        for operation in (codec.dumps, codec.measure):
            with patch.object(codec, "MAX_ARRAYS", 3), self.assertRaisesRegex(ValueError, "too many"):
                operation(small)
            with patch.object(codec, "MAX_HEADER_BYTES", 128), self.assertRaisesRegex(ValueError, "metadata"):
                operation({"value": "x" * 256})

    def test_size_caps_are_exact_integers_and_sample_reads_are_bounded(self):
        record, unused, raw, sha = self.seal()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.state"
            codec.save(path, record, len(raw))
            for cap in (True, float("inf"), float(len(raw)), -1):
                with self.subTest(cap=cap), self.assertRaises(ValueError):
                    codec.loads(raw, sha, cap)
                with self.subTest(cap=cap), self.assertRaises(ValueError):
                    codec.save(Path(directory) / "unwritten.state", record, cap)
                with self.subTest(cap=cap), self.assertRaises(ValueError):
                    budget.measured_envelope(path, cap)
            with self.assertRaisesRegex(ValueError, "artifact cap"):
                budget.measured_envelope(path, len(raw) - 1)
            with self.assertRaises(FileExistsError):
                codec.save(path, record, len(raw))
            self.assertEqual(path.read_bytes(), raw)

    def test_callback_error_still_records_ledger_integrity_failure_and_original_error(self):
        unused, fixed, raw, sha = self.seal()
        def bad(record, action, ledger):
            ledger["earlier_work"] = 0
            raise RuntimeError("original transition failure")
        ledger = {"earlier_work": 7}
        result = state.fork_all(raw, sha, fixed, [0, 1, 2, 3], bad, ledger)
        failure = result["failure"]
        self.assertFalse(result["complete"])
        self.assertTrue(failure["work_ledger_integrity_failure"])
        self.assertEqual(failure["message"], "original transition failure")
        self.assertEqual(failure["work_before"], {"earlier_work": 7})
        self.assertEqual(failure["work_after"], {"earlier_work": 0})

    def test_cost_rollback_is_rejected_and_shape_only_data_cannot_be_written(self):
        unused, fixed, raw, sha = self.seal()
        def bad(record, action, ledger): ledger["previous"] = 0
        self.assertFalse(state.fork_all(raw, sha, fixed, [0, 1, 2, 3], bad, {"previous": 9})["complete"])
        layout = {"large": codec.Layout("float32", (1_000_000,))}
        self.assertEqual(codec.measure(layout)["array_payload_bytes"], 4_000_000)
        with self.assertRaises(ValueError): codec.dumps(layout)

    def test_budget_rejects_missing_profiles_overflow_and_root_available_space_bypass(self):
        rows = [{"kind": kind, "count": count, "unit_bound_bytes": 32768, "basis": "declared_artifact_cap"}
                for kind, count in budget.REQUIRED_CLASSES.items()]
        plan = budget.estimate(rows)
        adequate = SimpleNamespace(f_bavail=3 * 1024 ** 3, f_bfree=3 * 1024 ** 3, f_frsize=1, f_favail=100000)
        self.assertTrue(budget.disk_gate("synthetic", plan, adequate)["capacity_passed"])
        self.assertFalse(budget.disk_gate("synthetic", plan, adequate)["research_start_permitted"])
        adequate.f_bavail = 0
        self.assertFalse(budget.disk_gate("synthetic", plan, adequate)["capacity_passed"])
        incomplete = budget.estimate(rows[:-1])
        self.assertIsNone(incomplete["raw_with_failure_bound_bytes"])
        self.assertFalse(budget.disk_gate("synthetic", incomplete, adequate)["capacity_passed"])
        rows[1]["unit_bound_bytes"] = 2 * budget.MIB
        self.assertFalse(budget.estimate(rows)["raw_cap_passed"])
        rows[1]["unit_bound_bytes"] = 32768
        retained = budget.estimate(rows, retained_failed_archive_bytes=2 * 1024 ** 3)
        self.assertGreater(retained["required_f_bavail_bytes"], budget.MIN_AVAILABLE)
        rows[0]["count"] = float(rows[0]["count"])
        with self.assertRaisesRegex(ValueError, "integer"):
            budget.estimate(rows)

    def test_actual_measurement_requires_real_envelope_not_asserted_boolean(self):
        rows = [{"kind": kind, "count": count, "unit_bound_bytes": 65536, "basis": "declared_artifact_cap"}
                for kind, count in budget.REQUIRED_CLASSES.items()]
        row = rows[0]
        row.update(basis="actual_envelope_with_declared_shape_bound", measured_bytes=True, shape_bound_verified=True)
        with self.assertRaisesRegex(ValueError, "envelope path"):
            budget.estimate(rows)
        with tempfile.TemporaryDirectory() as directory:
            record, unused, raw, sha = self.seal()
            path = Path(directory) / "synthetic.state"
            codec.save(path, record, 65536)
            row["envelope_path"] = str(path)
            with self.assertRaisesRegex(ValueError, "measurement"):
                budget.estimate(rows)
            row["measured_bytes"] = len(raw)
            plan = budget.estimate(rows)
            self.assertTrue(plan["unit_profiles_complete"])
            self.assertEqual(plan["actual_measured_units"][row["kind"]]["sha256"], sha)

    def test_typed_values_preserve_integer_keys_signed_zero_and_no_torch_import(self):
        value = {1: (None, True, -0.), "1": [np.asarray([-0., 0.], dtype=np.float32)]}
        raw = codec.dumps(value)
        restored = codec.loads(raw, hashlib.sha256(raw).hexdigest(), len(raw))
        self.assertEqual(codec.dumps(restored), raw)
        self.assertEqual(set(restored), {1, "1"})
        self.assertNotIn("torch", sys.modules)


if __name__ == "__main__":
    unittest.main()
