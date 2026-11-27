# Mac c895 memory and bulk-lane read-only review

This packet preserves the completed read-only review of two original Mac Intel failures at source `c89540598693697577cda8cba31cb07f6ce65317`, tree `5a7c897a33e4eef48ea8f4bf52eaf48ea7c866ae`. It contains fourteen full source files, exact byte slices from original job `130619380498` in run `43048568477`, their indexes and the unchanged review report.

**Neither root cause is uniquely determined.** No source, threshold, assertion, timeout or retry was changed. This work ran no native command, host command, model request or new CI campaign.

## Original observations

- Memory: `product_v2_reports_peer_truncation_before_aggregation` has an original FAILED row. Its target subsequently timed out in 300.5 seconds before the complete libtest failure summary. The current trace does not identify the assertion. The prior b054 0/16 observation is not transferred here.
- Code-mode: the actual failure is the second ten-second wait for 129 bulk result frames, after the first delegate-start barrier. The queue capacity is 1024, not 128. The log does not show final queue length, completed events, final alive state or encoder time.
- Cleanup observations in the report are static lifecycle facts, not established causes. No cleanup, permission, pool or deadline fix is proposed by this packet.

## Offline verification

Run:

```sh
python3 verify_packet.py
```

This checks every packet member, all fourteen complete source hashes and Git blob identities, the exact saved raw slices, current-case failure markers and the report's unchanged uncertainty boundary. It performs no subprocess or network operation.

The original full 2,677,695-byte Mac log and the complete c895 NUL tree inventory already belong to the separately archived original blocking packet. They are referenced by exact member, SHA256, size and its three actually created Git part objects in `FULL_ORIGINAL_REFERENCES.json`. They are not duplicated here, and the small packet does not claim to independently reconstruct the entire Git tree from fourteen files.

With those original members available, additionally run:

```sh
python3 verify_packet.py --full-raw PATH_TO_ORIGINAL_MAC_LOG --full-tree PATH_TO_ORIGINAL_SOURCE_TREE
```

That optional mode verifies every saved slice byte against its original offset and all fourteen source entries against the original complete inventory. The producer ran both offline modes and retained their receipts outside the frozen inner packet.

## Contents and publication boundary

`SOURCE_INDEX.json` binds all fourteen full files to the reviewed source. `RAW_SLICE_INDEX.json` supplies byte offsets, one-based line intervals, byte counts, SHA256 and Git blob identities. Slices preserve their original line endings. `ORIGINAL_RAW_EXCERPTS.json` is the earlier human-readable derived projection, preserved without replacing the byte slices.

`READ_ONLY_REVIEW.json` and `SOURCE_AND_RAW_AUDIT.json` are the original completed records, copied unchanged. `FILE_MANIFEST.json` binds all other regular members, including this README and the verifier. The compressed packet is a new evidence artifact; it is not a re-execution or a source change.

Actual immutable Git creation and full UTF-8 text readbacks are recorded in the outer publication index. The raw compressed blob's complete remote readback is the root's separate immutable-carrier step. No ref is changed by this packet.
