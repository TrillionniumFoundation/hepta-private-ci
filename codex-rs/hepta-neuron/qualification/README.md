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


## Model-to-native execution probe

`native_cell_probe.py` connects the existing artifact-bound resident mDeBERTa
worker to the existing `ui.native` binary clipboard qualification path. It uses a
fixed held-out copy-command slice and two OOD cases. Actual model probabilities
select the action, target and postcondition; expected labels are used only by the
subsequent evaluator. The effect is not preselected from the expected answer.

`apps/hepta-native/qualification/model-decision.mjs` checks the closed probability
shape, finite normalized values, current target generation, the model's explicit
support decision, and a predeclared confidence/OOD rule. The model support flag is
a mandatory veto: the fixed probe thresholds can only narrow support, never undo
the calibrated tensor consumer's abstention. Unsupported decisions abstain before
starting Xvfb. An accepted
choice is encoded with the existing ComputerActionIR codec, executes through
NativeShellRuntime/X11ClipboardPlatform and is independently read back by xclip.
The source/model/reply/frame/outcome chain is retained. The probe cannot issue a
capability: its authorizer is still explicitly a fixture on an isolated display.
The input digest checks provenance consistency within this probe, not independent
product trust. No second effect executor or durable operation owner is introduced.

Run against a clean committed source and exact retained artifact:

```sh
python3 native_cell_probe.py --receipt /qualified/receipts/mdeberta.json \
  --model-path /qualified/models/mdeberta --count 4 \
  --output-dir /qualified/model-native-run
node --test apps/hepta-native/test/model-decision.test.js
```

All selected cases, abstentions and failures are retained. No failed case is retried
or replaced with an easier case. Real clipboard execution does not establish general
GUI perception, independent calibration, a signed product caller, durable native
cross-process recovery, future-window efficacy or production activation. A missing
Python environment/model snapshot is an execution blocker, not a passed probe.

## Model support is preserved across the diagnostic boundary

`hepta.model-native-probe-input.v2` carries a required boolean `modelSupported`,
copied from the single-row `probabilities.supported` returned by the bound worker.
The producer rejects missing, numeric, null, empty or multi-row support before
native dispatch. The JavaScript consumer snapshots this own data property and
requires it to be true **in addition to** its existing action, target, disposition,
postcondition, confidence and OOD conditions. A true flag is not capability,
calibration trust, backend-selection authority or permission for an OS effect.

`hepta.model-native-evidence-evaluation.v3` independently recomputes the combined
rule and binds the receipt's echoed support decision. Old v1 packets and receipts
without explicit support remain historical; they cannot be relabelled as current
support-preserving evidence. The underlying ComputerActionIR wire format and its
registered codec are unchanged. These versions belong to the local experiment,
not to a new public wire contract or durable owner.

Task validity and physical observations stay separate. A bound clipboard readback
observed despite a denied model decision remains `external_effect=true`, but has
`model_policy_respected=false`, `task_passed=false` and `native_policy_violation`.
It must not become an invented `NotApplied` outcome or a retry permission. Missing
or substituted source/request/support/readback evidence remains indeterminate.
Rejecting an in-domain positive task is safe abstention, not successful efficacy.

Regressions use certain heads with explicit support denial, false-like/nonboolean
values, old packets, substituted support, actual JS/Python policy agreement and
post-effect policy failure. The fake-port tests do not establish real-model quality.

## Interrupted native panels retain negative evidence

The `hepta.model-native-execution-probe.v3` report separates experiment completion
from model truth and observed native effects. Before model startup, the probe
writes an exclusive `plan.json` containing every selected case. Its append-only
`progress.jsonl` flushes and syncs each model/native dispatch attempt and retained
case outcome. The final report binds both files by SHA-256. These are local
qualification records, not a second durable operation owner or a product receipt.

A model startup/transport failure, malformed model reply, native launch failure,
interruption or cleanup exception stops subsequent case dispatch. Unstarted cases
remain visible and cannot be replaced with easier inputs. There is no model restart
or automatic retry. A native process-control exception is not evidence of
`NotApplied`: the existing native validator first checks any retained observation,
preserves a verified copy, and leaves missing/invalid evidence indeterminate. A
nonzero evaluator sentinel is not reported as an actual child exit status.

The native runner terminates and reaps only its own private process group on
interruption. Source identity is checked before each model case, again immediately
before native dispatch, and at completion. A cleanup error, source drift or unknown
child cleanup prevents a panel pass even when earlier case effects were observed.
Reports retain exception classes and phases rather than raw exception messages.

This handling covers exceptions while the parent can still write evidence. It does
not claim recovery after parent `SIGKILL`, host power loss, exhausted/unwritable
storage or an adversarial filesystem. The synced plan/progress preserve available
breadcrumbs; they cannot authorize replay. Tests in
`test_native_cell_probe_evidence.py` use explicit fake model/native ports for fault
schedules and a real private child for interruption/reaping. Model quality still
requires a separately executed artifact-bound probe.

## Finite-sample support before calibration trust

`binomial_support.py` adds a separate count diagnostic, without changing historical
`selection-evaluation.v2` receipts or their pilot gates. It calculates one-sided
Clopper-Pearson binomial upper limits for OOD false acceptance and accepted-decision
error, allocating alpha=0.025 to each (familywise alpha <=0.05 by Bonferroni).
An empty accepted population has no bound. Zero observed errors are not zero risk.
The algorithm inverts the binomial CDF; small-population exact-sum regressions,
zero-error closed-form tests and bounded large-population checks accompany it.

For a 0.5% maximum error probability, even zero errors require at least 736
independent trials in each of those two populations. Zero errors among 64 OOD
examples has an upper limit about 5.60%, not 0.5%. These statements assume
independent Bernoulli units and a frozen evaluation rule; a repeated or correlated
synthetic panel does not satisfy that assumption merely by increasing row count.
Episode/source clusters, post-selection effects, additional comparisons and future
windows require their separately declared evaluation method. Passing this count
check cannot issue calibration, artifact-selection or activation authority.

```sh
python3 -m unittest -v test_binomial_support
```

## Auth-route rejection and training rights

The teacher diagnostic distinguishes an exact structured upstream HTTP 400
`invalid_request_error` stating that the requested model is unsupported for the
ChatGPT/Codex auth route from a missing local catalog entry or unknown outcome.
It preserves the associated diagnostic run identity and all negative authority
flags. Free-form stderr, a different model or a timeout is not that rejection.
Do not silently replace the requested model or reinterpret a subscription login
as a separately entitled API account. Tests: `test_teacher_entitlement.py`.

Provider connectivity, selected account entitlement, input privacy, permitted
output-training use and derived-weight distribution are distinct checks. The
actual governing contract and any written permission must be retained by the
appropriate owner. Public API model availability and repository-owner permission
do not by themselves establish rights for a particular subscription/auth route.


## Native Codex transport diagnostics

The OpenClaw Gateway and the native Codex CLI are different transports. An
`Unknown model` result from one is not a completed request on the other. A native
probe uses the already authorized local Codex login, an isolated empty directory,
a unique nonsecret nonce, read-only execution and no requested tools. Do not copy
credentials, edit the user's configuration, silently switch models or retry an
uncertain remote invocation. Capture the exact CLI version, requested model,
command, exit code, JSONL events, final response digest and nonce match.

When stdin is not interactive, explicitly close it (`</dev/null`) or supply the
prompt through a closed pipe. A process still waiting for prompt input has not
established a provider result. Record that local launch failure separately rather
than labelling it a model rejection or silently replacing its evidence.

A completed native nonce roundtrip is connectivity evidence for that invocation.
When JSONL events omit a transport-owned observed model/provider identity, the
`-m` argument remains **requested identity**, not proof of no fallback or provider
qualification. No tool event observed is not an independently enforced tool-sandbox
qualification. Retain the run/thread reference for diagnosis; do not ask the model
to certify its own identity. Connectivity outputs stay outside the training corpus.
The actual account agreement, permitted output use and distribution scope remain
separate from successful login, CLI completion and repository administrator rights.
