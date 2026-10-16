# MemoryCell Meta-Graph: original-source local execution and independent audit (2026-10-16)

**RESEARCH ONLY / DRAFT / DENY_ALL / NO MAIN MERGE / NO FINALUSE / NO PERFORMANCE PROMOTION.**
This is a *post hoc* evaluation of the already-specified five-arm source-only trial,
not a prospective independent model study, semantic evidence adjudication,
or evidence of trained MemoryCells / emergent graph learning.

## Original bytes and execution identity

- Original source: pre-existing GitHub Actions
  [run 37862780268](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/37862780268),
  staged artifact ID `11586991191` (`memory-native-staged-inputs`).
- Actually extracted `memory-inputs/locomo.json` from that archive,
  exactly **2,805,274 bytes**, SHA-256
  `79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4`.
- Prepared via *local independent reconstruction of the registered
  `associative_question_conditioned.py prepare` source-only input format*.
  Its 5,804 eligible public messages, ten dialogue families, 240 questions,
  238 valid evidence-positive cases, 224 cases with full evidence in the source
  pool and BM25 107/238 match the prior registered full-source census.
  **Exact-byte parity to the canonical hosted preparer remains pending.**
- Public SHA-256 `e3c9fe407afcc08a153eeb0122b107314443335cb8f153b6557693bdbf900455`;
  private derived annotation SHA-256
  `dfdf05dda8d552f2fe49f5aa09661ef5a81d7ed83d4ec876e84ada6138b77b87`.
  Private annotations were not present in the ranking input directory.
- Actual five-arm `memory_graph_source_trial.py` source byte-equivalent to
  Git blob `3661417b72f806b4a6f953cf8d19ed6a9147de55`.
  The local compatible V1 graph implementation was not byte-identical to the
  remote V1 graph blob; its traversal protocol was equivalent for this dataset.
  **Hosted exact-tree CI is still required.**
- 240-row prediction journal SHA-256:
  `882abb0424d3d92d9f096d86c1a864b35a589f095733c81fc474afd0f671ba8b`.
  Seal SHA-256:
  `3bcf2340ffd02186a3b6c15da4653c18696f683863f5219ca879115f703a2cac`.
  First source-review report SHA-256:
  `47866d4cae8b2800a8b4f8a011ab9f5986750167ae13e8a81fc8adbf4528be0f`.
  The distinct `memory_graph_independent_audit.py` opens pinned original
  conversations, checks question/source text against original positions,
  and agrees with the first review on all arm/family totals.

## Measured source-ID recall (not generated QA)

Among 238 canonical evidence-positive questions:

| Arm | Complete annotated evidence in Top-8 | Difference to BM25 |
| --- | ---: | ---: |
| BM25 | 107 | baseline |
| Adjacent temporal window | 121 | +14 |
| Two-hop temporal graph | **125** | +18 |
| Wrong-target shuffled graph | 101 | -6 |
| One local premise removed per seed | 123 | +16 |

The experiment builds 11,064 source-derived, within-session, directed
temporal-neighbor links across 5,804 original source messages. These are NOT
learned semantic, causal, or independently attested relational facts.

### Paired graph-vs-control analysis, exploratory only

| Control | Net graph gain | Per-question wins/losses | 10-family exact sign-flip probability | Paired family bootstrap delta-count, exploratory 95% |
| --- | ---: | ---: | ---: | ---: |
| BM25 | +18 | 35 / 17 | 0.01953125 | [8, 29] |
| Temporal window | **+4** | 7 / 3 | **0.3125** | [-1, 9] |
| Shuffled links | +24 | 25 / 1 | 0.00390625 | [13, 36] |
| Premise deletion | **+2** | 17 / 15 | **0.875** | [-10, 14] |

The sign-flip is an exhaustive mechanical sign enumeration over ten observed
family-score deltas. The resampling is a seeded, 20,000-draw paired family
bootstrap. Families may be correlated, they are not independently authenticated
populations, and there is no multiplicity-adjusted or independently justified
statistical superiority here. Do not interpret these as production p-values/CIs.

The most meaningful interpretation is that **temporal proximity helps the
retrieval ranking relative to plain BM25**, but more elaborate graph traversal
does NOT yet show a credible advantage over an explicit, cheaper temporal-window
control. Deleting a local edge sometimes *improves* results; thus edge traversal
is not validated as a causal-premise path.

### Observed resource envelope, not amortized TCO

On this local CPU Python environment, the **entire combined five-arm**
source-only ranking took 5.80 seconds wall time, 5.78 seconds user CPU,
and 104,852 KiB peak RSS. A separate independent original-source review took
4.28 seconds wall time / 105,108 KiB peak RSS.

These are observed **process envelopes**, not per-arm comparisons, inference
latency, GPU measurements, Encoder cost, index-building amortization, energy,
training, storage lifecycle, revocation, or Reader cost. Equal Top-8 outputs
do not equate to equal computation.

## Next binding gate

1. Run the newly added
   `.github/workflows/hepta-memory-meta-graph-source-trial.yml` at its
   exact pushed HEAD; first reproduce the historical journal SHA, or preserve
   a truthful mismatch and investigate preparer/traversal drift.
2. Execute independent exact-original reviewer after all 240 source-only
   predictions are sealed. The source-only worker must never receive
   `private.json`.
3. Hold out fresh independent source families and future windows; compare
   tuned, cached lexical/dense/hybrid/temporal strong-RAG baselines at matched
   reader token and *full* training/serving cost.
4. First prove the frozen Reader answers independent sufficient-evidence
   questions, then measure actual answers and citation entailment, lesion,
   old-task retention, and independent human adjudication.
5. Cell split, learned graph edges and NDU allocation remain separately
   unqualified hypotheses. Verify revocation, deletion non-resurrection,
   rollback, exact owner/authority boundaries and blocking-ci before any
   selection or promotion.

**Local execution is new source-ID evidence only**; it does not close
canonical hosted source parity, independent population, strong RAG, semantic
Reader, security acceptance, production cutover, or longitudinal capability.
