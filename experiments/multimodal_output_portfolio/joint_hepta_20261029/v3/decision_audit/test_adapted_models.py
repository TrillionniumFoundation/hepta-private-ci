"""Lifecycle fixtures only; no pretrained forward or efficacy evidence."""

from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image

from .adapted_models import AdaptedLocalModels
from .dual_runtime import FixedSchedule, Request, digest_file, run
from .local_models import LocalModels


class AdaptedModelTests(unittest.TestCase):
    def setUp(self):
        self.models, self.fail = [], None
        def activate(backend, key):
            if backend.active == key:
                return
            model = SimpleNamespace(hooks=[])
            self.models.append((key, model)); backend.active = key
            backend.model = model if key == "vlm" else None
            backend.pipeline = SimpleNamespace(unet=model) if key == "sd" else None
        def load(model, path, sha):
            if self.fail:
                raise self.fail
            handle = SimpleNamespace(remove=lambda: model.hooks.remove(handle))
            model.hooks.append(handle)
            return object(), handle
        modules = {__package__ + ".train_adapter": SimpleNamespace(load_adapter=load),
                   __package__ + ".train_image_adapter": SimpleNamespace(load_image_adapter=load)}
        for patcher in (patch.object(LocalModels, "_activate", activate),
                        patch.object(LocalModels, "identity", return_value={"backend": "fixture"}),
                        patch.dict(sys.modules, modules)):
            patcher.start(); self.addCleanup(patcher.stop)
        self.backend = AdaptedLocalModels("vlm", "sd", {
            key: {"path": key + ".safetensors", "sha256": "a" * 64} for key in ("vlm", "sd")})

    def test_switches_reinstall_and_same_family_never_stacks_hooks(self):
        for key in ("vlm", "vlm", "sd", "sd", "vlm"):
            self.backend._activate(key)
            self.assertEqual(len(self.models[-1][1].hooks), 1)
        self.assertEqual([key for key, _ in self.models], ["vlm", "sd", "vlm"])
        self.assertEqual([len(model.hooks) for _, model in self.models], [0, 0, 1])
        identity = self.backend.identity()
        self.assertEqual(identity["active_adapter"], "vlm")
        self.assertEqual([r["status"] for r in identity["adapter_activations"]], ["verified"] * 3)
        self.assertTrue(identity["base_parameters_frozen"])
        self.assertEqual(identity["generator_adaptation"], "external_learned_output_parameters")

    def test_failure_discards_old_model_and_retry_installs_exactly_one_hook(self):
        self.backend._activate("vlm")
        self.fail = ValueError("checkpoint rejected")
        with self.assertRaisesRegex(ValueError, "checkpoint rejected"):
            self.backend._activate("sd")
        self.assertEqual(self.models[0][1].hooks, [])
        self.assertIsNone(self.backend.active)
        self.assertIsNone(self.backend.pipeline)
        self.fail = None
        self.backend._activate("sd"); self.backend._activate("sd")
        self.assertEqual([key for key, _ in self.models], ["vlm", "sd", "sd"])
        self.assertEqual([r["status"] for r in self.backend.adapter_activations], ["verified", "failed", "verified"])
        self.assertEqual(len(self.models[-1][1].hooks), 1)

    def test_runtime_retains_adapter_failure_and_spend(self):
        with tempfile.TemporaryDirectory(dir="/dev/shm" if Path("/dev/shm").is_dir() else None) as folder:
            root = Path(folder); source = root / "source.png"
            Image.new("RGB", (8, 8), "yellow").save(source)
            request = Request("fixture", str(source), digest_file(source), "Explain the picture.")
            self.fail = TimeoutError("adapter validation expired")
            with patch.object(self.backend, "describe", side_effect=lambda *a: self.backend._activate("vlm")):
                report = run(request, self.backend, FixedSchedule(("perceive",)), root / "episode")
            self.assertEqual((report["status"], report["selected"]), ("timeout", []))
            self.assertEqual(report["events"][-2]["status"], "timeout")
            self.assertGreater(report["wall_seconds"], 0)
            self.assertTrue((root / "episode" / "report.json").is_file())


if __name__ == "__main__":
    unittest.main()
