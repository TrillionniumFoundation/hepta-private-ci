load("@crates//:data.bzl", "DEP_DATA")
load("@crates//:defs.bzl", "all_crate_deps")
load("@rules_rust//rust:defs.bzl", "rust_binary")

def v13_acceptance_example():
    """Expose explicit examples without duplicating auto-discovered targets."""
    binaries = DEP_DATA.get(native.package_name())["binaries"]
    for name in ["neuron_v13_acceptance", "neuron_v13_guarded_acceptance"]:
        source = "examples/" + name + ".rs"
        if name in binaries:
            if binaries[name] != source:
                fail("V13 acceptance target points to an unexpected source")
            continue
        rust_binary(
            name = name,
            testonly = True,
            srcs = [source] + native.glob([
                "examples/neuron_v13_acceptance/*.rs",
                "examples/neuron_v13_guarded_acceptance/*.rs",
            ]),
            crate_root = source,
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
