"""Independent replay and tamper tests; real-host fixtures are opt-in by path.

Set HEPTA_POLICY_AUDIT_FIXTURES to the all-arm preflight directory to run the
actual-native ledger tests. The deterministic math/schema tests need no files.
"""

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

import numpy as np

from experiments.continuous_boundary_flow.math_model import (
    build_model,
    solve_dp,
    TaskSpec,
)
from . import cells
from .audit import audit_episode
from .audit_cell import inference, validate_cell
from .audit_integrity import (
    ARMS,
    LEARNED,
    checked_file,
    strict_json,
    verify_profile,
    verify_protocol,
    verify_training_receipt,
)
from .audit_math import reference, streams
from .audit_stats import inspect_native_cost, paired_statistics
from .common import protocol

FIXTURES = os.environ.get("HEPTA_POLICY_AUDIT_FIXTURES")


class IndependentAuditTests(unittest.TestCase):
    def test_independent_recurrence_matches_all_fully_trainable_families(self):
        generator = np.random.default_rng(991)
        inputs = generator.normal(size=(9, 18))
        resets = generator.random(9)
        previous = generator.uniform(-1, 1, (9, 6))
        for kind in ("dual", "gru", "elman"):
            params = cells.initialize(991, kind)
            snapshot = cells.serialize(params, kind)
            independent, verified_kind = validate_cell(snapshot)
            scores, states = cells.step(inputs, resets, previous, params, kind)
            for index in range(9):
                calculated, state = inference(
                    inputs[index],
                    resets[index],
                    previous[index],
                    independent,
                    verified_kind,
                )
                np.testing.assert_allclose(
                    calculated, scores[index], atol=2e-14, rtol=0
                )
                np.testing.assert_allclose(state, states[index], atol=2e-14, rtol=0)

    def test_independent_bellman_matches_frozen_numerical_grid_exactly(self):
        for spec in (
            TaskSpec(),
            TaskSpec(mu=0.07, sigma=0.7, dt=0.65, horizon=8),
            TaskSpec(mu=-0.5, sigma=0.23, dt=0.35, horizon=16),
        ):
            numerical = build_model(spec, n_grid=64, x_max=4.8)
            expected = solve_dp(numerical)
            actual = reference(vars(spec))
            self.assertEqual(actual["q"].tobytes(), expected["q"].tobytes())
            np.testing.assert_allclose(
                actual["boundaries"],
                [r["boundary"] for r in expected["boundaries"]],
                atol=2e-13,
                rtol=0,
            )

    def test_changed_parameter_budget_sign_prior_or_nonfinite_rejected(self):
        original = cells.serialize(cells.initialize(991, "dual"), "dual")
        variants = []
        padded = deepcopy(original)
        padded["params"]["dead_padding"] = [0]
        variants.append(padded)
        sign = deepcopy(original)
        sign["params"]["Un"][0][0] = -1
        variants.append(sign)
        bad = deepcopy(original)
        bad["params"]["head"][0][0] = float("nan")
        variants.append(bad)
        forged = deepcopy(original)
        forged["architecture"]["trainable_scalars"] = 465
        variants.append(forged)
        fixed = deepcopy(original)
        fixed["fixed_sign_arrays"]["Wn"][11][0] *= -1
        variants.append(fixed)
        for changed in variants:
            with self.assertRaises(ValueError):
                validate_cell(changed)

    def test_changed_gate_sample_or_training_budget_rejected(self):
        original = protocol()
        verify_protocol(original)
        for name, value in (
            ("minimum_effect", 0),
            ("familywise_alpha", 0.2),
            ("seeds", [2203] * 8),
            ("epochs", 119),
            ("input_width", 19),
            ("child_cpu_clock_tolerance_seconds", 0.001),
        ):
            changed = deepcopy(original)
            changed[name] = value
            with self.subTest(name=name), self.assertRaises(ValueError):
                verify_protocol(changed)

    def test_artifact_tampering_duplicate_json_and_path_escape_rejected(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temporary:
            root = Path(temporary)
            path = root / "artifact.json"
            path.write_bytes(b'{"a":1}\n')
            identity = hashlib.sha256(path.read_bytes()).hexdigest()
            checked_file(root, "artifact.json", identity)
            path.write_bytes(b'{"a":2}\n')
            with self.assertRaises(ValueError):
                checked_file(root, "artifact.json", identity)
            with self.assertRaises(ValueError):
                checked_file(root, "../artifact.json", identity)
        for text in ('{"a":1,"a":2}', '{"a":NaN}', '{"a":Infinity}'):
            with self.assertRaises(ValueError):
                strict_json(text)

    def test_registered_seed_inference_and_stability_gate(self):
        positive = paired_statistics([0.1] * 8)
        self.assertTrue(positive["benefit_gate_passed"])
        self.assertFalse(
            paired_statistics([0.1] * 8, stability_failures=1)["benefit_gate_passed"]
        )
        self.assertFalse(paired_statistics([0.005] * 8)["benefit_gate_passed"])
        self.assertFalse(paired_statistics([-0.2, 0.4] * 4)["benefit_gate_passed"])
        with self.assertRaises(ValueError):
            paired_statistics([0.1] * 128)


@unittest.skipUnless(
    FIXTURES, "Set HEPTA_POLICY_AUDIT_FIXTURES for real native preflight ledgers"
)
class ActualNativeAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(FIXTURES)
        cls.records = {
            arm: json.loads((cls.root / "records" / f"{arm}.json").read_text())
            for arm in ARMS
        }
        cls.checkpoints = {
            arm: json.loads((cls.root / "checkpoints/991" / f"{arm}.json").read_text())
            if arm in LEARNED
            else None
            for arm in ARMS
        }
        cls.ref = reference(cls.records["dual_flow"][0]["spec"])
        cls.initial, cls.slots, _ = streams(991, "diagnostic", 0, 4, cls.ref)
        cls.binary = cls.records["dual_flow"][0]["steps"][0]["native_receipt"][
            "native_binary_sha256"
        ]
        native = cls.checkpoints["native_sparse"]
        cls.profile = json.loads((cls.root / native["profile_path"]).read_text())

    def validate(self, record, index=0, checkpoint=None):
        arm = record["arm"]
        return audit_episode(
            record,
            self.checkpoints[arm] if checkpoint is None else checkpoint,
            self.ref,
            self.binary,
            profile=self.profile if arm == "native_sparse" else None,
            expected_initial=int(self.initial[index]),
            expected_slots=self.slots[:, index],
        )

    def test_all_52_actual_native_and_reference_episodes(self):
        verify_profile(self.profile, 991)
        count = 0
        for arm, records in self.records.items():
            for index, record in enumerate(records):
                with self.subTest(arm=arm, path=index):
                    self.validate(record, index)
                    count += 1
        self.assertEqual(count, 52)

    def test_changed_reward_aggregate_regret_or_risk_rejected(self):
        original = self.records["dual_flow"][0]
        for name in ("reward", "discounted_reward", "action_regret", "predicted_risk"):
            changed = deepcopy(original)
            changed["steps"][0][name] += 0.01
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.validate(changed)
        changed = deepcopy(original)
        changed["reported_net_utility"] += 0.01
        with self.assertRaises(ValueError):
            self.validate(changed)

    def test_changed_hidden_scores_receipts_or_forbidden_sparse_work_rejected(self):
        original = self.records["dual_flow"][0]
        variants = []
        for name in ("hidden_before", "hidden_after", "scores_float"):
            row = deepcopy(original)
            row["steps"][0][name][0] += 0.01
            variants.append(row)
        row = deepcopy(original)
        row["steps"][0]["native_receipt"]["actual_kernel_calls"] = 1
        variants.append(row)
        row = deepcopy(original)
        row["steps"][0]["source_kernel_calls"] = 1
        variants.append(row)
        row = deepcopy(original)
        row["steps"][0]["native_receipt"]["model_sha256"] = "1" * 64
        variants.append(row)
        for changed in variants:
            with self.assertRaises(ValueError):
                self.validate(changed)

    def test_information_leak_malformed_reset_and_environment_repair_rejected(self):
        original = self.records["value_margin"][0]
        for column in (1, 12, 13, 14, 15):
            changed = deepcopy(original)
            changed["steps"][0]["features"][column] += 0.01
            with self.subTest(column=column), self.assertRaises(ValueError):
                self.validate(changed)
        changed = deepcopy(original)
        changed["steps"][0]["reset_fraction"] = 0.4
        with self.assertRaises(ValueError):
            self.validate(changed)
        changed = deepcopy(original)
        changed["steps"][0]["uniforms"][1] = 0.123
        with self.assertRaises(ValueError):
            self.validate(changed)

    def test_omitted_duplicated_and_after_stop_steps_rejected(self):
        original = self.records["always_keep"][0]
        changed = deepcopy(original)
        changed["steps"].pop()
        with self.assertRaises(ValueError):
            self.validate(changed)
        changed = deepcopy(original)
        changed["steps"][1] = deepcopy(changed["steps"][0])
        with self.assertRaises(ValueError):
            self.validate(changed)
        changed = deepcopy(self.records["always_stop"][0])
        changed["steps"].append(deepcopy(changed["steps"][0]))
        with self.assertRaises(ValueError):
            self.validate(changed)

    def test_actual_sparse_nested_and_score_flat_cost_receipts(self):
        for arm in ("native_sparse", "dual_flow"):
            receipt = json.loads(
                (self.root / "training/991" / arm / "TRAINING.json").read_text()
            )
            before = deepcopy(receipt)
            counters, cpu, residual = inspect_native_cost(
                receipt["native_process_cost"], receipt["cost"]
            )
            self.assertGreater(counters["actual_ndu_calls"], 0)
            self.assertGreater(cpu, 0)
            self.assertLessEqual(abs(residual), 5e-6)
            self.assertEqual(receipt, before)
            wrong = deepcopy(receipt["cost"])
            wrong["completed_child_cpu_seconds"] = 0
            with self.assertRaises(ValueError):
                inspect_native_cost(receipt["native_process_cost"], wrong)
            wrong = deepcopy(receipt["native_process_cost"])
            wrong.get("counters", wrong)["native_errors"] = 1
            with self.assertRaises(ValueError):
                inspect_native_cost(wrong, receipt["cost"])

    def test_actual_training_receipt_budget_and_selection_arithmetic(self):
        for arm in ("dual_flow", "generic_gru", "elman_mlp", "native_sparse"):
            original = json.loads(
                (self.root / "training/991" / arm / "TRAINING.json").read_text()
            )
            options = {"candidate_indices": (1,), "epochs": 4, "development_count": 2}
            winner = verify_training_receipt(original, 991, arm, **options)
            self.assertEqual(winner["candidate_index"], 1)
            changed = deepcopy(original)
            changed["selected_index"] = 0
            with self.assertRaises(ValueError):
                verify_training_receipt(changed, 991, arm, **options)
            changed = deepcopy(original)
            changed["candidates"][0]["development_mean_net_utility"] += 0.1
            with self.assertRaises(ValueError):
                verify_training_receipt(changed, 991, arm, **options)
            changed = deepcopy(original)
            changed["candidates"][0]["development_returns"].pop()
            with self.assertRaises(ValueError):
                verify_training_receipt(changed, 991, arm, **options)
            if arm != "native_sparse":
                changed = deepcopy(original)
                changed["candidates"][0]["fit"]["epochs"] -= 1
                with self.assertRaises(ValueError):
                    verify_training_receipt(changed, 991, arm, **options)

    def test_sparse_profile_head_or_receipt_tampering_rejected(self):
        original = self.records["native_sparse"][0]
        changed = deepcopy(original)
        changed["steps"][0]["native_row"]["activation_q24"][0] += 1
        with self.assertRaises(ValueError):
            self.validate(changed)
        profile = deepcopy(self.profile)
        profile["encoder_weights_q24"][0][0] += 1
        with self.assertRaises(ValueError):
            verify_profile(profile, 991)


if __name__ == "__main__":
    unittest.main()
