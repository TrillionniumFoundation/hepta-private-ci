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

The reporter computes family-paired coverage, abstention and learning contrasts.
Missing or duplicate question-arm records reject. In the abstention and learning
contrasts, changed candidate IDs, pool digests or frozen feature digests reject
instead of producing a spurious gain. Conservative confidence intervals are
reported per dataset; family independence remains a data-admission assumption.

## Bounds and byte identity

At most eight already-admitted ORIGINAL Documents, 16,384 scanned bytes in total,
4,096 per source, 384-byte windows and 192-byte stride. The remaining scan budget
is divided among remaining sources, and each source's first admissible window is
retained before a query-dependent lexical shortlist fills the 32-candidate cap.
This prevents long early documents from excluding all later source prefixes.
Full-document retrieval uses the existing persistent FTS5/BM25+dense index, held
fixed across all arms. Its 256-token dense encoding profile is explicit and can
itself miss evidence; it is not an oracle retriever.

No answer or support annotation enters window generation or encoding. Normalized
`#chunk:` documents reject rather than misrepresenting their offsets as original
source bytes. Negative offsets, detached source bytes, changed question identity
and withdrawn roots reject. The projection hashes inspected content, not an unread
suffix. Unread character counts and scanned byte counts remain separate. Paired
model inputs exceeding the 512-token bound fail rather than silently truncating
candidate evidence.

## Supervision and permissions

Only predeclared LoCoMo training families supply native source annotations. The
training cut binds permitted questions/families/roots and excluded holdout roots
before any parameter updates. Family-balanced optimization prevents replicated
questions in a large family from receiving extra family-level weight. Missing or
unresolved support is recorded as an unusable training example, NOT a no-answer
label. Explicit native unanswerability supplies no-answer supervision.

These public datasets have already been exposed during development; family cuts
do not turn them into new prospective evidence. Native document support is weak
window-level supervision and other candidates are unlabelled distractors, not
independently certified semantic negatives. `train_rows(reviewed_windows=...)`
also accepts already-admitted, exact-candidate-bound complete window labels via
`ReviewedWindows`. Its pool and admission digests must match; its positive and
negative sets must partition the entire candidate census. This path never reads
native target annotations and can distinguish windows within the same document.
Four negative categories are supported: same person/different time, same
entity/different relation, superseded fact and nearby irrelevant text. Explicit
fixtures exercise all four. No independent semantic reviews are manufactured for
the native pilot: authenticating reviewer identity and permission is the existing
owner's responsibility, not a new self-issued authority in this module.

Frozen and trained abstention offsets use the same fixed seven-point selection
search, weighted equally by source family. The candidate is chosen only with two
or more selection families, a strict mean gain and no family regression. Raw
trained results remain visible even when fallback chooses the frozen comparator.
Model artifacts contain bounded JSON tensors/metadata, encoder identity and
ancestor training roots; no pickle or previous context. Restore validates digest,
shape, finite values, exact encoder and current permitted/withdrawn roots. The
selection receipt separately retains roots used to choose the decision policy.
No-op or nonfinite training is rejected; failed training quarantines the head.

## Evaluation and non-claims

The plan freezes 48 train and 16 selection LoCoMo queries; 16 held-out-family
LoCoMo plus 16 LongMemEval transfer queries are measured after training and
selection. Every one of five arms remains in the prediction census. Predictions
are written before final labels are read. Offline coverage distinguishes retrieved
source coverage, literal answer visibility in scanned bytes and candidate windows.
Literal matching and source-top1 are diagnostics, not semantic entailment.

Reports retain actual encoder tokens/time, shared feature bytes, head parameter
count/training cost, query/head timing, abstention, explicit unscored cases,
source-family intervals and all failures. Two LoCoMo test families and one
LongMemEval connected component cannot satisfy production independent-sample
requirements. No independently signed citation precision, prospective window,
production acceptance or superiority flag is issued. Previously observed results
are not relabelled as untouched evidence after implementation refinements.

Run with pinned staged inputs and a ranker downloaded at the revision/tensor pin
in `relevance_ranker.py`, then disable network during execution:

```sh
python3 -m unittest discover -s scripts/memory_cell -p 'test_selector*.py' -v
HEPTA_MEMORY_TESTED_COMMIT="$(git rev-parse HEAD)" \
  HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  python3 scripts/memory_cell/selector_development.py STAGED RANKER NEW_OUTPUT_DIR
```

The retained `hepta-memory-selector-development.yml` is read-only. It validates
the complete Python regression suite and runs the exact pinned model experiment.
Temporary source-preparation files are removed after inspected adoption. Existing
required formatting, Architecture and blocking CI remain authoritative and unwaived.
