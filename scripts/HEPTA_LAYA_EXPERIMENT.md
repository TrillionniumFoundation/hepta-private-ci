# Pinned Laya retrieval experiment

This is an experimental leaf of the existing Neuron/inference learning work,
not a second execution owner, source ledger, global plan, evaluator authority,
or production organ. The canonical ownership and development policy remain in
`docs/DEVELOPMENT.md`. No model installation, caller activation or promotion is
performed by these scripts.

## Implemented boundary

`hepta_laya_retrieval.py` verifies a local CPU/fp32 bundle, Laya SDK 0.3.20 and
runtime package versions. The initially observed upstream model revision is
`convaiinnovations/laya@55cf4c4ebb4ebe31b2550e8bdf3bd21b99753851`.
A local hash records actual bytes; it does not authenticate their origin.
The five mandatory artifacts and every optional file under `encoder/` and
`tokenizer/` are hashed. Symlinks, altered files, silent tokenizer rewriting,
CPU mixed-precision mode and token truncation reject. The private encoding API
is intentionally SDK-version-bound. Runtime package versions are not binary
attestation: immutable, independently verified package installation is still a
host responsibility.

An input binds operation/workspace/generation, objective, observation, bundle,
query and exact source revisions/bytes. The output can only select an input
source or abstain. It binds the complete ordered candidate set and predictions,
plus a separate deterministic behavior policy and propensity. Model confidence
and `act_probability` issue no authority. Exceptions, timeout and withdrawal
produce no valid result and never trigger an automatic model retry.

`hepta_laya_experiment.py` compares lexical ranking, a four-parameter classifier,
frozen Laya (the no-change baseline), and a trained four-parameter head over
frozen Laya/lexical features. It does not fine-tune Laya weights or implement
organ credit, general recursive NDU, LoRA or structural plasticity. The local
head uses bounded deterministic cross-entropy descent and held-out temperature
selection. Insufficient training data leaves the Laya head unchanged.

Training, calibration, future-event evaluation and retention partitions must all
be present. Task groups and normalized queries cannot cross partitions. Training
labels must predate calibration events, and calibration labels must predate
future events. Separately supplied annotations never enter model input. These
checks do not detect every semantic duplicate or authenticate the observer.
Source text may be shared when legitimately needed across different tasks.

All comparisons use one declared resource ceiling, not equal observed cost.
Worst-case input-token capacity is reserved before each experiment call; the
observed token total cannot reset between rows. Collection is physically shared
once, while each Laya arm reports the inference cost it requires. Training,
calibration and scoring times are retained separately. CLI bundle verification
and loading time are measured separately from the steady-state budget. Memory,
power, asynchronous provider reconciliation and native migration are unmeasured.
A deadline check is not hard process preemption; the native inference worker must
enforce isolation and interruptibility when this becomes a product path.

## Run locally with explicitly provisioned weights

Use a separately provisioned environment with Laya 0.3.20 and dependencies. Nothing
here downloads a model. Materialize the reviewed checkpoint locally, including
`model.safetensors`, `rl_agent_config.json`, `encoder/config.json`,
`tokenizer/tokenizer.json` and `tokenizer/tokenizer_config.json`. Normalize any
SDK-incompatible tokenizer configuration into a **separate candidate bundle**,
then hash that effective bundle rather than claiming unchanged upstream bytes.
Set offline flags before loading Python dependencies:

```sh
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
python3 scripts/hepta_laya_retrieval.py --model-root /absolute/model \
  --revision 55cf4c4ebb4ebe31b2550e8bdf3bd21b99753851 > /tmp/laya-bundle.json
python3 -c 'from pathlib import Path; from scripts.hepta_laya_retrieval import digest,strict_json; print(digest(strict_json(Path("/tmp/laya-bundle.json").read_bytes())))'
python3 scripts/hepta_laya_experiment.py --model-root /absolute/model \
  --bundle /tmp/laya-bundle.json --bundle-digest <PRINTED_SHA256> \
  --dataset /absolute/dataset.json --annotations /absolute/annotations.json \
  --budget /absolute/budget.json > /tmp/laya-experiment.json
```

Missing weights/dependencies, incompatible pins, invalid splits, unavailable
inference and budget exhaustion are failures, not skipped successful experiments.
The caller must retain stderr/nonzero exit diagnostics; no incomplete JSON report
is evidence of improvement. Output files should be outside the repository tree.

Dataset fields:

- Top level: `schema="hepta.retrieval.dataset.v1"`, `workspace_id`, nonzero
  SHA-256 `objective_digest`, and `rows` (1..10000).
- Each row: `row_id`, `group_id`, `split` (`train`, `calibration`, `future`, or
  `retention`), positive `event_at_ms`, `query`, `sources` (1..15).
- Each source: `source_id`, positive `revision`, `content_sha256` of its exact
  UTF-8 text, and `text`. Query and individual text are bounded to 2048 bytes.
- Separate annotations: `schema="hepta.retrieval.annotations.v1"`, canonical
  `dataset_digest`, `observer_id`, `labels`. Each label contains `row_id`,
  `correct_source` (admitted source ID or null), and `observed_at_ms`.
- Budget: `per_request_ms`, `max_total_input_tokens`, `max_elapsed_ms`,
  `minimum_train`, `epochs`. Defaults are 5000, 131072, 600000, 32, 40.
  A supplied budget JSON may omit defaulted fields; unknown fields reject.

Digests use UTF-8, sorted keys, compact JSON, preserved array order and no NaN or
Infinity. Untrusted JSON duplicate keys reject. The tests construct small
**synthetic** datasets demonstrating the schema; they are not training evidence.

## Verification and remaining product integration

```sh
python3 -m unittest -v scripts.tests.test_hepta_multiscale_scope \
  scripts.tests.test_hepta_laya_retrieval scripts.tests.test_hepta_laya_experiment
cd codex-rs
just test --locked -p codex-hepta-automation --test convergence_recovery
```

The workflow `hepta-multiscale-regressions.yml` binds source-head and deterministic
base-merge checks to the actual Git event. It uses read-only permissions and the
existing exact-execution recorder. Ordinary prose does not select native recovery
work. This workflow does not replace `CI required` or `Architecture required`.
Python tests use explicit doubles. Automation tests exercise close/reopen; the
semantic owner suite additionally kills a real child after named durable
boundaries. Neither supplies real-model, live-browser, disk power-loss or
independent product qualification. Native tests must actually execute before a
pass is recorded; a missing/failed native result remains missing/failed.

The native semantic input/output boundary below is now source-implemented.
Existing `NeuronFeatureRequestV1` still carries numeric features and is unchanged.
Current `PinnedCognitiveRanker` loads an independently selected tabular artifact.
Do not bypass that selector or instantiate this script as an unrestricted Agentd
model server. Product integration still needs native owner integration of a qualified transport,
the durable owner/worker composition described below, source/registry
currentness at final use, artifact approval/revocation, then real task data on
fixed hardware. Source implementation of the owner journal is not product
startup selection or independent qualification. The
advisory callback here is not a sealed capability and cannot supply permissions.

Controlled computer effects and stateful topology cutover remain with their
existing owners. No arbitrary process-memory writes, automatic computer actions,
writer replacement, force merge, evaluator change or production activation are
added. Full five-stage completion requires their separate executable evidence.

## Native semantic data profile and worker extension

`codex-rs/hepta-infer-core/src/semantic_retrieval.rs` owns the new bounded
`SemanticRetrievalRequestV1` and reply decoder. `hepta_retrieval_wire.py` is the
matching leaf codec. Requests use magic `HPTARQ` followed by version byte 1 and
zero; replies use `HPTARS` with the same version bytes. Integers are big endian,
strings have u32 byte lengths and digests are raw SHA-256. There is no native
pointer, machine code, command line, authority token or arbitrary JSON field in
the wire. The whole frame is bounded to 64 KiB; query/source text is bounded to
2048 UTF-8 bytes, with 1..15 distinct sources and positive bounded revisions.
The request binds the exact supplied source order. Probabilities have a distinct
canonical order: abstain, then source IDs sorted by ASCII. Their integer ppm
mass is exactly one million. Neither a prediction nor its wire hash authorizes
an action or independently proves the model ran.

The request carries operation/workspace/generation, objective/observation/bundle
identities and an absolute Unix-millisecond deadline. The loaded model manifest's
model digest must equal the selected bundle digest for this profile. The result
binds the exact full request bytes, bundle, complete prediction vector and
observed token/latency values; request/bundle/shape drift rejects. Existing JSON
experiment digests retain their old meaning and are not replaced by wire hashes.

`InferenceWorker::run_semantic_retrieval` calls an explicitly supplied
`SemanticRetrievalDriver` through the existing loaded handle, grant validation,
active-request map and per-model active count. Its maximum_tokens is a total
input-plus-output token bound. Error, malformed output, missing measurement or
observed budget overrun retains the active identity instead of permitting replay
or unload. Pre-entry cancellation has a distinct error and is checked only after
an existing unknown request has been ruled out. The driver trait is not a
sandbox or durable result store. The bounded Linux process primitive described below is available, but no native
`SemanticRetrievalDriver` implementation or Agentd startup selection is supplied
by this profile.

The Python leaf entry point reads one complete binary frame from stdin, checks
it before loading a pinned model, scores once and writes one binary reply. It
has no retry/fallback loop. For a separately admitted request/model environment:

```sh
python3 scripts/hepta_laya_worker.py --model-root /absolute/model \
  --bundle /tmp/laya-bundle.json --bundle-digest <PRINTED_SHA256> \
  < /absolute/request.bin > /tmp/reply.bin
```

The host must close stdin, bound wall time, isolate/terminate the process, measure
resources and revalidate current sources/artifacts before consuming the result.
The Python currentness callback only describes immutable supplied bytes; it is
not a live revocation oracle. Startup/loading costs, device attestation, token
reservation persistence, authenticated negative outcomes and cross-process
reconciliation remain host work, not claims inferred from a successful frame.

Focused checks (native execution must actually succeed before claiming a pass):

```sh
python3 -m unittest -v scripts.tests.test_hepta_retrieval_wire
cd codex-rs
just test --locked -p codex-hepta-infer-core --lib semantic_retrieval::tests
just test --locked -p codex-hepta-infer-worker-host --test model_worker_lifecycle
```

The Python suite has 23 tests, including exhaustive frame-prefix truncation,
Unicode/byte limits, scope/ordering drift, mutation, expiry, no retry and three
actual subprocess pre-model rejection cases. The Rust suites add nine native
wire conformance cases and twenty worker lifecycle cases using deterministic
fixtures, not weights. Execution of one language is not proof that the other
compiled or that real model/device/retention performance was measured.


## Durable semantic owner profile

`durable_control::semantic` extends the existing `DurableInferenceControl` file,
exclusive writer lock, fsync-before-publication and poisoned-handle recovery.
It introduces no new database, daemon, event bus, source writer or effect owner.
The journal distinguishes `semantic-retrieval-v1|` from native V1 and legacy
records. Existing record meanings and numeric Neuron feature contracts remain
unchanged. Old binaries do not understand the new journal prefix; deployment
must retain a compatible reader and must not reinterpret or discard records.

The transitions are:

```text
Reserved -> DispatchFenced -> Completed -> downstream acknowledgement
    |              |
    v              +-> unknown after lost reply, crash or cancellation
NotDispatched          (no automatic redispatch and no slot release)
```

A record binds full request bytes, operation/workspace/generation, principal,
reservation, worker generation, selected bundle, resource limits and host grant
identity. Before driver entry the same owner fsyncs a dispatch fence. Complete
validated reply bytes and optional observed memory are then fsynced before
publication. In-memory output, stdout completion or a digest alone is not the
stored result. Changed request or completion bytes conflict under the same ID.
Legacy/native entry points cannot reuse a semantic identity. Historical replay
returns the original record without loading or executing another model.

Cancellation while Reserved is a durable negative. Cancellation after the fence
retains unknown execution and its capacity obligation. A later valid result is
retained as an observation even after cancellation or resource overrun, but is
not thereby eligible for current consumption. The final consumer must recheck
source/artifact currentness, objective, generation, deadline and actual authority.
The separate acknowledgement binds the destination owner's receipt; the inference
owner never writes Neuron checkpoints, TaskFlow outboxes or the learning ledger.
This is an outbox-style pending-result surface, not an implemented cross-owner
acknowledgement worker or a crash-atomic transaction spanning owners.

Result and acknowledgement headroom are reserved before admission. Unrelated
journal appends cannot spend this semantic reservation. Completed unacknowledged
eligible results retain acknowledgement space. Missing memory measurement stays
unknown, not zero. A valid observed completion releases the compute slot even
when its result cannot be used. Malformed output and lost replies do not.

`InferenceWorker::run_semantic_retrieval_durable` is the new trusted composition
port. The older in-memory call remains a compatibility seam, not a durable
product path. Native integration of the bounded process transport, owner-authenticated observations,
shared physical quotas across execution profiles, external anti-rollback
frontier, source revocation and Agentd product integration remain separate work.
Caller-supplied digests are bindings, not signed credentials or model attestation.
An unknown operation without a trusted reconciliation result remains blocked;
changing request IDs, deleting the journal or swapping a backup is not recovery.

The Python worker's deadline budget begins before model loading. A monotonic
elapsed limit complements absolute wall expiry, and observed clock regression
poisons the local guard. It never retries. This guard cannot preempt a stuck
model or certify time across reboot; the host must enforce process termination.

Additional executable checks:

```sh
python3 -m unittest -v scripts.tests.test_hepta_laya_deadline
cd codex-rs
just test --locked -p codex-hepta-infer-core --lib durable_control::semantic::tests
just test --locked -p codex-hepta-infer-worker-host --test semantic_owner_recovery
just test --locked -p codex-hepta-infer-core --run-ignored only --no-capture --test-threads 1 --retries 0 -E 'test(semantic_journal_retained_history_curve)'
```

The explicit measurement writes and fsyncs 64/256/1024 complete records, reopens
the same journal, verifies every stored result/ack and verifies replay appends no
bytes. It reports actual append/reopen duration and journal growth. It does not
perform compaction or establish a long-term SLO. The maintenance workflow's old
`post_compaction_multi_generation_curve` filter matched zero tests in the source
candidate; the new filter selects this actual retained-history test without
weakening the minimum executed-test requirement.


## Bounded Linux leaf transport

`hepta_laya_process.run_process` executes one host-selected trusted leaf using
an exact HPTARQ request and HPTARS response. It does not select a model, grant
permissions, own a journal, or independently turn a request into a product call.
The existing inference owner must record its dispatch fence before invoking it.
All post-spawn failures remain unknown execution to that owner, not proof that
nothing ran. Transport cleanup does not settle an operation or release durable
quota. The final consumer still revalidates source, artifact, objective, scope
and deadline before use; a previously valid reply is not current authorization.

The command must name an absolute host-selected executable. The environment is
explicit and allowlisted, with offline flags set and no inherited credentials,
`PYTHONPATH` or loader injection. This is not package attestation: the host must
provision immutable reviewed code, weights, tokenizer and runtime. In particular,
a path check alone does not protect an executable from filesystem replacement.

The transport uses nonblocking stdin/stdout/stderr with bounded per-poll work,
closes stdin after the complete request, caps stdout at 64 KiB and stderr at
16 KiB, and retains only diagnostic byte count and digest in the observation.
Both wall-clock expiry/regression and monotonic elapsed time are checked from
before spawn. Cancellation, invalid replies, nonzero exit, floods and deadline
failure never select another backend or automatically repeat the request.

Linux `waitid(WNOWAIT)` observes leader exit without releasing its PID. Group
signalling precedes `wait4` reaping, so a reused PID/PGID is not signalled by the
normal cleanup sequence. Normal leader exit also triggers group cleanup to
prevent inherited pipe holders from stalling result collection. A bounded cleanup
that has not observed leader exit retains the child in `ProcessUnavailable`;
the caller must keep or transfer that handle to its existing supervisor and use
`reconcile_cleanup`, rather than dropping ownership. Failure to signal a group
remains incomplete cleanup even when the leader was reaped.

The function requires Linux and exclusive child-reaping ownership. A custom
SIGCHLD disposition is rejected; the host must also ensure no competing thread
or library reaps the same child. Recorded peak RSS and CPU are Linux `wait4`
leader observations, not aggregate descendant usage, a hard memory cap, GPU
measurements or independent device attestation. An untrusted child can escape
its process group, and a killed parent is not recovered by this Python object.
Cgroups/sandboxing, daemon-death containment, hard resource reservations and
cross-restart reconciliation remain existing runtime/supervisor responsibilities.
No production isolation or arbitrary executable-loading claim follows here.

The real-process suite uses synthetic model replies and no Laya weights:

```sh
python3 -m unittest -v scripts.tests.test_hepta_laya_process \
  scripts.tests.test_hepta_laya_deadline scripts.tests.test_hepta_retrieval_wire
python3 -m unittest -v scripts.tests.test_hepta_multiscale_ci
```

Its twenty process cases cover valid output and host resource observations,
stdin EOF, both output floods, redacted diagnostics, failed/truncated/rebound
replies, hanging and pipe-holding children, cancellation before/after spawn,
environment rejection, reaping order, retained handles, failed group signalling
and clock regression. These are OS-process/transport regressions, not real-model
quality, organ credit, browser-task or stateful topology evidence.

The existing maintenance workflow now pins the repository Rust toolchain,
installs the repository `just test`/nextest entry point, and independently runs
source-head and base-merge tests, strict lint and nonmutating formatting. It no
longer skips native execution merely because a tree comparison is equal. Minimum
observed test counts and exact commit/tree/parent identities remain mandatory;
the process and CI wiring suites also run in the multiscale protocol workflow.
A passing wiring test only establishes the tested configuration; actual workflow
execution is required to establish either candidate passed. No historical run or
queued check is promoted to current-head success.
