"""Exercise generated binary feature graphs without starting a workspace build.

These tests evaluate the Python-compatible macro body with recording rule calls.
They check graph wiring, not Bazel analysis or native product qualification.
"""

import ast
import copy
from pathlib import Path
import unittest

try:
    import tomllib
except ModuleNotFoundError:  # Keep graph-only tests available on Python 3.10.
    tomllib = None


ROOT = Path(__file__).resolve().parents[2]


class MacroRecorder:
    def __init__(self, binaries, *, library=True, build_script=False):
        self.binaries = binaries
        self.library = library
        self.build_script = build_script
        self.targets = {}
        module = ast.parse((ROOT / "defs.bzl").read_text(encoding="utf-8"))
        module.body = [
            node
            for node in module.body
            if isinstance(node, ast.FunctionDef)
            and node.name in {"codex_rust_crate", "_test_shard_count"}
        ]
        self.scope = {
            "native": self,
            "DEP_DATA": {"codex-rs/probe": {"binaries": binaries}},
            "all_crate_deps": self.dependencies,
            "rust_test_dependencies": self.test_dependencies,
            "WINDOWS_RUSTC_LINK_FLAGS": [],
            "WINDOWS_GNULLVM_INCOMPATIBLE": [],
            "WINDOWS_GNULLVM_ONLY": [],
            "fail": self.fail,
        }
        for kind in (
            "rust_library",
            "rust_binary",
            "rust_test",
            "rust_proc_macro",
            "workspace_root_test",
            "cargo_build_script",
        ):
            self.scope[kind] = self.rule(kind)
        exec(compile(module, str(ROOT / "defs.bzl"), "exec"), self.scope)

    def rule(self, kind):
        def record(**kwargs):
            name = kwargs["name"]
            if name in self.targets:
                raise AssertionError(f"duplicate target: {name}")
            self.targets[name] = (kind, copy.deepcopy(kwargs))

        return record

    def filegroup(self, **kwargs):
        self.rule("filegroup")(**kwargs)

    def package_name(self):
        return "codex-rs/probe"

    def glob(self, patterns, *, exclude=(), allow_empty=False):
        del allow_empty
        files = []
        for pattern in patterns:
            if pattern == "src/**/*.rs":
                files.extend(
                    (["src/lib.rs"] if self.library else [])
                    + list(self.binaries.values())
                )
            elif pattern == "build.rs" and self.build_script:
                files.append("build.rs")
            elif pattern in {"tests/*.rs", "tests/**"}:
                files.append("tests/lifecycle.rs")
        return [path for path in files if path not in exclude]

    @staticmethod
    def dependencies(**kwargs):
        return ["//deps:build" if kwargs.get("build") else "//deps:normal"]

    @staticmethod
    def test_dependencies(replacements, **kwargs):
        del kwargs
        return [replacements.get("//deps:normal", "//deps:normal")]

    @staticmethod
    def fail(message):
        raise ValueError(message)

    def generate(self, **kwargs):
        self.scope["codex_rust_crate"](name="probe", crate_name="probe", **kwargs)
        return {name: attributes for name, (_, attributes) in self.targets.items()}


class BinaryFeatureGraphTests(unittest.TestCase):
    def test_group_replaces_only_its_own_library_and_keeps_shared_inputs(self):
        recorder = MacroRecorder(
            {"ordinary": "src/main.rs", "tool": "src/bin/tool.rs"}, build_script=True
        )
        targets = recorder.generate(
            crate_features=["base"],
            binary_feature_groups={
                "offline": {"binaries": ["tool"], "features": ["offline"]}
            },
            unit_test_features=["qualification"],
            unit_test_dependency_replacements={"//deps:normal": "//deps:test"},
            compile_data=["schema.json"],
            lib_data_extra=["runtime.json"],
            deps_extra=["//deps:extra"],
            rustc_env_files=["env.txt"],
        )
        variant = targets["probe-offline-lib"]
        self.assertEqual(
            variant,
            targets["probe"]
            | {
                "name": "probe-offline-lib",
                "crate_features": ["base", "offline"],
                "visibility": ["//visibility:private"],
            },
        )
        self.assertEqual(
            targets["ordinary"]["deps"],
            ["//deps:normal", "probe-build-script", "probe", "//deps:extra"],
        )
        self.assertEqual(
            targets["tool"]["deps"],
            [
                "//deps:normal",
                "probe-build-script",
                "probe-offline-lib",
                "//deps:extra",
            ],
        )
        self.assertEqual(targets["ordinary"]["crate_features"], ["base"])
        self.assertEqual(targets["tool"]["crate_features"], ["base", "offline"])
        self.assertEqual(
            targets["tool-bin-unit-tests-bin"]["crate_features"], ["base", "offline"]
        )
        self.assertEqual(targets["probe-unit-tests-bin"]["crate"], "probe-test-lib")
        self.assertEqual(
            targets["probe-lifecycle-test"]["deps"],
            ["//deps:test", "probe-build-script", "probe-test-lib", "//deps:extra"],
        )
        self.assertEqual(
            targets["probe-lifecycle-test"]["crate_features"], ["base", "qualification"]
        )

    def test_one_library_is_shared_by_grouped_binaries_including_name_collision(self):
        targets = MacroRecorder(
            {"probe": "src/main.rs", "tool": "src/bin/tool.rs"}
        ).generate(
            binary_feature_groups={
                "offline": {"binaries": ["probe", "tool"], "features": ["offline"]}
            },
        )
        self.assertEqual(targets["probe-bin"]["deps"], targets["tool"]["deps"])
        self.assertEqual(
            targets["probe-bin"]["deps"], ["//deps:normal", "probe-offline-lib"]
        )
        self.assertEqual(targets["probe-bin-unit-tests-bin"]["crate"], ":probe-bin")
        self.assertEqual(
            targets["probe-lifecycle-test"]["env"]["CARGO_BIN_EXE_probe"],
            "$(rlocationpath :probe-bin)",
        )
        self.assertEqual(
            [name for name in targets if name.endswith("offline-lib")],
            ["probe-offline-lib"],
        )

    def test_existing_binary_override_keeps_product_process_data(self):
        targets = MacroRecorder({"tool": "src/main.rs"}).generate(
            binary_feature_groups={
                "offline": {"binaries": ["tool"], "features": ["offline"]}
            },
            integration_binary_overrides={"tool": "//product:tool"},
        )
        self.assertIn("//product:tool", targets["probe-lifecycle-test"]["data"])
        self.assertNotIn(":tool", targets["probe-lifecycle-test"]["data"])
        self.assertEqual(
            targets["tool"]["deps"], ["//deps:normal", "probe-offline-lib"]
        )

    def test_invalid_group_membership_is_rejected(self):
        cases = [
            ({"a": {"binaries": ["missing"], "features": ["a"]}}, "unknown binary"),
            (
                {"a": {"binaries": ["tool", "tool"], "features": ["a"]}},
                "multiple feature groups",
            ),
            (
                {
                    "a": {"binaries": ["tool"], "features": ["a"]},
                    "b": {"binaries": ["tool"], "features": ["b"]},
                },
                "multiple feature groups",
            ),
            (
                {"a": {"binaries": [], "features": ["a"]}},
                "require binaries and features",
            ),
            (
                {"a": {"binaries": ["tool"], "features": []}},
                "require binaries and features",
            ),
        ]
        for groups, message in cases:
            with (
                self.subTest(groups=groups),
                self.assertRaisesRegex(ValueError, message),
            ):
                MacroRecorder({"tool": "src/main.rs"}).generate(
                    binary_feature_groups=groups
                )

    def test_binary_only_crates_keep_existing_behavior_without_groups(self):
        recorder = MacroRecorder({"tool": "src/main.rs"}, library=False)
        self.assertEqual(recorder.generate()["tool"]["deps"], ["//deps:normal"])
        with self.assertRaisesRegex(ValueError, "ordinary library"):
            MacroRecorder({"tool": "src/main.rs"}, library=False).generate(
                binary_feature_groups={"a": {"binaries": ["tool"], "features": ["a"]}},
            )

    @unittest.skipIf(tomllib is None, "Cargo feature closure requires Python 3.11+")
    def test_actual_supervisor_build_keeps_offline_features_out_of_ordinary_targets(
        self,
    ):
        package = ROOT / "codex-rs/hepta-supervisor"
        manifest = tomllib.loads((package / "Cargo.toml").read_text(encoding="utf-8"))
        binaries = {entry["name"]: entry["path"] for entry in manifest["bin"]}
        recorder = MacroRecorder(binaries)
        scope = recorder.scope | {
            "load": lambda *args: None,
            "exports_files": lambda *args, **kwargs: None,
        }
        exec(
            compile(
                (package / "BUILD.bazel").read_text(encoding="utf-8"),
                str(package / "BUILD.bazel"),
                "exec",
            ),
            scope,
        )
        targets = {name: attrs for name, (_, attrs) in recorder.targets.items()}
        offline = {
            entry["name"]
            for entry in manifest["bin"]
            if "offline-authority-tools" in entry.get("required-features", [])
        }
        closure = {"offline-authority-tools"}
        while True:
            expanded = closure | {
                feature for name in closure for feature in manifest["features"][name]
            }
            if expanded == closure:
                break
            closure = expanded
        for binary in binaries:
            with self.subTest(binary=binary):
                self.assertEqual(
                    set(targets[binary]["crate_features"]),
                    closure if binary in offline else set(),
                )
                self.assertEqual(
                    targets[binary]["deps"],
                    [
                        "//deps:normal",
                        "hepta-supervisor-offline-authority-tools-lib"
                        if binary in offline
                        else "hepta-supervisor",
                    ],
                )
        self.assertEqual(targets["hepta-supervisor"]["crate_features"], [])
        self.assertEqual(targets["hepta-supervisor-test-lib"]["crate_features"], [])


if __name__ == "__main__":
    unittest.main()
