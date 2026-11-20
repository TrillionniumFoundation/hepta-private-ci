# Ordinary Rust consolidation: second reviewed source composition

This record extends repair head `73a96f64bfcf13380a62f6271b65d18ebf290799`.
The reviewed local source head is `1a1e97962c9aad4a08e5f147790b234d4ab0bb51`, tree `2326dfb516d4db967fd106265517c8c9e34c6b3f`.
Its independently read-back server source head is
`bdbdb9e555191353528d0a67946ee5f7c726de34` with the same complete tree.
The final audit append adds this evidence directory and losslessly repacks the
two existing raw evidence logs rejected by the original whitespace check. New server commit
IDs are mapped and read back during publication; the original branch commit IDs
and ordered merge parents are preserved. This record does not assert that the
whole repository has been qualified or merged to main.

## Source changes and their reasons

Three ordinary terminal-summary histories are integrated as real second parents:
`90bb831d030e6aba8c6be546833e535e67483295`,
`6612074c96fb379ffac29affe389a1f37ca6f336`, and
`086de626c32183822e47b04fbba17fb0cdc1005d`. Each was merged against its original
base with the default three-way merge. Six conflicting file regions and the
separately applied legacy assignment were reviewed explicitly. Current
item-aware completion, terminal guards, and existing native-app-server tests
remain intact. The first merge adds a transactional completion fix: if a later
item exceeds the size limit or conflicts with an already completed item,
neither partial output nor hidden item state is committed. Two new regressions
check output, state, and a subsequent valid retry. The historical third fixture
is adapted to the current item protocol, so this is a reviewed semantic union,
not a claim that the old and current source files are identical.

The actual CI on head `73a96f64` exposed several independent build and test
contract failures. The following fixes address those observed failures.

| Area | Reviewed change |
| --- | --- |
| Active formatting | Apply the exact CI formatter afterimages to three Python and two Rust files. The Python ASTs are unchanged. |
| Historical custody | Register only three exact relocated broker source records by path, size, and hash. Retain missing-file, symlink, mutation, and neighboring-active-source checks. There is no directory-wide formatter exemption. |
| Hermetic stripping | Declare the existing LLVM strip tool as a non-Windows test binary and resolve it through the repository cargo-bin helper. Missing or invalid Bazel metadata fails; ordinary Cargo execution retains its existing system-strip fallback. |
| Research test syntax | Restore the missing newline between two original test definitions, then apply the repository-locked Ruff formatter. All six original test methods and their minimal-repair AST remain. |
| Windows checkout | Enable Git long paths before checkout, using the existing repository workflow pattern. Historical evidence paths are unchanged. |
| Windows source pins | Rebind the sole changed Cargo pin and formatter-only probe identities to the exact reviewed bytes. All 37 pin checks and the original Windows method/refusal/source guards remain. |
| Integration test features | Add a dedicated test-only worker library for the three generation harnesses whose Cargo declarations require the composition feature. Retain shared dependency type identities; the other 23 harness bindings and production/unit feature lists are unchanged. |
| Timestamp conversion | Add a fallible conversion using signed total nanoseconds and checked platform epoch arithmetic. Adapt the remaining file-time fixtures and reuse it in the existing rollout helper. Pre-epoch fractions, explicit leap seconds, and platform range behavior are covered by new tests. |
| Windows clock precision | Preserve the original Timestamp nanosecond assertions, separately verify a representable negative 100ns SystemTime, and always exercise the original 1ns clock request against its actual standard-library interval and exact roundtrip. No skip is added. |
| Remaining Rust types | Use checked signed offsets in TUI text rebasing, checked timestamp increments in fixtures, the missing Unix test imports, and the exact boxed-value adaptations required by current types. Original assertions remain. |

The shared Timestamp method does not add a panicking conversion trait. The
three TUI fixtures construct standard errors compatible with their existing
`color_eyre::Result` return type. The existing rollout regression is **one Rust
test with three real file-modification-time cases**; earlier shorthand must not
be read as three separate test functions.

The concurrent recovery owner prepared a compatible conversion method and one
additional five-case test. Its complete 934-byte test is appended unchanged
after this candidate's complete 10,657-byte utility test module, preserving both
owners' inputs and assertions. The overlap report distinguishes identical
method bodies and formatting from incompatible fixture error types. It also
records the other owner's four-record formatter custody proposal and additional
tests for a later explicit integration union; this batch retains its reviewed
three-record scope without overwriting either owner's frozen work.

## Verification and its exact scope

| Evidence | Actual result |
| --- | --- |
| Provider job 136060199386 on head 73a96f64 | Six selected Rust provider tests passed. The other 2,479 tests were filtered and are not counted as passing. |
| Same job, core library and test Clippy command | Completed successfully with the original `-D warnings` command. The whole job later failed at source formatting. |
| Formatter-custody candidate suite | All 41 Python tests passed, including six new tests. All 35 original test bodies remain. |
| Existing branch-protection suite on the exact policy | All 31 original tests passed using isolated real local Git remotes. The production freeze operation also preserved all prior pins and the new HIA identity on the complete fresh repository snapshot. |
| New formatter tests against original policy | Failed with 13 subtest assertion failures; the original failure output is preserved. |
| Exact Ruff 0.15.13 execution | The formatter-policy files remained unchanged; the research test was formatted by the same locked version. |
| Research repair syntax | Normal and optimized Python compilation passed; six original methods were discovered. Their behavior tests were not run without the genuine research packet. |
| Compiler patch source preservation | 1,392 original assertion macro calls remain byte-for-byte and in order. This is a lexical source check, not Rust compilation or an AST proof. |
| Original Windows utility test job 136061097394 | Fifteen passed and one failed because its SystemTime subtraction assumed 1ns precision. The separate test correction is reviewed; its native result is pending. |
| Source objects and independent reviews | Exact modes, Git blobs, SHA256 values, ordered parents, and complete per-step deltas were checked. |
| New native Rust, Bazel analysis, Windows runs, and Rust formatting | Pending on the exact newly published head. No old or scoped result substitutes for these runs. |

Full selected CI logs are stored as deterministic gzip files under `ci/`, with
both compressed and uncompressed identities in `verification.json`. Reviews,
patches, complete formatter suite outputs, source bindings, and the local source
commit plan are included beside this document. Original failures are retained.
Patch records and raw test output are also stored as deterministic gzip files;
decompression reproduces the exact original bytes, including diagnostic trailing
spaces and final blank lines. The original whitespace check remains in force for
the actual source and all text records. Existing historical blob identities and
results remain recorded when the two older raw logs are repacked.

The separate main-recovery session's full B4 result belongs to its own exact
source tree. It is not claimed as qualification of this repair head. The
original `CI required` and `Architecture required` gates remain mandatory.

The complete base73 snapshot at 04:01:33 UTC contains 113 checks over two pages:
41 failed, 53 succeeded, 14 were skipped, and five were still running. The
45-job blocking workflow had 20 failures and two jobs still running. Architecture
base-merge had succeeded; source-head was still running. These are real base73
results, not results for this new candidate. The included report separates 21
observed root-cause groups and records each candidate's actual qualification as
pending. Remaining Windows binary-location, lock, prepared-input identity,
checkpoint, and permission-boundary failures require further diagnosis. The
macOS FIFO portability work remains assigned to the original recovery owner.

## HIA protection and remaining work

The fresh full snapshot contains 7,656 heads: main, 485 protected HIA-related
heads, and 7,170 ordinary heads. All 507 historical/current protected pins remain
in the protection set. No protected head or pin is an ancestor of this ordinary
candidate. The prospective server-mapped source history represents 2,842 ordinary
names, leaving 4,328 pending. Main still has no ordinary ref eligible for
retirement. No branch has been deleted.

The latest new HIA branch, `codex/hia-chrono-locked-oracle-projection-20261120-a11`,
points to `a6c5a0bcfdcc5a9cb869cbefb0f550177c884300`, whose parent is the already
protected `811e50dc4da55c2f22ac89c1ed03e471503ba78e`. The current protection rules
already cover this descendant. Its new identity is retained in this fresh
evidence without rewriting prior historical snapshots or moving the HIA ref.

The included history manifest and delta reconstruct the exact 78,760-node graph
from the 78,730-node graph already stored in thirteen published gzip parts plus
30 new verified nodes. Every old ordered parent vector remains unchanged. The
formatted reconstruction script was actually run on this new delta and matched
the complete 6,653,234-byte graph and its SHA256. Run
`python history/reconstruct-history.py --repo <checkout>` from this audit
directory to repeat that verification against a checkout containing the
published baseline parts.

The original recovery session remains the sole integration publisher. This
repair updates its existing ordinary branch and PR #6773, and must be genuinely
merged into that ongoing work without replacing the other session's valid
source or assertions.

The CellSplit frontier still has unresolved atomic publication, journal,
reopening, generation, temporary-path, and decode-boundary findings. Two Python
frontiers require a versioned protocol union; a host annotation versus immutable
actor-wire inconsistency is recorded. Their review reports are included, but
neither frontier is silently accepted as source-equivalent or merged here.

The source-only native copy request with key
`hepta-rust-c2d514464ab5-exact-source-copy-01` still has an unknown acknowledgement.
It supplies no native build or passing result. The previously rejected C2D
production repair remains unapplied. Neither condition is retried under a new
identity or treated as permission to weaken an existing gate.
