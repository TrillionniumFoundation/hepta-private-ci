"""Offline adversarial contract tests; no fabricated pretrained model claims."""
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from cell_learning import (
    DynamicCell, LearningContractError, Q24, budgeted_cell, paired_future_score,
    q24_reference, rust_candidate_digest, validate_rust_candidate,
)
from offline_stem import (
    OfflineSharedStem, StemQualificationError, digest, joint_text,
    load_pinned_snapshot, quantize_q24, verify_request,
)
from organ_transfer import compare_organ, fit_frozen_organ
from scale_probe import run_head_probe


def fixture_q24():
    return {
        "cell_identity": "cell.a", "encoder_digest": "a" * 64,
        "input_width": 2, "output_width": 1, "rank": 1, "groups": 2,
        "down_q24": [Q24, 0], "up_q24": [Q24, Q24],
        "gate_bias_q24": [0, 0], "cell_state_q24": [0, 0],
        "drive_weights_q24": [Q24, Q24],
        "prediction_weights_q24": [Q24, 0],
        "drive_bias_q24": [0], "prediction_bias_q24": [0],
    }


def request(cell, scope="scope.a", principal="principal.a"):
    return {
        "scope_id": scope, "principal_id": principal,
        "purpose_id": "purpose.decision", "cell_id": cell,
        "generation": 3, "authority_epoch": 2,
        "input": {"question": "选择什么？", "options": ["A", "B"], "state": "情境"},
    }


class StemContracts(unittest.TestCase):
    def test_full_joint_text_is_stable_and_unambiguous(self):
        a = joint_text(request("cell.a")["input"])
        b = joint_text(request("cell.a")["input"])
        self.assertEqual(a, b)
        self.assertIn("选择什么？", a)
        self.assertIn('"options":["A","B"]', a)
        self.assertIn("情境", a)
        with self.assertRaises(StemQualificationError):
            joint_text({"question": "q", "state": "s", "options": []})

    def test_scope_principal_epoch_break_reuse_identity(self):
        original = verify_request(request("cell.a"))[0]
        self.assertEqual(original, verify_request(request("cell.b"))[0])
        self.assertNotEqual(original, verify_request(request("cell.b", scope="scope.b"))[0])
        self.assertNotEqual(original, verify_request(request("cell.b", principal="other"))[0])
        changed = request("cell.b")
        changed["authority_epoch"] = 3
        self.assertNotEqual(original, verify_request(changed)[0])

    def test_fanout_algorithm_is_strictly_non_authorizing_without_weight_fixture(self):
        # This is explicitly NOT a real encoder forward: only the admission /
        # fanout algorithm is being tested under an injected deterministic stub.
        stub = OfflineSharedStem.__new__(OfflineSharedStem)
        stub.pipeline_digest = "a" * 64
        stub.forward_calls = 0
        def fake_encoder(inputs):
            stub.forward_calls += 1
            return [[Q24, 0] for _ in inputs]
        stub._encode_unique = fake_encoder
        result = stub.encode_fanout([request("cell.a"), request("cell.b")])
        self.assertEqual(result["distinct_inputs"], 1)
        self.assertEqual(result["actual_pretrained_forward_calls"], 1)  # stub-only
        self.assertEqual(result["rows"][0]["authority"], "DENY_ALL")
        with self.assertRaises(StemQualificationError):
            stub.encode_fanout([request("cell.c"), request("cell.d", scope="scope.b")])
        with self.assertRaises(StemQualificationError):
            stub.encode_fanout([request("cell.c"), request("cell.d", principal="another")])
        with self.assertRaises(StemQualificationError):
            differing = request("cell.d")
            differing["authority_epoch"] = 4
            stub.encode_fanout([request("cell.c"), differing])

    def test_q24_rejects_wide_nonfinite_and_out_of_range(self):
        self.assertEqual(quantize_q24([0.5, -0.25]), [Q24 // 2, -Q24 // 4])
        with self.assertRaises(StemQualificationError):
            quantize_q24([float("nan")])
        with self.assertRaises(StemQualificationError):
            quantize_q24([9])
        with self.assertRaises(StemQualificationError):
            quantize_q24([0.0] * 768)

    def test_complete_snapshot_immutable_file_hashes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            snap = root / "snapshot"
            snap.mkdir()
            (snap / "config.json").write_text('{"architectures":[]}', encoding="utf-8")
            (snap / "model.safetensors").write_bytes(b"not actual weights, hash contract only")
            files = {name: digest((snap / name).read_bytes()) for name in
                     ("config.json", "model.safetensors")}
            manifest = {
                "model_id": "jhu-clsp/mmBERT-small",
                "revision": "a" * 40, "snapshot": "snapshot",
                "files": files, "max_tokens": 8192,
                "runtime": {"torch": "2.8.0", "transformers": "4.57.0",
                            "tokenizers": "0.22.1", "safetensors": "0.6.2"},
            }
            path = root / "manifest.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            self.assertEqual(load_pinned_snapshot(path)[0]["files"], files)
            invalid_runtime = dict(manifest)
            invalid_runtime["runtime"] = {"torch": "2.8.0"}
            path.write_text(json.dumps(invalid_runtime), encoding="utf-8")
            with self.assertRaises(StemQualificationError):
                load_pinned_snapshot(path)
            path.write_text(json.dumps(manifest), encoding="utf-8")
            (snap / "config.json").write_text("tampered", encoding="utf-8")
            with self.assertRaises(StemQualificationError):
                load_pinned_snapshot(path)
            (snap / "config.json").write_text('{"architectures":[]}', encoding="utf-8")
            (snap / "hidden.txt").write_text("unlisted", encoding="utf-8")
            with self.assertRaises(StemQualificationError):
                load_pinned_snapshot(path)
            (snap / "hidden.txt").unlink()
            manifest["revision"] = "main"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(StemQualificationError):
                load_pinned_snapshot(path)


class DynamicLearning(unittest.TestCase):
    def test_2k_8k_16k_tiers_have_real_distinct_parameter_budgets(self):
        sizes = []
        for ceiling in (2048, 8192, 16384):
            head = budgeted_cell("cell.a", "a" * 64, 384, ceiling, seed=4)
            self.assertLessEqual(head.parameter_count(), ceiling)
            self.assertGreater(head.parameter_count(), 0)
            sizes.append(head.parameter_count())
        self.assertEqual(sizes, sorted(sizes))
        self.assertEqual(len(set(sizes)), 3)

    def test_cross_language_candidate_digest_golden(self):
        self.assertEqual(
            rust_candidate_digest(fixture_q24()),
            "31d23d4d80f039d5fbe63b8dfde0f37e36b7f6b044e11b50f4d0b166f3a3ed22",
        )
        drive, prediction = q24_reference(fixture_q24(), [Q24, Q24])
        self.assertEqual((drive, prediction), ([3 * Q24 // 2], [3 * Q24 // 4]))

    def test_rust_gate_rejects_bad_shapes_coerced_numbers_and_forged_identity(self):
        valid = fixture_q24()
        self.assertEqual(validate_rust_candidate(valid), 14)
        invalid_cases = [
            ("extra tensor value", lambda x: x["down_q24"].append(0)),
            ("missing tensor value", lambda x: x["up_q24"].pop()),
            ("wrong output shape", lambda x: x.update({"output_width": 2})),
            ("bool coefficient", lambda x: x["gate_bias_q24"].__setitem__(0, True)),
            ("coerced float", lambda x: x["up_q24"].__setitem__(0, float(Q24))),
            ("out of range", lambda x: x["cell_state_q24"].__setitem__(0, 8 * Q24 + 1)),
            ("integer dimension bool", lambda x: x.update({"rank": True})),
            ("extra unknown field", lambda x: x.update({"authority": "production"})),
            ("missing field", lambda x: x.pop("prediction_bias_q24")),
            ("zero encoder", lambda x: x.update({"encoder_digest": "0" * 64})),
            ("uppercase encoder", lambda x: x.update({"encoder_digest": "A" * 64})),
            ("unsafe Cell identity", lambda x: x.update({"cell_identity": "../cell"})),
            ("non-ascii Cell identity", lambda x: x.update({"cell_identity": "神经元"})),
        ]
        for name, mutation in invalid_cases:
            with self.subTest(name=name):
                item = copy.deepcopy(valid)
                mutation(item)
                with self.assertRaises(LearningContractError):
                    validate_rust_candidate(item)
                with self.assertRaises(LearningContractError):
                    rust_candidate_digest(item)
                with self.assertRaises(LearningContractError):
                    q24_reference(item, [Q24, Q24])
        for bad_inputs in (
                [True, Q24], [Q24, float(Q24)],
                [8 * Q24 + 1, Q24], [Q24],
                np.array([Q24, Q24]), [0, "0"]):
            with self.subTest(input=str(bad_inputs)):
                with self.assertRaises(LearningContractError):
                    q24_reference(valid, bad_inputs)
        for bad_id, bad_digest in (
                ("../wrong", "a" * 64),
                ("cell.a", "0" * 64),
                ("cell.a", "A" * 64)):
            with self.assertRaises(LearningContractError):
                DynamicCell.initialize(bad_id, bad_digest, 2, 2, 1, seed=4)

    def test_real_sgd_improves_future_on_synthetic_task_not_production(self):
        rng = np.random.default_rng(42)
        x = rng.normal(0, 0.45, (256, 16))
        y = (x[:, 0] + x[:, 1] * 0.7 > 0).astype(np.float64)
        f = rng.normal(0, 0.45, (128, 16))
        fy = (f[:, 0] + f[:, 1] * 0.7 > 0).astype(np.float64)
        trained = DynamicCell.initialize("cell.a", "a" * 64, 16, 4, 4, seed=9)
        frozen = trained.clone_frozen()
        frozen_digest = rust_candidate_digest(frozen.export_q24())
        for _ in range(100):
            trained.learn(x, y, lr=0.4)
        self.assertEqual(frozen_digest, rust_candidate_digest(frozen.export_q24()))
        self.assertNotEqual(frozen_digest, rust_candidate_digest(trained.export_q24()))
        score = paired_future_score(trained, frozen, f, fy, np.full(len(f), 0.5))
        self.assertLess(score["trained_bce"], score["frozen_bce"])
        self.assertLess(score["trained_bce"], score["no_change_bce"])

    def test_exported_q24_numeric_parity_without_float_shortcuts(self):
        cell = DynamicCell.initialize("cell.a", "a" * 64, 16, 4, 4, seed=5)
        rng = np.random.default_rng(7)
        x = rng.normal(0.0, 0.2, (16, 16))
        c = cell.export_q24()
        for row in x:
            input_q = np.rint(row * Q24).astype(np.int64).tolist()
            drive_q, pred_q = q24_reference(c, input_q)
            prediction, drive, _ = cell._forward(row[None, :])
            self.assertLess(abs(drive_q[0] / Q24 - drive[0]), 0.02)
            self.assertLess(abs(pred_q[0] / Q24 - prediction[0]), 0.02)

    def test_future_score_rejects_label_broadcasting_and_invalid_outcomes(self):
        head = DynamicCell.initialize("cell.a", "a" * 64, 8, 4, 4, seed=2)
        frozen = head.clone_frozen()
        x = np.zeros((4, 8))
        y = np.array([0.0, 1.0, 0.0, 1.0])
        baseline = np.full(4, 0.5)
        score = paired_future_score(head, frozen, x, y, baseline)
        self.assertTrue(np.isfinite(score["trained_bce"]))
        self.assertAlmostEqual(score["no_change_brier"], 0.25)
        self.assertAlmostEqual(score["no_change_ece"], 0.0)
        for candidate in ("no_change", "frozen", "trained"):
            for metric in ("bce", "brier", "ece"):
                self.assertTrue(np.isfinite(score[f"{candidate}_{metric}"]))
            self.assertGreaterEqual(score[f"{candidate}_brier"], 0.0)
            self.assertLessEqual(score[f"{candidate}_brier"], 1.0)
            self.assertGreaterEqual(score[f"{candidate}_ece"], 0.0)
            self.assertLessEqual(score[f"{candidate}_ece"], 1.0)
        malformed = [
            (y[:, None], baseline[:, None]),  # old code silently broadcast logits
            (np.array([0.0, 1.0, np.nan, 1.0]), baseline),
            (np.array([0.0, 1.0, 2.0, 1.0]), baseline),
        ]
        for labels, probabilities in malformed:
            with self.subTest(labels=labels.shape):
                with self.assertRaises(LearningContractError):
                    paired_future_score(head, frozen, x, labels, probabilities)
        with self.assertRaises(LearningContractError):
            paired_future_score(head, frozen, x[:0], y[:0], baseline[:0])
        with self.assertRaises(LearningContractError):
            paired_future_score(
                head, frozen, x, y, np.array([0.5, 0.5, np.nan, 0.5])
            )
        incompatible = DynamicCell.initialize("cell.a", "a" * 64, 16, 4, 4, seed=2)
        with self.assertRaises(LearningContractError):
            paired_future_score(head, incompatible, x, y, baseline)
        poisoned = head.clone_frozen()
        poisoned.prediction_weights[0] = np.nan
        with self.assertRaises(LearningContractError):
            paired_future_score(poisoned, frozen, x, y, baseline)

    def test_cell_learning_is_independent_and_no_change_mandatory(self):
        a = DynamicCell.initialize("cell.a", "a" * 64, 8, 4, 4, seed=2)
        b = DynamicCell.initialize("cell.b", "a" * 64, 8, 4, 4, seed=2)
        before_b = rust_candidate_digest(b.export_q24())
        x = np.ones((8, 8)) * 0.2
        a.learn(x, np.ones(8), lr=0.25)
        self.assertEqual(before_b, rust_candidate_digest(b.export_q24()))
        with self.assertRaises(LearningContractError):
            paired_future_score(a, b, x, np.ones(8), None)


class OrganAndScale(unittest.TestCase):
    def test_organ_transfer_has_disjoint_chronological_groups_and_equal_budgets(self):
        rng = np.random.default_rng(11)
        sx = rng.normal(0, .4, (64, 16))
        sy = (sx[:, 0] > 0).astype(int)
        organ = fit_frozen_organ("MemoryRead", sx, sy, [f"s{i}" for i in range(64)],
                                 list(range(64)))
        tx = rng.normal(0, .4, (48, 16))
        ty = (tx[:, 0] > 0).astype(int)
        fx = rng.normal(0, .4, (24, 16))
        fy = (fx[:, 0] > 0).astype(int)
        kwargs = dict(
            organ=organ, target_cell="cell.mem", encoder_digest="a" * 64,
            training_x=tx, training_y=ty, training_groups=[f"t{i}" for i in range(48)],
            training_times=list(range(100, 148)),
            future_x=fx, future_y=fy, future_groups=[f"f{i}" for i in range(24)],
            future_times=list(range(200, 224)),
            production_no_change=np.full(24, 0.5),
            steps=12,
        )
        report = compare_organ(**kwargs)
        self.assertEqual(report["role"], "MemoryRead")
        self.assertEqual(report["production_promotion"], "DENY_ALL")
        self.assertIn("negative_transfer", report)
        self.assertGreater(report["head_parameters"], 0)
        self.assertEqual(report["organ_shared_parameters"], 16)
        kwargs["future_groups"][0] = "t0"
        with self.assertRaises(LearningContractError):
            compare_organ(**kwargs)

    def test_organ_source_history_must_precede_target_learning(self):
        rng = np.random.default_rng(123)
        sx = rng.normal(0, 0.3, (64, 8))
        sy = (sx[:, 0] > 0).astype(np.float64)
        groups = [f"s{i}" for i in range(64)]
        with self.assertRaises(LearningContractError):
            fit_frozen_organ("MemoryRead", sx, sy[:, None], groups, list(range(64)))
        # Source remains earlier than future, but overlaps target training.
        # Prior logic accepted this retrospective transfer leakage.
        late_source = fit_frozen_organ(
            "MemoryRead", sx, sy, groups, list(range(90, 154))
        )
        tx = rng.normal(0, 0.3, (16, 8))
        future = rng.normal(0, 0.3, (8, 8))
        with self.assertRaises(LearningContractError):
            compare_organ(
                organ=late_source, target_cell="cell.mem",
                encoder_digest="a" * 64,
                training_x=tx, training_y=(tx[:, 0] > 0).astype(float),
                training_groups=[f"t{i}" for i in range(16)],
                training_times=list(range(100, 116)),
                future_x=future, future_y=(future[:, 0] > 0).astype(float),
                future_groups=[f"f{i}" for i in range(8)],
                future_times=list(range(200, 208)),
                production_no_change=np.full(8, 0.5),
                steps=1,
            )

    def test_organ_cannot_read_future_or_unsupported_role(self):
        x = np.ones((16, 8), dtype=float)
        y = np.arange(16) % 2
        with self.assertRaises(LearningContractError):
            fit_frozen_organ("Unauthorized", x, y, [str(i) for i in range(16)], list(range(16)))

    def test_bounded_resource_probe_reports_real_head_only(self):
        report = run_head_probe(64, 0.25, 0.5, feature_width=16)
        self.assertEqual(report["logical_cells"], 64)
        self.assertEqual(report["active_cells"], 16)
        self.assertEqual(report["distinct_synthetic_inputs"], 8)
        self.assertFalse(report["physical_pretrained_encoder_executed"])
        self.assertEqual(report["production_promotion"], "DENY_ALL")
        self.assertGreater(report["p99_head_micros"], 0)
        with self.assertRaises(LearningContractError):
            run_head_probe(8192, 1.0, 0.5)


if __name__ == "__main__":
    unittest.main()
