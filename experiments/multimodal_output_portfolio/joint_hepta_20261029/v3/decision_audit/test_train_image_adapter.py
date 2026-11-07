"""Behavior fixtures with small real tensors; never pretrained-model evidence."""

import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import torch
from torch import nn
from diffusers import DDPMScheduler

from . import train_image_adapter as trainer


class TinyUNet(nn.Module):
    def __init__(self, fail_on_call=None):
        super().__init__()
        self.conv_out = nn.Conv2d(4, 4, 3, padding=1, dtype=torch.bfloat16)
        self.calls, self.fail_on_call = 0, fail_on_call
        self.requires_grad_(False)

    def forward(self, sample, timestep, encoder_hidden_states):
        self.calls += 1
        if self.calls == self.fail_on_call:
            raise RuntimeError("injected forward failure")
        return SimpleNamespace(sample=self.conv_out(sample + encoder_hidden_states.mean()))


class ImageAdapterTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "input.bin").write_bytes(b"explicit unit fixture, not a training photo")
        self.manifest = self.root / "training.json"
        self.data = {"schema": "hepta.real-image-adapter-training-data.v1", "role": "training_only",
                     "examples": [{"source_id": "unit-fixture", "image_path": "input.bin",
                                   "image_sha256": trainer.digest_file(self.root/"input.bin"),
                                   "prompt": "a unit fixture", "target_provenance": "small tensor fixture only"}]}
        self.manifest.write_text(json.dumps(self.data))

    def run_fixture(self, *, fail_on_call=None, output_name="result", **kwargs):
        model = TinyUNet(fail_on_call)
        pipe = SimpleNamespace(unet=model, vae=nn.Linear(1, 1).requires_grad_(False),
                               text_encoder=nn.Linear(1, 1).requires_grad_(False), scheduler=DDPMScheduler())
        backend = SimpleNamespace(pipeline=pipe, _activate=lambda key: None,
                                  identity=lambda: {"test_fixture": True, "pretrained_evidence": False})
        with patch.object(trainer, "LocalModels", return_value=backend), patch.object(
                trainer, "prepare_pair", return_value=(torch.ones(1, 4, 4, 4, dtype=torch.bfloat16),
                                                       torch.ones(1, 2, 4, dtype=torch.bfloat16), {"test_fixture": True})):
            return trainer.train("unused", self.manifest, self.root/output_name, "a"*40,
                                 trainer.digest_file(self.manifest), steps=2, **kwargs)

    def test_bfloat16_identity_update_and_frozen_base(self):
        model = TinyUNet(); before = trainer.parameter_hashes(model)
        sample = torch.randn(1, 4, 4, 4, dtype=torch.bfloat16)
        plain = model.conv_out(sample).detach()
        adapter = trainer.ImageOutputAdapter(4, 4)
        handle = adapter.attach(model); self.addCleanup(handle.remove)
        self.assertTrue(torch.equal(plain, model.conv_out(sample)))
        with self.assertRaises(ValueError):
            adapter.attach(model)
        optimizer = torch.optim.SGD(adapter.parameters(), lr=1)
        model.conv_out(sample).float().square().mean().backward(); optimizer.step()
        changed = model.conv_out(sample)
        self.assertEqual(changed.dtype, torch.bfloat16)
        self.assertGreater(float(adapter.up.weight.detach().abs().sum()), 0)
        self.assertTrue(bool(torch.isfinite(adapter.up.weight.grad).all()))
        self.assertEqual(before, trainer.parameter_hashes(model))
        self.assertTrue(all(p.grad is None for p in model.parameters()))

    def test_safe_reload_preserves_output_and_checks_identity(self):
        model = TinyUNet(); adapter = trainer.ImageOutputAdapter(4, 4)
        with torch.no_grad():
            adapter.up.weight.fill_(0.2)
        handle = adapter.attach(model)
        sample = torch.ones(1, 4, 4, 4, dtype=torch.bfloat16)
        expected = model.conv_out(sample).detach(); handle.remove()
        path = self.root/"image.safetensors"
        sha = trainer.save_image_adapter(adapter, path, trainer.fingerprint(trainer.parameter_hashes(model)), {})
        loaded, handle = trainer.load_image_adapter(model, path, sha); self.addCleanup(handle.remove)
        self.assertTrue(torch.equal(expected, model.conv_out(sample)))
        self.assertTrue(all(not p.requires_grad for p in loaded.parameters()))
        with self.assertRaises(ValueError):
            trainer.load_image_adapter(model, path, "0"*64)
        with self.assertRaises(ValueError):
            trainer.load_image_adapter(TinyUNet(), path, sha)

    def test_prediction_targets_use_scheduler_convention(self):
        scheduler = DDPMScheduler()
        latent, noise, timestep = torch.ones(1, 4, 2, 2), torch.zeros(1, 4, 2, 2), torch.tensor([4])
        self.assertTrue(torch.equal(trainer.denoising_target(scheduler, latent, noise, timestep), noise))
        scheduler.register_to_config(prediction_type="v_prediction")
        self.assertTrue(torch.equal(trainer.denoising_target(scheduler, latent, noise, timestep),
                                    scheduler.get_velocity(latent, noise, timestep)))
        scheduler.register_to_config(prediction_type="sample")
        self.assertTrue(torch.equal(trainer.denoising_target(scheduler, latent, noise, timestep), latent))
        scheduler.register_to_config(prediction_type="unrecognized")
        with self.assertRaises(ValueError):
            trainer.denoising_target(scheduler, latent, noise, timestep)

    def test_clip_overflow_is_rejected_before_image_encoding(self):
        tokenizer = Mock(return_value={"input_ids": list(range(78))}); tokenizer.model_max_length = 77
        pipe = SimpleNamespace(tokenizer=tokenizer, text_encoder=SimpleNamespace(config=SimpleNamespace(max_position_embeddings=77)))
        row = trainer.read_example(self.manifest, trainer.digest_file(self.manifest))
        with self.assertRaisesRegex(ValueError, "truncation is forbidden"):
            trainer.prepare_pair(pipe, row, torch.Generator())

    def test_actual_tensor_updates_reload_and_full_base_immutability(self):
        result = self.run_fixture()
        self.assertEqual((result["status"], result["completed_updates"], result["actual_unet_forward_completed"]),
                         ("completed", 2, 5))
        self.assertEqual(result["base_parameter_hashes_before"], result["base_parameter_hashes_after"])
        self.assertGreater(result["adapter_changed_parameter_values"], 0)
        self.assertTrue(result["checkpoint_qualified"] and result["reload_probe"]["equal"])
        self.assertTrue(all(u["finite_gradient"] for u in result["updates"]))
        self.assertEqual(result["observed_training_source_count"], 1)
        self.assertFalse(result["four_arm_efficacy_established"])

    def test_failure_keeps_completed_updates_and_cost_receipt(self):
        result = self.run_fixture(fail_on_call=2)
        self.assertEqual((result["status"], result["completed_updates"], result["actual_unet_forward_attempts"]),
                         ("failed", 1, 2))
        self.assertIsNone(result["checkpoint"])
        self.assertFalse(result["checkpoint_qualified"])
        receipt = json.loads((self.root/"result/cost_receipt.json").read_text())
        self.assertGreater(receipt["cpu_seconds"], 0)
        self.assertIn("training_failure", [e["kind"] for e in receipt["events"]])

    def test_final_write_budget_overrun_cannot_complete(self):
        clock, original = [0.0], trainer.write_json
        def delayed_write(path, value):
            original(path, value)
            if path.name == "cost_receipt.json":
                clock[0] = 20.0
        with patch.object(trainer.time, "process_time", side_effect=lambda: clock[0]), patch.object(
                trainer.time, "perf_counter", side_effect=lambda: clock[0]), patch.object(trainer, "write_json", side_effect=delayed_write):
            result = self.run_fixture(cpu_budget=10, wall_budget=10)
        persisted = json.loads((self.root/"result/report.json").read_text())
        self.assertEqual((result["status"], persisted["status"], persisted["checkpoint_qualified"]), ("timeout", "timeout", False))
        self.assertTrue(persisted["checkpoint"]["reload_verified"])

    def test_final_parameter_hash_failure_still_writes_receipts(self):
        original, count = trainer.parameter_hashes, [0]
        def failing_hash(module):
            if isinstance(module, trainer.ImageOutputAdapter):
                count[0] += 1
                if count[0] == 4:
                    raise RuntimeError("injected final adapter hash failure")
            return original(module)
        with patch.object(trainer, "parameter_hashes", side_effect=failing_hash):
            result = self.run_fixture()
        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["checkpoint_qualified"])
        self.assertTrue((self.root/"result/image_adapter.safetensors").is_file())
        self.assertTrue((self.root/"result/cost_receipt.json").is_file())

    def test_rejected_nonfinite_requests_preserve_strict_json_receipts(self):
        for name, value in (("learning_rate", float("nan")), ("cpu_budget", float("nan")),
                            ("wall_budget", float("inf"))):
            with self.subTest(parameter=name):
                result = self.run_fixture(output_name=name, **{name: value})
                persisted = json.loads((self.root/name/"report.json").read_text())
                self.assertEqual((result["status"], persisted["status"], result["actual_unet_forward_attempts"]),
                                 ("failed", "failed", 0))
                self.assertEqual(persisted["request_configuration"][name], repr(value))
                self.assertFalse(persisted["checkpoint_qualified"])
                self.assertTrue((self.root/name/"cost_receipt.json").is_file())


if __name__ == "__main__":
    unittest.main()
