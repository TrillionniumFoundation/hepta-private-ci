# Failed native v1 run 001: complete original evidence

**FAILED.** Source is fixed to `8a47cdd26574a85cd314fabce65cc395dbe316a8`. The real pretrained training completed 96 updates and 96 training forwards. The daemon probe then failed during CognitiveStore recovery, before production source admission, daemon startup, native feature inference or decoder/control queries. This archive does not turn that failure into success or merge it with a later continuation.

## Original execution and failure

The original `/tmp/hm-native-001` contains exactly 83 regular files and 4,954,052 bytes. Every file is retained, including the complete checkpoint, imported source records, source archive, training receipt, original database, WAL and SHM. All original directory entries are retained, including empty `trial/native-process-receipts`. The six actual child stages are `source-archive`, `prepare-source`, `prepare-owner`, `train-96`, `configure`, `daemon-probe`. Exact argv, working directory, timeouts and unmodified receipts are in `original-run/commands/` and `audit/command-ledger.json`; model acquisition is retained separately as in-process HTTP work.

The wrapper exited 1 after 77.66258329599987 seconds. The daemon probe exited 1 after 0.0320871799995075 seconds with the original immutable-file-identity error. Its WAL and SHM are mode 0644 while retained-sidecar admission requires 0600. WAL existence by itself is not a failure: the recovery path can replay authenticated copied WAL. No SQLite API was opened while preserving these bytes.

`production-source.json`, `daemon-health.json`, `raw-result.json`, control-stage directories and final reports are absent, as are several other later-stage records listed in `audit/phase-and-absence.json`. The exact archived Rust source places `open_host` before source admission and daemon spawn; the archived driver places controls after successful daemon probe. Those observations support derived counts of zero decoder queries, zero native feature forwards and zero research controls. The original wrapper's `actual_completed_model_calls: null` is retained unchanged; it is not silently replaced with zero. Training forwards remain 96, not zero.

## Costs retained separately

| Item | Observed quantity | Scope |
| --- | ---: | --- |
| Training updates / forwards | 96 / 96 | Actual saved training receipt |
| Training input / supervised tokens | 7,296 / 192 | Actual training receipt |
| Training subprocess wall time | 67.69840356999975 s | Includes child startup/save overhead |
| Training subprocess user / system CPU | 118.795261 / 3.085944 s | Original process receipt |
| Internal training loop | 56.37101271500069 s | Nested within subprocess |
| Complete wrapper wall time | 77.66258329599987 s | Overlaps all child timing |
| Original run files | 4,954,052 B | All 83 files archived |
| Checkpoint files | 1,890,112 B | Included in original run total |
| Adapter tensor file | 1,858,776 B | Included in checkpoint total |
| Shared base model files | 271,170,520 B | Six pinned files; hashes and sizes rechecked, bytes excluded |
| Original v1 executable | 479,624,264 B | Original build/invocation SHA receipts; binary excluded |

Nested times and included file categories must not be added twice. Base `st_blocks` reports 271,187,968 allocated bytes; this is a filesystem allocation report, not a full physical-device or deduplication measurement. Gradient and optimizer tensor sizes are retained in `audit/costs.json`; peak RAM, full runtime dependency storage and full-system net compression were not measured. Excluding shared base/executable bytes from the archive does not remove their cost. The source case was already exposed development data, not an unseen future-task evaluation.

The base is `HuggingFaceTB/SmolLM2-135M-Instruct` at revision `12fd25f77366fa6b3b4b768ec3050bf629380bac`; all six SHA256/size pins match the original acquisition record. `audit/base-model-inventory.json` retains each pin and observed physical-file size. The verified 28-package runtime freeze and its original method limitations are retained. No fresh package-metadata or model command was run for this capture.

## Integrity and repair boundary

The source archive's git comment is the fixed head above; all 342 archived source-file bytes match the original `source-before.json`. Wrapper/build/invocation pins agree. The driver never reached its final `source-after.json` check; that missing record is explicitly retained as an absence rather than fabricated. The wrapper's original clean-worktree receipt remains a separate observation.

Before/after inventories prove that original file bytes, permissions, ownership, link counts, inode/device and modification/change timestamps remained unchanged. Access timestamps are excluded because reading may update them. The archive preserves original modes, including the 0644 sidecars; tar UID/GID/timestamps are normalized, while original metadata remains in the inventories. Every archived regular member was read back and compared byte-for-byte. No original write, chmod, SQLite connection, Rust build or model execution occurred during capture.

`post-failure-candidate/` contains the separate two-line awaited-close patch, its raw evidence bundle and independent review. That candidate was not executed by this original run; it preserves the actual logical anchor and awaits pool shutdown before publishing prepare success. Its future runtime qualification is separate. Any continuation must retain this failed attempt's training cost and use its frozen checkpoint without retroactively relabeling this attempt.
