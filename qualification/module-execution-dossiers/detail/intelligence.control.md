# intelligence.control: implementation design

Parent: `docs/modules/intelligence.control/TECHNICAL.md`.
Lane: `LANE-F-ADAPTIVE-POLICY`.
Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`.

Status: canonical composition, authenticated configurable daemon ingress,
formal learning adapters/outbox, current-clock replay checks, bounded recovery
scheduling and request-independent worker supervision have source. Native
validation, full product execution and process-loss acceptance are not implied.

## 1. Source and work envelope

Exclusive owner root: `codex-rs/hepta-intelligence`. Agentd owns orchestration
integration; kernel.operations owns cursor/claim state operations; learning.ledger
owns authenticated facts and witness. Packages remain `INTELLIGENCE-A0-Q0.63`,
`INT-2-AGENTD-CODEX-COMPOSITION` and `C1-PROMPTED-MEMORY-RETRIEVAL-RANK`.
No new intelligence database or execution plane is introduced.

## 2. Public operations and contracts

Canonical operations remain `build_legal_candidates`, `prepare_intelligence_run`,
`decide_boundary`, `assemble_context` and `validate_current_snapshot`.
`validate_canonical_outcome_v1` rehashes mutable nested decisions, context binding
and envelope contents against the admitted run/candidate snapshot. Membership
alone cannot validate replacement by another legal candidate or propensity.

Agentd's retained prepared object also pins its original private context
attachment; formal learning adapters revalidate this boundary. Produced
`LegalActionCandidateSetV1` and `IntelligenceHostEnvelopeV1` remain deny-all.
Digest validation is not external producer authentication.

## 3. State records and transaction design

The complete durable RunStart determines request, objective/body/artifact,
authority, generation/fence and deadline. The host provider cannot replace those
fields. Bound coordinator admission rejects foreign launch/Running identities.

V2 Decision/Outcome sidecars retain original predecessor, event time and complete
verified signing identity. `intelligence_learning_payload.rs` contains the codec
and sole `LedgerWriter` adapters; `intelligence_learning.rs` owns composition
with the existing operations store, not learning facts.

Sidecar sync precedes intent publication. No-replace file installation preserves
immutable identity. Destination-first recovery compares complete authenticated
V2 event equality; first application uses a current host clock and fresh
final-use authority. Independent witness catch-up/acknowledgement remains open.

## 4. Algorithm and actual dependency edges

Canonical order is objective -> NDU -> neuron -> prompt -> intuition -> context
-> signed evaluation. Owner bindings are checked before/after every stage and
again before prepared handoff. Abstain/slow-path stops before context/evaluation.

Concrete adapters retain actual NDU and neuron outputs. NDU contributions cover
the same legal universe plus only reserved abstain. The real NDU result binds
the neuron input; real neuron state binds intuition; actual NDU infeasibility
cannot be silently marked legal/unvetoed by intuition. Nonzero predecessor
substitution is rejected and owner failures still record their latency.

The prompt receipt chain does not yet prove authorized prompt realization
contents constructed context and the physical request. That semantic edge and
an executable authenticated input factory remain product requirements.

## 5. Scheduling, capacity and isolation

Four worker permits stay with actual computation. An independent OS observer
starts with each bounded worker; dropping the request future cannot disarm it.
Completion joins the observer before permit release. Explicit hard-timeout
policy can terminate Agentd at code 70; this is not proof of complete Supervisor
replacement and durable recovery.

Cognition and final currentness use the remaining monotonic budget. The factory
and synchronous learning grant/file/writer work still require a complete bounded
owner lifetime. No general hard-preemption claim is made for synchronous Rust.

Recovery uses stable identity keyset pages, not an unchanged oldest timestamp.
Recovery/fresh dispatch have separate shares, alternating when batch size is
one. Only a still-Prepared exact live claim may defer after pre-dispatch grant
unavailability. Unknown effects never return to the normal dispatch queue.

## 6. Verification evidence and limitations

The module JSON explicitly maps requirements to package/source/test names and
states the support scope of each test. Original identity-substitution tests and
legacy qualification-only coverage are retained. New source includes mutable
DTO mutations, current-time expiry/clock rollback, real SQLite cursor and lease
regressions, bounded scheduling, file publication and real-child watchdog tests.

Source declarations remain pending. The independent workflow must execute
intelligence and operations packages, default Agentd tests, separately labelled
legacy tests, formatting, all-target compilation and strict lint on exact head
and deterministic merge. Exact projections require real command records and
matching logs with the mapped tests observed passing. Read-only supplementary
native diagnostics do not replace mandatory checks or target-host evidence.

## 7. Integration, compatibility and rollback

The actual configured source route is authenticated ObjectiveStart -> durable
RunStart -> host provider -> canonical preparation -> bound run/context admission.
Ordinary CLI does not install an authorized seven-owner factory. The native
App Server `run_intelligence` consumer exists, but Decision-before-dispatch,
actual delivered context/request and independently observed terminal Outcome
must still be composed into one product path.

Legacy read-only, shadow/evaluated-shadow and feature-gated learning methods
retain historical interpretation. Do not retire them by deleting records or use
their tests as default-product proof. Lost physical acknowledgements and absent
terminal observations remain reconcile-only, never fresh effect replay.

## 8. Current native implementation

- `hepta-intelligence/src/canonical.rs` and `canonical_invariants.rs`: pure graph and mutable-DTO integrity.
- `hepta-agentd/src/intelligence_ingress.rs`: durable identity and host invocation boundary.
- `intelligence_product.rs`, `intelligence_product_ports.rs`, `intelligence_product_runner.rs`: owner calls, actual-result bindings and bounded preparation.
- `intelligence_prepared_integrity.rs`, `intelligence_worker_watchdog.rs`: retained-object integrity and independent supervision.
- `intelligence_learning.rs`, `intelligence_learning_payload.rs`, `intelligence_learning_clock.rs`, `intelligence_learning_runtime.rs`: formal learning composition, immutable encoding, current verification time and fair scheduling.
- `hepta-operations/src/reconciliation_cursor.rs`, `pre_dispatch_defer.rs`: destination-scoped keyset observation and exact pre-dispatch deferral.
- `hepta-infer-worker-host/src/native_run_control.rs`: existing physical App Server handoff, not a newly completed product loop.

All Rust paths above are relative to `codex-rs` where a crate prefix is shown,
and otherwise to `codex-rs/hepta-agentd/src`.

Effective operating contracts are
`docs/modules/intelligence.control/PRODUCT_CLOSURE.md` and
`docs/modules/intelligence.control/RESTART_RECONCILIATION.md`.
Remaining work: actual prompt/context/request materialization, executable owner
factory, Decision/terminal Outcome wiring, bounded factory/learning I/O,
parent-anchored no-follow file access, independently durable authority rollback
floor, ledger-witness recovery, current native validation, physical process fault
cuts, performance/quality baselines and independent acceptance. Source work does
not grant activation, promotion, release or C1 longitudinal efficacy.


## Product boundary source convergence

The guarded canonical profile now optionally installs a daemon-owned completion
interface at authenticated ObjectiveStart. Its concrete native embedding reuses
DurableInferenceControl, the existing App Server driver and the sole learning
host. It requires witnessed Decision acknowledgement before model send, derives
physical bytes only from owner-constructed PreparedPromptDeliveryV1, and checks
independent Outcome support against the observed run and provider terminal.
A terminal native observation remains available when the Outcome path needs
reconciliation; canonical_executed is episode closure, not task success.

The effective current contracts are PRODUCT_CLOSURE.md and
RESTART_RECONCILIATION.md in the module guide directory. Their source mechanisms
supersede earlier statements that these adapters were wholly absent: private
prompt-source lineage and regenerated serialization proof; bounded factory and
learning I/O workers; parent-component no-follow reads; a separately retained
manifest floor; exact LedgerWriter witness-prefix/last-record recovery. These
are not proof of a deployed owner factory, a full physical ObjectiveStart E2E,
write-side crash/root replacement, target-host performance or task efficacy.
Qualification-only legacy writes are never used to supply the default product.
