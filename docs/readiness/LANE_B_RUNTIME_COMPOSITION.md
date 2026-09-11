# Lane B runtime composition and failure semantics

Base: `f278a89eea18fccb6d37b876aa5679863a64139d` / tree `5baa144717d4b3e3c596501fb56ce911d009e728`

Candidate branch: `codex/hepta-lane-b-truth-runtime-closure-20260911`

Truth-index SHA-256: `64c6af0c546fdde6b366be6462613384c62b83a915e2bf28691689b19a5fb0fb`

Validated against the v3 truth index and canonical module maps.

## 1. Purpose and truth boundary

This document defines the only repository-admissible composition for the eleven Lane B modules. It is generated from `LANE_B_IMPLEMENTATION_TRUTH.json`. All 39 design operations have owner source mappings; source mapping is not deployment, a caller-supplied observation is not terminal proof, and an injected driver is not evidence that a real external target executed.

## 2. Canonical module set

Dependency order is:

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

No twelfth owner may be introduced without canonical module, contract, data-authority, work-package and source-binding admission.

## 3. Runtime and process topology

```text
runtime.supervisor
  +-- runtime.agentd (one enrolled Agent identity)
        +-- runtime.codex / existing App Server and Core
        +-- inference.control
              +-- inference.worker / injected qualified ModelDriver
        +-- automation.taskflow
        +-- channel.matrix
        +-- browser.servo / injected qualified browser driver
        +-- ui.control
        +-- ui.native
runtime.fleet remains a separate capacity/allocation owner
```

Embedding a library does not transfer data ownership. Agentd owns composition and runtime health only. Codex owns thread/turn execution. Inference control owns request/reservation/settlement. TaskFlow owns orchestration. Matrix and browser own their adapter state. UI owns presentation only.

## 4. Identity tuple

Every admitted run freezes principal, Agent identity, supervisor incarnation, Agentd spawn generation, configuration digest, objective/body/artifact generations, thread/turn identity, model/tokenizer/template/tool-schema digests, authority epoch, revocation frontier, resource lease and deadline. Any mixed tuple rejects before context attachment or effect entry.

## 5. Startup order

1. Supervisor verifies configuration, registry, release selection, signed-intent recovery and revocation readers.
2. Supervisor establishes a new generation fence and starts Agentd under explicit resources.
3. Agentd validates roots, owner-only socket paths, strict feature state, local thread store and adapter versions.
4. Agentd starts the existing App Server/Core spine and attaches required owner ports.
5. Inference, TaskFlow, Matrix and browser boundaries become ready only after their state, authority and resource prerequisites pass.
6. UI may connect only after a coherent runtime snapshot exists.
7. Supervisor publishes readiness for the current generation only after all critical dependency readiness is observed.

## 6. Normal request path

```text
authenticated request
 -> frozen objective/body/artifact tuple
 -> Agentd session ingress
 -> Codex thread/turn admission
 -> exact context attachment
 -> inference durable reservation and worker assignment
 -> final payload/authority revalidation
 -> worker driver execution
 -> authenticated provider/device observation
 -> inference settlement
 -> Codex turn observation
 -> independently owned outcome/evidence
```

A successful predecessor never implies a missing successor.

## 7. Automation path

```text
registered schedule/definition
 -> deterministic occurrence
 -> current generation/fence claim
 -> durable pre-dispatch intent
 -> Codex/App Server admission
 -> final-use verification
 -> effect adapter
 -> trusted terminal observation or indeterminate state
 -> occurrence settlement
 -> separately authorized compensation
```

TaskFlow does not call a provider, Matrix endpoint or browser directly and never blindly retries an unknown effect.

## 8. Matrix path

Ingress binds enrolled homeserver/user/device/room/session, bounded sync payload, durable event identity, watermark, correction/redaction and room/thread admission. Send binds one operation, final room/payload/session authority and Matrix transaction. HTTP acceptance, homeserver persistence and human reading are distinct claims.

## 9. Browser path

BrowserProfileHost binds principal, exact manifest/profile grant, origin allowlist, effect grant, process/profile/page generation, destination, final payload, authority epoch and deadline. Redirect, upload, download, credential and DOM actions are separate capabilities. Indeterminate actions must reconcile before profile close.

## 10. UI path

Web and native clients consume coherent backend generations and submit stable authenticated request identities. They cannot issue capabilities or authenticate their own terminal outcomes. Disconnect removes local affordances but neither cancels nor relabels backend work. Native OS permission remains separate from a Hepta grant.

## 11. Cancellation and deadline semantics

Cancellation is monotone. Before effect entry it may become terminal cancelled; after possible entry it remains cancelling or indeterminate until the terminal observer settles it. A late valid completion is recorded and accounted. Deadline is part of semantic identity whenever changing it alters retry behavior. Timeout grants no new retry identity.

## 12. Backpressure and resource exhaustion

All ingress, queues, payloads, concurrency, tokens, tabs, events, operations and retries are bounded. Saturation yields rejected, unavailable or deferred outcomes. Hard safety/evidence/rollback floors are reserved first; uncertain resource holders are reconciled before reallocation.

## 13. Fault-state matrix

| Fault | Required state | Forbidden inference | Recovery owner |
|---|---|---|---|
| stale process/page/session generation | rejected | old observation advances new generation | owning runtime |
| critical store integrity failure | not ready or quarantined | live process is ready | state owner + Supervisor |
| crash before proven effect entry | pending/recoverable | effect occurred | dispatcher |
| crash after possible effect entry | indeterminate | blind retry is safe | effect owner |
| provider acknowledgement loss | indeterminate | zero usage or failure | inference observer |
| Matrix send acknowledgement loss | same transaction, indeterminate | new transaction is safe | Matrix owner |
| browser document drift | rejected | old element is valid | browser owner |
| UI disconnect | local pending view | backend action cancelled | UI + backend |
| revocation during frozen run | new effects denied | snapshot overrides revocation | authority owner |
| rollback request | drain/reconcile/new generation | in-place mixed artifacts | Supervisor + owners |

## 14. Shutdown and rollback order

Stop admission; freeze the generation; cancel only provably pre-boundary operations; reconcile or quarantine dispatched work; flush owner state/outboxes; close UI/Matrix/browser/inference/Codex transports in dependency order; stop Agentd; release only acquired resources; load an independently selected compatible predecessor in a new generation; then reapply current revocation and deletion frontiers.

## 15. Module maturity at the base

| Module | Repository maturity | Operations | Terminal observation boundary |
|---|---|---:|---|
| `runtime.supervisor` | `native_lifecycle_runtime` | 4 mapped | The process driver and current-generation health probe may establish process terminality. User-task, provider, Matrix, browser and tool outcomes remain with their effect owners. |
| `runtime.fleet` | `lease_runtime_boundary` | 3 mapped | The fleet owner observes lease state. Actual host capacity, consumption and release are terminal only when the enrolled target host supplies authenticated observations. |
| `runtime.agentd` | `delegating_composition_runtime` | 4 mapped | Agentd observes process and ingress readiness. App Server/Core observe turn admission/interruption; downstream effect owners observe external terminal outcomes. |
| `runtime.codex` | `native_execution_spine` | 4 mapped | App Server/Core observe local admission and streaming state. Provider and tool adapters remain the trusted terminal observers for their own external effects. |
| `inference.control` | `durable_control_runtime` | 4 mapped | Inference control accepts only authenticated worker/provider observations matching the exact assignment. The actual provider/device remains the external terminal observer. |
| `inference.worker` | `isolated_worker_boundary` | 3 mapped | The qualified ModelDriver observes model/runtime/device execution. The repository boundary cannot self-certify that real weights or a real accelerator executed. |
| `automation.taskflow` | `durable_fenced_orchestrator` | 4 mapped | The downstream effect adapter is the terminal observer. TaskFlow records terminal or indeterminate receipts and never infers success from queue admission. |
| `channel.matrix` | `durable_channel_boundary` | 3 mapped | A matching authenticated homeserver server-event observation establishes Matrix send terminality. App Server completion and HTTP acceptance are not substitutes. |
| `browser.servo` | `profile_and_effect_boundary` | 3 mapped | The browser driver observes process/page/action outcomes. Remote business effects require destination-owned reconciliation; page load alone is not success. |
| `ui.control` | `authenticated_web_runtime_client` | 3 mapped | Only the backend/effect owner can authenticate terminal state. The UI may display pending, indeterminate, failed or terminal observations but cannot manufacture them. |
| `ui.native` | `native_shell_runtime_boundary` | 4 mapped | Platform and updater adapters observe their own terminal states. The shell preserves indeterminate outcomes and cannot self-sign packages or authenticate OS effects. |

These maturity labels describe repository source boundaries, not deployment status.

## 16. Evidence package required for activation

Every activation receipt must bind exact commit/tree/parents, guide and truth digests, build artifact, owner entrypoint and product caller, host/runtime/configuration, physical state and migration or `none_by_design`, writer fence, authority/revocation/final payload, terminal observer, fault results, p50/p95/p99 resources, rollback predecessor and every applicable external gate.

## 17. Acceptance rule

Repository-controlled composition closure requires: 11 modules, 39 exact mappings, 44 traced acceptance cases, zero open repository gaps, generated-document byte parity, read-only exact-head and synthetic-merge verification, and no unsupported positive external claim. Product/deployment closure additionally requires the nine independently owned `RDY-EXT-*` evidence gates; those remain open and cannot be self-issued by this repository.
