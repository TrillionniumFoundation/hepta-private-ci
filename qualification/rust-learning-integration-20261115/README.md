# Reviewed Learning integration

This directory records the ordinary two-parent integration of Learning tip
`f387d7027039e3fc055fe7c201421f5364e1ab9d` into the reviewed Rust candidate
`b6a5e15aa4b05ddfe63c88cb870de85c19a87214`. The 34 new HIA branches remain outside
this integration. No HIA ref or remote branch is changed by this local work.

`MERGE_REVIEW.json` identifies the original 45 conflict paths and preserves the
review decisions. The source contains both existing Memory/ACT/inference owner
paths and the incoming Learning/Root paths. The central decisions are:

- Retain the original locked-file digest, physical replay, cursor restoration,
  poison, witness and CAS checks alongside incoming independent CURRENT reads.
  Holdout writes update cached state only after both physical post-write reads
  agree with the expected bytes and state. The two qualification observations
  retain their distinct bounds and poisoned-owner behavior.
- Retain the original Prepared Dataset borrow while adding captured Source
  operations. Training uses the same source before and after native work, then
  rechecks the actual journal and deadline before terminal publication. Existing
  Pending and Missing states retain their meanings.
- Route shared Trainer operations through the same original transport identity
  and complete verifier context. Independent Q24 readback remains available.
  A host operation cannot substitute an independent or reconstructed trainer.
- Preserve both independent test suites whose filenames collided. Prepared
  tests now have `cell_q24_prepared_training_*` filenames under their original
  parent modules; incoming bootstrap/source tests retain their original names.
- Combine the exact original native test selections and package sets. The
  daemon helper preparation and verification both include `codex-cli`, because
  the existing episodic drain subprocess invokes the real `codex` binary.
  The settlement assertions and production shutdown behavior are unchanged.

## Closed source boundaries

The caller manifest contains 1,618 closed boundaries and 801 consolidated
protected file records. Consolidation retains every required and forbidden
marker, ordered check, function scope, top-level requirement and false authority
metadata from both original domains. Caller-specific checks stay with their
actual file when the two sets of callers differ. The verifier and its typed
receiver scanner are unchanged.

Two private `Active`/`State` structs have specific owner names, and a small set
of calls now spells their actual types explicitly. This keeps the conservative
scanner from confusing unrelated owners with the same method or struct name.
It does not create a new owner interface or add a generic caller exception.

The repository formatter ran on the exact integrated Rust files. Historical
qualification contracts remain byte-identical. Their checks use the explicit,
SHA-pinned marker map in
`qa/b4-no-bypass/protected_marker_format_20261115.json`; no general source-proof
exception is introduced. The independent consolidation tests reject omitted
checks, changed order, wrong function scope, lost top-level constraints, changed
authority metadata and duplicate records that could mask an incomplete union.

The complete reviewed guard changes can be read with:

```sh
gzip -dc qualification/rust-learning-integration-20261115/GUARD_REVIEW.json.gz
```

## Evidence and validation

Five incoming evidence files exceeded the unchanged 512,000-byte blob limit.
Their ordered 500,000-byte parts, original and per-part SHA-256 values, lengths,
no-clobber restoration commands and byte-identical validation are documented in
`qualification/learn-evidence-storage-20261115/`. Historical reports and export
manifests keep their original paths and experimental conclusions.

`MERGE_REVIEW.json` records the actual validation states at this checkpoint.
The original caller CLI passed on 7,349 Rust files, 1,618 boundaries and 801
protected files, with the same caller-manifest SHA before and after execution.
The full formatted source-closure suite passed all 1,164 tests with no failures,
errors or skips. The other six repository QA modules passed 123 tests; the four
kernel-authority tests passed after review of the two exact resident caller
inventory entries. The verifier self-test and original 512,000-byte blob gate
also passed. The full caller receipt is in `CALLER_PROOF.json.gz`; the source
snapshot hashes and blob log are stored alongside it.

Historical patch and terminal captures retain their original whitespace and
bytes. The source diff check passed; no historical evidence was reformatted to
make a whitespace diagnostic disappear.

A formatted source proof is separate from a native test result. Native compilation
and execution remain unproven while locked dependency retrieval is blocked by
the recorded network timeout. Later validation updates must record their actual
terminal results and must not turn this dependency failure into a pass.

## Adjacent historical evidence branches

`NEIGHBOR_MERGES.json` records the subsequent ordinary merges of the four
reviewed Learning neighbors. They add 53 unique qualification evidence files;
Rust source, caller rules, QA code and CI workflows are identical to the primary
merge. The original failed target attempt remains a failure, and the original
archive restoration remains archive-only evidence. Prepared historical carrier
scripts were preserved without dispatching them. Each retained file has an
original-tip byte count and SHA-256 in the receipt.

## Coalescence with the frozen root candidate

`ROOT_COALESCENCE.json` records the ordinary merge with root candidate
`bd9a22512f78794d31a0f5c9a8b8db4b5192eeee`. Its fresh preview has no text
conflicts. The 19 incoming Rust paths do not alter any declared boundary path or
protected file; all 801 protected file bytes and the caller manifest remain
identical to the primary Learning proof. The neuro, NDU, Windows, fixture and
workflow interactions are reviewed explicitly in that record. Cargo workspace
and lock inputs do not change.

Native results from either parent remain evidence for their original source.
Combined-source validation must record its own outcome; the old successful
source proof and the old download failure are not relabelled as a combined
native pass.

## Combined validation and the next 23 Learning heads

`COMBINED_VALIDATION.json` records the actual original caller CLI pass and all
1,291 repository QA tests passing on combined source
`e961959486b95b4f08cabf4c6a4c3237ee6e1ed9`, with no failures, errors or skips.
The before/after HEAD and caller-manifest hashes match. This still does not
establish a native compile/test pass.

`ADJACENT_23_MERGES.json.gz` records 23 subsequent ordinary merges, each freshly
previewed against its cumulative HEAD, covering 41 additional frozen tips and
branch names. They retain 298 qualification files and the same two diagnostic
Rust test additions; production source, caller rules, QA and CI are unchanged.
The diagnostic timing limits and assertions remain intact. Historical native
failures remain failures on their recorded old sources. Current diagnostic
formatting and native execution require their own actual outcomes.

Ten oversized evidence files are represented by 20 verified byte parts. The
final-tree restoration was executed again and refused overwrite on its second
invocation. See `../learn-evidence-storage-followup-20261115/` for the exact
original identities, the restoration program and five verified helper exports.
