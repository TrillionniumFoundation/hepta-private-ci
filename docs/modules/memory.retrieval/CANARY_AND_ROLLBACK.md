# Canary, promotion and rollback

Status: source-composed delivery candidate; native execution and independent rollout acceptance remain pending. Agentd now parses all four selectors and wraps the provider in the real runtime composition. Read/final-use identities bind HNMF delivery mode and signed publication lifecycle. See `ADR/0003-signed-lifecycle-delivery.md` for the integration and its exclusions.

## Four distinct modes

| Process selector | Published context | Implemented behavior and qualification boundary |
| --- | --- | --- |
| `compatibility` | Existing baseline | No implicit HNMF dependency; startup forbids an attached HNMF provider. |
| `hnmf-shadow` | Baseline only | Compute HNMF on the authorized owner cut when available. Never label shadow selection as delivered HNMF exposure. Shadow provider/computation/ledger failure does not substitute HNMF or reject baseline delivery. |
| `hnmf-canary` | Baseline or HNMF by versioned owner cohort | The current source profile uses a stable approximately 5% owner hash cohort. Selected owners fail closed like required; unselected owners follow shadow. No request-supplied cohort override exists. |
| `hnmf-required` | HNMF only | Provider required at startup; freshness, lease or authority failure rejects, never silently falls back. |

The cohort policy and mode are included in HNMF lifecycle/read bindings; the signed publication independently binds owner and launched body generation. Different mode or publication invalidates old HNMF final-use receipts even when selected text is identical. Request code cannot use a provider's own mode report to override the host wrapper.

The fixed cohort is a source baseline, not an approved rollout policy. A protected configurable rollout owner, explicit shadow CPU/memory isolation, real process bootstrap and live canary/rollback measurements remain required before production activation. Shadow isolation currently covers result/exposure/failure semantics, not resource contention. Do not treat the new enum or in-process tests as a measured rollout.

## Promotion gates

The change must be non-draft and approved at its current head by an independent human who is neither PR author nor source author/committer. Outstanding change requests block promotion. Require successful exact-source, source-head, base-merge and named target-host checks from their expected workflow paths and exact qualified source. The synthetic merge uses the main commit fetched for that run, not a possibly stale PR event base. Source-only map refresh commits may refer to an ancestor with identical declared code/qualification inputs; the emitted observation still binds the exact checkout.

Require all nine pipeline stages, ranker and durable learning sink in E2E qualification. Preapprove workload cases and numerical limits before measurement. Preserve raw samples, policy digest, host/allocator/SQLite instrumentation identity, process-wide resource accounting and actual failure dispositions. A validator pass or self-declared `producer=agentd-product` is not independent provenance. Actions retention and Git hashes are not independent WORM storage.

## Rollback procedure

Stop new canary allocation through the protected rollout owner once that owner is composed and qualified. Fence in-flight HNMF contexts using an advancing frontier. Publish the previously qualified policy/code combination as a new authorized generation, never by decreasing an epoch/sequence or copying an old cache. Start/revalidate the selected profile, verify deterministic cohort behavior and compare source receipts. If freshness cannot be established, required mode remains closed; compatibility is a deliberate host mode change, not hidden error recovery.

Retain incident, rollback, deployment and final-use receipts. Keep `productionImplementation`, `productExecutionProved`, `independentAcceptance`, `activation` and `release` false until their separate evidence exists. This implementation session cannot act as its own independent reviewer or external release authority.
