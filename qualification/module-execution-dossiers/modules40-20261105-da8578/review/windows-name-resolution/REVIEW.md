# Windows test name-resolution review

## Conclusion and scope

No blocking source defect was found in this minimal two-file patch. It resolves the names implicated by the actual Windows E0034 and E0659 diagnostics. It does not modify production implementations, assertion operands, access masks, result handling, child protocols, timeout budgets, dependencies, ignores, CI, or Bazel configuration.

The frozen preimage is commit `797116d61cf422c26274ffef31297dce84a53a80`, tree `67ce024db1679aa6cd301856ba3a694ea18bc4b6`. Both target files were independently fetched at that commit and at the executed failure source `bb55b0d7d263c396ec504c45393d938c3428dae5`; their contents and Git blobs are identical between the two commits. Every fetched target and reviewed parent blob was verified locally.

## Native HANDLE resolution

`NativeChild.child` is `std::process::Child`. The test already imports both `portable_pty::Child as _` and `std::os::windows::io::AsRawHandle`. Both traits expose an `as_raw_handle` method for `std::process::Child`, matching the actual E0034 compiler notes.

The three calls now use `AsRawHandle::as_raw_handle(&self.child)`. This explicitly selects the already imported standard Windows trait and preserves the same borrowed native process HANDLE. The `.cast()` operations, `DuplicateHandle` arguments, both `WaitForSingleObject` calls, all unsafe scopes, error branches, ownership and cleanup remain intact. One now-long match header is wrapped without an additional token change.

The portable trait import stays because the original tests also call `wait` and `try_wait` on `WinChild`; the fixed parent implements `portable_pty::Child` for that type. Removing that import would needlessly alter those method-resolution requirements.

The original five-second deadline, stdin release byte, limited-access handle tests, `ERROR_ACCESS_DENIED` checks and native exit-code-259 assertions are preserved.

## Assertion macro resolution

The immediate parent `unified_exec/tests.rs` imports `pretty_assertions::assert_eq` and declares `delete_permission_tests`. Its sibling `acl_setup_tests.rs` explicitly imports that same macro, and the crate already declares `pretty_assertions` as a development dependency.

Adding `use pretty_assertions::assert_eq;` to the child selects the original parent macro explicitly instead of leaving it to the ambiguous glob/prelude lookup. All eight `assert_eq!` invocations and the entire test body are byte-identical. The host comparison, all four delete routes, physical filesystem readback, allowed-path deletion and outside-path deletion denial checks remain unchanged. The 5000ms host wait, 5000ms sandbox timeout and ten-second output collector limit remain unchanged.

## Validation and evidence boundary

Local validation covered the exact allowed replacements, unchanged function names, string and numeric literals, assertion counts, unsafe-token count, fixed source/configuration blobs and successful `git apply --check --whitespace=error-all`. Complete postimages, source records, parent modules, file identities and the combined patch are saved alongside `manifest.json`.

The observed failures remain attached to full-ci run `42058694002`: ARM64 Clippy job `127354042203` and x64 archive job `127354042307` reported E0034; x64 Clippy job `127354042573` and ARM64 release Clippy job `127354042546` reported E0659. The latter job was still in progress at the saved observation even though its Clippy step had failed; this review does not promote it to an unobserved run/job terminal result.

No Rust/native execution, Windows compilation, formatter run, remote mutation, CI restart or cancellation was performed for this review. The original Windows checks must execute on the next actual fixed candidate. Neither prior Linux/native success nor this source review is claimed as Windows compilation success.
