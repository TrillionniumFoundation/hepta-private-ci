# Raw numerical and recovery evidence

These ASCII base64 files are ordered slices of one deterministic gzip/tar stream.
Every encoded file is at most 80,000 bytes. `MANIFEST.json` binds each encoded
part, decoded slice, reconstructed archive and the per-logical-file hash index.

The archive preserves the excluded early run01, qualified run02, all recorded
process receipts and fault checkpoints, private scorer ledgers, public model
arrays, independent numerical inputs, development failures and original campaign
source. No compiled binary is included. The compiler and binary identities and
exact build command are retained in `BUILD_IDENTITY.json`.

Download every part, `MANIFEST.json`, and `restore.py` together, then run:

```sh
python restore.py recovered-evidence
```

The destination must be new. The script verifies every layer before reporting
success, rejects unsafe archive paths and checks every restored logical file.

From the repository root, audit the restored qualified results with:

```sh
OPENBLAS_NUM_THREADS=1 python -m tools.hcsn.native_numeric_r19_20261102.audit \
  /absolute/path/to/recovered-evidence/results/run02 \
  --output /tmp/hcsn-r19-restored-audit.json
```

The old run01 remains excluded even when its archived checks passed. Restoration
does not extend finite numerical parity into learned-head, production, GPU,
energy, network, or whole-model adoption qualification.
