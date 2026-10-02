# Windows retained-file identity and input admission

Published source: `6e76bb778b58abe557dca516fe66da020da84ae6`, tree `5f3b98aecf7c3fa688f8093a275fe8fba855ffef`. It matches the complete tree of local
source commit `9ac6b9bd0a95aa72965bcc7b984e60b549c85a0a`. Exact qualification base
remains `978c1923eda66373e9dce4fe0efa890bc60ac404`.

## Exact historical findings

[Run 36983477130](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/36983477130)
executed candidate `931f096be5bd21370a72a1126c6c38b954314d95` with frozen source
`bdedf9e7cd3ddb0bb6457704940910cadb4cef1a`. Its [job/artifact record](historical-run.json) shows Linux head/merge,
storage and macOS head success; Windows head/merge, macOS merge and aggregate
failed. These remain old-source observations.

Windows formatting/lint and the bounded-diagnostic regression passed. All three
registrar fixture failures were specifically `registrar persisted target path
mismatch (0x80004005)`, rather than a COM API call failure. The log does not reveal
which path normalization occurred. macOS merge failed in TemporaryDirectory
cleanup with `Directory not empty` on the disposable `.git` directory, without
an observed source-inventory assertion failure. The exact cause is unproven.
The fixture now disables automatic maintenance only in its disposable repository;
cleanup errors and assertions remain enforced. [Retained logs](retained-logs.zip)
keep the original Windows and macOS records byte-for-byte.

## Reviewed source policy

The expected executable is opened before save and retained through readback, with
read sharing only. The observed target is opened without following its final
reparse point; both opened handles must be regular non-reparse files. Equality
uses the entire `FILE_ID_INFO`: volume serial plus the full 128-bit identifier.
No case folding or string-only equivalence can admit a target. This follows the
[Windows file-ID contract](https://learn.microsoft.com/en-us/windows/win32/api/winbase/ns-winbase-file_id_info).

Because [alternate streams](https://learn.microsoft.com/en-us/windows/win32/fileio/file-streams)
can contain different bytes within one base file, both expected and observed
paths reject stream separators before any filesystem call. Only absolute disk
or UNC prefixes, including their corresponding verbatim forms, are admitted;
device namespaces and arbitrary verbatim/GLOBALROOT prefixes are rejected.
Parent directories are not sandboxed. Unsupported identity queries fail closed.

Mandatory regressions cover distinct case/hard-link aliases of one file,
different files, wrong AUMID, reparse targets, retained-handle write/delete/rename
denial, real ADS byte divergence, and default-stream/namespace admission.
The new destination hard-link audit requires preservation of the other fixture's
bytes and unchanged shortcut bytes on rejection. On successful Save it requires
a distinct shortcut file identity. This is an unexecuted test, not evidence of a
vulnerability or of atomic replacement; production destination-write policy has
not been changed speculatively.

A distinct 8.3 alias is tested when supplied by the filesystem. Otherwise the
nocapture log explicitly says `UNEXERCISED`; that coverage is never inferred from
a passing test count. No privilege or volume setting is changed.

## Local verification and pending execution

[Diagnostic binding](diagnostic-binding.json) records strict Windows GNU-target
Clippy for all platform-adapter targets, 17 workflow tests and complete formatting
of 443 Cargo targets in three batches. `just fmt` succeeded; 54 unrelated baseline
format changes were restored. The initial shared temporary Python environment
collision was resolved by using each project's own environment. New Windows
regressions are compiled only; no Windows runtime exists locally.

An early Windows adapter-only step now produces separate exact-source evidence
before the full application build. It preserves failure exit codes and never
substitutes for original full-suite/matrix/aggregate checks. All original workflow
text outside that additive step is unchanged.

[Frozen inventory](implementation-inventory.json): 455 Git blobs over
33 selection paths; digest `f5fe232dc844bd843bbdb85ca1e7bbb8e16ae905442c87b62deaa00b5a01f6d4`. Seven current anchors agree.
Historical records and all compiled storage-budget semantics are retained.
Fresh six-platform head/ordered-merge, release storage, package and aggregate
execution remains required, along with physical/signing/independent acceptance.
Production, deployment and release flags remain false.

## Metadata validation

[Local metadata checks](metadata-checks.json) passed 268 native Python cases with
one Windows-only NTFS skip, seven projection tests, four registry tests, the
native v6 map adapter and structural source guard. Projection verification made
no generated changes. Prior nested records and retained historical files were
compared with the published source and preserved exactly. Storage budget semantics
are unchanged. These checks observed the uncommitted metadata continuation and
are not final hosted-candidate qualification.
