"""Bounded safetensors archive checks; actual CPU weights, stdlib replay."""
import json
from pathlib import Path
import struct
import tempfile
import unittest

import torch
from torch import nn
from safetensors.torch import save_file

from group_checkpoint_audit import verify_checkpoint_file
from group_training import model_parameter_digest


def synthetic_file(path, *, dtype="F32", shape=None, offsets=None, data=None):
    if shape is None:
        shape = [2]
    if offsets is None:
        offsets = [0, 8]
    if data is None:
        data = struct.pack("<ff", 0.5, -2.0)
    header = json.dumps({
        "weight": {"dtype": dtype, "shape": shape, "data_offsets": offsets}
    }, sort_keys=True, separators=(",", ":")).encode()
    path.write_bytes(len(header).to_bytes(8, "little") + header + data)


class CheckpointAuditTests(unittest.TestCase):
    def test_real_pytorch_model_matches_independent_stored_tensor_digest(self):
        torch.manual_seed(10)
        model = nn.Sequential(nn.Linear(8, 12), nn.GELU(), nn.Linear(12, 8))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "actual.safetensors"
            save_file({n: v.detach().cpu().contiguous()
                       for n, v in model.state_dict().items()}, str(path))
            reviewed = verify_checkpoint_file(path)
            self.assertEqual(reviewed["model_sha256"], model_parameter_digest(model))
            self.assertEqual(reviewed["authority"], "DENY_ALL")
            self.assertFalse(reviewed["source_model_execution_attested"])
            self.assertEqual(len(reviewed["tensors"]), len(model.state_dict()))

    def test_reject_bad_shape_offset_nonfinite_and_wrong_dtype(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "malformed.safetensors"
            for keyword in (
                dict(dtype="F64"),
                dict(shape=[3]),
                dict(offsets=[1, 9]),
                dict(offsets=[0, 4]),
                dict(data=struct.pack("<ff", float("nan"), 1.0)),
            ):
                with self.subTest(mutation=keyword), self.assertRaises(ValueError):
                    synthetic_file(path, **keyword)
                    verify_checkpoint_file(path)

    def test_reject_truncation_trailing_bytes_and_header_overflow(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.safetensors"
            synthetic_file(path)
            original = path.read_bytes()
            for mutated in (original[:-1], original + b"ignored",
                            (2_000_000).to_bytes(8, "little") + original[8:]):
                with self.subTest(bytes=len(mutated)), self.assertRaises(ValueError):
                    path.write_bytes(mutated)
                    verify_checkpoint_file(path)


if __name__ == "__main__":
    unittest.main()
