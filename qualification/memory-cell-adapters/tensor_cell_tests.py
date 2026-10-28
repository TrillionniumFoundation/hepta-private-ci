"""Behavioral tests for real updates, isolated division and portable checkpoints."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np
import torch

from split import distill_merge, fixed_experts, matched_high_rank, split_pair
from tensor_cell import BLOB_CAP, CellConfig, OutputSpec, TensorCell, digest, unique_parameter_count


ROOT = Path(__file__).parent
TEST_ENCODER_SHA = "a" * 64


class TensorCellTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)

    def problem(self):
        x = np.random.default_rng(73).normal(size=(128, 12)).astype(np.float32)
        y = np.column_stack((x[:, 0] > x[:, 1], x[:, 2] > 0)).astype(np.float32)
        return x, y, [f"behavioral-fixture:{index}" for index in range(len(x))]

    def cell(self, name="parent", outputs=None):
        outputs = outputs or (OutputSpec("bits", "binary", 2),)
        return TensorCell(CellConfig(name, rank=2, input_dim=12, outputs=outputs, seed=41), TEST_ENCODER_SHA)

    def test_frozen_head_adapter_updates_and_retains_no_answer_table(self):
        x, y, ids = self.problem()
        cell = self.cell().freeze_head()
        old_a, old_b = cell.A.detach().clone(), cell.B.detach().clone()
        head = [p.detach().clone() for p in cell.head.parameters()]
        receipt = cell.fit(x, y, source_ids=ids, steps=100, batch_size=32, lr=0.04)
        self.assertLess(receipt["final_loss"], receipt["initial_loss"] * 0.4)
        self.assertFalse(torch.equal(old_a, cell.A))
        self.assertFalse(torch.equal(old_b, cell.B))
        self.assertTrue(all(torch.equal(a, b) for a, b in zip(head, cell.head.parameters(), strict=True)))
        self.assertEqual(receipt["sample_presentations"], 3200)
        self.assertGreater(receipt["max_gradient_norm"]["A"], 0)
        self.assertGreater(receipt["max_gradient_norm"]["B"], 0)
        self.assertGreater(float((cell.predict(x)["bits"] == y).mean()), 0.95)
        self.assertEqual(set(cell.state_dict()), {"A", "B", "head.weight", "head.bias"})
        control = cell.without_adapter("zero-adapter")
        with torch.no_grad():
            np.testing.assert_array_equal(control.raw_outputs(x), control.head(torch.from_numpy(x)).numpy())

    def test_split_preserves_behavior_then_diverges_without_sibling_mutation(self):
        x, y, ids = self.problem()
        parent = self.cell()
        parent.fit(x, y, source_ids=ids, steps=20, batch_size=16, lr=0.03)
        parent_digest = parent.parameter_digest()
        children = split_pair(parent, ("child-a", "child-b"))
        high = matched_high_rank(parent, "high-rank")
        fixed = fixed_experts(parent, ("fixed-a", "fixed-b"))
        for child in children:
            np.testing.assert_array_equal(parent.raw_outputs(x), child.raw_outputs(x))
        np.testing.assert_allclose(parent.raw_outputs(x), high.raw_outputs(x), rtol=1e-6, atol=1e-6)
        self.assertEqual(unique_parameter_count(children), unique_parameter_count([high]))
        self.assertEqual(unique_parameter_count(fixed), unique_parameter_count([high]))
        other_digest = children[1].parameter_digest()
        left = children[0].fit(x, 1 - y, source_ids=ids, steps=50, batch_size=16, lr=0.04)
        self.assertEqual(children[1].parameter_digest(), other_digest)
        self.assertEqual(parent.parameter_digest(), parent_digest)
        right = children[1].fit(x, y, source_ids=ids, steps=50, batch_size=16, lr=0.04)
        single = high.fit(x, y, source_ids=ids, steps=100, batch_size=16, lr=0.04)
        self.assertEqual(left["sample_presentations"] + right["sample_presentations"], single["sample_presentations"])
        self.assertGreater(np.linalg.norm(children[0].raw_outputs(x) - children[1].raw_outputs(x)), 1.0)
        self.assertLess(left["final_loss"], left["initial_loss"])
        self.assertLess(right["final_loss"], right["initial_loss"])
        with self.assertRaises(ValueError):
            children[0].fit(x, y, source_ids=ids, steps=1, train_head=True)

    def test_multiple_classification_heads_and_regression(self):
        x, _, ids = self.problem()
        outputs = (OutputSpec("action", "multiclass", 3), OutputSpec("value", "regression", 1))
        cell = self.cell(outputs=outputs)
        targets = {"action": x[:, :3].argmax(1), "value": 0.2 * x[:, 4]}
        receipt = cell.fit(x, targets, source_ids=ids, steps=120, batch_size=32, lr=0.03)
        predictions = cell.predict(x)
        self.assertLess(receipt["final_loss"], 0.15)
        self.assertGreater(np.mean(predictions["action"] == targets["action"]), 0.95)
        self.assertLess(np.mean((predictions["value"][:, 0] - targets["value"]) ** 2), 0.01)

    def test_merge_uses_routed_behavior_and_keeps_teachers_immutable(self):
        x, y, ids = self.problem()
        parent = self.cell().freeze_head()
        teachers = split_pair(parent, ("teacher-a", "teacher-b"))
        for index, teacher in enumerate(teachers):
            teacher.fit(x, y, source_ids=ids, steps=60, batch_size=32, lr=0.04, seed=index)
        old = [t.parameter_digest() for t in teachers]
        merged, receipt = distill_merge(teachers, x, np.arange(len(x)) % 2, source_ids=ids,
                                        cell_id="merged", rank=4, steps=80, lr=0.02)
        self.assertLess(receipt["final_loss"], receipt["initial_loss"] * 0.7)
        self.assertEqual(old, [t.parameter_digest() for t in teachers])
        self.assertEqual(receipt["teacher_parameter_sha256"], old)
        assignments = (np.arange(len(x)) % 2).astype("<i8")
        self.assertEqual(receipt["teacher_assignments_sha256"], digest(assignments.tobytes()))
        self.assertEqual(receipt["teacher_forward_rows"], len(x))
        self.assertEqual(merged.source_ids, set(ids))

    def test_checkpoint_fresh_process_shared_head_and_tamper_rejection(self):
        x, y, ids = self.problem()
        cell = self.cell()
        cell.fit(x, y, source_ids=ids, steps=25, batch_size=32, lr=0.03)
        children = split_pair(cell, ("a", "b"))
        with tempfile.TemporaryDirectory(prefix="tensor-cell-test-", dir=ROOT) as temporary:
            path = Path(temporary) / "checkpoint"
            saved = children[0].save(path)
            self.assertGreater(saved["stored_bytes"], 0)
            manifest = json.loads((path / "manifest.json").read_bytes())
            self.assertEqual(set(manifest["tensors"]), {"A", "B", "head.weight", "head.bias"})
            loaded = TensorCell.load(path, TEST_ENCODER_SHA, shared_head=cell.head)
            self.assertIs(loaded.head, cell.head)
            self.assertEqual(loaded.source_ids, children[0].source_ids)
            code = "import json,sys; from tensor_cell import TensorCell; print(json.dumps(TensorCell.load(sys.argv[1]).raw_outputs(json.load(sys.stdin)).tolist()))"
            process = subprocess.run([sys.executable, "-B", "-c", code, str(path)], cwd=ROOT,
                                     input=json.dumps(x[:5].tolist()), text=True, capture_output=True, check=True)
            np.testing.assert_array_equal(np.asarray(json.loads(process.stdout), dtype=np.float32), children[0].raw_outputs(x[:5]))
            with self.assertRaises(ValueError):
                TensorCell.load(path, "b" * 64)
            chunk = path / manifest["tensors"]["A"]["parts"][0]["file"]
            raw = bytearray(chunk.read_bytes())
            raw[-1] ^= 1
            chunk.write_bytes(raw)
            with self.assertRaises(ValueError):
                TensorCell.load(path)

    def test_large_tensor_is_chunked_below_publication_cap(self):
        cell = TensorCell(CellConfig("large-checkpoint", rank=384), TEST_ENCODER_SHA)
        with tempfile.TemporaryDirectory(prefix="tensor-cell-test-", dir=ROOT) as temporary:
            path = Path(temporary) / "checkpoint"
            cell.save(path)
            self.assertTrue(all(p.stat().st_size <= BLOB_CAP for p in path.iterdir()))
            loaded = TensorCell.load(path)
            self.assertEqual(loaded.parameter_digest(), cell.parameter_digest())
            self.assertGreater(len(json.loads((path / "manifest.json").read_bytes())["tensors"]["A"]["parts"]), 1)

    @unittest.skipUnless(os.environ.get("HEPTA_ENCODER_PYTHON") and os.environ.get("HEPTA_ENCODER_DIR"), "explicit pretrained integration environment required")
    def test_actual_pinned_encoder_preserves_content_and_query_independence(self):
        code = """import json,sys,numpy as np
from encoder import PinnedMiniLMEncoder
encoder= PinnedMiniLMEncoder(sys.argv[1])
x=encoder.encode(['Alice prefers tea on 2026-01-01.', 'Bob prefers coffee on 2026-01-02.', 'Alice prefers tea on 2026-01-01.'])
print(json.dumps({'shape':list(x.shape),'norms':np.linalg.norm(x,axis=1).tolist(),'repeat_equal':bool(np.array_equal(x[0],x[2])),'distinct':bool(not np.array_equal(x[0],x[1])),'receipt':encoder.receipt()}))
"""
        process = subprocess.run([os.environ["HEPTA_ENCODER_PYTHON"], "-B", "-c", code, os.environ["HEPTA_ENCODER_DIR"]],
                                 cwd=ROOT, capture_output=True, text=True, check=True)
        result = json.loads(process.stdout)
        self.assertEqual(result["shape"], [3, 384])
        self.assertTrue(result["repeat_equal"] and result["distinct"])
        np.testing.assert_allclose(result["norms"], 1, atol=1e-6)
        self.assertEqual(result["receipt"]["inference_calls"], 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
