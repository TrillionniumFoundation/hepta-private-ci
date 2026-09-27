# Canary, promotion and rollback

Status: source-composed delivery candidate; native execution and independent rollout acceptance remain pending. Agentd parses all four selectors, wraps the provider in the real runtime composition and binds delivery mode, signed publication lifecycle and host-captured rollout policy into read/final-use identity. See `ROLLOUT_POLICY.md`, `ADR/0003-signed-lifecycle-delivery.md`, `ADR/0004-protected-rollout-and-shadow-budgets.md` and `PROCESS_BOOTSTRAP.md`.

## Four distinct modes

| Process selector | Published context | Implemented behavior and qualification boundary |
| --- | --- | --- |
| `compatibility` | Existing baseline | No implicit HNMF dependency; startup forbids an attached HNMF provider. |
| `hnmf-shadow` | Baseline only | Compute HNMF on the authorized owner cut when available. Never label shadow selection as delivered HNMF exposure. Shadow provider/computation/ledger failure does not substitute HNMF or reject baseline delivery. A separately pinned structural budget is checked before optional work. |
| `hnmf-canary` | Baseline or HNMF by versioned owner cohort | Bootstrap v1 preserves the historical fixed approximately 5% owner cohort. Bootstrap v2 uses a protected descriptor-pinned ppm threshold and nonzero cohort-generation salt. Selected owners fail closed like required; unselected owners follow bounded shadow. No request-supplied cohort override exists. |
| `hnmf-required` | HNMF only | Provider required at startup; freshness, lease, rollout-policy or authority failure rejects, never silently falls back. |

The mode, canary-policy version, threshold, salt, shadow ceilings and signed provider lifecycle are included in the routed lifecycle/read binding. Changing any of them invalidates old HNMF final-use receipts even when selected text and execution context payload are identical. Request code cannot use a provider's own mode report or request field to override the host wrapper.

Bootstrap v2 provides source-level configurable rollout ownership and structural non-delivery ceilings. It is not an approved rollout policy and does not isolate CPU, RSS, allocations, wall time or cancellation. Qualification of the ordinary-process bootstrap, protected launcher/filesystem, independently durable frontier and live canary/rollback measurements remain required. Do not treat the enum, descriptor schema, loader source, structural budget or in-process tests as a measured rollout.

## Cohort policy

Version 1 keeps the original owner hash and cutoff exactly so adopting this source cannot silently reshuffle an existing v1 cohort. Version 2 derives a deterministic 64-bit sample from the exact owner identity and descriptor salt and compares it with a 128-bit parts-per-million cutoff. `0` ppm selects no owners; `1000000` ppm selects all owners.

Changing a v2 salt is an explicit cohort-generation change. A threshold increase with the same salt preserves deterministic nesting; changing the salt intentionally creates another cohort. Either operation requires new descriptor bytes, a new independently approved raw-byte digest pin and a new process launch. Editing a live descriptor in place or reusing a digest for different bytes is forbidden.

## Promotion gates

The change must be non-draft and approved at its current head by an independent human who is neither PR author nor source author/committer. Outstanding change requests block promotion. Require successful exact-source, source-head, base-merge and named target-host checks from their expected workflow paths and exact qualified source. The synthetic merge uses the main commit fetched for that run, not a possibly stale PR event base. Source-only map refresh commits may refer to an ancestor with identical declared code/qualification inputs; the emitted observation still binds the exact checkout.

Require all nine pipeline stages, ranker and durable learning sink in E2E qualification. Preapprove workload cases and numerical limits before measurement. Preserve raw samples, policy digest, host/allocator/SQLite instrumentation identity, process-wide resource accounting and actual failure dispositions. `E2E_MEASUREMENT.md` specifies the v2 source-head/tree binding and conservative rate arithmetic. A validator pass or self-declared `producer=agentd-product` is not independent provenance. Actions retention and Git hashes are not independent WORM storage.

A recommended staged policy is v2 at 0 ppm with bounded shadow, then a small approved cohort, then independently reviewed increases and finally required mode. Every step must preserve the exact source/descriptor/policy identity and compare abstention, stale-context rejection, resource use and outcome quality against the baseline.

## Rollback procedure

Stop new canary allocation by launching an independently approved descriptor with a lower threshold or compatibility mode. Fence in-flight HNMF contexts using an advancing frontier. Publish the previously qualified policy/code combination as a new authorized generation, never by decreasing an epoch/sequence, copying an old cache or editing a descriptor beneath its digest. Start/revalidate the selected profile, verify deterministic cohort behavior and compare source receipts. If freshness cannot be established, required and selected-canary delivery remain closed; compatibility is a deliberate host mode change, not hidden error recovery.

Retain incident, rollback, descriptor, deployment and final-use receipts. Keep `productionImplementation`, `productExecutionProved`, `independentAcceptance`, `activation` and `release` false until their separate evidence exists. This implementation session cannot act as its own independent reviewer or external release authority.
