# Semantic retrieval through the existing inference owner

This is a component integration guide, not another runtime, authority, learning
owner or global plan. `experimental-local-model` still gates the synchronous
native model worker; default production binaries do not gain a local execution
path from these sources. Ordinary reviewed source changes need no deployment
approval. Real execution, protected data use and promotion retain their own gates.

## Native owner and exact operation identity

`InferenceWorker::run_semantic_retrieval_durable` in `src/semantic_worker.rs`
uses `DurableInferenceControl`'s existing file, exclusive writer lock, fsync,
capacity and poison state. It does not create another request database.
`SemanticRetrievalCallV2` binds the full `SemanticRetrievalRequestV1`, principal,
reservation, worker generation and exact model/resident/KV/transient tuple.
The new critical `ReserveResourcesV2` event preserves the meaning of old V1
journal events; old decoders reject the new variant. Even a different resource
split with an equal total is a conflict, not an idempotent retry.

The order is: verify immutable input and current grant; reserve workspace;
persist admission and dispatch fence; enter the selected driver; validate and
persist the entire result; release only terminally observed resources. The
resident reservation is held from model loading. Error, panic, malformed reply
or missing terminal observation retains the dispatch fence and quarantines
entered workspace. A returned timeout/cancel request is not proof of no work.
A complete over-budget or unmeasured result remains an observation but cannot
be delivered as an eligible result. Capacity is not automatically reset.

Reopen returns original completed, not-dispatched or unknown records without a
loaded model or a new inference. A historical lookup after expiry is not current
permission to use the result. Only `Reserved` can become a new dispatch fence;
its original worker/generation/grant must still match. `DispatchFenced` cannot
be reassigned or replayed merely because another worker is available. Downstream
owner acknowledgements remain explicit and do not let this owner write Neuron,
TaskFlow or the learning ledger. Source/artifact revocation and final-use checks
must be performed again at consumption.

## Binary model data, not machine code

`python/hepta_retrieval_wire.py` and the native core codec implement the existing
HPTARQ/HPTARS V1 profile. Integers are big endian; strings and frames are bounded;
source text must match its SHA-256. The original input, including source order,
revisions, objective, workspace, generation, model bundle and absolute deadline,
is bound by the request digest. Output probabilities are ordered as abstain then
ASCII-sorted source IDs. No field is an executable instruction or capability.

`python/laya_binary.py` wraps the existing pinned `RetrievalDriver`. It supports
at most eight sources, aliases source IDs without losing their original binding,
rejects truncation before inference, conserves a wall/monotonic deadline captured
before model loading and keeps library messages away from binary stdout.
The CLI accepts one packet on stdin and returns one packet on stdout. A host
must bound pipe I/O, process lifetime, OS resources and cancellation; this leaf
is not that supervising host. No automatic retry or model fallback is admitted.

SDK-rounded prediction mass is normalized by a versioned exact largest-remainder
conversion to parts per million, with deterministic tie order. Raw probabilities
and conversion identity remain in the diagnostic observation. Prediction scores
are not behavior propensities. Token usage comes from the actual SDK response;
missing, boolean, out-of-range or incompatible values fail instead of becoming
zero cost. The raw binary reply deliberately contains no fabricated memory or
device attestation. A trusted native driver still has to supply those observations.

## Bounded leaf-process transport

`python/laya_process.py` supervises the existing one-shot binary leaf without
creating another inference owner, model-selection service or command language.
The parent delivers one bounded request, drains stdout and stderr concurrently,
and accepts a full request-bound reply only after observing zero exit status.
The original `OwnerDeadline` bounds loading and inference; timeout, cancellation,
pipe overflow, invalid output or nonzero exit never authorizes another attempt.
Diagnostics retain bounded byte counts and digests, not source text.

The POSIX profile requires non-reaping child observation (`waitid`/`WNOWAIT`).
It signals the process group before reaping its leader, including when a child
retains a pipe after the leader exits. Unsupported platforms and an installed
external child reaper reject before spawn. Failed direct-child cleanup retains
the unresolved handle in `ProcessFailure`; it is not reported as successful
termination. If group signalling fails, the leader is deliberately not reaped:
`ProcessFailure` retains its handle and `reconcile_cleanup` retries only cleanup,
not the original request. Reconciliation rechecks exclusive child ownership before
signalling, serializes concurrent cleanup attempts and becomes idempotent after
reaping. An external reaper loses that permission; stale numeric group IDs are
never used to compensate. A typed failure retains unresolved cleanup even when
process interruption caused the failure. Completing cleanup does not retroactively
publish a reply, declare task success or release unmeasured device resources.
Detected child-ownership loss is a permanent per-handle latch: a later successful
`waitid` cannot renew a numeric PID after an external reaper collected it. Cleanup
observations exposed by `ProcessFailure` are scalar copies, not mutable owner
state. Bounded cleanup stage/errno diagnostics distinguish observation, signalling
and reap failures without retaining exception text or source content. The
exclusive-reaper precondition remains; this is not an atomic defense against a
concurrent foreign reaper or a crash-durable cross-process ownership protocol.
Process-group cleanup is not a sandbox or proof that escaped
children stopped. Device memory, full descendant exit and task success remain
explicitly unknown. Callers must not infer workspace release from these fields.

The selected interpreter and immutable checkpoint paths are host inputs, never
model output. The leaf rechecks checkpoint pins. The environment excludes common
credential and loader/import overrides; this is not filesystem or network
isolation. OS resource control, protected source revalidation and durable
cross-process ownership remain responsibilities of the existing native host.

The existing smoke workflow runs source-head and fixed-base merge lanes on
macOS and Linux. Both lanes require a fourth, distinct model request through
this transport. `process-observation.json` binds both binary frames, token usage
and observed direct-child termination; it deliberately does not claim a
production caller, device attestation or held-out efficacy. Skipped contracts
are a qualification failure on these supported targets. A configured workflow
is not evidence that its current exact-source and merge jobs succeeded.

## Verification and remaining product work

Run the ordinary component checks from the repository root:

```sh
python3 -m unittest discover -v -s codex-rs/hepta-infer-worker-host/python -p 'test_*.py'
cd codex-rs
just test --locked --lib -p codex-hepta-infer-core -p codex-hepta-infer-worker-host --retries 0
cargo fmt -p codex-hepta-infer-core -p codex-hepta-infer-worker-host -- --check
cargo clippy --locked -p codex-hepta-infer-core -p codex-hepta-infer-worker-host --all-targets -- -D warnings
cargo check --locked -p codex-hepta-infer-worker-host --all-targets --features experimental-local-model
```

Python tests use synthetic predictors and real rejection subprocesses. Native
worker tests use real durable files and counted synthetic drivers, including
reopen, cancellation, resource drift, unknown outcomes and panic. Neither suite
alone establishes real model execution. The existing Laya CI smoke separately
loads fixed real weights, performs two JSON and one binary forward passes,
checks observed token usage and exact source/merge identities, and retains
source/environment/model observations. Its two-source synthetic task is not a
held-out retrieval benchmark. Read `python/SMOKE.md` for the fixed preparation.

Still required before a product claim: the concrete native local driver joined
to the existing verified inference execution boundary and actual Agentd/Neuron
consumer; authenticated current source/artifact validation; OS/device resource
and terminal observation; cross-process durable resource ownership; end-to-end
TaskFlow/Neuron result handoff; and independent equal-budget retrieval outcomes.
Local parameter training, organ credit, controlled computer actions and stateful
organ surgery are not established by binary predictions or these source tests.

### Portable non-reaping observation

The existing process owner now uses `laya_wait.observe_owned_exit` rather than
requiring CPython to expose `os.waitid` on macOS. On supported 64-bit Darwin,
the helper uses the public `libSystem` waitid/siginfo ABI with
`waitid(P_PID, pid, ..., WEXITED | WNOHANG | WNOWAIT)`; other
supported POSIX interpreters retain native `os.waitid`. It checks the ABI before
writing through a native pointer, zero-initializes the result, checks complete
child identity and terminal reason, and propagates errors without retries.
`ECHILD` remains permanent ownership loss. Nothing here reaps, signals, grants
resource settlement, proves descendant containment or permits inference retry.

Both Linux and macOS qualification lanes execute the complete process suite and
the actual supervised pinned-model exchange. A skipped contract test fails this
qualification; missing `os.waitid` is no longer a reason to skip the transport.
The injected Darwin ABI tests are not native Darwin evidence: only the actual
macOS source/merge job results establish that runtime observation. The existing
owner journal, resident-model integration and protected final consumer remain
separate product obligations.
