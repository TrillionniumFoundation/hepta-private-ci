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

Still required before a product claim: a concrete supervised local driver joined
to the existing verified inference execution boundary and actual Agentd/Neuron
consumer; authenticated current source/artifact validation; OS/device resource
and terminal observation; cross-process durable resource ownership; end-to-end
TaskFlow/Neuron result handoff; and independent equal-budget retrieval outcomes.
Local parameter training, organ credit, controlled computer actions and stateful
organ surgery are not established by binary predictions or these source tests.
