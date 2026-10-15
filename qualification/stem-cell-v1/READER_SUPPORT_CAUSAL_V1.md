# Reader evidence support / critical-premise counterfactual (research V1)

**Scope:** additive MultiRC Reader study built on the frozen V1 Reader and the all-native training research lineage (#2080). This is **DENY_ALL**, not model selection, deployment, original observation replacement, NDU admission, or CellSplit execution.

## Scientific motivation

The existing blinded neutral-evidence and cross-question stress tests prove that model outputs can move when input features change. They do not establish that selected evidence is independently sufficient to answer a question, that a named premise is indispensable, or that the Reader can correctly abstain. This experiment introduces strict, source-bound, externally selected character spans and a separate sealed prediction / label-opening sequence.

## Matched four-condition actual execution

For every original selected question and answer candidate, use the same frozen Reader, Encoder/tokenizer identity, source group and query. Each row receives four distinct Encoder inputs:

| Condition | Input | Legitimate claim |
| --- | --- | --- |
| no_evidence | Fixed Evidence unavailable string | No-evidence sensitivity |
| ordinary_retrieval | Entire original passage | Exact replay of the original frozen V1 prediction |
| support_candidate | Two to eight verbatim original source spans, in source order | Candidate support only, NOT independently certified sufficient |
| premise_removed | Same selected spans, excluding the designated critical span | Prediction movement only; the original human binary label is NOT valid ground truth |

All four inputs execute real PyTorch Encoder and frozen Reader forwards. The question embedding is executed once per original task. Separate wall-time counters include each condition, but are not authenticated end-to-end p99, GPU, energy or full model lifecycle cost.

Span annotations are supplied *before* test labels are opened. No code automatically uses the answer label to discover supporting spans. Missing external annotations block the actual pretrained experiment.

## External annotation file contract

Use schema hepta.reader.external-source-spans.v1 with top-level fields: schema, panel_id, original_observation_id, labels_exposed=false, support_independently_verified=false, rows, annotation_id. Annotation_id is the SHA-256 canonical JSON digest of the object without annotation_id.

Each row contains precisely task_id, source_group, support_spans, critical_span_index. Spans are nonoverlapping [start,end] Python character offsets into the original unmodified passage. The complete original task inventory from at least two source groups must appear in original order. No label, rewritten supporting passage or authority claim may enter this input.

The trained frozen ModernBERT Reader and original panel identity are verified through existing V1 check_seal, load_conditioned_bank, safetensors and safe_encoder owners. Any mismatched source/weight or original-logit replay refuses execution.

## Three sealed steps against existing original V1 artifact paths

~~~sh
python qualification/stem-cell-v1/reader_support_native_adapter.py prepare \
  --blind-eval-bundle /approved/multirc-material/blind-eval-bundle.json \
  --run-dir /approved/multirc-run --expected-v1-seal-id "$V1_SEAL_ID" \
  --external-spans /approved/sealed-external-spans.json --output /approved/support-plan

python qualification/stem-cell-v1/reader_support_native_adapter.py run \
  --plan /approved/support-plan/plan.json --run-dir /approved/multirc-run \
  --expected-v1-seal-id "$V1_SEAL_ID" \
  --snapshot /approved/public-encoder/snapshot --output /approved/support-observations

python qualification/stem-cell-v1/reader_support_native_adapter.py score \
  --plan /approved/support-plan/plan.json \
  --observations-dir /approved/support-observations \
  --expected-observation-id "$SUPPORT_OBSERVATION_ID" \
  --owner-labels /approved/multirc-material/owner-only-eval-labels.json \
  --expected-owner-label-file-sha256 "$OWNER_LABEL_FILE_SHA256" \
  --output /approved/support-scores
~~~

The exact label file name comes from the *original* material-owner run. Every stage writes into a new output directory and emits COMMITTED.json or FAILED.json. Score opens labels only after the prediction seal exists and verifies the supplied original owner label SHA256.

## Honest interpretation and blockers

The score reports original-label accuracy/Brier for no_evidence, ordinary_retrieval and support_candidate, and descriptive probability movement for premise_removed. It does **not** score premise_removed against the original human binary answer; the removed condition may be underdetermined. All source and model digests are local identity checks, not independent issuer signatures. Supposed semantic sufficiency is never marked certified, even if the numbers look ideal.

The completed fixture exercises two toy groups and four real CPU tensor forwards per row. It is not true pretrained effectiveness. The next real scientific gate is independent source-family/time-disjoint annotation, an external semantic sufficiency reviewer, an explicitly valid unknown/abstain answer for removed evidence, Reader/RAG matched controls and full physical cost. Do not fabricate this reviewer, its human annotations, a model winner, 4,096 production Cells, or a general FBSDE gain from this source-only CI.

## Reproduce the isolated numerical and tamper tests

~~~sh
python -m unittest discover -s qualification/stem-cell-v1 -p 'test_reader_support_*.py' -v
python -O -m unittest discover -s qualification/stem-cell-v1 -p 'test_reader_support_*.py' -v
python -m compileall -q qualification/stem-cell-v1/reader_support_causal.py qualification/stem-cell-v1/reader_support_native_adapter.py
~~~

**22 offline numerical and adversarial methods** were executed locally on this exact code. The corresponding source-only GitHub Actions workflow replays them at its own source SHA. Main, CURRENT, selected Stem, original inference Worker, NDU, signed FinalUse, CNS and production learning owners are untouched; no regular blocking-ci check is waived.
