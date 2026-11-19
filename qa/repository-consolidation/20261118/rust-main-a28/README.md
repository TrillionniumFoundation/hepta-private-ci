# Rust consolidation: source checks, digest configuration, and Notes deadlines

This checkpoint continues the existing ordinary Rust integration. The source
parent is `a91102d3639a5a1f02394bfc0331611e9ab101a1`; the real Notes merge parent
is `59d05538c9a2be1d1240e328648935832fac7cf4`. The repository-wide consolidation
remains in progress. Required hosted checks, unresolved ordinary histories, and
platform failures retain their original status until independently qualified.

## Source changes

### Source closure checks follow the actual replay implementation

Two Python source-check files still searched for inline code that had moved into
the physical replay helpers and bounded memo. The old 24-test selection produced
nine errors. The corrected 26-test selection checks those actual source paths,
retains the original refusal conditions, and adds two negative checks for the
physical image and memo bindings. Production code and caller allowlists are
unchanged by this repair.

The complete original `qa/b4-no-bypass` discovery command passed 1,347 tests in
583.147 seconds, with zero failures, errors, or skipped cases. The tested snapshot
is the exact source parent with these two Python changes; the Notes merge has its
own 26 passing source-guard cases and unchanged caller-boundary review. These
component results remain bound to their recorded source files.

The earlier incomplete snapshot's four missing qualification fixtures and failed
run remain in the evidence. The final complete run restored the original blobs;
it did not remove or skip those tests.

### Bazel uses Cargo's existing optimization for the actual digest backend

`Digest32` uses `sha2 0.10.9`. Cargo already compiles that package at optimization
level 3 in the development profile. Bazel had the corresponding annotation for
`sha2 0.11.1`, but omitted the version actually used by this digest backend.

The seven-line `MODULE.bazel` change adds the missing version-specific annotation.
The actual Bazel compiler action ends with `-Copt-level=3`, after the fastbuild
default of level 0. The execution-platform action also ends at level 3. The
original `just bazel-lock-update` completed successfully and left the lockfile
unchanged. No hash algorithm, version, feature, physical read, ownership check,
signature check, or deadline changes.

The original Bazel Types and Intelligence Evaluation targets passed: 70 and 228
top-level test cases, respectively, with no ignored or failed cases. The six
subprocess test invocations in the Evaluation log are nested in those cases and
are not counted again. Both targets ran with test-result caching disabled.

This validates the concrete build mismatch and the digest/replay regressions.
The original Agentd NextUse diagnostic still needs its own result on the final
hosted candidate with the unchanged 500 ms evidence deadline. These scoped
results do not establish that timing result.

The first Bazel attempt's omitted original V8 build inputs and the second
attempt's overly broad action-reader assertion remain recorded. The final reader
selects the actual SHA-2 crate and its source, and interprets compiler options in
their actual order. It does not treat a consumer's dependency arguments as a
SHA-2 compiler action.

### Notes rejects ready results received after the original absolute deadline

The incoming ordinary history has two new commits. A native three-way merge
retains that history and adds a deadline recheck immediately after each of the
two RPC awaits, before a returned result can be adopted. The existing strict
`Instant::now() < end` predicate supplies both checks.

Two regression cases make an immediately polled future block for 20 ms against
the original 5 ms budget. This covers a future that returns `Ready` after the
deadline, which an outer timeout alone does not reject. In the red control, the
original six status cases pass and both added cases fail at their intended
assertions. The real merged source passes all 126 selected Notes cases, including
both added regressions, in 10.449 seconds with zero retries. The other 1,576 cases
are outside the explicit `test(notes_)` selection; they are not reported as
executed by this scoped run.

The only merge conflict was a sentence in `PRODUCTION_LAUNCHER.md`. Its resolution
keeps the installed failure preserved and requires the new run to produce its
own independent evidence. All three original document versions are retained.
Other incoming changes already present in the source parent are preserved by the
actual merge; this is not an ancestry-only merge.

## Scope and branch protection

The initial census contains 7,572 branch names: 7,222 ordinary names, 349 protected
HIA/Cell names, and `main`. Protection uses explicit exclusions and ancestry,
including names that do not contain `hia`. The two HIA roots and the additional
Cell ancestry anchor are excluded from the proposed ancestry.

At that census, `main` is
`732e934ba496d90fbe042b8d41d479ef901643e5`, and no ordinary branch tip is reachable
from it. Consequently, the deletion-eligible set is empty. Every future deletion
requires a fresh exact tip, protection classification, and reachability from the
successfully merged main. Required checks and branch protection remain in force.

The original inventory and the later publication inventory are separate evidence
records. The later inventory has 7,581 names: 7,224 ordinary names, 356 protected
HIA/Cell names, and `main`. Nine branches were added and no earlier ref moved or
disappeared between these two reads. Seven new names have complete parent paths
to the Cell/HIA root. The two new owner/native names do not descend from either
HIA root; their exact source differences are retained for ordinary source review.
Concurrent branch creation is not attributed to this checkpoint.

The proposed Notes ancestry covers 2,064 ordinary names, including the two newly
integrated Notes/desktop names. That leaves 5,160 ordinary names outside this
candidate's ancestry in the later inventory. Coverage in an integration candidate
is separate from coverage in successfully merged `main`.

## Verification and evidence

`candidate-source.json` binds each changed source file to its Git blob and
SHA-256. Raw reports and logs preserve their exact bytes in the evidence archive;
the archive index records every member's size and SHA-256. Complete branch
inventories use separate lossless gzip files to remain within the existing blob
size limit. No check exemption or blob-size exception is added.

Formatting follows testing. `just fmt` completed for the Bazel and Python changes
without changing their tested bytes. The Notes merge also passed the complete
caller verifier: 7,873 Rust files, 1,645 boundaries, and 820 protected files.
`just fmt --base a91102d3639a5a1f02394bfc0331611e9ab101a1` then completed with both
Notes source files and both caller-manifest files unchanged. No tests ran after
formatting. The nested `native-notes-originals.tar.gz` preserves all 22 original
native report, log, source, and Git-bundle members; its separate summary and
control records retain the failed metadata-reader attempt as well.

No component pass is transferred to a different source tree or to
whole-repository qualification.

Existing hosted failures on the source parent include the original NextUse
deadline, Windows admission and connection behavior, Linux Guardian response
routing, the macOS PTY drain case, a Core structured-input case, and dependency
policy. They remain open until their own repaired candidate obtains the required
results. Related ordinary branches with large unresolved conflict sets are not
attached merely because their latest commit contains a useful small repair.
