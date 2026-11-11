# Exact storage for four historical artifacts

This package changes storage only. It preserves the original bytes and SHA-256
identities of three native evidence archives and the historical HCSN `full.json`.
It does not run a model, replay an experiment, reset a budget, change a receipt,
or qualify a new source revision. All original failures and incomplete statuses
remain in the recovered data.

The native archives contain their original compressed bytes, split at 262,144-byte
boundaries. They are not unpacked or recompressed. The JSON is gzip-compressed
without changing its decoded bytes. [ARCHIVE.json](ARCHIVE.json) records the
ordered parts, offsets, lengths and hashes, as well as the unchanged six original
index, verification, summary and audit files.

| Original logical path | Original bytes | Stored form |
| --- | ---: | --- |
| `qualification/cell-six-refactors/evidence/native-a8dd9d46.tar.gz` | 531,052 | Three `.parts/part-NNN.bin` files |
| `qualification/cell-six-refactors/evidence/native-c058c08f.tar.gz` | 538,535 | Three `.parts/part-NNN.bin` files |
| `qualification/cell-six-refactors/evidence/native-cb6f0a4a.tar.gz` | 563,937 | Three `.parts/part-NNN.bin` files |
| `qualification/hcsn/evidence/cloud-20261105/attempt-safe/full.json` | 830,338 | `full.json.gz`, 24,249 bytes |

Run the read-only verification from the repository root:

```sh
python3 -B qualification/historical-blob-storage-v1/readback.py
python3 -B -m unittest discover -s qualification/historical-blob-storage-v1 -p 'test_*.py'
```

To recover all four original files under their original relative paths, choose a
new directory outside the repository whose parent already exists:

```sh
python3 -B qualification/historical-blob-storage-v1/readback.py --restore-dir /tmp/hepta-historical-readback-20261107
```

An existing destination is rejected. Verification completes before creation;
interruption during writing can leave a partial new directory, which is retained
for inspection. The tool checks each written file again and never extracts a tar
archive. It requires Python 3 and the standard library only. Stored parts are
bounded at 256 KiB, metadata at 64 KiB, and decoded artifacts at their four exact
original lengths (2,463,862 bytes in total). It rejects symlinks, missing or
reordered parts, altered hashes, inflated lengths, invalid gzip data and an
ambiguous retained original. No existing receipt-reader limit is increased.

Historical records retain their original logical paths and hashes; the archive
manifest supplies the current storage locations. HCSN's `benchmark.py` is not a
recovery tool: invoking it can execute experiments. `audit_population.py` reads
the explicit benchmark path and also needs the original adjacent `.runs` layout
and referenced weights for a new population audit. This readback does not
reconstruct those additional inputs or run that audit. Use the preserved
`full-population-audit.json` to inspect the historical audit result. The readback
code lives outside `qualification/hcsn` so it does not enter that package's Python
source snapshot. Its training scripts and attempt records are unchanged.
