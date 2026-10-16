# MemoryCell meta-network: original-source graph lesion (research only)

**Status: SHADOW_ONLY / DENY_ALL / NO MAIN / NO FINAL_USE.** This stage extends
MemoryCell PR #2365, not a second Memory OS or production selector. It leaves
HNMF source, Neuron, Plasticity, Artifact and CNS ownership untouched. No
model is installed, no existing source fact is written, no Cell is promoted,
and neither `blocking-ci` nor any authority gate is bypassed.

## Why this experiment

The existing full-source 240-query LoCoMo shadow found BM25 complete Top-8
107/238 vs question-conditioned Cell 1/238 and RRF+Cell 101/238. This is
source-id evidence ranking, **not** natural-language answer accuracy. Adding
learned graph parameters now would confound retrieval, source coverage, Reader
capacity, topology and training. First test whether a bounded graph assembled
only from chronology and source-content overlap adds evidence coverage at all.

## Precommitted arms, shared budgets and negative controls

One exact original LoCoMo dataset digest (`79fa87e9...`), ten correlated
publisher conversation families, 24 source-independently hashed questions per
family (240 total), at most 1,024 chronological ASCII-admitted messages per
family, equal Top-8 output and unchanged BM25 seed rank (top 3):

1. `bm25`: exact cached full-source lexical ranking. A source-retaining control.
2. `temporal`: same BM25 plus at most two local steps in same-session source
   chronological adjacency, with degree and propagation caps.
3. `lexical`: BM25 plus source-only non-stopword overlap edges, with degree and
   document-frequency caps; does not use question answer/evidence annotations.
4. `fixed_graph`: source-only temporal and lexical edges combined.
5. `rewired_graph`: SHA-seeded, label-blind permutation of fixed edges preserving
   edge kinds/weights/count and **global degree distribution**, NOT per-original
   document degree or source semantics. This is a destruction/lesion control.

The graph is a rebuildable retrieval projection, not an authority/truth graph.
Its lexical edges are *association only*, never learned causal relations. No
trainable parameters and no fine-tuning are used. This deliberately isolates
fixed-graph contribution; it does not claim to measure learned graph gain, Cell
split benefit or NDU System 2 efficacy.

## Three independent execution boundaries

- `prepare ORIGINAL_LOCOMO NEW_PREPARED`: source SHA gate; train/test label
  separation, `public.json`, `private.json` and immutable manifest. Query
  sample selected by original qid hash **without** reading answer/evidence to
  choose sources or questions. No cross-conversation index.
- `run PUBLIC_ONLY NEW_RUN`: no private file in the worker input; complete
  five-arm source ranking for all 240 questions; create-only sealed original
  `predictions.json` and `seal.json`. Records real elapsed CPU scheduling time
  but does not infer full lifecycle TCO from it.
- `review PREPARED SEALED_RUN NEW_REPORT`: only after original model-free
  predictions are committed; compare exact manifests and re-execute all source-
  only ranking outputs, reject resealed forged outputs, open publisher evidence,
  compute family-level evidence coverage and record unscorable/unavailable cases.

CI performs these stages in separate jobs: worker downloads public-only artifact,
never the original corpus, reference labels, or private file. Independent review
rebuilds public bytes from the exact pinned source and refuses drift. Digests are
source-integrity checks and do **not** constitute independent human or publisher
signatures. The 10 LoCoMo conversation families are correlated; no claim of
200 independent sources, real future windows, or valid statistical superiority.

## Outcome interpretation

`complete_at_8` means every canonical annotated source ID is among the eight
retrieved IDs; `available_all` reports whether all annotated IDs are even in
the admitted source pool. `any_at_8` is weaker and must never be substituted.
Unresolved reference formatting and empty evidence labels have explicit counts.
Metrics are by original dialogue family, not falsely independent query rows.
Neither publisher evidence IDs nor token-F1 alone prove semantic correctness.

- If temporal/lexical graph merely helps the rewired lesion equally, there is
  **no demonstrated source-graph structural benefit**.
- If graph improves Top-8, next run the same Reader with unchanged prompts,
  complete original evidence and premise-deletion controls. Until fixed Reader
  can use sufficient evidence and cite it, there is no basis for claiming
  end-to-end MemoryCell/graph task gains.
- Only then compare frozen/split/merged parametric Cells and learned edge
  weights under matched trainable parameters, optimizer work, full lifecycle
  resources, prospective independent source-family tasks and human adjudication.
- Correction, withdrawal, tombstones, derived artifact unlearning, old-task
  retention, rollback and current authority remain mandatory separate gates.

## Reproduce

```sh
PYTHONPATH=scripts/memory_cell python3 -m unittest discover \
  -s scripts/memory_cell -p 'test_associative_graph_causal.py' -v
PYTHONPATH=scripts/memory_cell python3 scripts/memory_cell/associative_graph_causal.py \
  prepare /path/to/sha-pinned/locomo.json /tmp/graph-prepared
mkdir /tmp/graph-public
cp /tmp/graph-prepared/{public,manifest}.json /tmp/graph-public/
PYTHONPATH=scripts/memory_cell python3 scripts/memory_cell/associative_graph_causal.py \
  run /tmp/graph-public /tmp/graph-original-run
PYTHONPATH=scripts/memory_cell python3 scripts/memory_cell/associative_graph_causal.py \
  review /tmp/graph-prepared /tmp/graph-original-run /tmp/graph-review.json
```

**Negative claim defaults:** `production_accepted=false`,
`statistical_superiority=false`, `reader_ability_evaluated=false`,
`trainable_graph=false`, `full_lifecycle_cost_measured=false`,
`independent_semantic_citation_adjudication=false`.
