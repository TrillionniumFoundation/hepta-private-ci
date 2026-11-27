# Procedural replay with a real frozen Encoder and a trained task Head

The complete replay → real Encoder → SGD → saved artifact → reload → observed
file-output evaluation ran successfully. **The trained Head did not outperform
the strongest frozen-feature baselines.** All three Head seeds, nearest neighbor,
and nearest centroid completed 64/64 heldout tasks under forced selection. BM25
completed 40/64. At the predeclared confidence threshold of 0.7, the Head completed
only 21/64, 20/64, and 21/64 tasks; nearest neighbor completed 57/64 and centroid
59/64. This negative coverage result is part of the outcome.

This is a controlled artificial procedure-selection experiment. It trains a
post-Encoder **task Head** to select one of four existing programs, then measures
actual output-file correctness. It does not learn new program implementations,
grant execution rights, activate a MemoryCell, or demonstrate a general memory
system. The separate `action_head`, value and uncertainty heads remain untrained;
local state remains zero. All artifacts are `DENY_ALL` and `SHADOW_ONLY`.

## Frozen design and observed labels

[plan.json](plan.json) was written and its SHA-256 retained before the first
quality run:

`7c4fc2bb251d1c6f897e336dcc82adad3780511b6f353e7b672dc9fca8f471bf`

The plan binds all 20 local source-closure members, all task specifications,
partitions, fixed budgets, calibration policy and comparison rule. Their exact
UTF-8 sources are retained in [source_snapshot.jsonl.gz](source_snapshot.jsonl.gz).
No experiment source, task, hyperparameter or seed was changed after freezing.
[result.json](result.json) is the final result; [observe_report.json](observe_report.json)
preserves the earlier phase's `awaiting_pinned_encoder` status. The later real
Encoder and SGD completion is recorded in [validation_manifest.json](validation_manifest.json).

Every input is bounded JSON containing records with `id`, `group`, `score`, and
`note`, plus a threshold. All four procedures consume exactly this format and
write a fresh `output.json` in the same private temporary directory:

| Class | Fixed procedure | Required output |
| --- | --- | --- |
| 0 | `latest_by_id` | Last input occurrence for each id, ordered by id |
| 1 | `group_totals` | Sum all scores by group, ordered by group |
| 2 | `threshold_filter` | All records with score at least the threshold, preserving input order and duplicates |
| 3 | `stable_score_sort` | Every record in ascending score order, preserving input order on ties |

The executor actually reads each input, performs the selected transformation and
writes the result. A separate observer module reopens input and output files,
checks the unchanged input hash, and recomputes the expected result using its own
algorithms. It ignores executor success claims. The observer is separate code,
not a separate security principal, independent organization or production signer.

The replay phase executed all four candidates for each of the 192 queries:
**768 attempts, 192 observed successes, 576 wrong results, zero execution errors,
and no ambiguous or unsolved query.** The unique successful candidate supplies
the training label. All wrong-program outputs are retained in
[replay_attempts.jsonl.gz](replay_attempts.jsonl.gz); they were not removed to make
the corpus appear successful.

All split labels are generated before training and are available to the scoring
harness. **This is not a blind test.** Heldout labels, gold goals and output bytes
are excluded from selectors, SGD, temperature fitting and seed selection. The
public query carries instruction text and input metadata; selectors use only the
text. Each input-file family is crossed with all four goals, so file structure,
family identity or the number of records cannot determine the selected procedure.

| Partition | Queries | Template families | Input-file families |
| --- | ---: | ---: | ---: |
| Training | 64 | 4 | 16 |
| Calibration | 32 | 2 | 8 |
| Development | 32 | 2 | 8 |
| Heldout | 64 | 4 | 16 |

Template families, input families, exact query texts and input-file byte hashes
are disjoint across partitions. There are 48 distinct input files in total. The
four heldout template families are manually written paraphrase groups, each
containing all four procedure meanings. **Three seeds reuse the same 64 heldout
queries; they are not 192 independent tests.** This artificial distribution and
the small number of template groups limit statistical generalization.

## Real Encoder, local training and baselines

The original fixed checkpoint is
[`ibm-granite/granite-embedding-97m-multilingual-r2`](https://huggingface.co/ibm-granite/granite-embedding-97m-multilingual-r2/tree/835ad14087e140460703cf0fae09f97d469d65c2),
revision `835ad14087e140460703cf0fae09f97d469d65c2`. The six-file acquisition totals
220,226,871 bytes; its inventory SHA-256 is
`08bdb7bb7eefb051ac74924787354a3638ba8a0e6fe6ffdd96ae57d6f1402db3`.
[checkpoint_acquisition.json](checkpoint_acquisition.json) records exact files,
upstream metadata and hashes. Model files remain outside Git. The model card and
its license at that pinned revision govern reuse; no new external dependency was
installed for this experiment.

`FrozenRealEncoder` loaded those exact local files and ran 24 physical batches of
8 queries, producing 192×384 actual float32 pooled features. Maximum text length
was 128 tokens; CPU thread limits were 2. Encoder parameters were frozen, with
zero Encoder training steps. [encoder_manifest.json](encoder_manifest.json)
records the actual per-batch receipts, feature identity and counters.
[pooled_features.npz](pooled_features.npz) retains actual pooled outputs; token
states are not retained or fabricated. No historical news features were reused.

Each seed (7, 17 and 29) ran exactly 200 full-batch SGD steps at learning rate 0.2
on the 64 training examples. Only `task_head.weight` and `task_head.bias` changed:
1,540 trained parameters. Temperature was selected from the existing fixed grid
on the 32 calibration examples only; every Head selected 0.25. Development was
reported but did not select a configuration or seed. Heldout was absent from the
trainer call. Training cross-entropy decreased from 1.39160/1.39011/1.39073 to
0.99725/0.99494/0.99630 after the final step.

Three predeclared baselines use the same successful training replay labels:

- SQLite FTS5 BM25 with Porter tokenization; maximum matching document score per procedure.
- Nearest training example by cosine similarity on the real frozen features.
- Normalized mean training feature for each procedure, scored by cosine similarity.

Cosine logits use the fixed multiplier 20. Every baseline uses the same
temperature grid and calibration partition; no test-driven threshold was chosen.
The primary comparison forces exactly one choice. The secondary policy uses
confidence ≥0.7 and can abstain. **The bound is one execution per query, arm and
policy.** Forced and selective policies are separate real execution sets, so both
together can execute twice for a query/arm. There is no equal-compute claim.

## Results and retained failures

The primary metric is independently observed file-output success. Abstentions
count as zero successful tasks in the secondary metric.

| Arm | Forced development success /32 | Forced heldout success /64 | Threshold 0.7 heldout executions /64 | Threshold 0.7 heldout successes /64 |
| --- | ---: | ---: | ---: | ---: |
| BM25 replay | 24 | 40 | 56 | 40 |
| Frozen nearest neighbor | 32 | 64 | 57 | 57 |
| Frozen nearest centroid | 32 | 64 | 59 | 59 |
| Head seed 7 | 32 | 64 | 21 | 21 |
| Head seed 17 | 32 | 64 | 20 | 20 |
| Head seed 29 | 32 | 64 | 21 | 21 |

The predeclared improvement rule required all three Head seeds to exceed both
feature baselines and BM25. It was **not met**. Against either feature baseline,
every forced-success paired difference is zero. The bootstrap interval `[0,0]`
reflects identical observed outcomes, not proof of population equivalence. Against
BM25 the observed difference is +0.375; exploratory grouped bootstrap intervals
are [0.3125,0.4375] across 16 input families and [0.25,0.5] across just four template
families. These groups are small, manually authored and dependent in meaning.

Coverage at 0.7 is a substantive failure: the Head completes only 32.8125%,
31.25% and 32.8125% of heldout tasks, versus 89.0625% for nearest neighbor and
92.1875% for centroid. All three Heads abstain on **all 16 stable-sort tasks and
all 16 threshold-filter tasks**. Seeds 7/29 execute 12/16 last-by-id and 9/16
group-total tasks; seed 17 executes 11/16 and 9/16. Successful accepted cases do
not erase these 43/44/43 abstentions. The frozen calibration grid and threshold
were left unchanged after seeing this result.

BM25's forced heldout failures are 4/16 last-by-id, 0/16 group-total, 8/16
threshold-filter and 12/16 stable-sort cases. Its 0.7 policy still executes 16
wrong heldout programs and abstains on eight tasks. Full outputs, wrong choices
and abstentions are retained in the per-arm `.jsonl.gz` files. There were no
execution exceptions in this valid-input quality corpus; the separate mechanism
test uses an actual invalid input to verify that execution failures are charged.

## Actual work, artifact costs and source withdrawal

| Phase | Actual file executions |
| --- | ---: |
| Four-candidate replay across all partitions | 768 |
| Observe-phase BM25 forced evaluation | 96 |
| Main forced evaluation, six arms ×96 dev/heldout queries | 576 |
| Main selective evaluation, six arms with abstention | 363 |
| Total | **1,803** |

Across these deliberately repeated evaluation passes there are 1,139 successful
executions and **664 wrong-output executions**, plus 213 abstention records.
These are execution accounting totals, not counts of independent test examples.
The archive audit reopens retained output bytes and recomputes every observer
result without rerunning an Encoder, selector or program. It verifies all 80
original evidence files and 20 frozen source members; see
[archive_audit.json](archive_audit.json). This is an archive consistency check,
not an independent execution provenance signature.

Actual Head hooks recorded 206 module calls and 13,056 example calls per seed
during training/calibration/development reporting. Each seed adds one 192-row
loaded-artifact call, one separate 192-row parity call, and one 192-row call whose
output is rejected by a mid-forward source withdrawal. Total recorded Head work
is 627 module calls and 40,896 example calls. Only 600 calls are optimizer steps.
Rejected pre-forward withdrawal scenarios perform zero Head calls.

The saved ABI retains 7,315 parameters (29,260 float32 bytes), of which the trained
task tensors occupy 6,160 bytes. Each NPZ is 32,426 bytes, plus its training
manifest and 35,845-byte research source-owner manifest. This must not be described
as a 6 KB complete memory system. The nearest-centroid baseline retains only
6,144 feature-tensor bytes; nearest neighbor retains 98,304; BM25's serialized
index is 49,152 bytes. These exclude shared Encoder storage, runtime overhead and
provenance metadata, and are not equal-cost full-system measurements.

The real Encoder has 97,441,152 loaded parameters and 389,764,864 bytes of resident
tensor storage. Its recorded load-plus-encode wall time was 7.402 seconds; the
three recorded training phases totalled 0.833 seconds. Driver peak Linux RSS was
1,220,596 KiB (about 1.16 GiB). Timings are local observations, not a controlled
hardware performance comparison. Archived evidence is about 1.2 MB, separate
from the 220 MB checkpoint on disk.

Each artifact reload reproduced the trained probabilities bit for bit. In
independent scenarios, withdrawing a training or calibration source blocks loading
and use; withdrawing a current heldout feature source blocks use before the Head.
A real forward hook changes the view during computation and its output is rejected.
The affected owner instance remains invalid even if its provider rolls back.
These probes do not roll back the clean evaluation owner. New owner instances
still trust the experiment's host view; this is not durable authenticated
antirollback, parameter unlearning, or a runtime Procedure admission capability.

## Reproduction

Run from the research repository root with the recorded Python environment
(Python 3.12.14, PyTorch 2.10.0+cpu, NumPy 2.2.6). All experiment outputs are created
exclusively; use a new output directory to avoid overwriting this evidence.

```bash
PROCEDURE_PY=/workspace/scratch/19dd72e63851/stem-venv/bin/python
PROCEDURE_MODEL=/tmp/hepta-procedure-model/granite97m
PROCEDURE_OUTPUT=/tmp/hepta-procedure-replay-reproduction
PROCEDURE_PLAN=7c4fc2bb251d1c6f897e336dcc82adad3780511b6f353e7b672dc9fca8f471bf
export OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2
export TOKENIZERS_PARALLELISM=false

# Only if the exact existing snapshot is missing; the downloader verifies pins.
"$PROCEDURE_PY" qa/stem-bakeoff/fetch_real_checkpoint.py \
  --candidate granite97m --destination "$PROCEDURE_MODEL"

"$PROCEDURE_PY" qa/stem-bakeoff/procedure_replay_probe.py freeze \
  --output "$PROCEDURE_OUTPUT"

# Check the printed plan digest against the retained pin before proceeding.
"$PROCEDURE_PY" qa/stem-bakeoff/procedure_replay_probe.py observe \
  --output "$PROCEDURE_OUTPUT" --expected-plan-sha256 "$PROCEDURE_PLAN"

env HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 "$PROCEDURE_PY" \
  qa/stem-bakeoff/procedure_replay_probe.py learn \
  --output "$PROCEDURE_OUTPUT" --expected-plan-sha256 "$PROCEDURE_PLAN" \
  --snapshot "$PROCEDURE_MODEL" --operator-accepted-terms

"$PROCEDURE_PY" qa/stem-bakeoff/procedure_replay_verify.py \
  --evidence "$PROCEDURE_OUTPUT" --expected-plan-sha256 "$PROCEDURE_PLAN" \
  --output "$PROCEDURE_OUTPUT/archive_audit.json"

"$PROCEDURE_PY" -m unittest discover -s qa/stem-bakeoff \
  -p test_procedure_replay.py -v
```

The exact model version and code closure are required; a different Python
version also changes the frozen plan's environment field. Runtime timings and
temporary execution traces can change between runs. The nine mechanism tests
use small fixture features only where necessary; their success is separate from
the archived real Granite experiment. Their original log is retained in
[logs/unit_tests.log.gz](logs/unit_tests.log.gz); actual freeze/observe/learn/acquisition
logs are retained alongside it as deterministic gzip files. Their original byte
hashes and lengths are recorded in [log_inventory.json](log_inventory.json). The post-run auditor was added after the plan
freeze and has its own source hash in its audit output.

## Native Head handoff boundary

The new artifacts use the existing linear 12-tensor NPZ profile: width 384,
rank 4, state width 8, four task classes, zero `up.weight`, zero-state task-only
inference, and unchanged DENY_ALL/SHADOW_ONLY posture. This matches the supported
structural profile of the existing native P37 Head decoder. **This new artifact
has not been executed by the native runtime in this experiment.** Native batches
are limited to 128 rows; the 192-row research bundle needs bounded sub-batches.
The existing `hepta-learning-artifacts/tools/export_cell_head_bundle.py` is tied
to the P37 input paths and `head_artifacts` report shape. A separate adapter must
validate this experiment's plan/result and source closure before packaging the
original manifest/NPZ; the existing exporter cannot be assumed to accept it.

A host would need a new independently pinned bundle and artifact-owner admission,
the exact current feature identity from `encoder_manifest.json`, and an explicit
ordered class contract `[latest_by_id, group_totals, threshold_filter,
stable_score_sort]` bound to this plan and task objective. The news Head's class
interpretation and source pins cannot be reused. For new queries the real trusted
feature producer must run this exact checkpoint/preprocessor and retain ordered
feature-byte and source-record pins; an ABI-compatible tensor alone does not
prove Encoder execution or source authority.

There is currently no live Agentd cue-to-this-Granite-profile producer. The native
bundle binds training/calibration dataset digests but does not itself expand and
revalidate this experiment's 526 learning-source digests or each current query
source. Those require an explicit current host closure and withdrawal mapping;
the research `replay_owner.json` is not imported automatically by native readback.

The offline observer traces and research withdrawal wrapper are not current
signed Outcome evidence. Any runtime Procedure admission/use still requires its
separate current ledger owner, exact steps/environment/success criterion/trace
binding and use-time revalidation. An advisory class index or confidence does not
authorize executing the selected procedure. The strong-baseline and coverage
results provide no basis for default activation or live Agentd memory ranking.
