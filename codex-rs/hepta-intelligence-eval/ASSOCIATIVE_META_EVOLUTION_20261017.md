# MemoryCell Meta-Network — source-only trainable gate and type-split experiment

**Status:** RESEARCH / SHADOW_ONLY / DENY_ALL. Not a production MemoryCell,
not a learned general memory fabric, not a parameter-only language memory,
not a supported source of facts, and not a deployment or merger request.

## Exact ancestry and scope

Stacked on the isolated source-graph research PR #2486 at
`dde5ee160b11bdb1e6bddf1c5e27dac41fd630cb`, itself stacked on PR #2365
and the pre-existing PR #1452. Adds standalone source-only experiment, tests,
research documentation and a read-only workflow. Does not change a registered
wire contract, production Owner/Selector, `main`, `blocking-ci` or the shared
weight selection and retirement lifecycle. Reuse the current `cognitive.store`,
HNMF and artifact owners for future integrations instead of creating a new one.

## What is actually new

* A deterministic source-only **four-parameter** trainable graph routing head
  learns a bounded continuity proxy from observed historical source edges.
  It uses text-token overlap, event order, session and registered edge type.
  This is genuine numerical learning, but **not learning real QA utility**.
* A proposal splits that head into **two two-parameter typed heads** (temporal
  and lexical), with **four total parameters** and bounded wrong-type routing.
  The shared head trains for 128 updates x 4 parameter touches, while the pair
  trains for 256 x 2 touches. These are approximate scalar touches, **not equal
  FLOPs, wall time, train samples or an unbiased training-compute comparator**.
  Initial split is **not** an exact function-preserving parameter inheritance;
  the existing rank-splitting experiment owns that separate mechanism.
* Every trained candidate binds all original source root identities, ordered
  source digest, family scope, explicit non-authority fields, input model recipe,
  and static resource counts. A revoked ancestor denies the **entire** candidate,
  not a magical selective-unlearning claim. No live weight or selected topology
  is mutated. Although trainable routing weights change, this is NOT learned
  graph topology: endpoint and edge-type sets are frozen.
* Seven frozen-policy arms: BM25; temporal; fixed graph; source-trained shared
  gate; matched-parameter typed split; swapped child route; and topology-rewired
  typed control. All consume exactly the same original source inventory,
  question list and Top-8 evidence-ID budget, and use the same 2-round graph
  propagation and 3 BM25 seeds. The rewired control preserves the graph's
  edge-type, weight and degree distribution but permutes their endpoints.
* Provenance-rechecked, create-only, SHA256-sealed original prediction journal.
  `review` repeats every source-only training and ranking operation from the
  unchanged public source and compares canonical **full journal bytes before**
  opening pinned private annotations. Source-ID scores cannot grant answer
  correctness, citation entailment, statistical superiority or FinalUse.

## Frozen real-source protocol

The existing PR #2486 `prepare` stage admits the exact original LoCoMo source
SHA256 `79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4`.
It publishes only `public.json` and `manifest.json` to a clean worker. Each of
10 authored dialogue groups contributes at most 1,024 admitted historical ASCII
messages and 24 preselected questions, giving 240 fixed query IDs. The two
noncanonical reference questions remain in the full denominator. Historical
result conditions and model identities MUST NOT be rewritten as new observations.

The new branch's read-only Actions workflow runs three physically separated jobs:
privileged original preparation and adversarial tests; blind model training and
seven-arm ranking; and postseal source reconstruction, rerun, and scoring.
Workloads publish original hashes, process wall/peak RSS, unmodified predictions
and reviewer reports. Source labels must never enter the training/ranking job.

```bash
export PYTHONPATH=scripts/memory_cell
python3 -m unittest discover -s scripts/memory_cell \
  -p 'test_associative_meta_evolution.py' -v
# After the existing graph-causal prepare created PUBLIC_ONLY and PREPARED:
python3 scripts/memory_cell/associative_meta_evolution.py \
  run PUBLIC_ONLY NEW_SEALED_RUN
python3 scripts/memory_cell/associative_meta_evolution.py \
  review PREPARED NEW_SEALED_RUN NEW_REVIEW_JSON
```

The new runtime requires only Python 3 standard library; source parsing and
indexing reuse `associative_graph_causal.py`. The local development simulator
has 14 adversarial checks but does not count as original LoCoMo inference or
an exact-source GitHub CI pass. Only completed exact-HEAD Actions receipts can
upgrade that mechanical execution statement.

## Required negative-result controls and next qualification

1. **Compare with the temporal-only graph**: upstream evidence suggests that
   fixed temporal adjacency dominates the current result. Learned typed
   weights winning over BM25 but not temporal means there is NO incremental
   learned graph advantage. A swapped route not harming performance does not
   establish specialist routing.
2. Compare with the full-source cached, independently tuned BM25+dense+temporal
   hybrid at equal downstream Reader and actual lifecycle cost. The proxy-trained
   gate learns from the test dialogue's *source text*, not from independent
   external experience. Ten dialogues are NOT 200 independent families.
3. Prove the Reader can answer given sufficient evidence; test matched
   source-ID coverage vs actual natural-language answers, missing premises,
   supported citations, source corrections, Unicode, deletion and clean restore.
4. Before network evolution or serving, evaluate an independently sourced
   future-family and time split and implement topology candidate admission via
   `learning.plasticity` and immutable `learning.artifacts`, with exact
   generation fencing and qualified revert. Add real total cost and no-change
   selection; do not let a learning signal change source permissions.

Every result remains: `production_accepted=false`,
`statistical_superiority=false`, `independent_semantic_judge=false`,
`trained_memory_content=false`, `learned_graph_topology=false`.
An inconclusive or negative result is a valid output and prevents promotion.

## Observed original-source local research result, 2026-10-17

A subsequent **actual** source-only, postseal diagnostic used the already pinned
GitHub original-input artifact `11586991191` and PR #2486 public artifact
`12056496280`, source SHA `79fa87e9...be4`. All 10 original dialogue
groups (5,804 admitted messages; 240 questions) were processed; 238 had
scoreable canonical reference IDs and 224/238 had all reference sources within
the admitted corpus. The worker saw *only public files*. Its predictions were
sealed before the separately reconstructed original reference annotations
were opened. The public input and manifest matched the upstream archived
bytes exactly. A local compatibility port of the existing graph-causal source
code gave **0/240** exact ranking mismatches on all three frozen baseline arms
(BM25, temporal, fixed graph) versus upstream sealed predictions. This port is
not a substitute for exact-source hosted CI; the local processes did not use
physical host isolation.

| Complete reference source IDs in final Top-8 | Questions / 238 |
| --- | ---: |
| BM25 | 107 |
| Fixed temporal graph | **136** |
| Fixed temporal + lexical graph | 134 |
| Trained shared 4-parameter gate | 119 |
| Two trained typed children, 4 parameters total | 121 |
| Swapped type route | 118 |
| Rewired typed lesion | 105 |

Paired typed-split vs temporal: **2 gained / 17 lost / 219 tied**.
Paired typed-split vs shared: **2 gained / 0 lost / 236 tied**.
Typed-split was worse than temporal in nine of ten original dialogue groups,
and tied in one. The small advantage over this source-only shared gate does
not establish superiority over an appropriate matched model or stronger RAG.

The new source-only model journal SHA256 is
`2340a46f6c7477de11a43721bdd3572926c9e9a38327cbe6a604fa46272d6800`;
the local replay review SHA256 is
`faf849ce3d0218bf53c11a02a0fdf216f91b467e4ff2020e4f63d7876c621398`.
The observed original-run process wall was about 13.94 seconds and peak RSS
109,296 KiB on that local host; neither is a complete lifecycle TCO.
The immutable sanitized receipt is
`META_EVOLUTION_SOURCE_OBSERVATION_20261017.json`.
No raw original conversations, answers, model weights or private labels were
committed.

**Decision: retain fixed temporal graph; deny candidate promotion.**
These are source-ID diagnostics only. Model language generations: 0; learned
source content: none; trained topology endpoints: none; independent source
families, semantic citations, future-time transfer and full cost: unproven.
Production acceptance and superiority remain false.
