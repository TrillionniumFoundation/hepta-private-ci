"""Small tensor integrity controls; these are NOT real tiny-sd qualification.

The fixture exercises checkpoint state and rejection only. No generated image,
semantic score, new dataset, trained provider or confirmatory fit is claimed.
"""

import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

try:
    import torch
    from safetensors.torch import load_file, save_file
except ImportError as error:
    raise unittest.SkipTest("tensor integrity controls require torch and safetensors") from error

from . import sd_checkpoint as checkpoint
from . import sd_train


class TensorFixture(torch.nn.Module):
    """Parameter roster fixture, not a diffusion model or model replacement."""

    def __init__(self):
        super().__init__()
        self.frozen = torch.nn.Linear(2, 2)
        self.conv_out = torch.nn.Linear(2, 1)
        with torch.no_grad():
            self.frozen.weight.copy_(torch.tensor([[0.5, -0.25], [0.125, 0.75]]))
            self.frozen.bias.fill_(0.25)
            self.conv_out.weight.copy_(torch.tensor([[0.5, -0.5]]))
            self.conv_out.bias.fill_(0.125)

    def forward(self, value):
        return self.conv_out(self.frozen(value))


class SdCheckpointTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="hepta-sd-checkpoint-control-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.model = TensorFixture()
        self.before = checkpoint.inventory(self.model)
        parameters = checkpoint.freeze_for_training(self.model)
        self.optimizer = torch.optim.SGD(parameters, lr=0.01, momentum=0.9)
        self.rng = torch.Generator(device="cpu").manual_seed(17)
        self.base_sha = "a" * 64
        self.metadata = {"base_manifest_sha256": self.base_sha,
                         "optimizer": {"kind": "SGD", "learning_rate": 0.01,
                                       "momentum": 0.9, "completed_steps": 2},
                         "scope": "unit-integrity-fixture-only"}
        for _ in range(2):
            self.step(self.model, self.optimizer, self.rng)

    @staticmethod
    def step(model, optimizer, rng):
        inputs = torch.randn((3, 2), generator=rng)
        targets = torch.randn((3, 1), generator=rng)
        optimizer.zero_grad(set_to_none=True)
        torch.nn.functional.mse_loss(model(inputs), targets).backward()
        optimizer.step()

    def save(self, name="candidate"):
        path = self.root / name
        digest = checkpoint.save_candidate(path, self.model, self.optimizer,
                                           self.rng, self.before, self.metadata)
        return path, digest

    @staticmethod
    def rewrite_manifest(path, mutate):
        manifest = json.loads((path / "CHECKPOINT.json").read_bytes())
        mutate(manifest)
        (path / "CHECKPOINT.json").write_bytes(checkpoint.canonical(manifest) + b"\n")
        return checkpoint.file_sha(path / "CHECKPOINT.json")

    def assert_rejected_without_mutation(self, path, digest, *, model=None, base=None):
        model = model or TensorFixture()
        before = checkpoint.inventory(model)
        with self.assertRaises((ValueError, FileNotFoundError)):
            checkpoint.restore_candidate(path, model, base or self.base_sha, digest)
        self.assertEqual(checkpoint.inventory(model), before)

    def test_only_allowed_parameters_get_gradients_and_updates(self):
        after = checkpoint.inventory(self.model)
        changed = sorted(name for name in self.before if self.before[name] != after[name])
        self.assertEqual(changed, list(checkpoint.TRAINABLE))
        with_gradient = sorted(name for name, value in self.model.named_parameters()
                               if value.grad is not None)
        self.assertEqual(with_gradient, list(checkpoint.TRAINABLE))

    def test_restored_parameter_momentum_and_rng_continue_exactly(self):
        path, digest = self.save()
        restored = TensorFixture()
        manifest, state, restored_rng = checkpoint.restore_candidate(
            path, restored, self.base_sha, digest)
        parameters = checkpoint.freeze_for_training(restored)
        config = manifest["metadata"]["optimizer"]
        restored_optimizer = torch.optim.SGD(parameters, lr=config["learning_rate"],
                                              momentum=config["momentum"])
        named = dict(restored.named_parameters())
        for name in checkpoint.TRAINABLE:
            restored_optimizer.state[named[name]]["momentum_buffer"] = state[name].clone()
        self.assertEqual(checkpoint.inventory(restored), checkpoint.inventory(self.model))
        self.assertTrue(torch.equal(restored_rng.get_state(), self.rng.get_state()))
        # The next real SGD operation consumes the restored RNG and momentum.
        self.step(self.model, self.optimizer, self.rng)
        self.step(restored, restored_optimizer, restored_rng)
        self.assertEqual(checkpoint.inventory(restored), checkpoint.inventory(self.model))
        self.assertTrue(torch.equal(restored_rng.get_state(), self.rng.get_state()))
        original = dict(self.model.named_parameters())
        for name in checkpoint.TRAINABLE:
            self.assertTrue(torch.equal(
                self.optimizer.state[original[name]]["momentum_buffer"],
                restored_optimizer.state[named[name]]["momentum_buffer"]))

    def test_wrong_external_digest_and_base_manifest_are_rejected(self):
        path, digest = self.save()
        self.assert_rejected_without_mutation(path, "0" * 64)
        self.assert_rejected_without_mutation(path, digest, base="b" * 64)

    def test_loaded_base_tensor_change_is_rejected(self):
        path, digest = self.save()
        wrong = TensorFixture()
        with torch.no_grad():
            wrong.frozen.bias[0] += 0.125
        self.assert_rejected_without_mutation(path, digest, model=wrong)

    def test_manifest_byte_tampering_is_rejected(self):
        path, digest = self.save()
        self.rewrite_manifest(path, lambda m: m.update(production_promotion_permitted=True))
        self.assert_rejected_without_mutation(path, digest)

    def test_delta_and_optimizer_byte_tampering_is_rejected(self):
        for name in ("delta.safetensors", "optimizer.safetensors"):
            with self.subTest(file=name):
                path, digest = self.save(name)
                data = bytearray((path / name).read_bytes())
                data[-1] ^= 1
                (path / name).write_bytes(data)
                self.assert_rejected_without_mutation(path, digest)

    def test_shape_mismatch_with_consistent_file_hash_is_rejected(self):
        path, _ = self.save()
        tensors = load_file(str(path / "delta.safetensors"))
        tensors["conv_out.weight"] = torch.ones((1, 3))
        save_file(tensors, str(path / "delta.safetensors"))
        def update(manifest):
            manifest["files"]["delta.safetensors"] = {
                "sha256": checkpoint.file_sha(path / "delta.safetensors"),
                "bytes": (path / "delta.safetensors").stat().st_size}
        digest = self.rewrite_manifest(path, update)
        self.assert_rejected_without_mutation(path, digest)

    def test_frozen_after_record_mismatch_does_not_partially_mutate_model(self):
        path, _ = self.save()
        def update(manifest):
            manifest["after"]["frozen.weight"]["sha256"] = "f" * 64
        digest = self.rewrite_manifest(path, update)
        self.assert_rejected_without_mutation(path, digest)

    def test_frozen_parameter_change_prevents_checkpoint_publication(self):
        with torch.no_grad():
            self.model.frozen.bias[0] += 0.125
        with self.assertRaisesRegex(ValueError, "frozen tensor"):
            self.save()
        self.assertFalse((self.root / "candidate/CHECKPOINT.json").exists())

    def test_nonfinite_candidate_and_momentum_cannot_be_published(self):
        for name in ("candidate", "momentum"):
            with self.subTest(state=name):
                parameters = dict(self.model.named_parameters())
                target = (parameters["conv_out.bias"] if name == "candidate" else
                          self.optimizer.state[parameters["conv_out.bias"]]["momentum_buffer"])
                old = target.detach().clone()
                with torch.no_grad():
                    target.fill_(float("nan"))
                with self.assertRaisesRegex(ValueError, "nonfinite"):
                    self.save(name)
                self.assertFalse((self.root / name / "CHECKPOINT.json").exists())
                with torch.no_grad():
                    target.copy_(old)

    def test_incomplete_checkpoint_is_retained_and_not_loadable(self):
        # Failure after delta publication must retain the bytes without a commit manifest.
        with patch("safetensors.torch.save_file", wraps=save_file) as writer:
            count = 0
            def write_then_fail(*args, **kwargs):
                nonlocal count
                count += 1
                if count == 2:
                    raise OSError("injected storage failure")
                return save_file(*args, **kwargs)
            writer.side_effect = write_then_fail
            with self.assertRaisesRegex(OSError, "injected storage failure"):
                self.save()
        path = self.root / "candidate"
        self.assertTrue((path / "delta.safetensors").is_file())
        self.assertFalse((path / "CHECKPOINT.json").exists())
        self.assert_rejected_without_mutation(path, "0" * 64)

    def test_replay_requires_successful_bound_fit_receipt_before_model_load(self):
        path, digest = self.save()
        base = {"status": "completed", "mode": "fit",
                "result": {"checkpoint_sha256": digest}}
        for field, value in (("status", "failed"), ("mode", "replay"),
                             ("result", {"checkpoint_sha256": "0" * 64})):
            with self.subTest(field=field):
                receipt = copy.deepcopy(base)
                receipt[field] = value
                (self.root / "RESULT.json").write_bytes(checkpoint.canonical(receipt))
                with patch.object(sd_train, "load_pipeline") as loader:
                    with self.assertRaisesRegex(ValueError, "completed bound fit receipt"):
                        sd_train.replay("unused", path, digest, self.root, False,
                                        checkpoint.file_sha(self.root / "RESULT.json"))
                    loader.assert_not_called()
        (self.root / "RESULT.json").write_bytes(checkpoint.canonical(base))
        with self.assertRaisesRegex(ValueError, "terminal receipt identity mismatch"):
            sd_train.replay("unused", path, digest, self.root, False, "0" * 64)

    def test_nonfinite_model_prediction_is_rejected(self):
        batch = {"noisy": None, "timestep": None, "embeddings": None}
        for value in (float("nan"), float("inf")):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "nonfinite real UNet prediction"):
                    sd_train.predict(lambda *args, **kwargs: SimpleNamespace(
                        sample=torch.tensor([value])), batch)


if __name__ == "__main__":
    unittest.main()
