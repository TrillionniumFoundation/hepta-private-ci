"""Expose one proposer target with either Cargo-discovered or fallback metadata."""

load("@crates//:data.bzl", "DEP_DATA")
load("@rules_rust//rust:defs.bzl", "rust_binary", "rust_test")

def joint_generation_binary():
    """Call after codex_rust_crate; never redeclare its discovered binary."""

    # Read the same package key and mapping as //:defs.bzl. Discovery can change
    # with Cargo metadata regeneration, so neither state is guessed or pinned.
    binaries = DEP_DATA.get(native.package_name())["binaries"]
    if "hepta-joint-propose" in binaries:
        # codex_rust_crate already emitted the public binary and its bin tests.
        return

    sources = ["src/bin/hepta-joint-propose.rs"] + native.glob(["src/joint_generation/*.rs"])
    rust_binary(
        name = "hepta-joint-propose",
        srcs = sources,
        crate_name = "hepta_joint_propose",
        crate_root = "src/bin/hepta-joint-propose.rs",
        edition = "2024",
        visibility = ["//visibility:public"],
    )

    # The binary builds an explicit unsupported stub elsewhere; its numerical
    # tests exercise the actual Linux/libm profile only.
    rust_test(
        name = "hepta-joint-propose-tests",
        srcs = sources,
        crate_name = "hepta_joint_propose_tests",
        crate_root = "src/bin/hepta-joint-propose.rs",
        edition = "2024",
        target_compatible_with = ["@platforms//os:linux"],
    )
