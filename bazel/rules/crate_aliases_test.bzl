"""Analysis regressions for Cargo alias dependency edges."""

load("@bazel_skylib//lib:unittest.bzl", "analysistest", "asserts")
load("@bazel_skylib//rules:common_settings.bzl", "string_flag")
load("@rules_rs//rs/private:all_crate_deps.bzl", _all_crate_deps = "all_crate_deps")
load(":crate_aliases.bzl", "crate_aliases")

_AliasInfo = provider(fields = ["values"])

def _alias_probe_impl(ctx):
    declared = {dependency.label: True for dependency in ctx.attr.deps}
    for dependency in ctx.attr.aliases:
        if dependency.label not in declared:
            fail("alias introduced an undeclared dependency: {}".format(dependency.label))
    return [_AliasInfo(values = {str(dependency.label): name for dependency, name in ctx.attr.aliases.items()})]

_alias_probe = rule(
    implementation = _alias_probe_impl,
    attrs = {
        "aliases": attr.label_keyed_string_dict(),
        "deps": attr.label_list(),
    },
)

def _alias_values_probe_impl(ctx):
    return [_AliasInfo(values = ctx.attr.values)]

_alias_values_probe = rule(implementation = _alias_values_probe_impl, attrs = {"values": attr.string_dict()})

def _aliases_test_impl(ctx):
    env = analysistest.begin(ctx)
    actual = analysistest.target_under_test(env)[_AliasInfo].values
    asserts.equals(env, ctx.attr.expected, actual)
    return analysistest.end(env)

_aliases_test = analysistest.make(_aliases_test_impl, attrs = {"expected": attr.string_dict()})
_linux_aliases_test = analysistest.make(
    _aliases_test_impl,
    attrs = {"expected": attr.string_dict()},
    config_settings = {str(Label(":crate_aliases_test_platform")): "linux"},
)
_windows_aliases_test = analysistest.make(
    _aliases_test_impl,
    attrs = {"expected": attr.string_dict()},
    config_settings = {str(Label(":crate_aliases_test_platform")): "windows"},
)
_macos_aliases_test = analysistest.make(
    _aliases_test_impl,
    attrs = {"expected": attr.string_dict()},
    config_settings = {str(Label(":crate_aliases_test_platform")): "macos"},
)

def _label(name):
    return "//{}:{}".format(native.package_name(), name)

def _resolved_platforms(platforms):
    return select({platform: [] for platform in platforms} | {
        "//conditions:default": ["@platforms//:incompatible"],
    })

def crate_aliases_test_suite(name):
    """Cover kind isolation, dependency variants, and platform-specific aliases."""
    string_flag(name = "crate_aliases_test_platform", build_setting_default = "default")
    linux = _label(name + "_linux")
    windows = _label(name + "_windows")
    macos = _label(name + "_macos")
    platforms = [linux, windows]
    resolved_platforms = _resolved_platforms(platforms)
    for platform in ["linux", "windows", "macos"]:
        native.config_setting(name = name + "_" + platform, flag_values = {":crate_aliases_test_platform": platform})

    normal = _label(name + "_normal_dep")
    yaml = _label(name + "_yaml_dep")
    original = _label(name + "_original_dep")
    replacement = _label(name + "_replacement_dep")
    build = _label(name + "_build_dep")
    dev = _label(name + "_dev_dep")
    aliases = {
        normal: "normal_name",
        yaml: "serde_yaml",
        original: "core_name",
        build: "build_name",
        dev: "dev_name",
    }
    data = {
        "aliases": aliases,
        "deps": [normal, yaml, original],
        "build_deps": [build],
        "dev_deps": [dev],
    }

    # Like Agentd/Worker and MCP/test-common, dev consumers depend back on the
    # normal library. A leaked dev alias therefore creates a real Bazel cycle.
    native.filegroup(name = name + "_dev_dep", srcs = [":" + name + "_normal"], testonly = True)
    native.filegroup(name = name + "_normal_dep", srcs = [":" + name + "_build"], testonly = True)

    # A stale original alias also becomes a cycle on a replaced test library.
    native.filegroup(name = name + "_original_dep", srcs = [":" + name + "_replaced"], testonly = True)
    for suffix in ["yaml_dep", "replacement_dep", "build_dep", "linux_yaml", "windows_yaml", "cross_dep"]:
        native.filegroup(name = name + "_" + suffix, testonly = True)

    normal_aliases = {normal: "normal_name", yaml: "serde_yaml", original: "core_name"}
    replaced_aliases = {normal: "normal_name", yaml: "serde_yaml", replacement: "core_name"}
    cases = [
        ("normal", {}, data["deps"], normal_aliases),
        ("normal_explicit", {"normal": True}, data["deps"], normal_aliases),
        ("build", {"build": True}, [build], {build: "build_name"}),
        ("dev", {"normal_dev": True}, [dev], {dev: "dev_name"}),
        ("normal_dev", {"normal": True, "normal_dev": True}, data["deps"] + [dev], normal_aliases | {dev: "dev_name"}),
        ("replaced", {"replacements": {original: replacement}}, [normal, yaml, replacement], replaced_aliases),
        ("replaced_relative", {"replacements": {original: ":" + name + "_replacement_dep"}}, [normal, yaml, replacement], replaced_aliases),
        ("replaced_label", {"replacements": {Label(original): Label(replacement)}}, [normal, yaml, replacement], replaced_aliases),
        ("replaced_normal_dev", {"normal": True, "normal_dev": True, "replacements": {original: replacement}}, [normal, yaml, replacement, dev], replaced_aliases | {dev: "dev_name"}),
    ]
    tests = []
    for suffix, kwargs, dependencies, expected in cases:
        probe = name + "_" + suffix
        _alias_probe(name = probe, aliases = crate_aliases(data, resolved_platforms, **kwargs), deps = dependencies, testonly = True)
        test = probe + "_test"
        _aliases_test(name = test, target_under_test = ":" + probe, expected = {str(Label(label)): alias for label, alias in expected.items()})
        tests.append(":" + test)

    linux_yaml = _label(name + "_linux_yaml")
    windows_yaml = _label(name + "_windows_yaml")
    platform_data = {
        "aliases": aliases | {linux_yaml: "platform_yaml", windows_yaml: "platform_yaml"},
        "deps": [normal],
        "deps_by_platform": {linux: [linux_yaml], windows: [windows_yaml]},
        "build_deps": [build],
        "dev_deps": [dev],
    }
    for suffix, replacements in [("platform", {}), ("platform_replaced", {linux_yaml: replacement, windows_yaml: replacement})]:
        probe = name + "_" + suffix
        dependencies = _all_crate_deps(platform_data, platforms)
        if replacements:
            dependencies = [normal] + select({linux: [replacement], windows: [replacement], "//conditions:default": []})
        _alias_probe(
            name = probe,
            aliases = crate_aliases(platform_data, resolved_platforms, replacements = replacements),
            deps = dependencies,
            testonly = True,
        )
        for platform, factory, expected in [
            ("default", _aliases_test, {normal: "normal_name"}),
            ("linux", _linux_aliases_test, {normal: "normal_name", replacements.get(linux_yaml, linux_yaml): "platform_yaml"}),
            ("windows", _windows_aliases_test, {normal: "normal_name", replacements.get(windows_yaml, windows_yaml): "platform_yaml"}),
        ]:
            test = probe + "_" + platform + "_test"
            factory(name = test, target_under_test = ":" + probe, expected = {str(Label(label)): alias for label, alias in expected.items()})
            tests.append(":" + test)

    cross = _label(name + "_cross_dep")
    cross_data = {
        "aliases": {yaml: "serde_yaml", cross: "cross_name", linux_yaml: "platform_yaml"},
        "deps": [yaml],
        "deps_by_platform": {linux: [cross, linux_yaml]},
        "dev_deps_by_platform": {windows: [cross]},
    }
    for suffix, resolved in [("hoisted", platforms), ("hoisted_reordered", list(reversed(platforms))), ("missing_platform", platforms + [macos])]:
        probe = name + "_" + suffix
        _alias_probe(
            name = probe,
            aliases = crate_aliases(cross_data, _resolved_platforms(resolved), normal = True, normal_dev = True),
            # Use the actual pinned upstream algorithm as the dependency oracle.
            deps = _all_crate_deps(cross_data, resolved, normal = True, normal_dev = True),
            testonly = True,
        )
        common = {yaml: "serde_yaml"} if macos in resolved else {yaml: "serde_yaml", cross: "cross_name"}
        for platform, factory, expected in [
            ("default", _aliases_test, common),
            ("linux", _linux_aliases_test, {yaml: "serde_yaml", cross: "cross_name", linux_yaml: "platform_yaml"}),
            ("windows", _windows_aliases_test, {yaml: "serde_yaml", cross: "cross_name"}),
            ("macos", _macos_aliases_test, common),
        ]:
            test = probe + "_" + platform + "_test"
            factory(name = test, target_under_test = ":" + probe, expected = {str(Label(label)): alias for label, alias in expected.items()})
            tests.append(":" + test)

    probe = name + "_workspace_not_hoisted"
    _alias_probe(
        name = probe,
        aliases = crate_aliases(cross_data, resolved_platforms, normal = True, normal_dev = True, replacements = {cross: replacement}),
        # Preserve the existing rust_test_dependencies workspace replacement selects.
        deps = [yaml] + select({linux: [replacement, linux_yaml], windows: [replacement], "//conditions:default": []}),
        testonly = True,
    )
    for platform, factory, expected in [
        ("default", _aliases_test, {yaml: "serde_yaml"}),
        ("linux", _linux_aliases_test, {yaml: "serde_yaml", replacement: "cross_name", linux_yaml: "platform_yaml"}),
        ("windows", _windows_aliases_test, {yaml: "serde_yaml", replacement: "cross_name"}),
    ]:
        test = probe + "_" + platform + "_test"
        factory(name = test, target_under_test = ":" + probe, expected = {str(Label(label)): alias for label, alias in expected.items()})
        tests.append(":" + test)

    # Value comparisons cover external Cargo mapping without fetching a Rust
    # graph in this analysis-only suite. Default dictionaries remain explicit.
    external = "@crates//:crate_aliases_external_fixture"
    external_names = {external: "renamed_external", cross: "cross_name"}
    external_data = {"aliases": external_names, "deps_by_platform": {linux: [external, cross]}, "dev_deps_by_platform": {windows: [external, cross]}}
    external_aliases = crate_aliases(external_data, resolved_platforms, normal = True, normal_dev = True, replacements = {cross: replacement, external: replacement})
    expected_common = {native.package_relative_label(external): "renamed_external"}
    expected_branch = expected_common | {native.package_relative_label(replacement): "cross_name"}
    external_empty_data = {"aliases": external_names, "deps_by_platform": {linux: [external]}, "dev_deps_by_platform": {windows: [cross]}}
    external_empty_aliases = crate_aliases(external_empty_data, resolved_platforms, normal = True, normal_dev = True, replacements = {cross: replacement})
    checks = [
        ("selector_reordered", _resolved_platforms(list(reversed(platforms))) == resolved_platforms),
        ("selector_missing", _resolved_platforms([linux]) != resolved_platforms),
        ("selector_extra", _resolved_platforms(platforms + [macos]) != resolved_platforms),
        ("external_hoisted", external_aliases == select({linux: expected_branch, windows: expected_branch, "//conditions:default": expected_common})),
        ("external_empty_platform", external_empty_aliases == select({linux: expected_common, windows: {native.package_relative_label(replacement): "cross_name"}, "//conditions:default": {}})),
    ]
    for suffix, matched in checks:
        probe = name + "_" + suffix
        _alias_values_probe(name = probe, values = {"matched": str(matched)}, testonly = True)
        test = probe + "_test"
        _aliases_test(name = test, target_under_test = ":" + probe, expected = {"matched": "True"})
        tests.append(":" + test)
    native.test_suite(name = name, tests = tests)
