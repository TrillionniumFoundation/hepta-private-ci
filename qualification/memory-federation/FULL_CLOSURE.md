# memory.federation full-closure qualification

This qualification package keeps source, execution, independent acceptance and
release authority separate. It covers the in-process V2 checked adapter, bounded
Agentd product composition, authenticated wire protocol and the transport-neutral
durable host boundary without claiming that a real cross-host product is active.

<!-- BEGIN GENERATED MEMORY FEDERATION STATUS -->
## Generated capability status

This block is generated from `CAPABILITY_STATE.json`. It separates source,
execution, independent acceptance, activation, promotion, and release; prose
outside this block cannot widen those claims.

| Capability or gate | Canonical state |
| --- | --- |
| In-process V2 engine | `source_hardened_candidate_pending_execution` |
| Agentd product caller | `composed_candidate_pending_execution` |
| Discovery/read budgeting | `half_budget_reserved_for_admitted_reads` |
| Authenticated wire | `source_hardened_protocol_candidate_pending_execution` |
| Verified-frame boundary | `private_fields_read_only_accessors` |
| Replay admission | `bounded_fail_closed_monotonic_clock_per_credential_partition` |
| Cross-host product transport | `transport_neutral_host_boundary_source_candidate_not_agentd_composed` |
| Durable attempt/replay recovery | `host_store_snapshot_source_candidate_pending_selected_backend` |
| Exact-head execution | `pending_current_head_qualification` |
| Deterministic merge execution | `pending_current_base_merge_qualification` |
| Product execution proved | `false` |
| Independent acceptance | `false` |
| Activation | `false` |
| Promotion | `false` |
| Release | `false` |

<!-- END GENERATED MEMORY FEDERATION STATUS -->

## 1. Claim boundary

Four claims remain independent:

1. **source candidate complete** — the one-peer V2 engine, bounded in-process
   caller, host-governed limits, compatibility isolation, authenticated wire and
   durable host boundary exist in source;
2. **product execution proved** — the exact source head and deterministic merge
   with the then-current base both pass the retained matrix under identical
   command/source contracts;
3. **independent acceptance** — an independent semantic/security reviewer and
   selected-host operator accept the evidence;
4. **activation and release** — canary, promotion and release authorities select
   the product explicitly.

`productExecutionProved` remains false until successful exact-head and merge
receipts are reviewed and bound by a later metadata-only status change. Logical
host tests, protocol source or a green individual command never imply real-host
acceptance, activation or release.

## 2. In-process product closure

The product runtime owns bounded owner discovery, admitted-peer limits, discovery
and attempt concurrency, final-use revalidation and one global request horizon.
Discovery can consume at most one half of that horizon. Completed discoveries are
retained; unfinished owners become typed failed coverage. The remaining horizon
is reserved for reads already eligible after deterministic sorting and
deduplication.

This explicitly closes the counterexample:

```text
fast valid owner completes discovery
+ second owner remains permanently pending
=> fast owner still receives read/authority budget and may contribute evidence
```

The split does not make completion order authoritative and does not extend the
total budget.

Final revalidation groups exact owner/capability bindings and executes groups
with bounded concurrency. Retrieval may degrade per source before proposal
construction, with coverage recording omitted, unavailable, stale, partial and
truncated sources. Once exact federated bytes are prepared, the physical-send
final-use guard is all-or-nothing: any stale or unavailable binding discards the
whole prepared federated proposal rather than silently changing approved bytes.

A nonempty result below the retrieval ceiling may be complete. Reaching the
ceiling is conservatively partial. Empty remains empty; `Partial + []` remains
partial. Post-merge item truncation is separate.

V1 is absent from the default surface and exists only behind `legacy-v1` and its
dedicated compatibility lane.

## 3. Authenticated wire and host closure in source

The standalone wire crate provides:

- registered canonical query/response/cancel/cancel-ack encoding;
- directional credential enrollment, strict rotation, expiry and revocation;
- HMAC-SHA-256 frames over peer identities, generation, times, nonce and message;
- OS CSPRNG nonces and bounded frame lifetime;
- private, immutable verified-frame result type;
- globally bounded, per-credential replay admission with host-time watermark;
- authenticated chained owner-cut witnesses;
- typed cancellation acknowledgement;
- a transport-neutral host boundary requiring secure-channel peer identity;
- durable replay and attempt snapshots with global/per-peer isolation;
- two-stage query admission, cancel and terminal persistence.

The host exposes no memory writer. Verified replay is persisted before a query is
admitted; pending intent is persisted before the read handler; cancellation or
terminal state is persisted before acknowledgement/response bytes. Cancellation
persisted first fences late completion, including after restart.

The host crate is deliberately not an Agentd network member. Its recovery store
is injected; the included in-memory store is a fault-test fixture. No socket,
TLS implementation, certificate authority, production secret store or durable
backend is selected by this work package.

## 4. Adversarial acceptance cases

The qualification matrix emphasizes counterexamples:

| Scenario | Required property |
| --- | --- |
| Fast valid owner plus permanently pending owner | Fast source retains read budget and may contribute evidence |
| External construction or mutation of verified frame | Compile fails; only successful verification constructs the value |
| Expiry cleanup followed by wall-clock rollback and old frame replay | Admission still fails closed |
| One credential or peer fills its partition | Other credentials/peers retain bounded capacity |
| Cancel persists before terminal, then host restarts | Late completion remains rejected and emits no success response |
| Secure transport says peer C while frame says peer A | Frame is rejected before handler admission |
| Handler returns an owner cut for another host or future time | Completion is rejected |
| Source, command list, SHA or tree changes during qualification | Final execution guard rejects the run |
| Exact head passes but deterministic current-base merge fails | `productExecutionProved` remains false |

Normal happy paths remain covered, but they cannot substitute for these cases.

## 5. Read-only execution guard

`scripts/memory_federation_execution_guard.py` captures before compilation:

- exact candidate SHA;
- exact candidate tree;
- complete qualified source-file manifest digest and count;
- qualified-path inventory digest;
- complete declared command manifest digest and count.

After all format, compile, test and lint commands, it recomputes the same object
and requires exact equality. It also requires a clean tracked checkout. Its state
file is outside the repository and has its own SHA-256 sidecar. Self-test proves
that a command-contract change is rejected even when the sidecar is recomputed.

This guard does not replace the final attestation. It prevents a long-running
matrix from inheriting an input identity that ceased to be true while commands
were executing.

## 6. Scoped implementation-map verification

The module lane calls
`scripts/verify_memory_federation_implementation.py`. That wrapper dynamically
loads the canonical repository verifier and narrows only the `MODULES.json` view
to `memory.federation`. All canonical schema, source-object, source-observation,
claim, product-caller and clean-checkout logic remains unchanged.

The repository-wide verifier remains required for global convergence. The module
lane no longer fails because a different module's historical observation is not
an ancestor of this deterministic merge candidate.

## 7. Canonical status source

`docs/modules/memory.federation/CAPABILITY_STATE.json` is the single status
source for:

- the generated blocks in `TECHNICAL.md`, `V2_HARDENING.md`, `WIRE_V1.md` and this
  document;
- the implementation-map claim boundary;
- the wire-map claim boundary and external gates;
- the status verifier;
- the copied and hashed capability-state evidence in every qualification payload.

`scripts/verify_memory_federation_status.py verify` rejects any divergent prose
block, map claim, external gate or missing receipt binding. Detailed hand-written
sections remain useful, but they cannot promote a status.

## 8. Qualification command matrix

`.github/workflows/memory-federation-v2-final-verify.yml` runs the same script on
both exact head and deterministic current-base merge candidates. The script runs:

- Python syntax, guard self-test, guard capture and status verification;
- module-scoped canonical implementation-map verification;
- focused Rust formatting;
- V2 library tests;
- explicit `legacy-v1` tests;
- product runtime, legacy-federation and Memory-extension tests;
- Agentd/App Server compile checks;
- strict Clippy over core product packages;
- standalone wire formatting and metadata resolution;
- wire library tests;
- wire doctests, including external compile-fail verified-frame contracts;
- standalone wire strict Clippy;
- Git diff and clean tracked-checkout checks;
- final execution-guard verification.

The command contract is hashed in the guard and retained in the attestation.

## 9. Qualification payload and envelope

A lane emits a self-digesting payload that binds:

- source/base/tested/merge identities and trees;
- lane and conclusion;
- toolchain;
- exact source-file manifest;
- exact command manifest;
- claim boundary;
- referenced evidence digests;
- canonical capability-state copy and digest;
- resolved standalone wire `Cargo.lock` when generated.

A second envelope binds that payload to GitHub's uploaded-artifact ID, name and
SHA-256 digest. The verifier recomputes checkout identity, source manifest,
command manifest, capability state and referenced evidence. A failure payload is
diagnostic only.

The generated wire lockfile is retained as review evidence. A later source commit
must promote the accepted lockfile to a tracked input before claiming locked,
reproducible production qualification.

## 10. Capacity and performance evidence

Source now supplies global and per-credential/per-peer ceilings. Qualification
proves finite behavior and typed fail-closed rejection, including isolation
between peers.

It does not yet prove production performance. The selected host qualification
must measure:

- owner discovery and read latency under slow-peer mixtures;
- replay-cache cleanup and partition saturation;
- durable snapshot encode/store latency;
- rejection rate under overload;
- cancellation tail and late-terminal rate;
- restart recovery time and restored live-entry volume;
- network backpressure and partition behavior;
- CPU, memory and I/O ceilings at target concurrency.

Measurements must bind the selected transport, recovery backend, credential
provider, host profile and exact build.

## 11. External cross-host gates

Before product network activation, all of the following remain mandatory:

- a selected mutually authenticated transport whose authenticated peer identity
  is passed to and matched by the host boundary;
- secure credential enrollment, storage, rotation, revocation and recovery;
- a selected crash-safe recovery-store backend with migration, backup and
  rollback procedure;
- two independently provisioned real hosts exercising revoke-during-I/O,
  partition, timeout, replay, rollback, clock skew, cancellation, restart and
  overload;
- measured latency, capacity, backpressure, replay pressure, cancellation tail
  and recovery;
- independent semantic/security review;
- operator acceptance, canary, promotion and release authority.

Until those gates pass, the accurate labels are **in-process read-only product
candidate** and **authenticated cross-host protocol/host source candidate**.
