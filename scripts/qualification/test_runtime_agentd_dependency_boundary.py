from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from scripts.qualification.runtime_agentd_dependency_boundary import verify


class RuntimeAgentdDependencyBoundaryTests(unittest.TestCase):
    def fixture(self) -> Path:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        crate = root / "codex-rs/hepta-agentd"
        crate.mkdir(parents=True)
        (crate / "Cargo.toml").write_text(
            """[package]
name = "codex-hepta-agentd"
version = "0.0.0"

[features]
default = []
production-cognitive-write = []
qualification-cognitive-write = ["production-cognitive-write"]

[dependencies]
codex-hepta-types = "1"
serde = "1"
codex-app-server = "1"
codex-hepta-intelligence = "1"
codex-hepta-neuron = "1"
codex-hepta-prompt-registry = "1"
codex-hepta-memory = "1"
codex-hepta-plasticity = "1"

[dev-dependencies]
tempfile = "1"
""",
            encoding="utf-8",
        )
        boundary = {
            "schema": "hepta.runtime-agentd-dependency-boundary.v1",
            "module": "runtime.agentd",
            "status": {
                "defaultFeatureReadOnly": True,
                "coreOnlyBuildEstablished": False,
                "productAdaptersOptionalized": False,
            },
            "categories": {
                "core_runtime": ["codex-hepta-types"],
                "platform_support": ["serde"],
                "product_adapters": [
                    "codex-app-server",
                    "codex-hepta-intelligence",
                    "codex-hepta-memory",
                    "codex-hepta-neuron",
                    "codex-hepta-plasticity",
                    "codex-hepta-prompt-registry",
                ],
                "development_only": ["tempfile"],
            },
            "migration": {"targetFeature": "product-adapters"},
        }
        (crate / "DEPENDENCY_BOUNDARY.json").write_text(
            json.dumps(boundary, indent=2) + "\n", encoding="utf-8"
        )
        return root

    def test_exact_inventory_and_nonclaiming_status_pass(self) -> None:
        result = verify(self.fixture())
        self.assertEqual(result["normalDependencies"], 8)
        self.assertFalse(result["coreOnlyBuildEstablished"])

    def test_unclassified_dependency_fails(self) -> None:
        root = self.fixture()
        cargo = root / "codex-rs/hepta-agentd/Cargo.toml"
        cargo.write_text(cargo.read_text() + "unclassified = \"1\"\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "inventory drift"):
            verify(root)

    def test_product_adapter_cannot_be_relabelled_core(self) -> None:
        root = self.fixture()
        path = root / "codex-rs/hepta-agentd/DEPENDENCY_BOUNDARY.json"
        boundary = json.loads(path.read_text())
        boundary["categories"]["product_adapters"].remove("codex-app-server")
        boundary["categories"]["core_runtime"].append("codex-app-server")
        boundary["categories"]["core_runtime"].sort()
        path.write_text(json.dumps(boundary, indent=2) + "\n")
        with self.assertRaisesRegex(ValueError, "relabelled as core"):
            verify(root)

    def test_default_writer_capability_fails(self) -> None:
        root = self.fixture()
        cargo = root / "codex-rs/hepta-agentd/Cargo.toml"
        cargo.write_text(
            cargo.read_text().replace("default = []", "default = [\"production-cognitive-write\"]"),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "default feature set"):
            verify(root)

    def test_optionalization_claim_requires_real_feature(self) -> None:
        root = self.fixture()
        path = root / "codex-rs/hepta-agentd/DEPENDENCY_BOUNDARY.json"
        boundary = json.loads(path.read_text())
        boundary["status"]["productAdaptersOptionalized"] = True
        path.write_text(json.dumps(boundary, indent=2) + "\n")
        with self.assertRaisesRegex(ValueError, "optionalization status"):
            verify(root)


if __name__ == "__main__":
    unittest.main()
