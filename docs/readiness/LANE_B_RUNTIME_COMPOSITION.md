# Lane B runtime composition and failure semantics

**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0  
**Lane:** `LANE-B-RUNTIME`  
**Truth registry:** `qualification/lane-b/LANE_B_IMPLEMENTATION_TRUTH.json`  
**Baseline:** `8613cd93e04200eb1cb5a743d0d5e12f239bd660` / tree `d6a9b473314b4248722094c1a3a8f494d79f8be6`  
**Status:** repository-controlled composition specification; product execution and external evidence are not implied

## 1. Purpose and truth boundary

This document defines the only admissible composition model for the eleven Lane B modules. It separates target design from observed native source, library reachability from product callsites, process health from task terminality, and repository qualification from deployment or independent acceptance.

The canonical module guides remain the target architecture. `LANE_B_IMPLEMENTATION_TRUTH.json` records the current implementation maturity and exact mapped symbols. A directory, Cargo package, JavaScript export, source pin, test fixture, queue acknowledgement or caller-supplied observation is never sufficient proof of product execution.

The following claims remain false until exact evidence is committed and independently issued where required:

- production activation passed;
- every target design operation is implemented;
- every module has a real product consumer;
- a provider or model executed;
- a Servo process performed a network effect;
- the Web or native UI was deployed;
- Matrix send terminality was observed at the homeserver boundary;
- external effects, hardware behavior, future-window efficacy, operator acceptance, promotion or release passed.

## 2. Canonical module set

The Lane B closed set, in dependency order, is:

1. `runtime.supervisor`
2. `runtime.fleet`
3. `runtime.agentd`
4. `runtime.codex`
5. `inference.control`
6. `inference.worker`
7. `automation.taskflow`
8. `channel.matrix`
9. `browser.servo`
10. `ui.control`
11. `ui.native`

No implementation package may silently add a twelfth Lane B owner. A new service, worker, adapter or presentation process first enters the canonical module, contract, data-authority, work-package and source-binding registries.

## 3. Runtime and process topology

The intended product topology is:

```text
runtime.supervisor process
  owns process-generation fencing, launch, health, drain, stop and rollback
  |
  +-- runtime.agentd process, one enrolled Agent identity
        owns composition and runtime-health observation only
        |
        +-- runtime.codex / existing Codex App Server
        |     owns the thread/turn execution spine and thread-session persistence
        |
        +-- inference.control service or owner-local control component
        |     owns request, reservation and settlement facts
        |     |
        |     +-- inference.worker isolated process
        |           consumes an existing request, lease and reservation
        |
        +-- automation.taskflow scheduler
        |     owns schedule/occurrence orchestration facts
        |     dispatches only through the Codex/App Server admission seam
        |
        +-- channel.matrix runtime
        |     owns Matrix ingress projection and dispatch ledger
        |     bridges enrolled Matrix scope to the Codex/App Server seam
        |
        +-- browser.servo isolated process target
        |     consumes exact profile/network/effect grants
        |
        +-- ui.control Web presentation target
        +-- ui.native platform presentation target
```

`runtime.fleet` is a separate resource-allocation owner. Its registry library may be embedded by the supervisor, but embedding does not transfer canonical data ownership. The pure allocator cannot publish a grant. A future allocation-grant publisher must consume current capacity, authority, revocation and generation evidence and must have a named product caller.

## 4. Identity tuple

Every admitted run freezes one immutable tuple:

```text
principal identity
agent identity
supervisor process identity and incarnation
agentd process identity and spawn generation
configuration digest and revision
objective digest and generation
body/topology digest and generation
Codex thread and turn identity
model, tokenizer, template and tool-schema digests
artifact-set identity and predecessor
authority epoch and revocation frontier
resource-allocation lease and expiry
```

Any mixed tuple rejects before context attachment, provider dispatch, tool execution, Matrix send, browser action or platform capability request. A retry reuses the same stable operation identity only when the complete semantic digest is equal.

## 5. Startup order

Startup is fail-closed and ordered:

1. Supervisor verifies its configuration, physical registry, release selection, revocation reader and rollback predecessor.
2. Supervisor creates a new process/incarnation fence and starts Agentd with immutable identity and resource limits.
3. Agentd validates private roots, socket paths, local stores, exact adapter versions and required feature states.
4. Agentd starts the Codex App Server on the configured local transport with strict configuration and the required local thread-store mode.
5. Agentd attaches required owner read ports and optional advisory ports. Missing critical owners block readiness; optional advice may degrade only through a declared no-authority-widening fallback.
6. Inference, TaskFlow, Matrix and browser targets become ready only after their own schema, integrity, authority and resource prerequisites pass.
7. UI projections may connect after a coherent runtime snapshot exists. Their availability never changes backend readiness.
8. Supervisor marks the instance ready only after critical dependency readiness, not process liveness, is observed under the current generation.

A stale callback, old socket peer, previous process handle or inherited cache cannot advance the new generation.

## 6. Normal request path

The target read/model path is:

```text
authenticated request
  -> frozen objective/body/artifact tuple
  -> Agentd run admission
  -> Codex thread/turn admission
  -> exact context compilation and attachment
  -> inference request and resource reservation
  -> deterministic eligible-worker assignment
  -> final payload and authority revalidation
  -> isolated worker execution
  -> provider/model terminal observation
  -> inference settlement
  -> Codex turn observation
  -> independently owned outcome/evidence path
```

Current source implements only bounded portions of this path. The truth registry identifies which design operations are partial, boundary-only, unmapped or planned. No stage may infer the missing successor from a successful predecessor.

## 7. Automation path

The target TaskFlow path is:

```text
schedule revision
  -> deterministic occurrence identity
  -> generation-fenced claim
  -> durable pre-dispatch intent
  -> Codex/App Server queue admission
  -> typed operation intent and final-use verification
  -> effect-owner dispatch
  -> trusted terminal observation or indeterminate state
  -> occurrence settlement
  -> separately authorized compensation when required
```

TaskFlow never calls a model, tool, provider, Matrix endpoint or browser directly. A timeout after the admission seam is `indeterminate`, not retryable success or failure. Recovery preserves the occurrence, client-message and operation identities.

## 8. Matrix path

The target Matrix ingress path is:

```text
enrolled homeserver/user/device/room session
  -> bounded sync response
  -> durable event identity and watermark
  -> correction/redaction application
  -> room/thread binding
  -> Codex/App Server admission
  -> turn projection
```

The target send path is:

```text
Codex/App Server output
  -> durable Matrix outbox identity
  -> final room/payload/session-bound authority
  -> one Matrix transaction identity
  -> homeserver dispatch
  -> trusted server-event observation or indeterminate reconciliation
```

Queueing, HTTP acceptance, homeserver persistence and downstream user reading are distinct claims. Redacted or deleted content must not re-enter context after reconnect, replay, backup restore or projection rebuild.

## 9. Browser path

The current browser package only normalizes and bounds authority-free navigation/projection data, while the Servo manifest pins an upstream source identity. The target process path requires:

```text
enrolled browser manifest and exact Servo build
  -> isolated profile process
  -> origin/network/filesystem/credential policy
  -> generation-bound page observation
  -> final element/page/destination/payload validation
  -> one typed action
  -> trusted terminal observation or indeterminate reconciliation
```

A URL proposal, page projection or source pin is not a browser process, network capability or successful action. Redirects, downloads, uploads, credential use and DOM actions are separate capabilities.

## 10. UI path

`ui.control` and `ui.native` are presentation owners only. They may display coherent backend projections and submit authenticated requests, but cannot issue capabilities, write owner stores, select candidates or authenticate their own terminal conclusions.

Every UI request binds:

```text
session identity
view generation and displayed revision
operation identity
target and final payload digest
requested action
backend protocol version
```

Reconnect reconciles existing request identities. Disconnect removes local affordances but does not cancel or relabel external work. Emergency stop remains usable without model cooperation; physical emergency stop is independent of either UI.

## 11. Cancellation and deadline semantics

Cancellation is a monotonic request, not retroactive erasure:

- before dispatch, a verified cancellation may produce a terminal cancelled state;
- while dispatch is definitely pre-boundary, resources may be released under the same fence;
- after an effect may have crossed the boundary, the state is cancelling or indeterminate until the terminal observer settles it;
- a late valid completion is recorded and accounted under the declared settlement order;
- a deadline is part of request identity whenever changing it changes retry semantics;
- no timeout creates permission to retry with a new operation identity.

## 12. Backpressure and resource exhaustion

Every ingress has a finite payload, queue, concurrency and deadline bound. Saturation produces an explicit rejected, unavailable or deferred outcome. It cannot create unbounded tasks, retries, buffered model tokens, Matrix events, browser observations or UI snapshots.

Resource order is:

1. reserve hard safety, evidence and rollback floors;
2. validate current host capacity and uncertainty;
3. allocate only feasible resources;
4. persist the allocation or reservation fence;
5. dispatch;
6. account observed usage and reconcile unknown holders before reallocation.

The pure Fleet allocator supplies a calculation only; it cannot attest capacity freshness or issue a lease.

## 13. Fault-state matrix

| Fault | Required state | Forbidden inference | Recovery owner |
|---|---|---|---|
| stale generation callback | rejected | new process advanced | Supervisor |
| critical store integrity failure | not ready/quarantined | live process is ready | owning store + Supervisor |
| Agentd crash before dispatch | recoverable pre-dispatch or pending | effect occurred | Supervisor/Agentd |
| Agentd crash after possible dispatch | indeterminate | safe blind retry | operation/effect owner |
| provider acknowledgement loss | indeterminate | model call failed or succeeded | inference control/observer |
| TaskFlow admission timeout | indeterminate after seam | occurrence may be duplicated | TaskFlow + Codex owner |
| Matrix reconnect | resume durable watermark | replay is harmless | Matrix owner |
| Matrix send acknowledgement loss | same transaction, indeterminate | new transaction is safe | Matrix owner |
| browser page generation drift | rejected | old element remains valid | browser owner |
| UI disconnect | local pending view | backend action cancelled | UI + backend owner |
| revocation during frozen run | new effects denied | frozen snapshot overrides revocation | authority/effect owner |
| rollback request | drain/reconcile then new generation | in-place mixed artifacts | Supervisor + artifact owner |

## 14. Shutdown and rollback order

Shutdown proceeds as follows:

1. stop new request and occurrence admission;
2. freeze the current generation and record drain intent;
3. cancel only operations still provably before an effect boundary;
4. reconcile or quarantine dispatched and indeterminate operations;
5. flush owner-local durable state and outboxes;
6. close UI, Matrix, browser, inference and Codex transports in dependency-safe order;
7. stop Agentd and verify process exit;
8. release only resources actually acquired by this generation;
9. load an independently selected compatible predecessor into a new process generation;
10. verify current revocation and deletion frontiers before readiness.

Rollback never restores expired leases, revoked capabilities, deleted content, obsolete consent or an old revocation frontier.

## 15. Module maturity at the baseline

| Module | Current repository maturity | Main missing closure |
|---|---|---|
| `runtime.supervisor` | partial runtime | exact daemon callsites and native cross-platform qualification |
| `runtime.fleet` | registry plus authority-free allocator | allocation-grant publisher and ownership separation |
| `runtime.agentd` | partial composition runtime | complete run/cancel/context callsite binding |
| `runtime.codex` | real app-server alias plus receipt adapter | exact protocol-handler and product-callsite mapping |
| `inference.control` | process-local ledger plus plan calculator | durable scheduler, quota and provider settlement |
| `inference.worker` | receipt-boundary scaffold | real model/runtime/device host |
| `automation.taskflow` | qualification ledger and scheduler | final-use effect owner and trusted terminal observer |
| `channel.matrix` | substantial durable runtime | product transport callsites and send terminality |
| `browser.servo` | intent core plus upstream pin | Servo process, profile and network/effect host |
| `ui.control` | presentation core | Web runtime, transport, authentication and E2E deployment |
| `ui.native` | native intent core | platform shell, IPC, secure storage and signed updates |

The machine-readable truth registry is authoritative for exact operation states and mapped symbols.

## 16. Evidence package required for activation

Each module activation package must bind all of the following to one exact source and merge candidate:

- source commit, tree and ordered parents;
- module guide and truth-registry digests;
- executable/library/build-target identity;
- native entrypoints and non-test product callers;
- host, operating system, runtime, configuration and body generation;
- physical files/tables/keyspaces and schema migrations, or proved statelessness;
- single-writer fence and shard rule;
- authority, revocation and final-payload checks;
- terminal observer and indeterminate reconciliation;
- crash, corruption, timeout, cancellation, drift and saturation results;
- target-host latency and resource measurements;
- exact rollback predecessor and recovery rehearsal;
- every applicable external gate, either evidenced or explicitly open.

The implementation team cannot self-issue independent acceptance, future-window efficacy, hardware safety, external-owner consent, promotion or release.

## 17. Acceptance rule

Repository-controlled composition documentation is complete only when this document, the truth registry and their validator agree with the canonical Lane B module set, source bindings and native anchors.

Target implementation closure additionally requires every operation to leave `planned`, `mapping_required`, `boundary_only` and `implemented_partial`; every module must have a named product caller, exact host/runtime identity, physical-state and migration disposition, executable product tests and terminal observation. External gates remain separately governed and cannot be converted into repository facts.
