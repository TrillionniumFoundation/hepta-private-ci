# Core Windows helper fixture layout

## Observed failure

The normal fac3 Windows main run `45600017662`, job `139157914105`,
executed `workspace_roots_allow_file_and_command_writes`. Its command
returned `orchestrator_helper_launch_failed`: setup refresh could not find
`codex-windows-sandbox-setup.exe`. The patch output also reported exit 1;
the later missing-file error is not evidence that either write succeeded.
The complete public job log has SHA-256
`9da567fccde9b5b108dab1fa8149dcea5f9d2bd171db481053e5db461865044f`.

Core already declares the actual setup and runner binaries in
`core/BUILD.bazel::extra_binaries`. Bazel makes their runfile locations
available to `codex_utils_cargo_bin`. The production setup and runner
resolvers, however, inspect `current_exe` and its adjacent
`codex-resources` directory. Configuring a different `codex_self_exe` alone
does not change that lookup in the current Core test process.

## Fixture correction

The existing helper staging in the Windows sandbox suite moves into a
Windows-only test-support module. TestCodex invokes it only when Windows
sandboxing is configured and the harness includes a local environment.
The three existing direct Windows sandbox tests reuse the same function.
The existing Bazel binary declarations suffice; dependencies and both
lockfiles remain unchanged.

Staging resolves the real binaries, publishes complete copies through a
same-directory temporary file, and verifies exact bytes. Concurrent
writers or an executable still in use are accepted only when the
destination already contains those same bytes. An unoccupied stale copy
is atomically replaced by the actual binary; an occupied wrong version
or an unreadable/non-file destination is rejected. The helper
prepares executable fixtures only: it does not invoke setup, change an
account, install an ACL, or modify a sandbox permission profile.

All workspace-roots test source and all existing Windows sandbox test
bodies remain byte-for-byte unchanged. In particular, positive writes,
negative permission checks, and expected Unsupported errors are retained.
This change does not repair or qualify the separate host DELETE
confinement defect.

## Validation boundary

`just fmt` and `git diff --check` completed successfully. The actual new
fixture module and actual cargo-bin dependency passed isolated Linux
`cargo clippy --locked --offline -- -D warnings` in 5.898 seconds; its
36 dependencies match the workspace package identities. All four edited
source hashes remained unchanged. This checks the new module's Rust
types and lints, not the full Core graph or native Windows behavior.
The original normal Windows cases remain the required runtime evidence.
