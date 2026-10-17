"""Diagnostic only: simulated model observations never count as physical evidence."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import hepta_neuron_physical_smoke as smoke
from hepta_neuron_model_trials import InvalidTrial


class PhysicalSmokePreflightTests(unittest.TestCase):
    def test_missing_or_unpinned_physical_artifacts_fail_before_inference(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            catalog = root / "catalog.json"
            catalog.write_text(json.dumps({"schema": "irrelevant"}))
            with self.assertRaisesRegex(InvalidTrial, "pinned SDK"):
                smoke.run_smoke(catalog, "laya", root / "missing", "garbage", "cpu")
            with self.assertRaisesRegex(InvalidTrial, "explicit device"):
                smoke.run_smoke(catalog, "laya", root / "missing", "a" * 64, "cuda")
            with self.assertRaisesRegex(InvalidTrial, "unknown locked model variant"):
                with patch.object(
                    smoke, "verify_catalog", side_effect=lambda c: {"variants": {}}
                ):
                    smoke.run_smoke(catalog, "laya", root / "missing", "a" * 64, "cpu")
            with self.assertRaisesRegex(InvalidTrial, "absolute directory"):
                with patch.object(
                    smoke,
                    "verify_catalog",
                    side_effect=lambda c: {"variants": {"laya": {"model_id": "test"}}},
                ):
                    smoke.run_smoke(catalog, "laya", Path("relative"), "a" * 64, "cpu")

    def test_mock_success_is_explicitly_diagnostic_never_production(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            catalog_path = root / "catalog.json"
            catalog_path.write_text("{}")
            catalog = {
                "repository": "test-repo",
                "revision": "a" * 40,
                "variants": {
                    "laya": {
                        "model_id": "convaiinnovations/laya",
                        "weights_sha256": "b" * 64,
                    }
                },
            }
            fake_package_dir = root / "laya"
            fake_package_dir.mkdir()
            (fake_package_dir / "__init__.py").write_text("# dummy")
            # No torch/model objects are imported or executed in this fixture.
            from types import SimpleNamespace

            with (
                patch.object(smoke, "verify_catalog", return_value=catalog),
                patch.object(
                    smoke,
                    "inspect_local",
                    return_value={
                        "local_weight_bytes_verified": True,
                        "artifact_tree_sha256": "c" * 64,
                    },
                ),
                patch.object(smoke, "sha_tree", return_value="d" * 64),
                patch.object(
                    smoke,
                    "run_laya",
                    return_value=(
                        421000000,
                        "b" * 64,
                        [
                            {
                                "id": "synthetic-no-label-control-1",
                                "probabilities": [0.7, 0.3],
                            }
                        ],
                        {},
                    ),
                ),
                patch.dict(
                    sys.modules,
                    {
                        "laya": SimpleNamespace(
                            __file__=str(fake_package_dir / "__init__.py")
                        )
                    },
                ),
            ):
                report = smoke.run_smoke(
                    catalog_path, "laya", root / "model", "d" * 64, "cpu"
                )
            self.assertFalse(report["actual_hepta_data_used"])
            self.assertFalse(report["target_host_independently_attested"])
            self.assertFalse(report["ndu_selection_authorized"])
            self.assertFalse(report["promotion_authorized"])
            self.assertEqual(report["weights_sha256"], "b" * 64)


class WorkflowOfflineIsolationTests(unittest.TestCase):
    def test_all_physical_model_workflows_require_offline_forward(self):
        for workflow in (
            "hepta-neuron-physical-smoke.yml",
            "hepta-neuron-matched-cpu.yml",
        ):
            with self.subTest(workflow=workflow):
                content = (ROOT / ".github" / "workflows" / workflow).read_text(
                    encoding="utf-8"
                )
                self.assertNotIn("${1}", content)
                for variable, expected in (
                    ("HF_HUB_DISABLE_TELEMETRY", "1"),
                    ("HF_HUB_OFFLINE", "1"),
                    ("TRANSFORMERS_OFFLINE", "1"),
                    ("USE_TF", "0"),
                ):
                    self.assertIn(f'{variable}: "{expected}"', content)
                    self.assertIn(
                        f'test "${variable}" = "{expected}"',
                        content,
                    )
                self.assertIn("--allow-network", content)
                self.assertIn("if: always()", content)


if __name__ == "__main__":
    unittest.main()
