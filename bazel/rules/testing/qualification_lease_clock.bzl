"""One test-only CognitiveStore identity for the lease-expiry qualifications."""

load("@crates//:data.bzl", "DEP_DATA")
load("@crates//:defs.bzl", "aliases")
load("@rules_rust//rust:defs.bzl", "rust_library")
load(":rust_test_dependencies.bzl", "rust_test_dependencies")

# This is the normal dependency closure from the two qualification roots,
# including Agentd's infer-worker-host dev dependency. Product targets keep
# their original dependencies and features; existing test-lib names stay intact.
LEASE_CLOCK_TEST_DEPENDENCIES = {
    "//codex-rs/app-server": "//codex-rs/app-server:app-server-qualification-clock-lib",
    "//codex-rs/app-server-client": "//codex-rs/app-server-client:app-server-client-qualification-clock-lib",
    "//codex-rs/ext/hepta-memory": "//codex-rs/ext/hepta-memory:hepta-memory-qualification-clock-lib",
    "//codex-rs/hepta-agentd": "//codex-rs/hepta-agentd:hepta-agentd-qualification-clock-lib",
    "//codex-rs/hepta-codex-adapter": "//codex-rs/hepta-codex-adapter:hepta-codex-adapter-qualification-clock-lib",
    "//codex-rs/hepta-cognitive-store": "//codex-rs/hepta-cognitive-store:hepta-cognitive-store-qualification-clock-lib",
    "//codex-rs/hepta-infer-worker-host": "//codex-rs/hepta-infer-worker-host:hepta-infer-worker-host-qualification-clock-lib",
    "//codex-rs/hepta-memory": "//codex-rs/hepta-memory:hepta-memory-qualification-clock-lib",
    "//codex-rs/hepta-supervisor": "//codex-rs/hepta-supervisor:hepta-supervisor-qualification-clock-lib",
}

def qualification_lease_clock_library(
        name,
        crate_name,
        compile_data = [],
        crate_features = [],
        extra_srcs = [],
        base_replacements = {}):
    """Add a distinct qualification library without mutating the normal graph."""
    if "//" + native.package_name() not in LEASE_CLOCK_TEST_DEPENDENCIES:
        fail("lease-clock variant is outside the reviewed type closure")
    if native.glob(["build.rs"], allow_empty = True):
        fail("lease-clock variant requires an explicit build-script review")
    rust_library(
        name = name + "-qualification-clock-lib",
        testonly = True,
        srcs = native.glob(
            ["src/**/*.rs"],
            exclude = DEP_DATA[native.package_name()]["binaries"].values(),
        ) + extra_srcs,
        aliases = {dep: alias for dep, alias in aliases().items() if alias == "serde_yaml"},
        compile_data = compile_data,
        crate_features = crate_features,
        crate_name = crate_name,
        crate_root = "src/lib.rs",
        edition = "2024",
        rustc_env = {"BAZEL_PACKAGE": native.package_name()},
        deps = rust_test_dependencies(base_replacements | LEASE_CLOCK_TEST_DEPENDENCIES),
        visibility = ["//visibility:public"],
    )
