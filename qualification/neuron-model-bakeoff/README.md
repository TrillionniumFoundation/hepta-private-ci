# Hepta Neuron model bakeoff — executable, fail-closed research lane

This lane tests five fixed candidates without changing the production Neuron
or Inference Control owners. It implements experiment tools, **not** completed
benchmark evidence, signed operator acceptance, a GPU deployment, or model
promotion. All report formats explicitly retain independent acceptance=false.

## Models and comparable experiments

1. Baseline: convaiinnovations/laya (421M) and laya-typed-decisions (421M).
2. Direct substitute: laya-multilingual (322M), same choice-task test rows.
3. Frozen shared Encoder + equal-budget ranker: Snowflake arctic-embed-m-v2.0
   (305M) and Microsoft harrier-oss-v1-270m (270M); each has a deterministic,
   256-parameter ranker, the same update count/seed/optimizer and fixed
   nontrainable Gaussian projection. This is a **new decision Head**, not
   Laya-head compatibility. Compare retrieval separately with retrieval.py.
4. Calibration: a disjoint calibration split selects a fixed temperature from
   a preregistered grid, never from future_test. The abstention threshold must
   be selected/frozen independently before running the final holdout.
5. Resource scale: 64/256/1024/4096 distinct logical cells, separately
   configured actual active concurrency; report latency, throughput,
   serving-PID RSS, host-wide GPU memory and queue-age. A separately observed
   signed model-load receipt is still needed.
6. Lifecycle: check Ed25519-signed Artifact CAS, supervisor fence, route
   cutover, old-generation denial, forced crash, durable recovery, rollback
   at a strictly *new* generation, and stale candidate rejection.

Source models: https://huggingface.co/convaiinnovations/laya ;
https://huggingface.co/convaiinnovations/laya-typed-decisions ;
https://huggingface.co/convaiinnovations/laya-multilingual ;
https://huggingface.co/Snowflake/snowflake-arctic-embed-m-v2.0 ;
https://huggingface.co/microsoft/harrier-oss-v1-270m .

## Setup and real measurement

The source commit, model repo and revision, all seven artifact digests, dataset
SHA256, predictions SHA256, training profile and outcome partitions are bound
in the emitted run receipts. **No implicit HF downloads are allowed.**
Prepare each model snapshot in a private target host by independently
downloading a specific 40-character HF revision and verifying its immutable
weights/tokenizer against the owner's artifact registry.
A freeze-ready plan must explicitly set `kind=frozen_experiment_plan`,
`source_commit` to the exact runner checkout SHA, a timezone-aware
`registered_before_utc`, and a preregistered `abstention_threshold`
strictly between zero and one. Template values cannot pass evaluation.
Each model run must bind the **same** source commit and threshold.
The plan's `model_artifacts` map must independently freeze **all five**
40-character repository revisions and 64-character *observed-model-inventory*
weight/tokenizer digests before future-test analysis. A new runner revision
or a silently changed safetensors/tokenizer fails the comparison. This is
an identity check and not proof that an independent Artifact CAS owner
authenticated the files.
The evaluator independently recomputes abstention from each published
probability vector; changing an `abstained` boolean cannot improve
selective accuracy or OOD acceptance. Reported `accuracy` is raw
prediction accuracy on all in-domain rows, `effective_correct_rate`
is correct-and-accepted divided by all in-domain rows, and
`selective_accuracy` is correct/accepted. Keep these distinct.

The three Laya arms require distinct **repository-specific** local
Hugging Face cache snapshots. The English bundled repository's
multilingual/typed sibling files are excluded from the English artifact
hash; standalone Typed/Multilingual snapshots must correspond to their
own repository paths. Directory names are a drift check, not independent
artifact provenance or proof of real execution.

The runner now requires --device cpu|cuda|mps and verifies the selected
device on load and after inference (Laya may otherwise silently fall back
to CPU after an OOM). Its quantization digest binds the loaded tensor
shape/dtype/device manifest; full quantization calibration, operator and
runtime identities still require external Artifact Registry verification. The resolved folder
must be a real Hugging Face cache snapshots/<revision> directory. Install
pinned compatible versions of torch, transformers, laya, sentence-transformers
and numpy on that host; retain an external lock/SBOM. Some upstream checkpoints
require reviewed custom code; this runner intentionally disables
trust_remote_code and fails closed if compatible safe loading is unavailable.

Dataset JSONL requires one row per decision with id, cluster, split
(train/validation/calibration/future_test), timezone-aware event_time,
language, slice, ood (boolean), state (text), question (text), options
(list of distinct strings), and gold (an option). Clusters must not cross
partitions and the four split cohorts must be ordered. Future-test rows
**must** also name `future_window=future_1|future_2`; non-holdout rows
must not claim a future window. Both windows require in-domain tasks, strictly
ordered timestamps, and disjoint source clusters. Holdout requires both
in-domain and OOD rows overall. The frozen plan's registration timestamp
must strictly **predate the first future-test event**; a later registration
fails closed, even if a self-reported plan hashes correctly. This is a
structural anti-retrospective gate, **not proof of independently timestamped
registration or custody of future labels**. Those remain external blockers. Dataset rows must be supplied by an independent owner;
never commit raw private states or labels. The example plan is **not frozen**
until a real dataset digest, role separation, thresholds and a preregistration
timestamp are externally authenticated.

From the checked-out exact source commit (do not run against uncommitted
changes), for each model:

    export HF_HUB_OFFLINE=1 USE_TF=0
    python3 qualification/neuron-model-bakeoff/run_models.py \
      --model laya-english-421m \
      --snapshot /private/hub/models--convaiinnovations--laya/snapshots/ACTUAL_SHA \
      --revision ACTUAL_SHA \
      --source-commit "$(git rev-parse HEAD)" \
      --dataset /private/eval/locked.jsonl \
      --abstention-threshold PRE_REGISTERED_FLOAT --device cuda \
      --output-root /private/eval/runs

Repeat for typed, multilingual, Arctic and Harrier with their own actual
snapshot, repository and revision. Never route typed to the wrong checkpoint.
The Laya runner uses the published typed choice interface; score and noul
primitives require separately versioned evaluation adapters. Laya's rounded
option probabilities are renormalized; unknown/malformed outputs abort.

The Encoder runner freezes the base and fits only a linear, 256-parameter
choice Head. It does **not** claim equal encoder FLOPs, and it does not
claim one training recipe is optimal. Training input/order, trainable
parameters, optimizer, seed and temperature grid are controlled identically.
Training memory/time, full inference time and power require separate receipts.

Then, after the independent dataset owner has published an immutable
preregistered plan:

    python3 qualification/neuron-model-bakeoff/bakeoff.py \
      --plan /private/eval/frozen-plan.json \
      --dataset /private/eval/locked.jsonl \
      --runs /private/eval/runs \
      --output /private/eval/diagnostic.json

The evaluator aborts if any of the five runs is missing, a model or artifact
identity drifts, Head budgets differ, data leaks between partitions, OOD is
absent, probabilities are malformed, or holdout predictions are incomplete.
It reports raw accuracy, correct-and-accepted rate, selective
accuracy/coverage, class-balanced recall, macro-F1, multiclass normalized
Brier, ECE (top-confidence, 15 bins), OOD false acceptance,
per-language/task regressions, **separately scored future_1/future_2**
metrics and maximum within-window accuracy regression, and a
**diagnostic-only paired cluster bootstrap interval**
(2,000 deterministic resamples). A future-window without OOD rows has
`ood_false_acceptance=null` (unknown), never fabricated as zero; aggregate
holdout OOD is still mandatory. Metric admission checks *both* future windows,
not merely the pooled headline. A high raw accuracy
can hide total failure on a rare class; it cannot qualify by itself.
For the two Encoder arms, it independently hashes the exact labeled
**train partition** and rejects a mismatch across the published Head
training receipts. This diagnostic is not a causal or independent acceptance
decision. Correlated-cluster confidence bounds, alpha spending, power,
retention and two real future windows remain mandatory external gates.

For each shared Encoder separately run real retrieval on the same frozen
query/corpus files (query rows have id, split=future_test, query,
positive_ids; corpus rows have id and text):

    python3 qualification/neuron-model-bakeoff/retrieval.py \
      --model harrier-270m --snapshot /private/hub/REPO/snapshots/ACTUAL_SHA \
      --revision ACTUAL_SHA --source-commit "$(git rev-parse HEAD)" \
      --queries /private/eval/queries.jsonl \
      --corpus /private/eval/corpus.jsonl \
      --output /private/eval/harrier-retrieval.json

Observe Recall@10, MRR@10 and NDCG@10. Rankings are deterministic. Query
vectors must use each model's reviewed **query-only** prompt: Arctic
`prompt_name="query"`, Harrier `prompt_name="web_search_query"`; document
embeddings do **not** take either query prompt. Missing registered prompts
fail closed, and their name/content SHA256 are recorded in the retrieval
receipt. Any prompt change invalidates old scores. These are upstream
retrieval instructions, not user-provided policy authority.
This retrieval result does not automatically establish decision superiority.

For serving, build a **real** isolated qualification-only local adapter bound
to the Inference Control owner. The adapter must accept one POST JSON with
request_id/cell_id/generation/model_digest/mode and return exactly bound IDs,
terminal_observed, success, output_digest and queue_age_us. It must not
perform tools/effects; no retries for uncertain requests. Model identity
comes from the independent Artifact CAS owner, not from request assertions.
Run scale.py against loopback with its real serving PID and selected active
concurrency. Server RSS is a single PID; GPU metric is whole-host, not
per-process, so separate isolation evidence is still needed. Load-time and
crash/adapter miss costs are **not fabricated**.

Lifecycle.py requires ten exact signed events with separate pinned
artifact_owner/supervisor/router/observer Ed25519 keys, monotonic sequence,
previous-receipt chain, actual operation IDs, immutable model digests,
observed outcome and new rollback generation. Pass the independently
pinned trusted-keys SHA256. It verifies signatures and consistency, not
physical CAS, routing, execution or final-use authorization.

## Regressions and claim ceiling

    python3 -m unittest discover -v -s qualification/neuron-model-bakeoff -p 'test_*.py'

The synthetic contract and loopback tests exercise negative inputs and no-authority invariants.
They are never model accuracy, resource or live crash measurements. Real
acceptance additionally needs signed owner-observed artifact writes,
independent dataset provenance/holdout verification, target-host performance,
model-load and failure receipts, evaluator/operator separation, confirmed
hardware/software bill of materials, retention, zero unauthorized final use,
canary and rollback. Until then all six production gates remain blocked.

Existing canonical authorities remain:
docs/learning/NEURAL_BIOMIMICRY_SPEC.md,
docs/readiness/NEURON_RUNTIME_EXECUTION.md,
qualification/module-execution-dossiers/LEARNING_EXPERIMENT.md and
qualification/module-execution-dossiers/detail/inference.worker.md.
