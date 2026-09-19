# inference.worker production readiness and runbook

This runbook answers one operational question: **what must be true before
`inference.worker` may be called production-ready for a named deployment?**
It complements [TECHNICAL.md](./TECHNICAL.md), the
[module execution dossier](../../../qualification/module-execution-dossiers/detail/inference.worker.md)
and [Lane B native host](../../readiness/LANE_B_NATIVE_HOST.md). It does not
replace independent acceptance, activation or release authority.

## 1. Current execution profiles

### Hosted App Server

`hepta-infer-worker --profile native-app-server` executes one request through
the exact owning Agent/App Server generation. Admission and provider dispatch
identity are persisted by `DurableInferenceControl`.

Each request receives a **dedicated durable App Server thread**. The stable
worker request id is sent as `client_user_message_id`. If the worker dies after
durable dispatch but before terminal settlement, restart performs
`thread/read(includeTurns=true)` against that exact thread. A known turn id
must match exactly. If the turn id was lost with the `turn/start` response, the
worker accepts only a persisted turn whose user item carries the exact original
`client_user_message_id`. It never submits a replacement turn.

A terminal persisted turn may therefore reconcile to `Completed`, `Failed`
or `Interrupted`. If the durable thread cannot be read, the binding is
ambiguous, or the turn is still in progress at the reconciliation deadline, the
request remains `Indeterminate`. Missing provider token usage remains
`None`; it is never converted to zero.

Because reconciliation requires history, these dedicated threads are not
ephemeral. They live in the owning Agent's private App Server store and must
follow that principal's retention and deletion policy.

### Local process

`LocalProcessModelDriver` is the production adapter for a separately selected
local runtime process. Before process creation it requires regular,
non-symlink, absolute files and checks SHA-256 for:

- weights;
- tokenizer;
- preprocessor;
- quantization descriptor/artifact;
- license;
- SBOM;
- runtime executable;
- device descriptor.

The model manifest and trusted process-local resource grant must name the same
device digest. The worker enforces aggregate loaded-model memory against the
grant instead of checking only one model at a time.

The runtime inherits no ambient environment. Only the explicitly configured
runtime environment is supplied. A strict bounded
`hepta.local-model-runtime.v1` JSON-lines protocol performs `load`,
`infer` and `unload`. The load acknowledgement must echo the exact artifact
binding, OS process id, handle id and a non-zero memory reservation within the
remaining grant. The inference response is bound to request and handle id. The
worker receives raw output and computes the output SHA-256 itself.

This adapter makes a real runtime process invocation possible; it does **not**
by itself prove that a vendor runtime physically honored a GPU reservation.
That proof belongs to target-host qualification below.

## 2. ResourceGrant trust boundary

`model_worker::ResourceGrant` is a **trusted process-local capability**, not a
wire credential and not a self-authenticating token.

The worker locally rechecks expiry, revoked state, authority epoch presence,
worker generation, model/request/memory ceilings, semantic digest shape and
device binding. It does not verify a signature or query the authority service
inside `model_worker.rs`.

Therefore a caller that receives grant material over IPC/network must first
authenticate the producer, verify the external credential/revocation/epoch
according to the registered `kernel.authority` contract, and only then
construct `ResourceGrant`. Moving this type across a process boundary without
that adapter is a security regression and blocks activation.

## 3. Isolation guarantees

The module currently guarantees these source-level isolation properties:

- exact Agent id and generation fencing for hosted App Server execution;
- exact App Server home check before hosted execution/reconciliation;
- one dedicated hosted thread per request and no replay after possible dispatch;
- exact local artifact digests and exact runtime executable digest;
- cleared inherited environment for the local runtime process;
- model/device digest binding and aggregate worker memory ceiling;
- bounded payload, output, protocol messages, token limits, model count and
  active request count;
- cancellation/authority loss cannot be rewritten into successful authority;
- the local driver kills resident children on protocol failure/unload/drop.

The module does **not** claim the following unless the deployment evidence
explicitly proves them:

- Linux namespace/container isolation;
- cgroup v2 CPU/memory enforcement;
- seccomp or Landlock policy;
- GPU MIG partitioning, device ACLs or vendor-driver memory hard limits;
- network egress filtering;
- filesystem mount isolation;
- protection from a malicious runtime binary that already matches an approved
  digest;
- VM/TEE isolation.

Those are host/launcher responsibilities. “Isolated inference worker” must not
be interpreted as “security sandbox certified by this Rust crate”.

## 4. Runtime protocol requirements

A selected local runtime must implement one long-lived JSONL session.

### Load

The worker sends the exact artifact paths/digests, model id, maximum tokens,
grant id, authority epoch, worker generation, grant semantic digest and
remaining memory ceiling. The runtime must return
`operation=load_result`, the exact model/artifact binding, its actual OS PID,
a stable handle id and non-zero reserved-memory bytes.

A mismatch fails load and terminates the child.

### Infer

The worker sends the stable request id, handle id, model id, actual bounded
payload and maximum token count. The response must bind the same request and
handle and report terminality, success/failure, raw output, consumed token count
and observed memory.

The worker, not the runtime, hashes the returned output. A non-terminal response
is `Indeterminate`; terminal success without output is rejected.

### Unload

The runtime must acknowledge the exact handle. The worker then terminates/waits
the resident child so an unload does not leave a process behind.

Runtime protocol I/O is bounded and deadline-controlled. A timeout, malformed
JSON, unknown field, identity mismatch or broken pipe is a driver failure and
the child is terminated.

## 5. Provider crash/restart reconciliation

The durable journal is the local authority for whether provider dispatch may
have occurred. Recovery follows this order:

1. reopen and lock the same private inference journal;
2. verify the duplicate request has identical semantics;
3. if a terminal observation already exists, return it without provider I/O;
4. otherwise reconnect to the exact Agent id/generation;
5. read the exact durable App Server thread;
6. use the durable turn id when known, otherwise require the exact persisted
   `client_user_message_id`;
7. if a matching terminal turn exists, settle that observed terminal fact;
8. if terminality cannot be proved, retain `Indeterminate` and do not replay.

Token usage is a separate truth. `thread/read` does not currently supply an
authoritative per-turn usage record, so a recovered terminal turn may still have
unknown usage. Production economic settlement must reconcile that through a
trusted provider/billing observation before treating usage as complete.

## 6. Required target-host qualification

Repository unit/CI tests are necessary but insufficient. Before activation for
a concrete runtime/device tuple, collect immutable evidence for all applicable
cases:

| Gate | Required observation |
| --- | --- |
| Artifact identity | Binary, weights, tokenizer, preprocessor, quantization, license, SBOM and device digests equal the selected manifest |
| CPU load/unload | Repeated load/infer/unload produces correct output and no monotonic RSS/FD leak |
| GPU/accelerator load | Device identity is the granted device; measured device memory stays within the grant |
| OOM | Host/runtime refuses or fails boundedly; another principal/device allocation is not corrupted |
| Concurrency | Maximum admitted concurrent requests respect request/token/memory ceilings |
| Cancellation | Cancellation reaches runtime; terminality is observed or remains indeterminate; resources drain |
| Driver crash | Runtime child death is detected; no fabricated success or zero usage |
| Worker crash | Hosted dispatched request reconciles without a second turn |
| App Server restart | Durable thread can be read/reconciled or stays indeterminate; no replay |
| Device reset | Reset produces bounded failure/fencing and no stale success |
| Soak | Repeated load/run/unload demonstrates stable memory, descriptors and device allocation |
| Sandbox | cgroup/namespace/seccomp/device/network/filesystem policy is measured on the target launcher |

Store the runtime version, kernel/driver versions, device identity, model tuple,
host image digest, test command, exact source SHA/tree SHA, raw logs and
measurement artifacts together. A test name or screenshot is not sufficient.

## 7. Exact-revision source qualification

The workflow
`.github/workflows/inference-worker-qualification.yml` runs for worker/core
and module-document changes. It checks out the exact PR head or pushed SHA,
verifies `git rev-parse HEAD`, runs the focused inference-control/worker tests
and strict worker clippy, and uploads:

- `tests.json` command record;
- `clippy.json` command record;
- `receipt.json` containing exact source SHA, tree SHA and SHA-256 digests of
  those command records.

The receipt explicitly records that hardware qualification, independent
acceptance, activation and release are not granted by that workflow.

For a release candidate, the accepted receipt must reference the **exact
candidate SHA**. Any source change after that receipt invalidates it. A merge
candidate needs its own exact synthetic-merge receipt where the release process
requires merged-tree evidence.

## 8. Product composition gate

Source-complete worker code is not product composition. Activation requires a
named production caller that proves this chain:

`authenticated authority -> verified reservation/lease -> worker admission ->
exact execution profile -> durable terminal/indeterminate observation ->
inference.control settlement -> product consumer`.

The production caller must not construct `ResourceGrant` directly from
untrusted JSON and must not create a second durable inference writer. The
canonical `DurableInferenceControl` owner remains the single local journal
writer for hosted dispatch facts.

Until that caller and its authority adapter are named and tested,
`productCallerState=not_composed` and
`productionWriterState=not_established` remain correct.

## 9. Operational signals and SLO inputs

At minimum export or capture counters/gauges for:

- admitted, rejected, running and indeterminate requests;
- reconciliation attempts/success/failure/timeout;
- provider terminal status and unknown-usage count;
- loaded model count and aggregate reserved/observed memory;
- local runtime starts, crashes, protocol errors and unload failures;
- cancellation latency;
- model load latency, time-to-first-terminal-output and total inference latency;
- worker generation and selected model/runtime/device digests.

Do not define production SLO thresholds from this repository alone. Thresholds
must come from the selected host/runtime capacity profile and measured
qualification data.

## 10. Failure injection

For each release-candidate tuple, inject failure at least at:

- before local runtime spawn;
- after spawn before load acknowledgement;
- after load acknowledgement before worker model-map commit;
- during inference input write;
- during inference output read;
- during cancellation;
- during unload;
- after hosted journal dispatch before `turn/start`;
- after provider accepted `turn/start` before response;
- after terminal provider state before journal settlement;
- during Agent generation fencing;
- during App Server restart.

The oracle is never “command returned”. It is the combination of journal state,
provider/runtime terminal evidence, resource release, exact identity binding and
absence of duplicate execution.

## 11. Rollback

Hosted rollback must preserve the journal and App Server private thread store.
Never delete either to make an indeterminate request appear retryable. A binary
rollback is allowed only if the predecessor understands every persisted record
version it may open.

Local-runtime rollback drains active requests, unloads the current model,
terminates the resident runtime child, then starts a new worker generation with
the predecessor artifact tuple and a newly verified grant. Never mix old
tokenizer/preprocessor/runtime/device material with new weights under one model
identity.

## 12. Activation checklist

A deployment may advance only when all of the following are independently true:

- repository-focused tests/lint pass on the exact release-candidate SHA;
- the exact receipt artifact is retained and verifiable;
- the named caller/authority adapter is composed;
- the selected runtime/model/device tuple has target-host qualification;
- OS/device isolation guarantees are documented with evidence, not inferred
  from the module name;
- provider crash/restart reconciliation is exercised on the selected App Server
  persistence profile;
- unknown token usage has an economic reconciliation policy;
- alerting and capacity thresholds come from measured target data;
- rollback was rehearsed without journal/history deletion;
- independent acceptance, activation and release decisions are recorded by
  their owning processes.

If any item is missing, keep production/activation/release claims false.
