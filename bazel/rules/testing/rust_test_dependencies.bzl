"""Resolve test-only workspace variants without changing external Cargo selects."""

load("@crates//:data.bzl", "DEP_DATA")
load("@crates//:defs.bzl", "all_crate_deps")

def rust_test_dependencies(replacements, normal_dev = False):
    """Keep one physical workspace crate identity throughout a test graph."""
    if not replacements:
        return all_crate_deps(normal = True, normal_dev = normal_dev)
    data = DEP_DATA[native.package_name()]
    normalized = {Label(original): replacement for original, replacement in replacements.items()}
    kinds = ["deps", "dev_deps"] if normal_dev else ["deps"]
    shared = {}
    by_platform = {}
    for kind in kinds:
        for dependency in data.get(kind, []):
            if not dependency.startswith("@crates//:"):
                shared[normalized.get(Label(dependency), dependency)] = True
        for platform, dependencies in data.get(kind + "_by_platform", {}).items():
            branch = by_platform.setdefault(platform, {})
            for dependency in dependencies:
                if not dependency.startswith("@crates//:"):
                    branch[normalized.get(Label(dependency), dependency)] = True
    result = all_crate_deps(normal = True, normal_dev = normal_dev, cargo_only = True)
    result += sorted(shared.keys())
    branches = {
        platform: sorted([dependency for dependency in dependencies if dependency not in shared])
        for platform, dependencies in by_platform.items()
    }
    if branches:
        branches["//conditions:default"] = []
        result += select(branches)
    return result
