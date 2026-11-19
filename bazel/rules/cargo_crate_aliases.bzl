"""Preserve Cargo renames on the dependency graph selected for each Rust target."""

load("@crates//:data.bzl", "DEP_DATA")

def cargo_crate_aliases(
        normal = False,
        normal_dev = False,
        build = False,
        workspace_replacements = {}):
    """Select aliases by Cargo dependency kind, platform, and test-only variant."""
    data = DEP_DATA[native.package_name()]
    renames = data.get("aliases", {})
    normalized = {Label(original): replacement for original, replacement in workspace_replacements.items()}
    kinds = []
    if normal_dev:
        kinds.append("dev_deps")
    if build:
        kinds.append("build_deps")
    if normal or not kinds:
        kinds.append("deps")

    shared = {}
    by_platform = {}
    for kind in kinds:
        for dependency in data.get(kind, []):
            if dependency in renames:
                shared[normalized.get(Label(dependency), dependency)] = renames[dependency]
        for platform, dependencies in data.get(kind + "_by_platform", {}).items():
            for dependency in dependencies:
                if dependency in renames:
                    branch = by_platform.setdefault(platform, {})
                    branch[normalized.get(Label(dependency), dependency)] = renames[dependency]

    if not by_platform:
        return shared

    # Each key is a complete target triple, matching all_crate_deps' selects.
    # Keep aliases off platforms where the corresponding dependency is absent.
    branches = {
        platform: shared | platform_aliases
        for platform, platform_aliases in sorted(by_platform.items())
    }
    branches["//conditions:default"] = shared
    return select(branches)
