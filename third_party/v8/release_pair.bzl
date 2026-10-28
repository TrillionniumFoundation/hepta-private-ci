"""Build the named release archive/binding pairs in the optimized configuration."""

def _release_configuration_impl(_settings, _attr):
    return {"//command_line_option:compilation_mode": "opt"}

_release_configuration = transition(
    implementation = _release_configuration_impl,
    inputs = [],
    outputs = ["//command_line_option:compilation_mode"],
)

def _release_pair_impl(ctx):
    files = depset(transitive = [src[DefaultInfo].files for src in ctx.attr.srcs])
    return [DefaultInfo(
        files = files,
        runfiles = ctx.runfiles(transitive_files = files),
    )]

# A release pair must retain its release configuration when the caller uses
# Bazel's default fastbuild mode. Preserve the requested platform and V8 flags;
# the ordinary consumer aliases continue to use the caller's configuration.
rusty_v8_release_pair = rule(
    implementation = _release_pair_impl,
    attrs = {
        "srcs": attr.label_list(
            allow_files = True,
            cfg = _release_configuration,
        ),
        "_allowlist_function_transition": attr.label(
            default = "@bazel_tools//tools/allowlists/function_transition_allowlist",
        ),
    },
)
