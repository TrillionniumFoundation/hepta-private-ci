# Reviewed integration of native Windows ACL changes

Base: `7880ad3fc16e0bc9724aa24bcbfdddb4e8eff576`.
Incoming PR #6396: `93dd309eb57384e655096ac34d52fabd221d7ec9` (`audit/windows-acl-native-20261115`).
This is a normal merge with both histories retained. No main protection, required gate, assertion, retry policy, or HIA ref is changed.

## Accepted implementation and conflict resolutions

- Adopt the incoming handle-based ACL repair and normalized deny evaluation (`acl.rs`, new `acl_deny.rs`), with all ten ACL methods. The no-op path opens only READ_CONTROL, and repairs compare full 128-bit file identity before using a WRITE_DAC handle. File replacement, changed target type, partial rights, scope, SID and ACE precedence remain fail-closed conditions.
- Keep the combined `token.rs` exactly as in the base. This retains the dedicated sandbox user/capability/network restrictions and excludes ambient Everyone/logon SIDs from the elevated restriction pass.
- Keep the combined `token_tests.rs` and append the incoming distinct existing-file-preservation refusal test; preserve the original native permission matrix and diagnostic tests.
- Keep the combined crate-visible snapshot helpers in `legacy_admission_tests.rs`. Keep the combined nextest comments and identical local JUnit behavior.
- Retain the combined Cargo graph, Cargo/Bazel lockfiles, runner custody and teardown implementation. The incoming narrow branch must not replace the full combined source tree.
- Rebind six source pins and the strict parsed Cargo.lock remainder digest in the incoming native workflow to the actual combined source. Size, Git blob ID, mode, SHA-256, exact HEAD, clean worktree/index, complete method inventory, zero skips/retries and unchanged postflight checks are retained.

## Observed evidence and its limits

PR #6396 native run [43777712400](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43777712400), ACL job [133007697151](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43777712400/job/133007697151), completed successfully at its exact incoming head. Artifact 14187720256 (23,474-byte ZIP, SHA-256 `50a04d15ac9713196581eba8b04391d66a27ddcf915aba37a4cb34ae32cf41fc`) was independently inspected. It contains ten distinct original ACL passes, six distinct Python integrity passes, and two native legacy admission refusals. The report explicitly says `completed_permission_cases=0`, `original_permission_invariants_observed=false`, `qualification=false`, `status=legacy_backend_refused`. It does **not** qualify elevated process isolation, and does not certify this merge head.

The combined six Python probe integrity methods passed locally, without skips, before formatting. ROG ran the repository's `just fmt` on an exact isolated snapshot of the six changed Rust files with the pinned Rust 1.96.0 toolchain and owning manifests/configuration; it returned zero and changed no source bytes. The snapshot was for formatting only and is not presented as compilation or Windows execution. Native Windows tests and scoped Clippy remain for the published combined candidate.

## Unresolved elevated safety failure

At published integration head `8576cdb382d6d49cfccb45d0b07e651fc7aa474e`, [native Windows job 132877426555](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43735547173/job/132877426555) executed the full elevated four-cell deletion matrix. Outside-root files and directories survived Neither/TargetOnly, but were actually deleted in ParentOnly/Both. The child completed all markers, exited zero, and deleted the permitted-root positive controls. This is a demonstrated boundary escape, not a spawn-fixture failure. The original assertion at `unified_exec/delete_permission_tests.rs` remains unchanged.

The ACL-only native result does not repair this `WRITE_RESTRICTED` admission defect. The immediate safety correction must refuse elevated sandbox launch and raw elevated token creation until a replacement is qualified. A functional replacement additionally needs exact native read-root, executable/DLL, IPC and four-cell delete evidence. Removing `WRITE_RESTRICTED` alone would change the read contract and is not qualified by the existing owned-object probes.
