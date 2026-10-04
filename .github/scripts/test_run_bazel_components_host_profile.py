"""Platform contract regressions, not substitutes for native Cargo/Bazel builds."""

import ast
from pathlib import Path
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[2]
COMPONENTS = ROOT / "codex-rs/hepta-agent-components"


def bazel_profile(platform):
    """Evaluate only the literal macro attributes and platform selects we own."""
    tree = ast.parse((COMPONENTS / "BUILD.bazel").read_text())
    call = next(
        node.value
        for node in tree.body
        if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == "codex_rust_crate"
    )

    def value(node):
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id != "select":
                raise AssertionError("unexpected computed macro attribute")
            choices = ast.literal_eval(node.args[0])
            return choices.get(
                f"@platforms//os:{platform}", choices["//conditions:default"]
            )
        return ast.literal_eval(node)

    return {attribute.arg: value(attribute.value) for attribute in call.keywords}


class ComponentsHostProfileTest(unittest.TestCase):
    def test_linux_bazel_host_matches_cargo_optional_externs(self):
        profile = bazel_profile("linux")
        manifest = tomllib.loads((COMPONENTS / "Cargo.toml").read_text())
        self.assertEqual(profile["crate_features"], ["fixed-eval-host"])
        optional = {
            name.removeprefix("dep:")
            for name in manifest["features"]["fixed-eval-host"]
            if name.startswith("dep:")
        }
        self.assertEqual(optional, {"serde", "serde_json"})
        self.assertEqual(
            set(profile["deps_extra"]), {f"@crates//:{name}" for name in optional}
        )
        for name in optional:
            self.assertTrue(manifest["dependencies"][name]["optional"])

    def test_non_linux_keeps_ordinary_product_and_test_profile(self):
        linux = bazel_profile("linux")
        for platform in ("windows", "osx", "freebsd"):
            with self.subTest(platform=platform):
                profile = bazel_profile(platform)
                self.assertEqual(profile["crate_features"], [])
                self.assertEqual(profile.get("deps_extra", []), [])
                for key in ("unit_test_features", "unit_test_dependency_replacements"):
                    self.assertEqual(profile[key], linux[key])
                self.assertFalse(
                    any("exclude" in key or "compatible" in key for key in profile)
                )

    def test_wire_module_and_test_share_linux_feature_boundary(self):
        guard = (
            r'cfg\(all\(target_os\s*=\s*"linux",\s*feature\s*=\s*"fixed-eval-host"\)\)'
        )
        source = (COMPONENTS / "src/lib.rs").read_text()
        self.assertRegex(source, rf"#\[{guard}\]\s*pub mod frozen_generator_wire;")
        test = (COMPONENTS / "tests/frozen_generator_wire.rs").read_text()
        self.assertRegex(test, rf"^#!\[{guard}\]")
        # The composition facade remains available on every supported platform.
        self.assertRegex(
            source, r"pub mod intelligence\s*\{\s*pub use codex_hepta_intelligence::\*;"
        )

    def test_cargo_host_activation_reaches_explicit_ledger_review_host(self):
        manifests = {
            name: tomllib.loads((ROOT / f"codex-rs/{name}/Cargo.toml").read_text())
            for name in (
                "hepta-agent-components",
                "hepta-intelligence-eval",
                "hepta-learning-ledger",
            )
        }
        components = manifests["hepta-agent-components"]
        evaluation = manifests["hepta-intelligence-eval"]
        ledger = manifests["hepta-learning-ledger"]
        for manifest in manifests.values():
            self.assertEqual(manifest["features"]["default"], [])
        self.assertEqual(
            set(components["features"]["fixed-eval-host"]),
            {
                "codex-hepta-intelligence-eval/fixed-eval-host",
                "dep:serde",
                "dep:serde_json",
            },
        )
        self.assertIn(
            "codex-hepta-learning-ledger/review-host",
            evaluation["features"]["fixed-eval-host"],
        )
        self.assertIn("review-host", ledger["features"])
        wire_test = next(
            test
            for test in components["test"]
            if test["name"] == "frozen_generator_wire"
        )
        self.assertEqual(wire_test["required-features"], ["fixed-eval-host"])


if __name__ == "__main__":
    unittest.main()
