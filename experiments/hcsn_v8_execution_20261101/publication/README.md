# Byte-preserving publication transport

Eight evidence files exceed the 450,000-byte publication selection threshold.
Their original 7,289,944 bytes remain untouched in the working tree. The published
tree can omit exactly the eight paths in `MANIFEST.json` and carry this directory
instead. This is a transport representation of existing evidence; it creates no
new scientific result.

Each original is split into raw slices of at most 400,000 bytes. Each slice is
wrapped in gzip with `mtime=0` and no embedded filename. Restoring means decoding
each wrapper and concatenating its raw payload. In particular, an original
`.jsonl.gz` or `.npz` is treated as opaque bytes: its existing compressed bytes
are restored exactly, without decompressing or re-encoding the original format.

## Inventory and verified outcome

All paths below are relative to `experiments/hcsn_v8_execution_20261101/`.
The machine-readable manifest records repository-relative paths, original byte
counts and SHA-256 hashes, ordered parts, and each compressed and raw part's
byte count and SHA-256 hash.

| Original path | Bytes |
| --- | ---: |
| `frontend/validation/development001/PAIRED_ROWS.jsonl` | 1,346,364 |
| `frontend/validation/replay002/PAIRED_ROWS.jsonl` | 1,346,364 |
| `mechanisms/results/development001/evaluation/runs.jsonl.gz` | 2,090,505 |
| `mechanisms/results/development001/fit_81101/sampled_data.npz` | 501,149 |
| `mechanisms/results/development001/fit_81103/sampled_data.npz` | 501,226 |
| `mechanisms/results/development001/fit_81107/sampled_data.npz` | 501,425 |
| `mechanisms/results/development001/fit_81109/sampled_data.npz` | 501,501 |
| `mechanisms/results/development001/fit_81113/sampled_data.npz` | 501,410 |

The two frontend originals have identical bytes and share their four transport
parts. There are 24 ordered part references, 20 distinct part files, and
4,668,266 total bytes in those distinct files. The largest part is 400,143 bytes;
every part is strictly smaller than 512,000 bytes.

`RESTORE_VALIDATION.json` records an actual fresh restoration into
`/tmp/hcsn-v8-transport-verify-fa_fubmm/restored`, a byte-by-byte comparison of all
eight files against their originals, SHA-256 equality, and unchanged originals.
All ten checks passed, including an identical second restore and refusal of
different existing bytes, a symlink ancestor, path traversal, and a modified
transport part. The modified part was rejected before any original was written.
An independent read-only review also passed 16 checks of the implementation,
manifest, part identities, original and restored identities, install/reuse
counts, both cost receipts, and frozen metering source identities. It performed
no model rerun and made no source edits.

## Restore from a published checkout

Run from the repository root with Python 3.9 or later; only the standard library
is used. Choose a destination directory for the restored repository-relative
paths:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m experiments.hcsn_v8_execution_20261101.publication.transport restore \
  --manifest experiments/hcsn_v8_execution_20261101/publication/MANIFEST.json \
  --destination /tmp/hcsn-v8-restored-evidence
```

To populate the omitted files directly in the published checkout, use
`--destination .` instead. Existing identical files are verified and reused;
different existing bytes are refused. Other files in that destination remain
untouched.

The restore checks every compressed part's identity before creating original
files. It then bounds each decoded part, checks its raw identity, and verifies
the complete original before installing that file. Installation uses a temporary
file followed by a no-overwrite hard link within the destination directory.
Relative paths with traversal components, symlink paths, and conflicting bytes
are refused. Installation is atomic per file, not transactional across all
files. The intended destination is a controlled local filesystem with hard-link
support; hostile concurrent filesystem mutation is outside this tool's scope.

## Reproduce packaging or validation

Packaging requires the original files. It scans the declared namespace, excludes
the output directory and `__pycache__`, selects files larger than 450,000 bytes,
and refuses to replace an existing manifest. Use a fresh output directory:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m experiments.hcsn_v8_execution_20261101.publication.transport pack \
  --root . \
  --scope experiments/hcsn_v8_execution_20261101 \
  --output experiments/hcsn_v8_execution_20261101/publication_reproduced
```

The recorded package uses `publication/` as its excluded output directory. When
repacking a checkout that also contains this existing package, its parts are all
below the selection threshold and are not selected. Validation requires the
eight originals to be available for direct byte comparison and a fresh report
path:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m experiments.hcsn_v8_execution_20261101.publication.validate_transport \
  --root . \
  --manifest experiments/hcsn_v8_execution_20261101/publication/MANIFEST.json \
  --report /tmp/hcsn-v8-restoration-check.json
```

## Measured execution scope

Both executions ran once through the unchanged
`economics.worker_cost` supervisor. Their complete receipts, supervision data,
commands, and logs are retained under `validation/`.

| Execution | Enclosing CPU seconds | Cold supervisor-to-exit wall seconds |
| --- | ---: | ---: |
| `pack_cost001`: scan, read, slice, compress, hash, write manifest and parts | 0.480450 | 0.587542395 |
| `restore_cost001`: actual restoration, byte comparison, identical reuse, and four refusal checks | 0.314846 | 0.312409241 |

These are packaging and validation costs, not model inference costs. Each row
uses its enclosing `wait4` CPU once; nested component timings are not added.
The boundary includes the fresh supervisor, interpreter startup, task work,
output drain, and inner evidence write. Outer launcher bootstrap, configuration
write, and final receipt serialization are outside that boundary. Both receipts
report successful completion and complete task CPU coverage. No scientific
campaign was rerun for this package.
