"""Optional native PyTorch v2.8 checkpoint interoperability smoke test.

This test is skipped on Python installations without torch. It is not a
training experiment or validation of the original C2 zero-byte checkpoints.
"""
import hashlib
from pathlib import Path
import tempfile
import unittest

try:
    import torch
except ImportError:
    torch = None

try:
    from .c2_durable import EvidenceError, publish_checkpoint, verify_checkpoint
except ImportError:
    from c2_durable import EvidenceError, publish_checkpoint, verify_checkpoint


def same(left, right):
    if torch.is_tensor(left):
        return (torch.is_tensor(right) and left.dtype == right.dtype
                and left.shape == right.shape and torch.equal(left, right))
    if isinstance(left, dict):
        return type(right) is type(left) and left.keys() == right.keys() and all(
            same(left[key], right[key]) for key in left
        )
    if type(left) in (tuple, list):
        return type(right) is type(left) and len(left) == len(right) and all(
            same(a, b) for a, b in zip(left, right)
        )
    return type(left) is type(right) and left == right


@unittest.skipUnless(torch is not None, "torch is not installed on this interpreter")
class TorchInteropTests(unittest.TestCase):
    def test_actual_optimizer_model_rng_frozen_round_trip(self):
        torch.manual_seed(17)
        model = torch.nn.Linear(3, 2, dtype=torch.float64)
        optimizer = torch.optim.AdamW(model.parameters(), lr=0.001)
        loss = model(torch.ones((2, 3), dtype=torch.float64)).square().mean()
        loss.backward()
        optimizer.step()
        frozen = {
            "schema": "hcsn-c2-torch-interoperability-fixture-v1",
            "model": model.state_dict(),
            "optimizer": optimizer.state_dict(),
            "torch_rng": torch.get_rng_state(),
            "epochs_completed": 3,
            "main_updates": 3,
            "model_configuration": {"features": 3, "outputs": 2},
            "source_sha256": hashlib.sha256(b"frozen-source").hexdigest(),
            "data_manifest_sha256": hashlib.sha256(b"frozen-data").hexdigest(),
        }
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "complete.pt"

            def validate(target):
                observed = torch.load(target, map_location="cpu", weights_only=True)
                return same(observed, frozen)

            proof = publish_checkpoint(
                path, lambda handle: torch.save(frozen, handle), validate,
            )
            self.assertGreater(proof["bytes"], 1000)
            self.assertEqual(verify_checkpoint(path, proof, validate), proof)
            with self.assertRaises(EvidenceError):
                verify_checkpoint(
                    path, {**proof, "sha256": "0" * 64}, validate,
                )
            with self.assertRaises(EvidenceError):
                verify_checkpoint(path, proof, lambda target: False)


if __name__ == "__main__":
    unittest.main()
