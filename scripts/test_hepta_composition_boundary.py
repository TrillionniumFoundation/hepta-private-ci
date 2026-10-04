from __future__ import annotations

import ast
import runpy
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

    def test_client_profile_omits_server_dependencies_but_default_retains_them(self):
        manifest = tomllib.loads(
            (ROOT / "codex-rs/hepta-agentd/Cargo.toml").read_text()
        )
        # Cargo feature references also resolve dependencies declared for a
        # target. Keep every declaration of a shared alias; a non-optional
        # declaration must not disappear behind another target's optional one.
        dependencies = {}
        tables = [manifest["dependencies"]] + [
            target.get("dependencies", {})
            for target in manifest.get("target", {}).values()
        ]
        for table in tables:
            for name, row in table.items():
                dependencies.setdefault(name, []).append(row)

        def enabled(requested):
            active = {
                name
                for name, rows in dependencies.items()
                if any(
                    not isinstance(row, dict) or not row.get("optional", False)
                    for row in rows
                )
            }
            seen = set()
            pending = list(requested)
            while pending:
                name = pending.pop()
                if name in seen:
                    continue
                seen.add(name)
                if name.startswith("dep:"):
                    self.assertIn(name[4:], dependencies)
                    active.add(name[4:])
                elif "/" in name:
                    dependency = name.split("/", 1)[0]
                    if not dependency.endswith("?"):
                        active.add(dependency)
                elif name in manifest["features"]:
                    pending.extend(manifest["features"][name])
                else:
                    self.assertTrue(
                        all(row.get("optional") for row in dependencies[name])
                    )
                    active.add(name)
            return active

        client, product = enabled([]), enabled(["default"])
        for dependency in (
            "codex-hepta-agent-components",
            "codex-hepta-app-host",
            "codex-hepta-app-bridge",
            "codex-hepta-bao-adapter",
        ):
            self.assertNotIn(dependency, client)
            self.assertIn(dependency, product)
        self.assertIn("codex-hepta-agent-protocol", client)
        for binary in manifest["bin"]:
            self.assertIn("server", binary["required-features"])
        worker = tomllib.loads(
            (ROOT / "codex-rs/hepta-infer-worker-host/Cargo.toml").read_text()
        )
        self.assertIs(
            worker["dependencies"]["codex-hepta-agentd"]["default-features"], False
        )
        self.assertIn("codex-hepta-agentd", worker["dev-dependencies"])


class HeptaBuildProfileParityTests(unittest.TestCase):
    def test_generated_binaries_receive_the_library_feature_profile(self):
        # Exercise generated attributes rather than prescribing the expression
        # spelling. Explicit tool profiles may differ; ordinary binaries must
        # still inherit their library's complete feature list.
        recorder = runpy.run_path(
            ROOT / ".github/scripts/test_run_bazel_binary_features.py"
        )["MacroRecorder"]
        targets = recorder(
            {"app": "src/main.rs", "worker": "src/bin/worker.rs"}
        ).generate(crate_features=["server", "transport"])
        self.assertEqual(targets["probe"]["crate_features"], ["server", "transport"])
        for binary in ("app", "worker"):
            with self.subTest(binary=binary):
                self.assertEqual(
                    targets[binary]["crate_features"],
                    targets["probe"]["crate_features"],
                )
                self.assertEqual(
                    targets[binary + "-bin-unit-tests-bin"]["crate_features"],
                    targets["probe"]["crate_features"],
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
                if feature in result or "/" in feature or feature.startswith("dep:"):
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
