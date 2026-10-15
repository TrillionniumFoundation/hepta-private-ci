# Hepta Reader P0 — physically replayed source-premise intervention (V2 scoring)

**2026-10-15 · research-only / DENY_ALL · stacked on PR #2108.** This increment does not select a Stem, amend the original V1 ModernBERT Reader, train an Encoder, mutate production Cell state, authorize a source, issue FinalUse, promote a model, or merge into `main`. Keep the source-owner and independent-evaluator boundaries intact.

## Scientific problem and why V1 alone was insufficient

The first support-premise experiment executes four evidence variants on the *same task* and isolates human labels until scoring. However the V1 scoring entrypoint could consume a self-hashed observation without **reopening the independently sealed original V1 predictions** or verifying all reported real tensor forwards. A SHA alone can be rehashed by the producer and does not certify numerical work, model origin or semantic adequacy.

This child adds **two separate readbacks** without changing the original task roster, source selection or frozen trained weights:

1. **Scoring-time original V1 rebind.** The scorer must separately reload the original `hepta.multirc.unscored-model-seal.v1` and verify every original candidate task, source group, Head weights digest and numeric original-evidence logits. The prior `original_prediction_replay_verified` field must be true but **is not** accepted as sufficient proof.
2. **Second physical forward pass.** After the original four-condition run and **before opening withheld human labels**, a dedicated `replay` stage reloads the same pinned original full Encoder and frozen Reader, reencodes *every* condition and reexecutes *every* Reader. The complete computed logits must match the first sealed observations to within a fixed `1e-5` absolute float tolerance. Both physical passes and the second-pass file identity are recorded independently. This second pass is not an independent neural architecture, vendor signer or external observer.

The original four evidence conditions remain:

| Condition | Actual feature input | Label/claim boundary |
| --- | --- | --- |
| `no_evidence` | Fixed neutral string | Original-answer descriptive baseline only |
| `ordinary_retrieval` | Original unchanged passage | Must exactly replay pinned original V1 Reader |
| `support_candidate` | Original passage verbatim slices from external prelabel span plan | **Candidate** support only; NOT independently adjudicated sufficient |
| `premise_removed` | Candidate slices with declared critical span omitted | Report probability movement only; the original answer label is not valid ground truth |

The external annotated plan is `hepta.reader.external-source-spans.v1` with exact original V1 task/panel/source identities, at least two nonoverlapping source-text spans, critical index, `labels_exposed=false` and `support_independently_verified=false`. Spans are Unicode codepoint offsets into the **exact original passage**, ordered with no overlap. The evaluator must never choose support spans from model or heldout answer labels. Without an independently authored plan, the real-pretrained science case remains **BLOCKED**, not simulated with made-up evidence.

## Version and exact contracts

- Retain existing `hepta.reader.support-causal-plan.v1` plan schema, since its meaning and fields are unchanged.
- **Break the old research observation and score schema**: `hepta.reader.support-causal-observation.v2` and `hepta.reader.support-causal-score.v2` cannot silently accept V1 receipts. Add the new `hepta.reader.support-causal-replay.v1` second-pass record.
- Score requires both the original V1 owner seal and the second-pass seal. It verifies their linked observation ID and original V1 seal, immutable file SHA, every task/prediction/feature digest, counted full Encoder/Reader/query forwards and conditional elapsed-time components.
- A rehashed but altered logit, incorrect model or Reader digest, forged number/type of tensor calls, changed source/order, missing condition, nonfinite probability, undercounted cumulative wall time, fake `production_authorized`, fake `independent_*` success or stale v1 observation fails closed.
- A positive structural replay says only that a second computation was run with the source submitted to it. **Neither content-addressing, tests nor same-code repeated inference establishes original model signing or trusted human sufficiency.** In particular the `physically_*` counters are structurally verified receipts from the research processes, not independently metered hardware attestation or GPU/latency/energy data.

## Reproduction with ORIGINAL V1 materials (not the new all-native Head weights)

First create a label-free human/span annotation at `/approved/external-source-spans.json`. The original V1 study produces `blind-eval-bundle.json`, `owner-only-labels.json`, and the complete original `conditioned.safetensors` + `COMMITTED.json`. Keep them at the original material/run paths; do not overwrite either study's artifacts. Source-only tests use a stub owner and synthetic 4D Torch features, not real pretrained ModernBERT efficacy.

```bash
python qualification/stem-cell-v1/reader_support_native_adapter.py prepare \
  --blind-eval-bundle /approved/material/blind-eval-bundle.json \
  --run-dir /approved/v1-run --expected-v1-seal-id "$V1_SEAL" \
  --external-spans /approved/external-source-spans.json --output /approved/support-plan

python qualification/stem-cell-v1/reader_support_native_adapter.py run \
  --plan /approved/support-plan/plan.json \
  --run-dir /approved/v1-run --expected-v1-seal-id "$V1_SEAL" \
  --snapshot /approved/modernbert-snapshot --output /approved/support-run

python qualification/stem-cell-v1/reader_support_native_adapter.py replay \
  --plan /approved/support-plan/plan.json \
  --observations-dir /approved/support-run \
  --expected-observation-id "$OBSERVATION_ID" \
  --run-dir /approved/v1-run --expected-v1-seal-id "$V1_SEAL" \
  --snapshot /approved/modernbert-snapshot --output /approved/support-replay

python qualification/stem-cell-v1/reader_support_native_adapter.py score \
  --plan /approved/support-plan/plan.json \
  --observations-dir /approved/support-run \
  --expected-observation-id "$OBSERVATION_ID" \
  --run-dir /approved/v1-run --expected-v1-seal-id "$V1_SEAL" \
  --replay-dir /approved/support-replay --expected-replay-id "$REPLAY_ID" \
  --owner-labels /approved/material/owner-only-labels.json \
  --expected-owner-label-file-sha256 "$OWNER_LABEL_SHA256" \
  --output /approved/support-score
```

No pre-labeled run or generated proof of semantic sufficiency is supplied. An original unchanged passage can have other valid evidence spans; observed movement under one removed candidate span **does not show** causally necessary evidence without external review. A properly evaluated abstention requires an additional, explicitly labeled "unknown" arm; it is not inferred from binary MultiRC labels.

## Actually executed local regression scope

```bash
python -m unittest discover -s qualification/stem-cell-v1 -p 'test_reader_support_*.py' -q
python -O -m unittest discover -s qualification/stem-cell-v1 -p 'test_reader_support_*.py' -q
python -m compileall -q qualification/stem-cell-v1/reader_support_causal.py \
  qualification/stem-cell-v1/reader_support_native_adapter.py
```

**40 distinct tests passed in both runs** on actual local PyTorch CPU. These tests deliberately use tiny **synthetic features** and **stub V1 model/signer** interfaces, while executing two actual sets of Torch Encoder/Reader tensor computations. The file-level test performs the complete prepare → run → replay → score flow with label input held back until the last stage, and asserts failure-only artifact creation if a stale replay seal is presented. This is new mechanism evidence, NOT human-annotated MultiRC/real-pretrained task efficacy.

## Missing independent acceptance evidence

Physical load of the original public pinned ModernBERT (not supplied by this child), independently precommitted actual support spans, a human judgment about sufficiency and criticality, cross-source prospective task outcomes, adequate NDU and cheap Critic controls, full lifecycle p95/p99 and hardware energy, source-owner signatures, production Worker final-use, all source-head and synthetic-merge blocking CI, production selection/rollback and 4,096 real Cell trials **remain explicitly unresolved**. All reported `production_authorized` fields remain false; security and evaluator authority are not modified. Keep this PR Draft, unmerged, DENY_ALL until separate full qualification.

## V3 prospective material identity and sparse shared-feature follow-through

**2026-10-15 · still research-only / DENY_ALL.** This additive child fixes a
reproduced source-identity flaw in the V2 `prepare` path: V2 would accept an
altered original passage under an unchanged, caller-supplied `panel_id` so long
as the associated source-group identifiers and task IDs were unchanged. A
rehashed annotation SHA is not proof of the original dataset source content.

The `prepare` stage now **requires both** the original sealed `train-bundle.json`
and `blind-eval-bundle.json`. It reconstructs the **actual V1** panel SHA from
`{header, train_rows, evaluation_rows}` with the original JSON canonicalization
(`sort_keys`, compact separators, Python default ASCII escaping). The rebuilt
SHA must match both original bundles and the frozen V1 Reader's `panel_id`.
Training-only labels remain in the train bundle; the validation bundle may not
contain validation labels or unexpected question fields. Changes to original
passages, selected question/answer text or IDs, train data/labels, source
metadata or unicode JSON byte encoding must never silently match the frozen
Reader. Additional standalone negative tests exercise each case.

The `prepare` invocation above is superseded by:

```bash
python qualification/stem-cell-v1/reader_support_native_adapter.py prepare \
  --train-bundle /approved/material/train-bundle.json \
  --blind-eval-bundle /approved/material/blind-eval-bundle.json \
  --run-dir /approved/v1-run --expected-v1-seal-id "$V1_SEAL" \
  --external-spans /approved/external-source-spans.json \
  --output /approved/support-plan
```

This binds *the exact original research material* to the already-frozen V1
prediction roster. It is still not a publisher-attested data-origin signature
or proof that the pretraining distribution excludes the test passages. No
fabricated external evidence annotations are included.

### Physical shared Encoder feature fan-out (additional cost-only control)

`reader_support_fanout.py` is a separate physically executed CPU Torch
**non-serving** baseline. Given the same sealed plan, original V2 observation,
frozen Reader, model, tokenizer identity and explicit caller-provided per-use
access hook, it shares the *same actual feature tensor* across multiple logical
Reader questions only when all of these agree:

- Principal, scope, generation, authority epoch, Stem SHA, tokenizer SHA and
  source-use revision;
- exact original source group and condition;
- exact condition input bytes (SHA256).

Its access callback executes **for every logical Cell borrow**, including cache
hits; an unauthenticated callback remains just a caller assertion and may not
be treated as signed `FinalUse`. It checks feature tensor bytes after each
Reader invocation so an in-place Reader mutation cannot poison other Cells.
LRU eviction is capacity-bounded; the zero-cache counterfactual must replay
identical outputs and correctly show zero saved physical Encoder forwards.

Actual local **toy** four-task, two-source-group Torch computation:

| Cache cap | Logical feature uses | Physical Encoder calls | Actual Reader calls | Cache hits | Peak feature bytes | Logit max error |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 B | 16 | 16 | 16 | 0 | 0 | 0 |
| 40 B | 16 | 16 | 16 | 0 | 32 | 0 |
| 32 MiB | 16 | 8 | 16 | 8 | 256 | 0 |

The 50% reduction in **Encoder-call count** on the carefully chosen repeated
**synthetic** source is real under this tiny executed CPU fixture, but it is
neither a guaranteed wall-time speedup nor a 4,096-Cell deployment result.
The 40 B case actually incurs eviction overhead and no compute savings;
negative/zero improvements must be retained. Actual all-in process memory,
cache-hit authorization cost, GPU, p99, energy, optimizer and genuine public
pretrained features are not qualified. The newly added tests reject cross-
source neutral-evidence reuse, stale authority epochs, changed model/tokenizer,
wrong source/task roster, mutated Reader buffers, denied feature borrow and
false resource or model-superiority claims.

The fully source-locked four-stage Reader experiment remains P0 Reader
sufficiency *diagnostics*. The sparse cached fan-out is a paired P1 *mechanism*
control, not new evidence of learning, reasoning or NDU superiority. Next real
qualification must execute pinned pretrained weights on source-disjoint
natural tasks, with independent external span judgments, verified Worker
access/FinalUse, full model lifecycle costs and strong Reader baselines.
