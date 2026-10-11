# Token-position ranking and task-answer learning

Opt-in development in the existing memory worker/evaluation path. No default
serving, authorization, historical result or production acceptance changes.

## Two independently controlled interventions

The token head learns start/end positions from the original external SQuAD
TRAIN answer offsets. The paired encoder is frozen; all candidates share its
native relevance score and token representations. The head has 770 scalars for
the 384-dimensional model. Only source tokens and CLS can receive probability.
Unknown/out-of-window answers receive no loss and never become null labels.
Source token targets are extraction annotations, not certified non-entailment
labels for every other possible window. Within-source answer positions, rather
than global document scores, now receive learning pressure.

At inference the maximum bounded (32-token) start/end margin over CLS is added
with fixed coefficient 1 to the native relevance logit. This changes only ranking;
primary arms are forced choice. The extraction is never used as an answer or
attached to a generated answer. Frozen-native vs token-enhanced comparisons use
byte-identical pools and encoder inputs. Calibration and coverage do not change.

Separately, rank-4 query/value LoRA on the existing reader is supervised on
external TRAIN answers plus their actual source label. Prompt labels are masked;
explicit unanswerability and empty-context examples teach the response protocol.
No benchmark test labels enter either optimizer. The trained adapter is saved,
reset and validated through the existing immutable candidate consumer before use.

A 2x2 factorial compares native/token selection with disabled/enabled answer LoRA.
Two additional empty-context arms measure actual model abstention. All six arms
use the same base, tokenizer, prompt and 96-token deterministic decoder. Models
produce every raw answer; no rule inserts citations, repairs output or replaces
an empty-context response. Ranking improvements, reader improvements and their
interaction must be reported separately. Literal citation syntax is not entailment.

## Registered scope and reproducibility

The run reuses the prior 128 train, 32 reserved selection, 16 external test and
8+8 native transfer questions. Previously exposed public datasets remain
DEVELOPMENT data, not prospective independent observations. Source views and
candidate pools are reconstructed from original pinned documents and compared
with the previous complete run. Cached retrieval is a fixed experimental input,
not a claim of newly observed live memory. All model/package inventories are
checked against the locked reference; both actual inference and training are
offline after staging.

Token training: 512 family/query-balanced steps, learning rate 0.002. Reader:
192 steps at most, learning rate 0.0002, 65,536 input training tokens at most.
The selection set is reserved and not used to tune this run. Hyperparameters
and coefficient 1 are fixed before test generation, not selected from new scores.

The workflow executes the complete Python regressions in one process and actual
pretrained models in a distinct process. Raw answer journals are synced before
score annotation access. Missing/failed attempts stay in the census and make the
run fail; sparse families widen reported uncertainty. No >=99% semantic precision,
independent signature, superiority or production rollout is issued by this lab.

```sh
HEPTA_MEMORY_TESTED_COMMIT="$(git rev-parse HEAD)" \
  HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  python3 scripts/memory_cell/token_task_trial.py \
  STAGED RANKER EXTERNAL LOCKED_REFERENCE_EXPERIMENT NEW_OUTPUT
```
