# Native forward evidence transport

`evidence_compact/` preserves435 logical files (35,525,714bytes) with exact SHA256 restoration. Its55base64 parts are at most120,000ASCIIbytes each; payload4,920,516bytes uses deterministic lossless binary XOR/byte shuffle and XZ. No floating precision is reduced. All input TSV/NPZ, formal and failed developmental outputs, wholeworker receipts and original raw-symbol profiles are retained. Five generated executable bodies are excluded; `BINARY_IDENTITIES.json` records their exact bytes/hash and source-qualified status.

Use the supported restoration environment in `RESTORE_ENVIRONMENT.json`; NumPy/zlib deterministic NPZ reconstruction is checked against every original SHA. From any directory:

```sh
python evidence_compact/RESTORE.py restore --source evidence_compact \
  --destination /absolute/fresh/learned-native-evidence \
  --receipt /absolute/fresh-roundtrip.json
```

Destination must not exist. Restored paths are relative to `tools/hcsn/learned_native_r19_20261102/`; the original files are not overwritten. All logical identities are directly readable in `LOGICAL_FILES.json`. Packing additionally performed a complete fresh restoration, recorded in `FRESH_ROUNDTRIP.json`.

Qualification cost remains8.673383CPU seconds; the separate posthoc packaging CPU12.331699seconds includes both compression trials and full restoration and is recorded in `EVIDENCE_PACK.process.json`. Early development overhead boundaries are disclosed in `COST.json`.
