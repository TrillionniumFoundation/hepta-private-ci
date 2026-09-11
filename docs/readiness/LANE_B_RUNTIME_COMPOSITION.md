# Lane B runtime composition and failure semantics

**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0  
**Lane:** `LANE-B-RUNTIME`  
**Lineage anchor:** `f278a89eea18fccb6d37b876aa5679863a64139d` / tree `5baa144717d4b3e3c596501fb56ce911d009e728`  
**Exact candidate:** clean CI checkout `HEAD`  
**Truth registry:** `qualification/lane-b/LANE_B_IMPLEMENTATION_TRUTH.json`  
**Status:** repository-controlled composition specification; production execution and external evidence are not implied

## 1. Purpose and truth boundary

This document defines the only admissible composition model for the eleven Lane B modules. It separates target design from current native source, owner entrypoints from delegated callees, build reachability from product callsites, process health from user-task terminality, and repository qualification from deployment or independent acceptance.

The immutable lineage anchor is a parent snapshot. The exact candidate is supplied by the CI checkout and `EXPECTED_SHA`; the document never embeds its own final Git hash. The machine truth records current operation disposition, native symbols and test identifiers. A directory, Cargo package, JavaScript export, source pin, fixture, injected driver, queue acknowledgement or caller-supplied observation is not product execution.

The following claims remain false until exact external evidence is issued: production activation, real provider/model/device execution, Servo network effects, Matrix homeserver delivery, deployed Web/native identity, target-host measurements, hardware safety, future-window efficacy, operator acceptance, signing, selection, promotion and release.

## 2. Canonical module set

The closed Lane B set, in dependency order, is:

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

A new process, service, adapter, worker or UI cannot silently become a twelfth owner. It must first enter the canonical module, contract, data-authority, work-package and source-binding registries.

## 3. Runtime and process topology

```text
runtime.supervisor
  owns generation fencing, launch, readiness, drain, stop, upgrade and rollback
  |
  +-- runtime.agentd
        owns composition, private local transport and runtime-health observation
        |
        +-- runtime.codex / existing Codex App Server and core
        |     owns thread, turn, model-call and tool-routing execution spine
        |
        +-- inference.control
        |     owns durable request, reservation, assignment, cancel and settlement facts
        |     |
        |     +-- inference.worker
        |           consumes a current request, reservation and resource grant
        |
        +-- automation.taskflow
        |     owns schedule/occurrence and step-orchestration state
        |
        +-- channel.matrix
        |     owns Matrix ingress and transaction-bound send observation
        |
        +-- browser.servo
        |     owns isolated profile and page/effect boundary state
        |
        +-- ui.control
        +-- ui.native
```

`runtime.fleet` is a separate allocation owner. Its deterministic allocator and lease state may be loaded by another host, but embedding does not transfer canonical ownership. Agentd delegates thread/turn operations to `runtime.codex`; that delegation is explicit in the truth registry and does not make App Server source an Agentd-owned root.

## 4. Identity tuple

Every admitted run freezes:

```text
principal and agent identity
supervisor process identity and incarnation
agentd process identity and spawn generation
configuration digest and revision
objective digest and generation
body/topology digest and generation
Codex thread and turn identity
model, weights, tokenizer, template, tool-schema, runtime and device digests
artifact-set identity and predecessor
authority epoch and revocation frontier
fleet allocation and inference reservation identities
operation identity, final payload digest and deadline
```

Any mixed tuple rejects before context attachment, provider dispatch, tool entry, Matrix send, browser action or platform operation. A retry reuses the same operation identity only when the full semantic digest is equal.

## 5. Startup order

1. Supervisor verifies configuration, lifecycle storage, release selection, revocation reader and rollback predecessor.
2. Supervisor creates a new incarnation fence and starts Agentd with immutable identity and resource limits.
3. Agentd verifies private roots, local transport paths, peer restrictions, local stores, adapter versions and required feature states.
4. Agentd starts the existing Codex App Server on its configured local transport. It does not create a second execution spine.
5. Required owner ports are attached. Missing critical owners block readiness; optional advice may degrade only through a bounded no-authority-widening fallback.
6. Fleet, inference, TaskFlow, Matrix and browser components become ready only after their schema, integrity, authority and resource prerequisites pass.
7. UI clients connect only after a coherent runtime snapshot exists. UI availability never changes backend readiness.
8. Supervisor marks the generation ready only after dependency readiness, not merely process liveness.

A stale callback, old socket peer, inherited handle, previous process ID or cached generation cannot advance a new instance.

## 6. Normal request path

```text
authenticated request
  -> frozen objective/body/artifact tuple
  -> Agentd admission and bounded queue
  -> Codex thread/turn admission
  -> exact context attachment
  -> inference request and durable reservation
  -> deterministic worker assignment
  -> final payload and current authority revalidation
  -> worker model admission and bounded execution
  -> provider/device observation
  -> inference settlement
  -> Codex turn observation
  -> independently owned outcome/evidence path
```

Current repository code implements the local operations listed in the truth registry. It does not prove that the complete path executed on a deployed host. No stage may infer its successor from a successful predecessor.

## 7. Automation path

```text
schedule revision
  -> deterministic occurrence identity
  -> generation-fenced claim
  -> durable pre-dispatch intent
  -> Codex/App Server admission
  -> typed operation intent and final-use verification
  -> effect-owner dispatch
  -> trusted terminal observation or indeterminate state
  -> occurrence settlement
  -> separately authorized compensation
```

TaskFlow does not acquire ambient model, tool, Matrix or browser authority. Unknown effect state blocks dependent mutation. Compensation has a new operation identity, grant and terminal observation.

## 8. Matrix path

Ingress:

```text
enrolled homeserver/user/device/room session
  -> bounded sync response
  -> durable event identity and watermark
  -> correction/redaction
  -> room/thread binding
  -> Codex/App Server admission
```

Send:

```text
Codex/App Server output
  -> durable operation and Matrix transaction identity
  -> final room/payload/session-bound authority
  -> homeserver dispatch
  -> matching server-event observation or indeterminate reconciliation
```

Queueing, HTTP acceptance, homeserver persistence and downstream human reading are distinct claims. A reconnect preserves transaction identity and applies current redaction, deletion and revocation frontiers before exposing cached content.

## 9. Browser path

```text
enrolled browser manifest and exact build identity
  -> isolated principal-bound profile
  -> origin/network/filesystem/credential policy
  -> generation-bound page observation
  -> final document/element/destination/payload/grant validation
  -> one typed action
  -> trusted terminal observation or indeterminate reconciliation
```

The repository implements the profile and effect state machine through an injected driver boundary. A source pin or JavaScript class does not prove a reproducible Servo process, network effect or remote business outcome. Redirects, downloads, uploads, credential use and DOM actions remain separately typed capabilities.

## 10. UI path

`ui.control` and `ui.native` are presentation owners only. They may display coherent backend projections and submit authenticated requests. They cannot issue capabilities, write domain stores, select candidates or authenticate their own terminal conclusions.

Every request binds:

```text
session identity
connection/session generation
view generation and displayed revision
operation identity
target and final semantic or payload digest
requested action
backend protocol version
```

Reconnect reconciles existing operation identities. Disconnect removes local affordances but does not prove cancellation. Native OS permission and a Hepta grant are separate requirements. Emergency stop remains usable without model cooperation; physical emergency stop is independent of both UIs.

## 11. Cancellation and deadline semantics

Cancellation is monotonic, not retroactive erasure:

- before dispatch, a verified cancellation may become terminal;
- while an operation is provably pre-boundary, reserved resources may be released under the same fence;
- after an effect may have crossed the boundary, the state remains cancelling or indeterminate until its terminal observer settles it;
- late valid completion and usage are recorded under the declared ordering;
- a deadline participates in semantic identity whenever changing it changes retry behavior;
- timeout never grants permission to create a new operation identity and blindly retry.

## 12. Backpressure and resource exhaustion

Every ingress has finite payload, queue, concurrency and deadline bounds. Saturation produces an explicit rejected, unavailable or deferred result. It cannot create unbounded tasks, retries, model tokens, Matrix events, page observations or UI snapshots.

Resource order is:

1. reserve hard safety, evidence and rollback floors;
2. validate current capacity and uncertainty;
3. calculate only feasible allocation;
4. commit allocation or reservation identity and fence;
5. dispatch;
6. account observed usage;
7. reconcile uncertain holders before reuse.

Repository defaults are design and test bounds until target-host measurements bind them to a named profile.

## 13. Fault-state matrix

| Fault | Required state | Forbidden inference | Recovery owner |
|---|---|---|---|
| stale generation callback | rejected | new process advanced | Supervisor |
| critical store integrity failure | not ready or quarantined | live process is ready | store owner + Supervisor |
| Agentd crash before dispatch | pending or pre-dispatch failure | effect occurred | Supervisor/Agentd |
| Agentd crash after possible dispatch | indeterminate | blind retry is safe | operation/effect owner |
| provider acknowledgement loss | indeterminate | model call failed or succeeded | inference control/observer |
| TaskFlow admission timeout | indeterminate after seam | occurrence may be recreated | TaskFlow + Codex owner |
| Matrix reconnect | resume durable watermark | replay is harmless | Matrix owner |
| Matrix send acknowledgement loss | same transaction, indeterminate | new transaction is safe | Matrix owner |
| browser page generation drift | rejected | old element is valid | browser owner |
| UI disconnect | local pending view | backend action cancelled | UI + backend owner |
| revocation during frozen run | new effects denied | snapshot overrides revocation | authority/effect owner |
| rollback request | drain and reconcile, then new generation | in-place mixed artifacts | Supervisor + artifact owner |

## 14. Shutdown and rollback order

1. Stop new request and occurrence admission.
2. Freeze the current generation and record drain intent.
3. Cancel only operations still provably before an effect boundary.
4. Reconcile or quarantine dispatched and indeterminate operations.
5. Flush owner-local durable state and outboxes.
6. Close UI, Matrix, browser, inference and Codex transports in dependency-safe order.
7. Stop Agentd and verify process exit.
8. Release only resources acquired by the current generation.
9. Load an independently selected compatible predecessor into a new generation.
10. Verify current revocation, deletion and consent frontiers before readiness.

Rollback never restores expired leases, revoked capabilities, deleted content, obsolete consent or an old revocation frontier.

## 15. Module maturity at the current repository candidate

| Module | Repository maturity | Main external completion |
|---|---|---|
| `runtime.supervisor` | lifecycle runtime, partly deployment-bound | operator endpoint and target-host process qualification |
| `runtime.fleet` | host/lease runtime | real capacity and resource-holder enforcement |
| `runtime.agentd` | composition runtime with explicit delegation | deployed peer identity and target-process qualification |
| `runtime.codex` | existing execution spine | deployed trace, real model/tool terminal observations |
| `inference.control` | durable control runtime | worker discovery, quota and provider/device evidence |
| `inference.worker` | model-driver runtime boundary | qualified real model driver and device |
| `automation.taskflow` | fenced execution runtime | deployed App Server/effect-owner callsite and crash/DST qualification |
| `channel.matrix` | ingress and send-observer runtime | real homeserver, encryption and remote acknowledgement |
| `browser.servo` | profile/effect runtime boundary | reproducible Servo process and target-browser qualification |
| `ui.control` | authenticated runtime client | deployed Web application and accessibility/security qualification |
| `ui.native` | native shell runtime boundary | signed target application, secure storage and updater rehearsal |

Exact operation states and source symbols remain authoritative in the machine truth.

## 16. Evidence package required for activation

Each activation package binds one exact candidate to:

```text
source commit, tree and ordered parents
module guide, truth and module-map digests
executable/library/build target
owner entrypoints and named non-test callers
host, operating system, runtime and immutable configuration
physical files/tables/keyspaces and migrations, or proved none_by_design
single-writer fence
authority, revocation, destination and final-payload checks
terminal observer and indeterminate reconciliation
fault, cancellation, drift, saturation, crash and recovery results
target-host p50/p95/p99 and resource measurements
rollback predecessor and rehearsal
external gates, each evidenced or explicitly open
```

The implementation team cannot self-issue independent acceptance, external-owner consent, provider/model execution, hardware safety, future efficacy, promotion or release.

## 17. Acceptance rule

Repository-controlled composition and mapping documentation is complete only when the manifest, truth registry, test traceability, generated module maps, this document and the native-closure projection agree at the clean exact CI head and deterministic synthetic merge.

Target-design implementation closure additionally requires every partial or delegated integration to be exercised by a named deployed caller, with exact runtime identity, physical-state disposition, authenticated terminal observation, target-host tests and rollback evidence. External gates remain separate and cannot be converted into repository facts by prose, fixtures or Boolean edits.
