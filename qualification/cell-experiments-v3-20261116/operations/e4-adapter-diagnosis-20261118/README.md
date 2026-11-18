# Actual later-adapter precision loss

These are read-only tensor inspections of the retained Run02 adapters and the exact admitted PEFT 0.18 / Torch 2.9.1+cu128 runtime. Both diagnostic processes exited 0; neither trained nor generated an answer. The first E4 traceback in #6679 names no adapter, so this separate diagnosis is not retroactively inserted into that trace.

## Observed bytes

The first inspection loaded the same C checkpoint three ways: initial `from_pretrained(cell_0)`, later `load_adapter(default, is_trainable=False)`, and later `load_adapter(cell_1, is_trainable=True)`. Initial C preserved all 112 serialized FP32 tensors and its unchanged training-after hash. Both later loads changed all 112 tensors despite ending in FP32; every changed tensor exactly matched a saved FP32 → BF16 → FP32 round trip. The trainable flag does not explain the difference.

The second inspection repeated the original ordered C/F/T adapter loads:

| Load | Original after hash | Actual normalized hash | Byte-identical tensors | Exact BF16 round-trip tensors |
| --- | --- | --- | --- | --- |
| First C, cell_0 | e268d276… | e268d276… | 112 / 112 | 0 / 112 |
| Later F, cell_1 | e5d3d0a1… | dca57064… | 0 / 112 | 112 / 112 |
| Later T, cell_2 | 2da6848d… | 888850fc… | 0 / 112 | 112 / 112 |

All loaded tensors were FP32. Full hashes, normalized names in original iteration order, shapes, serialized and loaded byte hashes, and maximum absolute differences are retained in the archive. For later F/T the maximum absolute difference was approximately 0.00012206. Looking only at the final dtype would miss this loss. The original complete tensor gate correctly rejected the changed values.

PEFT's initial adapter path promotes the target before loading; its additional-adapter path creates BF16 targets, copies the saved values, and promotes them afterward. The narrowly scoped repair in #6680 promotes only the new adapter before the copy and retains the original expected after hash, count, base identity, frozen-state and per-activation checks. It is a new engineering candidate, not a change to the failed attempt.

## Original evidence and costs

`adapter-diagnostic-originals.tar.gz` contains 17 regular files (20 members): exact executed diagnostic sources and formatting receipts, two INTENT/RESULT records, six per-tensor records, two round-trip checks, and SUMMARY. Size 69,173 bytes; SHA256 `df9d48aa2b29bc769c401f8ebcba6945e76532536f5fedd4c2fbe8c0e38eff11`. Version-bound chunk hashes and the full original SHA were checked after transfer, along with safe archive paths and absence of model weights.

`SUMMARY.json` and `ARCHIVE_RESULT.json` are unmodified originals. The two inspection scopes took 24.581579471 and 22.870047250 seconds, respectively, including their admission and inspection. Each nested sub-operation must not be added again. Energy, monetary cost, and complete system cost are unknown. These diagnostic costs and the earlier failed initialization are bound into the next E4 protocol; they are not erased by the repair.

This establishes an implementation defect and its mechanism. It supplies no new task, user, teacher, learning gain, Circuit business gain, native adoption, or contribution reward evidence.
