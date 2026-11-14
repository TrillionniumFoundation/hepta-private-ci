# Measured storage coding for parameter memory

This component converts verified float32 LoRA tensors to deterministic per-tensor
symmetric int8 or packed int4 storage. It preserves the exact original lineage,
configuration and inherited source roots. The derived artifact has its own
manifest, payload and decoded-state identities. Quantization performs zero
optimizer updates and is explicitly recorded as a lossy derivation.

## API

Add `scripts/memory_cell` and `scripts/memory_cell_codec` to `PYTHONPATH`.

```python
from checkpoint_codec import encode_checkpoint, decode_checkpoint

packed = encode_checkpoint(
    parent, packed_directory,
    expected_manifest_sha256=parent_manifest,
    allowed_roots=current_allowed_roots,
    revoked_roots=current_revoked_roots,
    bits=8,  # or the independently registered 4-bit arm
)
derived = decode_checkpoint(
    packed_directory, materialized_directory,
    expected_codec_sha256=packed["codec_manifest_sha256"],
    allowed_roots=current_allowed_roots,
    revoked_roots=current_revoked_roots,
)
```

Both destinations must be new. Admission checks roots before derivation or
materialization. Existing `ParametricOwner` and `SourceMemoryCell.load` consume
the materialized v2 checkpoint using `derived["manifest_sha256"]`, with normal
independent base/configuration compatibility and current-frontier checks.

The low-level codec bounds header, tensor count, matrix shape, decoded bytes,
contiguous offsets and finite scales. It rejects truncation, trailing bytes,
reserved codes and invalid padding. Checkpoint reads reuse the regular-file,
size and descriptor-identity protections in `tensor_contract.bounded_read`.

## What the costs mean

`packed_artifact_bytes` includes the actual packed tensor file, original source
lineage, configuration and codec manifest. `materialized_checkpoint_bytes`
includes the decoded tensors and all retained derivation/source receipts.
`decoded_tensor_bytes` reports actual float32 parameter memory. If packed and
materialized forms are both retained, charge both. Any retained parent versions,
shared base, source ledger, learned router and training cost must also be charged
by the caller; this codec never silently declares them free.

The current decoder materializes float32 safetensors. It does not run quantized
matmuls, prove lower inference RAM, or certify that answers survive quantization.
Error statistics describe this tensor conversion; task-quality acceptance must
use a separately registered source-selection/final protocol. Do not select a
precision after observing final answers and then report it as preregistered.

`exact_baselines.measure_baselines(records, destination)` saves and verifies
actual complete-record JSON, zlib level 9, LZMA preset 6 and SQLite alternatives.
When every original record has the legacy `scope/entity/relation/value` fields,
it separately labels a semantic-only projection which omits source metadata.
For heterogeneous original ledgers, that projection is explicitly unavailable;
the full original records and their metadata are still measured unchanged. The
complete records remain the comparable provenance-preserving baseline. Sizes
of different alternative encodings are not one combined deployed-store size;
all retained alternatives still count toward experiment artifact storage.

Smaller adapter files establish compression relative to the original adapter,
not superiority over exact memory. Independently random assignments carry
irreducible information; a model cannot universally encode arbitrary facts in
fewer bits while retaining exact recovery. Structured distributions may admit
useful lossy or amortized representations, which require measured quality and
full-system cost comparisons. General memory, semantic compression superiority,
statistical forgetting and production acceptance are not certified here.
