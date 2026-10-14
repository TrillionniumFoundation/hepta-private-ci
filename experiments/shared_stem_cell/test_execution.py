"""Real Torch regressions; random tensors below are explicitly NOT model evidence."""
from pathlib import Path
import tempfile
import unittest

import torch
from torch import nn

from experiments.shared_stem_cell import execution as e
from experiments.shared_stem_cell import controls as c


class FakeEncoder:
    simulated = True
    identity = "fixture-only"

    def encode(self, texts):
        return torch.tensor([[len(t), sum(t.encode()) % 7] for t in texts], dtype=torch.float32)


class ExecutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)

    def cases(self):
        return tuple(e.Case(str(i), str(i), "train", i, 0, "scope", str(i % 3)) for i in range(9))

    def test_json_duplicate(self):
        for raw in (b'{"x":1,"x":2}', b'{"x":{"v":1,"v":2}}'):
            with self.assertRaises(e.InputError):
                e.decode(raw)

    def test_json_nonfinite(self):
        for raw in (b'{"x":NaN}', b'{"x":Infinity}', b'{"x":1e999}'):
            with self.assertRaises(ValueError):
                e.decode(raw)

    def test_write_once(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "a.json"
            e.write_once(path, {"n": 1})
            before = path.read_bytes()
            with self.assertRaises(FileExistsError):
                e.write_once(path, {"n": 2})
            self.assertEqual(path.read_bytes(), before)

    def test_invalid_write_has_no_file(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "a.json"
            with self.assertRaises(ValueError):
                e.write_once(path, {"x": float("nan")})
            self.assertFalse(path.exists())

    def test_digest_dtype_shape(self):
        x = torch.tensor([1, 2], dtype=torch.float32)
        self.assertNotEqual(e.tensor_digest(x), e.tensor_digest(x.reshape(1, 2)))
        self.assertNotEqual(e.tensor_digest(x), e.tensor_digest(x.bfloat16()))

    def test_real_batch_cache_parity(self):
        x, solo = e.encode_cases(FakeEncoder(), self.cases(), batch_size=1)
        y, batched = e.encode_cases(FakeEncoder(), self.cases(), batch_size=9)
        z, cached = e.encode_cases(FakeEncoder(), self.cases(), batch_size=3, cache_bytes=24)
        self.assertTrue(torch.equal(x, y) and torch.equal(y, z))
        self.assertEqual(solo["encoder_forward_calls"], 9)
        self.assertEqual(batched["encoder_forward_calls"], 1)
        self.assertEqual(cached["encoder_forward_calls"], 1)
        self.assertEqual(cached["cache_reuses"], 6)
        self.assertIsNone(cached["energy_joules"])

    def test_cache_hits_survive_eviction(self):
        cases = list(self.cases())[:4]
        x, _ = e.encode_cases(FakeEncoder(), cases, batch_size=2)
        y, _ = e.encode_cases(FakeEncoder(), cases, batch_size=2, cache_bytes=16)
        self.assertTrue(torch.equal(x, y))

    def test_cache_rows_do_not_pin_whole_batch(self):
        _, report = e.encode_cases(FakeEncoder(), self.cases(), batch_size=9, cache_bytes=8)
        self.assertEqual(report["cache_retained_tensor_bytes"], 8)
        self.assertFalse(report["cache_object_overhead_measured"])

    def test_invalid_batch_never_returns_partial(self):
        class Invalid(FakeEncoder):
            def encode(self, texts):
                values = super().encode(texts)
                values[-1, 0] = float("nan")
                return values
        with self.assertRaises(e.InputError):
            e.encode_cases(Invalid(), self.cases(), cache_bytes=1024)

    def test_cross_scope_batch_rejects_before_encoder(self):
        from dataclasses import replace
        cases = list(self.cases())
        cases[1] = replace(cases[1], scope="other")
        class Never(FakeEncoder):
            def encode(self, texts):
                raise AssertionError("backend should not run")
        with self.assertRaises(e.InputError):
            e.encode_cases(Never(), cases)

    def test_late_cross_scope_and_singleton_batch_refuse_before_any_forward(self):
        from dataclasses import replace
        cases = list(self.cases())
        cases[-1] = replace(cases[-1], scope="other")

        class Counting(FakeEncoder):
            def __init__(self):
                self.calls = 0

            def encode(self, texts):
                self.calls += 1
                return super().encode(texts)

        for batch in (1, 3, 8):
            backend = Counting()
            with self.subTest(batch=batch), self.assertRaises(e.InputError):
                e.encode_cases(backend, cases, batch_size=batch, cache_bytes=1024)
            self.assertEqual(backend.calls, 0)

    def test_encoder_workload_preflight_rejects_missing_case_without_forward(self):
        class Never(FakeEncoder):
            def encode(self, texts):
                raise AssertionError("invalid complete workload must not dispatch")

        with self.assertRaises(e.InputError):
            e.encode_cases(Never(), (*self.cases(), None), batch_size=1)
        with self.assertRaises(e.InputError):
            e.encode_cases(Never(), (), batch_size=1)

    def rows(self):
        return [{"case_id": str(i), "group": str(i), "split": split,
                 "observed_at": i + 1, "cell": 0, "scope": "s", "text": f"sample {i}", "label": i % 2}
                for i, split in enumerate(("train", "train", "calibration", "holdout"))]

    def load_rows(self, rows, temporal=True):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "dataset.jsonl"
            raw = b"".join(e.canonical(r) for r in rows)
            path.write_bytes(raw)
            return e.dataset(path, e.sha(raw), 2, 1, temporal)

    def test_dataset_label_redaction(self):
        cases, labels = self.load_rows(self.rows())
        self.assertFalse(hasattr(cases[0], "label"))
        self.assertEqual(labels["0"], 0)

    def test_dataset_cross_fold_group(self):
        rows = self.rows()
        rows[-1]["group"] = rows[0]["group"]
        with self.assertRaises(e.InputError):
            self.load_rows(rows)

    def test_dataset_cross_fold_content(self):
        rows = self.rows()
        rows[-1]["text"] = rows[0]["text"]
        rows[-1]["scope"] = "other"
        with self.assertRaises(e.InputError):
            self.load_rows(rows)

    def test_dataset_actual_chronology(self):
        rows = self.rows()
        rows[-1]["observed_at"] = 0
        with self.assertRaises(e.InputError):
            self.load_rows(rows)

    def test_dataset_missing_time_not_imputed(self):
        rows = self.rows()
        rows[-1]["observed_at"] = None
        with self.assertRaises(e.InputError):
            self.load_rows(rows)
        self.assertEqual(len(self.load_rows(rows, False)[0]), 4)

    def test_missing_model_no_synthetic_fallback(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(e.InputError):
                e.LocalEncoder(Path(root) / "missing", {"revision": "a" * 40})

    def test_source_digest_drift(self):
        with tempfile.TemporaryDirectory() as root:
            p = Path(root) / "a"
            p.write_bytes(b"wrong")
            with self.assertRaises(e.InputError):
                e.bound_file(p, e.sha(b"right"))

    def test_snapshot_extra_member(self):
        from safetensors.torch import save_file
        with tempfile.TemporaryDirectory() as root:
            p = Path(root)
            save_file({"x": torch.ones(1)}, str(p / "a.safetensors"))
            m = {"revision": "a" * 40, "files": {"a.safetensors": e.sha((p / "a.safetensors").read_bytes())}}
            e.verify_snapshot(p, m)
            (p / "undeclared.json").write_text("{}")
            with self.assertRaises(e.InputError):
                e.verify_snapshot(p, m)

    def test_four_actual_trainers_and_frozen_preservation(self):
        torch.manual_seed(4)
        x = torch.randn(32, 8)
        y = (x[:, 0] > 0).long()
        for kind in ("linear", "gated", "low_rank", "sparse_expert"):
            initial = e.Head(8, 2, kind, 4).eval()
            original = e.parameters(initial)["sha256"]
            trained, report = e.fit(initial, x, y, steps=8)
            self.assertEqual(e.parameters(initial)["sha256"], original)
            self.assertNotEqual(report["sha256"], original)
            self.assertEqual(tuple(trained(x).shape), (32, 2))

    def test_split_function_inheritance(self):
        parent = e.Head(4, 2, rank=4)
        x = torch.randn(12, 4)
        x[:, -1] = torch.arange(12) % 2
        self.assertTrue(torch.allclose(parent(x), c.RoutedSplit(parent)(x), rtol=1e-6, atol=1e-6))

    def test_split_same_information_and_budget(self):
        torch.manual_seed(1)
        x = torch.randn(24, 5)
        x[:, -1] = torch.arange(24) % 2
        y = (x[:, 0] > 0).long()
        result = c.split_trial(x, y, x[:8], classes=2, steps=3)
        self.assertGreaterEqual(result["larger_unsplit_parameter_gap"], 0)
        self.assertTrue(result["route_feature_shared_by_all_arms"])
        self.assertNotIn("more_data", result["predictions"])
        self.assertFalse(result["topology_activation"])

    def test_invalid_split_route(self):
        x = torch.ones(2, 4)
        x[:, -1] = 0.5
        with self.assertRaises(e.InputError):
            c.RoutedSplit(e.Head(4, 2, rank=4))(x)

    def modalities(self, n=8):
        return {k: (torch.randn(n, 2, 4), torch.ones(n, 2, dtype=torch.bool),
                    torch.tensor([[0., 1.]]).repeat(n, 1)) for k in ("text", "video")}

    def test_connector_gradients_do_not_enter_towers(self):
        inputs = self.modalities()
        for x, _, _ in inputs.values():
            x.requires_grad_(True)
        model = c.FusionHead({"text": (2, 4), "video": (2, 4)}, 2)
        model(inputs).sum().backward()
        self.assertTrue(all(v[0].grad is None for v in inputs.values()))
        self.assertIsNotNone(model.connectors["video"].weight.grad)

    def test_reversed_timestamps_reject(self):
        inputs = self.modalities()
        inputs["video"][2][:] = torch.tensor([1., 0.])
        with self.assertRaises(e.InputError):
            c.FusionHead({"text": (2, 4), "video": (2, 4)}, 2)(inputs)

    def test_real_connector_training_unimodal_controls(self):
        result = c.modality_trial(self.modalities(), torch.arange(8) % 2,
                                  self.modalities(4), classes=2, steps=3)
        self.assertEqual(set(result["predictions"]), {"text", "video", "text+video"})
        self.assertIsNone(result["semantic_quality"])

    def test_recurrence_actual_halt_and_four_arms(self):
        torch.manual_seed(8)
        x = torch.randn(24, 2, 6)
        y = (x[:, 0, 0] > 0).long()
        r = c.recurrent_trial(x[:12], y[:12], x[12:18], y[12:18], x[18:], classes=2, steps=4)
        self.assertEqual(r["costs"]["no_recurrence"]["cell_transitions"], 6)
        self.assertEqual(r["costs"]["fixed_recurrence"]["cell_transitions"], 24)
        self.assertLessEqual(r["costs"]["adaptive_ndu_linear"]["cell_transitions"], 24)
        self.assertIsNone(r["general_fbsde_gain"])

    def test_distillation_preserves_selected_models(self):
        torch.manual_seed(3)
        x = torch.randn(16, 4)
        teachers = [nn.Linear(4, 2), nn.Linear(4, 2)]
        student = nn.Linear(4, 2)
        digest = e.parameters(student)["sha256"]
        candidate, result = c.distill_heads(teachers, student, x, x[:4], steps=3)
        self.assertEqual(e.parameters(student)["sha256"], digest)
        self.assertNotEqual(e.parameters(candidate)["sha256"], digest)
        self.assertFalse(result["generator_distillation_completed"])

    def test_predictor_accepts_train_labels_only_and_seals(self):
        rows = self.rows()
        cases, labels = self.load_rows(rows)
        x = torch.randn(4, 4)
        predictions, _ = e.head_trial(x, cases, {"0": 0, "1": 1}, classes=2, kind="linear", steps=3, seed=1)
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "predictions.json"
            seal = e.write_once(path, {"predictions": predictions})
            report = e.evaluate_sealed(path, seal, labels, cases)
            self.assertEqual(report[0]["cases"], 1)
            self.assertFalse(report[0]["independent_evaluation"])
            path.write_text("{}")
            with self.assertRaises(e.InputError):
                e.evaluate_sealed(path, seal, labels, cases)


    def test_empty_predictions_not_accepted(self):
        cases, labels = self.load_rows(self.rows())
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "predictions.json"
            seal = e.write_once(path, {"predictions": []})
            with self.assertRaises(e.InputError):
                e.evaluate_sealed(path, seal, labels, cases)

    def test_whole_missing_arm_not_accepted(self):
        cases, labels = self.load_rows(self.rows())
        row = {"case_id": "3", "input_digest": cases[-1].input_digest,
               "arm": "linear", "probabilities": [0.5, 0.5],
               "frozen_probabilities": [0.5, 0.5]}
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "predictions.json"
            seal = e.write_once(path, {"predictions": [row]})
            with self.assertRaises(e.InputError):
                e.evaluate_sealed(path, seal, labels, cases, expected_arms=("linear", "gated"))

    def test_external_metrics_do_not_inherit_synthetic_profile(self):
        from experiments.shared_stem_head_matrix.runner import ARMS, run
        rows = [{"arm_id": arm, "task_id": "task", "cells": 1,
                 "active_cells": 1, "training_budget": 1, "seed": 1,
                 "utility": 0.5, "active_flops_g": 1.0,
                 "latency_us": 2.0, "resident_memory_mb": 3.0} for arm in ARMS]
        result = run(tasks=("task",), cells=1, active_cells=1,
                     training_budget=1, seed=1, observations=rows)
        self.assertIsNone(result["profile"]["stem_digest"])
        for row in result["results"]:
            for key in ("incremental_parameters_m", "incremental_memory_mb", "negative_transfer_penalty"):
                self.assertIsNone(row[key])

    def test_existing_cli_invokes_real_path_without_synthetic_fallback(self):
        from experiments.shared_stem_head_matrix.runner import main
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)
            raw = b"".join(e.canonical(row) for row in self.rows())
            (path / "dataset.jsonl").write_bytes(raw)
            e.write_once(path / "manifest.json", {
                "schema": "hepta.shared-stem-execution.v1", "classes": 2, "cells": 1,
                "temporal": True, "dataset": {"path": "dataset.jsonl", "sha256": e.sha(raw)},
                "model": {"path": "missing", "revision": "a" * 40}})
            with self.assertRaises(e.InputError):
                main(["--execution-manifest", str(path / "manifest.json"),
                      "--output", str(path / "result")])
            self.assertTrue((path / "result/failure.json").is_file())
            self.assertFalse((path / "result/report.json").exists())


if __name__ == "__main__":
    unittest.main()
