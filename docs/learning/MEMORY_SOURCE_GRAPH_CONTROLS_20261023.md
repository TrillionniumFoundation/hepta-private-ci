# Hepta Memory: original-source A/C/D retrieval controls (2026-10-23)

**Research-only:** `SHADOW_ONLY / DENY_ALL / HOLD_NO_GO`. No training, Reader model, model-serving admission, topology activation, production memory mutation or source permission is granted here.

## Position in the A-I qualification program

The existing [historical same-source acceptance PR #3414](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3414) and [future prospective whole-answer gate PR #3411](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3411) are separate, not numerically interchangeable. This additive experiment supplies **actual original-source, non-neural retrieval computations for A/C/D** only; it is neither the nine-arm training run nor the eight- or eleven-contrast production-quality outcome.

The source is the [original LoCoMo 10-conversation release](https://github.com/snap-research/locomo/tree/3eb6f2c585f5e1699204e3c3bdf7adc5c28cb376), CC BY-NC 4.0, original source blob `d95b872480b413d935821fdc3c84f8a8f5f29e73`, SHA-256 `79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4`, 2,805,274 bytes. The reused historical parent plan is SHA-256 `62216f4a7b69fb9f27e087b49daa5249bfb485e99ef96b88123d8fb8b025ff2f` on #3125 pinned commit `7aac712474b850858d4d72b46419e39a3315d200`.

The fixed six evaluation groups are `conv-47, conv-42, conv-48, conv-43, conv-49, conv-50`. The runner permits only original question strings, dialogue text, speakers, timestamps and source IDs to reach retrieval. Gold evidence IDs, answers and categories are used in `independentEvidenceScore` **after** all selections have been generated. The two functions currently execute in one Node process, not independently authenticated hosts. The output answers no complete QA; it is a source-ID retrieval diagnostic.

## Actual implemented comparison

| Arm | Original-source implementation | Does *not* establish |
| --- | --- | --- |
| A | Genuine per-conversation BM25 term-frequency/IDF lexical search over original message text | The identical SQLite FTS5/Porter implementation used by the earlier PR #3125 baseline |
| C | Original-source time-adjacency + rare-token association graph; bounded two-hop traversal over BM25 seeds | A learned graph, entity-grounded causal edges, HippoRAG parity or neural Graph-RAG |
| D | Untrained, query-intent-based episodic/semantic/procedural neighborhood expansion over the same source messages | Actual trained multi-type Cell heads or a real production typed runtime |

All arms deliver **at most eight complete original turns and 4,096 UTF-8 frame bytes** without truncating frames. A/C/D have the same source and query census, but do **not** have equal actual index, CPU, graph-construction or TCO budgets. B (Dense + BM25 + real Reranker) and E-I (learned local Heads, sparse Router, learned Meta-Graph and actual Split/Merge) are **NOT RUN** in this experiment.

## Measured output (historical exploratory only)

The research-only result in [`report.json`](../../qa/stem-bakeoff/evidence/20261023-source-only-ACD/report.json) comes from the pinned original source and a frozen code commit. Its reported diagnostic is whether **all publisher-annotated source IDs** are selected, not whether the supplied context suffices to produce a correct answer.

| Arm | All annotated support IDs, 1,022 scorable | Six-conversation macro | Multi-hop all-ID coverage, 175 scorable |
| --- | ---: | ---: | ---: |
| A | 51.57% | 51.45% | 10.86% |
| C | 50.59% | 50.58% | 9.71% |
| D | 56.75% | 56.78% | 10.29% |

- C−A conversation-macro difference: **−0.87 pp**; no source-graph gain.
- D−A conversation-macro difference: **+5.33 pp**; descriptive, not a claim of independent or prospective improvement.
- D−C conversation-macro difference: **+6.20 pp**; also exploratory.
- Of 1,331 evaluation questions, 299 are adversarial and 10 lack usable evidence annotations. This experiment does **not** provide a learned abstention policy or answerability success.
- Multi-hop retrieval is weak in every arm and D's multi-hop all-ID score is lower than A's. The historical cohort has been used in earlier research. Six conversations are not 200 independent future source families.
- Contrast estimates are neither corrected for eleven preregistered A-I comparisons nor certified as causal; no model/head/router/split was trained, and no independent semantic QA judge was used.

This is a negative/diagnostic control as much as a limited positive episodic/typed result. It cannot justify promoting any MemoryCell or replacing a strong hybrid retriever.

## Reproduction

Download LoCoMo from the pinned original revision locally without committing or redistributing its licensed raw content. From the repository root:

```sh
node --check qa/stem-bakeoff/memory_source_graph_controls.mjs
node qa/stem-bakeoff/test_memory_source_graph_controls.mjs
sha256sum ORIGINAL_LOCOMO.json
node qa/stem-bakeoff/memory_source_graph_controls.mjs \
  ORIGINAL_LOCOMO.json predictions.json report.json
```

Both output paths must be absent: the CLI uses create-only writes. The `hepta-memory-source-graph-controls` GitHub Actions workflow fetches the exact original bytes, runs the actual A/C/D source-only retrieval and adversarial tests, reopens the committed report and recomputes *every arm's* full result object and paired contrasts. It uploads the row-level prediction census as a temporary build artifact. A queued or failed workflow is **not** a pass.

## Remaining independent blockers

1. Run real B Dense Encoder **and** real Reranker forwards with pinned original weights and no gold access; run a credible strong graph baseline, not only the basic source-derived C explored here.
2. Run **E-I** with real frozen shared Encoder, genuine local training on permitted train families, typed Heads, pre-execution sparse Router, learned evidence-bound Meta-Graph, actual split/merge and static equal-budget controls **on exactly the same memory queries**.
3. Lock one authoritative protocol and prospective comparison family across #3411 and #3414; never pool differently defined A/C/D results.
4. Use a fixed Reader/tokenizer/prompt and independent, source-grounded **whole-answer** adjudication, citation sufficiency, adversarial abstention, OOD and deletion/rebuild witnesses.
5. Obtain future windows, at least 200 authenticated independent source families, multiple-seed and whole-family uncertainty, complete physical resource/TCO accounting and required exact-head Rust/Bazel/security platform gates.
6. Keep learned models, memories and topology `DENY_ALL` unless separate qualified Artifact, Ledger, Evaluation, Model/Graph Snapshot and FinalUse owners approve the corresponding version. An external source hash is not a signature.

**None of these scientific or production blockers is closed by this A/C/D original-source research control.**
