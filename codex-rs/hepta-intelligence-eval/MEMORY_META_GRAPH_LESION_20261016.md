# Memory Cell Meta-Graph lesion V1 (research only)

This additive experiment stacks on MemoryCell PR #2365 without touching the
existing selected Memory writer, reader, model installer, Rust owners, HNMF
wire contracts, training weights, or main.

## Experimental question

Can a **source-bound two-hop graph traversal** recover a target that cannot be
reached without the relevant graph edges? Does deleting the second premise or
permuting destinations remove that result?

This is a unit-scale controlled graph *mechanics* experiment, not learned
link prediction, causal inference, text retrieval, a pretrained Reader, an
independently sourced dataset, or a strong RAG comparison. All four queries
come from **one authored fixture family**, so results cannot support an
independent-sample confidence interval.

## Scope and strict negative controls

- Four arms: `no_graph`, `graph`, `shuffled`, `premise_deleted`.
- The evaluation-only expected node is never supplied to the recall method.
- Same seed/scope/generation and activation/hop budgets in every arm.
- An invalid source, duplicate node/edge, revoked support root, cross-scope
  target, old generation or unbounded budget is rejected or ineligible.
- The shuffled ablation deliberately builds incorrect destinations for
  **diagnostics only** and must never be used as a source-support projection.
- Returned packets declare `evidence_verified=false` and
  `production_accepted=false`. This is *not* the canonical HNMF RecallPacket.

## Run

From repository root (requires Python 3.10+; standard library only):

```sh
PYTHONPATH=scripts/memory_cell python3 -m unittest \
  discover -s scripts/memory_cell -p test_memory_graph_lesion.py -v
python3 scripts/memory_cell/memory_graph_lesion.py
```

Expected *authored-fixture* mechanics: graph 4/4, no-graph 0/4,
shuffled 0/4, and deleted-premise 0/4. These values are properties
of the constructed fixture, **not evidence of task-quality improvement**.

## Required next evidence

1. Frozen source-family/time splits and SHA-pinned original evidence records.
2. Same admitted candidate set and budget for lexical, dense, BM25, hybrid,
   temporal graph, parent Cell, typed split, true links, wrong links, and
   premise deletion.
3. A pretrained fixed Reader first proven capable of answering independently
   verified sufficient-evidence tasks, with actual citation entailment review.
4. Original answer/trace/cost receipts, complete training and serving TCO,
   source deletion/non-resurrection, restart, artifact and topology rollback.
5. Independent admission according to the HNMF/Neuron/learning owner policies.

**No main merge, production model promotion, new authority, or bypass of
`blocking-ci` is authorized by this experiment.**
