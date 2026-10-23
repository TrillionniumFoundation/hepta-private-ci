# Independent source review — FinalUse follow-up

Reviewed base: `2f7ae91c4176896d0b9caf9aea75ed3e030a81f8`.
Reviewed working-tree diff SHA-256: `65699b27aa19d0c4e302a40da1ace657d47e3b6bca15e460afedd7ea2587e8db`.
Recorded UTC: 2026-10-23T16:01:47.677483+00:00.
16 tracked paths reviewed. Exact per-file hashes: independent-review-source-manifest.json. This review is bound to these bytes, not to a later edited tree.

## Conclusion

No blocking source defect found in the reviewed change. The FinalUse storage patch closes the reproduced live length-drift admission hole without relaxing grant/signature/frontier/nonce rules. The execution-core fix corrects the assertion to the existing rejection contract and adds a separate stricter missing-grant regression. Proceed to the parent's exact-source scoped Rust/Clippy/Python checks and remote verification; this source review alone does not certify those executions, full CI or production Runtime acceptance.

## Production storage change

- `codex-rs/hepta-contracts/src/final_use_store.rs:293` compares the opened journal's end with the last validated length before writing. A truncate or unexpected extension returns Unavailable; `final_use.rs`'s unchanged append-failure path marks state.failed. No token is returned on this failure.
- `final_use_store.rs:355` initializes length from successfully parsed bytes, not from the current epoch's nonce count. This is essential when a crash leaves valid previous-epoch frames after the newer snapshot.
- `final_use_store.rs:303` updates length only after the entire append and sync_all succeed. Partial write/sync errors leave the owner fenced through the existing authority mutex/state path.
- `final_use_store.rs:382` updates length only after replacement file sync, rename and directory sync. Fresh stores and legacy snapshot migrations both call this path; current-schema reopens call read_claims. Failed opens discard the partially initialized Store.
- AtomicU64 Relaxed is appropriate here: authority state Mutex provides operational serialization; the atomic preserves shared Store thread-safety rather than claiming a filesystem transaction. No schema or record encoding change is introduced.

## Regression and migration audit

The previously unattached nonce tests targeted an incompatible 80-byte `authority.nonces` checksum/revision protocol. The actual product module owns 40-byte `authority.claims` epoch+nonce frames. Connecting the old parser directly would have tested or changed a different storage format.

The reviewed module is now attached under `final_use::tests::nonce_tests` (existing Unix/test gate). Nine active regressions cover: 32 fixed-frame claims and reopen replay rejection; missing file; live truncation at 0/39 bytes; unexpected growth to 41/80 bytes; old same-epoch log after revocation snapshot; old-epoch residual log followed by a valid new-epoch append/reopen; strict torn-tail rejection on repeated reopen without disk rewrite; invalid epoch frames; and external-frontier rejection of aligned loss or same-length altered nonce, with partial-tail rejection earlier in parsing.

The original live-truncation failure is retained in nonce-before.log: expecting an error instead observed a VerifiedUseToken. The new helper's Result/? rewrite and `err() == Some(Unavailable)` comparisons are exact rejection assertions; Ok maps to None and still fails. They do not broaden accepted errors.

Migration mapping NONCE-MIGRATION.md was checked against the source. Existing live Store tests already cover actual schema1 single-key/schema2 key-ring migration preserving claims, appending and reopening, plus trust/exact-head mismatch. The old schema4, checksum/revision parser and reopen-compaction assertions are inapplicable to the current product format; the new tests do not pretend those mechanisms exist. Key-ring migration plus external frontier is supported by the existing composed paths, not newly claimed as an independently executed dedicated test in this change.

## execution-core and lint changes

- `execution-core/src/journal.rs:86` already rejects a previously Verified FinalUse witness being changed or downgraded before start authorization. The old fixture had a Verified intent/reservation and then removed the witness. Exact Binding error is therefore the correct existing contract; production authorization ordering is unchanged.
- `execution-core/src/journal_tests.rs:150` now asserts that exact rejection and unchanged journal; the stale start still requires exact AuthorizationDenied and unchanged journal.
- The new missing-FinalUse test starts with NotGranted throughout, checks exact AuthorizationDenied, and uses a verifier that panics if called. This distinguishes genuinely absent authority from a downgrade, and ensures missing grants cannot reach host verification.
- Removing an unused import, moving the last-use operation_id String instead of cloning, and using slice::from_ref in two read-only test verifier calls are mechanical. Rustfmt line wrapping does not change the transition matrix or authorization checks.

## Independent Python check

Independently loaded all nine Python files from git HEAD and current disk. Converted only assignment-to-lambda nodes to equivalent FunctionDef/Return nodes for comparison, then compared complete AST dumps without locations. All nine match. The only conversions are local test fixture functions `h` and `digest`; seven files are AST-identical without any conversion. Results saved in independent-python-ast.json. These fixtures do not introspect lambda names or function identity. `git diff --check` also passed.

## Explicit limitations, not waived

The length check does not detect same-size overwrite, same-size file replacement or hostile concurrent mutation after the check. Independent frontier remains necessary for strong antirollback; this patch does not make the legacy no-frontier constructor equivalent to protected production custody. Local filesystem tests do not simulate hardware power loss. The in-memory execution journal remains non-durable and non-executing. No new effect dispatch, issuer, production credential, security setting, deployment or merge authority is introduced.

This independent review did not run Cargo concurrently with the parent's validation. It inspected existing before/after evidence without attributing those executions to itself. Parent must record completed command results and exact published SHA separately.
