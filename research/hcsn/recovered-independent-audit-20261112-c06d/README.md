# Recovered independent C2 checkpoint audit

The original read-only audit is now observed as passed for all six bounded checkpoint continuations. It reports 26 already executed optimizer calls, 554 rehashed bound files, and zero optimizer calls in the audit. This evidence closes retrieval and consistency auditing of that diagnostic. Independent complete C2 training replay remains **0/6**, with **HOLD_NO_GO** unchanged.

This is an isolated evidence successor of [#6173](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6173), based exactly on `3d2451ebfcaf19912a77a5a888d01c55f7a9dca3`. The original branch and records remain unchanged.

## Exact recovered originals

| File | Bytes | SHA-256 |
| --- | ---: | --- |
| [AUDIT.json](AUDIT.json) | 5,562 | `342ce2498e6e95c9233564aa7210058fc0abb98115059f5a6b86d156bb96af70` |
| [ARCHIVE.json](ARCHIVE.json) | 550 | `e1a0213e3f8a86c902912f7f9fb67605681f8d3dc033bc1feb839f1d5b993e45` |

Both files were read as complete UTF-8 files from the configured desktop and published without changing any bytes. [READBACK.json](READBACK.json) retains their independent file versions, source identities and publication observations. The read is an independent-file read, not an atomic snapshot of multiple files.

The frozen source and inputs already exist in this commit's parent and are used without duplication:

| Input | Exact inherited path | SHA-256 |
| --- | --- | --- |
| Producer summary | [SUMMARY.json](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/3d2451ebfcaf19912a77a5a888d01c55f7a9dca3/qualification/hcsn_differentiable/replay_v1/evidence/real-recovery-20261112-4092/SUMMARY.json) | `c8dcd62b2391a730c5d21ecd6dfa4b4b1ad0e4d71ae9c23fbaafa29f2502eeb5` |
| Six original selections | [SELECTION.json](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/3d2451ebfcaf19912a77a5a888d01c55f7a9dca3/qualification/hcsn_differentiable/replay_v1/SELECTION.json) | `6271b8dd1859b8a124f5ecd06ba307c0f9ebcdc5e6f86a9d164c4ac374cdbd55` |
| Read-only audit source | [audit_replay.py](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/3d2451ebfcaf19912a77a5a888d01c55f7a9dca3/qualification/hcsn_differentiable/replay_v1/audit_replay.py) | `1174ad3615ebfaa27c21f308f7f2cce16fad6ddada8e0c416c8653bc04e9a48e` |

The audit source was frozen at `d8bcfac912c3cc24faeadf3bb234d1df5107f088` before its original invocation. No audit, producer, model or workflow code changes are made by this evidence PR.

## Independent review

[REVIEW-v2.json](REVIEW-v2.json) is a freshly generated review from new exact Git reads and original desktop file reads. It independently checks all six selected origins, epochs, all three worker identities, per-mode counts, batch/loss/gradient receipt concatenation and reference/resume final serialized file identities.

| Fit | Selected epoch | Positive physical calls | Final logical increment | Reference/resume byte identity |
| --- | ---: | ---: | ---: | --- |
| hcsn-s101-lr0.001 | 116 | 4 | 2 | Equal |
| hcsn-s101-lr0.003 | 76 | 4 | 2 | Equal |
| hcsn-s211-lr0.001 | 126 | 4 | 2 | Equal |
| hcsn-s211-lr0.003 | 50 | 4 | 2 | Equal |
| hcsn-s307-lr0.001 | 127 | 4 | 2 | Equal |
| hcsn-s307-lr0.003 | 72 | 4 | 2 | Equal |

The physical count is `6 × (reference 2 + producer 1 + resume 1) + omit-Adam 1 + pre-publication-crash 1 = 26`. The resumed final state is two logical updates beyond each selected origin. The frozen audit independently deserialized full model, Adam, RNG and cursor state, verified Adam increments, decoded the actual crash temporary and detected the omitted-Adam control. This new review does not deserialize those checkpoint files again; its decoded-state finding is explicitly attributed to the frozen recovered auditor.

The auditor defines its own recursive comparison and does not import the producer model or comparison helper. It uses the same Torch deserializer/runtime and operator-controlled files. Its six syntactic `torch.load` sites use CPU and `weights_only=True`; it calls no training methods. This is a separately implemented consistency audit, not hostile-host attestation.

The generic JSON loader's non-finite-constant handling and the empty-Adam-map vacuity remain documented in REVIEW-v2. The fixed-byte producer writes finite JSON, and no evidence shows an empty optimizer map in these selected trained checkpoints. These hardening limits do not create a new result or expand its scope.

The earlier 5,840-byte independent review is presently inaccessible with the scratch environment. Its recorded identity is retained in REVIEW-v2; its original bytes are not invented or represented by this new review.

## Reconciliation and archive status

[OPERATION-RECONCILIATION-v1.json](OPERATION-RECONCILIATION-v1.json) preserves the retained original tool objects and timeout history. It was reencoded from those unchanged objects with the same serialization and has the expected 13,207 bytes. The inaccessible earlier local file's SHA-256 is pending, so this publication does not assert byte identity to that earlier scratch file.

[OPERATION-RECONCILIATION-v2.json](OPERATION-RECONCILIATION-v2.json) preserves that previous record and adds later observations. In particular:

- The native audit's original request timed out, and its actual completed AUDIT document was subsequently recovered. No replacement training job was started.
- The diagnostic archive request launched job `1a1ceb6682a-2564-17f9`. Its receipt and an independent file-info read agree on a 7,070,892-byte `originals.tar.xz`, SHA-256 `f3f6992f31d7ab85a10eaa727dfc894fdb72ef5dafbba6bc43fc36d23a899dc7`. Receipt `original_files=118` is not asserted to be the tar member count; archive creation also adds the manifest.
- This review has not fetched the entire diagnostic archive or observed it published to Git. The archive process's authoritative terminal status was not retrieved here.
- A separate original 11,397,159-byte **input ZIP** was published at [Draft #6214](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6214), head `917e4886658ae9f0c342eb1fa0f545d79c39e2c8`. This PR/head was independently read through GitHub after the native publisher's 373-byte stdout was recovered. The retained ACK timeout remains in v1; the later Git publication is an observed effect. The native publisher's authoritative terminal status was not retrieved here. This input ZIP publication is distinct from the complete diagnostic originals archive.

## Qualification boundary

This evidence publication performs **zero new model runs and zero new optimizer calls**. Original complete full-training replay remains **0/6**. The original C2 job `1a1c74f3308-be2a-75` and lifetime optimizer totals for the two SIGTERM attempts remain **UNKNOWN**.

These old-operator checkpoint continuations do not qualify the newer uniform, graded or dense joint diffusion/delay operators, scientific superiority, sufficient training, production adoption, or new independent task sources. No HOLD or admission gate is relaxed.
