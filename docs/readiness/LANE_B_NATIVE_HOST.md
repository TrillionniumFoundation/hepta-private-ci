# Lane B: native host implementation and remaining external gates

This page describes executable source at schema v19. It supersedes v16-era
statements while preserving them in the adjacent legacy snapshot.

## Actual owners

- `codex-rs/hepta-automation`: durable schedule, occurrence, TaskFlow, timer and
  effect-evidence owner.
- `codex-rs/hepta-agentd`: scheduler/recovery service, App Server queue adapter,
  Calendar V2 control and configured external-effect host.
- App Server: authoritative queue/persisted-turn records.
- final-use authority and provider adapter: independently configured effect
  authorization and transport.
- deployment controller: selected host, external host fence, byte transfer and
  release evidence.

## Repository-controlled closure

Implemented in source:

- schema v19 migration convergence and startup verification;
- bounded recovery and admission lanes;
- age-first scheduling and provider backpressure;
- formal error disposition and SLOs;
- Agentd external-effect execute/reconcile path;
- Calendar V2 DST/tzdb-profile semantics;
- timer lifecycle and fail-closed cross-host manifest;
- Neural Circuit event/decision/choice/organ/wait/budget/feedback/cancellation/
  terminal vertical slice;
- PR/main focused workflow and exact-head command receipt.

## Deliberate non-owners

Do not turn `hepta-taskflow-runtime` into a second scheduler. Do not let Neural
Circuit code call a provider directly. Do not infer terminality from an
incomplete observer. Do not treat a checkpoint digest as a distributed lock.

## External gates

Before activation, retain selected-host evidence for authentic current IANA tzdb,
DST cases, multi-scheduler races, crash/restart, restore/capacity, provider
identity, authority keys/revocation state and terminal observer. A distinct
acceptance principal must sign the final candidate. These gates remain false in
the implementation map until supplied.
