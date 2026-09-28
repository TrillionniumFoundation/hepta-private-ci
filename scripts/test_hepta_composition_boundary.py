from __future__ import annotations

import re
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class HeptaCompositionBoundaryTests(unittest.TestCase):
    def test_app_server_depends_on_one_hepta_bridge(self) -> None:
        manifest = tomllib.loads(
            (ROOT / "codex-rs/app-server/Cargo.toml").read_text(encoding="utf-8")
        )
        hepta = {
            name for name in manifest["dependencies"] if name.startswith("codex-hepta-")
        }
        self.assertEqual(hepta, {"codex-hepta-app-bridge"})

    def test_agentd_depends_on_stable_composition_boundaries(self) -> None:
        manifest = tomllib.loads(
            (ROOT / "codex-rs/hepta-agentd/Cargo.toml").read_text(encoding="utf-8")
        )
        hepta = {
            name for name in manifest["dependencies"] if name.startswith("codex-hepta-")
        }
        self.assertEqual(
            hepta,
            {
                "codex-hepta-agent-protocol",
                "codex-hepta-agentd-core",
                "codex-hepta-agent-components",
                "codex-hepta-app-bridge",
                "codex-hepta-app-host",
            },
        )

    def test_agentd_product_source_does_not_import_concrete_domain_crates(self) -> None:
        allowed = {
            "codex_hepta_agent_components",
            "codex_hepta_agent_protocol",
            "codex_hepta_agentd_core",
            "codex_hepta_app_bridge",
            "codex_hepta_app_host",
            "codex_hepta_agentd",
        }
        concrete: list[str] = []
        source = ROOT / "codex-rs/hepta-agentd/src"
        for path in source.rglob("*.rs"):
            if path.name.endswith("_tests.rs") or path.name == "test_support.rs":
                continue
            text = path.read_text(encoding="utf-8")
            for crate in re.findall(r"\b(codex_hepta_[a-z0-9_]+)::", text):
                if crate not in allowed:
                    concrete.append(f"{path.relative_to(ROOT)}:{crate}")
        self.assertEqual(concrete, [])

    def test_app_server_source_uses_only_bridge_namespace(self) -> None:
        concrete: list[str] = []
        source = ROOT / "codex-rs/app-server/src"
        for path in source.rglob("*.rs"):
            text = path.read_text(encoding="utf-8")
            for crate in re.findall(r"\b(codex_hepta_[a-z0-9_]+)::", text):
                if crate != "codex_hepta_app_bridge":
                    concrete.append(f"{path.relative_to(ROOT)}:{crate}")
        self.assertEqual(concrete, [])


if __name__ == "__main__":
    unittest.main()
