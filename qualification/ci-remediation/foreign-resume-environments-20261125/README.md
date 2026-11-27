# Preserve explicit executor selections across the suspension fixture

The complete GNU Wine-exec shard for source
`4be2e45d4c90fe539abf61814fa9b362d8922881` failed
`root_turn_suspension_preserves_unfinished_turn_history`. The original
14,309-byte log has SHA-256
`67705786fbf694d282c512e669142f89d319530907b1c547e91d307a3761e73a`.
Its retained recovery diagnostics identify exactly `workspace_roots` as the
unequal reference-context field, followed by `RecoveryStateChanged`.

The ordinary Wine test startup supplies a target-native environment selection.
The old resume fixture retained the original Config but used the default resume
entry, which reconstructs selections from host-shaped configuration paths.
That does not reproduce the original Windows path convention and workspace
roots. The strict recovery comparison correctly rejects the changed context.
The same case passing on a native Linux executor does not qualify Wine-exec.

The explicit-environment resume fixture now takes the complete selections
captured from the original thread before suspension. A new manager reads the
persisted history from its ThreadStore with the same path, archived-history
handling, and full-history requirement used by the existing resume API. It
passes that history and the retained selections through the existing
`resume_thread_with_history_and_environments` entry. The integration test
compares the entire restored selection vector before calling recovery.

The original durable Ready check, descendant-live rejection, descendant removal,
independent-manager assertions, exact turn ID, unfinished history, completion,
and single initial and resumed provider-request counts remain. The production
reference-context, environment digest, epoch, and authority comparisons are
unchanged. No retry, timeout, permission profile, or sandbox setting is relaxed.
The regular resume entry is retained. The explicit-environment fixture rejects
unsupported shell overrides and clears its private temporary selection on
normal completion and preparation errors after environment selection.

The test-support crate declares its direct workspace history dependency. Cargo
and Bazel lock generation belongs to the integration step; native qualification
must use the resulting locked source. No new external package is required.
Formatting and source review are not execution evidence: the cross-environment
regression still requires the original native CI lane.
