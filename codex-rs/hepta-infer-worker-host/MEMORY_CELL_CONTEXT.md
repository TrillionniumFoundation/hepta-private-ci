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

## Address worker response framing

The host serializes worker exchanges and checks for buffered or readable pipe
output both after a complete response and before writing the next request.
Unexpected output, malformed frames, and response bindings that differ from
the current complete request discard the child. A later request must start a
fresh pinned process after such a failure; stale bytes are never reused as a
new request's answer.

The frozen JSON-lines protocol has no end-of-response acknowledgement beyond
the newline. Returning a complete valid frame cannot prove that the process
will never write more bytes in the future. The host therefore also validates
the query, full request digest, registry cut and model for every subsequent
response. The transport tests separate an immediately available atomic double
frame from a delayed old response emitted after the next request arrives.
Neither a valid address frame nor transport ordering grants source access or
execution authority; the owner and final-use checks remain required.

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

## Calendar dates and native timestamps

Native `MemoryCellRecordV1.effective_at` and `MemoryRequestV1.at/since` are **Unix
seconds**, never `YYYYMMDD` integers or scope-specific logical clocks. The host
transport profile `hepta.memory.host-utc-midnight-time-view.v1` bridges literal
dates to the frozen addressing worker, whose date check uses `YYYYMMDD` slots.

Only requests containing a literal `YYYY-MM-DD` or `YYYYMMDD` date get a private
worker time view. Owner-listed canonical names and aliases are masked on a
normalized recognition copy first, so names such as `sensor20250201` do not
become cutoffs. Neither the native text nor any non-time request field changes.
The host binds the original complete request separately from the worker view,
verifies the exact returned view, then executes with the original Unix seconds.

For History, the native `at` must equal that date's UTC midnight. For Change,
the native `since` must equal it. An instant elsewhere on the same day, a
conflicting day, an invalid date or multiple distinct date cutoffs are rejected.
Alias masking uses NFKC and lowercase rather than full Unicode casefold; a
missed date-bearing alias can conservatively reject a non-temporal query.
Unmentioned aliases never block a literal cutoff merely by sharing its date.
NFKC-compatible date digits are
recognized; remaining non-ASCII decimal date forms are outside this profile.
No-date requests retain their original time slots and wire binding.

For example, `2025-02-01` requires native cutoff `1738368000`; `20250201` appears
only in the private worker view. Providing `20250201` as the native cutoff is
rejected against that literal date, rather than reading a record in 1970.
This deterministic adapter is outside the frozen classifier/model policy.
Classifier held evaluation does not establish the adapter's correctness; its
separate real-worker/SQLite/native temporal receipts do.
