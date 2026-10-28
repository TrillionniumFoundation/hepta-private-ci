# Restore large audit outputs and original figures

`MANIFEST_001.json` maps every archived original to its exact study002-relative
path, uncompressed byte count and SHA256. Each mapping also records the complete
gzip byte count and SHA256. The archive inventory lists every ordered part with
its own byte count and SHA256. Identical original contents share one archive.

From the repository root, run:

```sh
python3 experiments/continuous_spiking_followup/results/study002/analysis/restore_audit_archives.py \
  --study-root experiments/continuous_spiking_followup/results/study002 \
  --manifest experiments/continuous_spiking_followup/results/study002/analysis/audit_archives/MANIFEST_001.json
```

Add `--verify-only` to verify all archive bytes, decompressed identities and any
existing original files without creating outputs. The utility needs only the
Python standard library and imports no model or training code.

After restoration, report-linked large JSON files and high-resolution figures
are available at their original paths, including `TRAINING_AUDIT_V2.json`,
`analysis/COMPARISON_SUMMARY.json`, `analysis/ONLINE_SUMMARY.json`, and the mapped
files under `analysis/figures/` and `analysis/figures_v2/`. Published smaller plot
files remain directly viewable. The mapped SVG and PNG originals retain their
exact bytes; this transport performs no resizing or scientific recomputation.

The utility verifies the manifest identity, each archive part, each complete
gzip stream and every decompressed SHA256 before creating outputs. It creates
missing files and skips existing byte-identical files. It rejects mismatching
existing files, unsafe paths, symlinks, malformed or concatenated gzip streams,
and excessive declared output sizes. Run it without concurrent filesystem
writers. Existing files are never overwritten.

This manifest covers 16 original paths with 11 distinct contents, totaling
11,585,344 bytes across their original locations. Its 13 archive parts total
1,809,951 bytes; every part is at most 400,000 bytes. Four already generated gzip
archives are reused at their existing paths after exact decompression checks.
All gzip headers use `mtime=0`.

Large binary files are archived above 512,000 raw bytes. UTF-8 files without NUL
bytes are archived above a conservative 250,000 raw bytes to keep publication
payloads bounded. The original local outputs remain unchanged. The manifest's
canonical SHA256 is
`04d7e1e7097b8906c9fb5929134ff257faf52f4a0ea53566aa0c9b911da41660`.

`TRANSPORT_CHECK_001.json` records exact restoration of all 16 current originals,
idempotent reuse, verification without writes, and 24 rejection checks covering
path safety, corruption, stream boundaries, existing-file preservation and
expansion through repeated original paths.
