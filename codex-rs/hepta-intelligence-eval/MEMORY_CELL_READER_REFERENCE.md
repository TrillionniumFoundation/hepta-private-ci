# Reader capability before more memory learning

This stage executes the existing eight-case evidence census, not another invented
oracle. It preserves ordinary retrieval, empty, full-source, omission, reviewed
full and reversed conditions. Five reviews are provisional implementation-assistant
claims; three are unavailable. All eight independent human reviews are still
pending. Do not call these inputs human-verified sufficient context.

The reference study compares the existing SmolLM2-1.7B and a fixed published
Qwen2.5-3B-Instruct revision. Both use BF16 weights and eager attention, the same
system instruction, semantic prompt construction, original evidence bytes,
2,048-token ceilings and 64-token deterministic decoder. Tokenizers and actual
consumption differ; this is a reader-family/capacity comparison, never a learned
MemoryCell gain or an equal-FLOP claim. Historical float32 Smol runs remain a
different numeric profile. Neither model is automatically adopted.

Qwen2.5-3B uses the Qwen RESEARCH LICENSE AGREEMENT: this run is non-commercial
research/evaluation only. The pinned LICENSE and README are retained in the local
model inventory. No weights are uploaded, no teacher labels are produced, and no
commercial serving authorization is inferred from being able to download a model.
Use of another model in production requires its applicable license and the existing
selection/trust owners. The shared reader need not have the same capacity as a cell.

## Genuine experiment, not a lowered gate

The full inherited plan/review/withdrawal/label hashes are fixed in the executable.
Before download, staging obtains file metadata at the exact model revision; every
Git or LFS object and tensor shard is checked against that catalogue. The catalogue
and final inventory are separate. Model inventory and withdrawal views are then
pinned across loading and actual inference. Existing answer journaling precedes
QA scoring. No generated answer is repaired or assigned a citation after inference.

`ReferenceReader` only changes the constructor's numerical profile. Generation,
source checks, output receipts and frozen verification reuse FrozenBundleReader.
The existing `reviewed_diagnostic.execute` performs the complete projection and
all original admission checks. Missing review rows remain in denominators and
score uncertainty. A successful workflow is execution evidence, not a passed
capability screen, independent semantic review or production qualification.

The report counts actual input/output tokens, read seconds, model storage and
staging time. Training cost is zero because this stage invokes no optimizer.
Inherited extraction/index costs are UNKNOWN here, not zero; use the original
input-build receipts when comparing end-to-end lifecycle costs. Retained source
storage is not erased or omitted to create a parametric compression claim.

## Causal order for subsequent work

1. Obtain correctly admitted sufficient-context judgments for all fixed cases and
   judge actual answers semantically; token F1 alone is not a verdict. Keep the
   unchanged full/reversed/empty thresholds and the independent-review boundary.
2. When a reader genuinely works with sufficient evidence, compare persistent
   hybrid RAG against event/entity/valid-time/correction projections and set
   completion under that SAME reader and tool budget. Do not retrain the reader
   and attribute its gains to memory organization.
3. Only then compare learned retrieval policy and experience-specific knowledge
   modules. Freeze sources, policy/knowledge bytes and lineage before future task
   exposure. Use new facts, corrections, multisource tasks and actual executable
   outcomes with equivalent baseline tools. Reused public cases remain development.
4. Measure extraction, indexing, training, N reads, retention and revocation/repair
   costs together. Independent samples, future windows and production recovery
   require actual external evidence. More CI or synthetic clocks do not supply it.

Stages 2-4 are NOT executed by this reader experiment. A low reader score or
missing review cannot be repaired by changing a gate after seeing outputs.

## Execute

```sh
python3 scripts/memory_cell/reader_reference.py stage qwen-3b MODEL_DIR
HEPTA_MEMORY_TESTED_COMMIT="$(git rev-parse HEAD)" HF_HUB_OFFLINE=1 \
  TRANSFORMERS_OFFLINE=1 python3 scripts/memory_cell/reader_reference.py \
  run ORIGINAL_AUDITED_INPUTS MODEL_DIR NEW_RUN_DIR --stage-sha STAGING_RECEIPT_SHA
```

The read-only `hepta-memory-reader-reference.yml` workflow runs all regressions
and actual model calls in separate processes and retains failed outputs as well
as successful ones. No dedicated Hepta host or cloud environment is used. The
repository formatting check remains required; diagnostics do not update any Git
reference. Consult terminal status and the exact generating commit, not this doc.
