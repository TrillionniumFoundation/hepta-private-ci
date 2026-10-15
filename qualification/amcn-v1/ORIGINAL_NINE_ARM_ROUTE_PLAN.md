# AMCN source-first nine-arm route materialization (shadow-only)

This increment closes a missing execution boundary between **original physically reloaded #1968 Head probabilities**, source-first candidate selection, independently supplied **actual strong-RAG route outputs**, a registered fixed HNMF graph, TRAIN-only graph relation coefficients, and the already existing #2085 **same frozen Reader** original-answer execution path. It is not a production model, a new memory writer, an independent host/reviewer, or proof of adaptive memory superiority.

## Exact prerequisites

`amcn_causal_route_plan.py` requires six **out-of-band SHA-256 pinned, immutable JSON files**:

1. `source`: complete eligible source inventory for every question, not a publisher-label-selected shortlist. Each source binds ID, original root, exact scope/generation, current-not-revoked marker, revision, original UTF-8 content SHA, source-first Encoder input row ID and reconstructed input digest; source-family and temporal splits must remain separate. A fake `revoked=False` flag is only a caller declaration until the source owner authenticates it.
2. `predictions`: original `amcn_typed_budget.py` saved TRAIN-only physical five-arm Head probabilities, with exact row/source/type/split input hashes.
3. `bank`: complete output of the existing `amcn_causal_physical_bank_bridge.replay_and_bind_original_bank`, including **six actually reloaded safetensors Heads, 5 forwards per original heldout row**, two independent equal-cost trained Head banks, frozen Head and negative authority. Self-generated JSON can imitate SHA strings; it is not independently authenticated model material. Prefer `build_from_original_physical_bank` to force physical re-execution before plan construction.
4. `rag`: **original external strong hybrid-RAG execution receipt** and full-source inventory/immutable request per question. A BM25 shortlist is **not** a strong RAG substitute. If actual RAG discovers sources outside lexical Top-16, they MUST enter the common candidate union and receive real Head Encoder/forward predictions before comparing any arms. Missing rows refuse the entire study; silently restricting RAG to lexical Top-16 is scientifically invalid.
5. `graph`: registered source-bound original edge sets, one predeclared lesion edge and six real TRAIN-only relation coefficients plus immutable physical training/graph receipts. Three interventions are fixed weights, trained relation weights on unchanged topology, and source-supported edge lesion. Graph association scores are ranking signals, not causal/factual authority. Graph discoveries outside Top-16 also require common physical feature forwards. Frozen and learned graph must preserve provenance and final evidence count.
6. `reader`: one exact Reader/Tokenizer/Prompt/Encoder source tuple and a fixed input/output token ceiling for all original nine arms.

Only after all six records pass exact source checks is a **create-only** full-nine-arm request plan emitted. Gold labels and outcome scores are not read. All plan source candidates are capped and final Reader evidence counts match across arms. Original source-root transitive aliases are extended with shared **actually eligible evidence roots** to prevent counting linked questions as independent.

## Execute the source-only plan bridge

```sh
PYTHONPATH=qualification/amcn-v1 python3 qualification/amcn-v1/amcn_causal_route_plan.py \
  --source /pinned/original-complete-source.json --source-sha256 "$SOURCE_SHA" \
  --predictions /pinned/original-physical-head-predictions.json --predictions-sha256 "$PRED_SHA" \
  --bank /pinned/six-head-physical-bridge.json --bank-sha256 "$BANK_SHA" \
  --rag /pinned/original-strong-rag-route.json --rag-sha256 "$RAG_SHA" \
  --graph /pinned/original-hnmf-trained-graph-routes.json --graph-sha256 "$GRAPH_SHA" \
  --reader /pinned/one-original-reader-tuple.json --reader-sha256 "$READER_SHA" \
  --final-k 4 --output /new/only-once/original-nine-arm-route-plan.json
```

For physical re-execution rather than consuming a bank JSON, use the `build_from_original_physical_bank` Python entry point with the original `FeatureMatrix`, `type_by_row`, TRAIN receipt, six Head safetensors and externally supplied tensor/source SHA pins; that calls the **original #1968** safetensors validator and all five physical Head forwards for every heldout source pair before constructing any Reader request.

`original-nine-arm-route-plan.json` contains a nested `plan` suitable for `amcn_causal_reader_generation.generate_original`. Pass **that nested plan**, with an independently pinned exact byte representation, to the Reader—not the wrapper. Execute only after an independently checked original Reader model inventory exists, then use the independent `amcn_causal_journal_review.py` and a separately authenticated scoring authority. Any original failure remains a failure. Candidate metadata never grants `FinalUse` or production selection.

## What this increment proves and does not prove

The new source-only unit tests exercise real BM25 numerical ranking, typed/pooled score sorting, common original source union, graph intervention and lesion reconstruction, stronger RAG sources absent from lexical Top-16, source revocations, exact Reader binding, transitive evidence-root clustering and byte-exact CLI pins. These use **synthetic input packets and predictions**, not pretrained Encoder/Reader weights, original hybrid-RAG executions or independently judged natural tasks.

The **current original 44-question historical LoCoMo source-first labels** had a negative result (original uniform Head weak-support Hit@1 typed 4/44; lexical 14/44). Separate post-hoc balanced-sampling outputs must never be mixed into that frozen census. Authentic complete nine-arm source/graph/Reader material is not available in this experiment branch, therefore this increment cannot assert actual nine-arm model calls or wins. Production remains **DENY_ALL**, Draft, no main merge, no `blocking-ci` waiver and no independent future-calendar observation.

## Exact two-hop candidate-frontier correction

The original HNMF `FrozenGraph` candidate traversal is bounded to **two
outgoing steps**. A prior route-plan implementation included only the first
neighbor of BM25 seeds, incorrectly disadvantaging the registered graph.
`amcn_causal_route_plan` now traverses registered source-bound directed
non-`contradicts` graph edges for at most two hops, with deterministic source
order and a strict common 512-source cap. The independent strong-RAG selection
is retained unchanged and never used as an unregistered graph expansion seed.
Graph nodes discovered only at hop 2 must still have original source-bound
physical Encoder/Head feature predictions; absence causes explicit refusal.
A graph frontier larger than the cap is rejected, never silently truncated.

Two additional hermetic adversarial regressions verify the missing-second-hop
forward refusal and complete-second-hop common candidate inclusion while
leaving original strong-RAG delivered evidence unchanged. Combined source-only
test count **82/82 locally**; no additional pretrained model/Reader execution
or measured task performance is claimed. This correction changes a research
mechanism, not HNMF production graph ownership or the pending qualification.


## Physical relation-graph integration and frozen seed correction

The source-first BM25 seeds for each original question now remain the **only**
graph propagation roots. The learned-Head ordering and the independently
executed strong hybrid RAG may alter final selections but never silently
become extra graph seeds. All graph arms use the same immutable Top-16 lexical
seed IDs, original source frontier, maximum two hops, final evidence budget
and Reader identity. Two-hop signed propagation uses one bounded visit per
source/destination per seed, prevents cycle amplification, and preserves
negative relation suppression. The earlier direct second-hop source discovery
without second-hop scoring was incomplete; this change corrects both sides.

`amcn_causal_graph_training.py` calls the **existing original**
`amcn_learning.train_relation_router` (real PyTorch SGD), bound to exact
original `FrozenGraph` source/edge SHA, authorized TRAIN-only relation
examples, precommitted original source/future-family exclusions, optimizer
steps and a registered lesion edge. `independent_sgd` recomputes the six
original coefficient updates independently using scalar logistic gradients
and checks numerical parity without claiming source truth.

`build_with_original_trained_graph` will refuse missing per-question
registered physical graph supervision; `build_with_original_physical_heads_and_graph`
first reloads/re-forwards the actual #1968 six Head safetensors before it
accepts original graph-owner observations. Neither wrapper creates a
strong-RAG retrieval receipt, genuine Reader outputs, independent judgments,
future windows or authority.

The standalone graph workflow physically executes the original Torch owner
on **synthetic TRAIN relation examples** as an original-code integration
and fault test. The numeric suite lives at
`test_amcn_physical_graph_training.py`, deliberately separate from the
stdlib-only nine-arm source/provenance workflow. Source-only CI must not
silently import Torch by discovering all test files under a broad glob.
Until the exact GitHub runner successfully completes, local scalar tests
must not be relabelled an exact-source hosted Torch/graph run.


## Baseline-sign and graph TRAIN source-family hardening

The fixed graph arm's baseline coefficients retain the HNMF inhibitory sign:
`contradicts=-0.5`, while registered non-inhibitory relations retain `+0.5`.
Previously giving every relation `+0.5` would have made the learned graph's
negative coefficients look beneficial simply because the fixed graph had the
wrong sign. This is a hypothesis/control correction, not a measured improvement.

TRAIN-only edge-label admission now also excludes original RETENTION,
prospective question families, their case source roots and all actual eligible
source roots, closed over admitted transitive source aliases. Unknown
alias endpoints fail **before** any Torch optimizer call. Each graph physical
training request must declare that entire derived exclusion roster, not just
the public FUTURE_A/FUTURE_B family names. This guards an avoidable
old-source/future-source contamination route; an independently authenticated
original-source/label owner is still a prerequisite for causal inference.

The exact-source local stdlib-only suite covered these new controls. Only the
separate original-Torch graph workflow can prove the original owner was
executed against this new exact HEAD; no answer-level outcome, independent
future window, or production authority follows from passing source tests.
