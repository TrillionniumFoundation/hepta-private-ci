# E5 Atomic Packed Head Checkpoint: actual child SIGKILL fault matrix

**RESEARCH / SHADOW / DENY_ALL.** This experiment tests a POSIX **process death** during a local, unsigned Packed Head SGD checkpoint commit. It is NOT a certified production WAL, remote Artifact CAS, FinalUse/revocation system, power-cut filesystem, or pretrained-model task evaluation.

## Why this is a separate experiment

Previous [clean-restart momentum](E5_PACKED_MOMENTUM_REPLAY.md) established that manually saved FP32 Head and momentum tensors can reproduce SGD. It had no atomic publication pointer or actual dying writer. This study adds content-addressed **immutable full-FP32 checkpoint blobs**, immutable chain-linked **commit manifests**, a file-locked compare-and-swap writer, a write-once temporary HEAD, atomic `os.replace` publication, file and parent-directory `fsync`, and cross-process recovery that considers **only** the HEAD-referenced committed manifest.

`e5_crash_atomic_store.py` refuses unsafe scopes, wrong generation/model/fence, changed checkpoint bytes, stale expected HEAD, nonadvancing optimizer steps, wrong tensor shapes, missing parent manifests and misleading promotion flags. Readers verify actual original `e5_packed_momentum_replay.restore` tensors including **all** Head FP32 parameters and momentum, not just a claimed hash. `fcntl.flock` serializes local writers (POSIX host only); a killed writer loses its file lock automatically. SHA256 provides local **integrity**, not independent cryptographic origin authentication. Orphan stage files, immutable blobs and manifests lacking a published HEAD **cannot** become selected state.

The exact HEAD source dependencies `e5_packed_momentum_replay.py`, `e5_sparse_packed_sgd.py`, `e5_packed_head_fanout.py` are reused without modification. The experimental file limit is 750 MiB; that is a bound, **not** proof of successful 4096-Cell crash recovery or safe process memory use.

## Actual independent SIGKILL injection

Ten fixed injection points, executed in child OS processes with `os.kill(os.getpid(), SIGKILL)`, never just an ordinary caught exception:

| Crash position | 64-Cell post-crash visible step | Meaning |
| --- | ---: | --- |
| blob partially written | 2 | Staged partial blob invisible |
| blob fsynced | 2 | Unpublished blob invisible |
| blob published | 2 | Immutable blob alone insufficient |
| manifest partially written | 2 | Staged manifest invisible |
| manifest fsynced | 2 | Fsynced unpublished manifest invisible |
| manifest published | 2 | Manifest alone insufficient |
| HEAD partially written | 2 | Torn temporary pointer invisible |
| HEAD fsynced but not replaced | 2 | Temporary HEAD invisible |
| HEAD atomically replaced | 4 | New complete commit visible to fresh process |
| HEAD parent-directory fsynced | 4 | New complete commit visible to fresh process |

Original staged checkpoint contains **2 real SGD steps** of selected Cells. The attempted new complete snapshot contains **4 steps** with momentum. Whenever HEAD remains old, recovery genuinely resumes two more PyTorch SGD updates and publishes a new checkpoint. After the atomic switch, recovery loads the new checkpoint without duplicate application. In **every scenario**, all restored Cell weights and momentum are **bit-exact** relative to uninterrupted four-step SGD.

**Local physical outcomes on 2026-10-14:** 64 logical/8 active Cells: **10 independent real SIGKILL child processes**; 256 logical/25 active Cells: **4 additional independent real SIGKILL child processes** at blob partial, manifest publication, HEAD replacement and directory-fsynced HEAD. All **14 completed** and were independently recounted from the original JSON. CPU PyTorch performs real numeric SGD on **synthetic Q24 features and labels**.

- 64-Cell exact-source raw: [E5_CRASH_ATOMIC_LOCAL_64_20261014.json](E5_CRASH_ATOMIC_LOCAL_64_20261014.json), SHA256 `b3a6c8df686784066bc11e0f5f7d94063ac8b9ca37b38eb9a4e79d120116888a`.
- 256-Cell exact-source raw: [E5_CRASH_ATOMIC_LOCAL_256_20261014.json](E5_CRASH_ATOMIC_LOCAL_256_20261014.json), SHA256 `a9aa7c537028bb3ac5ef647d6e54507205344342b7a6f64d408d790d5a1b8ad4`.
- Local independent read-only numeric reviewer: SHA256 `21aa5acb7e50b253137add0ee29fa74613f6ad5401f700652f1a91918c588074`.
- Actual source Git blobs (checked against remote): `e5_crash_atomic_store.py` `e12d9fb4e9679bbd408d96c34288ba46239cd245`; `test_e5_crash_atomic_store.py` `88921bfb68f3b4927431a9de5efdff6dad09121a`; `e5_crash_matrix.py` `5021ad9424b4601e214b4522bf62459a8de50fe9`; `e5_crash_matrix_review.py` `49f63643e6b2ac7d539a84d2b3bf7e7a4b09a02c`; upstream momentum source `bfb88d70879921199cbaf0fcc4b9f37d3042a5ea`.

A real two-writer cross-process race demonstrates that one writer succeeds and the second is rejected by the exact expected-HEAD CAS. Additional fault tests cover stale CAS, wrong Scope/Generation/model/fence, corruption of blob/manifest/HEAD, missing HEAD, symlink HEAD and orphan garbage. The **12 physical/store unit tests + 12 independently adversarial receipt tests all pass locally**. The reviewer reads supplied JSON and thus explicitly reports `independently_verified_OS_process_exits=false`; the direct child runner, unlike the read-only reviewer, actually inspected child `returncode == -9`.

## Exact HEAD GitHub re-execution

The read-only [hepta-e5-sigkill-atomic-checkpoint.yml](../../.github/workflows/hepta-e5-sigkill-atomic-checkpoint.yml) installs pinned CPU Torch; checks out the exact PR SHA; runs both test modules; then runs a **fresh** 64-Cell 10-cut study and 256-Cell 4-cut study in isolated subprocesses, rechecks their independent summaries, and uploads full/partial receipts on `always()`. The job is **not successful until GitHub Actions actually completes**. Use:

```bash
python -m unittest discover -s experiments/shared_stem_cell -p 'test_e5_crash_atomic_store.py' -v
python -m unittest discover -s experiments/shared_stem_cell -p 'test_e5_crash_matrix_review.py' -v
python experiments/shared_stem_cell/e5_crash_matrix.py \
  --cells 64 --active 8 --output /approved/64.json
python experiments/shared_stem_cell/e5_crash_matrix.py \
  --cells 256 --active 25 \
  --failpoint blob_partial --failpoint manifest_published \
  --failpoint head_replaced --failpoint head_dirsynced \
  --output /approved/256.json
python experiments/shared_stem_cell/e5_crash_matrix_review.py \
  --small /approved/64.json --medium /approved/256.json \
  --output /sealed/independent-e5-crash-review.json
```

## What this DOES NOT prove

1. A SIGKILL terminates one process while leaving the host and OS page cache alive; it is **not** a real power cut, hard reboot, disk failure, remount, NFS/object-store test or native WAL recovery qualification. The observation at the **HEAD replaced but not directory-fsynced** stage cannot be generalized to power-loss durability.
2. `fcntl` and local `os.replace` are not a distributed transactional CAS/consensus service, and there is no independent monotonically signed root-of-trust protecting the HEAD from malicious rollback. Scope/model/fence digests are **caller-provided identities**, not host-signed authorization.
3. This mechanism currently uses hex-encoded full-FP32 JSON checkpoints. It has measured crash semantics at 64 and 256 logical Cells, **not** 1024/4096-Cell real power loss, sustained throughput or cost-optimized delta snapshots. Memory/disk amplification needs future measurement.
4. No live Encoder, Reader sufficient-evidence semantic outcomes, three future windows, NDU, production Worker, actual FinalUse revocation, journal epoch CAS, native Rust microbatch or owner security signoff was exercised. Promotion remains **`DENY_ALL`** and `production_promotion_permitted=false`.

The PR remains Draft, requires exact-HEAD `blocking-ci` and independent Evaluator/Selector/Executor before any production deployment or Stem choice.
