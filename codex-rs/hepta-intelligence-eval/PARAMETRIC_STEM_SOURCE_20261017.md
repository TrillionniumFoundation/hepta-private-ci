# Frozen MiniLM Stem → Associative MemoryCell → same-source retrieval

**2026-10-17: RESEARCH / SHADOW_ONLY / DENY_ALL. Not a production MemoryCell or
trained general-memory system. This continuation stacks after MemoryCell
MetaMemory PR #2612; the preceding negative temporal-graph result is retained.**

## Concrete source-only mechanism

`parametric_stem_reader.py` uses the source-original pinned frozen
`all-MiniLM-L6-v2` 6-layer 384-D Encoder via the existing
`associative_minilm_offline.MiniLMOfflineEncoder`, with the existing deterministic
384→64 projection, and trains the repo's **actual** `AssociativeCell` with
rank 8 (1,024 scalars) once per original LoCoMo conversation. Source-only cues
are reproducibly built from the source message and speaker, while target values
are embeddings of the same message. Historical user question strings, reference
answers, supporting-source IDs and evaluation labels are unavailable to the
training worker. The native standalone Encoder supports a restricted ASCII
subset; the upstream registered HF/Transformers parity remains a separate
requirement, not an assumed property of this trial.

Each logical family has an explicit training cut of at most **512 chronologically
first admitted original source messages**, including fewer messages for families
with less than 512. Training validates the whole source set, scope, revisions,
encoder/projector identity, rank and current revocations before proposing an
immutable candidate. Weights, all source root IDs, and the model lineage are
exported and clean-process-restored. Historical changes/forgetting would deny
a candidate until legitimately retrained from an eligible root set: there is
**no independent authentication of the source admission and no certified
machine unlearning**. Runtime never selects these candidates.

The MemoryCell emits a **64-D latent vector**. Turning it into a ranked source
ID uses an external retained catalogue of original source embeddings and full
source IDs. Therefore this is *not* parameter-only language recall, and no
storage compression ratio may exclude the source catalogue, 91-MB shared
encoder, cold model loading or training costs.

## Same-source evidence ranking arms

The same first-512-or-fewer source pool and Top-8 evidence IDs is used for
BM25, fixed temporal graph, dense frozen Encoder, three-channel RRF,
frozen/untrained Cell, source-trained Cell, and RRF plus trained Cell. BM25 and
temporal process exact original source bytes; Encoder processing uses the
explicit 180-character source excerpt profile to keep the tokenizer below its
maximum, never a silent token truncation. This is a real asymmetry of
representational access and is reported rather than concealed.

The original benchmark's 10 authored LoCoMo conversations yield **240 planned
questions**, including two unresolved/zero reference records, 238 valid
reference questions and only 176 with every gold reference still present in
the bounded input pool. The source-only worker knows none of those references;
the separate reviewer first executes the frozen MiniLM, projection, source-only
SGD and all seven rankings anew, then compares the full original prediction
journal and every serialized weight artifact **byte-for-byte** before opening
published benchmark annotations.

## Actual local real model execution (not exact-head hosted acceptance)

Pinned LoCoMo original SHA-256:
`79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4`.
Historical source preparation used authentic prior GitHub staged artifact
`11586991191`. The public source bytes match prior graph-causal PR #2486
exactly. The actual original-weight frozen Encoder + ten 1,024-scalar Head
training and 240-question seven-arm execution was **57.67 s** on a local CPU
host, excluding all model acquisition/Reader/lifecycle costs. An independent
second execution with the same exact source/model bytes revalidated the
entire journal and Cell artifacts before accessing original references.

| Source-ID complete references in Top-8 | / 238 |
| --- | ---: |
| Fixed temporal | **109** |
| BM25 + dense + temporal RRF | 100 |
| RRF plus parametric MemoryCell | 93 |
| BM25 | 83 |
| Frozen dense Encoder | 52 |
| Actually trained low-rank MemoryCell | 7 |
| Frozen/untrained Cell | 4 |

**Result: unequivocal non-promotion.** The Cell trained and its source identity
verified, but parametric latent readout did not improve source evidence
coverage. Adding the Cell to the bounded hybrid lowered coverage from 100 to
93. The earlier full-source temporal result (136/238) has a **different source
pool** and cannot be presented as a directly matched comparator.

The observed original journal/receipt digests and resource counters are frozen
in `PARAMETRIC_STEM_ORIGINAL_OBSERVATION_20261017.json`. The original binary
source, private answers, source vectors, Reader files, and original weights
remain outside Git; only identities, code, tests and sanitized observations
are committed.

## How to reproduce without an Actions queue

Given the original unchanged `locomo.json`, the existing graph-causal source
`prepare` phase, a frozen registered Encoder directory and Python with CPU
torch, NumPy and safetensors:

```sh
export PYTHONPATH=scripts/memory_cell
python3 -m unittest discover -s scripts/memory_cell \
  -p 'test_parametric_stem_reader.py' -v
python3 scripts/memory_cell/parametric_stem_reader.py run \
  PUBLIC_ONLY PRESTAGED_FROZEN_ENCODER NEW_RUN
python3 scripts/memory_cell/parametric_stem_reader.py review \
  TRUSTED_PREPARED NEW_RUN PRESTAGED_FROZEN_ENCODER NEW_REVIEW
```

A new read-only hosted workflow has independent source-preparation, label-blind
original-model ranking, and postseal, model-reexecuting reference jobs. No
`blocking-ci` bypass, model selection or production source writer is added.

## Next: original Reader bottleneck

The next stacked study supplies these same sealed rankings as bounded original
source snippets to the exact pinned original SmolLM2-135M weights, comparing
empty, temporal, hybrid, parametric and hybrid+parametric conditions on ten
preselected questions. The Reader worker cannot see answers. A third process
scores unchanged model output only after its full journal is sealed; Reader
capacity and citation ability are separate from retrieval evidence accuracy.
The original FP32 implementation is **not** HF/BF16 parity-certified.
