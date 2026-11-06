# Development action-value training on the existing capture path

`r2_action_value.py` adds an actual parameter-training and checkpoint-loading
path for a **one-step development predictor**. It reads the existing
`transition_capture_read.read_capture` output. It does not run generators,
select or execute actions, score generated content, or open a test split.
The current implementation is a precursor to a greedy control baseline;
it is not the complete controller/generator R2 trainer or a qualified baseline.

## Input and observation boundary

The training bundle schema is `hepta.r2.action-value-training.v1`. Its canonical
SHA256 must be supplied separately to `fit`. The bundle contains:

- `purpose`: `development` or explicitly `synthetic_control`.
- `config`: seed, updates, learning_rate, momentum, l2, maximum_cpu_seconds,
  maximum_wall_seconds, cpu_tariff, wall_tariff, service_tariffs, failure_utility.
- `roster`: capture_id, directory, summary_sha256, declared_source, split and
  source_cluster_id for every admitted capture. Paths are explicit local read
  inputs; relative paths resolve from the bundle file. This is not an OS path
  sandbox. `declared_source` is the original `DevelopmentSource` object.
- `label_manifest` with schema `hepta.development-action-labels.v1`, evaluator_id,
  evaluator_source_sha256, rubric_sha256 and rows; `labels_sha256` commits it.
- Each label row has capture_id, step, transition_sha256, utility_before and
  utility_after. `transition_sha256` hashes the entire corresponding transition
  returned by the existing reader, including its actual attempted before-view.

Only `train` observations change parameters. `development` observations receive
descriptive prediction-error reporting and never update parameters. Declared
source clusters, source IDs and exact input image hashes cannot cross these
splits. Test/validation rows are rejected. Captures must match the installed
runtime/recorder source and the `fresh-after-capture-v1` admission contract.
Every observed action needs a label, including failed/cancelled/timed-out
actions. If the final action returns but the original episode rejects it at a
deadline or finalization check, its outcome still requires failure utility.
An intent with no observed action terminal gets no fabricated reward;
its transition, failure and original costs remain in `INPUT_RECEIPT.json`.
Missing or corrupted captures reject the entire fit rather than disappearing.

Labels must come from the separately established development evaluation
process. The software cannot authenticate that custody from a JSON identity or
hash. It always records `custody_authenticated=false` and `no_update=true`.
Here `no_update` means no promotion or replacement of the incumbent. Candidate
parameters do change; `updates_completed` and initial/final parameter hashes
record those actual optimizer updates.
Synthetic backend captures cannot be relabelled as real development evidence.
This does not prove that every other provider or declared source is authentic,
or establish perceptual near-duplicate or independently verified source clusters.

## Model, objective and preserved costs

The fixed 143-feature encoding uses only the nine-field public before-View:
four separate 32-bin signed SHA256 word-count vectors, public state/budget
scalars, and seven action-history counts. It never reads the image path, source
ID, after-state, evaluation label or future outcome. It has no visual embedding;
that limitation must be resolved or measured before claiming a strong baseline.

Seven action rows are trained by seeded full-batch SGD with momentum and an
explicit L2 penalty. The target is the independently labelled utility change
minus the recorded controller/action CPU/wall intervals and the explicitly
declared service fee for that action. CPU/wall tariffs remain 0.02/0.001;
every service mapping must be supplied. Development failure utility is -1 and
abstention utility is zero. These are development-contract declarations, not a
completed freeze of the real R2 action service mapping or evaluator rubric.
Actions absent from training are refused at prediction time; an unsupported
development action produces an unknown aggregate MSE, not a zero prediction.

This regression target is not the gamma-2 population certainty equivalent.
It also does not establish expected value of sample information, continuation Q
or a qualified greedy baseline; those require further modelling and evaluation.
The original seven CE contrasts, 32 independent fit seeds and crossed bootstrap
are unchanged. Preflight, finalization, nested observer costs and unknown costs
remain in their original retained ledgers. They are not silently assigned to a
training example or summed twice. The predictor supplies no whole-cost benefit
claim. Its CPU/wall budgets cover input validation, updates and checkpoint
writing, checked synchronously; they are not preemptive hard limits.

## Execution and reload

```bash
python -m experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.decision_audit.r2_action_value fit \
  --bundle /absolute/development/bundle.json --bundle-sha256 PRECOMMITTED_SHA256 \
  --output /absolute/new-fit-directory
```

The output preserves `INPUT.json`, `INPUT_RECEIPT.json`, the actual numeric
`TRAINING_ROWS.json`, `FIT.json` and, on completion, `checkpoint.json`. The
checkpoint includes initial/final parameter hashes, complete momentum state,
training-row identity, source hashes, config, Python/NumPy versions and action
coverage. Failed attempts retain their error, measured cost and available
partial state. Existing output directories are never overwritten.

The `predict` subcommand accepts only a public `view` and `action` query, plus
the separately retained checkpoint and `FIT.json` SHA256 values
(`--checkpoint-sha256` and `--fit-sha256`). It verifies source/numeric identity, parameter
and optimizer shape, and the completed fit receipt. A checkpoint whose write
exceeded the budget is retained but refused. A mutable sibling status is not
accepted as the fit identity. It does not load the generator or resume training.
The training-row identity is recorded; prediction does not re-open training data.
Overflowing loss, optimizer or prediction arithmetic is refused. Failed final
receipt writes return a failed result with no fabricated receipt identity.
The POSIX CLI translates SIGTERM to a caught cancellation and writes its
receipt; library callers may deliver `KeyboardInterrupt`. Kill/power loss and
incomplete storage still require external recovery and remain unknown.
The behavioral tests exercise actual SGD and a new Python prediction process
using explicitly synthetic captures/labels. They do not provide real R2
training, independent semantic evaluation, generalization or production
qualification. All six original scientific/data/custody gates remain open.
