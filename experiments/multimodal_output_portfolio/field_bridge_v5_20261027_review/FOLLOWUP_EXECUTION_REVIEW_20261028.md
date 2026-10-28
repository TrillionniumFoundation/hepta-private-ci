# V5 follow-up: engineering repair and bounded dispatch diagnosis

This is an additive, postexecution review prepared for publication after registration
commit `8e09fee8a59f2de40acbb2595f01f648fe8b1ed8`. It does not replace the frozen
V5 audit, the original blocker ledger, or either preregistered diagnostic.

**The fixed-input diagnostic and local evidence preservation are complete. V5
remains REJECTED, the historical exact-regression gate remains FAIL, and
`admission=false`. All original substantive blockers are not closed.** New-head
Rust compilation and CI results are still pending at this publication snapshot.

## Engineering changes ready for CI

The first five reviewable stages and exact identities of their 20 source files are in
[ENGINEERING_STAGES.json](ci_repair_20261028/ENGINEERING_STAGES.json).
The final eight engineering stages and all 28 exact source identities after the
last formatter run are bound in
[PUBLICATION_FINAL_ENGINEERING.json](ci_repair_20261028/PUBLICATION_FINAL_ENGINEERING.json).

| Stage | Commit | Change and validation boundary |
| --- | --- | --- |
| Historical/platform fixtures | `1acb7db945a4fe1a98a47eae696851ca309023fa` | Use the actual v1 SQLite migration and checksum, preserve current migration checks, provide Bazel compile data, use the repository SQLite shim and portable absolute temporary paths, and separate issuer/global outbox capacity fixtures. |
| cargo-deny diagnostics | `3022fba4ffed1093138c6cc7cc8c9a167820ffa2` | Keep the canonical gate unchanged; collect a bounded, identity-bound host diagnostic only after canonical failure. Eight Python boundary tests pass. This is observability, not a cargo-deny fix or equivalent qualification run. |
| Terminal publication | `31a8c37a9442f56b7bb9c0699d3f4f0e61de3722` | Persist and flush terminal work, finish old-owner cleanup, then retire the exact owner and publish synchronously under the admission locks. Covers normal completion, running abort and prestart abort. |
| Deterministic terminal tests | `b2ce4d9e9e8ca6c0adc7e6ec6592f5bfb4ac9fec` | Add flush/publication gates, exact completion identity and duplicate-publication checks, cancellation coverage, and an immediate-next-turn public integration test. Source review is complete; these Rust tests have not yet executed locally. |
| Writable flush fixture | `d5ee6a28e66d54775af86f8681accb447dcff229` | Open the copied SQLite file for read and write before `sync_all`, retaining all tamper assertions. |

Independent static review found no additional blocking issue in the terminal
change. Actual `just fmt` and `git diff --check` pass. The v1 migration has an
independent SQLite replay through all 18 later migrations, retaining the task and
expected lifecycle state. That check is not a Rust integration-test result.

Local dependency resolution previously failed with ENOSPC. No Rust compilation,
Clippy completion, or runtime-test pass is claimed. The new CI run must validate
the published tree. No Cargo lockfile, dependency policy, production owner ACL,
Windows directory-durability requirement, or scientific admission rule changed.

An additional production recovery fix at
`a4e900d0594329a033c577da639cfcb6fbc2a701` preserves a candidate and all sidecars
when resolving the active pointer fails. It returns Indeterminate with both
errors instead of treating unknown state as proof of nonpublication. An outer
Arc retains the exclusive file fence until reconciliation completes; a successful
store clones the same guard. Known-unpublished cleanup remains. Two focused
regression tests cover a genuinely corrupt pointer with exact file-tree
preservation and known-unpublished cleanup, while the existing recovery/fence
coverage is retained. This small fix has independent static review, not a new
native execution result.
The independent recovery review is retained in
[COGNITIVE_RECOVERY_INDEPENDENT_REVIEW.json](ci_repair_20261028/COGNITIVE_RECOVERY_INDEPENDENT_REVIEW.json).

The earlier delivery head `5b7bef4e5788f2cea2546f0cb620af471b4fbcf7` ended with
44 checks: 21 success, 7 failure, 10 cancelled and 6 skipped. Actual base-run logs
and delivery logs contain the same 63 platform failures when compared by test,
source location and first panic; their entire `codex-rs` tree was identical.
Additional bounded fixes address the 19 consumer directory-handle fixtures
(commit `a84b81d8318c0b0d6686cb94a106e4d0cf6464b9`) and one non-Unix
negative test that previously failed during unrelated runtime initialization
(commit `14a2494ad613a3dd798af3bd166cb27e5faa4f6f`). The former reuses the
existing ledger fixture's Windows read/write directory handle construction;
root independently verified the saved Windows target-level ledger PASS log.
Production directory checks and real synchronization still run. The latter
now calls the real unsupported-platform refusal API and retains its exact
error and no-created-file assertions.

The post-rename negative test now proves the real active pointer changed before
exercising reconciliation, while retaining its original Indeterminate and
candidate-preservation assertions. These fixes do not close the remaining
41 positive tests blocked by the unimplemented non-Unix private owner profile.
No tests are skipped or converted to early-success returns. Consumer Windows
execution remains pending; successful directory-handle construction is not a
power-loss durability certificate. The original active-pointer failure's
specific suboperation remains unresolved; an assertion label alone does not
establish that rename failed.

## Two separately registered diagnostics

The first diagnostic was registered at
`57a42933da685425fc714eb9b45cb3cb08f2f77a`. Its DEFAULT case failed reconstructed
input identity before any recorded forward call, so its overall diagnostic is
incomplete and uninterpretable. The original failure is retained. Its actual
cost was 80 generator and 320 observer calls; the exact failed tensor identity
was not retained, so its cause is not assigned to RNG or normalization.

The second diagnostic was independently reviewed and registered at
`8e09fee8a59f2de40acbb2595f01f648fe8b1ed8` before execution. It prepares the inputs
once under unset dispatch, then reads that same immutable snapshot in all five
cases. It is a fixed-input computational intervention, not an end-to-end replay
of each capability's original random-input generation.

Its 20 NPZ input snapshots contain 140 numeric arrays with 49,520,640 bytes of
numeric payload. Both unset controls pass all 160 original-forward bitwise
parity comparisons. Both unset raw/components/forward-field files are byte
identical; unset also reproduces the current V5 raw and first diagnostic's unset
raw/components exactly. All five cases complete. Costs are exactly 140
generator and 400 observer calls, including the original-forward controls.
Preparation has zero neural-model calls. The two diagnostics together cost
220 generator and 720 observer calls, with no training or new holdout access.

The independent postexecution review verifies all 36 input bindings, 64 frozen
scientific sources, six registered diagnostic source blobs, raw identities,
snapshots, resource counters and arithmetic. See
[EXECUTION_REVIEW.md](historical_fixed_inputs_20261028/EXECUTION_REVIEW.md) and
[EXECUTION_REVIEW.json](historical_fixed_inputs_20261028/EXECUTION_REVIEW.json).

| Capability | Utility differences from current V5: task / clean | Differences from historical: task / clean | Historical raw identity match |
| --- | ---: | ---: | --- |
| unset before | 0 / 0 | 24 / 4 | None |
| DEFAULT | 26 / 2 | 34 / 6 | None |
| AVX2 | 28 / 2 | 36 / 6 | None |
| AVX512 | 0 / 0 | 24 / 4 | None |
| unset after | 0 / 0 | 24 / 4 | None |

These are utility scalar counts across both observers, not independent sample
counts. DEFAULT changes 13 task pixels and one clean pixel relative to unset;
AVX2 changes 14 task pixels and one clean pixel. Every changed pixel differs by
one integer level. Captions and discrete observer primitives remain identical.
All 2,560 row-level logits/probability hashes change under DEFAULT and AVX2.

With current uint8 pixels and targets fixed, the entire dequantization-to-MSE
path is identical across all five capabilities. Exact utility reconstruction
equals current V5, retaining 24 task and four clean historical differences.
Thus this intervention demonstrates dispatch sensitivity of logits and a few
quantized pixels, but it does not recover the old raw bytes, reproduce the old
utility vectors, or identify the historical machine or cause. No capability is
selected and no tolerance or original exact gate is changed. The scope is
seed17, frozen original action0 on the current host; it does not close seed29,
seed43 or learned ordinary48 regression.

The original V5 audit SHA remains
`35af3341f3fc283c41beda469e5c9ff2531f7bf01d537cb4dcc9c4a7fd6b42df`.
The first failed SUMMARY SHA remains
`555ab819d5d3215fc34b901db7a70aa89c4e4363719c5bc8eadfbffadd786642`.
The completed fixed-input SUMMARY SHA is
`cf13fa5f2ea53f0b1e14321f6f6239ed11d5ac60c919a5d89c5ec0fd8a1b2d41`.

## Local evidence preservation

The independent supplement contains 143 payload files, 84,045,856 bytes, plus a
manifest. It retains both attempts, both driver logs, registered source bundles,
postexecution reviews and the pure-data verification script. Postexecution
appendices are explicitly distinguished from preregistered files.

| Artifact | Bytes | SHA256 |
| --- | ---: | --- |
| `hepta_field_bridge_v5_20261028_dispatch_evidence.tar.gz` | 36,703,243 | `0fb91290b340dc6b5604cea89d84f1af6923333f5c800ee8ec8f02618a7fd4ee` |
| `hepta_field_bridge_v5_20261028_dispatch_archive_verification.json` | 61,302 | `32faec17fb10ed3ae84a0d27f7851f155a6df2831f24c8f02cdd3fdfc17ea266` |

All 144 archive members pass length/SHA verification and per-member literal
restoration. All 38 NPZ, 18 inner gzip streams and the outer gzip pass CRC/EOF
checks. This is not simultaneous full-tree restoration or model replay. The
original canonical V5 archive and its verification remain unchanged in bytes,
SHA, mtime and inode. The first packaging attempt rejected an inventory change
before writing an archive; its receipt is retained separately.

[DISPATCH_ARCHIVE_VERIFICATION_20261028.json](DISPATCH_ARCHIVE_VERIFICATION_20261028.json)
records the full bounded-space procedure. The raw archives are local only.
Git publication of source and review metadata is not external preservation of
the raw evidence. There have been no new raw upload attempts.

## Remaining decisions and blockers

| Item | Current disposition |
| --- | --- |
| Fixed-input diagnostic execution and integrity | Closed for this registered bounded diagnostic. No historical or scientific claim upgrade. |
| Local canonical/supplement preservation | Verified within each receipt's stated restore scope. External durability remains pending. |
| Historical exact regression and missing original raw | Open. No tested capability reconstructs the original raw; original audit remains FAIL. |
| V5 candidate decision | Complete: REJECTED. Four matched field-minus-ordinary/richer contrasts are zero; no positive field increment established. |
| B03/B04/B05/B06 | Original benefit criteria remain not established. B07/B09 remain partial. B01/B02/B08 retain only their previously recorded bounded scope. |
| New-head engineering validation | Pending remote CI; local Rust build is resource blocked. The cargo-deny root cause remains unresolved until a complete diagnostic is retrieved. |
| Windows production qualification | Non-Unix owner/ACL and directory durability gaps remain; fail-closed behavior is preserved. |
| Next scientific candidate | NOT_REGISTERED / NOT_EXECUTED. Separate synthetic state/serialization preparation is underway; implementation review and a frozen execution protocol are still required. Its minimum 2 GiB `f_bavail` requirement is currently unmet. No fresh holdout is authorized. |
| Raw evidence persistence | Specific named-file/destination authorization remains required by the recorded automatic-review refusals. No alternate upload route is attempted. |
| L01/L02 | Formal theorem applicability, LLM scale and production owner integration remain unestablished claim boundaries. |

`DENY_ALL`, `requires_calibration=true`, `native_owner_integration=false`, the
original closure criteria, and `all_original_substantive_blockers_closed=false`
are preserved. Subsequent CI observations belong to the exact new head/merge
commit and should be appended as later evidence, not read back into this
pre-CI snapshot.
