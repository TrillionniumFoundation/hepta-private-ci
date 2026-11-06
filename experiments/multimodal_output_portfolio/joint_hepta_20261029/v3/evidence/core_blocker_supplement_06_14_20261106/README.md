# Core evidence supplement: units 06 through 14

This is a separate, immutable supplement. The earlier Core v3 evidence archive is unchanged. The Linux rejected-donor witness in PR #5061 is already published independently and is not duplicated here.

## Preserved material

The archive contains 119 files and 26,089,118 original bytes: every frozen original, candidate, patch, review and verification receipt for the units below; the rejected Core10 proposal and its distinct Core10b replacement; immutable causal source snapshots; complete original GNU and musl logs for #5025; the complete GNU log for #5035; explicit case-evidence tables; and the original #5025 GNU execution-log artifact ZIP with its GitHub metadata and scope receipt.

| Unit | Narrow scope | Publication status at capture |
| --- | --- | --- |
| 06 | Cwd-relative turn differences | #5038 |
| 07 | Hook MCP scope and metadata | #5042 |
| 08 | Mismatched environment fixture | #5043 |
| 10 | WebSocket fixture proposal with a single-use helper | Rejected; retained unchanged |
| 10b | Existing shared permission-profile helper | #5055 |
| 11 | Cold-resume named-profile workspace roots | #5056 |
| 12 | Two private-metadata endpoint fixtures | #5059 |
| 13 | Suspension recovery with the original request identity | #5062 |
| 14 | Plan recovery before provider output | #5063 |

Publication and static verification do not establish native success. Each unit's manifest records what actually ran locally: the pinned formatter and forward/reverse patch byte checks. Separate spelling and boundary receipts retain their actual scope. Native Rust compilation, Clippy and test results must come from a source-bound CI execution containing the corresponding change.

## Runtime evidence limits

The #5025 recovery receipt proves five explicitly emitted passing cases, associated with their executed binaries and zero ignored cases. Two further cases lack an emitted result: `cold_sigkill_after_provider_output_is_not_recoverable` and `cold_paginated_sigkill_recovery_uses_canonical_context_tail`. They remain **pending evidence**.

The original GNU artifact is 11,575,704 bytes with SHA256 `88d61da937024189297492d7941f35b91ae900e00161b71db2934baa02c3d9ed`, matching the freshly read GitHub artifact metadata. It contains one compressed Bazel execution log. The prior in-memory inspection found execution paths and CAS references, without standalone test-log or test-XML contents. Those references are not individual passing-case evidence. The 88 MB decoded payload is not duplicated, and it was not decoded again for this supplement.

The #5035 case table records nine earlier failing cases with explicit passing output at that source, while retaining the remaining failures and absent-case evidence boundaries. Repeated CI attempts are not independent samples. That source predates units 06 onward; this package does not treat it as validation of those later repairs. No queued, skipped or cached job is relabeled as a new execution.

## Restore and inspect

The unchanged original archive still has 28 raw parts pinned by the unchanged `INDEX.json`. This version transports those same archive bytes in 29 independent gzip containers, each with at most 440,000 decoded bytes and at most 450,000 container bytes. The fixed `TRANSPORT.json` binds every container and decoded segment to the original archive. Original part order, exact file paths, source paths, regular-file permissions and SHA256 values remain unchanged.

```sh
python -O restore.py /absolute/path/to/bundle /absolute/path/to/new-destination
```

The destination must not already exist and must lie outside the bundle. The restorer verifies the fixed index hash, all part and archive hashes, and the exact unique regular-file member set before writing restored files. It rejects unsafe paths and special-file permissions, writes nothing inside the input bundle, and reports only to stdout. The new reader adds the reviewed bounded single-member gzip transport: it rejects trailing data, extra members, truncation and excessive expansion, checks the reassembled archive, then checks each of the original 28 raw-part identities before using the unchanged exact-member restoration checks. The original index, archive and 119 source-file hashes are unchanged.

Restoration integrity is separate from the underlying runtime claims. Restoring this archive does not run a model, a native test or the rejected Linux scheduling witness.

## Preserved transport failure

The first version's narrow text-only spelling check passed, but it did not cover all binary parts. The subsequent whole-packet check used the unchanged repository configuration and the exact CI options. It failed with exit code 65 because a raw middle XZ part was interpreted as text. Both original receipts and the entire first-version bundle remain preserved. This version changes the transport containers, without adding a spelling exclusion, changing an original evidence byte or rerunning any native test or model.
