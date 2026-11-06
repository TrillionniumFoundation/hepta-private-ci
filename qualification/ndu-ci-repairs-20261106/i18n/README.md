# Versioned i18n Bazel alias

Linux Bazel analysis requests the public target
`//codex-rs/third_party/i18n-config-0.4.8:i18n-config-0.4.8`, but the package
only defines `i18n-config`. This repair adds a public alias from the requested
versioned name to that existing crate target. The existing target and its
consumers remain valid.

The file exactly replays PR #4375 at
`c3b2c620f75d32f3cc5603e95a8558b8484f8c04`. Its donor preimage is identical to
the file at source commit `cb5019ae86bc52c9baff27858a3ee21cafc89ac5`.
`validation.json` records both Git blob identities and the observed failure.
No dependency version, lockfile, Rust source, test assertion, or security policy
changes. Bazel was unavailable locally, so this validates the exact replay and
the target declaration only. The native CI job must verify resolution and
expose any remaining independent failures.
