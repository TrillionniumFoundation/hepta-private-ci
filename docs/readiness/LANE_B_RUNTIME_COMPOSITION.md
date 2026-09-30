# Lane B runtime composition and failure semantics — schema v19

This document records actual runtime composition. Target topology is not treated
as execution evidence.

## Composition

```text
Agentd timer owner
  ├─ recovery budget → exact queue/turn/provider reconciliation
  └─ admission budget → AutomationScheduler::tick_batch
       └─ one durable V1 tick per occurrence
            ├─ stable occurrence/client identity
            ├─ TaskFlow intent before contact
            └─ App Server queue or final-use-authorized effect seam
```

The store schema is v19. Timer lifecycle and destination dedupe are part of the
same owner database; the Neural Circuit runtime adapter compiles and executes
against the existing TaskFlow owner rather than creating a new daemon.

## Failure semantics

| Boundary | Failure before contact | Outcome possibly crossed seam |
|---|---|---|
| App Server queue | bounded retry | `DispatchUnknown`, exact-client reconciliation |
| provider effect | bounded retry only with proof of no contact | stable provider-key reconciliation |
| timer writer | fence current generation | no old-epoch resume |
| database schema | fail-stop | no automatic repair or checksum relabeling |
| circuit route | isolate invalid activation | no route outside admitted edges |

Recovery and admission have separate budgets. Provider concurrency remains one,
so batching improves throughput without adding a competing authority path.

## Cross-host boundary

Same-store handoff is implemented by timer epoch. Cross-host transfer additionally
requires the v1 recovery manifest, checkpoint digest and external host-fence
receipt. Byte transport and distributed lease are deployment-controller duties.

## Evidence boundary

Repository CI can prove source behavior on its runner. It cannot self-issue
independent acceptance, prove the selected production host, or authenticate a
current IANA tzdb profile not supplied to the run. Those gates remain explicit.
