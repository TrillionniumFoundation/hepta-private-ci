# MemoryCell V2: source-only LoCoMo Meta-Graph five-arm lesion

**State:** DRAFT / RESEARCH / DENY_ALL / NO FINALUSE / NO MAIN MERGE.
**Parent:** existing MemoryCell PR #2365 / Meta-Graph PR #2491. No new memory
writer, inference provider, training selector, production graph, authority
issuer, or release permission is created.

## Purpose and data boundaries

The first synthetic V1 graph fixture only demonstrates deterministic two-hop
traversal; its 4/4 result is defined by an authored graph and **does not
demonstrate task understanding**. V2 reads a previously registered full-source
LoCoMo `public.json` built by
`associative_question_conditioned.py prepare` from dataset SHA-256
`79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4`.
Its **ten correlated dialogue groups** contain 240 questions and their exact
eligible public source records. No query answer, evidence annotation, or
semantic judge label enters ranking.

No pretrained Encoder, MemoryCell tensor, graph trainer, generative Reader or
learned relationship is executed. Temporal-neighbor relations are created only
between consecutive observed records in the same session. Bidirectional
adjacency means *temporal proximity* and **never causal support, implication,
permission to execute, or semantic entailment**. All node identities carry
source-content digests; scope and source-root revocation are enforced by the
research graph mechanism before traversal.

## Frozen source-only arms and budgets

Every condition sees exactly the same complete source catalogue, one original
question, the same initial BM25 ordering, and returns exactly eight *original*
source IDs per question.

| Arm | Inference rule | Question answered |
| --- | --- | --- |
| `bm25` | Original full-source lexical BM25 Top-8 | Strong simple no-graph control |
| `temporal_window` | Query-independent adjacent source windows around BM25 seeds | Does direct indexing match graph traversal? |
| `graph` | Two-hop bounded temporal graph from the same two seeds | Does graph traversal improve evidence Top-8? |
| `shuffled` | Wrong-target graph ablation (not factual relations) | Is a candidate gain sensitive to edge identity? |
| `premise_deleted` | Delete the first eligible outgoing seed edge, without gold | Does one local graph link affect results? |

The deterministic readout uses a fixed reciprocal-rank blend, a maximum
of two seeds, two graph hops and sixteen visited nodes per seed; the caller
receives exactly eight source IDs. **Equal final Top-8 size is not equal total
work, FLOPs, memory, candidate count or hardware cost.** An experiment receipt
records native process resources and graph edge counts. BM25 is a meaningful
lexical control but not a tuned dense/hybrid/graph strong RAG+Reader comparator.
`temporal_window` deliberately tests a cheap non-graph alternative.

The premise-deletion edge is selected from source-only graph order; it is not
chosen using a benchmark gold label. Shuffled edges are *untrusted ablation
internals* and never become HNMF source, causal, or permission edges.

## Reproduce (standard library for the graph stage)

First prepare the original frozen corpus using the existing registered
`associative_question_conditioned.py prepare` in a pinned research environment,
then **physically separate** `public.json` and `manifest.json` from
`private.json` before running the ranking worker:

```sh
PYTHONPATH=scripts/memory_cell python3 -m unittest discover \
  -s scripts/memory_cell -p 'test_memory_graph_source_trial.py' -v
PYTHONPATH=scripts/memory_cell python3 scripts/memory_cell/memory_graph_source_trial.py \
  run /tmp/meta-public /tmp/meta-run-new
# Reviewer only after journal + seal are complete:
PYTHONPATH=scripts/memory_cell python3 scripts/memory_cell/memory_graph_source_trial.py \
  review /tmp/meta-trusted-prepared /tmp/meta-run-new /tmp/meta-reviewed-new.json
```

Hosted workflow `.github/workflows/hepta-memory-meta-graph-source-trial.yml`
uses separate prepare, source-only ranking, and postseal reviewer jobs. The
first and last job independently reconstruct the SHA-pinned original source.
The ranking worker receives only public source, questions, and the manifest.
The postseal reviewer reconstructs and verifies exact public bytes, recomputes
**all 240** rankings and validates every sealed source ID before opening
the original private evidence labels. Reported results are exact-ID evidence
coverage, not semantic correctness or citations.

## Gate for next study

Before any claims of graph improvement or universal MemoryCell:

1. Review the **actual original** postseal five-arm journal and all 10
   dialogue-family denominators, and retain every failure/unresolved label.
2. Compare paired family outcomes against BM25, temporal window, dense/hybrid
   and a tuned provenance-aware RAG at matched complete resource budgets.
3. Independently establish Reader sufficient-evidence capability; run
   no-evidence, sufficient, missing-premise and actual-retrieval arms using
   the **same frozen Reader**, with explicit citation and answer adjudication.
4. Test genuine query-conditioned parameter Cell, typed split, graph lesions,
   retraining/retention and prospective future source families. Two tests from
   one original dialogue are not two independent populations.
5. Source corrections, withdrawal, influence retraining, cache invalidation,
   crash/reopen, full lifecycle accounting and owner-selected promotion must
   pass independently. Source-read permission never grants training permission.

Until all gates are satisfied: `production_accepted=false`,
`causal_graph_or_parametric_advantage=false`, no `blocking-ci` waiver,
no HNMF current-memory rewrite, no model selection and no claimed neural
network emergence.
