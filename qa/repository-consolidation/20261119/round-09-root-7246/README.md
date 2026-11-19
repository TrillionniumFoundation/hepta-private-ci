# Round nine: original branch merges and source repairs

This record freezes the completed root audit at commit
`ff686ea1db4cb3f3a04cdb05fc8a5a804f2a5abf`, tree
`47b88762ae4872a4f00bed704b89ecd8097fb2dc`.
It records specific source checks and their limits. It does not grant complete
CI qualification or authorize changing `main` or any protected HIA reference.

## Real ancestry and protected references

Four original ordinary tips were merged with their actual Git parents:

| Original tip | Merge commit | Original paths |
| --- | --- | ---: |
| `1ad429a13ffbda6336509f8a8a6fc63da4a1ae6c` | `f561557b0a6a0ecf622405f55231e76bccfb7097` | 1 |
| `49dc1847deced9b2cd4f2e08aaa1eb3d7ade433c` | `facac8a70329e68427aabee2912258ff9f5e86ab` | 6 |
| `68e9e6c80b9139d5a4b081e4cdd41341fc951142` | `86f8706c6fd6b22e68722cdb483d85e571ee150d` | 5 |
| `10f11a4bd1828577d7d69177ae03a27a31b8e8d8` | `44b51c01296d9ad6a235ebe2770201f31455ef9b` | 18 |

All 30 resulting original paths match their original bytes. These four merges
cover nine additional ordinary branch names. The NDU merge at
`bab7fa0df36a37a529de9d91048304478a602322` adds 17 more names through its real
`480e83532df57ec691ce70ff7ecb572717887a7e` ancestry. Its separate qualification
record is under `round-09-7246/ndu-feedback-480e`.

The independently read remote integration at 19:05:06 UTC on 2026-11-19 was
`b33751526c9c9c6158bafd3641c603c646b7da4a`, with 2,800 ordinary names covered.
The local source recorded here covers 2,826; 4,343 remain pending against that
frozen reference snapshot. `main` remains
`732e934ba496d90fbe042b8d41d479ef901643e5`. No branch was deleted.

The same remote observation contains 478 protected HIA names and 499 retained
commit pins. The external HIA a11 advance to
`01b78c489326a60f74c10a15d41c5695c2d2a827` retains its earlier `70827` parent
as a protection pin. The audit did not write either reference. The recorded
source ancestry has no protected pin intersection. The original parent graph,
incremental graph records, exact reference snapshots, and publication readback
are included as evidence. Future publication requires a fresh comparison.

## Qualification scope

| Scope | Observed result | Limit |
| --- | --- | --- |
| Memory compiler, encoder, reader originals | 11 of 11 original tests passed on native Python with Torch | Original tests use their original doubles; no model quality claim |
| Actual Rust capture | 64 compiler invocations: 24 accepted and 40 expected constraint rejections | Stored compiler outputs and source hashes verified; initial wrapper comparison failure retained |
| Original observer utility | One original test passed | No new Docker or remote execution claim |
| First hit numerical source | Five original tests passed; inverse identifier substitution preserves the AST | Only two local variable names changed |
| Infer core replay signature repair | 131 passed, eight default skips | Scoped original suite; not a complete workspace pass |
| AuthBus and supervisor repair | 57 original native tests passed with no skips | Separate source and native evidence in `round-09-ci-audit-7246` |
| Qualification error propagation | Three original tests and actual strict Clippy passed | Separate evidence in `round-09-qualification-expect-7246`; earlier outer wrapper failure retained |
| Evidence validator | 15 tests passed and all 99 registered files verified | Exact paths and digests only; original validator functions remain unchanged |

The learning workflows retain their original commands, permissions and coverage
threshold. Their pinned Rust toolchain moves from 1.95 to the workspace's 1.96.
The production AuthBus quota and recovery checks remain unchanged. Two helpers
used only by tests are gated for tests; original runtime guards are preserved.

## Spelling and original evidence

The full source scan at `89e66450318ea1a7ac5376fdaf82e4f0f1da1409` checked
51,093 eligible files in 81 batches. It failed with 62 diagnostics in two raw
archive parts. This failure is preserved. The complete five-part archive was
subsequently reconstructed and all 406 members were verified before registering
the two exact path and digest pairs. A final complete scan of the next source
candidate is still required; this record does not relabel the earlier scan.

The 48 frozen text records and 25 binary or encoded records were reviewed
individually. Of the 48, 43 match earlier original digest records; five bind to
current Git bytes and their historical contexts without claiming a separate
earlier digest manifest. The 25-file archive review checks 14 complete groups,
192 parts and 18,169 top-level members, plus seven nested ZIP archives. The
indexed replay part set remains incomplete at 11 of 87. Its independently
retained whole ZIP and the available slices were verified, while the historical
scientific hold remains in force. HTML image payloads, PDF bytes and the
embedded compressed JSON have separate custody proofs.

All original evidence bytes remain intact. The existing word list, global
ignore patterns, byte limits and validator logic are unchanged. New exact pins
are enforced by the original validation plus an additional exhaustive test
against digest changes, nearby paths and path traversal. Historical failure
logs retain their original contents.

## Remaining CI failures

The b337 architecture and Windows private-state logs record compile failures;
tests blocked by compilation are not counted as failed assertions. The Windows
AppContainer native helper and the actual command interpreter have separate
results: native helper operations passed, while command deletion and the LPAC
child path remained unsuccessful. Fixture checks do not establish production
runner equivalence. No deletion permission was broadened and no guard or test
was skipped to change those outcomes.

The next integration still needs the actual dependency alias compilation,
strict architecture lint, production app-server compilation, final source
checks, and required remote CI. The large remaining branch candidates have not
been accepted by this record.

## Reconstructing the evidence

`evidence-index.json` binds 35 independently valid gzip files. Decompress each
part in index order, then concatenate those raw bytes to obtain one TAR. The
TAR contains 789 original evidence files and `EVIDENCE_MANIFEST.json`, which
records every original relative path, byte count and SHA-256 digest.

Each stored part is below the existing 512,000-byte blob limit; no size waiver
was added. Even the original large compressed proof and complete parent graph
are preserved exactly inside this bounded representation. These are storage
chunks of already identified evidence, not rewritten execution logs.

Run `python verify_evidence.py` from this directory to validate every compressed
part, the reconstructed TAR, and every member without extracting files. A
successful result proves byte custody only. The test and CI claims remain bound
to their individual source versions and results above.
