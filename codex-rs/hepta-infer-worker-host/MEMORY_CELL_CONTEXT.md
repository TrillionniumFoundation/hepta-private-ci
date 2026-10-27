# Typed memory in a hosted model turn

`AppServerModelDriver::with_memory_request(MemoryRequestV1)` attaches one typed
memory request to the existing hosted inference path. The command-line entry
point exposes the same path through `--memory-request-file ABSOLUTE_JSON`. This
option adds to the normal `native-app-server` arguments and does not replace the
independent `--final-use-authority-config` requirement described in
`FINAL_USE_AUTHORITY_PORT.md`.

The file contains the strict `hepta.memory.request.v1` schema: `query_id`,
`scope`, `entity`, `text`, `at`, `since`, `max_hops`, and `max_cells`. Obtain the
canonical scope and entity names from the authorized owner. The caller cannot
provide an operation, model selection, source registry, expected answer, or
authority claim. The daemon's configured addressing model resolves the
operation. The file is bounded to 65,536 bytes before strict decoding.

## Configure the owner before invoking the worker

The owning Agentd must already have a real source store, independently selected
memory release, and pinned address worker attached through the explicit
embedding API. A typical composition ends with:

```rust,ignore
let resolver = Arc::new(MemoryCellAddressWorkerV1::start(address_config).await?);
let cells = AgentdMemoryCellRuntimeV1::new(
    config.identity().agent_id.clone(),
    config.identity().spawn_generation,
    scope,
    selected_release_host,
    resolver,
)?;
config = config.with_memory_cells(Arc::new(cells))?;
```

`selected_release_host` must use the real artifact owner service and its
configured selector verifier. Publication, independent selection, current
registry validation, and withdrawal admission precede loading. Address worker
configuration fixes the interpreter, model digest, encoder directory and the
complete first-party import closure. Neither the query file nor the trainer
can create these authorities.

Agentd's standalone `main` currently has **no memory release bootstrap flag**.
It does not infer a release, construct a selector, or load private signing keys
from a query. Use the explicit configured embedding. An unconfigured owner
rejects a memory read; snapshot export is separately available for authorized
training data acquisition.

## Evidence, final use, and failure behavior

After preparatory thread creation, the worker acquires a real typed owner read.
`context.compiler` realizes successful results as `UntrustedEvidence`. The
compact model-visible JSON includes the entity, operation, prediction kind,
complete value, release generation, bundle digest, and evidence digest. It has
a hard limit of **768 UTF-8 bytes**. Oversized values fail without truncation.
The combined old cognitive context and new memory attachment also obey the
existing bounded attachment limit. No exact tokenizer count is claimed.

The host retains the full readout, source IDs, cell digests, request binding and
version in the evidence digest. Only elapsed time is normalized, because it
changes on a new read. Semantic/procedural outputs remain `model_prediction`;
composed arithmetic remains `mixed`. None becomes a trusted instruction or
execution grant. The existing `AdditionalContextUserFragment` carries this
content to the model as untrusted user context.

The durable inference admission binds the entire typed request. The physical
turn payload, including the evidence, remains covered by the existing signed
final-use binding. After durable dispatch preparation and immediately before
physical `turn/start`, the worker performs a second real owner read and compares
the full evidence binding. A source correction, withdrawal, selected-version
change, abstention, unavailable owner, or mismatched value stops the operation
through the existing durable abort-before-effect path. There is no silent
fallback to an answer without the requested memory evidence.

The two reads incur actual owner and native-inference work. They do not train
parameters or issue grants. Unknown outcomes after a physical dispatch retain
the existing reconcile-only behavior and are never automatically replayed.
