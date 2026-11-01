"""Preserve Cargo import names on the dependency edges selected for each rule."""

load("@crates//:data.bzl", "DEP_DATA")
load("@crates//:defs.bzl", "aliases")

def _aliases_for_dependencies(dependencies, names, replacements):
    result = {}
    for dependency in dependencies:
        original = Label(dependency)
        if original not in names:
            continue
        replacement = dependency if dependency.startswith("@crates//:") else replacements.get(original, dependency)
        target = Label(replacement)
        name = names[original]
        if target in result and result[target] != name:
            fail("Dependency replacement gives conflicting Cargo aliases for %s" % target)
        result[target] = name
    return result

def rust_crate_aliases(normal = False, normal_dev = False, build = False, replacements = {}):
    """Mirror all_crate_deps kinds and platform selection, including test variants."""
    data = DEP_DATA.get(native.package_name())
    if not data:
        return {}
    names = {Label(dependency): name for dependency, name in aliases().items()}
    replacements = {Label(original): replacement for original, replacement in replacements.items()}
    kinds = []
    if normal_dev:
        kinds.append("dev_deps")
    if build:
        kinds.append("build_deps")
    if normal or not kinds:
        kinds.append("deps")
    shared = []
    by_platform = {}
    for kind in kinds:
        shared += data.get(kind, [])
        for platform, dependencies in data.get(kind + "_by_platform", {}).items():
            by_platform.setdefault(platform, []).extend(dependencies)
    shared_aliases = _aliases_for_dependencies(shared, names, replacements)
    branches = {}
    for platform, dependencies in by_platform.items():
        selected = _aliases_for_dependencies(shared + dependencies, names, replacements)
        if selected != shared_aliases:
            branches[platform] = selected
    if not branches:
        return shared_aliases
    branches["//conditions:default"] = shared_aliases
    return select(branches)
