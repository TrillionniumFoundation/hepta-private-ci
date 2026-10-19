"""Keep Cargo crate aliases on their selected dependency edges."""

def _selected_aliases(dependencies, names, replacements):
    result = {}
    for dependency in dependencies:
        original = Label(dependency)
        if original not in names:
            continue

        # rust_test_dependencies replaces workspace edges, never external Cargo.
        actual = dependency if dependency.startswith("@crates//:") else replacements.get(original, dependency)
        actual = native.package_relative_label(actual)
        alias = names[original]
        if actual in result and result[actual] != alias:
            fail("conflicting Cargo aliases for {}: {} and {}".format(actual, result[actual], alias))
        result[actual] = alias
    return result

def crate_aliases(
        dep_data,
        resolved_platforms,
        normal = False,
        normal_dev = False,
        build = False,
        replacements = {}):
    """Select aliases with the same kind/platform semantics as dependency lists.

    rules_rs 0.0.96 stores all dependency kinds in one alias map. Passing that
    map directly adds implicit label dependencies, including dev-only cycles.
    Test-only replacements must also apply to alias keys, not only to deps.

    Args:
        dep_data: This package's generated DEP_DATA entry.
        resolved_platforms: The generated public RESOLVED_PLATFORMS selector.
        normal: Include ordinary dependencies, also the default when no kind is set.
        normal_dev: Include dev dependencies.
        build: Include build-script dependencies.
        replacements: Original workspace labels to test-only dependency labels.

    Returns:
        A label-to-crate-name dictionary or a platform-select of dictionaries.
    """
    kinds = []
    if normal_dev:
        kinds.append("dev_deps")
    if build:
        kinds.append("build_deps")
    if normal or not kinds:
        kinds.append("deps")

    names = {Label(dependency): alias for dependency, alias in dep_data.get("aliases", {}).items()}
    normalized = {Label(original): replacement for original, replacement in replacements.items()}
    shared = []
    by_platform = {}
    for kind in kinds:
        shared.extend(dep_data.get(kind, []))
        for platform, dependencies in dep_data.get(kind + "_by_platform", {}).items():
            by_platform.setdefault(platform, []).extend(dependencies)

    # The pinned rules_rs generator omits empty platform branches. Its public
    # RESOLVED_PLATFORMS has this exact shape; Bazel 9 compares selects by value.
    # Equality proves these keys cover every resolved platform. Otherwise a
    # missing empty platform makes the all_crate_deps intersection empty.
    covered_platforms = select({platform: [] for platform in by_platform} | {
        "//conditions:default": ["@platforms//:incompatible"],
    })
    if by_platform and covered_platforms == resolved_platforms:
        platform_deps = by_platform.values()
        common_dependencies = set(platform_deps[0])
        for dependencies in platform_deps[1:]:
            common_dependencies.intersection_update(dependencies)

        # With test replacements, workspace edges retain their original
        # selects; only external Cargo edges use all_crate_deps' intersection.
        shared.extend([
            dependency
            for dependency in common_dependencies
            if not replacements or dependency.startswith("@crates//:")
        ])

    common = _selected_aliases(shared, names, normalized)
    branches = {
        platform: _selected_aliases(shared + dependencies, names, normalized)
        for platform, dependencies in by_platform.items()
    }
    if not any([aliases != common for aliases in branches.values()]):
        return common
    branches["//conditions:default"] = common
    return select(branches)
