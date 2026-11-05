# Restore the exact native certificate inputs

The five `fit_*_REQUEST.json.gz` logical inputs are stored as raw byte parts so
that each repository blob respects the existing 512,000-byte limit. Each part
is at most 479,000 bytes, using the same `.part0000` / `.parts.json` format as
the preceding `native_bellman_replay/bridge_io.py` research package.

The parts are slices of the original frozen gzip bytes. JSON was not rewritten,
and gzip was not recompressed. `INPUT_MANIFEST.json`, all scientific protocols,
executed sources, recorded results and original logical input hashes remain
unchanged. The earlier publication commit retains the original large blobs;
the current checkout uses parts instead.

For the existing record verifier with its fixed `inputs/` path, restore the
**complete original logical package** into a new directory outside the checkout.
From the repository root:

```sh
python3 -B tools/hcsn/wsp_native_value_20261105/native_certificate/restore_inputs.py \
  --package-source tools/hcsn/wsp_native_value_20261105/native_certificate \
  --output /tmp/native-certificate-package-restored
```

Pass `/tmp/native-certificate-package-restored` to the existing verifier's
`--package` option. The resulting directory contains all 143 original logical
package files plus the unchanged `FINAL_PUBLISH_MANIFEST.json`. Their original
lengths and hashes are verified before writing and checked again after writing.
The original fixed `inputs/` paths now exist. New storage documentation, parts,
and the helper itself are not needed in this restored original package.

For drivers that accept an independent `--inputs` directory, an inputs-only
mode is also available from this package's `native_certificate` directory:

```sh
python3 -B restore_inputs.py --source inputs --output /tmp/native-certificate-inputs-restored
```

The output directory must not exist, and its parent must exist. Each command
validates the original input manifest, every part, and each complete gzip hash
before creating any destination file. It copies the unchanged input manifest
and five small reference files, producing the original eleven-file input
directory. Pass that directory to the existing `--inputs` options documented
in the package README. The frozen drivers do not need a storage-format change.

The original `FINAL_PUBLISH_MANIFEST.json` describes logical research files:
the five listed request files are materialized by this step. The per-input
`.parts.json` files describe their physical repository representation. A raw
checkout is therefore not expected to contain the five original large paths.

`../INPUT_STORAGE_VERIFICATION.json` records byte-for-byte reconstruction against
the preserved originals, complete original-package restoration, and a one-byte
corruption rejection. The negative
control created no output directory or original-name output file. These checks
validate transport only; they are not new native qualification, model execution,
training, or efficacy evidence.
