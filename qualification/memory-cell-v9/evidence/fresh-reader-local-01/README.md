# Real training followed by fresh Python readers

This archive preserves one independent development qualification of the V9
catalog and byte MLP representations. Its four real Adam fits completed before
ten new reader processes started. All four trained representation/type pairs
recovered 4/4 written values with the original source support; the paired
zero-step controls recovered 0/4. Two catalog-removal controls were rejected.

The reader is an independent Python float64 implementation of the native-format
artifacts. This receipt does not establish Rust-native execution, language-model
fine tuning, held-language quality, compression, or complete lifecycle cost.
The source facts were separately authored development data; the frozen V9 held
fixtures were not used.

## Preserved evidence

- `receipt.json` is an exact copy of the original top-level receipt.
- `ARTIFACTS.json` identifies every complete real trained/zero artifact and the
  deliberately invalid catalog-removal controls, plus executed source hashes.
- `ARCHIVE.json` lists all original evidence files and ordered transport parts.
- `raw-evidence.tar.xz.part-*` preserve all 61 original files losslessly, including
  the actual numerical models, original catalog models, source export, frozen
  development protocol, worker requests/responses, process receipts and errors.

Each transport part is at most 400,000 bytes. No dependency or V6 source tree is
copied here. The executed source identities are retained instead. The run used
the recorded base checkout plus the then-uncommitted fresh-reader additions;
the base commit alone does not identify those new files.

## Restore and replay

Run `python restore.py /absolute/new/directory`. The script verifies each part,
the compressed archive, the complete member inventory, and every member's exact
bytes before restoration. It performs no training.

The restored original requests retain their original absolute artifact paths as
evidence. For an inference-only replay, copy one `readers/*/request.json`, change
only `artifact_path` to the corresponding restored `artifacts/*.json`, and feed
that new request to `learning/fresh_reader.py read` with Python's `-I -B` flags.
Keep `artifact_sha256` and `support_sha256` unchanged. Record the new request and
response separately; their PID, timing, and request digest will differ. This
replay requires NumPy and the reader source, but no V6 trainer or target export.

To rerun optimization as a separate experiment, use
`learning/fresh_reader.py qualify --export RESTORED/TRAINING_EXPORT.json --output NEW_DIR`.
The existing V6 training runtime must be available at its default location or
through `--v6-root`. Do not overwrite this retained run.

Process wall measurements include interpreter startup and shutdown. Reader
compute measurements are nested inside those durations and must not be added
again. The evidence does not provide continuous RSS byte-time or complete
maintenance cost.
