# Common-source retained-domain and persistent-state reexecution

This engineering attempt freshly ran the bound-migration and persistent-DDE source together. It remains **HOLD_NO_GO**: no training, full C2 replay, independent future-task benefit or Cell adoption is claimed.

## Source and ordering

The execution source is `9f6c7c4dc24510472ca012647ebd1d96c1405c69`, tree `d706c2ca2655f388c201d12781980ae68ccf700c`, published in draft PR #6174 and read back before this attempt started. Its first parent is #6157 exact `fb663f141f5763692a5fc05e09ae60e8d7da4bdf`; its second is #6144 evidence `67b93060451117c7cc14465b384dd6da124b5761`.

The actual tree is the exact #6157 tree plus the 17 historical #6144 evidence/documentation blobs, one `audit_graded.py` guard addition for its new `state_io.py` import, and `qualify_common.py` / `COMMON_SOURCE_PROTOCOL.json`. The numerical algorithms and thresholds were unchanged. The second parent preserves evidence ancestry; it does not turn old passing results into a new execution.

Start `2026-11-12T06:49:47.618820+00:00`; finish `2026-11-12T06:54:22.994004+00:00`. Both sequential lanes ran on the same frozen local bytes after remote source publication. The common guard binds 18 source/protocol files. The domain runtime closure is 9 Python files plus its protocol; state qualification binds its 16 Python files, including test sources. Guarding a file does not count as executing a test.

## Fresh results

The state lane ran **28 tests, zero skips**, then restored actual JSON checkpoint bytes in a fresh process without replaying the prefix. The absolute resume clock was **0.417**, final clock **1.0**, and maximum retained-channel difference from uninterrupted integration was **7.6711775820470507e-11**.

The complete original retained domain was then recomputed:

| Mesh intervals | Original retained positions | Failures at unchanged 1% scaled continuation threshold | Maximum scaled error | Maximum noncancelling scaled error |
|---:|---:|---:|---:|---:|
| 256 | 14,336 | 0 | 1.58748786719e-05 | 1.58749080441e-05 |
| 512 | 14,336 | 0 | 4.00956338842e-06 | 4.00959285912e-06 |

Every retained prior and posterior was included. The original input summary SHA256 remains `12fa561e6b5e6f710d1239d2a00bcf596da9d0060bf4691473ff337b7b5d0822`. Raw input identities and all original checks are retained in the domain summary.

The full population uses the linear first-excursion M/H/A kernel and continuation. It is **not 14,336 separately integrated DDE trajectories**. In addition, **30 actual `JointModel.solve` integrations** freshly ran the first posterior of each of 12 arms plus three fixed boundary/tail/phase fixtures on each mesh. Their 210 query records retain probability and signed-content channels. All 30 migrations now have the canonical source-law/target-node binding receipt. Maximum spectral-versus-DDE error was **2.091088413536113e-11**.

The freshly computed full-domain arrays equal the historical arrays element for element; the new execution is established by its original logs, updated map-binding receipts, source guards, timing and separate attempt outputs. This equality does not pool historical results into the new run.

Total sequential lane wall time was **275.368 seconds**, with one BLAS/OpenMP thread. Exact commands, child CPU time, high-water RSS, package versions and before/after source hashes are retained. The mandatory scoped `just fmt` ran after verification; its source hashes are unchanged and no tests were rerun after formatting.

## Evidence and limits

The immutable attempt is `evidence/common-source-20261112-d706/attempt001/`. `RESULT.json` binds the common run; `state/` contains the real cold checkpoint bytes and original process logs; `domain/` contains both complete arrays, direct DDE records and original summary. `MANIFEST.json` maps every compressed object to its decoded original hash and binds source/readback/format receipts.

Persistent recovery remains the existing 9 state controls and declared fresh-process fixture; it was not repeated for every retained posterior. This attempt does not claim recursive observation filtering, full-network gradients, neural retraining, six completed C2 optimizer replays, rare-tail relative accuracy below the original floor, independent future tasks, moving-reset qualification, or production/default-cell adoption. No Torch cascade result is included. New optimizer calls = 0; complete C2 replays = 0; independent future tasks = 0.
