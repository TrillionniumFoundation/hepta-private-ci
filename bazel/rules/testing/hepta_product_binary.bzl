"""Ordinary product artifacts and process harnesses using the Cargo product profile."""

_EXTRA_RUSTC_FLAGS = "@rules_rust//rust/settings:extra_rustc_flags"
_LTO = "@rules_rust//rust/settings:lto"
_CODEGEN_UNITS = "@rules_rust//rust/settings:codegen_units"
_PRODUCT_FLAGS = [
    "-Copt-level=2",
    "-Cdebug-assertions=yes",
    "-Coverflow-checks=yes",
    "-Cdebuginfo=0",
    "-Cstrip=symbols",
]

def _product_transition_impl(settings, _attr):
    flags = settings[_EXTRA_RUSTC_FLAGS]

    # A product harness can depend on a product program. Preserve one identical
    # configuration instead of appending flags at every nested transition.
    if flags[-len(_PRODUCT_FLAGS):] != _PRODUCT_FLAGS:
        flags = flags + _PRODUCT_FLAGS
    return {
        "//command_line_option:compilation_mode": "opt",
        _EXTRA_RUSTC_FLAGS: flags,
        _LTO: "off",
        _CODEGEN_UNITS: 4,
    }

_product_transition = transition(
    implementation = _product_transition_impl,
    inputs = [_EXTRA_RUSTC_FLAGS],
    outputs = [
        "//command_line_option:compilation_mode",
        _EXTRA_RUSTC_FLAGS,
        _LTO,
        _CODEGEN_UNITS,
    ],
)

def _product_binary_impl(ctx):
    if len(ctx.attr.binary) != 1:
        fail("expected exactly one product binary")
    binary = ctx.attr.binary[0][DefaultInfo]
    runfiles = ctx.runfiles(transitive_files = binary.files).merge(binary.default_runfiles)
    if not ctx.attr._harness:
        # Forward the actual rust_binary file, not an installation symlink.
        return [DefaultInfo(files = binary.files, runfiles = runfiles)]
    executable = binary.files_to_run.executable
    if executable == None:
        fail("product harness must provide an executable")
    output = ctx.actions.declare_file(ctx.label.name + (".exe" if executable.basename.endswith(".exe") else ""))
    ctx.actions.symlink(output = output, target_file = executable, is_executable = True)
    return [DefaultInfo(files = depset([output]), executable = output, runfiles = runfiles)]

def _product_attrs(harness):
    return {
        "binary": attr.label(cfg = _product_transition, executable = True, mandatory = True),
        "_harness": attr.bool(default = harness),
        "_allowlist_function_transition": attr.label(
            default = "@bazel_tools//tools/allowlists/function_transition_allowlist",
        ),
    }

hepta_product_binary = rule(
    implementation = _product_binary_impl,
    attrs = _product_attrs(False),
    doc = "Exposes a normal product program built with the complete optimized production closure.",
)

hepta_product_test_binary = rule(
    implementation = _product_binary_impl,
    attrs = _product_attrs(True),
    executable = True,
    doc = "Builds a process acceptance harness with the same product dependency profile.",
)
