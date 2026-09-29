# DecisionCell backend qualification

This package-local qualification harness compares frozen pretrained encoders with
real, separately trained organ/cell adapters and typed heads. It is not a second
Neuron owner, inference runtime, artifact selector, or computer-effect executor.
The authoritative product path remains the guarded V2 owner described in
[the V2 development guide](../../../docs/modules/neuron.runtime/V2_DEVELOPMENT.md).

## Scope and evidence

The generated panel is deliberately synthetic. It contains separate training,
tuning, calibration, test, retrospective-time-labelled, and OOD partitions.
Synthetic time labels are not prospective calendar windows. High accuracy on this
panel establishes neither GUI competence nor production calibration or efficacy.
The base remains frozen; training updates the actual organ/cell adapters and heads,
not the pretrained backbone. Candidate target scoring uses a shared pointer scorer,
not a classifier over fixed target positions. Each artifact binds its tensor groups.

The program retains failed/unsupported cases and emits content-addressed datasets,
embedding tensors, trained weights, manifests, calibration, per-model receipts and
comparison summaries outside Git. A summary is a recommendation for a bounded
experiment only. It cannot issue selection, independent acceptance, activation,
promotion, release, or rights to redistribute a model.

## Source identity before model execution

`model_snapshot` must verify every locally consumed file against the exact upstream
Git commit before executing the backend. A matching revision string is insufficient.
Ordinary files match Git blob hashes; LFS files match their upstream SHA-256 and
size. Extra, modified, duplicate, escaping and malformed files fail closed.
`normalized_hub_manifest` and `verify_snapshot_files` implement this check without
trusting a mutable local directory name as model provenance.

Offline execution remains possible for diagnostics, but it does not fabricate an
upstream observation. Such a receipt cannot pass exact-revision admission. Auditing
cached files later produces a separate record; it does not rewrite or requalify an
older execution. A modified tokenizer/preprocessor requires a separately bound
derivation, never silent editing under the original upstream model revision.

Source identity, safe-code review and licensing are different checks. Matching LFM
custom-code hashes is not code review; a permissive license tag is not an independent
license decision. Unreviewed remote-code candidates cannot become internal-shadow
recommendations merely by producing a good score. No candidate in this synthetic
panel is eligible for runtime selection.

## Immutable Laya loader inputs

The pinned Laya source calls `_fix_tokenizer_config` inside `Agent.__init__` and
rewrites a list-valued `extra_special_tokens` field in place. Feeding the original
upstream directory to that constructor therefore changes the bytes previously
admitted by the snapshot verifier and prevents later exact-revision replay.

`laya_loader_view.py` now copies the admitted snapshot to private regular files,
checks the copy against the previously admitted inventory digest, and performs
only `laya-tokenizer-compatibility-v1` there. Its receipt binds both the original
snapshot and effective loader-input digests, the exact before/after tokenizer
bytes, changed paths and this adapter's code digest. The original snapshot is
never repaired or relabelled in place. A previously changed cache must be retained
as diagnostic evidence and replaced by a separately materialized exact upstream
snapshot before another qualified run.

The caller verifies the view after loading and again after model use; artifact
replay requires the identical effective loader identity. Undeclared writes, source
drift, symlinks, invalid configuration and silent device fallback reject. The
private view is removed on close. This is an integrity/compatibility adapter, not
an OS sandbox, code-review approval or evidence that a model is selected. The
trusted-parent-filesystem assumption still applies during loader use.

```sh
python3 -m unittest -v test_laya_loader_view
python3 -m unittest -v test_tensor_bundle
python3 artifact_replay.py --receipt /qualified/output/receipts/MODEL-DIGEST.json \
  --model-root /qualified/models --device cpu --output /qualified/replay.json
```

## Commands

From this directory, use an isolated environment with the pinned direct dependencies
in `requirements-bakeoff.lock.txt`. That file is not a transitive, hash-locked build.
Keep the concrete environment and runtime identity with each executed experiment.
Do not install or upgrade dependencies from a live Cell invocation.

```sh
python3 -m unittest discover -s . -p test_snapshot_identity.py -v
python3 -m unittest discover -s . -p test_decision_cell_bakeoff.py -v
python3 decision_cell_bakeoff.py --output-dir /qualified/output \
  --model-root /qualified/models --device cpu prepare
python3 decision_cell_bakeoff.py --output-dir /qualified/output \
  --model-root /qualified/models --device cpu run --model mdeberta-v3-base
python3 decision_cell_bakeoff.py --output-dir /qualified/output \
  summarize --models mdeberta-v3-base
python3 decision_cell_bakeoff.py --output-dir /qualified/output \
  verify --models mdeberta-v3-base
```

`snapshot_identity.py` can audit a pinned local model against public HTTPS metadata
without importing PyTorch, sending credentials or executing model code. It writes
a new audit with the validator digest and upstream response digest. Its records
are local qualification evidence, not registered cross-module authority contracts.

Run each backend in a separate process. The comparison refuses mixed dataset,
script, source commit/tree, maximum input length, or duplicated model identities.
A real equal-condition bakeoff must additionally freeze device, concurrency,
precision, tokenizer/preprocessor and the complete end-to-end workload. Report
encoder extraction separately from full decision and actuator latency.

## Remaining product qualification

The selected inference owner must consume the exact admitted base/organ/cell/head
bundle and calibration/OOD artifacts. This training harness does not install that
owner, migrate live state, or sign its own artifacts. Browser/native effects still
require the registered semantic contract, final-use authority, durable operation
identity, target generation and trusted terminal observation.

External teacher traces need an independently admitted input/data-use scope and
applicable output-training rights before training a distributable artifact. Teacher
agreement is not ground truth. Retain independent environment outcomes, human review,
student-state coverage and prospective holdout; do not replace them with synthetic
labels or a successful HTTP response.

## Complete-decision evaluation profile

`hepta.decision-cell-selection-evaluation.v2` includes action, applicable target,
disposition **and postcondition** in joint accuracy. Report the actual intersection
of confidence acceptance and OOD acceptance, its in-domain coverage, complete-decision
error and a Wilson 95% upper bound. An empty accepted set has an undefined error
rate (`null`), not observed zero risk. Accepted OOD rows count as unsupported errors.

The pre-run synthetic diagnostic panel retains prior quality floors and additionally
requires postcondition accuracy >=0.80, at least 20 supported in-domain rows,
supported in-domain coverage >=0.25 and supported joint error <=0.05. These empirical
pilot thresholds do not relax any production bound or establish statistical safety.
All-reject behavior remains a valid fallback, but cannot win backend selection.

Receipts and head manifests bind the evaluation profile and implementation digest.
Do not relabel old metrics with new semantics: use the historical evaluator or record
a new evaluation. Comparisons also require identical recorded host/runtime/thread/
device profiles. Summary verification recomputes model rows, gates and recommendations
from the verified receipts; merely rehashing a modified summary cannot certify it.

The shared tensor consumer separately checks the closed runtime-profile semantics,
including projection, pooling, class digests and integer dimensions. It validates
owned floating-point feature snapshots and rejects non-finite calibrated outputs.
These integrity checks do not manufacture independent calibration or OOD trust.

Dependency-free regressions: `python3 -m unittest -v test_decision_cell_metrics`.

## Bounded head retraining when backbone materialization is already retained

`head_retraining.py --source-receipt PATH --source-receipt-sha256 SHA256
--output-dir OUTPUT` reuses this package's existing `fit_heads`, calibration,
evaluation, artifact serializer and the shared inference-worker tensor consumer.
It checks the original receipt/artifact hashes, exact dataset labels, row order,
feature dimensions, finite values and bounded NPZ expansion before optimization.
No source or historical receipt is rewritten. Model/download dependencies are
loaded only at the boundary that actually needs them.

The resulting `hepta.decision-cell-head-retraining.v1` report records actual
optimizer execution, separately changed organ/cell/head parameter groups, exact
saved-weight reload parity, and the versioned complete-decision metrics. The
original base-materialization source and feature artifact remain explicit inputs.
This is **head retraining from historical real-encoder features**, not a new base
inference, current upstream audit, full model bakeoff, independent calibration,
prospective data collection, artifact selection or production activation. The
current entry admits only the already declared synthetic corpus. A success here
cannot supply missing Laya execution or justify distributing vendor-derived models.

## Frozen encoder consumed by the runtime worker

`hepta-infer-worker-host/python/decision_cell_encoder.py` now owns one bounded
CPU session for the pinned mDeBERTa base and the existing V2 tensor graph. It loads
actual base weights once and reuses the same organ/cell adapters and typed heads
used by training. It imports no qualification encoder and downloads no model or
remote code during a request. Host-supplied manifest hashes still require current
artifact-owner admission; this library cannot select its own artifact.

Loader inputs are byte-copied into a private read-only snapshot with inventory,
size and content validation. Requests use immutable bounded text/target batches;
overlong token sequences reject rather than truncating away target information.
A monotonic deadline is checked around encoder work and before result publication.
Hard interruption and concurrent-request serialization remain supervisor/owner
responsibilities: a deadline check alone does not interrupt a running CPU kernel.
This explicit profile has four candidate targets and no temporal/parameter-value
head. It is not a general daemon bootstrap or a new durable execution owner.

```sh
python3 -m unittest -v test_frozen_encoder test_tensor_bundle
python3 frozen_encoder_probe.py --receipt /qualified/receipts/mdeberta.json \
  --model-root /qualified/models --output /qualified/frozen-encoder-probe.json
```

The probe re-encodes raw held-out observations, consumes actual trained tensors and
compares complete-decision metrics against the frozen source receipt. Unit tests
use an explicitly fake backbone for lifecycle faults, not model quality evidence.
Neither path establishes independent calibration, prospective GUI efficacy,
production activation, teacher-data rights, operator acceptance or release.

## Private resident encoder process and bounded interruption

`hepta-infer-worker-host/python/frozen_decision_cell_worker.py` serves the same
frozen encoder/tensor graph through a closed JSON-lines private channel. Its
command envelope binds a host-selected session, exact invocation digest, request
identity, immutable text/target projection and process-local deadline. A bounded
volatile result cache retains observed or indeterminate executions; identical
queries reuse bytes, changed semantics reject, and lookup never invokes a model.
A fresh process returns unknown for an unretained request, never NotApplied.
The existing Neuron operation owner must persist dispatch/result and owns recovery;
this cache is not another durable journal. Capacity rejects before model work.

`decision_cell_process.py` is the POSIX private transport for that worker. Both
pipe writes and reads honor bounded deadlines and cancellation. Channel corruption,
identity drift, timeout or cancellation permanently closes the handle, kills its
private child process group and reaps the child. It never starts a replacement or
retries an unknown inference. A host supplies reviewed code/environment, selected
artifacts, reservation and current authority; a ready message grants none of them.
Windows, general daemon bootstrap, real temporal/parameter-value heads and
independent calibration are not implemented by this four-target CPU profile.

`test_frozen_worker_protocol.py` and `test_frozen_process.py` test duplicate/lost
reply behavior, unknown recovery, bounded framing, real child exit/kill, blocked
writes, cross-session binding and cancellation. The subprocess fixtures are not
model-quality tests. `frozen_process_probe.py` separately loads the actual retained
base and trained tensors, reuses a resident worker, verifies original reply reuse,
checks lookup after replacement, and interrupts a real model child. Its report
retains exact source/artifact identity and does not claim production activation,
external action success, independent acceptance or prospective efficacy.

The process host owns the private model snapshot parent and removes only that
created directory after confirmed child exit. Hard cancellation cannot rely on a
child's `finally` cleanup. If exit or cleanup is unconfirmed, new calls remain
closed and a later close can finish cleanup; the directory is not deleted while a
child may still be running. Host crash/power-loss cleanup requires the deployment
supervisor's own retained launch inventory and is not claimed by these tests.

## Complete batch execution, not partial-success selection

The existing `all` command creates a fresh `panel-*` directory beneath
`--output-dir`; it never borrows `.current.json` receipts from an earlier panel.
`--model-timeout-seconds` bounds each child (default 900, maximum 3600 seconds).
Every requested backend is attempted once, in a separate process, even after an
ordinary backend failure. Logs, exit codes, elapsed time, source/runner digests
and started/finished events are retained in that panel. Timeout terminates and
reaps the private process; user interruption stops subsequent backend launches.
Duplicate backend names and invalid deadlines reject before execution.

Any failed, timed-out or unlaunched backend makes `all` exit nonzero without
comparing partial results or recycling a prior recommendation. Only a complete
successful execution panel with unchanged source reaches the existing full
receipt/summary verification. Execution success is not a quality pass, artifact
selection, current calibration trust or production activation. Single-backend
`run`, `summarize` and `verify` commands keep their existing explicit semantics.

Dependency-free runner regressions: `python3 -m unittest -v test_bakeoff_panel`.

## External teacher connectivity is not training permission

`teacher_connectivity.py` inspects retained `openclaw models list --plain`,
Gateway JSON and diagnostics without reading credentials, changing configuration,
calling a provider or retrying. Bind the exact requested provider/model and nonce.
A missing configured model, model fallback, missing transport-owned identity,
incomplete/aborted result, changed nonce or non-boolean flags cannot establish
connectivity. Preserve a returned Gateway run ID after an error for reconciliation;
a local CLI exit is not proof a remote run never started. Reports retain hashes,
not raw diagnostics, prompt text, account identifiers or secrets.

Even a valid connectivity observation leaves provider qualification, tool isolation,
training-data admission, training rights, operator acceptance and activation false.
A model's self-description is not provider identity, and repository administration
rights do not grant third-party output-training rights. Determine the actual account
agreement and any written permission before admitting teacher outputs to training.
The [Services Agreement](https://openai.com/policies/services-agreement/) and
[consumer Terms](https://openai.com/policies/terms-of-use/) have different scope;
neither an OAuth login nor this diagnostic decides which agreement applies.

```sh
python3 -m unittest -v test_teacher_connectivity
python3 teacher_connectivity.py --catalog /observed/models.txt \
  --response /observed/gateway.json --diagnostics /observed/gateway.stderr \
  --expected-model openai/gpt-6-luna --nonce frozen-request-nonce \
  --output /observed/teacher-connectivity.json
```

This package-local observation is not a cross-module authority protocol. Exit 2
means connectivity was not established; it is not permission to change models,
copy tokens, switch agents or reissue an uncertain provider request.
