# MemoryCell A--I strict task-level ablation matrix V1 (research / deny-all)

## Decision and scope

This change supplies a **predeclared, independently recomputable audit contract** for
nine experimental arms. It does **not** claim those nine models ran, that a
MemoryCell beat Hybrid-RAG/Graph-RAG, or that any source can enter production.
The source/revision owner, evaluator, trainer, and Artifact/Topology owners must
remain separate. All current outputs are `SHADOW_ONLY / DENY_ALL / HOLD_NO_GO`.

A previous LoCoMo retrieval experiment had only a weak BM25 comparison and
untrained Episode organization (with multi-hop regression and failed abstention).
The real router and equal-budget evolution results on historical news tasks did
not produce a stable held-out accuracy win. Those outcomes must not be imported
as if they were nine paired memory-task trials. See PR #3125's retained evidence
under `qa/stem-bakeoff/evidence/20261022-{locomo-memory-retrieval,real-cell-router,real-cell-evolution}`.

## Frozen arms and actual producer requirements

| Arm | Producer requirement | Falsification / lesion control |
| --- | --- | --- |
| A | Native BM25 over identical authorized source texts | Exact same Top-K and context cap |
| B | Frozen dense retrieval + BM25 fusion + independently trained reranker | Dense-only, BM25-only, equal source rights |
| C | Graph-RAG / HippoRAG-style evidence graph retrieval | Edge permutation, necessary-edge removal, equal retrieval budget |
| D | Evidence-bound typed Episodic/Semantic/Procedural/Meta organization, no local SGD | Scramble type labels and compare B/C |
| E | One shared frozen Encoder, exactly one trained Head | Equal-cost untrained/frozen-nearest neighbor controls |
| F | Same shared Encoder, multiple typed private Heads | Swap Head/type correspondence; single Head E |
| G | F + independently trained sparse pre-execution Router | Fixed Router and all-Heads counterfactual; count Router work |
| H | G + learned source-bound association graph | Fixed graph and wrong-edge graph lesion |
| I | H + candidate-only Split/Merge/Retire & approved next-snapshot policy | Same-budget static specialists, parent rollback, no evolution |

**No placeholders may be counted as producer runs.** Each arm must emit one
actual source-bound prediction row for **every** frozen evaluation query, even
when its decision is unavailable or an explicit abstention. `memory_matrix_contract`
rejects missing arm results rather than impute, omit, or promote them.

## Pre-registered inputs and isolation

`plan.json` contains exactly nine arm identities, eight ordered contrasts,
source, reviewer-gold, blinded query, Reader, source-frontier and forget-frontier
SHA-256 digests; immutable train/calibration/evaluation/future-1/future-2/OOD
source-group assignments; one common per-query budget; source-group power floor,
effect-size floor and deterministic seed. Its bytes must be sealed to a separate
write-once artifact before the first training/evaluation outcome. An external
trusted commit or signature and chronological run registry are still required;
local SHA-256 strings alone are **not** signed evidence.

`queries.json` is a list of records with exactly:

`query_id`, `group_id`, `split`, `question`, `available_source_ids`,
`source_snapshot_sha256`.

`reviewer-gold.json` is a separate evaluator-only list with exactly:

`query_id`, `answerable`, `acceptable_answers`, `required_support_ids`, `slice`.

The training/serving worker must **not mount or read reviewer gold**. No query
source group may belong to multiple roles. Future windows must be genuinely
collected after freezing and sourced from new independent entities, not merely
later dates inside a repeatedly tuned historical benchmark. The auditor detects
manifest overlap but cannot attest real-time independence on its own.

`budget` contains positive integer ceilings for `top_k`, `max_context_bytes`,
`max_output_tokens`, `max_wall_ms`, `max_peak_rss_bytes`,
`max_resident_bytes`, `max_head_calls`, `max_router_calls`, `max_encoder_calls`,
`max_graph_calls`. Actual model/tensor identities, training steps, GPU forwards,
I/O, RSS, energy, and total ownership cost require **externally observed**
worker/host receipts. Budget compliance from a caller-supplied number is not
independent hardware measurement.

## Producer output and independent reviewer

Provide a directory with the **nine** text files `A.jsonl` ... `I.jsonl`.
Each actual row has exactly the following fields:

- `arm`, `query_id`, `plan_sha256`;
- `source_snapshot_sha256`, `source_frontier_sha256`,
  `forget_frontier_sha256`, `reader_sha256`;
- `selected_source_ids`, `abstained`, `answer`;
- `resources` with `wall_ms`, `peak_rss_bytes`, `resident_bytes`,
  `context_bytes`, `input_tokens`, `output_tokens`, `head_calls`, `router_calls`,
  `encoder_calls`, `graph_calls`, `energy_joules`.

Rows are immutable experiment journals, not a request for automatic evaluation
or authoritative citations. The auditor independently recomputes answer exact
match, **annotated** gold-source coverage, answerability/abstention and actual
per-query budgets. It rejects duplicate/missing query-arm pairs, fabricated
source references not in the query's permitted snapshot, stale frontiers,
source/Reader drift, invalid counters, and additional self-reported scores.

The strict V1 whole-task signal for answerable questions is:

`answered AND answer_exact_match AND all_annotated_support_ids_selected`.

For explicitly unanswerable gold, the strict signal is `abstained`.
This is conservative and machine-verifiable, **not** semantic answer grading,
causal sufficiency, citation entailment or a licensed external judge. Those must
be added as separately attested task-specific reviewers; a program task requires
real external program-execution verification, not an exact string heuristic.

## Freeze and audit commands

From the repository root (standard-library Python, no model downloads):

```bash
python3 qa/stem-bakeoff/memory_matrix_contract.py freeze \
  --draft /approved/plan.draft.json \
  --queries /sealed/queries.json \
  --reviewer-gold /reviewer-only/gold.json \
  --plan /sealed/plan.json

python3 qa/stem-bakeoff/memory_matrix_contract.py audit \
  --plan /sealed/plan.json \
  --queries /sealed/queries.json \
  --reviewer-gold /reviewer-only/gold.json \
  --predictions /read-only/nine-arm-predictions \
  --report /sealed/independent-review.json

python3 -m unittest discover -s qa/stem-bakeoff \
  -p test_memory_matrix_contract.py -v
```

The freeze and review destinations are **create-only**; a second write fails.
The reviewer should run from an independently provisioned process with no
model/trainer authority, compare the previously published plan digest, and
archive input hashes + exact-head commit + real output file inventory.

## Primary statistical family (frozen order)

D--B, E--D, F--E, G--F, H--G, I--H, I--B, I--C.

Use group-macro **strict task success** with paired whole-source-group
resampling, descriptive 95% bootstrap intervals, one-sided paired sign-flip
randomization tests, and Holm family-wise adjustment across **all eight**
predeclared evaluation contrasts. No randomization over individual questions.
The example V1 admission requires at least 30 independent source groups in the
evaluation window **and each** of two new future windows, an ex-ante minimum
absolute lift (for example 0.03), and no unreported safety/abstention/OOD
regression. Those numeric thresholds are experiment policy, not retrospective
thresholds chosen after seeing results.

The Python reviewer produces `diagnostic_statistical_gate`, **never**
`scientific_superiority_established=true` or production authority: it does not
independently authenticate the data owner, model binary, model's input context,
semantic answer support, training cost, future independence or deletion efficacy.

## Resource and science reconciliation required outside this pure verifier

- **Equal evidence:** identical immutable root inventory, ACL, query and
  support bounds; full Reader input reconstructed by independent source owner.
- **Equal inference:** same Reader weights/prompt/output limits, Top-K and
  context bytes, physically observed Head/Router/Graph invocations, RAM/VRAM,
  FLOPs, p50/p95 latency, throughput and energy when metered.
- **Equal training where causal:** especially I vs H vs equally budgeted static
  specialists, same resident tensor bytes, updates, source-family opportunities,
  Router and Head work; distinguish cost cap from **exact** matched spending.
- **Negative transfer / ablations:** frozen vs learned, typed swapped, wrong
  graph edges, no Router, split vs static, merged vs parents, task-specific
  multi-hop / temporal / OOD / rare class / calibrated abstention.
- **Withdrawal:** reverse ancestor closure, tombstone frontier movement,
  contaminated Artifact denial, rebuild, stale preview rejection, final-use
  deletion tests (including remembered parameter influence).
- **Blind reviewer:** independently provisioned task semantic/program judge,
  escrowed answers, entity-disjoint prospective windows, reviewer attestation.

## Open blockers (none waived)

| Blocker | Concrete closure evidence |
| --- | --- |
| B/C strong baselines | Real trained dense/reranker and real Graph-RAG results on the identical memory queries, sealed model/source receipt |
| D--I end-to-end Memory tasks | Nine complete physical row censuses, trained Artifact digests, evidence and output verification; historical news labels are insufficient |
| Equal total cost | Actual training, Router, serving, shared Encoder, RSS/VRAM, latency/energy/recovery costs and matched I/H/static comparison |
| Independent future evaluation | Two post-freeze new-source collection windows, 30+ independent groups each and group-level uncertainty |
| Genuine scientific uplift | Positive predeclared whole-task gains vs B/C, all causal ablations and no critical safety/negative-transfer regressions |
| Evidence authority / forgetting | Independent Source/Revision + withdrawal attestations and no stale parametric influence granted use |
| Exact-head CI / deployment | All applicable `blocking-ci`, Architecture, V8 and OS/security gates conclusively green at the final SHA; explicit owner authorization |

Until these conditions are met, report honest negatives and preserve
`SHADOW_ONLY / DENY_ALL / HOLD_NO_GO`. A green unit-test job only certifies the
**audit contract**, not a nine-arm experiment, model superiority, or production
MemoryCell activation.
