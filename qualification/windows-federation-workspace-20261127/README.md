# Windows federation workspace binding

The original Windows shard at commit 124646c2baa78fd82b949b18a3423e26fd80383d
failed the unchanged `revoke_removes_prepared_federated_context_from_next_physical_send`
test at `federation.rs:1303`: no prepared authorized attachment was present.
The complete original log is retained in `../windows-shard-one-20261127/`.

Fleet `WorkspaceBinding::new` stores the filesystem-canonical workspace.
On Windows, canonicalization returns a verbatim path prefix. A `PathUri`
round trip removes that supported prefix, while the shared workspace digest
binds literal UTF-16LE path bytes. A valid registered grant therefore failed
the recall lookup before an attachment could be prepared.

The federation contributor now resolves the Windows path back to the same
registered canonical spelling at preparation and physical-send revalidation.
Missing paths fail closed; a different workspace still fails the exact
prepared-workspace check. The persistent grant format and digest are unchanged.
The original revocation test remains and now exercises URI decoding at both
boundaries, plus an explicit different-workspace rejection. Two Windows
controls cover verbatim identity recovery and missing/relative path refusal.

`just fmt` completed naturally on ROG with the pinned Rust 1.96.1 toolchain.
The focused Windows workflow runs the entire original extension unit suite
with `--nocache_test_results` and the original 60-minute budget. This commit
does not yet claim that native Windows test result or a complete matrix PASS.
