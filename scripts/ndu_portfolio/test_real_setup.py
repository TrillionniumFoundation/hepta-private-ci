"""Common startup and failure receipts with explicit model-free fixture backends."""

import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from .real_setup import warm_backend
from .real_execution import _sha


BACKEND = (
    "experiments.multimodal_output_portfolio.joint_hepta_20261029.v3."
    "decision_audit.local_models.LocalModels"
)


class SetupContracts(unittest.TestCase):
    def scenario(self, output, device="cpu"):
        plan = {
            "source_sha": "a" * 40,
            "allowed_actions": ["perceive", "text", "stop"],
            "profile": {
                "device": device,
                "dtype": "float16" if device == "cuda:0" else "float32",
                "threads": 2,
                "cpu_tariff": 1.0,
                "wall_tariff": 0.5,
            },
        }
        args = SimpleNamespace(
            models=str(output / "models"),
            output=str(output),
            device_smoke=None,
            device_smoke_sha256=None,
        )
        return plan, args

    def test_common_setup_is_retained_before_returning_any_backend(self):
        with tempfile.TemporaryDirectory() as folder, patch(BACKEND) as factory:
            root = Path(folder)
            plan, args = self.scenario(root)
            backend = factory.return_value
            backend.identity.return_value = {
                "evidence_kind": "explicit_model_free_fixture"
            }
            backend._activate.side_effect = lambda key: self.assertFalse(
                (root / "SHARED_SETUP.json").exists()
            )
            returned = warm_backend(plan, args)
            self.assertIs(returned, backend)
            backend._activate.assert_called_once_with("vlm")
            backend.synchronize.assert_called_once_with()
            record = json.loads((root / "SHARED_SETUP.json").read_text())
            self.assertEqual(record["status"], "completed")
            self.assertTrue(record["charged_once_in_inclusive_phase_meter"])
            self.assertFalse(record["charged_to_first_policy_episode"])
            self.assertIsNone(record["deployment_amortization_frequency"])
            self.assertGreater(record["wall_seconds"], 0)

    def test_failed_model_load_retains_cost_and_does_not_supply_backend(self):
        with tempfile.TemporaryDirectory() as folder, patch(BACKEND) as factory:
            root = Path(folder)
            plan, args = self.scenario(root)
            factory.return_value._activate.side_effect = RuntimeError(
                "fixture weight mismatch"
            )
            with self.assertRaisesRegex(RuntimeError, "weight mismatch"):
                warm_backend(plan, args)
            record = json.loads((root / "SHARED_SETUP.json").read_text())
            self.assertEqual(record["status"], "failed")
            self.assertGreater(record["engineering_cost"], 0)
            factory.return_value.synchronize.assert_not_called()

    def test_cuda_smoke_from_different_profile_cannot_trigger_model_load(self):
        with tempfile.TemporaryDirectory() as folder, patch(BACKEND) as factory:
            root = Path(folder)
            plan, args = self.scenario(root, "cuda:0")
            actual = {
                "device": "cuda:0",
                "dtype": "float16",
                "reviewed_model_pins": {},
                "versions": {},
            }
            factory.return_value.identity.return_value = actual
            smoke = root / "SMOKE.json"
            smoke.write_text(
                json.dumps(
                    {
                        "status": "completed",
                        "gpu_execution_verified": True,
                        "source_sha": plan["source_sha"],
                        "backend": {**actual, "dtype": "float32"},
                    }
                )
            )
            args.device_smoke, args.device_smoke_sha256 = str(smoke), _sha(smoke)
            with self.assertRaisesRegex(ValueError, "exact runtime profile"):
                warm_backend(plan, args)
            factory.return_value._activate.assert_not_called()
            self.assertEqual(
                json.loads((root / "SHARED_SETUP.json").read_text())["status"], "failed"
            )


if __name__ == "__main__":
    unittest.main()
