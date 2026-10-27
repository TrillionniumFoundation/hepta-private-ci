# Native sandbox test binaries and source identity

The original elevated functional case launches the actual setup and command
runner targets. A Cargo library-only test does not build those binaries, and its
test executable resides in `dev-small/deps`, outside the installed product's
bin/resources layout. Building only the library or placing an unrelated command
on PATH cannot qualify the real child process behavior.

`windows_real_test_helpers.py` builds both declared Cargo targets with the same
locked source, pinned native compiler and dedicated target directory as the
original test scope. It records executable/tool hashes and source before/after,
then exports the two exact `CARGO_BIN_EXE_*` test inputs. A separate always-run
after check verifies those same original files and source following the tests.
Build success grants no functional qualification. Original case output, environment
forwarding, actual exit code, scopes, deadlines and zero retries remain required.

Only `cfg(test)` calls with the actual current test executable use the existing
`codex-utils-cargo-bin` Cargo/Bazel resolver for these two fixed target names.
Synthetic path/layout regression probes retain the original resolver, and all
non-test installed-product lookup behavior is unchanged. Bazel uses the macro's
`unit_test_extra_binaries` contract to expose real runfiles and executable env
inputs; runtime data alone does not establish their paths.

This change does not relax legacy workspace or readonly refusal. Existing
ambient-ACL/parent-delete failures remain visible until real isolation and the
original assertions have been executed successfully. It does not change signer
authority, SSHSIG verification, the original 91-case driver or its scope file.
