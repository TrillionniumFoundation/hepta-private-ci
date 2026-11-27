# Windows legacy sandbox: exact 53b read-only audit

## Result
The failing positive test requests a backend that the current product deliberately refuses before native sandbox preparation. The observed error is a fixed admission error, not the result of inspecting this test's parent-directory ACL. Changing the TempDir ACL cannot make this exact RestrictedToken request succeed while preserving the admission gate.

Source: 53b3227a8dff5af9e39ecef6356cfce702d80b1c, tree 10cb49cee9c3ca8ed280a680fb262c7e7ce549a1. CI checkout 7302b0d4d0cd9335c9c505db7995689e8dc9f9c8 has the same tree. This audit performs no test, actor, ACL edit, source edit, or retry.

## Original execution evidence
Run 43297579660 / job 131460490666: the exec_process target announced 24 methods and ended with 2 passed, 1 failed, 21 ignored, 0 filtered. The failing method is remote_windows_sandbox_process_accepts_process_write. Its original RPC error is -32603 with LegacyWindowsSandboxIsolationUnavailable's exact display text. The complete log is 400068 bytes, SHA256 d86655c3fb41c8658b4d65d41d8e1d7b1331de560ae89c207dfa6d4ee1038e6a; contiguous parts are d4a24b7bf7fb9e51984cb8fd1dafb2c2d617cd3b and f19b1d673b80b0c791aeb59bf615f272ff7ffe84.

The outer Bazel summary is 35 executed out of 144 targets, 92 target passes, 1 failure, 51 skipped. It includes cached targets. The later repeated failure block is the workflow's diagnostic log replay, not another independent sample. This audit does not convert target counts to fresh method counts.

## Source trace
1. exec-server/tests/exec_process.rs, assert_remote_windows_sandbox_process_write (lines 1181-1238): starts the real remote harness, creates TempDir, selects legacy ReadOnly and RestrictedToken, and expects backend.start to return a session. It then expects stdin Accepted, output hello, exit 0, closed, and blocked.txt absent. It neither sets nor measures a parent DACL.
2. exec-server/src/process_sandbox.rs keeps the requested windows_sandbox_level when preparing the native request (lines 251-281). It does not substitute a qualified backend for the caller.
3. exec-server/src/local_process.rs calls codex_sandboxing::spawn_process (lines 433-453); an error is returned through internal_error(err.to_string()). Its generic custody path already begins an effect reservation and marks the reservation unknown on a backend error. The audit does not change or reinterpret this upstream custody state.
4. sandboxing/src/spawn.rs (lines 42-86) passes the same level, policy, roots, cwd, and stdin flag to spawn_windows_sandbox_session_for_level.
5. windows-sandbox-rs/src/unified_exec/mod.rs (lines 103-118) calls require_legacy_filesystem_isolation immediately for RestrictedToken, before select_windows_sandbox_backend. Explicit Elevated is a separate entry with distinct identity and qualification requirements; Disabled is rejected by this API.
6. windows-sandbox-rs/src/legacy_admission.rs (lines 26-28) unconditionally returns Err(LegacyWindowsSandboxIsolationUnavailable.into()). There are no path, ACL, token, platform-probe, or environment parameters in this function. Its display text states the known ambient FILE_DELETE_CHILD risk; the message is not an observation of this run's DACL.
7. Existing legacy_admission_tests.rs already checks typed refusal for public RestrictedToken calls, including ReadOnly, write roots, read roots, and deny overrides, with unchanged tree bytes/DACLs and absent process/home markers. Those are source-level regression intentions, not newly executed evidence in this audit.

## Determinate defect versus unobserved environment
- Determinate: this positive test's selected backend and successful-launch expectation contradict the current unconditional fail-closed admission contract.
- Determinate: ACL-only fixture hardening cannot fix the contradiction. There is no conditional branch that such hardening can satisfy.
- Unobserved: the actual parent ACL, token access matrix, and whether a separately provisioned explicit Elevated backend could satisfy the positive stdin plus readonly contract on this runner. The supplied log contains no such qualification evidence.
- The gate's rationale refers to native deletion regressions, but this audit does not claim to have rerun or independently reproduced those regressions.
- The refusal occurs before token/capability/ACL/child operations in the sandbox backend. It does not imply that upstream RPC/custody bookkeeping had no effect.

## Minimal safe follow-up boundary
There is no safe success-preserving fixture-only patch for this exact request under the current source contract. Do not remove the isolation gate, change WRITE_RESTRICTED to mask the failure, switch silently to unsandboxed/Disabled/Elevated, alter global runner ACLs, skip the method, or count an expected refusal as proof of the original positive capability.

A narrowly scoped remote integration regression can explicitly check that the requested legacy backend's refusal reaches the RPC boundary before child launch and that the supplied sentinel/readonly contents are unchanged. That would validate refusal propagation; it must be named and counted as that purpose and must not erase the unresolved positive stdin-and-isolation requirement.

Restoring the original positive capability needs a separately qualified backend with explicit configuration and its actual native identity/provisioning evidence, preserving all original positive assertions plus adversarial deletion/read checks. Merely changing the enum to Elevated or hardening one TempDir is insufficient evidence. No implementation or dispatch is proposed as already authorized by this read-only audit.

## Verification scope
All 11 listed source blobs were fetched from exact 53b directory entries and their Git/SHA256 identities recomputed. The original first failure block is copied byte-for-byte from the complete archived log. Source review only; no formatting, compilation, or native test result is claimed.
