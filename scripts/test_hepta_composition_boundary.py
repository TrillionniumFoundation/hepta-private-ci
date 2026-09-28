from __future__ import annotations

import ast
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

    def test_generic_runtime_does_not_construct_automation_storage_or_adapter(
        self,
    ) -> None:
        runtime = (ROOT / "codex-rs/hepta-agentd/src/runtime.rs").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("AutomationStore", runtime)
        self.assertNotIn("AgentdAutomationQueue", runtime)
        self.assertIn("AutomationService::open", runtime)
        factory = (ROOT / "codex-rs/hepta-agentd/src/automation_factory.rs").read_text(
            encoding="utf-8"
        )
        self.assertIn("AutomationStore::open", factory)
        self.assertIn("spawn_with_queue", factory)
        # Behavioral replacement is covered by the native factory/owner tests.

    def test_app_server_source_uses_only_bridge_namespace(self) -> None:
        concrete: list[str] = []
        source = ROOT / "codex-rs/app-server/src"
        for path in source.rglob("*.rs"):
            text = path.read_text(encoding="utf-8")
            for crate in re.findall(r"\b(codex_hepta_[a-z0-9_]+)::", text):
                if crate != "codex_hepta_app_bridge":
                    concrete.append(f"{path.relative_to(ROOT)}:{crate}")
        self.assertEqual(concrete, [])


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
        observed = 0
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
                self.assertEqual(enabled, product)
                self.assertNotIn("qualification-legacy-learning-write", enabled)
            else:
                if call.func.id in {"rust_library", "rust_binary"}:
                    self.assertIn("testonly", fields)
                    self.assertTrue(ast.literal_eval(fields["testonly"]))
                self.assertEqual(enabled, qualification)
            observed += 1
        self.assertEqual(observed, 5)


if __name__ == "__main__":
    unittest.main()
