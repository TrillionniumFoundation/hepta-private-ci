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
            "type": lambda value: (
                "string" if isinstance(value, str) else type(value).__name__
            ),
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


class BinaryRequirementsTests(unittest.TestCase):
    def assert_binary_absent(self, targets, binary):
        self.assertNotIn(binary, targets)
        self.assertNotIn(binary + "-bin-unit-tests", targets)
        self.assertNotIn(binary + "-bin-unit-tests-bin", targets)
        for attributes in targets.values():
            for reference in (binary, ":" + binary):
                self.assertNotIn(reference, attributes.get("data", []))
            for field in ("env", "rustc_env"):
                self.assertNotIn("CARGO_BIN_EXE_" + binary, attributes.get(field, {}))
            self.assertNotIn(":" + binary, attributes.get("runfile_env", {}))

    def test_default_targets_omit_unavailable_signer_and_all_references(self):
        recorder = MacroRecorder(
            {"daemon": "src/main.rs", "signer": "src/bin/signer.rs"}
        )
        targets = recorder.generate(
            binary_required_features={"daemon": [], "signer": ["authority"]}
        )
        self.assert_binary_absent(targets, "signer")
        self.assertIn("daemon", targets)
        self.assertIn("daemon-bin-unit-tests", targets)
        self.assertIn("daemon", targets["probe-lifecycle-test"]["data"])
        self.assertEqual(targets["probe"]["crate_features"], [])

    def test_all_required_features_must_be_in_the_emitted_configuration(self):
        binaries = {"signer": "src/main.rs"}
        requirements = {"signer": ["first", "second"]}
        partial = MacroRecorder(binaries).generate(
            crate_features=["first"], binary_required_features=requirements
        )
        self.assert_binary_absent(partial, "signer")
        complete = MacroRecorder(binaries).generate(
            crate_features=["first", "second"], binary_required_features=requirements
        )
        self.assertEqual(complete["signer"]["crate_features"], ["first", "second"])
        self.assertEqual(
            complete["signer-bin-unit-tests-bin"]["crate_features"], ["first", "second"]
        )
        self.assertIn("signer", complete["probe-lifecycle-test"]["data"])

    def test_optional_metadata_preserves_existing_graph(self):
        binaries = {"ordinary": "src/main.rs"}
        self.assertEqual(
            MacroRecorder(binaries).generate(),
            MacroRecorder(binaries).generate(binary_required_features={"ordinary": []}),
        )

    def test_metadata_rejects_incomplete_or_invalid_binary_declarations(self):
        for requirements in (
            {},
            {"signer": [], "unknown": []},
            {"other": []},
            [],
            {"signer": "authority"},
            {"signer": [""]},
            {"signer": [1]},
        ):
            with (
                self.subTest(requirements=requirements),
                self.assertRaisesRegex(ValueError, "binary_required_features"),
            ):
                MacroRecorder({"signer": "src/main.rs"}).generate(
                    binary_required_features=requirements
                )

    @unittest.skipIf(tomllib is None, "Cargo target metadata requires Python 3.11+")
    def test_supervisor_targets_follow_actual_cargo_manifest(self):
        package = ROOT / "codex-rs/hepta-supervisor"
        manifest = tomllib.loads((package / "Cargo.toml").read_text(encoding="utf-8"))
        binaries = {entry["name"]: entry["path"] for entry in manifest["bin"]}
        recorder = MacroRecorder(binaries)
        declarations = []

        def declare_crate(**kwargs):
            declarations.append(kwargs)
            return recorder.scope["codex_rust_crate"](**kwargs)

        scope = recorder.scope | {
            "load": lambda *args: None,
            "exports_files": lambda *args, **kwargs: None,
            "codex_rust_crate": declare_crate,
        }
        exec(
            compile(
                (package / "BUILD.bazel").read_text(encoding="utf-8"),
                str(package / "BUILD.bazel"),
                "exec",
            ),
            scope,
        )
        requirements = {
            entry["name"]: entry.get("required-features", [])
            for entry in manifest["bin"]
        }
        self.assertEqual(declarations[0]["binary_required_features"], requirements)
        targets = {name: attrs for name, (_, attrs) in recorder.targets.items()}
        for binary, required in requirements.items():
            with self.subTest(binary=binary):
                if required:
                    self.assert_binary_absent(targets, binary)
                else:
                    self.assertIn(binary, targets)


if __name__ == "__main__":
    unittest.main()
