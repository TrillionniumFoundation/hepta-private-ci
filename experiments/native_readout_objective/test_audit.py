"""Independent arithmetic and corruption checks; no registered study samples."""

from copy import deepcopy
import gzip
import os
from pathlib import Path
import shutil
import tempfile
import unittest

import numpy as np

from .audit import audit_smoke
from .audit_core import (
    Q,
    canonical,
    checked_file,
    episode,
    paired_statistics,
    read,
    sha,
    streams,
    strict_json,
    verify_checkpoint,
    verify_protocol,
)
from .audit_costs import export_counts, native_work, phase_roster
from .audit_diagnostics import regret_values, selected, verify_panel
from .audit_integrity import exact_manifest, verify_contexts
from .audit_training import (
    independent_loss,
    load_shard,
    replay_optimizer,
    training_arrays,
    verify_export,
    verify_fit,
)
from .head import fit, loss_and_grad


class IndependentArithmeticTests(unittest.TestCase):
    def test_losses_gradients_and_full_120_update_trajectories(self):
        rng = np.random.Generator(np.random.Philox(993))
        x = rng.uniform(0, 0.8, (13, 20))
        x[:, 5] = 0
        q = np.c_[rng.normal(0, 2, (13, 2)), np.zeros(13)]
        weights = rng.normal(0, 0.2, (21, 2))
        for objective in ("q_mse", "policy_regret"):
            with self.subTest(objective=objective):
                loss, gradient = independent_loss(
                    np.c_[x, np.ones(13)], q, weights, objective
                )
                actual_loss, actual_gradient, _ = loss_and_grad(
                    x, q, weights, objective
                )
                self.assertAlmostEqual(loss, actual_loss, places=13)
                np.testing.assert_allclose(
                    gradient, actual_gradient, rtol=0, atol=1e-14
                )
                expected, losses, final = replay_optimizer(x, q, objective, 0.02)
                actual, receipt = fit(x, q, objective, learning_rate=0.02)
                np.testing.assert_allclose(actual, expected, rtol=0, atol=2e-12)
                np.testing.assert_allclose(
                    receipt["epoch_loss"], losses, rtol=0, atol=2e-13
                )
                self.assertAlmostEqual(receipt["final_loss"], final, places=13)

    def test_sixteen_seed_single_family_gate_and_zero_instability(self):
        values = 0.010 + 0.001 * np.arange(16)
        result = paired_statistics(values)
        radius = 2.131449545559323 * np.std(values, ddof=1) / 4
        np.testing.assert_allclose(
            result["interval"],
            [values.mean() - radius, values.mean() + radius],
            atol=1e-14,
        )
        self.assertTrue(result["benefit_gate_passed"])
        self.assertFalse(paired_statistics(values, 1)["benefit_gate_passed"])
        self.assertFalse(paired_statistics(np.full(16, 0.005))["benefit_gate_passed"])
        with self.assertRaises(ValueError):
            paired_statistics(values[:8])
        self.assertEqual(len(phase_roster(confirmed=False)), 80)
        self.assertEqual(len(phase_roster()), 288)

    def test_quantization_improvement_preserves_negative_regret_delta(self):
        # Tiny positive keep bias rounds to zero; exact NDU tie selects STOP.
        floating = [0.4 / Q, -1.0, 0.0]
        integer = [0, -Q, 0]
        self.assertEqual(selected(floating), 0)
        self.assertEqual(selected(integer), 2)
        self.assertEqual(
            regret_values([-1.0, -2.0, 0.0], selected(integer), selected(floating)),
            (0.0, 1.0, -1.0),
        )

    def test_protocol_budgets_cannot_be_relaxed(self):
        protocol = read(Path(__file__).parent, "PROTOCOL.json")
        verify_protocol(protocol)
        mutations = [
            ("primary_pair", "minimum_mean_net_utility", 0.0),
            ("primary_pair", "family_size", 4),
            ("fixed_native", "width", 21),
            ("matched_iterative_training", "updates", 121),
            ("data_plan", "split_weights", [0.6, 0.4]),
            ("costs", "numeric_bytes_per_decision", 0),
        ]
        for section, key, value in mutations:
            damaged = deepcopy(protocol)
            damaged[section][key] = value
            with self.subTest(section=section, key=key), self.assertRaises(ValueError):
                verify_protocol(damaged)

    def test_manifest_rejects_extra_missing_changed_and_hidden_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "data.json").write_bytes(b"{}\n")
            roster = {"data.json": sha(b"{}\n")}
            exact_manifest(root, roster)
            (root / "extra.json").write_bytes(b"{}\n")
            with self.assertRaises(ValueError):
                exact_manifest(root, roster)
            (root / "extra.json").unlink()
            (root / "data.json").write_bytes(b"[]\n")
            with self.assertRaises(ValueError):
                exact_manifest(root, roster)
            (root / "data.json").unlink()
            with self.assertRaises(ValueError):
                exact_manifest(root, roster)
            hidden = root / "unexpected" / "host" / "data.json"
            hidden.parent.mkdir(parents=True)
            hidden.write_bytes(b"{}\n")
            with self.assertRaises(ValueError):
                exact_manifest(root, {})
            with self.assertRaises(ValueError):
                checked_file(root, "../data.json", sha(b"{}\n"))
        for raw in (b'{"x":1,"x":2}', b'{"x":NaN}'):
            with self.assertRaises(ValueError):
                strict_json(raw)


@unittest.skipUnless(
    os.environ.get("HEPTA_NATIVE_READOUT_SMOKE"),
    "Set HEPTA_NATIVE_READOUT_SMOKE to the actual diagnostic-only native fixture",
)
class ActualNativeEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(os.environ["HEPTA_NATIVE_READOUT_SMOKE"])
        cls.summary = read(cls.root, "SUMMARY.json")
        cls.refs = verify_contexts(
            cls.root, [991], {"training": 2, "development": 1, "diagnostic": 1}
        )
        cls.checkpoints, cls.profiles = {}, {}
        for item in cls.summary["arms"]:
            arm = item["arm"]
            ckpt = read(cls.root, item["checkpoint"]["path"])
            cls.checkpoints[991, arm] = ckpt, item["checkpoint"]["sha256"]
            cls.profiles[991, arm] = verify_checkpoint(cls.root, ckpt, 991, arm)

    def test_complete_actual_native_smoke_passes(self):
        result = audit_smoke(self.root)
        self.assertTrue(result["passed"])
        self.assertFalse(result["registered_confirmation_accessed"])
        self.assertEqual(result["episodes_verified"], 16)

    def test_primitive_state_reward_risk_teacher_and_native_tampering_rejects(self):
        item = next(x for x in self.summary["arms"] if x["arm"] == "policy_regret")
        original = load_shard(self.root, item["shard"])[0]
        ckpt, _ = self.checkpoints[991, "policy_regret"]
        profile, ref = (
            self.profiles[991, "policy_regret"],
            self.refs[991, "diagnostic", 0],
        )
        initial, slots, _ = streams(991, "diagnostic", 0, 4, ref)

        def check(row):
            return episode(row, ckpt, ref, profile, int(initial[0]), slots[:, 0])

        check(original)
        changes = {
            "reward": lambda r: r["steps"][0].__setitem__(
                "reward", r["steps"][0]["reward"] + 0.1
            ),
            "risk": lambda r: r["steps"][0].__setitem__("predicted_risk", 0.123456),
            "state": lambda r: r["steps"][0].__setitem__(
                "state_idx", (r["steps"][0]["state_idx"] + 1) % 64
            ),
            "innovation": lambda r: r["steps"][0]["uniforms"].__setitem__(2, 0.314159),
            "margin": lambda r: r["steps"][0]["features"].__setitem__(11, 99.0),
            "teacher_units": lambda r: r["steps"][0].__setitem__(
                "teacher_q", [v / 8 for v in r["steps"][0]["teacher_q"]]
            ),
            "score": lambda r: r["steps"][0]["native_row"]["readout"][
                "scores_q24"
            ].__setitem__(0, 123),
            "native_action": lambda r: r["steps"][0]["native_row"][
                "readout"
            ].__setitem__("action", "stop"),
            "checkpoint": lambda r: r["steps"][0]["native_row"].__setitem__(
                "checkpoint_before", "1" * 64
            ),
            "activation_bound": lambda r: r["steps"][0]["native_row"][
                "activation_q24"
            ].__setitem__(0, 8 * Q + 1),
            "communication": lambda r: r["steps"][0].__setitem__(
                "semantic_message_bytes", 0
            ),
            "net_utility": lambda r: r.__setitem__(
                "reported_net_utility", r["reported_net_utility"] + 0.1
            ),
        }
        for name, change in changes.items():
            row = deepcopy(original)
            change(row)
            with self.subTest(corruption=name), self.assertRaises(ValueError):
                check(row)

    def test_binary_child_cpu_calls_and_full_wire_tampering_rejects(self):
        receipt = read(self.root, "datasets/991/FEATURE_EXPORT.json")
        expected = export_counts(self.root, receipt)
        source = {
            "native_binary_sha256": self.summary["native_binary_sha256"],
            "native_source_manifest_sha256": receipt["native_process_cost"]["identity"][
                "source_manifest_digest"
            ],
        }
        native_work(receipt["native_process_cost"], receipt["cost"], source, expected)
        for mutation in ("binary", "double_cpu", "kernel", "wire", "extra_owner"):
            native, cost = (
                deepcopy(receipt["native_process_cost"]),
                deepcopy(receipt["cost"]),
            )
            if mutation == "binary":
                native["identity"]["binary_sha256"] = "0" * 64
            elif mutation == "double_cpu":
                cost["completed_child_cpu_seconds"] += native["child_cpu_seconds"]
            elif mutation == "kernel":
                native["counters"]["actual_kernel_calls"] -= 1
            elif mutation == "wire":
                native["counters"]["response_bytes"] = 0
            else:
                native["counters"]["owner_ticks"] = 1
            with self.subTest(corruption=mutation), self.assertRaises(ValueError):
                native_work(native, cost, source, expected)

    def test_rehashed_wrong_teacher_units_still_rejects(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "fixture"
            shutil.copytree(self.root, target)
            meta = read(target, "datasets/991/training.json")
            path = target / meta["path"]
            with np.load(path, allow_pickle=False) as data:
                arrays = {name: data[name].copy() for name in data.files}
            arrays["context_0_target_q"] /= 8
            np.savez_compressed(path, **arrays)
            meta["sha256"] = sha(path.read_bytes())
            (target / "datasets/991/training.json").write_bytes(canonical(meta))
            with self.assertRaisesRegex(ValueError, "teacher units"):
                training_arrays(target, 991, self.refs, 2, 2)

    def test_optimizer_coefficients_and_matched_budget_tampering_rejects(self):
        features, teacher = training_arrays(self.root, 991, self.refs, 2, 2)
        activation, physical, _ = verify_export(self.root, 991, features, teacher, 2, 2)
        ckpt, _ = self.checkpoints[991, "policy_regret"]
        item = read(self.root, "training/991/policy_regret/TRAINING.json")[
            "candidates"
        ][0]
        verify_fit(item, ckpt, activation, physical, epochs=4)
        changed = deepcopy(ckpt)
        changed["head_coefficients"][0][0] += 0.001
        with self.assertRaises(ValueError):
            verify_fit(item, changed, activation, physical, epochs=4)
        item = deepcopy(item)
        item["fit"]["epochs"] = 5
        with self.assertRaises(ValueError):
            verify_fit(item, ckpt, activation, physical, epochs=4)

    def test_rehashed_signed_diagnostic_corruption_rejects(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "fixture"
            shutil.copytree(self.root, target)
            panel_item = deepcopy(self.summary["diagnostic_panel"])
            panel = read(target, panel_item["path"])
            arm_summary = panel["arms"][2]
            shard = arm_summary["shard"]
            records = load_shard(target, shard)
            records[0]["signed_quantization_regret"] = 0.125
            raw = b"".join(canonical(row) + b"\n" for row in records)
            path = target / shard["path"]
            path.write_bytes(gzip.compress(raw, mtime=0))
            shard.update(
                sha256=sha(path.read_bytes()),
                uncompressed_sha256=sha(raw),
                uncompressed_bytes=len(raw),
            )
            (target / "diagnostics/991/policy_regret.SUMMARY.json").write_bytes(
                canonical(arm_summary)
            )
            (target / panel_item["path"]).write_bytes(canonical(panel))
            panel_item["sha256"] = sha((target / panel_item["path"]).read_bytes())
            with self.assertRaisesRegex(ValueError, "signed diagnostic regret"):
                verify_panel(
                    target,
                    panel_item,
                    991,
                    self.refs,
                    self.checkpoints,
                    self.profiles,
                    1,
                    2,
                )


if __name__ == "__main__":
    unittest.main()
