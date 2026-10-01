#!/usr/bin/env python3
"""Exercise the actual crate macro and BUILD calls without invoking Bazel.

Only Bazel's loading-time primitives and generated dependency metadata are
substituted. Configurable dependencies remain opaque expressions, so the
macro cannot accidentally pass by iterating or flattening a select(). These
checks cover rule emission; Bazel analysis and Rust compilation are separate.
"""

import copy
import fnmatch
from pathlib import Path
import types
import unittest


ROOT = Path(__file__).resolve().parents[1]
CLIENT = "//codex-rs/app-server-client:app-server-client"
ADAPTER = "//codex-rs/hepta-codex-adapter:hepta-codex-adapter"
AGENTD = "//codex-rs/hepta-agentd:hepta-agentd"
INFER = "//codex-rs/hepta-infer-worker-host:hepta-infer-worker-host"
LINUX = "//platforms:linux"
MACOS = "//platforms:macos"
DEFAULT = "//conditions:default"


class LoadingError(ValueError):
    pass


class Configurable:
    """A minimal opaque select/list expression with per-condition evaluation."""

    def __init__(self, parts):
        self.parts = parts

    def __add__(self, other):
        return Configurable(self.parts + self._parts(other))

    def __radd__(self, other):
        return Configurable(self._parts(other) + self.parts)

    @staticmethod
    def _parts(value):
        return value.parts if isinstance(value, Configurable) else [list(value)]

    def __iter__(self):
        raise TypeError("Bazel select expressions cannot be iterated during loading")

    def __eq__(self, other):
        return isinstance(other, Configurable) and self.parts == other.parts

    def evaluate(self, condition=DEFAULT):
        result = []
        for part in self.parts:
            result.extend(
                part.get(condition, part.get(DEFAULT, []))
                if isinstance(part, dict)
                else part
            )
        return result


def select(branches):
    return Configurable([copy.deepcopy(branches)])


def values(expression, condition=DEFAULT):
    return (
        expression.evaluate(condition)
        if isinstance(expression, Configurable)
        else list(expression)
    )


def metadata(deps=(), dev_deps=(), **extra):
    return {
        "binaries": {},
        "deps": list(deps),
        "dev_deps": list(dev_deps),
        "deps_by_platform": {},
        "dev_deps_by_platform": {},
        "build_deps": [],
        "aliases": {},
        **extra,
    }


class MacroRuntime:
    def __init__(self, dep_data, files=None):
        self.dep_data = dep_data
        self.package = next(iter(dep_data))
        self.files = files or ["src/lib.rs", "src/helper.rs"]
        self.rules = {}
        self.all_deps_calls = []

        def label(value):
            value = str(value)
            if value.startswith("@@//"):
                value = value[2:]
            if value.startswith("@//"):
                value = value[1:]
            if value.startswith(":"):
                return "//" + self.package + value
            if not value.startswith(("//", "@")):
                return "//" + self.package + ":" + value
            if ":" not in value:
                return value + ":" + value.rsplit("/", 1)[-1]
            return value

        self.label = label
        self.env = {
            "load": lambda *args, **kwargs: None,
            "exports_files": lambda *args, **kwargs: None,
            "DEP_DATA": self.dep_data,
            "all_crate_deps": self.all_crate_deps,
            "select": select,
            "Label": label,
            "fail": self.fail,
            "platform_common": types.SimpleNamespace(ConstraintValueInfo=object()),
            "glob": self.glob,
            "native": types.SimpleNamespace(
                package_name=lambda: self.package,
                glob=self.glob,
                filegroup=self.recorder("filegroup"),
            ),
            "rule": lambda **kwargs: self.recorder("workspace_root_test"),
            "attr": types.SimpleNamespace(
                **{
                    name: lambda *args, **kwargs: None
                    for name in (
                        "bool",
                        "label",
                        "label_list",
                        "label_keyed_string_dict",
                        "string_dict",
                        "int",
                    )
                }
            ),
            "WINE_TEST_TARGET_COMPATIBLE_WITH": [],
        }
        for kind in (
            "rust_library",
            "rust_proc_macro",
            "rust_binary",
            "rust_test",
            "cargo_build_script",
            "foreign_platform_binary",
        ):
            self.env[kind] = self.recorder(kind)
        self.execute(ROOT / "defs.bzl")

    @staticmethod
    def fail(message):
        raise LoadingError(message)

    def recorder(self, kind):
        def record(**attrs):
            key = "//" + self.package + ":" + attrs["name"]
            if key in self.rules:
                raise LoadingError("duplicate emitted rule: " + key)
            self.rules[key] = (kind, copy.deepcopy(attrs))

        return record

    def glob(self, include, exclude=(), allow_empty=False):
        def matches(path, pattern):
            def components_match(parts, patterns):
                if not patterns:
                    return not parts
                if patterns[0] == "**":
                    return components_match(parts, patterns[1:]) or bool(
                        parts and components_match(parts[1:], patterns)
                    )
                return bool(
                    parts
                    and fnmatch.fnmatchcase(parts[0], patterns[0])
                    and components_match(parts[1:], patterns[1:])
                )

            return components_match(path.split("/"), pattern.split("/"))

        found = sorted(
            path
            for path in self.files
            if any(matches(path, pattern) for pattern in include)
            and not any(matches(path, pattern) for pattern in exclude)
        )
        if not found and not allow_empty:
            raise LoadingError("empty fixture glob: " + repr(include))
        return found

    def all_crate_deps(self, normal=False, normal_dev=False, build=False):
        self.all_deps_calls.append((self.package, normal, normal_dev, build))
        data = self.dep_data[self.package]
        kinds = (["dev_deps"] if normal_dev else []) + (["build_deps"] if build else [])
        if normal or not kinds:
            kinds.append("deps")
        common = sorted({dep for kind in kinds for dep in data.get(kind, [])})
        conditions = {
            condition
            for kind in kinds
            for condition in data.get(kind + "_by_platform", {})
        }
        branches = {
            condition: sorted(
                {
                    dep
                    for kind in kinds
                    for dep in data.get(kind + "_by_platform", {}).get(condition, [])
                }
                - set(common)
            )
            for condition in sorted(conditions)
        }
        if not branches:
            return common
        branches[DEFAULT] = []
        return common + select(branches)

    def execute(self, path):
        exec(compile(path.read_text(), str(path), "exec"), self.env)

    def macro(self, **kwargs):
        self.env["codex_rust_crate"](**kwargs)

    def rule(self, label):
        return self.rules[self.label(label)][1]

    def deps(self, label, condition=DEFAULT):
        return [
            self.label(dep)
            for dep in values(self.rule(label).get("deps", []), condition)
        ]


class UnitTestVariantTests(unittest.TestCase):
    def synthetic_runtime(self):
        return MacroRuntime(
            {
                "codex-rs/example": metadata(
                    [CLIENT, "//shared:types"],
                    ["//dev:fixture"],
                    binaries={"example-bin": "src/main.rs"},
                    build_deps=["//build:tool"],
                )
            },
            files=[
                "src/lib.rs",
                "src/helper.rs",
                "src/main.rs",
                "tests/sample.rs",
                "build.rs",
            ],
        )

    def test_opt_in_leaves_production_binary_and_integration_rules_identical(self):
        baseline = self.synthetic_runtime()
        variant = self.synthetic_runtime()
        common = dict(
            name="example",
            crate_name="codex_example",
            compile_data=["schema.json"],
            lib_data_extra=["fixture.json"],
            rustc_env_files=["generated.env"],
            deps_extra=["//extra:runtime"],
        )
        baseline.macro(**common)
        variant.macro(
            **common,
            unit_test_library_features=[],
            unit_test_deps_replacements={CLIENT: CLIENT + "-unit-test-lib"},
        )
        prefix = "//codex-rs/example:"
        self.assertNotIn(prefix + "example-unit-test-lib", baseline.rules)
        self.assertEqual(baseline.rule(":example-unit-tests-bin")["crate"], "example")
        for label, declaration in baseline.rules.items():
            if label != prefix + "example-unit-tests-bin":
                self.assertEqual(declaration, variant.rules[label], label)
        unit_library = variant.rule(":example-unit-test-lib")
        unit_test = variant.rule(":example-unit-tests-bin")
        self.assertEqual(
            variant.label(unit_test["crate"]), prefix + "example-unit-test-lib"
        )
        self.assertTrue(unit_library["testonly"])
        self.assertEqual(unit_library["visibility"], ["//visibility:private"])
        self.assertEqual(unit_library["crate_name"], "codex_example")
        self.assertEqual(unit_library["compile_data"], ["schema.json"])
        self.assertEqual(unit_library["rustc_env_files"], ["generated.env"])
        for target in (":example-unit-test-lib", ":example-unit-tests-bin"):
            self.assertIn(CLIENT + "-unit-test-lib", variant.deps(target))
            self.assertNotIn(CLIENT, variant.deps(target))
            self.assertIn("//extra:runtime", variant.deps(target))
            self.assertIn(prefix + "example-build-script", variant.deps(target))
        self.assertIn("//dev:fixture", variant.deps(":example-unit-tests-bin"))
        self.assertNotIn("//dev:fixture", variant.deps(":example-unit-test-lib"))

    def test_platform_and_dev_buckets_preserve_condition_and_replace_identity(self):
        old = "//shared/client:client"
        new = "//shared/client:client-unit-test-lib"
        runtime = MacroRuntime(
            {
                "codex-rs/example": metadata(
                    ["//shared:types"],
                    [old, "//dev:fixture"],
                    deps_by_platform={LINUX: [old, old], MACOS: ["//mac:transport"]},
                    dev_deps_by_platform={
                        LINUX: [old, "//linux:fixture"],
                        MACOS: ["//mac:fixture"],
                    },
                )
            }
        )
        helper = runtime.env["_unit_test_crate_deps"]
        expression = helper({"//shared/client": new}, normal_dev=True)
        for condition in (DEFAULT, LINUX, MACOS):
            actual = [runtime.label(dep) for dep in values(expression, condition)]
            self.assertIn(new, actual)
            self.assertNotIn(old, actual)
            self.assertEqual(actual.count(new), 1)
            self.assertEqual(actual.count("//shared:types"), 1)
        self.assertIn("//linux:fixture", values(expression, LINUX))
        self.assertNotIn("//linux:fixture", values(expression, MACOS))
        self.assertIn("//mac:transport", values(expression, MACOS))
        self.assertNotIn("//mac:transport", values(expression, DEFAULT))
        normal_only = helper({old: new})
        self.assertIn(new, values(normal_only, LINUX))
        self.assertNotIn(new, values(normal_only, MACOS))
        self.assertNotIn("//dev:fixture", values(normal_only, LINUX))

    def test_alias_keys_follow_replacement_without_changing_rust_alias(self):
        runtime = MacroRuntime(
            {
                "codex-rs/example": metadata(
                    [CLIENT], aliases={CLIENT: "codex_app_server_client"}
                )
            }
        )
        new = CLIENT + "-unit-test-lib"
        runtime.macro(
            name="example",
            crate_name="codex_example",
            unit_test_library_features=[],
            unit_test_deps_replacements={CLIENT: new},
        )
        for target in (":example-unit-test-lib", ":example-unit-tests-bin"):
            aliases = {
                runtime.label(key): value
                for key, value in runtime.rule(target)["aliases"].items()
            }
            self.assertEqual(aliases, {new: "codex_app_server_client"})
        self.assertNotIn("aliases", runtime.rule(":example"))

    def test_dev_only_alias_stays_out_of_the_unit_library(self):
        dev = "//dev:fixture"
        runtime = MacroRuntime(
            {
                "codex-rs/example": metadata(
                    [CLIENT],
                    [dev],
                    aliases={CLIENT: "codex_app_server_client", dev: "fixture_support"},
                )
            }
        )
        runtime.macro(
            name="example",
            crate_name="codex_example",
            unit_test_library_features=[],
            unit_test_deps_replacements={CLIENT: CLIENT + "-unit-test-lib"},
        )
        library_aliases = {
            runtime.label(key): value
            for key, value in runtime.rule(":example-unit-test-lib")["aliases"].items()
        }
        test_aliases = {
            runtime.label(key): value
            for key, value in runtime.rule(":example-unit-tests-bin")["aliases"].items()
        }
        self.assertNotIn(dev, library_aliases)
        self.assertEqual(test_aliases[dev], "fixture_support")

    def test_unit_features_extend_the_existing_profile_without_changing_production(
        self,
    ):
        runtime = MacroRuntime({"codex-rs/example": metadata()})
        runtime.macro(
            name="example",
            crate_name="codex_example",
            crate_features=["production-profile"],
            unit_test_library_features=["test-support"],
        )
        self.assertEqual(
            runtime.rule(":example")["crate_features"], ["production-profile"]
        )
        for target in (":example-unit-test-lib", ":example-unit-tests-bin"):
            self.assertEqual(
                runtime.rule(target)["crate_features"],
                ["production-profile", "test-support"],
            )

    def test_unknown_replacement_fails_instead_of_appending_an_unbound_variant(self):
        runtime = MacroRuntime({"codex-rs/example": metadata([CLIENT])})
        with self.assertRaises(LoadingError):
            runtime.macro(
                name="example",
                crate_name="codex_example",
                unit_test_library_features=[],
                unit_test_deps_replacements={
                    "//missing:client": CLIENT + "-unit-test-lib"
                },
            )

    def test_conflicting_aliases_fail_closed(self):
        first, second, replacement = (
            "//shared:first",
            "//shared:second",
            "//shared:variant",
        )
        runtime = MacroRuntime(
            {
                "codex-rs/example": metadata(
                    [first, second], aliases={first: "first", second: "second"}
                )
            }
        )
        with self.assertRaises(LoadingError):
            runtime.env["_unit_test_crate_aliases"](
                {first: replacement, second: replacement}
            )

    def test_actual_builds_form_one_testonly_client_adapter_agentd_closure(self):
        paths = [CLIENT, ADAPTER, AGENTD, INFER]
        dependencies = {
            CLIENT: ["//shared:transport"],
            ADAPTER: [CLIENT, "//shared:prompt-extension"],
            AGENTD: [CLIENT, ADAPTER, "//shared:types"],
            INFER: [CLIENT, ADAPTER, AGENTD, "//shared:types"],
        }
        data = {}
        for label in paths:
            package = label.removeprefix("//").split(":", 1)[0]
            aliases = {
                dep: dep.rsplit(":", 1)[1].replace("-", "_")
                for dep in dependencies[label]
                if dep in paths
            }
            data[package] = metadata(dependencies[label], aliases=aliases)
        runtime = MacroRuntime(
            data, files=["src/lib.rs", "src/helper.rs", "tests/support/fixture.rs"]
        )
        for label in paths:
            runtime.package = label.removeprefix("//").split(":", 1)[0]
            runtime.execute(ROOT / runtime.package / "BUILD.bazel")
        variants = {label: label + "-unit-test-lib" for label in paths}
        for label in paths:
            with self.subTest(label=label):
                package, name = label.removeprefix("//").split(":", 1)
                runtime.package = package
                production = runtime.rule(label)
                variant = runtime.rule(variants[label])
                unit_test = runtime.rule(
                    "//" + package + ":" + name + "-unit-tests-bin"
                )
                self.assertTrue(variant["testonly"])
                self.assertNotIn("//visibility:public", variant["visibility"])
                self.assertEqual(variant["crate_name"], production["crate_name"])
                self.assertNotIn("test-support", production["crate_features"])
                self.assertEqual(runtime.label(unit_test["crate"]), variants[label])
                self.assertCountEqual(runtime.deps(label), dependencies[label])
                for dependency in dependencies[label]:
                    if dependency in variants:
                        self.assertIn(
                            variants[dependency], runtime.deps(variants[label])
                        )
                        self.assertNotIn(dependency, runtime.deps(variants[label]))
                for dependency in runtime.deps(label):
                    self.assertNotIn(dependency, variants.values())
        self.assertIn("test-support", runtime.rule(variants[CLIENT])["crate_features"])
        for producer, consumers in (
            (CLIENT, [ADAPTER, AGENTD, INFER]),
            (ADAPTER, [AGENTD, INFER]),
            (AGENTD, [INFER]),
        ):
            visibility = runtime.rule(variants[producer])["visibility"]
            expected = {
                consumer.split(":", 1)[0] + ":__pkg__" for consumer in consumers
            }
            self.assertEqual(set(visibility), expected)
        self.assertEqual(
            runtime.rule(variants[INFER])["visibility"], ["//visibility:private"]
        )


if __name__ == "__main__":
    unittest.main()
