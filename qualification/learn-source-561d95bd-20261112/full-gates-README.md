# Complete source gates at frozen 561d95bd

Both original commands completed on the same clean frozen source `561d95bdf192b2631f6a762d2915d27a120d87bb`, tree `387feebbb3bc51f6d0a187137128e100ba63dea1`.

| Gate | Actual result | Recorded stage duration |
|---|---|---:|
| All `qa/b4-no-bypass/test_*.py` | 925 tests, OK, exit 0 | 209.05243407100352 seconds |
| Complete `verify_hepta_callers.py verify --root` | PASS_HEPTA_CALLER_CLOSED_SET, exit 0 | 697.2095637719976 seconds |

The full caller receipt covers 6,886 Rust files, 1,106 boundary entries, 1,106 privileged inventory entries and 870 protected-file entries. Its `authorityGranted` field remains false. Original caller stdout is 531,258 bytes with SHA-256 `99c8ac01dac0476a66f8d050675a478bc95fcb8cb3ba038f540de7897df05a65`; caller stderr is empty.

Every before/after snapshot is equal and clean: 15,494 tracked files / 234,381,882 bytes; aggregate SHA-256 `17acd96e6d244ed8e93da5cbd6785cfef083a958d2160bc5d1e08b7242f8d1b4`; CALLERS SHA-256 `ae01152e87c0e8905631f6440988535acbc3744d82645c3979e09d23aa7d477e`. The overall driver actually exited 0. The archive preserves both raw stdout/stderr streams, all terminal records, the exact driver, source snapshots and checkout/ref receipts; its 16 original input members were verified after compression.

This terminal record supplements the earlier QA-only checkpoint. It establishes source gates for this exact intermediate commit only. It executes no native tests, does not cover later source changes, and does not change the separate ordinary A failure or the end-to-end Adopt / evaluated NoUpdate / whole-cold counts.
