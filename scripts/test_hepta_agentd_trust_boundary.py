from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

MODULE_PATH = Path(__file__).with_name("hepta_agentd_trust_boundary.py")
SPEC = importlib.util.spec_from_file_location("hepta_agentd_trust_boundary", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class AgentdTrustBoundaryTests(unittest.TestCase):
    def test_repository_boundary_is_current(self) -> None:
        self.assertEqual(MODULE.validate(), [])

    def test_test_modules_are_not_production_authority_edges(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "owner.rs").write_text("fn owner() {}\n", encoding="utf-8")
            (root / "owner_tests.rs").write_text(
                "fn test_only() { start_revalidated_run_start(); }\n",
                encoding="utf-8",
            )
            nested = root / "tests"
            nested.mkdir()
            (nested / "product.rs").write_text(
                "fn test_only() { authentication_is_current(); }\n",
                encoding="utf-8",
            )
            self.assertEqual(
                [path.name for path in MODULE.rust_sources(root)],
                ["owner.rs"],
            )

    def test_production_locations_remain_visible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "unexpected.rs"
            source.write_text(
                "fn bypass() { start_current_run_start_record(); }\n",
                encoding="utf-8",
            )
            self.assertEqual(
                MODULE.token_locations(
                    "start_current_run_start_record(",
                    MODULE.rust_sources(root),
                    root,
                ),
                [("unexpected.rs", 1)],
            )


if __name__ == "__main__":
    unittest.main()
