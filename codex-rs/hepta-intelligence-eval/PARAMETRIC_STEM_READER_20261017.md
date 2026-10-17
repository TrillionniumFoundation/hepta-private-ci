# Original-weight language Reader after source-only parametric MemoryCell

**DRAFT / SHADOW_ONLY / DENY_ALL.** Layered on the original frozen MiniLM
parameter-memory retrieval study in PR #2636. No production selection,
model-serving change, fact writer, tool authority, new wire version or release.

## Original Reader protocol and isolation

After the actual frozen MiniLM and low-rank Cell source-ranking journal is
**already sealed**, `parametric_stem_reader_language.py` selects exactly one
question per each of the ten original LoCoMo dialogue groups via an independent
SHA256(question-id) hash. Every selected question receives five conditions:
empty, temporal, cached BM25+dense+temporal RRF, trained low-rank MemoryCell,
and RRF plus MemoryCell. Each condition gets the same `max_new_tokens=48`,
evidence Top-8 ceiling, source excerpt policy and immutable original
SmolLM2-135M-Instruct FP32 CPU Reader weights. No benchmark answers or gold
source IDs appear in the Reader worker. This implementation is inherited from
the repository's `offline_smol_reader.OriginalSmol`, NOT an HF parity-certified
replacement for registered Transformers/BF16 inference.

Model loading verifies each of the eight original publisher file digests and
the eight-file registered Reader inventory/transport manifest. The already
staged original GitHub archive is used; weights are never uploaded in this PR.
The Reader returns raw language output, actual evidence source IDs, token
identities, unsuccessful/unavailable attempts, model identity and immutable
journal hash. It never post-inserts citations or rewrites answers. The reviewer
reopens the exact original LoCoMo source SHA only **after** all 50 original
Reader calls are sealed; it checks every question/arm/evidence identity and
compares unchanged outputs with published string answers. Mean token-F1 is a
weak diagnostic, not an independent semantic correctness/citation score.

## Actual original-weight CPU execution — 2026-10-17 local

All **50/50** model attempts finished and produced sealed output. Ten historical
questions were preregistered; eight have nonempty string-valued publisher
answer references. Each arm therefore has denominator 10 planned / 8 string
scorable; unscorable answers are retained, not silently dropped.

| Reader evidence arm | Original mean diagnostic token-F1 (8 scorable) |
| --- | ---: |
| No evidence | 0.052835 |
| Temporal | 0.077519 |
| RRF | 0.121846 |
| Parametric MemoryCell | 0.053190 |
| RRF + MemoryCell | 0.122656 |

No model output emitted the requested `[E1]`..`[E8]` evidence marker:
**0/50** output answers with a citation label. When none are emitted,
citation precision is **undefined**, not 100%. The tiny RRF+MemoryCell token-F1
change has no independently supported task or statistical superiority; source-
ID complete evidence coverage was actually **worse** with the added Cell on
all 238 historic evidence questions (93 vs RRF 100). Consequently the source
and Reader results jointly say **do not promote the trained Cell**.

Frozen Reader file identity:
`afb110c28d68c8956d372e428277fa8f164a2304f0ef9d9064a084f3fab7d94c`.
The original 50-output journal SHA256 is
`da577e20660102e0d5a40f59b5729c4192f95b9717ffdfffb57129cb5aa2a3b7`.
The postseal scorer output SHA256 is
`bb25a0f2e11662e2592f55a9c01f88fe1a45ff55dba1de6fee742f23492b9393`.
No public model files, benchmark private annotations or original dialogue
content are committed; the sanitized receipt is
`PARAMETRIC_STEM_READER_ORIGINAL_20261017.json`.

## Reproduction / exact-source workflow

With public-only sealed retrieval results, original pinned Reader eight files
plus non-self-referential `SHA256SUMS` manifest, and privately preserved original
LoCoMo for **review only**:

```sh
export PYTHONPATH=scripts/memory_cell
python3 -m unittest discover -s scripts/memory_cell \
  -p 'test_parametric_stem_reader_language.py' -v
python3 scripts/memory_cell/parametric_stem_reader_language.py run \
  PUBLIC_ONLY SEALED_SOURCE_RANK READER_TRANSPORT NEW_READER_OUTPUT
python3 scripts/memory_cell/parametric_stem_reader_language.py review \
  PUBLIC_ONLY SEALED_SOURCE_RANK SEALED_READER ORIGINAL_LOCOMO NEW_REPORT
```

A physically separated hosted four-job research workflow re-stages the original
source and weights, trains/seals source rankings, runs original-model Reader
without hidden labels, then reexecutes original Encoder+training for source
integrity and reviews the Reader output. The local execution is *not* a hosted
completion receipt; all exact-HEAD Actions jobs must complete for that claim.

## Explicit blockers and next design consequence

This study does not evaluate prospective independent source families,
user-permission boundaries, exact Hebrew/Chinese Unicode tokenization, an
independent semantic judge, a 200-source effective sample count, full lifecycle
TCO, selective machine unlearning, or original Reader HF/BF16 parity.

A useful next candidate must improve **actual semantic Reader answer and
supported citation quality** over a cached, independently tuned strong
retrieval baseline at equal total source/Reader budget. If the original small
Reader cannot reliably answer with complete premises and cite them, fix
Reader capacity/prompt/evidence construction first, not the number of Memory
Cells. NDU can learn *whether to query the memory* only after independent
longitudinal outcomes and the existing non-learning authority rules.
