"""True safetensors round-trip and anti-forgery checks on research Head files."""
from pathlib import Path
import tempfile
import unittest
from copy import deepcopy
from hashlib import sha256

import torch
from safetensors.torch import load_file, save_file
from experiments.shared_stem_cell.execution import Head, parameters

from amcn_head_integrity import validate_sealed_semantic_head
from amcn_core import Refused


class PhysicalSemanticHeadVerification(unittest.TestCase):
    def fixture(self, parent, kind):
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(17)
            model = Head(12, 2, kind=kind, rank=4).eval()
        path = parent / "model.safetensors"
        save_file({k: v.detach().cpu().contiguous()
                   for k, v in model.state_dict().items()}, str(path))
        meta = parameters(model)
        return path, {
            "schema": "hepta.amcn.real-head-candidate.v1",
            "production_accepted": False,
            "head_tensor_sha256": sha256(path.read_bytes()).hexdigest(),
            "head_geometry": meta, "head_training": {"metrics": {"trained": meta}},
        }

    def test_real_linear_lowrank_and_gated_weights_materialize(self):
        for kind in ("linear", "low_rank", "gated"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                path, receipt = self.fixture(Path(tmp), kind)
                r = validate_sealed_semantic_head(path, receipt)
                self.assertEqual(r["metrics"]["actual_head_kind"], kind)
                self.assertTrue(r["metrics"]["all_tensors_finite"])
                self.assertFalse(r["metrics"]["original_predictions_reexecuted_here"])
                self.assertFalse(r["production_accepted"])

    def test_bytes_sha_digest_and_training_manifest_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, receipt = self.fixture(Path(tmp), "gated")
            bad = deepcopy(receipt)
            bad["head_tensor_sha256"] = "0"*64
            with self.assertRaises(Refused):
                validate_sealed_semantic_head(path, bad)
            bad = deepcopy(receipt)
            bad["head_training"]["metrics"]["trained"]["sha256"] = "0"*64
            with self.assertRaises(Refused):
                validate_sealed_semantic_head(path, bad)
            bad = deepcopy(receipt)
            bad["head_geometry"]["parameters"] += 10
            with self.assertRaises(Refused):
                validate_sealed_semantic_head(path, bad)

    def test_corrupted_payload_even_rehashed_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, receipt = self.fixture(Path(tmp), "low_rank")
            path.write_bytes(b"not safetensors")
            receipt["head_tensor_sha256"] = sha256(path.read_bytes()).hexdigest()
            with self.assertRaises((ValueError, Refused)):
                validate_sealed_semantic_head(path, receipt)

    def test_nonfinite_tensor_even_rehashed_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, receipt = self.fixture(Path(tmp), "linear")
            state = load_file(str(path))
            state["base.weight"][0, 0] = float("inf")
            save_file(state, str(path))
            receipt["head_tensor_sha256"] = sha256(path.read_bytes()).hexdigest()
            with self.assertRaises(Refused):
                validate_sealed_semantic_head(path, receipt)

    def test_unexpected_extra_or_missing_tensors_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, receipt = self.fixture(Path(tmp), "linear")
            state = load_file(str(path))
            state["unknown.extra"] = torch.ones((5,), dtype=torch.float32)
            save_file(state, str(path))
            receipt["head_tensor_sha256"] = sha256(path.read_bytes()).hexdigest()
            with self.assertRaises(Refused):
                validate_sealed_semantic_head(path, receipt)


if __name__ == "__main__":
    unittest.main()
