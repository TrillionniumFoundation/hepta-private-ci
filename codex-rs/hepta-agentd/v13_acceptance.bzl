load("@crates//:data.bzl", "DEP_DATA")
load("@crates//:defs.bzl", "all_crate_deps")
load("@rules_rust//rust:defs.bzl", "rust_binary")

def v13_acceptance_example():
    """Expose one explicit example without duplicating auto-discovered targets."""
    name = "neuron_v13_acceptance"
    binaries = DEP_DATA.get(native.package_name())["binaries"]
    if name in binaries:
        if binaries[name] != "examples/neuron_v13_acceptance.rs":
            fail("V13 acceptance target points to an unexpected source")
        return
    rust_binary(
        name = name,
        testonly = True,
        srcs = ["examples/neuron_v13_acceptance.rs"] + native.glob(["examples/neuron_v13_acceptance/*.rs"]),
        crate_root = "examples/neuron_v13_acceptance.rs",
        crate_name = name,
        edition = "2024",
        deps = [":hepta-agentd"] + all_crate_deps(normal = True),
        tags = ["manual"],
        target_compatible_with = select({
            "@platforms//os:linux": [],
            "//conditions:default": ["@platforms//:incompatible"],
        }),
        visibility = ["//visibility:public"],
    )
