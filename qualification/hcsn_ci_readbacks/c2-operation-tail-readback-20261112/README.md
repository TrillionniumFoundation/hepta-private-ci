# C2 immutable operation-result tail readback

**HOLD_NO_GO / all_closed=false. Full independent replay remains 0/6.**

This evidence-only successor to #6255 freezes the complete six-page readback of the already-existing immutable `h` operation `185441d37ac6e5e976f67a3a142304d21f618234183b12ef17c1152a15d57f7d`. It did not dispatch a new operation, model, optimizer, native training process, or idempotency key.

The six pages reconstruct exactly 87,789 bytes with SHA256 `d3c201e61f9b5e0511883431ed136c05c1f426bd175f83ece9921aeec3703051`. The nested result is the final 65,536 bytes of `/home/qian-qi/hcsn-real-replay-c06d-export-v1.zip`, from offset 11,331,623 through EOF 11,397,159, with SHA256 `ba3c005f7ed325d96a6863f429b5b4cb9f8244f76633e4d8097c8a3392d21d18`.

The ZIP EOCD independently proves 556 entries and an 83,624-byte central directory beginning at offset 11,313,513. The immutable returned range begins 18,110 bytes later. It therefore contains 441 complete central-directory records and excludes the first 115. `INDEX.json`'s central record is visible, but its local header and compressed bytes precede the returned range.

This is a bounded negative result: the existing operation result is fully recovered, but it does not contain the missing central-directory prefix or `INDEX.json` data. It cannot close the six original start-parent identities, per-fit active wall, or non-refunded remaining-wall ledger. Those fields, lifetime optimizer calls from historical cancelled attempts, and the original controller terminal state remain `UNKNOWN`. No full replay is authorized or completed by this evidence.

Files:

- `raw/operation-result-page-*.json`: all six immutable API page bodies, fully recoverable and hash-bound.
- `raw/zip-tail-offset-11331623.b64`: separately frozen exact ZIP tail bytes.
- `inspect_operation_tail.py`: stdlib-only independent byte/hash/EOCD/central-record verifier.
- `test_inspect_operation_tail.py` and `TEST.log`: exact bounded-result test and complete log.
- `RESULT.json`: machine-readable result with explicit non-closure and preserved `UNKNOWN` values.
- `RAW-MANIFEST.json`: byte sizes, SHA256 identities, and recovery procedure.

No production adoption or resource re-admission is proposed.
