# Clean CI maintenance replication evidence

This directory preserves the exact original `memory-adapter-longrun-output.tar.xz` bytes from GitHub Actions run [40681620656](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40681620656), job `122793476485`, artifact `12814206358`. The run completed successfully on 2026-10-28. Its source commit is `773e8c5540521861ab18b1c61268069d6610279a`, tree `f284bab3dc69c87dece3e8ffd8999d2f23bcea6b`.

`ARTIFACT_ORIGIN.json` records the retrieved GitHub identity and independent ZIP hash verification. `PACKAGING.json` is the unchanged runner packaging receipt. The original 7,089,136-byte tar is split into 18 consecutive parts, each at most 400,000 bytes, without recompression or modification. Its SHA-256 is `20c348466832e026e6d9280ea542f50f252bf9e633f64ea3fec0a0c900442a90`. It contains 4,153 regular files, 633 directories, and 21,766,558 uncompressed regular-file bytes.

The entire output root is included: preparation and dependency logs, hardware and initialization receipts, all 435 completed trainer/reader process receipts, actual model parameters, SQLite snapshots, requests and responses, raw resource samples, final results, and source freezes. Installed dependency wheels and shared encoder weights are referenced separately rather than embedded. The original local ZIP, original tar, restored raw tree, and interrupted first-chain evidence remain preserved.

## Verification and restoration

From a checkout containing this directory:

```sh
python -I -B qualification/memory-cell-adapters/longrun/evidence/longrun64x3-clean/restore.py --verify-only
python -I -B qualification/memory-cell-adapters/longrun/evidence/longrun64x3-clean/restore.py --output /tmp/hepta-memory-adapter-clean-evidence
```

The output directory must not already exist. The helper checks every transport part, the combined original tar hash, every member's type, size and digest, and the complete inventory. It rejects path traversal, duplicates, file-as-ancestor collisions, links and special entries. `VERIFICATION.json` records successful whole-archive verification and 11 transport checks. This new helper is an evidence reader outside the frozen training runtime; no frozen Python source was changed.

The restored bundle root is `/tmp/hepta-memory-adapter-clean-evidence/memory-adapter-longrun-output`. `PATHS.json` retains the actual runner paths. Use the evaluation auditor's explicit prefix mappings; do not rewrite original requests or receipts. The initial formal evidence must remain available separately, and historical monotonic timestamps must not be compared numerically with the CI host's timestamps.

## Results and cost boundaries

The frozen protocol completed 64 cycles for each of seeds 731, 732 and 733: 192 updates, 24 clean rebuilds, 216 successful fits and 219 fresh reader processes. Both parameter memory and same-information exact SQL obtained 1,512/1,512 active reads, 1,305/1,305 retention reads, 207/207 changed reads, and 24/24 revoked rejections. The independent CI audit reports 8,563/8,563 checks passed in `../../../evaluation/AUDIT-longrun-ci.json`.

`COST_SUMMARY.json` gives the derived cost ledger; `RAW_RESOURCE.json`, `RAW_PREPARATION.json`, `RAW_CI_RESULT.json` and the original tar retain its authorities. The runner used an Intel Xeon Platinum 8370C, four logical CPUs, Python 3.12.15, CPU PyTorch 2.8.0+cpu and NumPy 2.3.5. It used different hardware from the original local run.

| Measured scope | Wall time or CPU time |
| --- | ---: |
| Preparation wall time | 24.251046586 s |
| Lifecycle observation window | 858.478325932 s |
| Completed fit and reader child CPU | 852.535687 s |
| Driver wait4 CPU, including waited descendants | 856.774937 s |
| Monitor subtree CPU measured by its parent | 954.746828 s |
| Wrapper plus waited children CPU | 977.339552314 s |
| Separate archive packaging CPU | 4.456184323 s |

These are nested scopes. Do not add fit, reader, driver or monitor CPU to the wrapper total again. Packaging is a separate later process, producing 981.795736637 seconds of observed wrapper-plus-packaging CPU. Checkout/Python-setup CPU, upload CPU, and preparation memory/storage integrals were not measured. There were 3,802 resource samples and 29 sample errors; RSS/PSS intervals totaling 11.850252394 seconds and storage intervals totaling 1.344647791 seconds remain unknown. Sampled peak tree RSS was 548,093,952 bytes and peak PSS was 448,604,160 bytes. `full_cost_exact` remains false.

Storage is separated into explicit sources, parameters, shared encoder reference, canonical features and retained evidence. The shared encoder reference is 127,536,988 bytes; the encoder was neither downloaded nor rerun. Historical fitted checkpoints total 7,906,432 bytes, in addition to initial checkpoint copies and source snapshots. Archived old checkpoints do not provide physical erasure.

The clean replication adds 129,600 gradient steps and 4,147,200 sample presentations. Across the first completed chain and this clean run there are 432 successful fits, 259,200 steps and 8,294,400 presentations, plus the original interrupted attempt whose work and CPU remain unknown. These two longrun executions consumed 2,553.042976 seconds of observed successful fit/reader CPU; this excludes their other overhead and the earlier formal study. The clean run does not replace or erase the first chain's costs or measurement gap.

Parameter and SQL read slices execute sequentially inside the same fresh owner process; their slice timings exclude shared imports, checkpoint loading, connections and metadata work. They are not independent deployment latency measurements. This is a bounded eight-entity synthetic policy maintenance experiment using full replay. It does not demonstrate superiority over exact SQL, general memory emergence, or native Hepta integration.
