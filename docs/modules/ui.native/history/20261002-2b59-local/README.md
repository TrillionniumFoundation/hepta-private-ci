# Prepublication native diagnostics retained with the 2b59 source freeze

Published implementation: `2b59c1c5f877432a557185efd77331ae1143ae42`, tree
`9326a46a71a3f7aae14481d979cd3faee1935e7c`. The exact continuation parent is
`978c1923eda66373e9dce4fe0efa890bc60ac404`.

[The binding record](diagnostic-binding.json) retains byte counts and SHA-256
digests for the original logs and validator summary. The ordinary Linux tests
ran before final mechanical formatting. The compiler-negative test ran on local
commit `ad84ac978cb9717a32d69373101eced53096d3c9`; its source identity remains in
the original log. Exact Git comparison proves the selected product blobs of that
local commit equal the published implementation. This establishes a source
relationship, not execution of the final hosted candidate or merge subjects.

Observed local diagnostics: 278 native tests passed with four independently
selected entries skipped, 214 owner tests passed, three actual E0603 boundary
cases passed, and strict native Linux/Windows GNU/macOS ARM64 compilation checks
passed. Cross-target compilation did not execute Windows or macOS APIs. The
validator summary also scopes the earlier virtual raster and ordinary startup
observations; those earlier binaries are not relabeled as final-source results.

[The exact implementation inventory](implementation-inventory.json) lists 455
Git blobs selected through 33 paths, including native platform adapters and the
compiled storage budgets. Its canonical path-map SHA-256 is
`e9055dd142615e91f704feb5e57d64c9fd4176aa6b1145afa343154dfdcb09fd`.
The inventory describes the published implementation before the metadata-only
budget source-anchor update; all storage budget semantics remain unchanged.

Fresh six-platform head/merge execution, release storage measurements and strict
same-run aggregation remain pending. Physical OS/accessibility/IME behavior,
signing, independent acceptance, separate `ui.control` Rust migration and
current-main integration remain open. No production, deployment or release
authorization is asserted here.

[Metadata validation](metadata-checks.json) records 262 passing native Python
cases with one Windows-only skip, seven projection tests, four registry tests
and a structural source pass. It also retains the initial failed run: the isolated
map-adapter fixture lacked the new required Rust module files. Populating the
fixture and its platform dependency restores all intended assertions without
weakening the production guard. These are local metadata/tooling checks, not the
hosted platform and storage qualification.
