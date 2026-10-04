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
            "hepta_product_test_binary",
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
    def assert_binary_absent(self, targets, binary):
        self.assertNotIn(binary, targets)
        self.assertNotIn(binary + "-bin-unit-tests", targets)
        self.assertNotIn(binary + "-bin-unit-tests-bin", targets)
        for attributes in targets.values():
            self.assertNotIn(":" + binary, attributes.get("data", []))
            for field in ("env", "rustc_env"):
                self.assertNotIn("CARGO_BIN_EXE_" + binary, attributes.get(field, {}))
            self.assertNotIn(":" + binary, attributes.get("runfile_env", {}))

    def test_unmet_required_features_omit_all_binary_references(self):
        recorder = MacroRecorder(
            {"ordinary": "src/main.rs", "tool": "src/bin/tool.rs"}
        )
        targets = recorder.generate(
            binary_required_features={"ordinary": [], "tool": ["optional"]}
        )
        self.assert_binary_absent(targets, "tool")
        self.assertIn("ordinary", targets)
        self.assertIn("ordinary-bin-unit-tests", targets)
        self.assertIn(":ordinary", targets["probe-lifecycle-test"]["data"])
        self.assertEqual(targets["probe"]["crate_features"], [])

    def test_satisfied_requirements_preserve_the_entire_existing_graph(self):
        binaries = {"ordinary": "src/main.rs", "tool": "src/bin/tool.rs"}
        options = {
            "binary_feature_groups": {
                "optional": {"binaries": ["tool"], "features": ["optional"]}
            }
        }
        before = MacroRecorder(binaries).generate(**options)
        after = MacroRecorder(binaries).generate(
            **options,
            binary_required_features={"ordinary": [], "tool": ["optional"]},
        )
        self.assertEqual(after, before)
        self.assertEqual(after["probe"]["crate_features"], [])

    def test_workspace_resolved_features_do_not_enable_binary_rust_cfg(self):
        recorder = MacroRecorder({"tool": "src/main.rs"})
        recorder.scope["DEP_DATA"]["codex-rs/probe"]["crate_features"] = ["optional"]
        targets = recorder.generate(binary_required_features={"tool": ["optional"]})
        self.assert_binary_absent(targets, "tool")
        self.assertEqual(targets["probe"]["crate_features"], [])

    def test_all_required_features_must_be_in_the_emitted_configuration(self):
        binaries = {"tool": "src/main.rs"}
        requirements = {"tool": ["first", "second"]}
        partial = MacroRecorder(binaries).generate(
            crate_features=["first"], binary_required_features=requirements
        )
        self.assert_binary_absent(partial, "tool")
        complete = MacroRecorder(binaries).generate(
            crate_features=["first", "second"], binary_required_features=requirements
        )
        self.assertEqual(complete["tool"]["crate_features"], ["first", "second"])

    def test_required_feature_metadata_rejects_missing_unknown_or_invalid_entries(self):
        for requirements in (
            {},
            {"tool": [], "unknown": []},
            {"other": []},
            [],
            {"tool": "optional"},
            {"tool": [""]},
            {"tool": [1]},
        ):
            with self.subTest(requirements=requirements), self.assertRaisesRegex(
                ValueError, "binary_required_features"
            ):
                MacroRecorder({"tool": "src/main.rs"}).generate(
                    binary_required_features=requirements
                )

    @unittest.skipIf(tomllib is None, "Cargo feature closure requires Python 3.11+")
    def test_actual_supervisor_never_emits_an_unavailable_manifest_binary(self):
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
        for entry in manifest["bin"]:
            name = entry["name"]
            if name not in targets:
                continue
            with self.subTest(binary=name):
                self.assertLessEqual(
                    set(entry.get("required-features", [])),
                    set(targets[name]["crate_features"]),
                )
        self.assertIn("hepta-fleetctl", targets)
        self.assertIn("hepta-supervisor-authority-bundle", targets)

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

    def test_owner_dependencies_preserve_shared_and_binary_graphs(self):
        options = dict(
            crate_features=["base"],
            unit_test_features=["qualification"],
            unit_test_dependency_replacements={"//deps:normal": "//deps:shared"},
            binary_feature_groups={
                "offline": {"binaries": ["tool"], "features": ["offline"]}
            },
            crate_aliases={"//deps:extra": "extra"},
            compile_data=["schema.json"],
            lib_data_extra=["runtime.json"],
            deps_extra=["//deps:extra"],
            rustc_flags_extra=["--cfg=probe"],
            rustc_env={"PROBE": "yes"},
            rustc_env_files=["env.txt"],
        )
        for shape in (
            {},
            {"test_shard_counts": {"probe-lifecycle-test": 2}},
            {"product_integration_tests": ["lifecycle"]},
        ):
            with self.subTest(shape=shape):

                def generate(**extra):
                    recorder = MacroRecorder(
                        {"ordinary": "src/main.rs", "tool": "src/bin/tool.rs"},
                        build_script=True,
                    )
                    recorder.scope["rust_test_dependencies"] = (
                        lambda replacements, **kwargs: [
                            replacements.get(dep, dep)
                            for dep in ("//deps:normal", "//deps:owner")
                        ]
                    )
                    return recorder.generate(**options, **shape, **extra)

                baseline = generate()
                self.assertEqual(
                    baseline, generate(owner_test_dependency_replacements={})
                )
                targets = generate(
                    owner_test_dependency_replacements={
                        "//deps:owner": "//deps:owner-test",
                    }
                )
                expected_deps = [
                    "//deps:shared",
                    "//deps:owner-test",
                    "probe-build-script",
                    "//deps:extra",
                ]
                self.assertEqual(
                    targets["probe-owner-test-lib"],
                    baseline["probe-test-lib"]
                    | {
                        "name": "probe-owner-test-lib",
                        "deps": expected_deps,
                        "visibility": ["//visibility:private"],
                    },
                )
                self.assertTrue(targets["probe-owner-test-lib"]["testonly"])
                self.assertEqual(
                    targets["probe-unit-tests-bin"]["crate"], "probe-owner-test-lib"
                )
                self.assertEqual(targets["probe-unit-tests-bin"]["deps"], expected_deps)
                integration = "probe-lifecycle-test" + ("-bin" if shape else "")
                for name in (integration, "probe-lifecycle-test-windows-cross-bin"):
                    self.assertEqual(
                        targets[name]["deps"],
                        expected_deps[:-1] + ["probe-owner-test-lib", "//deps:extra"],
                    )
                # Only owner harnesses and the private library may change.
                changed = {name for name in baseline if baseline[name] != targets[name]}
                self.assertEqual(
                    changed,
                    {
                        "probe-unit-tests-bin",
                        integration,
                        "probe-lifecycle-test-windows-cross-bin",
                    },
                )
                self.assertEqual(set(targets) - set(baseline), {"probe-owner-test-lib"})

    def test_owner_only_map_generates_no_public_test_library(self):
        targets = MacroRecorder({}).generate(
            owner_test_dependency_replacements={"//deps:normal": "//deps:owner"}
        )
        self.assertNotIn("probe-test-lib", targets)
        self.assertEqual(
            targets["probe-unit-tests-bin"]["crate"], "probe-owner-test-lib"
        )
        self.assertEqual(targets["probe-owner-test-lib"]["deps"], ["//deps:owner"])

    @unittest.skipIf(tomllib is None, "Cargo dependency closure requires Python 3.11+")
    def test_supervisor_owner_closure_keeps_agentd_fleet_identity(self):
        def record_package(package, *, resolved_features=()):
            directory = ROOT / "codex-rs" / package
            manifest = tomllib.loads(
                (directory / "Cargo.toml").read_text(encoding="utf-8")
            )
            workspace = tomllib.loads(
                (ROOT / "codex-rs/Cargo.toml").read_text(encoding="utf-8")
            )["workspace"]["dependencies"]

            def dependency_label(spec, resolved):
                base = ROOT / "codex-rs" if spec.get("workspace") else directory
                return (
                    "//"
                    + (base / resolved["path"]).resolve().relative_to(ROOT).as_posix()
                )

            def linux_select(branches):
                unknown = set(branches) - {
                    "@platforms//os:linux",
                    "//conditions:default",
                }
                self.assertFalse(
                    unknown, f"unsupported fixture select conditions: {unknown}"
                )
                return branches.get(
                    "@platforms//os:linux", branches["//conditions:default"]
                )

            dependencies = []
            optional = {}
            for name, spec in manifest["dependencies"].items():
                if not isinstance(spec, dict):
                    continue
                resolved = workspace[name] if spec.get("workspace") else spec
                if isinstance(resolved, dict) and "path" in resolved:
                    label = dependency_label(spec, resolved)
                    if spec.get("optional"):
                        optional[name] = label
                    else:
                        dependencies.append(label)
            binaries = {
                entry["name"]: entry["path"] for entry in manifest.get("bin", [])
            }
            recorder = MacroRecorder(binaries)
            macro = recorder.scope["codex_rust_crate"]

            def configured_macro(**kwargs):
                pending = list(kwargs.get("crate_features", [])) + list(
                    resolved_features
                )
                enabled = set()
                while pending:
                    feature = pending.pop()
                    if feature in enabled:
                        continue
                    enabled.add(feature)
                    pending.extend(manifest.get("features", {}).get(feature, []))
                dependencies.extend(
                    label
                    for name, label in optional.items()
                    if name in enabled or "dep:" + name in enabled
                )
                macro(**kwargs)

            recorder.scope["codex_rust_crate"] = configured_macro
            recorder.scope["all_crate_deps"] = lambda **kwargs: list(dependencies)
            dev_dependencies = []
            for name, spec in manifest.get("dev-dependencies", {}).items():
                if isinstance(spec, dict):
                    resolved = workspace[name] if spec.get("workspace") else spec
                    if isinstance(resolved, dict) and "path" in resolved:
                        dev_dependencies.append(dependency_label(spec, resolved))
            recorder.scope["rust_test_dependencies"] = lambda replacements, **kwargs: [
                replacements.get(dep, dep)
                for dep in dict.fromkeys(
                    dependencies
                    + (dev_dependencies if kwargs.get("normal_dev") else [])
                )
            ]
            recorder.scope.update(
                load=lambda *args: None, glob=recorder.glob, select=linux_select
            )
            module = ast.parse((directory / "BUILD.bazel").read_text(encoding="utf-8"))
            # Evaluate the crate and explicit library declarations, excluding
            # unrelated product wrappers and standalone qualification harnesses.
            module.body = [
                node
                for node in module.body
                if isinstance(node, ast.Assign)
                and any(
                    isinstance(target, ast.Name)
                    and target.id == "_UNIT_TEST_DEPENDENCIES"
                    for target in node.targets
                )
                or isinstance(node, ast.Expr)
                and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Name)
                and node.value.func.id in {"load", "codex_rust_crate", "rust_library"}
            ]
            exec(
                compile(module, str(directory / "BUILD.bazel"), "exec"), recorder.scope
            )
            return {name: attrs for name, (_, attrs) in recorder.targets.items()}

        # The generated dependency list includes Cargo features selected by
        # workspace consumers, separately from this target's Rust cfg features.
        supervisor_manifest = tomllib.loads(
            (ROOT / "codex-rs/hepta-supervisor/Cargo.toml").read_text(encoding="utf-8")
        )
        owner_features = supervisor_manifest["dev-dependencies"]["codex-hepta-fleet"][
            "features"
        ]
        self.assertEqual(owner_features, ["durable-store"])
        fleet = record_package("hepta-fleet", resolved_features=owner_features)
        protocol = record_package("hepta-agent-protocol")
        supervisor = record_package("hepta-supervisor")
        agentd = record_package("hepta-agentd")
        components = record_package("hepta-agent-components")
        fleet_label = "//codex-rs/hepta-fleet"
        protocol_label = "//codex-rs/hepta-agent-protocol"
        fleet_variant = fleet_label + ":hepta-fleet-supervisor-owner-test-lib"
        protocol_variant = (
            protocol_label + ":hepta-agent-protocol-supervisor-owner-test-lib"
        )
        durable = fleet["hepta-fleet-supervisor-owner-test-lib"]
        self.assertTrue(durable["testonly"])
        self.assertEqual(fleet["hepta-fleet"]["crate_features"], [])
        self.assertEqual(fleet["hepta-fleet"]["deps"].count("//codex-rs/state"), 1)
        self.assertEqual(durable["deps"].count("//codex-rs/state"), 1)
        fleet_manifest = tomllib.loads(
            (ROOT / "codex-rs/hepta-fleet/Cargo.toml").read_text(encoding="utf-8")
        )
        self.assertTrue(fleet_manifest["dependencies"]["codex-state"]["optional"])
        self.assertEqual(fleet_manifest["features"]["default"], [])
        self.assertIn("dep:codex-state", fleet_manifest["features"]["durable-store"])

        self.assertEqual(durable["crate_features"], ["durable-store"])
        self.assertEqual(durable["compile_data"], fleet["hepta-fleet"]["compile_data"])
        self.assertEqual(
            durable["deps"], fleet["hepta-fleet"]["deps"] + ["@crates//:sqlx"]
        )
        self.assertEqual(
            durable["visibility"],
            [protocol_label + ":__pkg__", "//codex-rs/hepta-supervisor:__pkg__"],
        )
        protocol_owner = protocol["hepta-agent-protocol-supervisor-owner-test-lib"]
        self.assertTrue(protocol_owner["testonly"])
        self.assertEqual(
            protocol_owner["visibility"], ["//codex-rs/hepta-supervisor:__pkg__"]
        )
        self.assertIn(fleet_variant, protocol_owner["deps"])
        self.assertNotIn(fleet_label, protocol_owner["deps"])
        owner = supervisor["hepta-supervisor-owner-test-lib"]
        for variant in (fleet_variant, protocol_variant):
            self.assertIn(variant, owner["deps"])
        self.assertIn(
            "//codex-rs/hepta-intelligence-eval:hepta-intelligence-eval-test-lib",
            owner["deps"],
        )
        for name in (
            "hepta-supervisor",
            "hepta-supervisor-test-lib",
            "hepta-supervisor-offline-authority-tools-lib",
        ):
            self.assertIn(fleet_label, supervisor[name]["deps"])
            self.assertIn(protocol_label, supervisor[name]["deps"])
        self.assertIn(fleet_label, protocol["hepta-agent-protocol"]["deps"])
        agentd_test = agentd["hepta-agentd-unit-tests-bin"]["deps"]
        self.assertIn(
            "//codex-rs/hepta-supervisor:hepta-supervisor-test-lib", agentd_test
        )
        self.assertIn(
            fleet_label, components["hepta-agent-components-test-lib"]["deps"]
        )
        self.assertIn(protocol_label, agentd_test)
        self.assertNotIn(fleet_variant, agentd_test)
        self.assertNotIn(protocol_variant, agentd_test)

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
        declarations = []

        def record_crate(**kwargs):
            declarations.append(kwargs)
            return recorder.scope["codex_rust_crate"](**kwargs)

        scope = recorder.scope | {
            "load": lambda *args: None,
            "exports_files": lambda *args, **kwargs: None,
            "codex_rust_crate": record_crate,
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
        requirements = {
            entry["name"]: entry.get("required-features", [])
            for entry in manifest["bin"]
        }
        self.assertEqual(len(declarations), 1)
        self.assertEqual(declarations[0]["binary_required_features"], requirements)
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
                features = closure if binary in offline else set()
                if not set(requirements[binary]) <= features:
                    self.assert_binary_absent(targets, binary)
                    continue
                self.assertEqual(
                    set(targets[binary]["crate_features"]),
                    features,
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
