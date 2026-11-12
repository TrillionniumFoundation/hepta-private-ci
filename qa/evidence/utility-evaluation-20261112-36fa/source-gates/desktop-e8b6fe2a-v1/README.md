# Exact e8 desktop source-gate evidence

This is a new independent desktop execution against commit `e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd`, tree `b607ff5f50812c5e0f932d7dae18d4c74f1269cb`. It does not resume or replace the unavailable cloud 19aa runs, or transfer the earlier 91d/6d results.

## Actual results

The source-gate job `1a1cf209cdd-2564-199e` ended with normal exit 1, without timeout or output truncation. Its final status confirms complete durable output and terminal publication. The frozen v2 driver used the original source-closure command with 600 seconds, caller self-test with 300 seconds, and full caller verify with 4800 seconds. All three entrypoints actually ran; none are recorded as not_run.

| Gate | Actual result | Evidence |
| --- | --- | --- |
| Source closure | Failed, original command exit 1, no timeout | Original unittest output says Ran 357 tests, FAILED (errors=28). It contains 343 explicit ok methods and 14 distinct failing methods generating 28 error records/subtests. |
| Caller self-test | Passed, exit 0 | New actual e8 execution; original 48-byte log and original runner JSON retained. |
| Full caller verify | Failed, exit 1, no timeout | Original caller set mismatch: learning_source_bound_training_stage_readback unexpectedly calls from codex-rs/hepta-agentd/src/cell_q24_training_command_readback_service.rs. |

The source-closure runner JSON's original observed_passed_tests=329 and observed_failed_tests=28 fields are retained unchanged. Those are runner-derived fields, not a claim that only 329 test methods explicitly passed. The separate derived-counts-diagnostic.json records the reconciliation. All 28 error records report the same protected required_order mismatch in cell_q24_training_model_lane.rs; the raw log contains no PermissionError. The clone permissions were not changed to turn this result into a pass.

The full caller failure is independent of the two protected-order leaves. The separate 381-row diagnostic cannot clear the caller-set mismatch.

## Source and record preservation

Every original run result, dispatch/start/terminal record, gate raw log, gate-final.json and retained-manifest.json is preserved byte-for-byte. gate-summary.json is the original pre-package snapshot and may say package=pending; the final state is gate-final.json and run-result.json.

The four original retained manifests enumerate 53 original files. Their retained parts are placed at the original relative paths. Identity-encoded files also have direct readable copies. The seven large inventory checkpoints are supplied as original gzip parts, since each original JSON is 5,432,085 bytes. All seven have the same SHA256:

`a3077b5e249aadb856c4ec56a0cd4ef4b1bb83785a33fbd76866cf0fbd1393dd`

The original inventory contains 14,741 file entries. Baseline and every phase's before/after inventory match exactly. Source bytes and recorded modes stayed unchanged.

For a retained manifest entry, concatenate its parts in listed order. If encoding is gzip, decompress the concatenation; otherwise use it directly. Verify the resulting length and original_sha256 from that same unchanged manifest. Each individual Git blob is less than 500,000 bytes. No original inventory JSON was regenerated.

The compressed inventory concatenation is 1,224,091 bytes with SHA256 `5408870f163f6f1aba95160160b6de0fa8b3fd447ad18d283dae0e019c9c7ce8`. Each binary part was uploaded with its exact Git blob SHA. Because the connector's binary fetch refused UTF-8 decoding, every inventory-readback-companions/*.b64 file was fetched completely, compared to the encoded original chunk, decoded, and all chunks were joined and decompressed. The reconstruction matched the original JSON's full length and SHA256. The companions are transport readback evidence, not replacement inventories.

The source-closure forwarded.stdout.log was recovered from the fully observed 144,917-byte child log and the observed 1,466-byte wrapper suffix. The reconstructed 146,383 bytes exactly match the independently observed original full forwarded-log SHA256 `68c797041ec2001a07b529f00eaf85a74b7d3ee8f650e6d850acf62990c72aa0` and Git blob SHA. This recovery is distinct from claiming a second full direct file read.

The complete 5,154-byte supervisor stdout is retained. The SDK files preserve original serialized native tool payloads; they are supporting control-plane observations, not changes to the original gate records.

## Separate 381-row protected-order diagnostic

Job `1a1cf3fd260-2564-19d4` used the same unchanged exact e8 clone and an external reviewed CALLERS manifest. It ran the repository's original _verify_protected_files over all 381 protected rows and checked 313 source input files before/after. It finished in 4.386671673 seconds with exit 0: 381 passed rows, 0 failed rows, inputs unchanged. Its explicit status is passed_scoped_diagnostic and full_gate_status is not_run.

The script checked that only the two reviewed required_order leaves changed from "if owners" to "&& owners". It did not edit the clone, register callers, run source closure, run the complete caller gate, or run Rust tests. The input packet contains four prepared files; the bootstrap extracted only CALLERS.toml for this diagnostic. The complete original 133,715-byte diagnostic report, empty stderr, run metadata, script, bootstrap, launch receipt, supervisor output and final status are preserved separately under protected-rows-diagnostic/.

## Qualification limits

These are source-mechanism and diagnostic results. They do not establish real authorized task A, an independent B evaluation, a later real consumer C, ordinary daemon/Root cold recovery, Adopt, complete business NoUpdate, or objective fraud. Old unavailable cloud executions remain Unknown. The current e8 source gates remain failed even if a later source repair succeeds.

package-map.json is a newly generated repository-placement manifest. It does not masquerade as an original runner record. Its entries point to immutable blobs containing the original records and clearly marked derived/readback material.
