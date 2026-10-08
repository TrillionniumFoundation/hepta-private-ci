import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import torch

from composition import CellCircuit, MODES, export_native, fit
from native import Benchmark, Question


class IsolationTests(unittest.TestCase):
    def test_every_arm_is_independent_of_other_request_rows(self):
        for mode in MODES:
            torch.manual_seed(8)
            model = CellCircuit(12, mode=mode).eval()
            own = torch.randn(1, 12)
            with torch.no_grad():
                single = model(own)
                together = model(torch.cat([own, torch.randn(6, 12)]))[:1]
            torch.testing.assert_close(single, together)

    def test_small_family_partition_has_no_empty_phase_and_ignores_answers(self):
        questions = tuple(Question(str(i), str(i), str(i), "query", "2024") for i in range(10))
        benchmark = Benchmark("locomo", "digest", (), questions, {}, {str(i): str(i) for i in range(10)})
        phases = [benchmark.partition(q) for q in questions]
        self.assertEqual([phases.count(p) for p in ("train", "select", "test")], [6, 2, 2])
        for question in reversed(questions):
            self.assertEqual(benchmark.partition(question), phases[int(question.identity)])

    def test_actual_tensor_export_is_bound_and_reports_quantized_inputs(self):
        rng = np.random.default_rng(5)
        x = rng.normal(size=(12, 8)).astype(np.float32)
        labels = (x[:, 0] > 0).astype(int)
        model = fit(x, labels, ["train"] * 12, steps=2)["joint"][0]
        with tempfile.TemporaryDirectory() as root:
            output = Path(root) / "export"
            export_native(model, output, "a" * 64, "b" * 64, "c" * 64, x)
            artifact = json.loads((output / "circuit.json").read_text())
            parity = json.loads((output / "parity.json").read_text())
            self.assertEqual(artifact["semantic_weight"], model.semantic.weight.detach().flatten().tolist())
            self.assertEqual(len(parity["vectors"]), 12)
            self.assertEqual(artifact["scope_digest"], "c" * 64)
            with self.assertRaises(ValueError):
                export_native(model, Path(root) / "bad", "bad", "b" * 64, "c" * 64, x)


if __name__ == "__main__":
    torch.set_num_threads(2)
    unittest.main()
