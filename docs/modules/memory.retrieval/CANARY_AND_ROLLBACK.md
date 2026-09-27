# Canary, promotion and rollback

This document specifies the release contract. It does not claim all four modes are wired into the binary. Implemented process selectors remain compatibility and HNMF-required; shadow and canary need a reviewed host dispatcher and mode-bound final-use receipts before activation.

## Four distinct modes

| Mode | Published context | Required behavior |
| --- | --- | --- |
| Compatibility | Existing baseline | No implicit HNMF dependency. |
| Shadow | Baseline only | Compute HNMF on the same authorized input cut; do not append shadow selections as actual exposure. Separate CPU/memory budgets and discard incomparable cuts. |
| Canary | Baseline or HNMF according to a pinned rollout policy | Cohort assignment must be deterministic, owner/body-bound, independently configured and recorded. Once HNMF is selected, failure must not silently switch arms. |
| Required | HNMF only | Current authenticated provider and all enabled owners required. Any freshness/authority failure rejects. |

Rollout identity must bind cohort allocation, policy/encoder/model/graph generations, risk stratum and response/final-use validation. Do not let a provider override a host's required-mode contract by reporting another mode. A new mode must be tested at the actual Agentd request and final-use boundaries, not merely added as an enum.

## Promotion gates

The change must be non-draft and approved at its current head by an independent human who is neither PR author nor source author/committer. Outstanding change requests block promotion. Require successful exact-source, source-head, base-merge and named target-host checks from their expected workflow paths and exact qualified source. Source-only map refresh commits may refer to an ancestor with identical declared code/qualification inputs; the emitted observation still binds the exact checkout.

Require all nine pipeline stages, ranker and durable learning sink in E2E qualification. Preapprove workload cases and numerical limits before measurement. Preserve raw samples, policy digest, host/allocator/SQLite instrumentation identity, process-wide resource accounting and actual failure dispositions. A validator pass or self-declared `producer=agentd-product` is not independent provenance.

## Rollback procedure

Stop new canary allocation through the protected rollout owner. Fence in-flight HNMF contexts using an advancing frontier. Publish the previously qualified policy/code combination as a new authorized generation, never by decreasing an epoch/sequence or copying an old cache. Start/revalidate the selected profile, verify deterministic cohort behavior and compare source receipts. If freshness cannot be established, required mode remains closed; compatibility is a deliberate host mode change, not hidden error recovery.

Retain incident, rollback, deployment and final-use receipts. Keep `productionImplementation`, `productExecutionProved`, `independentAcceptance`, `activation` and `release` false until their separate evidence exists. This implementation session cannot act as its own independent reviewer or external release authority.
