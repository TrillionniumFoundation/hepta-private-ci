# CI source classification, workflow references and Clippy selection

This packet preserves three concrete #5136 CI failures, their source-bound
repairs and the actual checks available at the fixed snapshot. CI32 correctly
classifies Starlark inputs without altering the two original frozen JSON files.
CI33 checks workflow paths against the repository namespace encoded in a complete
reference, while retaining checks for local, relative, partial and URL references.
CI34 obtains the complete original manual Rust-test candidate set before target
configuration analysis, so unrelated release targets do not enter that analysis.
Every selected test remains represented, including failing dependencies.

The local evidence includes 35 formatter scope tests, 16 canonical checker tests,
57 full wrapper tests, 11 real Bazel configuration/analysis commands and two real
Bazel serialization commands. All final test methods ran without skips. Original
fixture setup failures and the first candidate's URL-query counterexample remain
separate original records. No failed output was overwritten to create a pass.
The Bazel fixture runs use Linux and explicit synthetic platforms. The special
label probe also records its four-flag fixture adapter; it is not a native MSVC
Clippy run.

Native evidence is recorded independently. The #5147 job actually passed its
original `just fmt-check` step and clean-worktree check. The #5154 canonical job
actually passed `verify --profile development`, reporting
`PASS_HEPTA_DEVELOPMENT_DOCS_V8`. Its original readiness/reference gap counts and
`historicalEvidenceRevalidated=false` are retained. This is not qualification
profile execution or external signer attestation. The native formatting log does
not enumerate its 237 buildifier inputs; that exact count comes from the separate
local replay of the original 239 arguments.

The #5165 Windows Clippy job was still running at this packet's snapshot. Neither
its terminal result nor repository-wide green status is inferred. All source,
actual merge and tree identities remain associated with their own job records.

Run `python3 -O -B restore.py /absolute/empty/directory` to verify and restore the
complete retained inventory as inert regular files. The reader executes no
archived sources. Recorded validation scripts use their original workspace paths;
they are not represented as directly runnable after arbitrary relocation. Raw
commands, original inputs, stdout and stderr remain available for inspection.

The INDEX records original modes, including executable shell sources and private
raw logs. Restored files deliberately use mode 0644. Each independent bounded gzip
member wraps one exact XZ segment; no new spelling exclusion was introduced.
Compiled tools, caches, private Git indexes and redundant patch-replay output are
excluded explicitly. Existing evidence packets and frozen receipts are unchanged.
