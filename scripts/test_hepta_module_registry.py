"""Tests for the canonical module/Cargo registry drift check."""

import json
from pathlib import Path
import tempfile
import unittest

from hepta_module_registry import compare_registry

ROOT = Path(__file__).resolve().parents[1]


class ModuleRegistryTests(unittest.TestCase):
    def test_repository_drift_is_machine_readable(self):
        report = compare_registry(ROOT)
        self.assertEqual(report["schema"], "hepta.module-registry-drift.v1")
        self.assertEqual(report["canonicalModuleCount"], 40)
        self.assertEqual(report["cargoHeptaCrateCount"], 50)
        self.assertEqual(report["boundCrateCount"], 50)
        self.assertEqual(report["status"], "aligned")
        self.assertEqual(report["unclaimedCargoCrates"], [])

    def test_exact_root_binding_detects_added_and_ambiguous_packages(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "docs/modules").mkdir(parents=True)
            (root / "codex-rs/hepta-one/src").mkdir(parents=True)
            (root / "codex-rs/hepta-two/src").mkdir(parents=True)
            modules = {
                "modules": [
                    {"id": "demo.one", "rootBindings": [{"path": "codex-rs/hepta-one"}]},
                    {"id": "demo.two", "rootBindings": [{"path": "codex-rs/hepta-two"}]},
                ]
            }
            (root / "docs/modules/MODULES.json").write_text(json.dumps(modules), encoding="utf-8")
            for path, package in (
                ("codex-rs/hepta-one", "codex-hepta-one"),
                ("codex-rs/hepta-two", "codex-hepta-two"),
            ):
                (root / path / "Cargo.toml").write_text(
                    f"[package]\nname = \"{package}\"\nversion = \"0.1.0\"\n",
                    encoding="utf-8",
                )
            report = compare_registry(root)
            self.assertEqual(report["status"], "aligned")
            self.assertEqual(report["boundCrateCount"], 2)

            # Adding a package without a root binding is a drift, even when
            # the overall package count still looks plausible.
            (root / "codex-rs/hepta-three").mkdir()
            (root / "codex-rs/hepta-three/Cargo.toml").write_text(
                '[package]\nname = "codex-hepta-three"\nversion = "0.1.0"\n',
                encoding="utf-8",
            )
            report = compare_registry(root)
            self.assertEqual(report["status"], "drift")
            self.assertEqual(report["unclaimedCargoCrates"][0]["package"], "codex-hepta-three")

    def test_duplicate_root_binding_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "docs/modules").mkdir(parents=True)
            (root / "codex-rs/hepta-one").mkdir(parents=True)
            (root / "codex-rs/hepta-one/Cargo.toml").write_text(
                '[package]\nname = "codex-hepta-one"\nversion = "0.1.0"\n',
                encoding="utf-8",
            )
            (root / "docs/modules/MODULES.json").write_text(
                json.dumps(
                    {
                        "modules": [
                            {"id": "demo.one", "rootBindings": [{"path": "codex-rs/hepta-one"}]},
                            {"id": "demo.other", "rootBindings": [{"path": "codex-rs/hepta-one"}]},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            report = compare_registry(root)
            self.assertEqual(report["status"], "drift")
            self.assertEqual(report["ambiguousRootBindings"], [{"path": "codex-rs/hepta-one", "modules": ["demo.one", "demo.other"]}])

    def test_explicit_cargo_registry_rejects_empty_stale_and_unknown_bindings(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "docs/modules").mkdir(parents=True)
            (root / "codex-rs/hepta-one").mkdir(parents=True)
            (root / "codex-rs/hepta-one/Cargo.toml").write_text(
                '[package]\nname = "codex-hepta-one"\nversion = "0.1.0"\n',
                encoding="utf-8",
            )
            (root / "docs/modules/MODULES.json").write_text(
                json.dumps(
                    {"modules": [{"id": "demo.one", "rootBindings": [{"path": "codex-rs/hepta-one"}]}]}
                ),
                encoding="utf-8",
            )
            binding_path = root / "docs/modules/CARGO_BINDINGS.json"
            cases = [
                ([], "unclaimedCargoCrates", [{"package": "codex-hepta-one", "path": "codex-rs/hepta-one"}]),
                ([{"packagePath": "codex-rs/hepta-one", "module": "demo.missing"}], "unknownModules", ["demo.missing"]),
                (
                    [
                        {"packagePath": "codex-rs/hepta-one", "module": "demo.one"},
                        {"packagePath": "codex-rs/hepta-removed", "module": "demo.one"},
                    ],
                    "unregisteredBindings",
                    ["codex-rs/hepta-removed"],
                ),
            ]
            for bindings, field, expected in cases:
                with self.subTest(field=field):
                    binding_path.write_text(
                        json.dumps({"schema": "hepta.cargo-module-binding.v1", "bindings": bindings}),
                        encoding="utf-8",
                    )
                    report = compare_registry(root)
                    self.assertEqual(report["status"], "drift")
                    self.assertEqual(report[field], expected)


if __name__ == "__main__":
    unittest.main()
