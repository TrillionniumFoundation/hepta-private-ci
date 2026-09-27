from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("hepta_architecture_graph.py")
SPEC = importlib.util.spec_from_file_location("hepta_architecture_graph", SCRIPT)
assert SPEC and SPEC.loader
architecture = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(architecture)


def package(name: str, dependencies: list[tuple[str, str | None]]) -> dict:
    short = name.removeprefix("codex-hepta-")
    return {
        "name": name,
        "manifest_path": f"/repo/codex-rs/hepta-{short}/Cargo.toml",
        "dependencies": [
            {"name": dependency, "kind": kind}
            for dependency, kind in dependencies
        ],
    }


def matrix_row(name: str, module: str, layer: int) -> dict:
    short = name.removeprefix("codex-hepta-")
    return {
        "packagePath": f"codex-rs/hepta-{short}",
        "packageName": name,
        "module": module,
        "compileLayer": layer,
        "ciGroups": ["lifecycle"],
    }
def documents(
    packages: list[dict],
    modules: list[tuple[str, list[str]]],
) -> tuple[dict, dict, dict]:
    metadata = {"packages": packages}
    matrix = {
        "schema": "hepta.module-ci-matrix.v1",
        "packages": [],
    }
    module_rows = []
    for module, uses in modules:
        module_rows.append({"id": module, "uses": uses})
    return metadata, matrix, {
        "schema": "hepta.module-registry.v7",
        "modules": module_rows,
    }


class ArchitectureGraphTests(unittest.TestCase):
    def test_production_flows_down_and_dev_reverse_is_separate(self) -> None:
        metadata, matrix, modules = documents(
            [
                package("codex-hepta-high", [("codex-hepta-low", None)]),
                package("codex-hepta-low", [("codex-hepta-high", "dev")]),
            ],
            [("high.module", ["low.module"]), ("low.module", [])],
        )
        matrix["packages"] = [
            matrix_row("codex-hepta-high", "high.module", 1),
            matrix_row("codex-hepta-low", "low.module", 0),
        ]
        report = architecture.build_report(metadata, matrix, modules)
        self.assertEqual(report["status"], "aligned")
        self.assertEqual(len(report["productionPackageEdges"]), 1)
        self.assertEqual(len(report["developmentPackageEdges"]), 1)
        self.assertEqual(report["physicalOnlyModuleEdges"], [])
        self.assertEqual(report["logicalOnlyModuleEdges"], [])
    def test_reverse_production_edge_is_a_gate_failure(self) -> None:
        metadata, matrix, modules = documents(
            [
                package("codex-hepta-low", [("codex-hepta-high", None)]),
                package("codex-hepta-high", []),
            ],
            [("low.module", []), ("high.module", [])],
        )
        matrix["packages"] = [
            matrix_row("codex-hepta-low", "low.module", 0),
            matrix_row("codex-hepta-high", "high.module", 1),
        ]
        report = architecture.build_report(metadata, matrix, modules)
        self.assertEqual(report["status"], "architecture_violation")
        self.assertEqual(len(report["violations"]["layerDirection"]), 1)
        self.assertEqual(
            report["violations"]["layerDirection"][0]["fromPackage"],
            "codex-hepta-low",
        )

    def test_production_cycles_are_reported_at_package_and_module_level(self) -> None:
        metadata, matrix, modules = documents(
            [
                package("codex-hepta-a", [("codex-hepta-b", None)]),
                package("codex-hepta-b", [("codex-hepta-a", None)]),
            ],
            [("a.module", ["b.module"]), ("b.module", ["a.module"])],
        )
        matrix["packages"] = [
            matrix_row("codex-hepta-a", "a.module", 2),
            matrix_row("codex-hepta-b", "b.module", 1),
        ]
        report = architecture.build_report(metadata, matrix, modules)
        self.assertEqual(
            report["violations"]["productionPackageCycles"],
            [["codex-hepta-a", "codex-hepta-b"]],
        )
        self.assertEqual(
            report["violations"]["productionModuleCycles"],
            [["a.module", "b.module"]],
        )
    def test_app_server_and_agentd_product_boundaries_are_enforced(self) -> None:
        metadata, matrix, modules = documents(
            [
                {
                    "name": "codex-app-server",
                    "manifest_path": "/repo/codex-rs/app-server/Cargo.toml",
                    "dependencies": [
                        {"name": "codex-hepta-app-bridge", "kind": None},
                        {"name": "codex-hepta-low", "kind": None},
                    ],
                },
                package("codex-hepta-app-bridge", []),
                package("codex-hepta-app-host", [
                    ("codex-hepta-app-bridge", None),
                    ("codex-app-server", None),
                ]),
                {
                    "name": "codex-hepta-agentd",
                    "manifest_path": "/repo/codex-rs/hepta-agentd/Cargo.toml",
                    "dependencies": [
                        {"name": "codex-app-server", "kind": None},
                        {"name": "codex-hepta-app-host", "kind": None},
                    ],
                },
                package("codex-hepta-low", []),
            ],
            [
                ("runtime.codex", []),
                ("runtime.agentd", ["runtime.codex"]),
                ("low.module", []),
            ],
        )
        matrix["packages"] = [
            matrix_row("codex-hepta-app-bridge", "runtime.codex", 0),
            matrix_row("codex-hepta-app-host", "runtime.codex", 2),
            {
                "packagePath": "codex-rs/hepta-agentd",
                "packageName": "codex-hepta-agentd",
                "module": "runtime.agentd",
                "compileLayer": 3,
                "ciGroups": ["lifecycle"],
            },
            matrix_row("codex-hepta-low", "low.module", 0),
        ]
        report = architecture.build_report(metadata, matrix, modules)
        rules = {row["rule"] for row in report["violations"]["hostBoundaries"]}
        self.assertIn("app_server_may_depend_only_on_hepta_app_bridge", rules)
        self.assertIn("agentd_must_use_hepta_app_host_not_app_server_implementation", rules)
        self.assertEqual(report["status"], "architecture_violation")

    def test_logical_and_physical_dependencies_remain_distinct(self) -> None:
        metadata, matrix, modules = documents(
            [
                package("codex-hepta-a", [("codex-hepta-b", None)]),
                package("codex-hepta-b", []),
                package("codex-hepta-c", []),
            ],
            [("a.module", ["c.module"]), ("b.module", []), ("c.module", [])],
        )
        matrix["packages"] = [
            matrix_row("codex-hepta-a", "a.module", 1),
            matrix_row("codex-hepta-b", "b.module", 0),
            matrix_row("codex-hepta-c", "c.module", 0),
        ]
        report = architecture.build_report(metadata, matrix, modules)
        self.assertEqual(
            report["physicalOnlyModuleEdges"],
            [{"fromModule": "a.module", "toModule": "b.module"}],
        )
        self.assertEqual(
            report["logicalOnlyModuleEdges"],
            [{"fromModule": "a.module", "toModule": "c.module"}],
        )


if __name__ == "__main__":
    unittest.main()
