# Cognitive context preparation, delivery and publication fences

Status: source candidate. Exact-head and deterministic-merge execution, independent
review and target-host acceptance remain required. Activation and release remain false.

This supplement extends [TECHNICAL.md](TECHNICAL.md),
[FINAL_USE_CLOSURE.md](FINAL_USE_CLOSURE.md) and
[SELECTED_OWNER_CUT.md](SELECTED_OWNER_CUT.md). It does not replace their owner,
capability, byte-budget or physical-use boundaries.

## Existing owners, not another log

The memory owner continues to own SQLite facts, corrections, tombstones and recovery.
The existing learning `LedgerWriter` owns retrieval assignment preparation. The existing
`DurableInferenceControl` journal owns native dispatch, observed turn acceptance and
terminal observations. The read crate acquires no SQL connection, writer, durable
cache or execution capability. No journal schema or wire format is changed here.

`LedgerWriter::read_current_retrieval_assignment` resolves one exact ID/episode through
its existing replay-built active index. It requires a current independent witness,
rejects revoked/inactive rows and borrows the record without copying the whole history.
`CognitiveRetrievalLearningSink::with_prepared_assignment` retains that owner lock during
a synchronous, non-reentrant inspection. The historical explicit operation API binds
owner, generation, exact read RPC ID and exact serialized context digest. The caller
must already be an authorized host;
this local API does not authenticate arbitrary external callers or grant training access.

The native owner provides `cognitive_context_delivery`, an opaque borrow-scoped,
DENY_ALL view. It binds the complete independently supplied `NativeRequest`, the exact
owner-context digest, source admission and modern dispatch identity. A caller cannot
construct the view by deserializing or editing a row. The digest is an integrity binding,
not a signature, lease, current execution grant or authorization to resume a failed writer.

## Evidence states are not interchangeable

| State | Established observation | Not established |
|---|---|---|
| No context-bound dispatch | No matching evidence is available from this journal revision | No exposure; safe retry |
| `NotSent` | The live native owner durably recorded a proven pre-effect stop | Training consent or general retry permission |
| `RejectedBeforeTurn` | App Server received the request but refused turn admission | That context bytes were never transmitted or disclosed |
| `AcceptanceUnknown` | Dispatch exists; exact acceptance has not been observed | Zero exposure, failure, successful completion or permission to replay |
| `TurnAccepted` | The exact App Server turn was observed | Completion, reward, token usage or successful authorization at settlement |
| `TerminalObserved` | The same journal has exact correlated terminal evidence | Successful result or current authority, which retain their separate checks |

Cancellation does not erase observed acceptance. Reopening an unknown attempt does not
turn it into a negative exposure observation. Historical incomplete dispatch bindings
cannot be silently upgraded into modern delivery evidence. Debug output omits prompt,
memory text, model output and stop reasons.

`AppServerModelDriver::inspect_cognitive_assignment` joins the active witnessed preparation
to native evidence under those existing owners. It verifies this driver's principal,
generation and model, then hashes the exact learning event/chain/sequence/support and
native evidence into an authority-free inspection result. It neither sends a request
nor appends a second event. Both read-RPC identity and native-attempt identity must be
independently pinned by the trusted host: matching a content digest alone is insufficient.

Ordinary cognitive reads use the existing ledger owner to issue an independent
preparation identity under its writer lock. The identity binds the durable owner,
current chain frontier and checked next sequence. Connection-local RPC counters
are correlation IDs and cannot identify durable operations across fresh clients.
The explicit replay API retains its separate namespace and identity-conflict
semantics; its inspection lookup cannot match an ordinary preparation by accident.

This is an implemented local inspection surface, not automatic product learning ingestion.
The current normal read client does not return or persist the owner-issued preparation
identity alongside a native-attempt identity. That explicit product handoff, its revalidation
at training admission and actual physical-worker evidence remain required. An inspection
fixture is not a replacement for a real model/provider boundary test.

An ordinary read preparation is not an idempotent operation inferred from its RPC
number. An unknown response does not authorize replay or establish zero exposure.

## Publication after awaited dependencies

The ordinary Agentd read handler now performs its last selected-memory-owner revalidation
after awaited ranker validation, retrieval-context validation and learning append. It then
checks the local plan deadline before publishing, without another await in that handler.
The worker independently repeats final-use checks at the physical `TurnStart` boundary.
This remains an observation, not a lease preventing subsequent writes.

The historical `context_exposed` field remains byte-compatible. At the pre-return append
point it is a write-ahead preparation assertion, not a socket acknowledgment or proof that
a model saw the context. A preparation may remain after publication fails. Delivery learning
must correlate the actual native evidence; it must not treat missing/unknown joins as zero
exposure, or reinterpret server rejection as a proof of no transmission.

## Exact executable regression inventory

`scripts/cognitive_read_delivery_gates.py` supplies four mandatory gates to the existing
read-only `cognitive_read_full_evidence.py` runner, on both source and merge candidates:

- `native-delivery-tests`: seven native-journal identity, recovery, cancellation,
  terminality, pre-effect and server-refusal cases;
- `delivery-preparation-tests`: two real-ledger index, witness-lag and revocation cases;
- `publication-fence-tests`: a real SQLite frontier mutation while the last retrieval
  dependency is blocked, using a bounded barrier rather than timing sleeps;
- `delivery-join-tests`: external library integration across the existing learning and
  native owners, including exact read RPC/context/generation rejection and journal reopen.

Each gate requires the exact command, zero exit status, exact binary and fully qualified
nextest PASS rows, and the exact positive case count. Source names, echoed PASS text,
wrong binaries, missing cases or successful unrelated tests cannot satisfy these gates.
The ten Python parser regressions test evidence validation only; they do not execute Rust.
Rust compilation, formatting, strict lint and the eleven Rust cases require actual runner
receipts. A source-preparation commit is ordinary authoring, not qualification.

## Capacity, migration and release boundary

The selected-ID owner path already present in the source baseline avoids materializing
unselected ancestry, but global owner counter/head metadata work is not eliminated. A
transactionally maintained owner root requires a separately reviewed existing-owner
schema/recovery migration and measurements; no authorization cache is introduced here.

No consumer is promoted by these inspection APIs. `compact.engine` product composition,
`context.compiler` verified V2 ingress, the other consumers' distinct lifecycle/host gaps,
automatic delivery-learning composition, exact-source/merge checks, target-host resource
qualification, independent review, canary and release remain separate work. Existing
consumer registries and all activation/acceptance/production flags remain unchanged.
