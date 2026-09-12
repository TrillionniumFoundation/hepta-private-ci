# Lane B runtime composition and failure semantics

Implementation correction: [Lane B native host](LANE_B_NATIVE_HOST.md) records actual owner wiring and repository-controlled gaps. The topology and immutable tuple below are target contracts; their presence does not establish an active caller or authority.

**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0  
**Lane:** `LANE-B-RUNTIME`  
**Immutable source base:** `f278a89eea18fccb6d37b876aa5679863a64139d` / tree `5baa144717d4b3e3c596501fb56ce911d009e728`  
**Exact candidate:** derived by the verifier from Git HEAD  
**Truth registry:** `qualification/lane-b/LANE_B_IMPLEMENTATION_TRUTH.json`

## 1. Purpose and truth boundary

This document defines the single admissible composition model for all eleven Lane B modules. It separates owner entrypoints from delegated callees, source implementation from product execution, process health from user-task terminality, and repository qualification from deployment or independent acceptance. Directory presence, a build target, a unit fixture, queue acknowledgement or caller-supplied observation cannot establish a real external effect.

## 2. Canonical module set

The closed module set is `runtime.supervisor`, `runtime.fleet`, `runtime.agentd`, `runtime.codex`, `inference.control`, `inference.worker`, `automation.taskflow`, `channel.matrix`, `browser.servo`, `ui.control` and `ui.native`. A twelfth runtime owner requires canonical module, contract, authority, work-package and source-binding admission.

## 3. Runtime and process topology

```text
runtime.supervisor daemon
  -> runtime.agentd daemon for one enrolled Agent identity
       -> runtime.codex / existing Codex App Server and core
       -> inference.control owner -> isolated inference.worker
       -> automation.taskflow scheduler -> Codex/effect owners
       -> channel.matrix runtime -> enrolled homeserver scope
       -> browser.servo driver boundary -> isolated browser target
       -> ui.control Web client
       -> ui.native shell
runtime.fleet remains a separate allocation-lease owner
```

Embedding a library does not transfer data ownership. Agentd owns an explicit admission coordinator in its own source root and separately names Codex callees. Fleet calculation does not become a lease until the fleet owner commits the exact grant and fence.

## 4. Immutable run identity

Each admitted run freezes principal, agent, supervisor incarnation, Agentd generation, configuration and port digests, objective/body/artifact generations, Codex thread/turn identity, model/tokenizer/template/tool-schema identity, authority epoch/revocation frontier, resource lease, deadline and stable operation identity. Mixed tuples reject before context attachment or any effect boundary.

## 5. Startup order

Supervisor verifies configuration, lifecycle state, revocation access and rollback predecessor, then creates a new process fence. Agentd validates private roots, socket identity, exact owner ports and bounded queues before starting the App Server. Owner services open and verify their physical state before readiness. Optional advisory inputs may fall back only to a deterministic no-authority-widening state. UI availability never changes backend readiness.

## 6. Normal request path

```text
authenticated request
 -> Agentd freezes run tuple
 -> Codex thread/turn admission
 -> context receipt matches frozen tuple
 -> inference reservation and assignment
 -> final authority and payload check
 -> worker driver execution
 -> authenticated terminal or indeterminate observation
 -> inference settlement
 -> Codex turn observation
 -> independently owned outcome/evidence path
```

Every transition uses the same semantic identity. A successful predecessor cannot infer a missing successor.

## 7. Automation path

TaskFlow persists schedule and occurrence identity, claims under a generation fence, writes durable pre-dispatch intent, enters the Codex/effect seam with final-use authority, and waits for a trusted terminal observer. Unknown effects block dependent mutation. Compensation has a new operation identity and separate authorization.

## 8. Matrix path

Ingress binds enrolled homeserver, user, device, room and encryption generation; deduplicates server event identity; applies correction/redaction; and advances a durable sync frontier. Send preparation binds room, session, payload, authority epoch and one Matrix transaction ID. HTTP acceptance, homeserver persistence and human reading are separate claims. Lost acknowledgement retains the same transaction for reconciliation.

## 9. Browser path

The browser owner freezes manifest, profile, principal, process and page generations, origins, effect grants and expiry. Every action revalidates page/document generation, final destination, payload digest and current authority. Redirect, input, upload, download and credential use are distinct capabilities. A driver fixture proves the boundary contract, not a deployed Servo process or a remote business outcome.

## 10. UI path

Web and native clients are presentation owners. Requests bind authenticated session, connection/view generation, displayed revision, operation identity, target and final payload digest. Reconnect reconciles existing identities. Disconnect cannot relabel backend work. Native OS permission and a Hepta effect grant are both required. Update execution requires independent selection, signature/compatibility verification, restart and predecessor rollback.

## 11. Cancellation and deadline semantics

Cancellation is monotonic. Before dispatch it may become terminal cancelled; after possible dispatch it becomes cancelling or indeterminate until the terminal owner settles it. Late valid completion and usage remain recordable. A deadline participates in semantic identity wherever changing it changes retry behavior. Timeout never creates permission for a fresh identity or blind retry.

## 12. Backpressure and capacity

Every ingress has hard payload, queue, concurrency and deadline bounds. Supervisor active instances, Fleet hosts/requests/resource axes, Agentd active and retained runs, inference queues/model resources, TaskFlow scans/graphs, Matrix batches/room queues, browser profiles/tabs/observations and UI pending requests are bounded. Saturation returns an explicit rejection or unavailable state. No fallback borrows authority, safety, evidence or rollback capacity.

## 13. Fault-state matrix

| Fault | Required state | Forbidden inference | Recovery owner |
|---|---|---|---|
| stale process/page/view generation | rejected | new generation advanced | owning runtime |
| critical store integrity uncertainty | not-ready or quarantined | live process is ready | store owner + supervisor |
| crash before proven dispatch | pending or safe pre-dispatch cancellation | effect occurred | initiating owner |
| crash after possible dispatch | indeterminate | blind retry is safe | operation/effect owner |
| provider or homeserver acknowledgement loss | same identity, indeterminate | success or failure inferred | inference/Matrix owner |
| TaskFlow unknown step | dependent steps blocked | workflow completed | TaskFlow + effect owner |
| browser stale element | rejected | old element remains valid | browser owner |
| UI disconnect | local pending view | backend cancelled | UI + backend owner |
| revocation during frozen run | new effects denied | snapshot overrides revocation | authority/effect owner |
| rollback request | drain, reconcile, new generation | in-place mixed artifacts | supervisor + artifact owner |

## 14. Shutdown and rollback order

Stop new admission; persist drain intent; cancel only provably pre-effect work; reconcile or quarantine dispatched work; flush owner-local state and outboxes; close UI, Matrix, browser, inference and Codex transports in dependency-safe order; stop Agentd and verify exit; release only resources acquired by the current generation; load an independently selected compatible predecessor into a new generation; then replay current revocation/deletion frontiers before readiness.

## 15. Source maturity

The truth registry records source-boundary mappings for all 39 operations. Supervisor and Codex are native runtime spines; Fleet, inference, TaskFlow and Matrix include native owner ledgers/adapters; Agentd now owns its own run coordinator; Browser/Web/Native provide bounded driver/client boundaries. The component mappings do not close repository-controlled integration work. Durable owner wiring, actual local model/browser drivers and runtime composition remain implementation tasks in addition to external qualification.

## 16. Evidence package required for activation

Activation receipts bind exact head/tree/parents, guide and truth digests, build target and artifact digest, owner entrypoint and non-test caller, host/runtime/configuration, physical state and migrations or proved statelessness, writer fence, authority/revocation/final payload, terminal observer, crash/timeout/cancellation/saturation results, target measurements, rollback predecessor and every applicable external gate. Fixture and CI results remain source qualification evidence only.

## 17. Acceptance rule

Repository-controlled Lane B closure passes only when the central truth, eleven module maps, generated human closure, test traceability, source symbols and exact-head/synthetic-merge workflow agree. Product execution, deployment, external effects, hardware behavior, independent acceptance, selection, promotion and release remain false until the designated external actor issues exact evidence. Unknown gaps are added; they are never suppressed to preserve a green count.
