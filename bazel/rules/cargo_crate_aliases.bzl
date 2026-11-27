"""Preserve Cargo renames on the dependency graph selected for each Rust target."""

load("@crates//:data.bzl", "DEP_DATA")
load("@crates//:defs.bzl", "RESOLVED_PLATFORMS")
load(":crate_aliases.bzl", _crate_aliases = "crate_aliases")

def cargo_crate_aliases(
        normal = False,
        normal_dev = False,
        build = False,
        workspace_replacements = {}):
    """Select aliases by Cargo dependency kind, platform, and test-only variant."""
    return _crate_aliases(
        DEP_DATA[native.package_name()],
        RESOLVED_PLATFORMS,
        normal = normal,
        normal_dev = normal_dev,
        build = build,
        replacements = workspace_replacements,
    )
