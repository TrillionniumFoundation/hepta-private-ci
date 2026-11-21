# E2 runtime metadata: blocked Stage A and completed increment

This append preserves two separately authorized engineering scopes and their original failures, sources, controls and terminal receipts. Stage A remained **blocked**. The later increment completed the declared package metadata closure. Neither result establishes an installed or working runtime, trained correction weights, or a fresh evaluation result.

The append parent is `2b70159464432181d0b2c9509588d74137148216`. The original seven correction files and prior execution evidence are unchanged. The correction executable source remains `dc3397c9e09e29861a0a4fe2267e8ef19e55db01`; an evidence publication head is not an executed training source identity.

## Actual outcomes and costs

| Scope | Actual terminal | HTTP attempts / complete cached responses | Observed application body bytes | Outer elapsed / scope limit |
| --- | --- | --- | ---: | ---: |
| Original Stage A | `BLOCKED_STAGE_A`, exit 2, confirmed complete durable logs | 54 / 53 | 16,604,448 | 134.8009338 s / 300 s |
| Separate metadata increment | metadata closure complete, exit 0, confirmed complete durable logs | 12 / 12 additional | 3,378,797 additional | 39.03839302062988 s / 120 s |

Stage A also observed 4,030,735,251 bytes of read-only access to its fixed 28 material paths. Both material workers reached confirmed terminals. The increment reused those retained observations and replayed the 53 cached responses; it performed zero material rescans. These byte categories are distinct, and the measured scope durations are reported separately from the earlier recovery, preparation and readback work.

The increment's cumulative ledger retains **66 attempted requests, 65 completed responses and 19,983,245 observed metadata-body bytes**. It does not erase or reclassify the blocked request. The old 3,600-second recovery window and old 300-second Stage A window remain closed. Unspent allowances from those scopes are not made available again by this append.

### Request 54 remains an explicit unknown

Stage A stopped at `https://pypi.org/pypi/requests/json` with `ScopeBlocked: declared metadata body exceeds remaining cap`; 172,768 bytes remained in its metadata-body allowance. `HTTP-054.partial` is preserved as the original zero-byte file.

The executed code did not preserve the response headers before that guard failed. **The declared Content-Length and original headers remain UNKNOWN.** Zero observed application body bytes do not establish zero physical network cost. No retrospective refetch was used to fill the missing old fields. The separately authorized increment's later response is separate evidence and does not repair the original observation.

## What the increment established

The final `OFFICIAL_METADATA_CLOSURE.json` is 258,077 bytes, SHA-256 `a7bf67d65bef981338a10d04ec78600932ca20fbd579fc3b4d52f2d664d25b55`. It contains 44 selected packages, 12 root requirements and 71 active dependency edges. All original 38 selections remain unchanged. The newly selected auxiliary versions are not claimed to reproduce a fully recovered historical runtime.

The corresponding material catalog records 11 retained complete wheels with official full-file SHA matches. A complete selected wheelhouse would total 4,109,714,899 bytes. The **conditional** remaining 504,322,940 bytes assume the retained inputs continue to match their recorded identities and that the stated partial ranges can be reused; this number is not a completed transfer.

Final installation, framework imports, runtime verification, CPU training encoding, model/native evaluation and optimizer updates were all **zero in these two scopes**. Wheel-body downloads were also zero. Stage B execution evidence is not included here, and this append authorizes no successor phase.

## Controls and failure history

The retained control records describe distinct source revisions. Their counts must not be combined into one experiment or treated as model evaluations.

| Record | Actual retained result |
| --- | --- |
| Stage A initial fixture run | 10 tests; 2 errors, 0 assertion failures; exit 1 |
| Stage A corrected prior run | 10 tests, exit 0 |
| Stage A final approved run | **11 tests**, exit 0 |
| Increment initial run | **12 tests**, exit 0 |
| Increment review-2 run | **15 tests**, exit 0; original `ResourceWarning` retained |
| Increment final run | **15 tests**, exit 0; warning no longer present |

The original local offline-replay SSL/import failure, its exact source, the corrected replay's full output, and the increment readback helper's retrieval warning are preserved. The retrieval warning was a readback interruption, not another scope execution. Earlier review-only source bundles and their original labels remain unchanged; executed source identities are bound separately by `SCOPE_CLAIM.json` and the actual finalization/outer terminal records.

The original [E2_INCREMENT_TERMINAL_REVIEW.json](E2_INCREMENT_TERMINAL_REVIEW.json) is copied byte-for-byte from root's independent review. [E2_FRESH_READOUT_RULES.md](E2_FRESH_READOUT_RULES.md) is likewise an unchanged interpretation note: it adds no execution allowance, preserves the four-task unit of analysis and lineage-specific comparisons, and does not infer retention or a Circuit/scaling result from this metadata work.

## Complete evidence and restoration

The new container preserves **176 files / 29,772,955 uncompressed member bytes** across the two source/review directories, two execution directories and four root review documents. It includes all 53 + 12 successful HTTP body originals, the failed zero-byte HTTP 54 original, full scope and outer logs, the original collection stdout and compressed cache envelope, every retained control/review failure and the complete metadata closure. Only 31 redundant H readback pagination envelopes are omitted from the archive; their source files remain untouched locally. No original observation is replaced by a generated summary.

The archive is a new deterministic USTAR+gzip container assembled from unchanged original bytes. Its numbered parts are real binary Git blobs, each at most 360,000 bytes, under the existing 512,000-byte blob gate. No ignore or allowlist is added.

```sh
cat STAGE_A_AND_INCREMENT_EVIDENCE.tar.gz.part??? > STAGE_A_AND_INCREMENT_EVIDENCE.tar.gz
sha256sum STAGE_A_AND_INCREMENT_EVIDENCE.tar.gz
tar -tzf STAGE_A_AND_INCREMENT_EVIDENCE.tar.gz
```

Use exactly the 29 part paths in `MANIFEST.json`, in ascending order. The restored archive is **10,248,647 bytes**, SHA-256 `412cd9263d8b08e5885c823e7a6b4c365e7c4878361c437ff511383b378221e1`. Extract into a fresh directory and check each member's listed size and SHA-256. Archived scripts are retained evidence and do not need to be executed. Packaging performed no new public-network request, ROG/desktop job, resolver replay, test, training encoding, model or native work. `PACKAGING_REVIEW.json` preserves a local publication-list shape error and its correction; the original archive bytes and experimental results were unaffected.
