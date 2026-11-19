# Five historical run assets: exact-byte inspection recovery

This is a storage layer for five existing historical artifacts, not a new experiment,
scientific pass, runtime reproduction or full-branch CI claim. Existing scientific
reports, manifests, protocol/source pins and one-shot/opening markers are unchanged.
The original five large files are stored as their same full paths plus `.gz`.

Run the new stdlib-only restorer from any directory with two explicit **repository
roots**. Replace SOURCE_ROOT with this repository's absolute path; NEW_INSPECTION_ROOT must not exist and
must be disjoint from SOURCE_ROOT, not equal to it or inside/above it.

```sh
python -I -B SOURCE_ROOT/qualification/joint-generation/restore_historical_run_assets.py --source-root SOURCE_ROOT --out NEW_INSPECTION_ROOT
```

This command performs storage restoration and static verification only. It never
imports an old producer/diagnostic/model or opens a scientific test. Do not use an
old Q1, CORE, D1 or D2 program as a restoration check, and do not remove RUNNING or
opened-test markers to make an old program run.

The five exact original files are recovered beneath NEW_INSPECTION_ROOT with the
complete `qualification/joint-generation/...` paths:

- `runs/codex-cloud-core-c1-t2/telemetry.json`
- `runs/codex-cloud-efficient-r2-decision-diagnostic-q1/diagnostic.json`
- `runs/codex-cloud-efficient-r2-decision-diagnostic-q1/predictions.npz`
- `runs/codex-cloud-efficient-r2-shared-profile-d1/profile.json`
- `runs/codex-cloud-efficient-r2-shared-timing-d2/timing.json`

Seven original small opening/declaration/latch files are validated and copied
byte-for-byte to preserve historical state. Nine original manifests/ADMIN/protocol/
fixture sidecars are read in place from SOURCE_ROOT and checked against complete
size/SHA256 pins in `compressed-historical-run-assets-manifest.json`. Those sidecars
are not copied to the inspection output, and their historical pins are not rewritten.

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

The output contains twelve historical files and two clearly separate
`inspection-metadata/` files. `RESTORATION.json` is created only after output reread
and verification completes; without it, the overlay is incomplete. A receipt never
excuses later missing/changed files. This is a partial inspection overlay, not a
complete checkout: no models, native library, source modules, selection/results
outside the five targets, pstats or `.git` are copied.

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
