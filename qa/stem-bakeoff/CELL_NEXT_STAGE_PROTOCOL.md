# Shared feature / small Cell study: frozen protocol

This is a bounded research continuation of commit
`429894ac8e0818102cfdea4ad47a56e4583b2902`. It preserves the existing
`SharedEncoderOwnerV1` / `CellHeadV1` ownership boundary. It does not install a
learned native Head or grant production execution authority.

## Questions and independent acceptance boundaries

1. **Feature interface:** one immutable event-bound feature batch can supply
   global features and, when requested, actual native token features. Encoder,
   preprocessing, extractor, dependency, source and generation identities must
   be explicit. Global-only retention must not retain a private copy of tokens.
   Character spans must come from tokenizer offsets; absent media alignment is
   not manufactured. One request must cause exactly one observed model forward.
2. **Learning:** compare fixed private Heads and retrieval/prototype controls at
   8, 32 and 128 distinct labelled source groups per task, with no heldout-label
   feedback. Report negative results. Running optimization successfully does not
   by itself establish useful learning or justify a gated Head over a linear one.
3. **Scale:** evaluate actual arrays at 64, 256 and 1024 resident Cells, separately
   reporting independent target definitions, unique fitted weight states and
   resident replicas. Verify scalar/batched parity, routing coverage, bounded
   cache and durable training. A fanout replica is not another learned task.
4. **Source recovery:** retain original issue text independently of model
   truncation; read it by exact ID/revision in a fresh process. Byte-exact source
   reads and semantic prediction have separate scores.

## Corpus and task meaning

The source is the official historical SWE-bench test corpus at immutable
[revision e48e2bd1e9fecd5bbd641e9414ac59da9f2e69f6](https://huggingface.co/datasets/princeton-nlp/SWE-bench/tree/e48e2bd1e9fecd5bbd641e9414ac59da9f2e69f6).
The acquired Parquet SHA256 is
`db4f70ef735b3162c74801ddcdf8d7bae8d704193788c6d844f898c20b571cbb`.
This experiment repurposes historical issue records for structural prediction;
its scores are **not SWE-bench repair success rates**.

`prepare_repair_cohorts.py` fixes 60 binary lexical patch predicates. Eligibility
uses only training counts, requiring at least 64 distinct positive and negative
events. A fixed capacity selects the first 32 eligible predicates in their
predeclared order. They form **one correlated repair-shape family**, not 32
independent capability domains. Regex matches include comments and strings;
labels do not claim AST semantics, root-cause adjudication or optimal repairs.

Only repository name and original issue description enter prediction. Gold
patches, test patches, hints and fail/pass lists are excluded. Source targets and
their hashes are retained separately. Normalized issue, changed-patch, predictor
text and source duplicate groups are formed before chronological 60/20/20 split
boundaries. Whole crossing groups are excluded, and one earliest event remains
per other group. Text is explicitly capped at 16,384 UTF-8 bytes; original source
text remains recoverable from its independent bank. Foundation-model exposure
to public historical issues is unknown. This is not prospective traffic.

## Fixed learning plan

- Granite 97M and EmbeddingGemma 2 use their registered immutable checkpoint
  revisions, CPU float32, text profile, classification preprocessing, 192-token
  maximum, batch 16, four Torch threads, and one owner per extraction process.
- Samples per Cell: 8 / 32 / 128; seeds: 7 / 17 / 29; nested, balanced, without
  replacement, at most one record per source group and normalized text.
- Arms: exact text lookup, BM25, dense nearest neighbour, class prototype,
  learned linear, learned feature gate and learned rank-8 residual Head.
- Learned arms: 200 full-batch Adam steps, learning rate 0.02, L2 0.001,
  at most 100,000 private parameters; actual parameter and optimizer bytes are
  reported. Encoder parameters stay frozen. Different Head architectures use
  different actual parameter counts within this shared ceiling.
- Temperature uses calibration labels only and the fixed grid 0.5/1/2/4/8.
  Abstention confidence is fixed at 0.7. Exact lookup misses abstain explicitly.
- Metrics: forced success/accuracy, balanced accuracy, positive-class recall,
  NLL, Brier score, calibration error, coverage, selective accuracy and accepted
  correct fraction over **all** rows. The latter prevents abstention inflating
  apparent success.
- Controls: every fitted learned Head is compared with parameters disabled and
  shuffled, and its artifact is reloaded in a fresh process. That process is
  given features and model identity, not labels; it shares the host filesystem
  and is not represented as an OS security boundary.
- All predefined comparisons are reported. No model, task, seed, budget or
  threshold is selected by heldout results. Source-group paired bootstrap may
  summarize uncertainty; correlated predicates must be resampled together.

BM25 sees the bounded full predictor text; dense/learned arms see the encoder's
192-token representation. This explicit resource tradeoff is not equal input
information. It is included because a practical low-cost lexical alternative
must not be omitted. Exact text lookup on a text-disjoint semantic split is a
negative generalization control, not the positive source-recovery assay.

## Scale and cost plan

Use each task's predeclared gated seed-7, 128-example artifact, regardless of its
heldout score. Routing prototypes use only those selected training examples.
Measure all-head and top-16 dispatch, 20 repeated observations, scalar parity,
raw timing samples and descriptive p50/p95. Relevance coverage is scored with
heldout task labels, which are not supplied to the router. Duplicate task
replicas remain visible in both activation and task coverage counts.

Train 32 additional 32-example Heads for 200 steps through the durable queue;
persist their source-bound inputs and artifacts and verify publications after
reopening. Lease expiry fences publication, not callback CPU execution.

The cost ledger separates shared model, modality modules, private tensors,
cached features, routing, training, preserved sources and recovery. Whole-process
RSS, tensor bytes and artifact bytes have different scopes. Unmeasured Python
metadata, energy and target-hardware costs stay explicitly unmeasured. No
scientific quality gate is closed merely by a passing mechanism test.
