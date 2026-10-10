# External span supervision and the same-generator experiment

This opt-in continuation consumes independent **dataset authors' answer-span and
unanswerability annotations**, then evaluates new free-text answers. It does not
claim an independently signed semantic review, training permission for private
sources, a production rollout, or a prospective performance measurement.

## External supervision

Source: Stanford SQuAD 2.0, https://rajpurkar.github.io/SQuAD-explorer/ . The authors
released crowdworker questions, exact answer spans and adversarial unanswerable
questions (Rajpurkar, Jia and Liang, 2018). The upstream dataset card attributes
CC-BY-SA-4.0; preserve its attribution and license when redistributing examples.
The dataset is pinned to SQuAD-explorer commit
`eee5fdbf62f8613a7812b03419e6b29617b74fd1` and the two exact Git blob identities in
`span_supervision.py`. A SHA-256 is recorded before training. No labels are written
by this model and no LoCoMo/LongMemEval target trains this head.

Character offsets are checked against original text and converted to UTF-8 byte
positions. A positive window must contain a complete annotated answer span, not
merely belong to its document. Missing/truncated positive spans cause an explicit
unusable-training record, never invented no-answer supervision. Explicit human
unanswerability supplies null labels. Other windows are outside-annotated-span
contrast candidates: this is **not** proof that each was independently reviewed
as a semantically false answer. Plausible answers on impossible questions are not
used as positive labels. The already-admitted `ReviewedWindows` path remains
available for actual per-window semantic reviews; no such reviewer is fabricated.

128 questions from 16 training articles and 32 from eight separate training-file
articles are fixed by ID before features/optimization. 16 official dev questions
and eight questions from each previously exposed native memory benchmark are
then evaluated. Article and exact-context overlap checks precede all updates.
The public data may occur in model pretraining; this is unknown, and these are not
new prospective or private-source observations. Data authenticity pins and an
experiment training cut are not a replacement for production authority.

## Controlled end-to-end intervention

All six arms use exactly one original candidate pool and frozen paired features.
Only a 6,562-parameter evidence/null head is updated for 192 steps. The shared
paired encoder and autoregressive answer generator are frozen and hash-checked.
The trained head is serialized/reloaded before answering.

- Frozen vs trained forced top-1 isolates ranking without null decisions.
- Frozen vs trained null choice uses the same zero threshold offset.
- Frozen vs trained calibrated choice uses the same seven-point selection-only
  search over external span labels. This is a decision-policy contrast, not a
  pure ranking estimate; raw top-1 changes are reported separately.

Every selection feeds the **same** frozen SmolLM2-135M-Instruct generator, same
system prompt, 1,024 input-token cap, 96 generated-token cap, greedy decoding and
source-label convention. Only the selected source window changes. Arm names,
gold answers and annotation metadata are not prompt inputs. Even an empty-evidence
selection calls the generator: its actual answer is retained, not replaced by a
hard-coded refusal. SQuAD supplies its paragraph as context (not a retrieval
achievement); native transfer uses the previous frozen FTS5/dense retriever.

Original source offsets accompany the delivered window. The model generates new
free-text answers and any citations; no post-hoc citation attachment or rewrite
is performed. Raw answers are synced to a create-only file before evaluation.
Truncation/empty-output failures are recorded; the failed trial remains failed.

## Interpretation

Multi-reference normalized exact match and token F1 are **diagnostics**, not an
official model judge or a >=99% semantic citation certificate. The scorer removes
protocol labels only in its scoring view, never in raw generation. Answerable and
unanswerable strata, selector/model abstentions, source-span visibility, changed
non-null ranking and raw response changes remain distinct. All planned arm/case
pairs must exist. Mismatched generator/profile/pool/features reject. Missing or
failed pairs widen the family-paired identification interval rather than being
counted as successful zero-cost observations. Article grouping is a dependence
assumption, not a certified effective independent sample count.

No previous full benchmark result is relabelled. A positive result here alone
cannot qualify production. Authentic deployment, independent semantic review,
old-task retention and actual future windows remain separate obligations.

## Execute

Use the pinned worker dependencies and upstream inputs. Then run offline:

```sh
python3 -m unittest discover -s scripts/memory_cell -p 'test_*.py' -v
HEPTA_MEMORY_TESTED_COMMIT="$(git rev-parse HEAD)" \
  HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  python3 scripts/memory_cell/selector_end_to_end.py STAGED RANKER SQUAD NEW_OUTPUT
```

`hepta-memory-span-e2e.yml` is read-only, checks repository formatting, runs the
entire Python suite and retains source, pins, training labels, head, selected
windows, raw answers, scores and errors. It neither signs nor deploys candidates.
