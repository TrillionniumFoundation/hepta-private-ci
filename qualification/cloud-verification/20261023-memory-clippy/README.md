# Memory transaction-input Clippy integration

Exact tested source: **6a9fe952c9191dd342c9cc2e23d791cfbe8a6465**. Parent: **b6cae33e26f09474f96df5598edb59d3d74ddd69** (#3598). Tree: **99d59da60e1b778e91473136afc84fd58b1860f2**. New branch fix/cloud-memory-transaction-inputs-20261023. DRAFT / HOLD_NO_GO, no merge/deployment.

## Findings and bounded repair

The two too_many_arguments errors are not special app-server feature/test behavior: strict `-p codex-hepta-memory --lib` reproduced both on clean b6cae33e (exit101). The crate has no feature declarations and both production modules are unconditional. Adding the caller-owned SQL transaction took the internal correction and outcome append signatures to 8 arguments; public signatures need not change.

GitHub search for too_many_arguments, hepta-memory Clippy, and ExpectedMemoryRevision found an existing exact repair in #2515, commit **6e4da822b02c8ed116c38146e18ef3d5e3bb314a**, parent c7c4f9ae80e50a83c918278da3ab568aea7e8ef2. It is not an ancestor of our chain (`git merge-base --is-ancestor` exit1). All three production preimages match exactly; therefore reuse that repair rather than invent a competing architecture. No matching-chain fix was found in those bounded searches; this is not a claim that every remote branch was exhaustively searched. Donor CI is not combination evidence.

ExpectedMemoryRevision keeps the existing memory ID/expected revision together. OutcomeTransitionPolicy keeps allowed states, destination state and exact-replay flag together. Public API, SQL, ordering, caller-owned transaction, authorization checks, payload matching, state transitions and one-shot dispatch semantics are unchanged. No lint suppressions, dependency/schema/security changes. The three production postimages still exactly match donor; two existing test files add regression assertions for wrong CAS identity/stale revision rollback and exact/different payload replay.

## Exact source results

- `just test --locked -p codex-hepta-memory --lib -E 'test(cognitive_intelligence_writer_tests) | test(local_lease_outbox_tests) | test(production_writer::tests)'`: **53 passed, 226 skipped/not selected**, exit0 on clean exact SHA; exact-tests.log. This is a scoped suite, not all Memory/workspace tests. Qualification crash/reopen probe remains ignored and its child helper may return without probe environment; no physical crash/power-loss acceptance is inferred from runner count. Existing production writer one-shot/concurrent dispatch assertions ran in selected scope.
- `CARGO_INCREMENTAL=0 cargo clippy --manifest-path codex-rs/Cargo.toml --locked -p codex-hepta-memory --lib -- -D warnings`: **exit0** on clean exact SHA, exact-lib-clippy.log. This is the same library gate that reproduced the original two errors.
- `just fmt --check --base b6cae33e26f09474f96df5598edb59d3d74ddd69` and whitespace checks pass. `just fmt` applied before tests. No changes after review other than adopting the identical remote commit.
- `--all-targets` remains **failed**, final-all-targets-clippy.log: 17 existing test diagnostics, one direct SqlitePoolOptions::connect in cognitive_schema_tests.rs:10 plus 16 expect calls in production_writer test helpers. The latter region is unchanged even though an earlier production call site in that file changes. Added test assertions introduce no additional lint diagnostic. No waiver or skip added.
- Original strict app-server command on the combined production tree now passes the two Memory blockers but fails at three existing diagnostics: CognitiveExtension::new in ext/hepta-memory/src/cognitive/mod.rs:274, unused api_digest in federation.rs:864, and core/src/client.rs:3100 map_response_events with8arguments. app-server-clippy.log preserves full errors. Those unrelated files are untouched. These runs used the same final production blobs but preceded final test-only assertions; they do not establish an app-server pass.

Earlier Bedrock3/Rust250/Python54 tests belong to their own SHAs and are not transferred. No supplier requests, real credential creation, fees, deployment or model download.

## Independent review and remote identity

Independent five-file source review passed: diff SHA256 **5208c0fcc980ea34d2957c4efe6f9f97958c65d78f6514bcb0c4e0340234ffea**. Reviewer did not run Cargo; its initial report predates final test completion. Parent execution logs above supply completed results. The reviewer independently verified donor pre/postimages and unchanged semantics.

GitHub plugin fetched all five exact-source files and each full content matched local reviewed source:

| Path suffix | Git blob |
|---|---|
| cognitive_intelligence_writer.rs | c357f8e94ff6fe2f0e08d9d5cc13499e0982a6a0 |
| cognitive_intelligence_writer_tests.rs | 07f34bb77705ac7acd075cb94042948301512c4d |
| local_lease_outbox.rs | 845de6876cb9e8dfd8d20f6dc04f251f09d43391 |
| local_lease_outbox_tests.rs | b3c8193866097a4c9b06ca5661f387a51afeab37 |
| production_writer.rs | 1deb8be5206914b4ebd2bc791e13caefbf47285e |

Full remote tree equals local staged tree. Commit was fetched, compared with git diff --exit-code, then adopted using git reset --soft only after equality. Source worktree clean. Remote writes use GitHub plugin; no force push.

## Commands, dependencies and resources

Worktree /workspace/bedrock-integration. Root AGENTS.md already read; no nested Memory AGENTS. RUSTUP_HOME=/workspace/rustup, CARGO_HOME=/workspace/cargo, PATH prepended /workspace/cargo/bin, CARGO_TARGET_DIR=/workspace/target-3567, CARGO_BUILD_JOBS=3. CARGO_INCREMENTAL=0 for Clippy only. Rust/Cargo1.95.0, just1.59.0, nextest0.9.149, Linux x86_64,5CPU/about17GiB/no swap. Cargo.lock and dependency features unchanged.

```
git fetch origin 6e4da822b02c8ed116c38146e18ef3d5e3bb314a
git merge-base --is-ancestor 6e4da822 HEAD
git diff 6e4da822^ 6e4da822 -- codex-rs/hepta-memory > donor.patch
# Before applying, strict library command above reproduces 2 failures.
git apply --check donor.patch
git apply donor.patch
git apply regression.patch
just fmt
git diff HEAD --check
# Run scoped tests and strict lib/all-targets commands listed above.
CARGO_INCREMENTAL=0 cargo clippy --manifest-path codex-rs/Cargo.toml --locked -p codex-app-server --all-targets -- -D warnings
git fetch origin 6a9fe952c9191dd342c9cc2e23d791cfbe8a6465
git diff --exit-code 6a9fe952c9191dd342c9cc2e23d791cfbe8a6465
git reset --soft 6a9fe952c9191dd342c9cc2e23d791cfbe8a6465
# Repeat scoped tests and strict Memory --lib on clean exact commit.
just fmt --check --base b6cae33e26f09474f96df5598edb59d3d74ddd69
```

Disk approached2GiB free while building; deleted only three completed app-server/core/test incremental cache directories (all-0jykcihqitv2e, codex_app_server-28uovywa8n8cy, codex_core-1qj919oe1hvbs) under target-3567/debug/incremental. Reclaimed about2.4GiB; no source, binaries or evidence deleted. No running Rust process terminated.

## Configuration atomicity conclusion

Separate read-only review in config-contract-review.md finds **no established contract violation**. config/batchWrite promises atomic edits to user config file, while protocol explicitly supports successful `OkOverridden` with a file path that was written. Bedrock wrapper can turn that response into an error and cancel active login beforehand. No reviewed API promises wrapper-error rollback. Keep this observable limitation; do not label it a security vulnerability or change production semantics without a new explicit contract. Validation rejection and successful-but-overridden writes are distinct paths.

## Remaining blockers

Full strict gates remain red as detailed above; exact-head hosted CI requires new qualification. Next actions: independently assess existing matching repairs for test SQLite shim/expect helpers and extension/core lint errors, with separate review and tests, rather than widening this patch or lowering gates. Full workspace, platform matrix, external supplier execution, physical durability and production acceptance remain untested. New draft stays HOLD_NO_GO.
