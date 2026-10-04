"""Execute crate macros with recording rules to check generated target wiring.

This follows the binary-feature graph recorder used by other repository branches.
It evaluates the actual Python-compatible macro functions, not Bazel analysis or
Rust compilation. Rule names must be unique, as they are in a Bazel package.
"""

import ast
import copy
import fnmatch
from pathlib import Path
from types import SimpleNamespace
import unittest


ROOT = Path(__file__).resolve().parents[2]


class MacroRecorder:
    def __init__(self, binaries, files, *, package="codex-rs/probe"):
        self.files = files
        self.package = package
        self.targets = {}
        self.wine_binaries = None
        module = ast.parse((ROOT / "defs.bzl").read_text(encoding="utf-8"))
        module.body = [
            node
            for node in module.body
            if isinstance(node, ast.FunctionDef)
            and node.name in {"codex_rust_crate", "_test_shard_count"}
        ]
        self.scope = {
            "native": self,
            "DEP_DATA": {package: {"binaries": binaries}},
            "all_crate_deps": lambda **kwargs: ["//deps:normal"],
            "WINDOWS_RUSTC_LINK_FLAGS": [],
            "WINDOWS_GNULLVM_RUSTC_LINK_FLAGS": [],
            "WINDOWS_GNULLVM_INCOMPATIBLE": [],
            "WINDOWS_GNULLVM_ONLY": [],
            "WINE_TEST_TARGET_COMPATIBLE_WITH": [],
            "wine_test_runtime": self.wine_runtime,
            "select": lambda choices: choices["//conditions:default"],
            "Label": lambda label: SimpleNamespace(name=label.rsplit(":", 1)[-1]),
        }
        for kind in (
            "rust_library",
            "rust_binary",
            "rust_test",
            "rust_proc_macro",
            "workspace_root_test",
            "cargo_build_script",
            "foreign_platform_binary",
        ):
            self.scope[kind] = self.rule(kind)
        exec(compile(module, str(ROOT / "defs.bzl"), "exec"), self.scope)

    def rule(self, kind):
        def record(**kwargs):
            name = kwargs["name"]
            if name in self.targets:
                raise AssertionError(f"duplicate target: {name}")
            self.targets[name] = {"kind": kind, **copy.deepcopy(kwargs)}

        return record

    def filegroup(self, **kwargs):
        self.rule("filegroup")(**kwargs)

    def package_name(self):
        return self.package

    def glob(self, patterns, *, exclude=(), allow_empty=False):
        del allow_empty

        def matches(path, pattern):
            return fnmatch.fnmatchcase(path, pattern) or fnmatch.fnmatchcase(
                path, pattern.replace("**/", "")
            )

        return sorted(
            path
            for path in self.files
            if any(matches(path, pattern) for pattern in patterns)
            and not any(matches(path, pattern) for pattern in exclude)
        )

    def wine_runtime(self, binaries):
        self.wine_binaries = binaries
        return SimpleNamespace(data=list(binaries.values()), runfile_env={})

    def generate(self, *, name="probe", crate_name="probe", **kwargs):
        self.scope["codex_rust_crate"](name=name, crate_name=crate_name, **kwargs)
        return self.targets

    def execute_build(self, build_file):
        scope = {**self.scope, "load": lambda *args: None, "glob": self.glob}
        exec(
            compile(build_file.read_text(encoding="utf-8"), str(build_file), "exec"),
            scope,
        )
        return self.targets


class BinaryTargetNameTests(unittest.TestCase):
    def test_library_only_keeps_its_public_label(self):
        targets = MacroRecorder({}, ["src/lib.rs"]).generate()
        self.assertEqual(
            {name: target["kind"] for name, target in targets.items()},
            {
                "package-files": "filegroup",
                "probe": "rust_library",
                "probe-unit-tests-bin": "rust_test",
                "probe-unit-tests": "workspace_root_test",
            },
        )
        self.assertEqual(targets["probe-unit-tests-bin"]["crate"], "probe")

    def test_binary_only_keeps_its_original_label_and_cargo_name(self):
        targets = MacroRecorder({"probe": "src/main.rs"}, ["src/main.rs"]).generate()
        self.assertEqual(
            {name: target["kind"] for name, target in targets.items()},
            {
                "package-files": "filegroup",
                "probe": "rust_binary",
                "probe-bin-unit-tests-bin": "rust_test",
                "probe-bin-unit-tests": "workspace_root_test",
            },
        )
        self.assertEqual(targets["probe"]["rustc_env"]["CARGO_BIN_NAME"], "probe")
        self.assertEqual(targets["probe-bin-unit-tests-bin"]["crate"], ":probe")
        self.assertNotIn("probe-bin", targets)
        self.assertNotIn("probe", targets["probe"]["deps"])

    def test_different_binary_name_keeps_its_original_label(self):
        targets = MacroRecorder(
            {"tool": "src/main.rs"}, ["src/lib.rs", "src/main.rs"]
        ).generate()
        self.assertEqual(targets["probe"]["kind"], "rust_library")
        self.assertEqual(targets["tool"]["kind"], "rust_binary")
        self.assertEqual(targets["tool-bin-unit-tests-bin"]["crate"], ":tool")
        self.assertEqual(targets["tool"]["deps"], ["//deps:normal", "probe"])

    def test_same_name_binary_keeps_cargo_identity_and_per_binary_inputs(self):
        targets = MacroRecorder(
            {"probe": "src/bin/probe.rs"}, ["src/lib.rs", "src/bin/probe.rs"]
        ).generate(
            binary_compile_data_extra={"probe": ["binary.data"]},
            binary_rustc_flags_extra={"probe": ["--cfg=binary_setting"]},
        )
        self.assertEqual(targets["probe"]["kind"], "rust_library")
        binary = targets["probe-bin"]
        self.assertEqual(
            {
                key: binary[key]
                for key in (
                    "kind",
                    "crate_name",
                    "crate_root",
                    "deps",
                    "compile_data",
                    "rustc_flags",
                )
            },
            {
                "kind": "rust_binary",
                "crate_name": "probe",
                "crate_root": "src/bin/probe.rs",
                "deps": ["//deps:normal", "probe"],
                "compile_data": ["binary.data"],
                "rustc_flags": ["--cfg=binary_setting"],
            },
        )
        self.assertEqual(binary["rustc_env"]["CARGO_BIN_NAME"], "probe")
        self.assertEqual(targets["probe-bin-unit-tests-bin"]["crate"], ":probe-bin")
        self.assertEqual(targets["probe"]["srcs"], ["src/lib.rs"])

    def test_integration_consumers_follow_the_renamed_binary(self):
        for sharded in (False, True):
            with self.subTest(sharded=sharded):
                recorder = MacroRecorder(
                    {"probe": "src/bin/probe.rs", "other": "src/bin/other.rs"},
                    [
                        "src/lib.rs",
                        "src/bin/probe.rs",
                        "src/bin/other.rs",
                        "tests/use_binary.rs",
                    ],
                )
                targets = recorder.generate(
                    test_shard_counts={"probe-use_binary-test": 2} if sharded else {},
                    run_tests_with_wine_exec=True,
                )
                env = {
                    "CARGO_BIN_EXE_probe": "$(rlocationpath :probe-bin)",
                    "CARGO_BIN_EXE_other": "$(rlocationpath :other)",
                }
                runfiles = {
                    ":probe-bin": "CARGO_BIN_EXE_probe",
                    ":other": "CARGO_BIN_EXE_other",
                }
                native = (
                    "probe-use_binary-test-bin" if sharded else "probe-use_binary-test"
                )
                for name in (native, "probe-use_binary-test-windows-cross-bin"):
                    self.assertEqual(
                        targets[name]["data"],
                        ["tests/use_binary.rs", "probe-bin", "other"],
                    )
                    for label in targets[name]["data"][1:]:
                        self.assertEqual(targets[label]["kind"], "rust_binary")
                self.assertEqual(
                    targets["probe-use_binary-test-windows-cross-bin"]["env"], env
                )
                self.assertEqual(
                    targets["probe-use_binary-test-windows-cross"]["runfile_env"],
                    runfiles,
                )
                if sharded:
                    self.assertEqual(
                        targets["probe-use_binary-test"]["runfile_env"], runfiles
                    )
                else:
                    self.assertEqual(targets["probe-use_binary-test"]["env"], env)
                self.assertEqual(recorder.wine_binaries["probe"], ":probe-bin")
                self.assertEqual(recorder.wine_binaries["other"], ":other")
                self.assertNotIn("CARGO_BIN_EXE_probe-bin", env)

    def test_actual_gateway_build_excludes_the_binary_from_library_sources(self):
        package = "codex-rs/hepta-native-gateway"
        root = ROOT / package
        binaries = {
            path.stem: path.relative_to(root).as_posix()
            for path in (root / "src/bin").glob("*.rs")
        }
        self.assertIn("hepta-native-gateway", binaries)
        files = [
            path.relative_to(root).as_posix()
            for path in root.rglob("*")
            if path.is_file()
        ]
        targets = MacroRecorder(binaries, files, package=package).execute_build(
            root / "BUILD.bazel"
        )
        library = targets["hepta-native-gateway"]
        binary = targets["hepta-native-gateway-bin"]
        self.assertEqual(library["kind"], "rust_library")
        self.assertEqual(binary["kind"], "rust_binary")
        self.assertEqual(binary["deps"], ["//deps:normal", "hepta-native-gateway"])
        self.assertEqual(binary["crate_name"], "hepta_native_gateway")
        self.assertEqual(binary["rustc_env"]["CARGO_BIN_NAME"], "hepta-native-gateway")
        self.assertEqual(
            targets["hepta-native-gateway-bin-unit-tests-bin"]["crate"],
            ":hepta-native-gateway-bin",
        )
        self.assertNotIn("src/bin/hepta-native-gateway.rs", library["srcs"])
        self.assertIn("src/bin/hepta-native-gateway.rs", binary["srcs"])

    def test_actual_external_binary_consumer_preserves_cargo_lookup(self):
        package = "codex-rs/rmcp-client"
        root = ROOT / package
        binaries = {
            path.stem: path.relative_to(root).as_posix()
            for path in (root / "src/bin").glob("*.rs")
        }
        files = [
            path.relative_to(root).as_posix()
            for path in root.rglob("*")
            if path.is_file()
        ]
        targets = MacroRecorder(binaries, files, package=package).execute_build(
            root / "BUILD.bazel"
        )
        consumers = [
            target
            for target in targets.values()
            if target["kind"] == "rust_test"
            and target.get("crate_root", "").startswith("tests/")
        ]
        self.assertTrue(consumers)
        for target in consumers:
            self.assertIn("//codex-rs/cli:codex", target["data"])
            self.assertEqual(
                target["env"]["CARGO_BIN_EXE_codex"],
                "$(rlocationpath //codex-rs/cli:codex)",
            )

    def test_recorder_rejects_duplicate_names_across_rule_kinds(self):
        recorder = MacroRecorder({}, [])
        recorder.rule("rust_library")(name="duplicate")
        with self.assertRaisesRegex(AssertionError, "duplicate target: duplicate"):
            recorder.rule("rust_binary")(name="duplicate")


if __name__ == "__main__":
    unittest.main()
