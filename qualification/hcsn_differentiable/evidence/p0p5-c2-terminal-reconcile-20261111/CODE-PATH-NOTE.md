# Original C2 crash-consistency code-path diagnosis (read-only)

This note is **not** a causal root-cause certification, a retrofit of the immutable original source, or a new training result. It is a bounded review of the exact program files running the original C2 job, combined with the preserved [terminal evidence](README.md) and [eight file identities](FIT-INVENTORY-READONLY.json).

## Source identities (original heptaruntime desktop)

- `/home/qian-qi/hepta-hcsn-core-study-20261110-c385-training/c2-execution-source-v4-20261110-c385/c2_controller.py`: 24,685 bytes, SHA-256 `5958053887fa3f29ee4a13aff9d06a151793e76d6369c68f554e77eb229104f6`.
- `/home/qian-qi/hepta-hcsn-core-study-20261110-c385-training/c2-execution-source-v4-20261110-c385/c2_runner.py`: 27,503 bytes, SHA-256 `161d803d878b2aa368f60f1f481de773d6577a91068a4c8dbff0b839074cde11`.

In `c2_controller.run_controller`, the original `record(row)` writes a JSON line with `journal.write(json.dumps(row, allow_nan=False) + '\\n')` followed by `journal.flush()` under a thread lock. It does **not** use a separate record file, atomic publish, or `fsync` at this point. The only full controller `RESULT.json` publication is in the `finally` block after the child-future harvest. A hard process termination can bypass Python `finally`; the torn original journal and absent controller RESULT are **consistent with** interruption during reporting, but do not prove when, why, or what killed it.

In `c2_runner`, its `finally` attempts an `immutable_checkpoint(out / 'interrupted.pt', snapshot(...))` on non-completed training. The two observed `interrupted.pt` files are **zero bytes**. Their existence proves neither a complete model serialization nor a valid optimizer/RNG continuation; separate `best.pt` files do not replace the intended interrupted-state snapshot. Do not deserialize or promote an empty checkpoint.

## Required separate successor design (NOT implemented in this PR)

1. **Atomic, verifiable checkpoint:** serialize to a new unique temporary file, flush and fsync bytes, validate size/hash and safe load under the frozen model/optimizer/manifest identity, then atomically publish with directory fsync. Never overwrite a valid checkpoint or interpret a zero-byte marker as recovery evidence.
2. **Crash-recoverable journal:** create immutable per-event framed receipts with sequence IDs, owner/process start identity and checksum; fsync before atomic rename and directory commit. The JSONL view can be derived from verified receipts, rather than being the only terminal authority. Reject incomplete/torn records, duplicates, contradictory attempts and missing terminal envelopes.
3. **Independent original reconciliation:** compare each native process terminal, full stdout/stderr and `wait4` resource cost to the checkpoint and attempted events. A missing outer controller RESULT can only be replaced by a *newly labeled reconstruction* with its own provenance and limitations, not a forged original RESULT.
4. **Kill/restart tests:** inject stop while checkpoint serialization, event write, post-child result publish and controller finalization. Require no false all-six terminal, no double counting, no retry of an uncertain original effect, and complete CPU/wall/memory provenance. Keep the full original attempt denominator and failures.

**Disposition: HOLD_NO_GO.** These are identified engineering obligations, not a tested fix. Any repair belongs on a new explicit source/experiment identity, with separate independent tests and CI. No cause, recovery correctness or scientific gain is asserted here.
