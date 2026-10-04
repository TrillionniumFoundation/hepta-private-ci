"""Execute the shared target factory with captured rules to check Cargo parity."""

from __future__ import annotations

import ast
import tomllib
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]


def feature_closure(manifest, requested):
    pending = list(requested)
    result = set()
    while pending:
        feature = pending.pop()
        if feature in result or "/" in feature or feature.startswith("dep:"):
            continue
        result.add(feature)
        pending.extend(manifest["features"][feature])
    return result


def capture_build(package, *, definitions=None):
    manifest = tomllib.loads((ROOT / package / "Cargo.toml").read_text())
    binaries = {row["name"]: row["path"] for row in manifest.get("bin", [])}
    calls = []

    def capture(kind):
        return lambda **kwargs: calls.append((kind, kwargs))

    def glob(patterns, exclude=(), **_kwargs):
        if patterns == ["src/**/*.rs"]:
            return [
                path
                for path in ["src/lib.rs", *binaries.values()]
                if path not in exclude
            ]
        return []

    def fail(message):
        raise ValueError(message)

    env = {
        "load": lambda *_args: None,
        "struct": SimpleNamespace,
        "glob": glob,
        "all_crate_deps": lambda **_kwargs: ["@crates//:ordinary-dependency"],
        "rust_test_dependencies": lambda replacements, **_kwargs: list(
            replacements.values()
        ),
        "native": SimpleNamespace(
            package_name=lambda: package, glob=glob, filegroup=capture("filegroup")
        ),
        "DEP_DATA": {package: {"binaries": binaries}},
        "WINDOWS_RUSTC_LINK_FLAGS": [],
        "WINDOWS_GNULLVM_INCOMPATIBLE": [],
        "select": lambda branches: branches["//conditions:default"],
        "fail": fail,
    }
    for kind in (
        "rust_library",
        "rust_binary",
        "rust_test",
        "rust_proc_macro",
        "workspace_root_test",
        "exports_files",
    ):
        env[kind] = capture(kind)
    # Execute the actual factory, rather than reimplementing target generation.
    tree = ast.parse(definitions or (ROOT / "defs.bzl").read_text())
    functions = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name in ("codex_rust_crate", "_test_shard_count")
    ]
    exec(compile(ast.Module(body=functions, type_ignores=[]), "defs.bzl", "exec"), env)
    env["exports_files"] = lambda *_args, **_kwargs: None
    exec(
        compile((ROOT / package / "BUILD.bazel").read_text(), "BUILD.bazel", "exec"),
        env,
    )
    return manifest, {row["name"]: (kind, row) for kind, row in calls}


class ToolProfileTests(unittest.TestCase):
    def test_offline_tools_use_cargo_feature_matched_isolated_libraries(self):
        manifest, targets = capture_build("codex-rs/hepta-supervisor")
        for binary in manifest["bin"]:
            name = binary["name"]
            target = targets[name][1]
            required = binary.get("required-features", [])
            # Model issuer dependency identity needs a separate validated repair.
            if required and "offline-authority-tools" not in required:
                continue
            expected = feature_closure(manifest, required)
            self.assertEqual(set(target["crate_features"]), expected, name)
            helper = targets[name + "-bin-unit-tests-bin"][1]
            self.assertEqual(set(helper["crate_features"]), expected, name)
            if required:
                self.assertNotIn("hepta-supervisor", target["deps"], name)
                isolated = [
                    dep
                    for dep in target["deps"]
                    if dep.startswith(":hepta-supervisor-")
                ]
                self.assertEqual(len(isolated), 1, name)
                library = targets[isolated[0][1:]][1]
                self.assertEqual(set(library["crate_features"]), expected, name)
                self.assertEqual(library["visibility"], ["//visibility:private"])
            else:
                self.assertIn("hepta-supervisor", target["deps"], name)
                self.assertFalse(
                    any(
                        dep.endswith("-tool-lib") or dep.endswith("-tools-lib")
                        for dep in target["deps"]
                    )
                )
        self.assertEqual(targets["hepta-supervisor"][1]["crate_features"], [])
        self.assertFalse(
            any(
                "tool-lib" in dep or "tools-lib" in dep
                for dep in targets["hepta-supervisor"][1]["deps"]
            )
        )


if __name__ == "__main__":
    unittest.main()
