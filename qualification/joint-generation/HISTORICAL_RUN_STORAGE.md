# Historical run assets and exact-byte inspection

The restorer recovers seven historical artifacts and seven original opening or
declaration files. It reads the repository as its source and writes to a new,
disjoint inspection directory.

```sh
python -I -B SOURCE_ROOT/qualification/joint-generation/restore_historical_run_assets.py --source-root SOURCE_ROOT --out NEW_INSPECTION_ROOT
```

The output uses the original `qualification/joint-generation/` paths. It contains
the CORE telemetry, Q1 diagnostic and predictions, D1 profile and D2 timing, as
well as both row exports under `runs/codex-cloud-dynamic-train-headroom-h4/`:

- `paired-row.csv` contains the header and 9,216 completed pairings.
- `paired-row.csv.partial-v1` contains the header and 6,144 pairings retained
  from the first, failed export. Its 1,850,445 bytes are the exact prefix of the
  2,775,720-byte completed CSV.

The H4 inputs are two numbered parts of a single gzip stream. Reassembling
them and verifying the compressed and decompressed hashes recovers the original
CSV, including every CRLF. The partial export is cut at its recorded byte
length and checked against its own hash. The original postrun manifest pins
both exports, the successful export receipt independently pins the complete
one and the failure receipt records which partial output was retained.

The five earlier assets use their original paths plus `.gz`. Seven original
opening or declaration files are verified and copied. Twelve manifests,
receipts, protocols and fixture sidecars are verified in place. Older v1
source descriptors retain their twelve-file output and original receipt scope.

All compressed inputs, markers, sidecars and static relations are checked before
creating the output. The restorer rejects corrupt/truncated/multiple-member/trailing
gzip content, wrong sizes/hashes, duplicate/nonfinite JSON, unallowlisted paths,
symlink paths and existing/overlapping output roots. It assumes a trusted local
filesystem, not protection against hostile concurrent mutation or power-loss atomicity.
If an output write fails, keep the partial inspection directory as incomplete;
there is no automatic retry or overwrite.

NPZ is handled only as complete original bytes with length and SHA256 checks. No
arrays are deserialized, no ZIP content is extracted, and no prediction is computed.
The recovered Q1 diagnostic's original relative `predictions.npz` reference is
checked against the actual recovered NPZ, with no fallback to a source-tree raw copy.

The v2 output contains fourteen historical files and two separate
`inspection-metadata/` files. `RESTORATION.json` is created only after output reread
and verification completes; without it, the overlay is incomplete. A receipt never
excuses later missing/changed files. This is a partial inspection overlay, not a
complete checkout: no models, native library, source modules, selection/results
outside these targets, pstats or `.git` are copied.

CORE telemetry supports static dual-manifest/ADMIN inspection, but its old diagnostic
still needs the large selection and has an audited historical evaluation-source SHA
mismatch. Restoring telemetry does not make that old runtime reproducible. Q1's old
producer needs T11 models and a fresh protocol-only directory; D1/D2 producers perform
real model and timing work. All remain outside this storage recovery procedure.

Original failed scientific outcomes, cost ledgers, timing outliers, reuse limitations,
source identities and sealed/opened state retain their original meaning. Historical
absolute paths and commands in receipts are preserved as history, not instructions
for this inspection. The repository's other artifacts and any unknown external
readers are not asserted to be fully restored or transparently gzip-aware.
