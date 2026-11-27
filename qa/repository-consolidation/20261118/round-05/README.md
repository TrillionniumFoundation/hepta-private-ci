# Reviewed additive histories and exact archive custody

This stage extends candidate `dafb60d0ccad1280381ce1ec97aa4f3b9febc425` with
21 independently reviewed original heads. Their complete original histories
cover 23 additional ordinary branch names in the pinned census: 2,059 of 7,239
ordinary names are represented in the candidate, with 5,180 still pending.
These are candidate counts; `main` has not moved and no branch is deleted.

## Retained source and evidence

- Fifteen passive heads contribute 152 original paths. Of those, 141 retain
  their exact Git blobs, three README files link to the lossless carriers, and
  eight raw artifacts are carried as deterministic gzip files. Three new
  support files document and verify restoration of the original bytes.
- Six additive code/artifact heads contribute 24 paths. Nineteen retain their
  original Git blobs. Four Python source/test files receive the narrow fixes
  described below and syntax-preserving formatting. One historical analysis
  script receives only an identifier rename, proven by complete normalized
  syntax-tree equality.
- Every original parent is listed in `coverage.json`. The source plans record
  each original branch, file mode and blob identity. Their old-base tree IDs
  are evidence only; their additive elements are composed onto the current
  candidate, preserving subsequent candidate changes.
- The ancestry of all proposed parents and the candidate was checked against
  265 protected HIA/Cell pins and two protected lineage roots. There were no
  intersections. The protected branches remain outside this integration.

The passive review verified JSON/JSONL parsing, five original ZIP CRC checks,
and the original documents and provenance. All eight compressed artifacts
restore to their exact original byte lengths, SHA-256 digests and Git blob
IDs. Original failures, incomplete runs and HOLD decisions remain visible.
The restore helper verifies before writing and only creates a separate new
output directory; it refuses an existing output or a repository destination.

## Narrow behavioral repairs

The NDU post-hoc audit now creates reports exclusively: an output argument
cannot overwrite the input archive or an existing report. The MemoryCell
matrix audit parses the same prediction bytes whose digest enters its
inventory, eliminating the interval between hashing and reopening the file.
Original production/scientific admission flags remain false.

The functional checks executed 60 distinct cases: 25 NDU cases, 24 matrix
cases and 11 frozen HCSN admission cases. The 11 HCSN cases also passed under
Python optimization, for 71 executions overall. The original five-file HCSN
source seal was verified in both modes. The preserved historical recovery
resolver scripts were reviewed, retained verbatim and not executed or
generalized. The associated read-only profile script only renames the local
right-caller variable to satisfy spelling checks; its full normalized syntax
tree is unchanged.
The frozen HCSN files retain their original bytes and source seal.

Red and green receipts are retained alongside the source plans. Formatting
preserved the four adapted Python syntax trees; tests were not rerun after
formatting. These checks do not establish native Rust, model or deployment
qualification for this candidate.

## Codespell custody repair

The hosted Codespell run at the parent candidate interpreted three split gzip
parts from round 03 as Latin-1 text. The repair adds only those three exact
paths and their SHA-256 digests to the existing custody verifier. It adds no
pattern exemption and does not modify the original evidence or workflow.

All 12 custody tests passed, including mutation tests for every pinned binary
and rejection of neighboring shards, patterns, Python paths and traversal.
The verifier checked 17 exact archived paths. The initial complete Codespell
2.4.3 scan passed with the unchanged workflow arguments after temporarily
parking the local, untracked formatter environment outside the scan. A final
combined-content spelling receipt and formatter receipt accompany this stage.

## Remaining work

Required hosted checks must pass on the final candidate before merging into
`main`. The unresolved large families, native qualification and remaining
dependency migration are separate work in progress. No successful historic
test result here is represented as a result for the final integrated tree.
