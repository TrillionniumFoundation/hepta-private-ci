# Production composition evidence scope

The source stack is based on Hepta #3383 head
`507b46749dea0cece820c4997208f20464362d75`.

`protected-authority-final-byte-tests.json` and
`protected-authority-final-byte-clippy.json` are raw local command receipts.
Five protected-authority tests passed, seven prior issuer tests were filtered,
and Clippy passed with warnings denied. Before/after hashes bind the executed
`production_authority.rs` and its tests to the final source bytes.

The isolated harness uses original contracts Rust source and the exact harness
lock listed in `final-source-identity.json`. The lock contains 77 registry
entries, of which 32 differ from the original workspace resolution. Exact local
harness inputs, including Cargo.lock, are preserved in
`isolated-authority-harness.json`; absolute local path directives identify the
verified source inputs and need relocation when reproducing elsewhere.

`original-package-final-attempt.json` records the attempted original Agentd
test command. It failed before compilation on a missing `aws-auth/Cargo.toml`
workspace member. No local factory, wrapped live verifier, SQLite writer,
Tokio worker, Notes handoff, or original-package test pass is claimed.
The seven generic composition tests and five Notes handoff tests require the
actual original owning-package CI gate. Queued/pending/skipped CI is not a pass.

`final-source-identity.json` also records fixed preimages/final file identities,
original contracts blob hashes, toolchain, harness inputs, raw receipt hashes,
format verification and local scope selection. Source-only scope is native
true, derived false, full_repo false. Adding these JSON evidence files selects
derived checks too; it does not turn the isolated run into a package run.

The tests use explicit qualification fixtures. They do not supply deployed
issuer support, production keys/clocks/frontiers/revocation/current-cut inputs,
real device acceptance, or permission to use fixture authority in production.
