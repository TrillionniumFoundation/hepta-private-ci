# V9 independent read-only archive review request

Status: prepared and not dispatched. This is a proposed second inspection of an already preserved archive. No native test, archive export, process, PTY, or branch update has been started by this request preparation.

The full original archive is already available as Git blob `f95aa80b21724f0462b594027eec7f361247a8c2` (2,392,536 bytes; SHA-256 `568c36f18b539a80e9894027f774e9711303eda8470d1ee570a4a231c68502b4`). Its native exporter verified all 116 members / 115 payload files. An independent V8 transfer verified all 37 binary chunks, the full SHA-256 and Git blob, and a 540,000-byte prefix obtained by the earlier immutable read-operation route. This proposed review does not replace or relabel those existing checks.

## Fixed request artifacts

| Artifact | Git blob | Bytes | SHA-256 |
| --- | --- | ---: | --- |
| Read-only Python validator | 03821f099928aa51af3d3d885857ef66ed360fd7 | 26319 | 8cf3c4237abd388b767269e2a42472e78a5c7e05f364b3b5f25a99e6e3c585e8 |
| Fixed configuration | 7512eb1bb89a4168670798fcc8f9f2d5d241d853 | 186385 | edd6c662c538cb9bd0be9c47f91ab5e1481283b60b4c6387d069f6de59359bce |
| Exact proposed h_pty_start request | 411133d9322a58a26ad9088bd259f5841ed05dc4 | 228657 | 7343041f486319056cde3790df409432f17b7c195085e0025742f338e0cbe0cc |

The fixed request uses `/usr/bin/python3 -I -B -c <validator> <four config chunks>`. The chunks are 48,000 / 48,000 / 48,000 / 42,385 UTF-8 bytes. All arguments are below the Linux single-argument 128-KiB boundary. The validator joins the four chunks and parses them as data. Embedded original native request objects are compared with archive JSON objects; their scripts and commands are never evaluated.

Host: `ai395`. Working directory: `/home/qq/af52-learning-local-decision-20261111`.
Reserved idempotency key: `af52-original-records-v9-independent-readonly-parse-20261112-v1`.
No request with this key has been sent. Root retains dispatch authority and owns the active f16 native campaign.

## Only original filesystem input

`/home/qq/af52-learning-local-decision-20261111/ordinary-2ac-and-7666-original-records-export-v9-20261112/original-records.tar.xz`

Expected immutable file version: `66306:55228380:2392536:1794456302624095909:1794456302624095909`.

The validator opens that one file with `O_RDONLY | O_CLOEXEC | O_NOFOLLOW`; it requires a canonical path, an ordinary regular file with one link, the exact size/version, identical descriptor/path metadata, and the exact full SHA-256 and Git blob. It rechecks descriptor/path metadata after all parsing. It never opens a source checkout, Root-owned live capability, original target/cache, credential, or live runtime record.

There is no subprocess, Git command, network operation, source/ref mutation, file creation, chmod/chown, cleanup, or filesystem extraction. Python's isolated mode ignores Python environment injection; `-B` prevents bytecode writes. Tar members are read from the decompressed in-memory stream using their checked data offsets. Neither `extract`, `extractall`, nor `extractfile` is called. The only application output is derived JSON on stdout; normal tool-owned PTY capture is separate transport behavior.

## Independent cross-checks

The validator requires exactly 116 safe, unique ordinary-file members with the original deterministic tar metadata and bounded sizes. The original manifest SHA is `7a7e87b294a13c689de53f457ff924b06b6e921c02e5234222e0220090184bf5`. Its 115 payload entries must exactly equal the tar payload set; every length, SHA-256, and Git blob is recomputed. The single original helper-binary exclusion, clean 7666 export anchor, and both terminal-record bindings are retained.

The original request/observation members were normalized by the exporter with Python JSON serialization. They are compared structurally with the already pinned native request/observation objects. The separate raw original request blobs retain their own exact byte hashes; no normalized member is claimed to be the same raw bytes.

For both terminal attempts the validator binds the complete progress object, every recorded launcher-log and execution-record side file, original tool-source snapshots, external-tool before/after digests, donor before/after identity, and the original physical-source inventory. The gzip inventory is read in memory under an explicit 64-MiB bound; its decoded digest, count, unique path/mode/digest rows, and original tool-source rows are checked.

### 2ac formatter-only failure

Source `2acdb420ea3074d0ba54774d43f565827bf40fec`, tree `3df95630b251283faf3ff03e64ddbaae4f6134cb`.

The actual original formatter execution has command exit 0 and failed executor status / exit 1. No ordinary or Root test stage or JUnit exists in this attempt: zero native tests. The original final physical-source check failed because seven formatter postimages remained dirty. The validator verifies their original base64 bytes, sizes, SHA-256 and Git blobs, their preimage bindings in the original physical inventory, the exact seven dirty paths, and the retained patch. It never resets that source or treats cleanup failure as success.

### 7666 Root component diagnostic failure

Source `7666bcc2c650298f2e1d47e615a25864fe792fa1`, tree `7495444ffe639ad28ac64aad5cc68e70c097c4aa`.

The complete original progress is 70,565 bytes, SHA-256 `a74f7e1b532ce4c4f58a281d7e5feb5836717ad4f675ac9fba2d79a169258394`, Git blob `061afa4b50aae4ff4f5e23265459ff40b0090db5`. It explicitly records nine successful cleanup checks and four successful cleanup commands; helper build/preverify/postverify succeeded. The Root test result nevertheless remains 17 executed / 15 passed / 2 failed, with original Root command exit 100 and the original JUnit collector exit 1.

The proposed parser independently counts the original JUnit, checks the exact 17 distinct parent roster, confirms the actual UID0 records and identical original source/binary custody, verifies the separately pinned 86,411-byte raw log, and checks both physical source inventories. The seven original formatter postimages must be the committed postimages observed in this Root source inventory. All helper and cleanup side-file bindings are verified. Unrun maintenance, product-bin, QA, caller, and ordinary-six-crate gates remain listed as unrun.

## Result and limits

A successful validator exit would mean only that the preserved original records and their failure classifications are internally consistent with the fixed archive and independent pins. It would not make either native attempt successful, qualify another source, prove an OS restart, make C independent, supply a business Outcome, or close the ordinary learning loop.

Ordinary complete chains / positive adoption chains / ordinary NoUpdateRollback chains remain **0 / 0 / 0**.

Current validation of this request is static inspection plus V8 reconstruction/hash checks only. Python AST compilation and execution have not been performed. Any later dispatch must use the exact reviewed request and original idempotency key, preserve failure/uncertain status, and must not retry by changing keys or input bytes.
