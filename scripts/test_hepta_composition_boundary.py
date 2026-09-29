from __future__ import annotations

import ast
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def hepta_dependency_packages(manifest: dict) -> set[str]:
    """Resolve actual Cargo package identities, including renamed dependencies."""
    packages = set()
    for alias, specification in manifest.get("dependencies", {}).items():
        package = (
            specification.get("package", alias)
            if isinstance(specification, dict)
            else alias
        )
        if isinstance(package, str) and package.startswith("codex-hepta-"):
            packages.add(package)
    return packages


class HeptaCompositionBoundaryTests(unittest.TestCase):
    def test_app_server_depends_on_one_hepta_bridge(self) -> None:
        manifest = tomllib.loads(
            (ROOT / "codex-rs/app-server/Cargo.toml").read_text(encoding="utf-8")
        )
        self.assertEqual(
            hepta_dependency_packages(manifest), {"codex-hepta-app-bridge"}
        )

    def test_agentd_depends_on_stable_composition_boundaries(self) -> None:
        manifest = tomllib.loads(
            (ROOT / "codex-rs/hepta-agentd/Cargo.toml").read_text(encoding="utf-8")
        )
        self.assertEqual(
            hepta_dependency_packages(manifest),
            {
                "codex-hepta-agent-protocol",
                "codex-hepta-agentd-core",
                "codex-hepta-agent-components",
                "codex-hepta-app-bridge",
                "codex-hepta-app-host",
            },
        )


class HeptaBuildProfileParityTests(unittest.TestCase):
    def test_generated_binaries_receive_the_library_feature_profile(self):
        tree = ast.parse((ROOT / "defs.bzl").read_text())
        factory = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "codex_rust_crate"
        )
        calls = [
            node
            for node in ast.walk(factory)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "rust_binary"
        ]
        self.assertTrue(calls)
        for call in calls:
            fields = {value.arg: value.value for value in call.keywords}
            self.assertIn("crate_features", fields)
            self.assertEqual(
                ast.dump(fields["crate_features"]),
                ast.dump(ast.Name(id="crate_features", ctx=ast.Load())),
            )

    def test_agentd_bazel_profiles_expand_their_actual_cargo_features(self):
        manifest = tomllib.loads(
            (ROOT / "codex-rs/hepta-agentd/Cargo.toml").read_text()
        )
        features = manifest["features"]

        def expand(names):
            result = set()
            pending = list(names)
            while pending:
                feature = pending.pop()
                if feature in result or "/" in feature:
                    continue
                self.assertIn(feature, features)
                result.add(feature)
                pending.extend(features[feature])
            result.discard("default")
            return result

        product = expand(["default"])
        qualification = expand(["qualification-cognitive-write"])
        tree = ast.parse((ROOT / "codex-rs/hepta-agentd/BUILD.bazel").read_text())
        product_targets = []
        qualification_targets = []
        for statement in tree.body:
            if not isinstance(statement, ast.Expr) or not isinstance(
                statement.value, ast.Call
            ):
                continue
            call = statement.value
            if not isinstance(call.func, ast.Name) or call.func.id not in {
                "codex_rust_crate",
                "rust_library",
                "rust_binary",
                "rust_test",
            }:
                continue
            fields = {value.arg: value.value for value in call.keywords}
            name = ast.literal_eval(fields["name"])
            enabled = (
                set(ast.literal_eval(fields["crate_features"]))
                if "crate_features" in fields
                else set()
            )
            if name == "hepta-agentd":
                product_targets.append(name)
                self.assertEqual(enabled, product)
                self.assertNotIn("qualification-legacy-learning-write", enabled)
            else:
                qualification_targets.append(name)
                if call.func.id in {"rust_library", "rust_binary"}:
                    self.assertIn("testonly", fields)
                    self.assertTrue(ast.literal_eval(fields["testonly"]))
                self.assertEqual(enabled, qualification)
        self.assertEqual(product_targets, ["hepta-agentd"])
        self.assertTrue(qualification_targets)
        self.assertEqual(len(qualification_targets), len(set(qualification_targets)))


if __name__ == "__main__":
    unittest.main()
