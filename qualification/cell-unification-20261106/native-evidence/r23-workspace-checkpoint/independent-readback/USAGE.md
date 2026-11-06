# r23 independent closed readback

Run `python3 r23-independent-readback/read_r23.py --native-results native-validation-results` from the task root with the original `checkpoint-r23-closed.tar.gz` and exact extraction present. This invokes only Python standard-library reading, hashing, parsing and writes of new audit artifacts.

The retained `reused_source_reader.py` is byte-identical to the independent recovery reader. Its full original framework input (12,259 entries) is rehashed through all 1,367 original directories, then all 188 original r23 source files are hashed and overlaid to independently compute source49 `be34ab1afe622ad3b8f030c8c5018f4f54fbc304`. Immutable Git commit/root responses are comparison inputs after computation, never substituted for the tree calculation. `INPUT-ORIGIN.json` preserves the original reserialization caveat.

The reader verifies all 211 regular archive members and 210 INDEX rows, transport modes and exact extraction, source manifest/declared Git modes/raw lock, original no-package-selector 193-member workspace scope, raw process return 100, matching receipt/resource exit and outer job terminal 100. Original full-log rows are independently parsed before the sole Summary: 20,228 unique tests = 20,220 PASS, 7 FAIL, 1 TIMEOUT. Eight footer repeats are excluded. The original 130 reported skipped tests remain a count; no skipped identities are invented. Every one of the eight failure block offsets, bytes and hashes is checked against the full original log.

`INDEPENDENT-READBACK.json` is a new audit, not a repair qualification. The workspace gate remains FAILED. The per-test timeout is distinct from the outer runner's `timed_out=false`. No finalizer, build, Rust test, original evidence, active log, native source or publication ref was touched.

`PARSED-EXECUTION-ROWS.json.gz` is lossless UTF-8 JSON with gzip mtime zero. Its exact uncompressed byte count/hash is in the report. All files needed by this reader are listed in HANDOFF-MANIFEST.json; original archive content is referenced instead of duplicating 188 source files here.
