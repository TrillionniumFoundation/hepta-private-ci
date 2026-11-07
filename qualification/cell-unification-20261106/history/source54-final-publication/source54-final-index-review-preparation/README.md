# Artifact7 INDEX validator preparation

This is an independent, local integrity validator for the final artifact7 INDEX.
It has not been run against a candidate INDEX. The prepared program performs no
network requests, subprocess calls, Git operations, Rust execution, metadata
queries, or canonical writes. Its optional report is create-only and must be
outside `hepta-cell`.

## Frozen historical basis

| Collection in the v4 INDEX | Original rows | Retention rule |
| --- | ---: | --- |
| `artifacts` | 2109 | Preserve every existing key/value by relative path, including any `git_blob` or decompression fields. |
| `historical_artifact_git_bindings` | 1673 | Preserve the old publication identity and false raw-read observation flags. |
| `additional_inherited_git_paths_not_in_prior_raw_inventory` | 50 | Preserve Git identities and explicit null/false raw observations. |
| `observed_local_artifacts` | 436 | Preserve prior observations; additional rows may be appended. |
| `unmaterialized_binary_references` | 139 | Preserve all original fields, including the ledger and historical raw hashes as distinct fields. |

The 139 unmaterialized references are not 139 additional paths: 89 overlap the
2109 raw rows and 50 overlap the Git-only collection. The actual checkpoint6 tree
has 2160 native-evidence leaves: 2109 raw rows, 50 Git-only leaves, and the
self-excluded main INDEX. Reordering rows or adding fields is permitted; deleting
an old row or changing an existing field is rejected. Top-level current metadata
may be upgraded. The complete old INDEX survives separately as exact gzip bytes.

The default prior input is
`hepta-cell/qualification/cell-unification-20261106/native-evidence/history/source54-index/INDEX-v4.json.gz`.
Its decoded bytes must match the original 1548794-byte INDEX with SHA256
`fe9d15906ac379e33e7d58e0bed4e385592cf79d4b8eaf6e76e2c90beb48dc61`.
`--prior-index` also accepts a raw JSON copy with that exact identity. The new
`previous_index` metadata may pin the gzip, but must separately contain the exact
decoded `{bytes, sha256}` pair, either in a nested object or explicitly prefixed
`raw_`, `decompressed_`, `uncompressed_`, or `original_` fields.

## Actual blob map input

`--new-blobmap` uses the existing map shape: `files` maps full repository-relative
paths to actual Git blob IDs, and `file_sizes` maps the same paths to byte sizes.
The two key sets must be equal. Both input modes are explicit:

- `--map-kind overlay` merges the supplied complete additions/replacements with
  the frozen checkpoint6 map.
- `--map-kind complete` accepts a full proposed publication map and requires all
  checkpoint6 paths to remain present.

Both modes must include all 1103 paths from the frozen
`r31-formal-root-preparation/COMBINED-STAGED-OVERLAY.json`, with their actual blob
and size identities unchanged. Every prior native-evidence leaf except the main
INDEX retains its checkpoint6 identity. Prior report paths outside
native-evidence may change; they must remain present and are listed separately.
The supplied main INDEX entry may still be the old self leaf or may be the exact
candidate blob. This does not assert that a final publication tree already
exists; root verifies that separately after publication.

Every mapped native-evidence leaf must be covered by the candidate raw or
Git-only collection, apart from the main INDEX. Every new raw row requires
available canonical bytes. The validator recomputes their byte size, SHA256, and
Git blob hash and requires all three to agree with the row and actual map. All
available old raw files are rehashed too. Missing historical files retain their
old observations, with missing and actually reread counts kept separate. Gzip
decompression pins are recomputed when the corresponding bytes are available.
Available Git-only bytes can be checked without rewriting their historical
observation flags. No SHA256-to-Git correspondence is invented from two unrelated
hash strings when bytes are absent.

## Counters and current identity

The five v4 counters continue to equal the lengths of their corresponding arrays:
`artifact_count`, `historical_artifact_count`, `current_raw_hash_count`,
`inherited_additional_git_reference_count`, and `unmaterialized_reference_count`.
The original 436 observed rows may be retained and extended, and all available
rows are independently checked again during actual validation. Counts must not
double-count the 139 references as new paths.

The final INDEX uses version 5 or later. `source_identity` must identify actual
registered source54, commit `b5209cfdf509e990f10922197b32540bf8c353a7`, tree
`42c1dd4e1a751c690c2800dfc3868e771dc9c70b`, and the unchanged 197-path scope
(183 Rust and 14 other paths). GitData registration is explicitly distinct from a
native checkout. The last closed project/workspace gate fields name `r30` and
`r31` with PASS/exit 0 and retain tested source53 commit
`f74be175de66a4b351cd239d39d98cd34fe9cc1b` / tree
`440d4a8e09af4009e4d9ea067388826308da8803`. The R31 command remains
`["just", "test", "--locked", "--retries", "0"]`. The validator checks these
identity boundaries; root's separate complete original-log reviews establish the
test results. No qualification transfers to the formatted tree.

`self_excluded`, `all_prior_Git_paths_retained_by_publication_plan_required`, and
`qualification_not_inferred_from_integrity` stay true; `science` stays `HOLD` and
`authority` stays `DENY_ALL`. `formal_INDEX_written` remains an explicit boolean
describing the candidate's adoption state. This validator does not adopt it.

## Run only with the actual final candidate and complete new map

```bash
python3 /workspace/scratch/08f5efd48967/source54-final-index-review-preparation/validate_final_index.py \
  --candidate-index /absolute/path/to/INDEX.candidate.json \
  --new-blobmap /absolute/path/to/COMPLETE-NEW-BLOB-MAP.json \
  --map-kind overlay \
  --canonical-root /workspace/scratch/08f5efd48967/hepta-cell \
  --report /absolute/new/path/to/INDEX-INDEPENDENT-READBACK.json
```

The report parent directory must already exist. Existing report files are never
overwritten. Exit 0 means local INDEX integrity only; it does not publish files,
create an artifact checkpoint, parse gate logs, or confer any new test result.
