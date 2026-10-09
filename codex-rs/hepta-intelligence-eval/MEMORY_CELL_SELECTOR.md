# Query-conditioned evidence selector

An opt-in experiment in the existing memory-cell worker/evaluation path. It does
not replace installed serving, rewrite earlier answers, grant training rights or
certify semantic relevance. The inherited cross-encoder LoRA experiment remains
separate; this experiment freezes the ENTIRE paired encoder and native ranking
head and trains only a small residual head plus an explicit no-answer head.

## Controlled changes

| Contrast | What changes | What stays fixed |
| --- | --- | --- |
| prefix_frozen_top1 vs windows_frozen_top1 | candidate coverage | original retrieved documents, paired encoder, forced top-1 |
| windows_frozen_top1 vs windows_frozen_null | abstention decision | candidates, frozen logits, response representation |
| windows_frozen_null vs windows_trained_null | small-head parameters | byte-identical candidates and paired features, response representation |
| selection_chosen | selection-only fallback | test annotations cannot choose the model |

The small head adds a 16-unit residual to each pretrained relevance logit and an
order-invariant no-answer logit. At 384 hidden features it has 6,562 trainable
scalars. No encoder parameter updates or Transformer LoRA updates are attributed
to this experiment. Exact source strings/UTF-8 byte offsets accompany each
selected window. The response is structured evidence selection, not free-form
language generation. Replacing autoregressive greedy decoding by evidence ranking
is NOT claimed as a learning gain: only the same-window, same-response frozen/head
comparison estimates the parameter contribution. A separate generator experiment
is required before making claims about long-form answer quality.

## Bounds and byte identity

At most eight already-admitted ORIGINAL Documents, 16,384 scanned bytes in total,
4,096 per source, 384-byte windows and 192-byte stride. A query-dependent lexical
shortlist retains at most 32 windows. Full-document retrieval uses the existing
persistent FTS5/BM25+dense index, held fixed across all arms. Its 256-token dense
encoding profile is explicit and can itself miss evidence; it is not an oracle
retriever. No answer or support annotation enters window generation or encoding.
Normalized `#chunk:` documents reject rather than misrepresenting their offsets
as original source bytes. The projection hashes inspected content, not an unread
suffix. Unread character counts and scanned byte counts remain separate.

## Supervision and permissions

Only the predeclared LoCoMo training families supply source annotations. The
training cut binds permitted questions/families/roots and excluded holdout roots
before any parameter updates. Family-balanced optimization prevents replicated
questions in a large family from receiving extra family-level weight. Missing or
unresolved support is recorded as an unusable training example, NOT a no-answer
label. Explicit native unanswerability supplies no-answer supervision.

These public datasets have already been exposed during development; family cuts
do not turn them into new prospective evidence. Native document support is weak
window-level supervision and other candidates are unlabelled distractors, not
independently certified semantic negatives. `train_rows(reviewed_negatives=...)`
also accepts pre-reviewed, exact-candidate-bound categories: same person/different
time, same entity/different relation, superseded fact and nearby irrelevant text.
Tests contain explicit examples of all four. No independent semantic reviews are
manufactured for the native pilot. An owner must authenticate real admission and
review before using nonpublic training inputs.

Frozen and trained abstention offsets use the same fixed seven-point selection
search, weighted equally by source family. The candidate is chosen only with two
or more selection families, a strict mean gain and no family regression. Raw
trained results remain visible even when fallback chooses the frozen comparator.
Model artifacts contain only bounded JSON tensors/metadata, encoder identity and
ancestor training roots; no pickle or previous context. Restore validates digest,
shape, finite values, exact encoder and current permitted/withdrawn roots. The
selection receipt separately retains roots used to choose the decision policy.

## Evaluation and non-claims

The plan freezes 48 train and 16 selection LoCoMo queries; 16 held-out-family
LoCoMo plus 16 LongMemEval transfer queries are measured after training and
selection. Every one of five arms remains in the prediction census. Predictions
are written before final labels are read. Offline coverage distinguishes retrieved
source coverage, literal answer visibility in scanned bytes and candidate windows.
Literal matching and source-top1 are diagnostics, not semantic entailment.

Reports retain actual encoder tokens/time, shared feature bytes, head parameter
count/training cost, query/head timing, abstention, explicit unscored cases,
source-family intervals and all failures. Five-arm family bounds assume the
supplied family definitions; two LoCoMo test families and one LongMemEval connected
component cannot satisfy production independent-sample requirements. No
independently signed citation precision, prospective window, production acceptance
or superiority flag is issued.

Run with pinned staged inputs and a ranker downloaded at the revision/tensor pin
in `relevance_ranker.py`, then disable network during execution:

```sh
python3 -m unittest discover -s scripts/memory_cell -p 'test_selector*.py' -v
HEPTA_MEMORY_TESTED_COMMIT="$(git rev-parse HEAD)" \
  HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  python3 scripts/memory_cell/selector_development.py STAGED RANKER NEW_OUTPUT_DIR
```

The read-only `hepta-memory-selector-development.yml` validates the complete
Python regression suite and runs the exact pinned model experiment. It retains
formatting diagnostics without editing source; existing required formatting,
Architecture and blocking CI remain authoritative and unwaived.
