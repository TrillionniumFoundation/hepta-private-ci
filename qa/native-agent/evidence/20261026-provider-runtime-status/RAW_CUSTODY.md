# Raw evidence custody

This initial record is prepared from exact original archives transferred from the executing host. Both full archive hashes, all direct regular members, and their internal manifest bindings were independently checked locally. The host's 95-file snapshot and original archive-production receipt are preserved separately from derived report text.

| Archive | Bytes | SHA-256 |
| --- | ---: | --- |
| `archives/original-receipts.tar.gz` | 159,013 | `40640a1446747727df72701a5d8c69b79eedb1c95b715bdb2e05692e08e33c5a` |
| `archives/independent-reviews.tar.gz` | 186,284 | `02dd83a4825418cb8e3b18154b4ba93b1150424f05bf71e1e5cd29e15a05711e` |

The first archive contains 95 original files totaling 838,857 bytes and `manifest.json` (18,980 bytes, SHA-256 `412de260857a2a93f256c1b272fbc5f19c569715ae69def553981a77c131b905`). The second contains nine original review/raw artifacts and `engineering-independent-reviews-v1/MANIFEST.json`. Its nested archives remain unchanged. No original log, source capsule, test output, or receipt was spell-corrected or reformatted.

**Remote archive publication/readback has not been attested by this initial record.** This file intentionally contains no future commit ID or guessed URL. After the archive commit is pushed, the publisher must independently read both full archives from that exact remote commit without local alternates, verify these byte counts and SHA-256 values, retain the readback receipt, and append a separate custody commit with immutable archive links. Preserve this initial record in Git history; exclude any generated file manifest from its own hash set.

This custody record is about byte preservation. It does not rerun a test, establish the availability of the executables, qualify a model route, or replace any failed gate.

## Independent remote readback completed

The two full archives were independently fetched from archive-bearing commit `9d2e428184193469162b4374eafa3274db5dca04` into a fresh bare Git clone with no local alternates or shared local object store. Both complete byte counts and SHA-256 values matched in 14.745277837 seconds. The receipt is [remote-readback.json](remote-readback.json), SHA-256 `957192a2e7f6d250d3289b252469ec1aff89c4a57f536389bc5f65dc27395ae3`.

- [Original validation receipts](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/9d2e428184193469162b4374eafa3274db5dca04/qa/native-agent/evidence/20261026-provider-runtime-status/archives/original-receipts.tar.gz)
- [Independent review and raw bundles](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/9d2e428184193469162b4374eafa3274db5dca04/qa/native-agent/evidence/20261026-provider-runtime-status/archives/independent-reviews.tar.gz)

The first readback launcher failed before any clone or network call because its helper was not materialized at the referenced path. That original failure remains retained; the successful second launcher verified the helper's exact source hash before use. No test, model request or runtime canary was repeated by either readback step. The initial custody text is retained in Git history and [this exact copy](provenance/history/initial-RAW_CUSTODY.md).
