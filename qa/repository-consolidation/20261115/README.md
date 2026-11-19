# Rust branch consolidation — 15 November 2026

## Requested result and protected work

The repository owner requested a full repository audit, consolidation of the
Rust branches into `main`, and retirement of their redundant branch refs.
The new HIA branches must remain unchanged.

`branch-manifest.json.gz` is the complete, frozen GitHub branch inventory at
2026-11-15 14:39:59 UTC (09:39:59 America/New_York), including exact tips and
associated PR numbers. It contains 7,256 branches: `main`, 7,221 Rust integration
candidates, and 34 excluded new HIA branches. All branch and PR collection pages,
including empty terminal pages, were inspected. Read the inventory with:

```sh
gzip -dc qa/repository-consolidation/20261115/branch-manifest.json.gz | python3 -m json.tool
```

`hia-exclusions.json` contains the 34 protected refs. Each tip descends from the
first new HIA commit `f02bb9f3344cdff4e361cca4353540ca0193bd21`, whose parent is
the current `main`. Four protected names do not contain `hia`; exclusion by name
alone is insufficient. Older Rust HIA/utility bridge branches do not descend
from this new HIA root and remain in the Rust integration inventory.

## Starting state

* `main`: `732e934ba496d90fbe042b8d41d479ef901643e5`.
* Existing integration PR: [#6293](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6293).
* Starting candidate: `a5ca2bae54d0bca65e72f1920f8157f44b5a4fb8`.
* Candidate tree: `ef85add3bd3d565d4e002cab2b662d461bb1ef9f`.
* `main` contains none of the 7,221 other non-HIA tips by ancestry.
* The starting candidate contains 692 non-HIA refs including `main` and itself;
  6,530 non-HIA refs are not yet ancestors. Those refs reduce to 6,203 distinct
  commits and 2,276 maximal tips. See `initial-graph.json`.
* The 119 checks on the starting candidate were 72 successful, 37 failed,
  9 skipped, and 1 cancelled. Required checks `CI required` and
  `Architecture required` both failed. `initial-checks.json` retains names,
  conclusions, links, and the exact head.

These are starting observations, not a claim that consolidation or qualification
has completed. All original tips remain recorded; they must not be retired
until their reviewed content and history have been retained on `main`.

## Repairs made in this checkpoint

1. Reconcile `FileAnchorWitnessStore::qualification_file_bytes` with its actual
   `Mutex<WitnessLockedFile>` and `AtomicBool` fields. Retain the original locked
   file description, cursor-restoration reader, and the poison fence on errors.
2. Remove duplicate global Bazel annotations for
   `matrix-sdk-store-encryption 0.19.1` and `sha2 0.11.1`, preserving the existing
   `crates`-scoped optimization flags and all other annotations.
3. Apply the module ordering reported by the Rust formatter for
   `fenced_holdout_file.rs`.
4. Preserve three over-limit original experiment archives as byte-identical
   bounded parts, with full/part SHA-256, sizes, reconstruction instructions,
   and unchanged experiment results. See
   [`memory-cell-archive-storage-20261115`](../../../qualification/memory-cell-archive-storage-20261115/README.md).

Static annotation checks and `git diff --check` passed. Archive reconstruction,
XZ/tar integrity, all 14 MEM12 checksum references, and all six MEM14 publication
references passed; the existing blob policy unit tests passed 10/10. The clean
replacement execution environment lacks Rust, `just`, and Bazel: native format
and owning-test commands returned exit 127 and remain unverified. Native
qualification must run on the exact combined tree using the original commands.

## Integration and retirement requirements

Use ordinary Git three-way merges and record actual conflict resolutions.
Criss-cross histories must use Git's recursive virtual base; choosing one
arbitrary merge base is insufficient. Equal merge trees can be legitimate
already-applied changes, but adding parents alone does not establish source
preservation. Source/API supersession must be reviewed separately from ancestry.

Before promoting a combined candidate, refresh `main` and candidate tips and
complete the repository's required checks. Before retiring any Rust ref,
independently read its current tip, verify inclusion in the new `main`, and use
that exact tip as the expected ref value. A moved ref requires another audit.
Re-read the protected HIA refs and compare them with their original tips. This
checkpoint does not change branch protection or required-check definitions.

## Other observed audit findings

The original real encoder E0 run rejected two features outside its `[-8,8]`
input contract; strict bwrap isolation failed during network-namespace setup;
the CodeQL check reported 21 alerts (8 critical and 13 high), with GitHub warning
that this large diff may include pre-existing alerts. Alert locations were not
available from the supported check API in this audit. None of those observations
is a passing qualification, an established new-vulnerability count, or evidence
that every product capability is complete.
